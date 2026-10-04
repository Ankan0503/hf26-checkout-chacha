"""Reads a bank statement export and turns it into the money facts Chacha can quote.

Indian banks all export differently (SBI, HDFC, ICICI, Axis, Kotak...), usually
with a few lines of account details above the real header. So instead of one
format per bank, this finds the header row by its column names and works out
which column is the date, the description, the money out, the money in, and the
balance.

The statement never leaves this laptop. It is parsed here and stored in
data/chacha.db, and "Delete all my data" removes it.
"""
import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime

DATE_COLS = ("txn date", "transaction date", "tran date", "date", "value date", "value dt")
TEXT_COLS = ("narration", "description", "particulars", "transaction remarks", "remarks", "details")
OUT_COLS = ("withdrawal", "debit", "dr", "paid out", "money out")
IN_COLS = ("deposit", "credit", "cr", "paid in", "money in")
BALANCE_COLS = ("closing balance", "balance", "bal")
AMOUNT_COLS = ("amount",)
DRCR_COLS = ("dr/cr", "dr / cr", "cr/dr", "type")

DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%d %b %Y", "%d-%b-%Y", "%d %b %y",
                "%d-%b-%y", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y")

# Merchant name -> (category, is it a need?). First match wins.
MERCHANTS = [
    (r"swiggy|zomato|eatsure|dominos|domino's|pizza ?hut|kfc|mcdonald|burger ?king|faasos|box8|behrouz", "food delivery", False),
    (r"blinkit|zepto|instamart|bigbasket|bb ?now|dmart|jiomart|grofers|kirana|grocery", "groceries", True),
    (r"netflix|spotify|hotstar|jiocinema|prime ?video|youtube ?premium|sonyliv|zee5|apple\.com|google ?play|crunchyroll", "subscriptions", False),
    (r"amazon|flipkart|myntra|ajio|meesho|nykaa|tata ?cliq|snapdeal", "shopping", False),
    (r"bookmyshow|pvr|inox|steam|playstation|epic ?games|valorant|riot", "fun", False),
    (r"uber|ola|rapido|irctc|redbus|metro|namma ?yatri|indigo|makemytrip", "travel", True),
    (r"jio|airtel|\bvi\b|vodafone|bsnl|recharge|electricity|bescom|cesc|wbsedcl|broadband|act ?fibernet", "bills", True),
    (r"apollo|pharmeasy|netmeds|1mg|medplus|hospital|clinic|pharmacy|chemist", "health", True),
    (r"college|university|school|fees|udemy|coursera|unacademy|byju|exam", "education", True),
    (r"cafe|chai|starbucks|ccd|cafe ?coffee ?day|chaayos|third ?wave", "eating out", False),
]
TRANSFER = re.compile(r"(?i)\b(neft|imps|rtgs|self|own account|transfer to|tfr|atm|cash withdrawal|sweep)\b")


@dataclass
class Txn:
    day: date
    text: str
    merchant: str
    category: str
    need: bool
    out: float      # money spent (0 for money coming in)
    inn: float      # money received
    balance: float | None


def _norm(cell: str) -> str:
    return re.sub(r"[^a-z/ ]", "", (cell or "").strip().lower()).strip()


def _find(header: list[str], names: tuple[str, ...]) -> int | None:
    """Exact match first, then 'starts with', so 'balance' doesn't grab 'closing balance' late."""
    cells = [_norm(h) for h in header]
    for name in names:
        if name in cells:
            return cells.index(name)
    for name in names:
        for i, c in enumerate(cells):
            if c.startswith(name):
                return i
    return None


def _money(cell: str) -> float:
    s = re.sub(r"[^\d.\-]", "", (cell or "").replace(",", ""))
    try:
        return abs(float(s)) if s not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def _balance(cell: str) -> float | None:
    """Balances keep their sign: '-1,234.00' and '1,234.00 Dr' are overdrawn, '1,234.00 Cr' is not."""
    s = (cell or "").strip()
    if not s:
        return None
    value = _money(s)
    return -value if s.startswith("-") or s.lower().endswith("dr") else value


