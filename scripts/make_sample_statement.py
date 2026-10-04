"""Writes data/sample/statement.csv: three months of a made-up student's bank statement.

Laid out like an HDFC export, including the account details above the header,
so the parser is tested against something realistic. Every name and number is
invented; the demo and the post use this, never anyone's real statement.

    python scripts/make_sample_statement.py
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "sample" / "statement.csv"
START, END = date(2026, 7, 1), date(2026, 10, 3)
rng = random.Random(26)


def upi(name: str, vpa: str) -> str:
    return f"UPI-{name}-{vpa}-YESB0YBLUPI-{rng.randrange(10**11, 10**12)}-PAYMENT FROM PHONE"


def events_for(day: date) -> list[tuple[str, float, float]]:
    """(narration, money out, money in) for one day."""
    out = []
    weekend = day.weekday() >= 5
    if day.day == 1:
        out.append(("NEFT CR-SBIN0001234-RAJESH SHARMA-POCKET MONEY", 0, 12000))
    if day.day == 7 and day.month in (8, 9):
        out.append(("IMPS-512345678-PRIYA FREELANCE CLIENT-WEBSITE WORK", 0, 3000))
    # Food delivery: the habit that eats the budget, worse at weekends.
    if rng.random() < (0.55 if weekend else 0.32):
        name, vpa = rng.choice([("SWIGGY", "SWIGGY8@YBL"), ("ZOMATO", "ZOMATO@HDFCBANK")])
        out.append((upi(name, vpa), round(rng.uniform(170, 460)), 0))
    if rng.random() < 0.14:
        name, vpa = rng.choice([("BLINKIT", "BLINKIT.PAYU@HDFCBANK"), ("ZEPTO", "ZEPTO@YBL")])
        out.append((upi(name, vpa), round(rng.uniform(140, 620)), 0))
    if rng.random() < 0.22:
        name, vpa = rng.choice([("UBER INDIA", "UBER@ICICI"), ("RAPIDO", "RAPIDO@AXISBANK")])
        out.append((upi(name, vpa), round(rng.uniform(55, 240)), 0))
    if rng.random() < 0.08:
        out.append((upi("THIRD WAVE COFFEE", "TWC@YBL"), round(rng.uniform(240, 460)), 0))
    # Subscriptions, same day every month.
    if day.day == 5:
        out.append((upi("NETFLIX", "NETFLIX@HDFCBANK"), 199, 0))
    if day.day == 12:
        out.append((upi("SPOTIFY INDIA", "SPOTIFY@AXISBANK"), 119, 0))
    if day.day == 18:
        out.append((upi("JIOHOTSTAR", "HOTSTAR@ICICI"), 299, 0))
    if day.day == 9:
        out.append((upi("JIO PREPAID RECHARGE", "JIOPAY@YBL"), 349, 0))
    # Shopping, plus the keyboard.
    if day == date(2026, 8, 14):
        out.append((upi("AMAZON PAY INDIA", "AMAZONPAY@APL"), 11999, 0))
    elif rng.random() < 0.06:
        name, vpa = rng.choice([("AMAZON PAY INDIA", "AMAZONPAY@APL"), ("FLIPKART", "FLIPKART@AXISBANK"), ("MYNTRA", "MYNTRA@ICICI")])
        out.append((upi(name, vpa), round(rng.uniform(299, 1899)), 0))
    if day == date(2026, 9, 21):
        out.append((upi("STEAM GAMES", "STEAM@PAYU"), 1299, 0))
    if day.day == 15:
        out.append(("ATM WDL-CASH-HDFC ATM KOLKATA", 2000, 0))
    return out


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    balance = 9000.0  # Some savings, most of which the keyboard eats in August.
    rows = []
    day = START
    while day <= END:
        for narration, spent, got in events_for(day):
            balance += got - spent
            ref = f"{rng.randrange(10**11, 10**12)}"
            d = day.strftime("%d/%m/%y")
            rows.append([d, narration, ref, d, f"{spent:.2f}" if spent else "", f"{got:.2f}" if got else "", f"{balance:.2f}"])
        day += timedelta(days=1)

    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["HDFC BANK Ltd.   (sample data, not a real account)"])
        w.writerow(["Statement of accounts"])
        w.writerow(["Account No :", "XXXXXXXX4821"])
        w.writerow(["Statement From :", START.strftime("%d/%m/%Y"), "To :", END.strftime("%d/%m/%Y")])
        w.writerow([])
        w.writerow(["Date", "Narration", "Chq./Ref.No.", "Value Dt", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"])
        w.writerows(rows)
        w.writerow([])
        w.writerow(["**Computer generated statement. Sample data for Checkout Chacha.**"])
    print(f"wrote {len(rows)} transactions to {OUT}, closing balance {balance:.2f}")

    # The made-up student's own labels, the way they'd tap them in the dashboard:
    # pricey delivery orders, late-month splurges and games are regrets.
    labels = {}
    for i, (d, narration, _ref, _vd, spent, _got, _bal) in enumerate(rows):
        if not spent or "ATM" in narration or "NEFT" in narration:
            continue
        amount, day_of_month = float(spent), int(d[:2])
        food = "SWIGGY" in narration or "ZOMATO" in narration
        splurge = any(s in narration for s in ("AMAZON", "FLIPKART", "MYNTRA", "STEAM"))
        late_month = day_of_month > 18  # Pocket money arrives on the 1st; by the 20th it's thin.
        regret = (food and (amount > 300 or late_month)) or (splurge and (amount > 700 or late_month)) or (
            "THIRD WAVE" in narration and amount > 350)
        labels[i] = int(regret)
    # Nobody labels everything; someone labelling on purpose makes sure both kinds are there.
    regrets = [i for i, y in labels.items() if y][:16]
    fine = [i for i, y in labels.items() if not y][:40 - len(regrets)]
    picked = {i: labels[i] for i in sorted(regrets + fine)}
    (OUT.parent / "labels.json").write_text(json.dumps(picked, indent=1))
    print(f"labelled {len(picked)} purchases, {sum(picked.values())} as regret")


if __name__ == "__main__":
    main()
