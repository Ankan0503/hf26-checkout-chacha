"""Chacha's one line.

Gemma 4, running locally through Ollama, writes it. The rules in judge.py have
already decided the mood; Gemma only gets to word it, from the facts it's handed.

Then two guards run. The fact guard: every number in the line must appear in
the facts. The tone guard: the line may mock the purchase, not the person. A
line that fails either is thrown away and Gemma gets one more try; after that, a
template line is used. Chacha may be rude. Chacha may not lie.

Every attempt is logged to data/voice-log.jsonl: how long it took, and what
each guard caught.
"""
import json
import os
import re
import threading
import time
import urllib.request

from .judge import PRIORITY, inr
from .store import DATA

OLLAMA = os.environ.get("CHACHA_OLLAMA", "http://127.0.0.1:11434")
MODEL = os.environ.get("CHACHA_MODEL", "gemma4:e2b")
TIMEOUT_S = 20  # Past this the orb would feel broken; a template line is better than a wait.
KEEP_LOADED = "2h"
LOG = DATA / "voice-log.jsonl"

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

SYSTEM = """You are Checkout Chacha: a funny, blunt Indian uncle who lives inside a shopping app and watches what the user is about to buy.
Reply with ONE line of at most 25 words, spoken to the user as "you".
Rules:
- Use only numbers that appear in FACTS, written exactly as given. Never invent a number, date, price or percentage.
- If a number from FACTS makes the joke land harder, use one.
- Name the item the way a person would ("a controller", "earphones"), not the full product title.
- Don't start with "You are buying". Vary how you open.
- Mock the purchase, never the person.
- No hashtags. Emoji optional, at most one.
- This is banter, not financial advice.
The style, for flavour only (never reuse their wording):
Controller again? Your thumbs need rest, beta, not a new toy.
Books? Finally, something your future self will thank you for.
Arre, more earphones? Do you have extra ears I don't know about?"""

LANGUAGE = {
    "en": "Write in simple, punchy English.",
    "hinglish": "Write in Hinglish: casual Hindi in Latin letters mixed with English, like an uncle texting on WhatsApp.",
}

TONE = {
    "roast": {
        1: "Tease gently.",
        2: "Roast honestly, with a punchline.",
        3: "Roast hard and dramatically. Be savage about the purchase.",
    },
    "normal": "Shrug: it's fine, mildly approving. Mention what's left.",
    "praise": "Praise warmly, like a proud uncle.",
}

# What each reason means, in words Gemma can use.
REASONS = {
    "forecast": "at this rate the money runs out on day {runs_out_day} of the month",
    "over_budget": "it costs more than the fun budget left ({fun_left})",
    "regret": "the user regrets purchases like this {regret_pct}% of the time",
    "repeat": "they added another {category} item to the cart {repeat_when}",
    "late_night": "it is {time}, late at night",
    "spree": "this is thing number {adds_today} added to the cart today",
    "big_ticket": "it is a big purchase",
    "cart_over_budget": "the cart total {cart_total} is more than the fun budget left ({fun_left})",
    "cart_ok": "the cart total {cart_total} fits within the fun budget",
    "need": "it's a need ({category}), not a want",
    "waited": "they waited {waited_hours} hours before buying it, so it's not an impulse buy",
}

