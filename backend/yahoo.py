"""Yahoo Finance (yfinance) lookups for data IB doesn't provide.

yfinance is blocking code, so every call runs in a worker thread (asyncio.to_thread) to keep
the event loop free for ib_async. Calls also run one at a time: yfinance keeps a small
SQLite cache that reports "database is locked" when used from several threads at once.
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import yfinance as yf

US_EXCHANGES = {"NASDAQ", "NYSE", "ARCA", "AMEX", "BATS", "IEX", "NYSE MKT", "NYSEARCA"}

# Total return indexes (dividends reinvested), so they compare like for like with
# the stock's dividend-adjusted return
BENCHMARKS = {
    "ASX": {"symbol": "^AXJT", "name": "S&P/ASX 200", "short": "ASX 200"},
    "US": {"symbol": "^SP500TR", "name": "S&P 500", "short": "S&P 500"},
}

_yf_lock = asyncio.Lock()


class YahooUnavailable(Exception):
    """Yahoo returned nothing useful for this symbol."""


def yahoo_symbol(contract):
    """Map an IB contract to its Yahoo ticker: TLS on ASX -> "TLS.AX", AAPL -> "AAPL".

    Returns None for exchanges we don't map yet.
    """
    # IB writes share classes with a space ("BRK B"); Yahoo uses a dash ("BRK-B")
    symbol = contract.symbol.replace(" ", "-")
    exchange = contract.primaryExchange or contract.exchange
    if exchange == "ASX":
        return f"{symbol}.AX"
    if exchange in US_EXCHANGES:
        return symbol
    return None


def benchmark_for(contract):
    return BENCHMARKS["ASX"] if (contract.primaryExchange or contract.exchange) == "ASX" else BENCHMARKS["US"]


async def _run(func, *args):
    async with _yf_lock:
        return await asyncio.to_thread(func, *args)


def _date(timestamp, tz_name=None):
    """Unix seconds -> "2026-08-12".

    Yahoo stores date-only fields (ex-dividend date, fiscal year end) as midnight UTC, so those
    use UTC. Earnings are a real time of day, so they use the exchange's time zone.
    """
    if not timestamp:
        return None
    try:
        tz = ZoneInfo(tz_name) if tz_name else timezone.utc
    except Exception:
        tz = timezone.utc
    return datetime.fromtimestamp(timestamp, tz=tz).date().isoformat()


def _number(value):
    return value if isinstance(value, (int, float)) and value == value else None  # value == value drops NaN


# ---------- Company info (one call feeds both About and the slow key statistics) ----------

def _fetch_info(symbol):
    info = yf.Ticker(symbol).info or {}
    if not (info.get("longName") or info.get("shortName")):
        raise YahooUnavailable(f"Yahoo has no company data for {symbol}")
    return info


async def fetch_info(symbol):
    return await _run(_fetch_info, symbol)


def profile_from_info(info):
    website = info.get("website")
    return {
        "long_name": info.get("longName") or info.get("shortName"),
        "description": info.get("longBusinessSummary"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "employees": _number(info.get("fullTimeEmployees")),
        "fiscal_year_end": _date(info.get("lastFiscalYearEnd")),
        "website": website,
    }


def stats_from_info(info):
    tz = info.get("exchangeTimezoneName")
    return {
        "fifty_two_week_low": _number(info.get("fiftyTwoWeekLow")),
        "fifty_two_week_high": _number(info.get("fiftyTwoWeekHigh")),
        "market_cap": _number(info.get("marketCap")),
        "beta": _number(info.get("beta")),
        "pe_ttm": _number(info.get("trailingPE")),
        "eps_ttm": _number(info.get("trailingEps")),
        "earnings_date": _date(info.get("earningsTimestampStart") or info.get("earningsTimestamp"), tz),
        "dividend_rate": _number(info.get("dividendRate")),
        # yfinance 1.x already gives this as a percentage (4.53 means 4.53%)
        "dividend_yield": _number(info.get("dividendYield")),
        "ex_dividend_date": _date(info.get("exDividendDate")),
        "target_price": _number(info.get("targetMeanPrice")),
        "currency": info.get("currency"),
    }


# ---------- News ----------

LEGAL_SUFFIXES = {"limited", "ltd", "ltd.", "inc", "inc.", "incorporated", "corporation", "corp", "corp.", "plc", "company", "co", "co."}


def search_name(long_name):
    """Company name without legal suffixes: "Telstra Group Limited" -> "Telstra Group", "Apple Inc." -> "Apple"."""
    words = long_name.replace(",", "").split()
    while len(words) > 1 and words[-1].lower() in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def _fetch_us_name(ib_symbol):
    """Long name of whatever trades under this bare symbol in the US (None if nothing)."""
    try:
        info = yf.Ticker(ib_symbol).info or {}
    except Exception:
        return None
    return info.get("longName") or info.get("shortName")


async def fetch_us_name(ib_symbol):
    return await _run(_fetch_us_name, ib_symbol)


def _normalise_title(title):
    title = re.sub(r"^(update|updated|corrected)\s*\d*\s*:\s*", "", title.strip(), flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _title_patterns(ib_symbol, long_name, short_name, is_asx, bare_ticker_ok):
    """Ways a headline can name the company. Names ignore case; tickers must match exactly."""
    names = {search_name(long_name), short_name}
    patterns = [re.compile(rf"\b{re.escape(n)}\b", re.IGNORECASE) for n in names if n and n != ib_symbol]
    if is_asx:
        patterns.append(re.compile(rf"\bASX:\s?{re.escape(ib_symbol)}\b|\b{re.escape(ib_symbol)}\.AX\b"))
    if bare_ticker_ok:
        patterns.append(re.compile(rf"\b{re.escape(ib_symbol)}\b"))
    return patterns


def _fetch_news(symbol, ib_symbol, long_name, short_name, is_asx, bare_ticker_ok):
    """Search Yahoo by company name (Ticker.news currently returns 404 from Yahoo), keep
    headlines that name the company, and drop repeats."""
    results = list(yf.Search(search_name(long_name), news_count=20, max_results=1).news)
    if len(results) < 5:
        results += yf.Search(symbol, news_count=20, max_results=1).news

    patterns = _title_patterns(ib_symbol, long_name, short_name, is_asx, bare_ticker_ok)
    seen, items = set(), []
    for n in results:
        title = (n.get("title") or "").strip()
        key = _normalise_title(title)
        # Related tickers are too loosely tagged to trust on their own, so the headline must name the company
        if not title or not n.get("link") or key in seen or not any(p.search(title) for p in patterns):
            continue
        seen.add(key)
        published = n.get("providerPublishTime")
        items.append({
            "title": title,
            "publisher": n.get("publisher"),
            "url": n["link"],
            "published": datetime.fromtimestamp(published, tz=timezone.utc).isoformat() if published else None,
        })
    items.sort(key=lambda i: i["published"] or "", reverse=True)
    return items[:10]


async def fetch_news(symbol, ib_symbol, long_name, short_name, is_asx, bare_ticker_ok):
    return await _run(_fetch_news, symbol, ib_symbol, long_name, short_name, is_asx, bare_ticker_ok)


# ---------- Performance ----------

def _closes(symbol):
    # auto_adjust folds dividends and splits into the prices, so returns are total returns
    history = yf.Ticker(symbol).history(period="6y", interval="1d", auto_adjust=True)
    closes = history["Close"].dropna() if "Close" in history else None
    if closes is None or closes.empty:
        raise YahooUnavailable(f"Yahoo has no price history for {symbol}")
    closes.index = closes.index.tz_localize(None)  # compare plain dates
    return closes


def _return_since(closes, start):
    """Percent change from the last close on or before start to the latest close."""
    before = closes[closes.index <= start]
    if before.empty:
        return None  # not listed that long ago
    return (closes.iloc[-1] / before.iloc[-1] - 1) * 100


def _fetch_performance(symbol, benchmark_symbol):
    stock = _closes(symbol)
    bench = _closes(benchmark_symbol)
    latest = stock.index[-1]
    starts = {
        "ytd": datetime(latest.year - 1, 12, 31),
        "1y": latest - timedelta(days=365),
        "3y": latest - timedelta(days=3 * 365),
        "5y": latest - timedelta(days=5 * 365),
    }
    return [
        {"period": key, "stock": _return_since(stock, start), "benchmark": _return_since(bench, start)}
        for key, start in starts.items()
    ]


async def fetch_performance(symbol, benchmark_symbol):
    return await _run(_fetch_performance, symbol, benchmark_symbol)
