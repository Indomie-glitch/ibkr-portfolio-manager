"""News sentiment (#170): whether each headline is good or bad news for the stock it's listed under,
and how strongly, for the sentiment arrows in the News section (#97).

The headlines for a stock that haven't been judged yet go to Claude in one call with a fixed
answer shape (structured outputs). Each answer is saved in news_sentiment.sqlite by stock and
article, so a headline is only judged once. Every call's token counts are logged in the same file
(ai_usage) so they can be priced with the summaries' usage (#86).

Without an API key, or if the call fails, the news is returned without sentiment: the arrows are
extra, never a reason for the news list to fail.
"""
import asyncio
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import anthropic

import config
from config import DATA_DIR
from secrets_guard import mask_secrets

DB_PATH = DATA_DIR / "news_sentiment.sqlite"
DIRECTIONS = ("positive", "negative", "neutral")
STRENGTHS = (1, 2, 3)
MAX_TOKENS = 8000  # room for adaptive thinking on the newer models; the answer itself is ~60 tokens a headline
TIMEOUT_S = 30
# Saved judgements are dropped after this long (the news list only shows recent headlines)
KEEP_DAYS = 90
# After a failed call, don't try that stock again for a while (each /news request would retry)
RETRY_AFTER_S = 5 * 60

SYSTEM_PROMPT = """You judge news headlines for one listed company: is each headline good or bad news \
for that company's business and its shareholders, and how strongly?

Rules:
- Judge only for the company named in the request. A headline can be good for one company and bad for
  another (a competitor's win, a supplier's problem): judge it for this company.
- You only have the headline, the publisher and the date. Don't assume details the headline doesn't give.
- direction: "positive" (good news for the company), "negative" (bad news) or "neutral" (routine,
  mixed, unclear, not really about this company, or general market commentary).
- strength, for positive and negative only (use 1 for neutral):
  1 = mild (an analyst note, a small contract, a modest move in the share price)
  2 = clear (results above or below expectations, a significant deal, a regulatory action, a guidance change)
  3 = major (a takeover offer, a large profit warning, fraud or a collapse, a transformative deal)
- A headline that only reports the share price rising or falling is at most strength 1.
- Opinion, analysis and speculation (questions, "might", "could", "reasons to", "how investors are
  reacting", valuation pieces, stock lists) are at most strength 1, and neutral if they don't say
  whether the news is good or bad.
- Selling or closing a business, cutting costs or jobs, or spending on a project is not bad or good
  news by itself: use neutral unless the headline says it helps or hurts the company.
- reason: one short line (under 15 words) saying why, in plain words. No advice about buying or selling,
  and no predictions about the share price.
- Answer for every headline id you're given, once each."""


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sentiments (
            con_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            direction TEXT NOT NULL,     -- positive / negative / neutral
            strength INTEGER,            -- 1-3; NULL for neutral
            reason TEXT NOT NULL,
            model TEXT NOT NULL,
            created_at TEXT NOT NULL,    -- ISO time with offset
            PRIMARY KEY (con_id, url)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            feature TEXT NOT NULL,       -- 'news_sentiment'
            model TEXT NOT NULL,
            con_id INTEGER,
            items INTEGER NOT NULL,      -- headlines judged in the call
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL
        )
    """)
    return conn


def saved_sentiments(con_id, urls):
    """{url: sentiment} for the articles of this stock that were already judged."""
    if not urls:
        return {}
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT url, direction, strength, reason FROM sentiments WHERE con_id = ? AND url IN ({','.join('?' * len(urls))})",
            (con_id, *urls),
        ).fetchall()
    return {r["url"]: {"direction": r["direction"], "strength": r["strength"], "reason": r["reason"]} for r in rows}


def save_sentiments(con_id, judged, model, usage):
    """judged: list of (item, sentiment). Also logs the call's tokens and drops old judgements."""
    now = datetime.now(timezone.utc)
    with _connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO sentiments (con_id, url, title, direction, strength, reason, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(con_id, item["url"], item["title"], s["direction"], s["strength"], s["reason"], model, now.isoformat())
             for item, s in judged],
        )
        conn.execute(
            "INSERT INTO ai_usage (created_at, feature, model, con_id, items, input_tokens, output_tokens) "
            "VALUES (?, 'news_sentiment', ?, ?, ?, ?, ?)",
            (now.isoformat(), model, con_id, len(judged), usage["input_tokens"], usage["output_tokens"]),
        )
        conn.execute("DELETE FROM sentiments WHERE created_at < ?", ((now - timedelta(days=KEEP_DAYS)).isoformat(),))