TEMPLATES = {
    "en": {
        "forecast": "{price} now, and your money runs out on day {runs_out_day}.",
        "over_budget": "{price}, and your fun budget has {fun_left} left. The maths says no.",
        "regret": "You regret buys like this {regret_pct}% of the time. Just saying.",
        "repeat": "More {category}? You added some to your cart {repeat_when}.",
        "late_night": "{price} at {time}? Nothing good gets bought after midnight. Sleep on it.",
        "spree": "That's thing number {adds_today} today. Chacha is getting worried.",
        "big_ticket": "{price} for {title}? That's a big one. Sleep on it for {cooldown_hours} hours.",
        "cart_over_budget": "Cart total {cart_total}, fun budget left {fun_left}. Something has to go.",
        "cart_ok": "Cart total {cart_total}. Within budget. Chacha allows it.",
        "normal": "{price}. Fine. {fun_left_after} of your fun budget left after this.",
        "need": "{title}? That's a need, not a want. Respect.",
        "waited": "You waited {waited_hours} hours for this. Not an impulse buy. Enjoy it.",
        "no_price": "I can't find a price here. Tap me on a product page or your cart.",
        "no_total": "I can't find the cart total on this screen.",
    },
    "hinglish": {
        "forecast": "{price} abhi, aur {runs_out_day} tareekh ko paise khatam.",
        "over_budget": "{price}? Fun budget mein sirf {fun_left} bacha hai. Bas kar.",
        "regret": "Aisi cheezon pe {regret_pct}% baar pachtaata hai tu. Soch le.",
        "repeat": "Phir se {category}? {repeat_days} din pehle hi cart mein daala tha.",
        "late_night": "Raat ke {time} baje {price}? Bas kar. Kal subah sochna.",
        "spree": "Aaj ki cheez number {adds_today}. Bas kar beta.",
        "big_ticket": "{price} for {title}? Itna bada kharcha? {cooldown_hours} ghante ruk ja.",
        "cart_over_budget": "Cart {cart_total} ka hai, budget mein {fun_left} bacha. Kuch hatao.",
        "cart_ok": "Cart {cart_total} ka. Budget mein hai. Chal, le le.",
        "normal": "{price}. Theek hai. Iske baad {fun_left_after} bachega.",
        "need": "{title}? Zaroori cheez hai. Shabash.",
        "waited": "{waited_hours} ghante ruka, ab le le. Shabash.",
        "no_price": "Yahan price nahi dikh raha. Product page ya cart pe tap kar.",
        "no_total": "Is screen pe cart total nahi mila.",
    },
}


# --- The fact guard ----------------------------------------------------------

def _norm(number: str) -> str:
    v = float(number.replace(",", ""))
    return str(int(v)) if v == int(v) else f"{v:g}"


def numbers_in(text: str) -> set[str]:
    return {_norm(n) for n in NUMBER.findall(text)}


def allowed_numbers(facts: dict) -> set[str]:
    out = set()
    for value in facts.values():
        if value is None or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            out |= {_norm(str(abs(value))), _norm(str(abs(round(value))))}
        elif isinstance(value, str):
            out |= numbers_in(value)
    return out


def invented(line: str, facts: dict) -> set[str]:
    """Numbers in the line that the facts don't back up. Empty means the line is honest."""
    return numbers_in(line) - allowed_numbers(facts)


# Roast the purchase, never the person. Small models drift into name-calling at "savage".
INSULT = re.compile(
    r"(?i)\b(fool|idiot|stupid|dumb|moron|loser|useless|pathetic|worthless|ugly|fat|bewakoof|pagal|gadha|ullu)\b"
)


def insults(line: str) -> set[str]:
    return {m.group(0).lower() for m in INSULT.finditer(line)}


# --- Templates ---------------------------------------------------------------

def _money(f: dict) -> dict:
    """The facts with every rupee amount written the way people read it: ₹1,23,456."""
    out = dict(f)
    for key in ("fun_left", "fun_left_after"):
        if f.get(key) is not None:
            out[key] = inr(max(f[key], 0))
    for key in ("price", "cart_total", "fun_budget"):
        if f.get(key):
            out[key] = inr(f[key])
    return out


def _key(mood: str, reasons: list[str]) -> str:
    if mood == "roast":
        return next((r for r in PRIORITY + ["cart_over_budget"] if r in reasons), "big_ticket")
    if mood == "normal":
        return "cart_ok" if "cart_ok" in reasons else "normal"
    return reasons[0] if reasons else "no_price"


def template_line(mood: str, reasons: list[str], f: dict, language: str) -> str:
    table = TEMPLATES.get(language, TEMPLATES["en"])
    return table[_key(mood, reasons)].format(**_money(f))


# --- Gemma -------------------------------------------------------------------