def _date(cell: str) -> date | None:
    s = (cell or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


UPI_NOISE = {"UPI", "DR", "CR", "P2M", "P2A", "PAY", "PAYMENT", "PAYMENT FROM PHONE", "SENT USING PAYTM UPI"}
IFSC = re.compile(r"[A-Z]{4}0[A-Z0-9]{6}")


def merchant_of(text: str) -> str:
    """The shop's name from a bank narration.

    SBI writes UPI/DR/412345678/SWIGGY/YESB/swiggy@ybl/..., HDFC writes
    UPI-SWIGGY-SWIGGY8@YBL-YESB0YBLUPI-412345678901-... The name is the first
    piece that isn't a code, a number, a UPI ID or a bank's IFSC.
    """
    t = text.upper()
    if "UPI" in t:
        for piece in re.split(r"[/-]", t):
            piece = piece.strip()
            if (not piece or piece in UPI_NOISE or "@" in piece or IFSC.fullmatch(piece)
                    or not re.search(r"[A-Z]{3,}", piece) or sum(c.isdigit() for c in piece) > 3):
                continue
            return piece.title()[:30]
    m = re.search(r"(?:POS|ECOM|VPS|IPS)\s*(?:\d+\s+)?([A-Z][A-Z0-9 .&'*]{2,30})", t)
    if m:
        return m.group(1).strip().title()
    return re.sub(r"\s+", " ", text).strip()[:30].title()


def categorize(text: str) -> tuple[str, bool]:
    low = text.lower()
    for pattern, category, need in MERCHANTS:
        if re.search(pattern, low):
            return category, need
    if TRANSFER.search(low):
        return "transfers", True
    return "other", False


def parse(raw: bytes) -> list[Txn]:
    """Every transaction in the export, oldest first. Raises ValueError if no header is found."""
    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))

    for start, header in enumerate(rows):
        di, ti = _find(header, DATE_COLS), _find(header, TEXT_COLS)
        if di is not None and ti is not None:
            break
    else:
        raise ValueError("Couldn't find the header row. Expected columns like Date and Narration/Description.")

    oi, ii = _find(header, OUT_COLS), _find(header, IN_COLS)
    bi, ai, ci = _find(header, BALANCE_COLS), _find(header, AMOUNT_COLS), _find(header, DRCR_COLS)

    out: list[Txn] = []
    for row in rows[start + 1:]:
        if len(row) <= max(di, ti):
            continue
        day = _date(row[di])
        if not day:
            continue  # Footer lines, totals, page breaks.
        narration = row[ti].strip()
        if oi is not None or ii is not None:
            spent = _money(row[oi]) if oi is not None and oi < len(row) else 0.0
            got = _money(row[ii]) if ii is not None and ii < len(row) else 0.0
        elif ai is not None:
            amount = _money(row[ai])
            is_debit = ci is not None and ci < len(row) and row[ci].strip().lower().startswith("d")
            signed = row[ai].strip().startswith("-")
            spent, got = (amount, 0.0) if (is_debit or signed) else (0.0, amount)
        else:
            continue
        category, need = categorize(narration)
        balance = _balance(row[bi]) if bi is not None and bi < len(row) else None
        out.append(Txn(day, narration, merchant_of(narration), category, need, spent, got, balance))

    if not out:
        raise ValueError("Found the header but no transactions under it.")
    return sorted(out, key=lambda t: t.day)


def subscriptions(txns: list[Txn]) -> list[dict]:
    """Same merchant, about the same amount, about a month apart, at least twice."""
    by_merchant: dict[str, list[Txn]] = {}
    for t in txns:
        if t.out and t.category != "transfers":  # A monthly ATM visit isn't a subscription.
            by_merchant.setdefault(t.merchant, []).append(t)
    found = []
    for merchant, items in by_merchant.items():
        if len(items) < 2:
            continue
        a, b = items[-2], items[-1]
        gap = (b.day - a.day).days
        if 25 <= gap <= 35 and abs(a.out - b.out) <= 0.1 * max(a.out, b.out):
            found.append({"merchant": merchant, "amount": b.out, "last": b.day.isoformat(), "category": b.category})
    return sorted(found, key=lambda s: -s["amount"])
