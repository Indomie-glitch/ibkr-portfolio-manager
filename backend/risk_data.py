"""Daily prices for the risk analysis (Milestone 8, #98): every stock held, the market indexes and
the exchange rates against the account's base currency (#271), from Yahoo, kept in
risk_prices.sqlite and turned into base currency returns for a window.

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

import fx
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


# ---------- Past crashes for the stress tests (#241) ----------

# start: the close on or before it is the level before; end: the close on or before it is the low
SCENARIOS = {
    "gfc": {"name": "GFC 2008 replay", "label": "Sep 2008 to Mar 2009",
            "start": date(2008, 8, 31), "end": date(2009, 3, 9)},
    "covid": {"name": "COVID crash replay", "label": "19 Feb to 23 Mar 2020",
              "start": date(2020, 2, 19), "end": date(2020, 3, 23)},
    "tech2022": {"name": "2022 tech sell-off replay", "label": "Jan to Dec 2022",
                 "start": date(2021, 12, 31), "end": date(2022, 12, 30)},
}
SCENARIO_FETCH = (date(2008, 8, 1), date(2023, 1, 10))  # one Yahoo call per symbol covers all three


def _scenario_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS risk_scenarios (
            symbol TEXT NOT NULL,
            scenario TEXT NOT NULL,
            ret REAL,  -- the symbol's return over the scenario; NULL if it had no prices then
            PRIMARY KEY (symbol, scenario)
        )""")


async def scenario_returns(symbols, fetch=yahoo.fetch_daily_closes):
    """{symbol: {scenario: return or None}} for the past crashes.

    A return over a past period never changes (a later dividend adjustment scales both closes alike),
    so each symbol is fetched once and kept. A symbol Yahoo has no prices for in those years is kept
    as None; a failed call is left out and tried again next time.
    """
    result = {}
    with _connect() as conn:
        _scenario_table(conn)
        for symbol, scenario, ret in conn.execute("SELECT symbol, scenario, ret FROM risk_scenarios"):
            result.setdefault(symbol, {})[scenario] = ret
    for symbol in symbols:
        if symbol in result:
            continue
        try:
            closes = dict(await fetch(symbol, *SCENARIO_FETCH))
        except yahoo.YahooUnavailable:
            closes = {}
        except Exception as exc:
            print(f"Stress test prices for {symbol} unavailable: {mask_secrets(exc)}")
            continue
        rets = {key: risk.period_return(closes, s["start"], s["end"]) for key, s in SCENARIOS.items()}
        with _connect() as conn:
            _scenario_table(conn)
            conn.executemany("INSERT OR REPLACE INTO risk_scenarios (symbol, scenario, ret) VALUES (?, ?, ?)",
                             [(symbol, key, ret) for key, ret in rets.items()])
        result[symbol] = rets
    return {symbol: result[symbol] for symbol in symbols if symbol in result}


@dataclass
class RiskInputs:
    """Everything the risk sections share, for one window. Money is in the account's base currency."""
    period: str
    start: date  # first day of the window
    base_date: date  # the first close in the window: the starting point of the first return
    dates: list  # the day of each return row (its close)
    holdings: list  # included holdings: con_id, symbol, name, market, currency, yahoo, sector, value_base, weight
    returns: np.ndarray  # rows = days, columns = holdings: daily returns of each holding's value in base currency
    local_returns: np.ndarray  # the same in each holding's own currency (price return only)
    weights: np.ndarray  # each holding's share of the base currency value of the included holdings
    benchmark_returns: dict  # {"ASX": array, "US": array, and the home market's if another}: index, daily
    fx_returns: dict  # {currency: array}: daily return of one unit of each foreign currency in base currency
    benchmarks: dict  # {"ASX": {symbol, short, total_return}, "US": ..., and the home market's}
    left_out: list = field(default_factory=list)  # [{con_id, symbol, reason}]
    cash_base: float = None  # the account's cash in base currency (set by the route; not part of any weight)
    scenarios: dict = field(default_factory=dict)  # scenario_returns() for the holdings, indexes and rate pairs
    stale: list = field(default_factory=list)  # symbols whose update failed (older prices used)
    base_currency: str = "AUD"  # the account's currency (GET /account)
    home_market: str = "ASX"  # the market whose index attribution compares with (yahoo.HOME_MARKETS)
    notes: list = field(default_factory=list)  # extra lines for meta.benchmark_note

    @property
    def days_used(self):
        return len(self.dates)

    def pair(self, currency):
        """The exchange rate series a foreign currency uses against the base currency."""
        return fx.Pair(currency, self.base_currency)


class NotEnoughData(Exception):
    """Too few holdings or common days to calculate anything."""


# The markets every analysis compares with: the holdings' own markets
MARKETS = ("ASX", "US")
# The currency each market's shares trade in (attribution's currency step per market)
MARKET_CURRENCY = {"ASX": "AUD", "US": "USD", "SG": "SGD"}


def home_market(base):
    """(market, note): the home index for an account in this currency, and a note when there is
    none and the S&P 500 is used instead."""
    if base in yahoo.HOME_MARKETS:
        return yahoo.HOME_MARKETS[base], None
    short = yahoo.RISK_BENCHMARKS[yahoo.DEFAULT_HOME]["short"]
    return yahoo.DEFAULT_HOME, f"No home market index for {base} accounts: attribution compares with the {short}"


