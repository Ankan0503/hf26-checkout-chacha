"""Facts and verdicts. Plain rules on purpose: every verdict can be explained with numbers.

The language model never decides the mood. It only gets to word it.
"""
import re
from datetime import datetime, timedelta

# (category, is it a need?, pattern). First match wins, so needs come first.
CATEGORIES = [
    ("books & study", True, r"\bbooks?\b|paperback|hardcover|hardback|\bnovel\b|notebook|textbook|stationery|\bpens?\b|pencil|calculator|\bguide\b|edition"),
    ("groceries", True, r"\batta\b|\brice\b|\bdal\b|cooking oil|\bghee\b|sugar|\bsalt\b|\bmilk\b|\btea\b|grocery|masala"),
    ("health", True, r"medicine|capsule|syrup|sanitizer|\bmasks?\b|bandage|thermometer|vitamin|first aid"),
    ("essentials", True, r"toothpaste|\bsoap\b|shampoo|detergent|toilet|bucket|bedsheet|charging cable"),
    ("gaming", False, r"controller|gamepad|\bps[45]\b|playstation|xbox|nintendo|gaming|joystick"),
    ("audio", False, r"headphone|headset|earphone|earbuds|\btws\b|neckband|speaker|soundbar|airdopes|\bbuds\b|bassheads|in-?ear"),
    ("gadgets", False, r"keyboard|\bmouse\b|smart ?watch|\bwatch\b|\btablet\b|ipad|phone case|power ?bank|camera|drone|led strip|\brgb\b"),
    ("fashion", False, r"t-?shirt|\bshirt\b|jeans|hoodie|jacket|sneakers?|\bshoes?\b|kurta|dress|sunglass|perfume|\bcap\b|wallet"),
]
OTHER = "other stuff"
COOLDOWN_HOURS = 24

# Which roast reason leads when several apply: the most damning first.
PRIORITY = ["forecast", "over_budget", "regret", "repeat", "late_night", "spree", "big_ticket"]


def categorize(title: str | None) -> tuple[str, bool]:
    t = (title or "").lower()
    for name, need, pattern in CATEGORIES:
        if re.search(pattern, t):
            return name, need
    return OTHER, False


def inr(x: float) -> str:
    """₹1,23,456, with Indian digit grouping."""
    n = int(round(x))
    s = str(abs(n))
    if len(s) > 3:
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", s[:-3])
        s = f"{head},{s[-3:]}"
    return ("-₹" if n < 0 else "₹") + s


