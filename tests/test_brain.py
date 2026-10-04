"""Checks for the parts that went wrong on real screens. Run: python tests/test_brain.py

The screens below are made up, but shaped like what the Flipkart and Amazon apps
really expose to Android (see data/dumps/ for the real ones, which never leave
this laptop).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain import judge, screen, statement, voice  # noqa: E402


def lines(*rows):
    return [{"t": t, "y": y, "c": False, "v": True} for t, y in rows]


def test_address_below_the_price_is_not_the_product():
    page = lines(
        ("Key Highlights", 248), ("FTX", 994), ("Visit store", 997),
        ("Men Relaxed Black Lycra Blend Trousers", 1059), ("Big Billion Days Price", 1225),
        ("62%, 1,249, ₹472", 1303), ("Delivery details", 1450),
        ("HOME, 12, Example Nagar, Sector 9, Near Some Landmark, Kolkata, West Bengal", 1560),
        ("Add to cart", 2152), ("Buy now", 2152),
    )
    assert screen.product(page) == ("FTX Men Relaxed Black Lycra Blend Trousers", 472.0)


def test_ad_strip_and_offscreen_price():
    page = [
        {"t": "AD", "y": 103, "v": False},
        {"t": "Some Neckband Ad Product With Long Name", "y": 111, "v": False},
        {"t": "₹285", "y": 171, "v": False}, {"t": "₹194", "y": 171, "v": False},
        {"t": "Add to cart", "y": 2152, "v": True}, {"t": "Buy now", "y": 2152, "v": True},
        {"t": "boAt BassHeads 211 Wired Earphones...more", "y": 2270, "v": True},
        {"t": "₹249", "y": 2520, "v": False},
    ]
    assert screen.product(page) == ("boAt BassHeads 211 Wired Earphones", 249.0)


def test_carousel_prices_are_not_the_product():
    page = lines(("Recently Viewed", 279), ("₹829", 830), ("₹472", 830), ("₹438", 830))
    assert screen.product(page)[1] is None


def test_cart_total_from_the_checkout_bar():
    cart = lines(("You'll save ₹962 on this order", 1610), ("1,598", 1700), ("₹636", 1760), ("Proceed to buy", 1760))
    assert screen.cart_total(cart) == 636.0
    assert screen.cart_total(lines(("Total Amount", 1977), ("₹472", 1977))) == 472.0
    assert screen.cart_total(lines(("Shopping Cart", 75), ("₹1,999", 837))) is None


def test_fact_guard():
    facts = {"price": 5499.0, "fun_left": 5000.0, "item": "Sony PlayStation 5 DualSense Controller"}
    assert voice.invented("₹5,499 with ₹5,000 left? Beta, no.", facts) == set()
    assert voice.invented("A PlayStation 5 controller? Bas kar.", facts) == set()
    assert voice.invented("Use it for 1001 more good habits.", facts) == {"1001"}


def test_tone_guard():
    assert voice.insults("That keyboard costs too much, you fool.") == {"fool"}
    assert voice.insults("That keyboard costs too much, beta.") == set()


def test_upi_merchants():
    assert statement.merchant_of("UPI/DR/412345678/SWIGGY/YESB/swiggy@ybl/Payment") == "Swiggy"
    assert statement.merchant_of("UPI-ZOMATO-ZOMATO@HDFCBANK-YESB0YBLUPI-512345678901-PAYMENT FROM PHONE") == "Zomato"


def test_needs_are_praised_and_overspending_is_roasted():
    cfg = {"fun_budget": 5000, "big_ticket": 3000}
    book = judge.facts("manual", "Atomic Habits (Paperback)", 399, None, [], cfg)
    assert judge.verdict(book)[0] == "praise"
    controller = judge.facts("add_to_cart", "PS5 DualSense Controller", 5499, None, [], cfg)
    mood, _, reasons = judge.verdict(controller)
    assert mood == "roast" and "over_budget" in reasons


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in globals().items() if name.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
