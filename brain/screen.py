"""Turns the raw text of a shopping screen into a product, a price, or a cart total.

The phone sends everything it can see and all the guessing happens here, so it
can be fixed without rebuilding the app. Every request is kept in data/dumps/
so these rules can be tuned against what the apps really show.

Strategy: find the selling price first, then the product title just above it.
Anchoring on the price keeps the delivery address (which sits below the price on
both Amazon and Flipkart) and carousel items (which carry their own prices) from
being mistaken for the product.
"""
import re

PRICE = re.compile(r"(?:₹|\b(?:Rs|RS|INR)\.?)\s?(\d[\d,]*(?:\.\d{1,2})?)")
# Lines whose price is not what you pay for the product.
NOT_SELLING_PRICE = re.compile(
    r"(?i)\bm\.?r\.?p\b|list price|\bwas\b|platform fee|delivery (fee|charge)|\bsave\b|\bemi\b|/\s?month"
    r"|cashback|discount|coupon|\bfee\b"
)
PRICE_LABEL = re.compile(r"(?i)\b(deal|offer|special|selling|sale|best)?\s*price\s*:?")
TOTAL = re.compile(r"(?i)\bsubtotal\b|total amount|order total|cart total|^total\b")

# Text that is part of the app, never a product name.
NOT_TITLE = re.compile(
    r"(?i)^(deliver|delivery|visit (the|store)|sold by|bank offer|get it by|get by|free delivery|in stock"
    r"|only \d+ left|save extra|see (all|more)|show all|[\d,.]+ ratings?|ratings?\b|no cost emi|emi\b"
    r"|cashback|coupon|offers?\b|special price|hurry|frequently bought|customers (who|also)|sponsored|brand:"
    r"|top brand|search|share|add to (cart|bag)|buy now|go to (cart|bag)|wishlist|move to wishlist|remove"
    r"|similar products|you might|recently viewed|inclusive of|secure transaction|\d+[- ]days? (return|replacement)"
    r"|selected (color|colour|size)|select (size|color|colour)|size chart|key highlights|big billion|lowest price"
    r"|limited time|deal of the day|bestseller|continue your shopping|back button|shopping cart|#)"
    r"|\bprice\b|\bwaist\b.*\binch"
    r"|^(home|play|categories|account|cart|you|menu|orders)$"  # bottom navigation labels
)
# Buttons that only appear on a single product's page.
PRODUCT_PAGE = re.compile(r"(?i)^\s*(add to (cart|bag|basket)|buy now|go to (cart|bag|basket))\s*$")


def is_product_page(lines: list[dict]) -> bool:
    return any(PRODUCT_PAGE.match(line["t"]) for line in lines)
# Delivery addresses: "HOME, 12, Some Nagar, ..." or anything with a six-digit PIN code.
ADDRESS = re.compile(
    r"(?i)^(home|work|other)\b\s*,|\b\d{6}\b"
    r"|\b(nagar|sector|road|street|lane|colony|near|apartment|flat|floor|block|phase)\b.*,.*,"
)
ADDRESS_LABEL = re.compile(r"(?i)^(deliver(y)? (to|details|address)|delivering to)\b")
AD_LABEL = re.compile(r"(?i)^(ad|sponsored)$")
READ_MORE = re.compile(r"\s*(\.\.\.|…)\s*(read )?more$", re.I)


def _ad_rows(lines: list[dict]) -> set[int]:
    """Indexes of lines sitting next to an 'AD' or 'Sponsored' label: someone else's product."""
    ad_ys = [line["y"] for line in lines if AD_LABEL.match(line["t"].strip())]
    return {i for i, line in enumerate(lines) if any(y - 30 <= line["y"] <= y + 150 for y in ad_ys)}


def price_of(text: str) -> float | None:
    m = PRICE.search(text)
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if value >= 1 else None


def _is_selling_price(text: str) -> bool:
    """A line that is just a price, maybe with a discount: '₹472', '62%, 1,249, ₹472', '-23% ₹26,990'."""
    if not price_of(text) or NOT_SELLING_PRICE.search(text):
        return False
    rest = PRICE_LABEL.sub("", PRICE.sub("", text))
    return len(rest.strip(" ,·|-–%0123456789.↓()")) <= 3


def _letters(text: str) -> float:
    return sum(ch.isalpha() for ch in text) / max(len(text), 1)


