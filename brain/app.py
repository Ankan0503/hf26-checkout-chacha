"""Checkout Chacha's brain. Runs on your laptop; the phone talks to it over your own Wi-Fi."""
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import judge, models, screen, statement, store, voice

DASHBOARD = Path(__file__).resolve().parent / "dashboard" / "index.html"
SAMPLE = store.DATA / "sample"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    voice.warm_up()
    yield


app = FastAPI(title="Checkout Chacha", docs_url=None, redoc_url=None, lifespan=lifespan)
CODE = store.pairing_code()
DUMPS = store.DATA / "dumps"
KEEP_DUMPS = 120

TITLES = {
    "roast": "Chacha says no",
    "normal": "Chacha shrugs",
    "praise": "Chacha approves",
    "info": "Chacha",
}


class Line(BaseModel):
    t: str
    y: int = 0
    h: int = 0
    c: bool = False
    v: bool = True  # False for text scrolled out of view


class Seen(BaseModel):
    app: str
    event: str  # add_to_cart | cart_view | manual | dump | trace
    clicked: str | None = None
    ts: float | None = None
    texts: list[Line] = []


QUIET = {"quiet": True}


class Decision(BaseModel):
    decision: str  # removed | sleep | buy
    verdict_id: str


def paired(token: str | None) -> bool:
    return (token or "").strip().upper() == CODE


def require_pairing(token: str | None) -> None:
    if not paired(token):
        raise HTTPException(status_code=401, detail="wrong pairing code")


def keep_dump(seen: Seen) -> None:
    """Raw screens, kept on this laptop only, to tune screen.py against what the apps really show.

    Traces (every settled screen, debug mode only) go in their own folder so they
    can't push out the screens that produced verdicts.
    """
    folder = DUMPS / "trace" if seen.event == "trace" else DUMPS
    folder.mkdir(parents=True, exist_ok=True)
    now = time.time()
    name = f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(now))}.{int(now * 1000) % 1000:03d}-{seen.event}.json"
    (folder / name).write_text(json.dumps(seen.model_dump(), ensure_ascii=False, indent=1), encoding="utf-8")
    for old in sorted(folder.glob("*.json"))[:-KEEP_DUMPS]:
        old.unlink()


@app.get("/v1/health")
def health(x_chacha_token: str | None = Header(default=None)):
    return {"ok": True, "name": "Checkout Chacha", "paired": paired(x_chacha_token)}


@app.post("/v1/see")
def see(seen: Seen, x_chacha_token: str | None = Header(default=None)):
    require_pairing(x_chacha_token)
    keep_dump(seen)
    lines = [line.model_dump() for line in seen.texts]

    if seen.event == "trace":
        return QUIET
    if seen.event == "dump":
        return {
            "id": "", "mood": "info", "title": "Saved on your laptop",
            "line": f"{len(lines)} lines saved for debugging.", "facts": [], "actionable": False,
        }

    # Tapping the orb on the cart page asks about the whole cart.
    total = screen.cart_total(lines) if seen.event in ("cart_view", "manual") else None
    event = "cart_view" if total is not None else seen.event
    if event == "cart_view":
        title, price = None, None
    else:
        title, price = screen.product(lines)

    # Automatic checks stay silent when they find nothing; only a tap gets an answer.
    if seen.event in ("cart_view", "add_to_cart") and not (total or price):
        return QUIET
    # A tap on the home page or search results would judge a random banner.
    if seen.event == "manual" and event != "cart_view" and not screen.is_product_page(lines):
        return {
            "id": "", "mood": "info", "title": "Chacha",
            "line": "Open a product or your cart, then tap me.", "facts": [], "actionable": False,
        }

    db = store.connect()
    try:
        cfg = store.settings(db)
        history = store.since(db, time.time() - 62 * 86400)
        f = judge.facts(event, title, price, total, history, cfg)
        f.update(money_facts(db, price or total, f["need"]))
        mood, level, reasons = judge.verdict(f)
        text, source = voice.line(mood, level, reasons, f, cfg)
        verdict_id = uuid.uuid4().hex[:12]
        if mood != "info":
            store.save_verdict(db, {
                "id": verdict_id, "ts": time.time(), "app": seen.app, "event": event,
                "title": title, "price": price, "category": f["category"], "need": f["need"],
                "mood": mood, "level": level, "line": text, "facts": f,
            })
    finally:
        db.close()

    title_text = TITLES[mood] + (" " + "🌶" * level if mood == "roast" else "")
    return {
        "id": verdict_id,
        "mood": mood,
        "level": level,
        "title": title_text,
        "line": text,
        "facts": judge.fact_lines(f, reasons),
        "item": {"title": title, "price": price},
        "cart_total": total,
        "actionable": mood in ("roast", "normal") and event != "cart_view",
        # Opening a cart that's fine just turns the orb blue; a card only when there's something to say.
        "card": not (seen.event == "cart_view" and mood != "roast"),
        "reasons": reasons,
        "source": source,
    }