def short(title: str | None, words: int = 5) -> str:
    if not title:
        return "this"
    parts = title.split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def facts(event: str, title: str | None, price: float | None, cart_total: float | None,
          history: list[dict], settings: dict, now: datetime | None = None) -> dict:
    """Everything Chacha is allowed to say, as numbers and short strings."""
    now = now or datetime.now()
    category, need = categorize(title)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    fun_budget = float(settings["fun_budget"])
    fun_spent = sum(
        h["price"] or 0 for h in history
        if h["decision"] == "buy" and not h["need"] and h["ts"] >= month_start.timestamp()
    )
    fun_left = fun_budget - fun_spent

    # Distinct things added to the cart today, counting this one.
    added = {h["title"] for h in history if h["event"] == "add_to_cart" and h["ts"] >= day_start.timestamp()}
    if event == "add_to_cart" and title:
        added.add(title)

    # A different thing from the same category, added or bought in the last 60 days.
    repeat_days = None
    if not need and category != OTHER:
        same = [
            h for h in history
            if h["category"] == category and h["title"] != title and h["decision"] != "removed"
            and (h["event"] == "add_to_cart" or h["decision"] == "buy")
            and h["ts"] >= (now - timedelta(days=60)).timestamp()
        ]
        if same:
            repeat_days = max(1, (now - datetime.fromtimestamp(same[-1]["ts"])).days)

    # Put on the wishlist with "Sleep on it" earlier?
    waited_hours = None
    slept = [h for h in history if title and h["title"] == title and h["decision"] == "sleep" and h["decided_at"]]
    if slept:
        waited_hours = int((now.timestamp() - slept[-1]["decided_at"]) // 3600)

    hourly = float(settings.get("hourly_income") or 0)
    wants_price = bool(price) and not need

    return {
        "event": event,
        "title": short(title),
        "item": (title or "")[:90],  # Longer name for Gemma, so "Controller" isn't cut off.
        "price": price,
        "category": category,
        "need": need,
        "time": now.strftime("%I:%M %p").lstrip("0"),
        "late_night": 0 <= now.hour < 5,
        "adds_today": len(added),
        "repeat_days": repeat_days,
        "repeat_when": None if repeat_days is None else f"{repeat_days} day{'s' if repeat_days != 1 else ''} ago",
        "waited_hours": waited_hours,
        "fun_budget": fun_budget,
        "fun_spent": fun_spent,
        "fun_left": fun_left,
        "fun_left_after": fun_left - (price or 0),
        "days_left": (next_month - now).days,
        "over_budget": wants_price and price > fun_left,
        "big_ticket": wants_price and price >= float(settings["big_ticket"]),
        "hours_of_work": round(price / hourly) if price and hourly > 0 else None,
        "cart_total": cart_total,
        "cooldown_hours": COOLDOWN_HOURS,
        # Filled in once a bank statement is loaded (TabPFN).
        "regret_pct": None,
        "runs_out_day": None,
    }


def verdict(f: dict) -> tuple[str, int, list[str]]:
    """(mood, spice level 0–3, reasons). Reasons are listed most damning first."""
    if f["event"] == "cart_view":
        total = f["cart_total"]
        if not total:
            return "info", 0, ["no_total"]
        if total > f["fun_left"]:
            return "roast", 2 if total > 2 * max(f["fun_left"], 1) else 1, ["cart_over_budget"]
        return "normal", 1, ["cart_ok"]

    if not f["price"]:
        return "info", 0, ["no_price"]
    if f["waited_hours"] is not None and f["waited_hours"] >= COOLDOWN_HOURS:
        return "praise", 1, ["waited"]
    if f["need"]:
        return "praise", 1, ["need"]

    hits = {
        "forecast": bool(f["runs_out_day"]),
        "over_budget": f["over_budget"],
        "regret": (f["regret_pct"] or 0) >= 60,
        "repeat": f["repeat_days"] is not None,
        "late_night": f["late_night"],
        "spree": f["event"] == "add_to_cart" and f["adds_today"] >= 3,
        "big_ticket": f["big_ticket"],
    }
    reasons = [r for r in PRIORITY if hits[r]]
    if not reasons:
        return "normal", 1, []
    return "roast", min(3, len(reasons)), reasons


def fact_lines(f: dict, reasons: list[str]) -> list[str]:
    """The two to four numbers shown under the line on the card."""
    out = []
    if f["price"]:
        out.append(f"{inr(f['price'])} · {f['category']} ({'a need' if f['need'] else 'a want'})")
    if f["cart_total"]:
        out.append(f"Cart total {inr(f['cart_total'])}")
    if not f["need"]:
        out.append(f"Fun budget: {inr(max(f['fun_left'], 0))} left of {inr(f['fun_budget'])}, {f['days_left']} days to go")
    if "repeat" in reasons:
        out.append(f"Last {f['category']} thing added: {f['repeat_when']}")
    if "spree" in reasons:
        out.append(f"Thing number {f['adds_today']} added today")
    if "late_night" in reasons:
        out.append(f"It's {f['time']}")
    if f["hours_of_work"]:
        out.append(f"That's {f['hours_of_work']} hours of your work")
    # Statement facts lead when they're the reason; they're what makes the verdict personal.
    if f.get("runs_out_day"):
        out.insert(1, f"Buy this and your money runs out on day {f['runs_out_day']}")
    if f.get("regret_pct") is not None:
        out.insert(1, f"Regret chance (TabPFN, from your labels): {f['regret_pct']}%")
    if f.get("food_delivery_month") and not f["need"]:
        out.append(f"Swiggy + Zomato in {f['food_delivery_month_name']}: {inr(f['food_delivery_month'])}")
    return out[:4]
