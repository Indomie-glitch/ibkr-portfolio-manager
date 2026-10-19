"""Daily prices for the risk analysis (Milestone 8, #98): every stock held, both total return indexes
and the AUD/USD rate, from Yahoo, kept in risk_prices.sqlite and turned into AUD returns for a window.

Yahoo is asked at most once a day per symbol, and only for the days not stored yet. Stock prices are
dividend-adjusted, and Yahoo rewrites a stock's past adjusted prices after each dividend, so every
update also fetches the last couple of weeks again: if those no longer match what's stored, the
symbol's whole history is fetched again.

The maths is in risk.py; the walk-through is in docs/risk-maths.md.
"""
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

import risk
import yahoo
from config import DATA_DIR
from secrets_guard import mask_secrets

DB_PATH = DATA_DIR / "risk_prices.sqlite"

HISTORY_DAYS = 3 * 365 + 45  # three years plus a margin for the window's first day
OVERLAP_DAYS = 14  # about the last 10 trading days, fetched again on every update
MATCH_TOLERANCE = 1e-4  # relative difference that means Yahoo re-adjusted the history
MIN_DAYS = 20  # fewer common days than this is too few for any statistic


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS risk_prices (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,   -- ISO date of the close
            close REAL NOT NULL,  -- dividend-adjusted close, in the symbol's own currency
            PRIMARY KEY (symbol, date)
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS risk_fetches (
            symbol TEXT PRIMARY KEY,
            fetched_on TEXT NOT NULL  -- the local date Yahoo was last asked
        )""")
    return conn


def stored_closes(symbol):
    """{date: close} for a symbol, from the database."""
    with _connect() as conn:
        rows = conn.execute("SELECT date, close FROM risk_prices WHERE symbol = ? ORDER BY date", (symbol,))
        return {date.fromisoformat(d): c for d, c in rows}


def _fetched_on(conn, symbol):
    row = conn.execute("SELECT fetched_on FROM risk_fetches WHERE symbol = ?", (symbol,)).fetchone()
    return date.fromisoformat(row[0]) if row else None


def _matches(stored, fresh):
    """True when every day in both lists has (nearly) the same close."""
    shared = [day for day in fresh if day in stored]
    return all(abs(fresh[day] / stored[day] - 1) <= MATCH_TOLERANCE for day in shared)


async def update(symbol, today, fetch=yahoo.fetch_daily_closes, stale=None):
    """Bring a symbol's stored closes up to date (at most one Yahoo call a day) and return them.

    fetch(symbol, start) -> [(date, close)]; it's a parameter so tests needn't call Yahoo.
    Raises when Yahoo fails and nothing is stored yet; with stored prices the old ones are used
    and the symbol is added to stale (a list), if given.
    """
    with _connect() as conn:
        if _fetched_on(conn, symbol) == today:
            return stored_closes(symbol)
    stored = stored_closes(symbol)
    full_start = today - timedelta(days=HISTORY_DAYS)
    try:
        if stored:
            fresh = dict(await fetch(symbol, max(full_start, max(stored) - timedelta(days=OVERLAP_DAYS))))
            replace = not _matches(stored, fresh)
            if replace:
                fresh = dict(await fetch(symbol, full_start))
        else:
            fresh = dict(await fetch(symbol, full_start))
            replace = True
    except Exception as exc:
        if not stored:
            raise
        print(f"Risk prices for {symbol} not updated: {mask_secrets(exc)}")
        if stale is not None:
            stale.append(symbol)
        return stored
    with _connect() as conn:
        if replace:
            conn.execute("DELETE FROM risk_prices WHERE symbol = ?", (symbol,))
        conn.executemany("INSERT OR REPLACE INTO risk_prices (symbol, date, close) VALUES (?, ?, ?)",
                         [(symbol, day.isoformat(), close) for day, close in fresh.items()])
        conn.execute("INSERT OR REPLACE INTO risk_fetches (symbol, fetched_on) VALUES (?, ?)",
                     (symbol, today.isoformat()))
    return stored_closes(symbol)


@dataclass
class RiskInputs:
    """Everything the risk sections share, for one window."""
    period: str
    start: date  # first day of the window
    dates: list  # the day of each return row (its close)
    holdings: list  # included holdings: con_id, symbol, name, market, currency, yahoo, value_aud, weight
    returns: np.ndarray  # rows = days, columns = holdings: daily returns of each holding's value in AUD
    local_returns: np.ndarray  # the same in each holding's own currency (price return only)
    weights: np.ndarray  # each holding's share of the AUD value of the included holdings
    benchmark_returns: dict  # {"ASX": array, "US": array}: total return index, daily
    fx_returns: np.ndarray  # daily return of one US dollar in AUD
    benchmarks: dict  # {"ASX": {symbol, short, total_return}, "US": ...}
    left_out: list = field(default_factory=list)  # [{con_id, symbol, reason}]
    stale: list = field(default_factory=list)  # symbols whose update failed (older prices used)

    @property
    def days_used(self):
        return len(self.dates)


class NotEnoughData(Exception):
    """Too few holdings or common days to calculate anything."""


async def _benchmark(market, start, today, fetch, stale):
    """The total return index for a market, or its price index when the total return series is
    missing or too short. Returns (info, closes)."""
    choice = yahoo.RISK_BENCHMARKS[market]
    for symbol, total_return in ((choice["symbol"], True), (choice["fallback"], False)):
        try:
            closes = await update(symbol, today, fetch, stale)
        except Exception as exc:
            print(f"Risk prices for {symbol} unavailable: {mask_secrets(exc)}")
            continue
        if closes and risk.covers_window(min(closes), start):
            return {"symbol": symbol, "short": choice["short"], "total_return": total_return}, closes
    raise NotEnoughData(f"No prices for the {choice['short']}")


async def build_inputs(holdings, period, today, fetch=yahoo.fetch_daily_closes):
    """Prices -> aligned AUD returns for the window.

    holdings: [{con_id, symbol, name, market ("ASX"/"US"/None), currency, yahoo (symbol or None),
    market_value (in its own currency)}].
    """
    start = risk.window_start(period, today)
    stale, left_out = [], []

    audusd = await update(yahoo.AUDUSD, today, fetch, stale)
    if not audusd:
        raise NotEnoughData("No AUD/USD exchange rates")
    benchmarks, index_closes = {}, {}
    for market in ("ASX", "US"):
        benchmarks[market], index_closes[market] = await _benchmark(market, start, today, fetch, stale)

    latest_rate = audusd[max(audusd)]
    included, aud_prices, local_prices = [], {}, {}
    for holding in holdings:
        def leave_out(reason):
            left_out.append({"con_id": holding["con_id"], "symbol": holding["symbol"], "reason": reason})

        if holding["currency"] not in ("AUD", "USD"):
            leave_out(f"Only AUD and USD holdings are included ({holding['currency']})")
            continue
        if not holding.get("yahoo"):
            leave_out("No daily prices for this exchange")
            continue
        if not holding.get("market_value") or holding["market_value"] <= 0:
            leave_out("No market value")
            continue
        try:
            closes = await update(holding["yahoo"], today, fetch, stale)
        except Exception as exc:
            print(f"Risk prices for {holding['yahoo']} unavailable: {mask_secrets(exc)}")
            leave_out("Couldn't get its prices from Yahoo")
            continue
        if not closes or not risk.covers_window(min(closes), start):
            first = min(closes).strftime("%-d %b %Y") if closes else None
            leave_out(f"Prices only from {first}" if first else "No prices")
            continue
        in_window = {day: c for day, c in closes.items() if day >= start}
        key = str(holding["con_id"])
        local_prices[key] = in_window
        aud_prices[key] = in_window if holding["currency"] == "AUD" else risk.to_aud(in_window, audusd)
        value_aud = holding["market_value"] if holding["currency"] == "AUD" else holding["market_value"] / latest_rate
        included.append({**{k: holding[k] for k in ("con_id", "symbol", "name", "market", "currency", "yahoo")},
                         "value_aud": value_aud})

    if not included:
        raise NotEnoughData("No holdings have prices for the whole period")

    window = lambda closes: {day: c for day, c in closes.items() if day >= start}  # noqa: E731
    keys = [str(h["con_id"]) for h in included]
    series = {**{f"aud:{k}": aud_prices[k] for k in keys}, **{f"local:{k}": local_prices[k] for k in keys},
              "index:ASX": window(index_closes["ASX"]), "index:US": window(index_closes["US"]),
              "fx": window(audusd)}
    dates, prices = risk.align(series)
    if len(dates) < MIN_DAYS + 1:
        raise NotEnoughData(f"Only {max(len(dates) - 1, 0)} days with prices for everything")

    n = len(keys)
    returns_all = risk.simple_returns(prices)
    w = risk.weights([h["value_aud"] for h in included])
    for holding, weight in zip(included, w):
        holding["weight"] = float(weight)
    return RiskInputs(
        period=period, start=start, dates=dates[1:], holdings=included,
        returns=returns_all[:, :n], local_returns=returns_all[:, n:2 * n], weights=w,
        benchmark_returns={"ASX": returns_all[:, 2 * n], "US": returns_all[:, 2 * n + 1]},
        fx_returns=risk.fx_returns(prices[:, 2 * n + 2]), benchmarks=benchmarks,
        left_out=left_out, stale=sorted(set(stale)),
    )