def _prompt(mood: str, level: int, reasons: list[str], f: dict) -> str:
    m = _money(f)
    facts = []
    if f["item"]:
        facts.append(f"item: {f['item']}")
    if f["price"]:
        facts.append(f"price: {m['price']}")
        facts.append(f"category: {f['category']} ({'a need' if f['need'] else 'a want'})")
    if f["cart_total"]:
        facts.append(f"cart total: {m['cart_total']}")
    if not f["need"]:
        facts.append(f"fun budget left this month: {m['fun_left']} of {m['fun_budget']}")
        if f["price"] and mood != "roast":
            facts.append(f"fun budget left after this: {m['fun_left_after']}")
        facts.append(f"days left this month: {f['days_left']}")
    if f["hours_of_work"]:
        facts.append(f"that is {f['hours_of_work']} hours of the user's work")
    # From the bank statement, when one is loaded.
    if f.get("food_delivery_month"):
        facts.append(f"spent on Swiggy and Zomato in {f['food_delivery_month_name']}: {inr(f['food_delivery_month'])}")
    if f.get("subscriptions_count"):
        facts.append(f"pays for {f['subscriptions_count']} streaming subscriptions: {inr(f['subscriptions_monthly'])} a month")
    if f.get("runs_out_day"):
        facts.append(f"if they buy this, their money runs out on day {f['runs_out_day']} of the month")
    if f.get("regret_pct") is not None:
        facts.append(f"chance they'll regret it, learned from their own past purchases: {f['regret_pct']}%")
    why = [REASONS[r].format(**m) for r in reasons if r in REASONS]
    tone = TONE[mood][max(1, min(level, 3))] if mood == "roast" else TONE[mood]
    return (
        f"VERDICT: {mood}. {tone}\n"
        + (f"WHY: {'; '.join(why)}\n" if why else "")
        + "FACTS:\n- " + "\n- ".join(facts)
        + "\nWrite Chacha's one line."
    )


def _clean(text: str) -> str:
    first = next((ln for ln in text.strip().splitlines() if ln.strip()), "")
    return first.strip().strip('"“”').strip()[:240]


def _ask_gemma(system: str, prompt: str, timeout: float, max_tokens: int = 80) -> dict:
    body = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "keep_alive": KEEP_LOADED,
        "options": {"temperature": 0.9, "num_predict": max_tokens},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _log(entry: dict) -> None:
    DATA.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def warm_up() -> None:
    """Load Gemma into memory in the background, so the first roast doesn't wait for the disk."""
    def run():
        try:
            _ask_gemma("Reply with OK.", "OK?", timeout=300, max_tokens=1)
        except OSError:
            pass  # Ollama isn't running; templates will be used.
    threading.Thread(target=run, daemon=True).start()


def line(mood: str, level: int, reasons: list[str], f: dict, settings: dict) -> tuple[str, str]:
    """(line, source). Source says who wrote it: 'gemma' or 'template'."""
    language = settings.get("language", "en")
    if mood in TONE and settings.get("use_gemma", True):
        system = SYSTEM + "\n" + LANGUAGE.get(language, LANGUAGE["en"])
        prompt = _prompt(mood, level, reasons, f)
        for attempt in (1, 2):
            started = time.time()
            try:
                out = _ask_gemma(system, prompt, TIMEOUT_S)
            except (OSError, ValueError) as e:  # Ollama down, too slow, or bad JSON.
                _log({"ts": started, "model": MODEL, "attempt": attempt, "error": str(e)[:200]})
                break
            text = _clean(out.get("message", {}).get("content", ""))
            bad = sorted(invented(text, f))
            # Brand names can contain these words ("Bewakoof" sells hoodies), so the item's own name is fine.
            rude = sorted(insults(text) - insults(f.get("item") or ""))
            _log({
                "ts": started, "model": MODEL, "mood": mood, "attempt": attempt, "line": text,
                "invented": bad, "insults": rude, "ms": round((time.time() - started) * 1000),
                "tokens": out.get("eval_count"), "gen_ms": round((out.get("eval_duration") or 0) / 1e6),
            })
            if text and not bad and not rude:
                return text, "gemma"

    text = template_line(mood, reasons, f, language)
    if invented(text, f):  # A template should never trip this; if it does, the template is wrong.
        raise ValueError(f"template invented numbers: {text}")
    return text, "template"
