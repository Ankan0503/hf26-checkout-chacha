# What this cannot do

Kept deliberately, in the habit of listing a project's real limits.

**It is not financial advice.** It's a friend with your bank statement and opinions.

**It only sees what Android shows it.**
- Some Flipkart sellers offer only "Buy now" and "Buy with EMI", with no
  "Add to cart". On those pages Chacha can't notice an add; tap the orb to ask.
- An "Add to cart" that is only an icon, with no label, is invisible to it.
- When Amazon or Flipkart change their pages, it can miss a product until
  `brain/screen.py` is updated. The phone sends raw screen text, so that fix
  never needs a new app.

**The phone needs the laptop.** The brain runs on the laptop, so the orb works
only while the phone is plugged in (or on the same Wi-Fi) and the brain is
running. Over Wi-Fi the traffic is plain HTTP on your home network, protected
by the pairing code, not by encryption.

**The models are small and personal.**
- The regret chance is learned from about 40 of your own labels. It's a
  personal hunch, not a scientific model, and it will be wrong sometimes. It
  sees amounts, timing and categories from your statement, not what the
  product is.
- The forecast is built from one to three months of history and smooths over
  one-off spikes. Treat the date as rough.

**The guards are narrow.**
- The fact guard checks numbers, not meaning. A line can contain only true
  numbers and still be unfair, for example calling a budget "finished" when it
  isn't.
- The tone guard is a word list. It catches name-calling, not every unkind
  sentence.

**It runs on a CPU.** On a laptop with no GPU, a verdict takes about 6–10
seconds. The orb spins while it thinks.
