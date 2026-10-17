"""Saved AI summaries, one row per generated summary, in a local SQLite file (data/ is gitignored).

Keeping recent summaries lets the page show the last one instantly, lets the next summary
say what changed since then, and lets the history view show and compare older ones.
"""
import json
import sqlite3

from config import DATA_DIR
from secrets_guard import mask_secrets

DB_PATH = DATA_DIR / "summaries.sqlite"
# Older summaries of a stock are deleted when a new one is saved, so the file doesn't grow forever
KEEP_PER_STOCK = 20


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            con_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            created_at TEXT NOT NULL,   -- ISO time with offset
            model TEXT NOT NULL,
            facts TEXT NOT NULL,        -- JSON: exactly what the model was given (plus news links)
            summary TEXT NOT NULL,      -- JSON: the 10 sections
            warnings TEXT NOT NULL      -- JSON list: removed citations, point-count notes, ...
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS summaries_by_stock ON summaries (con_id, created_at)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            model TEXT NOT NULL,
            facts TEXT NOT NULL,        -- JSON: the portfolio facts sheet (portfolio_facts.py)
            summary TEXT NOT NULL,      -- JSON: the 8 sections
            warnings TEXT NOT NULL
        )
    """)
    return conn


def save(con_id, symbol, created_at, model, facts, summary, warnings):
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO summaries (con_id, symbol, created_at, model, facts, summary, warnings) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (con_id, symbol, created_at, model, mask_secrets(json.dumps(facts)),
             mask_secrets(json.dumps(summary)), mask_secrets(json.dumps(warnings))),
        )
        # Same transaction as the insert: both happen or neither does
        conn.execute("""
            DELETE FROM summaries WHERE con_id = ? AND id NOT IN (
                SELECT id FROM summaries WHERE con_id = ? ORDER BY created_at DESC, id DESC LIMIT ?
            )
        """, (con_id, con_id, KEEP_PER_STOCK))
        return cursor.lastrowid


def history(con_id):
    """Every saved summary of a stock, newest first, without the full text."""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT id, created_at, model, json_extract(facts, '$."D:key_stats".last_price') AS price
            FROM summaries WHERE con_id = ? ORDER BY created_at DESC, id DESC
        """, (con_id,)).fetchall()
    return [dict(row) for row in rows]


def get(con_id, summary_id):
    """One saved summary as a dict, or None if it doesn't exist or belongs to another stock."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM summaries WHERE con_id = ? AND id = ?", (con_id, summary_id)).fetchone()
    return _record(row)


def latest(con_id):
    """The most recent summary for a stock as a dict, or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM summaries WHERE con_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (con_id,)
        ).fetchone()
    return _record(row)


def _record(row):
    if row is None:
        return None
    return {
        "id": row["id"],
        "con_id": row["con_id"],
        "symbol": row["symbol"],
        "created_at": row["created_at"],
        "model": row["model"],
        "facts": json.loads(row["facts"]),
        "summary": json.loads(row["summary"]),
        "warnings": json.loads(row["warnings"]),
    }


# ---------- portfolio summaries (one list, not per stock) ----------

def save_portfolio(created_at, model, facts, summary, warnings):
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO portfolio_summaries (created_at, model, facts, summary, warnings) VALUES (?, ?, ?, ?, ?)",
            (created_at, model, mask_secrets(json.dumps(facts)), mask_secrets(json.dumps(summary)),
             mask_secrets(json.dumps(warnings))),
        )
        conn.execute("""
            DELETE FROM portfolio_summaries WHERE id NOT IN (
                SELECT id FROM portfolio_summaries ORDER BY created_at DESC, id DESC LIMIT ?
            )
        """, (KEEP_PER_STOCK,))
        return cursor.lastrowid


def latest_portfolio():
    """The most recent portfolio summary as a dict, or None."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM portfolio_summaries ORDER BY created_at DESC, id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "model": row["model"],
        "facts": json.loads(row["facts"]),
        "summary": json.loads(row["summary"]),
        "warnings": json.loads(row["warnings"]),
    }
