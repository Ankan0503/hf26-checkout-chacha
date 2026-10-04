"""Everything Chacha remembers lives in one SQLite file on this laptop: data/chacha.db."""
import json
import secrets
import sqlite3
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA / "chacha.db"
CODE_PATH = DATA / "pairing-code.txt"

DEFAULTS = {
    "fun_budget": 5000,       # ₹ per month you're happy to spend on wants
    "big_ticket": 3000,       # ₹ above which a want gets a closer look
    "roast_level": "honest",  # gentle | honest | savage
    "language": "en",         # en | hinglish
    "hourly_income": 0,       # ₹ you earn per hour; 0 means unknown
    "use_gemma": True,        # False: template lines only
}

SCHEMA = """
create table if not exists verdicts (
    id text primary key,
    ts real not null,
    app text,
    event text,
    title text,
    price real,
    category text,
    need integer,
    mood text,
    level integer,
    line text,
    facts text,
    decision text,
    decided_at real
);
create table if not exists settings (key text primary key, value text);
create table if not exists txns (
    id integer primary key,  -- position in the statement, oldest first
    day text, text text, merchant text, category text, need integer,
    out real, inn real, balance real
);
create table if not exists labels (txn_id integer primary key, regret integer);
create table if not exists cache (key text primary key, value text);
"""


def connect() -> sqlite3.Connection:
    DATA.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def pairing_code() -> str:
    """Six characters, made once. No 0/O or 1/I, so it's easy to type on a phone."""
    DATA.mkdir(exist_ok=True)
    if CODE_PATH.exists():
        return CODE_PATH.read_text().strip()
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(alphabet) for _ in range(6))
    CODE_PATH.write_text(code)
    return code


def settings(db) -> dict:
    out = dict(DEFAULTS)
    for row in db.execute("select key, value from settings"):
        out[row["key"]] = json.loads(row["value"])
    return out


def put_setting(db, key: str, value) -> None:
    db.execute("insert or replace into settings values (?, ?)", (key, json.dumps(value)))
    db.commit()


def save_verdict(db, v: dict) -> None:
    db.execute(
        "insert into verdicts (id, ts, app, event, title, price, category, need, mood, level, line, facts)"
        " values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            v["id"], v["ts"], v["app"], v["event"], v["title"], v["price"], v["category"],
            int(bool(v["need"])), v["mood"], v["level"], v["line"],
            json.dumps(v["facts"], ensure_ascii=False),
        ),
    )
    db.commit()


def decide(db, verdict_id: str, decision: str) -> bool:
    cur = db.execute(
        "update verdicts set decision = ?, decided_at = ? where id = ?",
        (decision, time.time(), verdict_id),
    )
    db.commit()
    return cur.rowcount > 0


def since(db, ts: float) -> list[dict]:
    return [dict(r) for r in db.execute("select * from verdicts where ts >= ? order by ts", (ts,))]


# --- The bank statement --------------------------------------------------------

def save_statement(db, txns) -> None:
    """Replaces the statement. Labels pointed at the old rows, so they go too."""
    db.execute("delete from txns")
    db.execute("delete from labels")
    db.execute("delete from cache")
    db.executemany(
        "insert into txns values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(i, t.day.isoformat(), t.text, t.merchant, t.category, int(t.need), t.out, t.inn, t.balance)
         for i, t in enumerate(txns)],
    )
    db.commit()


def load_statement(db) -> list:
    from datetime import date

    from .statement import Txn
    return [
        Txn(date.fromisoformat(r["day"]), r["text"], r["merchant"], r["category"], bool(r["need"]),
            r["out"], r["inn"], r["balance"])
        for r in db.execute("select * from txns order by id")
    ]


def labels(db) -> dict[int, int]:
    return {r["txn_id"]: r["regret"] for r in db.execute("select txn_id, regret from labels")}


def set_label(db, txn_id: int, regret: int | None) -> None:
    if regret is None:
        db.execute("delete from labels where txn_id = ?", (txn_id,))
    else:
        db.execute("insert or replace into labels values (?, ?)", (txn_id, int(bool(regret))))
    db.commit()


def cache_get(db, key: str):
    row = db.execute("select value from cache where key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def cache_put(db, key: str, value) -> None:
    db.execute("insert or replace into cache values (?, ?)", (key, json.dumps(value)))
    db.commit()


def wipe() -> None:
    """Delete all my data: the database, saved screens and the voice log. The pairing code stays."""
    import shutil
    for path in (DB_PATH, DATA / "voice-log.jsonl"):
        path.unlink(missing_ok=True)
    shutil.rmtree(DATA / "dumps", ignore_errors=True)