def benchmark_symbols(markets):
    """The index symbols (total return and fallback) for these markets."""
    return [s for m in markets for s in (yahoo.RISK_BENCHMARKS[m]["symbol"], yahoo.RISK_BENCHMARKS[m]["fallback"]) if s]


async def _benchmark(market, start, today, fetch, stale):
    """The total return index for a market, or its price index when the total return series is
    missing or too short (or, like the STI, there's only a price index). Returns (info, closes)."""
    choice = yahoo.RISK_BENCHMARKS[market]
    tries = ((choice["symbol"], not choice.get("price_only")), (choice["fallback"], False))
    for symbol, total_return in tries:
        if not symbol:
            continue
        try:
            closes = await update(symbol, today, fetch, stale)
        except Exception as exc:
            print(f"Risk prices for {symbol} unavailable: {mask_secrets(exc)}")
            continue
        if closes and risk.covers_window(min(closes), start):
            return {"symbol": symbol, "short": choice["short"], "total_return": total_return}, closes
    raise NotEnoughData(f"No prices for the {choice['short']}")


async def build_inputs(holdings, period, today, fetch=yahoo.fetch_daily_closes, base="AUD"):
    """Prices -> aligned base currency returns for the window.

    holdings: [{con_id, symbol, name, market ("ASX"/"US"/None), currency, yahoo (symbol or None),
    market_value (in its own currency), sector (optional)}]. base: the account's currency.
    """
    start = risk.window_start(period, today)
    stale, left_out = [], []
    home, home_note = home_market(base)

    # Exchange rates: the US dollar's always (the US market is always compared with), plus every
    # other currency of a holding with prices. Holdings in a currency without rates are left out;
    # without the US dollar's there's nothing to compare with.
    rates = {}
    for currency in sorted({"USD"} | {h["currency"] for h in holdings if h.get("currency") and h.get("yahoo")}):
        if currency == base:
            continue
        pair = fx.Pair(currency, base)
        try:
            closes = await update(pair.symbol, today, fetch, stale)
        except Exception as exc:
            if currency == "USD":
                raise
            print(f"Risk prices for {pair.symbol} unavailable: {mask_secrets(exc)}")
            closes = {}
        if closes:
            rates[currency] = closes
        elif currency == "USD":
            raise NotEnoughData(f"No {pair.label} exchange rates")
    benchmarks, index_closes = {}, {}
    for market in dict.fromkeys((*MARKETS, home)):
        benchmarks[market], index_closes[market] = await _benchmark(market, start, today, fetch, stale)

    included, base_prices, local_prices = [], {}, {}
    for holding in holdings:
        def leave_out(reason):
            left_out.append({"con_id": holding["con_id"], "symbol": holding["symbol"], "reason": reason})

        currency = holding["currency"]
        if not holding.get("yahoo"):
            leave_out("No daily prices for this exchange")
            continue
        if currency != base and currency not in rates:
            leave_out(f"No exchange rates for {currency}")
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
        if currency == base:
            base_prices[key], value_base = in_window, holding["market_value"]
        else:
            pair, quotes = fx.Pair(currency, base), rates[currency]
            base_prices[key] = pair.convert(in_window, quotes)
            value_base = pair.to_base(holding["market_value"], quotes[max(quotes)])
        included.append({**{k: holding[k] for k in ("con_id", "symbol", "name", "market", "currency", "yahoo")},
                         "sector": holding.get("sector"), "quantity": holding.get("quantity"), "value_base": value_base})

    if not included:
        raise NotEnoughData("No holdings have prices for the whole period")

    window = lambda closes: {day: c for day, c in closes.items() if day >= start}  # noqa: E731
    keys = [str(h["con_id"]) for h in included]
    series = {**{f"base:{k}": base_prices[k] for k in keys}, **{f"local:{k}": local_prices[k] for k in keys},
              **{f"index:{m}": window(index_closes[m]) for m in benchmarks},
              **{f"fx:{c}": window(rates[c]) for c in rates}}
    dates, prices = risk.align(series)
    if len(dates) < MIN_DAYS + 1:
        raise NotEnoughData(f"Only {max(len(dates) - 1, 0)} days with prices for everything")

    n = len(keys)
    columns = {name: i for i, name in enumerate(series)}
    returns_all = risk.simple_returns(prices)
    w = risk.weights([h["value_base"] for h in included])
    for holding, weight in zip(included, w):
        holding["weight"] = float(weight)
    return RiskInputs(
        period=period, start=start, base_date=dates[0], dates=dates[1:], holdings=included,
        returns=returns_all[:, :n], local_returns=returns_all[:, n:2 * n], weights=w,
        benchmark_returns={m: returns_all[:, columns[f"index:{m}"]] for m in benchmarks},
        fx_returns={c: fx.Pair(c, base).returns(prices[:, columns[f"fx:{c}"]]) for c in rates},
        benchmarks=benchmarks, left_out=left_out, stale=sorted(set(stale)),
        base_currency=base, home_market=home, notes=[home_note] if home_note else [],
    )
