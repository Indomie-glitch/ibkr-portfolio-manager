"""Saved AI summaries, one row per generated summary, in a local SQLite file (data/ is gitignored).

Keeping every summary lets the page show the last one instantly and lets the next summary
say what changed since then.
"""
import json
import sqlite3

from secrets_guard import mask_secrets
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "summaries.sqlite"


def _connect():
    DB_PATH.parent.mkdir(exist_ok=True)
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
    return conn


def save(con_id, symbol, created_at, model, facts, summary, warnings):
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO summaries (con_id, symbol, created_at, model, facts, summary, warnings) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (con_id, symbol, created_at, model, mask_secrets(json.dumps(facts)),
             mask_secrets(json.dumps(summary)), mask_secrets(json.dumps(warnings))),
        )
        return cursor.lastrowid


def latest(con_id):
    """The most recent summary for a stock as a dict, or None."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM summaries WHERE con_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (con_id,)
        ).fetchone()
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