def usage_log():
    """Every logged call, oldest first (for cost tracking, #86)."""
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM ai_usage ORDER BY id").fetchall()]


def build_schema(ids):
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": list(ids)},
                        "direction": {"type": "string", "enum": list(DIRECTIONS)},
                        "strength": {"type": "integer", "enum": list(STRENGTHS)},
                        "reason": {"type": "string"},
                    },
                    "required": ["id", "direction", "strength", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    }


def user_message(company, symbol, numbered):
    lines = [f"Company: {company} (ticker {symbol})", "", "Headlines:"]
    for news_id, item in numbered.items():
        published = (item.get("published") or "")[:10] or "date unknown"
        lines.append(f"{news_id}. {item['title']} ({item.get('publisher') or 'unknown publisher'}, {published})")
    return "\n".join(lines)


def clean_answer(answer, ids):
    """{id: sentiment} from the model's answer, keeping only valid, known ids (first answer wins)."""
    result = {}
    for entry in answer.get("items", []):
        news_id = entry.get("id")
        direction = entry.get("direction")
        if news_id not in ids or news_id in result or direction not in DIRECTIONS:
            continue
        strength = entry.get("strength")
        if direction == "neutral":
            strength = None
        elif strength not in STRENGTHS:
            continue
        result[news_id] = {"direction": direction, "strength": strength,
                           "reason": " ".join(str(entry.get("reason") or "").split())[:200]}
    return result


async def judge(company, symbol, items, client):
    """Ask Claude about items (all new); returns ({url: sentiment}, usage). Raises on API errors."""
    numbered = {f"N{i}": item for i, item in enumerate(items, start=1)}
    response = await client.messages.create(
        model=config.ai_model(),
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message(company, symbol, numbered)}],
        output_config={"format": {"type": "json_schema", "schema": build_schema(numbered)}},
    )
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"stopped early ({response.stop_reason})")
    text = next(b.text for b in response.content if b.type == "text")
    by_id = clean_answer(json.loads(text), numbered)
    return {numbered[news_id]["url"]: s for news_id, s in by_id.items()}, usage


_locks = {}  # con_id -> asyncio.Lock, so two requests for one stock make one call
_failed_at = {}  # con_id -> monotonic time of the last failed call


async def with_sentiment(con_id, company, symbol, items, client=None):
    """items with a "sentiment" added to each: {direction, strength, reason}, or None when it isn't
    known (no API key, or the call failed). client is only passed by tests."""
    items = [dict(item) for item in items]
    for item in items:
        item["sentiment"] = None
    if not items or (client is None and not config.anthropic_api_key()):
        return items

    async with _locks.setdefault(con_id, asyncio.Lock()):
        known = await asyncio.to_thread(saved_sentiments, con_id, [i["url"] for i in items])
        new = [i for i in items if i["url"] not in known]
        recently_failed = time.monotonic() - _failed_at.get(con_id, -RETRY_AFTER_S) < RETRY_AFTER_S
        if new and not recently_failed:
            try:
                # The key never leaves the backend
                client = client or anthropic.AsyncAnthropic(api_key=config.anthropic_api_key(),
                                                            timeout=TIMEOUT_S, max_retries=1)
                judged, usage = await judge(company, symbol, new, client)
                await asyncio.to_thread(save_sentiments, con_id, [(i, judged[i["url"]]) for i in new if i["url"] in judged],
                                        config.ai_model(), usage)
                known.update(judged)
                _failed_at.pop(con_id, None)
            except Exception as exc:
                _failed_at[con_id] = time.monotonic()
                print(f"News sentiment failed for {symbol}: {exc.__class__.__name__}: {mask_secrets(exc)}")

    for item in items:
        item["sentiment"] = known.get(item["url"])
    return items