def money_facts(db, spend: float | None, need: bool) -> dict:
    """What the bank statement adds to a verdict. Empty until a statement is loaded."""
    txns = store.load_statement(db)
    if not txns or not spend:
        return {}
    fc = store.cache_get(db, "forecast")
    last = txns[-1].day
    food = [t for t in txns if t.category == "food delivery" and t.out]
    # This month if it has started properly, otherwise last month.
    month = last if last.day >= 15 else last.replace(day=1) - timedelta(days=1)
    food_month = sum(t.out for t in food if (t.day.year, t.day.month) == (month.year, month.month))
    subs = [s for s in statement.subscriptions(txns) if s["category"] == "subscriptions"]
    out = {
        "balance": fc["balance"] if fc else None,
        "food_delivery_month": round(food_month) or None,
        "food_delivery_month_name": month.strftime("%B"),
        "subscriptions_monthly": round(sum(s["amount"] for s in subs)) or None,
        "subscriptions_count": len(subs) or None,
    }
    if not need:
        before, after = models.runs_out_day(fc), models.runs_out_day(fc, spend)
        # Only a reason if this purchase is what makes the money run out, or run out sooner.
        if after is not None and (before is None or after < before):
            out["runs_out_day"] = after
        out["month_end_after"] = models.month_end_balance(fc, spend)
        out["regret_pct"] = models.regret_pct(txns, store.labels(db), spend, "shopping", date.today())
    return out


@app.post("/v1/feedback")
def feedback(d: Decision, x_chacha_token: str | None = Header(default=None)):
    require_pairing(x_chacha_token)
    if d.decision not in ("removed", "sleep", "buy"):
        raise HTTPException(status_code=400, detail="unknown decision")
    db = store.connect()
    try:
        return {"ok": store.decide(db, d.verdict_id, d.decision)}
    finally:
        db.close()


# --- The dashboard -----------------------------------------------------------

class Label(BaseModel):
    txn_id: int
    regret: int | None  # 1 regret, 0 worth it, None to clear


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    """Only for this laptop: the page carries the pairing code."""
    if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(status_code=403, detail="The dashboard only opens on the laptop running Chacha.")
    return DASHBOARD.read_text(encoding="utf-8").replace("{{CODE}}", CODE)


def _load_statement(db, raw: bytes) -> dict:
    try:
        txns = statement.parse(raw)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    store.save_statement(db, txns)
    started = time.time()
    store.cache_put(db, "forecast", models.forecast(txns))
    return {"transactions": len(txns), "forecast_seconds": round(time.time() - started, 1)}


@app.post("/v1/statement")
async def upload_statement(file: UploadFile = File(...), x_chacha_token: str | None = Header(default=None)):
    require_pairing(x_chacha_token)
    raw = await file.read()
    db = store.connect()
    try:
        return _load_statement(db, raw)
    finally:
        db.close()


