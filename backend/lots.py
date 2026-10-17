"""Purchase lots for each holding, from the IBKR Flex report (flex_report.py), kept in lots.sqlite.

The report is fetched at most once a day. Each holding's lots come from IBKR's own open lots when
the report has them; otherwise they're rebuilt from the year's trades first in, first out. Shares
bought before the report's period (a year) can't be dated that way and are reported as unknown.
"""
import asyncio
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import config
import flex_report as flex
from secrets_guard import mask_secrets

DB_PATH = config.DATA_DIR / "lots.sqlite"
REFRESH_AFTER = timedelta(days=1)
# After a failed refresh, wait this long before trying again (IBKR limits Flex requests)
RETRY_AFTER = timedelta(hours=1)


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS flex_lots (
            con_id INTEGER NOT NULL, symbol TEXT, currency TEXT,
            quantity REAL NOT NULL, cost_price REAL, opened TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS flex_trades (
            con_id INTEGER NOT NULL, symbol TEXT, currency TEXT,
            quantity REAL NOT NULL, price REAL, traded TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    return conn


def _meta(conn):
    return {row["key"]: json.loads(row["value"]) for row in conn.execute("SELECT key, value FROM meta")}


def _set_meta(conn, **values):
    conn.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                     [(key, json.dumps(value)) for key, value in values.items()])


def store_report(report, report_date, now):
    """Replaces the stored lots and trades with a freshly parsed report (one transaction)."""
    with _connect() as conn:
        conn.execute("DELETE FROM flex_lots")
        conn.execute("DELETE FROM flex_trades")
        conn.executemany(
            "INSERT INTO flex_lots VALUES (?, ?, ?, ?, ?, ?)",
            [(l["con_id"], l["symbol"], l["currency"], l["quantity"], l["cost_price"], l["opened"].isoformat())
             for l in report["lots"]])
        conn.executemany(
            "INSERT INTO flex_trades VALUES (?, ?, ?, ?, ?, ?)",
            [(t["con_id"], t["symbol"], t["currency"], t["quantity"], t["price"], t["traded"].isoformat())
             for t in report["trades"]])
        _set_meta(conn, last_success=now.isoformat(), last_attempt=now.isoformat(), last_error=None,
                  report_date=report_date.isoformat() if report_date else None)


def _record_failure(message, now):
    with _connect() as conn:
        _set_meta(conn, last_attempt=now.isoformat(), last_error=mask_secrets(message))


def status():
    """For the app: whether Flex is set up, when the lots were last fetched, and the last error."""
    with _connect() as conn:
        meta = _meta(conn)
    return {
        "configured": config.flex_configured(),
        "last_success": meta.get("last_success"),
        "report_date": meta.get("report_date"),
        "last_error": meta.get("last_error"),
    }


def refresh_due(now):
    with _connect() as conn:
        meta = _meta(conn)
    success = meta.get("last_success")
    attempt = meta.get("last_attempt")
    if attempt and meta.get("last_error") and now - datetime.fromisoformat(attempt) < RETRY_AFTER:
        return False
    return not success or now - datetime.fromisoformat(success) >= REFRESH_AFTER


async def refresh(now=None, force=False, fetch=None):
    """Fetches and stores the report if Flex is set up and the last one is a day old (or force).
    Returns True if new lots were stored. Never raises: failures are recorded for status()."""
    now = now or datetime.now(timezone.utc)
    if not config.flex_configured() or not (force or refresh_due(now)):
        return False
    fetch = fetch or flex.fetch_report
    try:
        data = await asyncio.to_thread(fetch, config.flex_token(), config.flex_query_id())
        report = flex.parse_report(data)
        store_report(report, flex.report_date(data), now)
        return True
    except flex.FlexError as exc:
        _record_failure(str(exc), now)
    except Exception as exc:  # a malformed report, a full disk...
        _record_failure(f"Couldn't read the Flex report ({exc.__class__.__name__}).", now)
    return False


async def keep_refreshed(check_every=timedelta(hours=3)):
    """Background task (started with the server): refreshes when due, checking every few hours."""
    while True:
        await refresh()
        await asyncio.sleep(check_every.total_seconds())


def cgt_discount_date(opened):
    """The first day a sale gets the 12-month CGT discount: the ATO counts 12 months without the
    purchase day, so it's the day after the first anniversary (29 Feb anniversaries fall on 28 Feb)."""
    try:
        anniversary = opened.replace(year=opened.year + 1)
    except ValueError:
        anniversary = opened.replace(year=opened.year + 1, day=28)
    return anniversary + timedelta(days=1)


def fifo_open_lots(trades):
    """The buys still held after selling the oldest shares first. trades: dicts with quantity
    (sells negative), price and traded (date). Returns (open lots, shares sold that weren't bought
    in these trades, i.e. bought earlier)."""
    open_lots = []
    sold_unmatched = 0.0
    for trade in sorted(trades, key=lambda t: t["traded"]):
        if trade["quantity"] > 0:
            open_lots.append({"quantity": trade["quantity"], "cost_price": trade["price"], "opened": trade["traded"]})
            continue
        to_sell = -trade["quantity"]
        while to_sell > 0 and open_lots:
            take = min(to_sell, open_lots[0]["quantity"])
            open_lots[0]["quantity"] -= take
            to_sell -= take
            if open_lots[0]["quantity"] <= 1e-9:
                open_lots.pop(0)
        sold_unmatched += to_sell
    return open_lots, sold_unmatched


def _row_date(text):
    return date.fromisoformat(text)


def lots_for(con_id, position_quantity, today=None):
    """A holding's lots with their CGT discount dates, matched to the quantity held now.

    source: "flex_lots" (IBKR's own lots), "flex_trades" (rebuilt from the year's trades, oldest
    sold first) or None (no report yet). unknown_quantity: shares whose purchase date isn't in the
    report (bought before its period, or traded since it was generated).
    """
    today = today or date.today()
    with _connect() as conn:
        lot_rows = conn.execute("SELECT * FROM flex_lots WHERE con_id = ? ORDER BY opened", (con_id,)).fetchall()
        trade_rows = conn.execute("SELECT * FROM flex_trades WHERE con_id = ?", (con_id,)).fetchall()
        meta = _meta(conn)

    if lot_rows:
        source = "flex_lots"
        lots = [{"quantity": r["quantity"], "cost_price": r["cost_price"], "opened": _row_date(r["opened"])} for r in lot_rows]
    elif trade_rows:
        source = "flex_trades"
        trades = [{"quantity": r["quantity"], "price": r["price"], "traded": _row_date(r["traded"])} for r in trade_rows]
        lots, _ = fifo_open_lots(trades)
    else:
        source = None
        lots = []

    # Match to what's held now: if fewer shares are dated than held, the rest are unknown; if more,
    # some were sold since the report, so drop the oldest first (first in, first out)
    dated = sum(l["quantity"] for l in lots)
    excess = dated - position_quantity
    while excess > 1e-9 and lots:
        take = min(excess, lots[0]["quantity"])
        lots[0]["quantity"] -= take
        excess -= take
        if lots[0]["quantity"] <= 1e-9:
            lots.pop(0)
    unknown = max(0.0, position_quantity - sum(l["quantity"] for l in lots))

    result = []
    for lot in lots:
        discount_from = cgt_discount_date(lot["opened"])
        result.append({
            "quantity": round(lot["quantity"], 6),
            "cost_price": lot["cost_price"],
            "opened": lot["opened"].isoformat(),
            "cgt_discount_from": discount_from.isoformat(),
            "days_until_discount": max(0, (discount_from - today).days),
        })
    return {
        "con_id": con_id,
        "source": source,
        "report_date": meta.get("report_date"),
        "lots": result,
        "unknown_quantity": round(unknown, 6),
    }
