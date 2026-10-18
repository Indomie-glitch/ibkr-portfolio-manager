"""Claude API usage and cost (#86): one row per call (stock summaries, portfolio summaries, news
sentiment) in usage.sqlite, priced when the call is made, and monthly totals for GET /usage.

Costs are estimates from Anthropic's list prices below (US dollars, standard API rates); the bill
from Anthropic is what counts. Each row keeps its own cost, so a later price change doesn't rewrite
history.
"""
import sqlite3
from datetime import datetime

from config import DATA_DIR

DB_PATH = DATA_DIR / "usage.sqlite"

FEATURES = ("stock_summary", "portfolio_summary", "news_sentiment")

# US$ per million tokens (input, output), for the models config.AI_MODELS offers. Claude Haiku 5.5
# costs more when a prompt is over 100K tokens; the app's prompts are far smaller, but it's priced anyway.
PRICES = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "long_input": 0.50, "long_output": 2.50, "long_from": 100_000},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00},
}


def cost_usd(model, input_tokens, output_tokens):
    """What one call costs in US$, or None for a model without a known price."""
    price = PRICES.get(model)
    if price is None:
        return None
    long = "long_from" in price and input_tokens > price["long_from"]
    per_input = price["long_input"] if long else price["input"]
    per_output = price["long_output"] if long else price["output"]
    return (input_tokens * per_input + output_tokens * per_output) / 1_000_000


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,    -- local ISO time with offset; its first 7 characters are the month
            feature TEXT NOT NULL,       -- stock_summary / portfolio_summary / news_sentiment
            model TEXT NOT NULL,
            con_id INTEGER,              -- the stock, for stock summaries and news sentiment
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            cost_usd REAL,               -- NULL when the model's price isn't known
            outcome TEXT NOT NULL        -- 'ok', or why the answer wasn't used (e.g. 'incomplete')
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ai_usage_by_time ON ai_usage (created_at)")
    return conn


def record(feature, model, usage, con_id=None, outcome="ok", now=None):
    """Log one call. usage: {"input_tokens", "output_tokens"}. Never raises: losing a usage row must
    not break a summary or the news list."""
    try:
        created = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
        inp, out = int(usage["input_tokens"]), int(usage["output_tokens"])
        with _connect() as conn:
            conn.execute(
                "INSERT INTO ai_usage (created_at, feature, model, con_id, input_tokens, output_tokens, cost_usd, outcome) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (created, feature, model, con_id, inp, out, cost_usd(model, inp, out), outcome),
            )
    except Exception as exc:
        print(f"Usage not recorded ({feature}): {exc.__class__.__name__}")


def import_rows(rows):
    """Adds rows logged elsewhere before this store existed (news sentiment's own table)."""
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO ai_usage (created_at, feature, model, con_id, input_tokens, output_tokens, cost_usd, outcome) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'ok')",
            [(r["created_at"], r["feature"], r["model"], r["con_id"], r["input_tokens"], r["output_tokens"],
              cost_usd(r["model"], r["input_tokens"], r["output_tokens"])) for r in rows],
        )


def monthly(month=None):
    """Totals for one month ("2026-10"; default this month, local time), overall and per feature."""
    month = month or datetime.now().astimezone().strftime("%Y-%m")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT feature, COUNT(*) AS calls, SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
            "SUM(cost_usd) AS cost_usd, SUM(cost_usd IS NULL) AS unpriced FROM ai_usage "
            "WHERE substr(created_at, 1, 7) = ? GROUP BY feature",
            (month,),
        ).fetchall()
    by_feature = {
        feature: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0} for feature in FEATURES
    }
    unpriced = 0
    for r in rows:
        by_feature[r["feature"]] = {"calls": r["calls"], "input_tokens": r["input_tokens"],
                                    "output_tokens": r["output_tokens"], "cost_usd": round(r["cost_usd"] or 0, 6)}
        unpriced += r["unpriced"]
    totals = by_feature.values()
    return {
        "month": month,
        "currency": "USD",
        "calls": sum(f["calls"] for f in totals),
        "input_tokens": sum(f["input_tokens"] for f in totals),
        "output_tokens": sum(f["output_tokens"] for f in totals),
        "cost_usd": round(sum(f["cost_usd"] for f in totals), 6),
        # Calls with a model this file has no price for: their tokens are counted but not their cost
        "unpriced_calls": unpriced,
        "by_feature": by_feature,
        "note": "Estimated from Anthropic's list prices; your Anthropic bill is what counts",
    }