@app.post("/v1/statement/sample")
def load_sample(x_chacha_token: str | None = Header(default=None)):
    """The made-up student from scripts/make_sample_statement.py, with their labels. For demos."""
    require_pairing(x_chacha_token)
    db = store.connect()
    try:
        result = _load_statement(db, (SAMPLE / "statement.csv").read_bytes())
        labels_file = SAMPLE / "labels.json"
        if labels_file.exists():
            for txn_id, regret in json.loads(labels_file.read_text()).items():
                store.set_label(db, int(txn_id), regret)
        return result
    finally:
        db.close()


@app.get("/v1/summary")
def summary(x_chacha_token: str | None = Header(default=None)):
    require_pairing(x_chacha_token)
    db = store.connect()
    try:
        txns = store.load_statement(db)
        fc = store.cache_get(db, "forecast")
        labels = store.labels(db)
        verdicts = store.since(db, 0)
        by_month: dict[str, float] = {}
        for t in txns:
            if t.category == "food delivery":
                key = t.day.strftime("%b %Y")
                by_month[key] = by_month.get(key, 0) + t.out
        return {
            "settings": store.settings(db),
            "statement": {
                "transactions": len(txns),
                "from": txns[0].day.isoformat() if txns else None,
                "to": txns[-1].day.isoformat() if txns else None,
                "balance": fc["balance"] if fc else None,
                "month_spend_so_far": fc["month_spend_so_far"] if fc else None,
                "month_end_balance": models.month_end_balance(fc),
                "runs_out_day": models.runs_out_day(fc),
                "food_delivery_by_month": {k: round(v) for k, v in by_month.items()},
                "subscriptions": statement.subscriptions(txns),
            } if txns else None,
            "labels": {
                "total": len(labels),
                "regret": sum(labels.values()),
                "needed": models.MIN_LABELS,
                "ready": len(labels) >= models.MIN_LABELS and 0 < sum(labels.values()) < len(labels),
            },
            "record": {
                "verdicts": len(verdicts),
                "roasts": sum(1 for v in verdicts if v["mood"] == "roast"),
                "saved": round(sum(v["price"] or 0 for v in verdicts if v["decision"] == "removed")),
                "sleeping": [
                    {"title": v["title"], "price": v["price"]} for v in verdicts if v["decision"] == "sleep"
                ],
                "recent": [
                    {"mood": v["mood"], "line": v["line"], "price": v["price"], "decision": v["decision"]}
                    for v in sorted(verdicts, key=lambda v: -v["ts"])[:8]
                ],
            },
        }
    finally:
        db.close()


@app.get("/v1/transactions")
def transactions(x_chacha_token: str | None = Header(default=None)):
    """Money going out, newest first, for labelling."""
    require_pairing(x_chacha_token)
    db = store.connect()
    try:
        labels = store.labels(db)
        rows = [
            {"id": i, "day": t.day.isoformat(), "merchant": t.merchant, "category": t.category,
             "amount": t.out, "label": labels.get(i)}
            for i, t in enumerate(store.load_statement(db)) if t.out and t.category != "transfers"
        ]
        return list(reversed(rows))
    finally:
        db.close()


@app.post("/v1/labels")
def label(item: Label, x_chacha_token: str | None = Header(default=None)):
    require_pairing(x_chacha_token)
    db = store.connect()
    try:
        store.set_label(db, item.txn_id, item.regret)
        return {"ok": True, "total": len(store.labels(db))}
    finally:
        db.close()


@app.post("/v1/settings")
def update_settings(changes: dict, x_chacha_token: str | None = Header(default=None)):
    require_pairing(x_chacha_token)
    db = store.connect()
    try:
        for key, value in changes.items():
            if key in store.DEFAULTS:
                store.put_setting(db, key, value)
        return store.settings(db)
    finally:
        db.close()


@app.post("/v1/wipe")
def wipe(x_chacha_token: str | None = Header(default=None)):
    """Delete all my data."""
    require_pairing(x_chacha_token)
    store.wipe()
    return {"ok": True}
