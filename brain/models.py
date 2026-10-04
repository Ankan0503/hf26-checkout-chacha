"""TabPFN, running locally on this laptop's CPU, does two jobs.

1. Regret. You mark ~40 past purchases from your statement "worth it" or
   "regret". TabPFN is a foundation model for small tables: it reads those rows
   as context and predicts for a new one in a single forward pass. No training
   run, no hyperparameters, and it works with 40 rows, which is the whole point.

2. Forecast. From your daily spending, it predicts each remaining day of the
   month, so Chacha can say the day your balance would hit zero, with and
   without the thing in your cart.

The weights are TabPFN-2's, under the Prior Labs License (Apache 2.0 plus
attribution). The newer weights are non-commercial and need an account; for a
project whose argument is "open", that difference decided it.
"""
import math
import os
import statistics
import threading
from datetime import date, timedelta

from .statement import Txn

os.environ.setdefault("TABPFN_NO_BROWSER", "1")  # Never open a login page.

MIN_LABELS = 12  # With fewer, or with only one kind of label, a regret % would be noise.
PAYDAY_MIN = 5000  # A credit this big is a payday (pocket money, salary, stipend).

CATEGORIES = [
    "food delivery", "groceries", "subscriptions", "shopping", "fun", "travel",
    "bills", "health", "education", "eating out", "transfers", "other",
]
REGRET_FEATURES = [
    "amount", "log amount", "amount vs your median", "category", "weekday",
    "day of month", "days since payday", "spent in last 7 days", "same category in last 7 days",
]
FORECAST_FEATURES = ["day of month", "weekday", "weekend", "days since payday"]

_lock = threading.Lock()  # TabPFN on CPU is happiest one call at a time.
_regret_cache: dict = {"key": None, "model": None}


def _version():
    from tabpfn.constants import ModelVersion
    return ModelVersion.V2


def _classifier():
    from tabpfn import TabPFNClassifier
    return TabPFNClassifier.create_default_for_version(
        _version(), device="cpu", categorical_features_indices=[REGRET_FEATURES.index("category")]
    )


def _regressor():
    from tabpfn import TabPFNRegressor
    return TabPFNRegressor.create_default_for_version(_version(), device="cpu")


# --- Features ----------------------------------------------------------------

def _paydays(txns: list[Txn]) -> list[date]:
    return [t.day for t in txns if t.inn >= PAYDAY_MIN]


def _days_since_payday(day: date, paydays: list[date]) -> int:
    before = [p for p in paydays if p <= day]
    return (day - before[-1]).days if before else 15


def regret_row(amount: float, category: str, day: date, txns: list[Txn]) -> list[float]:
    """One purchase as numbers, using only what happened before it."""
    earlier = [t for t in txns if t.day <= day and t.out]
    week = [t for t in earlier if (day - t.day).days < 7]
    median = statistics.median([t.out for t in earlier]) if earlier else 300.0
    return [
        amount,
        math.log1p(amount),
        amount / max(median, 1.0),
        CATEGORIES.index(category) if category in CATEGORIES else CATEGORIES.index("other"),
        day.weekday(),
        day.day,
        _days_since_payday(day, _paydays(txns)),
        sum(t.out for t in week),
        sum(1 for t in week if t.category == category),
    ]


# --- Regret ------------------------------------------------------------------

def regret_pct(txns: list[Txn], labels: dict[int, int], amount: float, category: str, day: date) -> int | None:
    """Chance, 0–100, that you'd regret spending `amount` on `category` today. None if not enough labels."""
    labelled = [(i, y) for i, y in labels.items() if 0 <= i < len(txns) and txns[i].out]
    ys = [y for _, y in labelled]
    if len(labelled) < MIN_LABELS or len(set(ys)) < 2:
        return None
    key = tuple(sorted(labelled)) + (len(txns),)
    with _lock:
        if _regret_cache["key"] != key:
            X = [regret_row(txns[i].out, txns[i].category, txns[i].day, txns[:i]) for i, _ in labelled]
            model = _classifier()
            model.fit(X, ys)
            _regret_cache.update(key=key, model=model)
        proba = _regret_cache["model"].predict_proba([regret_row(amount, category, day, txns)])[0]
    classes = list(_regret_cache["model"].classes_)
    return round(100 * proba[classes.index(1)])


# --- Forecast ----------------------------------------------------------------

def _daily(txns: list[Txn]) -> dict[date, float]:
    first, last = txns[0].day, txns[-1].day
    spend = {first + timedelta(days=n): 0.0 for n in range((last - first).days + 1)}
    for t in txns:
        spend[t.day] += t.out  # Cash withdrawals count: the cash gets spent too.
    return spend


def _forecast_row(day: date, paydays: list[date]) -> list[float]:
    return [day.day, day.weekday(), int(day.weekday() >= 5), _days_since_payday(day, paydays)]


def forecast(txns: list[Txn]) -> dict:
    """Predicted spending for each remaining day of the statement's last month."""
    daily = _daily(txns)
    paydays = _paydays(txns)
    X = [_forecast_row(d, paydays) for d in daily]
    y = list(daily.values())
    last = txns[-1].day
    month_end = (last.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    future = [last + timedelta(days=n) for n in range(1, (month_end - last).days + 1)]
    predicted = []
    if future:
        with _lock:
            model = _regressor()
            model.fit(X, y)
            predicted = [max(0.0, float(p)) for p in model.predict([_forecast_row(d, paydays) for d in future])]
    balance = next((t.balance for t in reversed(txns) if t.balance is not None), None)
    return {
        "as_of": last.isoformat(),
        "balance": balance,
        "days": [(d.isoformat(), round(p, 2)) for d, p in zip(future, predicted)],
        "month_spend_so_far": round(sum(v for d, v in daily.items() if d.month == last.month and d.year == last.year), 2),
    }


def runs_out_day(fc: dict | None, extra: float = 0.0) -> int | None:
    """Day of the month the balance would go below zero, after spending `extra` now. None if it won't."""
    if not fc or fc.get("balance") is None:
        return None
    balance = fc["balance"] - extra
    if balance < 0:
        return date.fromisoformat(fc["as_of"]).day
    for day, spend in fc["days"]:
        balance -= spend
        if balance < 0:
            return date.fromisoformat(day).day
    return None


def month_end_balance(fc: dict | None, extra: float = 0.0) -> float | None:
    if not fc or fc.get("balance") is None:
        return None
    return round(fc["balance"] - extra - sum(spend for _, spend in fc["days"]), 2)