def _in_carousel(lines: list[dict], i: int) -> bool:
    """Carousels show several products side by side, so three or more different prices share a row.

    A product page shows at most two in a row (the price and the struck-out MRP), and
    often the same price twice, once alone and once inside a combined label.
    """
    y = lines[i]["y"]
    row = {price_of(line["t"]) for line in lines if abs(line["y"] - y) <= 8 and _is_selling_price(line["t"])}
    return len(row) >= 3


def _title_candidates(lines: list[dict]) -> set[int]:
    """Indexes of lines that could be a product title."""
    near_address_label = set()
    for i, line in enumerate(lines):
        if ADDRESS_LABEL.search(line["t"]):
            near_address_label.update(
                j for j in range(i + 1, min(i + 4, len(lines))) if lines[j]["y"] - line["y"] <= 160
            )
    out = set()
    for i, line in enumerate(lines):
        t = line["t"]
        if i in near_address_label or not 10 <= len(t) <= 220 or len(t.split()) < 2:
            continue
        if t.startswith(",") or "↓" in t or PRICE.search(t) or NOT_TITLE.search(t) or ADDRESS.search(t):
            continue
        if _letters(t) < 0.5:
            continue
        out.add(i)
    return out


def _with_brand(lines: list[dict], i: int) -> str:
    """Flipkart puts the brand on its own line just above the name: 'FTX' + 'Men Relaxed Black Trousers'."""
    title = lines[i]["t"]
    for j in range(i - 1, max(i - 4, -1), -1):
        above = lines[j]
        if lines[i]["y"] - above["y"] > 120:
            break
        t = above["t"]
        if 1 <= len(t.split()) <= 3 and len(t) <= 25 and _letters(t) >= 0.6 and not NOT_TITLE.search(t):
            return title if title.lower().startswith(t.lower()) else f"{t} {title}"
    return title


def product(lines: list[dict]) -> tuple[str | None, float | None]:
    """Best guess at (title, price) on a product page. Either can be None.

    Lines marked v=False are off-screen; they are used only when nothing on
    screen has a price (for example, a product page that hasn't been scrolled).
    """
    visible = [line for line in lines if line.get("v", True)]
    for pool in (visible, lines):
        ads = _ad_rows(pool)
        price_at = next(
            (i for i, line in enumerate(pool)
             if i not in ads and _is_selling_price(line["t"]) and not _in_carousel(pool, i)),
            None,
        )
        if price_at is not None:
            break
    else:
        pool, price_at = visible, None
        ads = _ad_rows(pool)

    candidates = _title_candidates(pool) - ads
    price_y = pool[price_at]["y"] if price_at is not None else None
    best, best_score = None, float("-inf")
    for i in candidates:
        line = pool[i]
        t = line["t"]
        score = min(len(t), 120) / 10 + 0.3 * min(len(t.split()), 15) - (1.5 if line.get("c") else 0)
        if price_y is not None:
            gap = price_y - line["y"]
            if gap < -40:  # Below the price: delivery details, sellers, recommendations.
                continue
            score -= max(gap, 0) / 250
        else:
            score -= line["y"] / 400
        if score > best_score:
            best, best_score = i, score

    title = READ_MORE.sub("", _with_brand(pool, best)) if best is not None else None
    price = price_of(pool[price_at]["t"]) if price_at is not None else None
    return title, price


CHECKOUT = re.compile(r"(?i)^\s*(proceed to (buy|checkout)|place order|checkout)\b")


def cart_total(lines: list[dict]) -> float | None:
    """The amount you'd pay. None unless the screen actually shows a total.

    Prefers a labelled total ("Total Amount", "Subtotal"). Otherwise uses the price
    right before the checkout button, which is all Flipkart's cart shows on screen.
    """
    for i, line in enumerate(lines):
        if TOTAL.search(line["t"]):
            p = price_of(line["t"]) or next(
                (price_of(n["t"]) for n in lines[i + 1:i + 4] if price_of(n["t"])), None
            )
            if p:
                return p
    for i, line in enumerate(lines):
        if CHECKOUT.search(line["t"]):
            before = reversed(lines[max(0, i - 3):i])
            p = next((price_of(n["t"]) for n in before if price_of(n["t"]) and not NOT_SELLING_PRICE.search(n["t"])), None)
            if p:
                return p
    return None
