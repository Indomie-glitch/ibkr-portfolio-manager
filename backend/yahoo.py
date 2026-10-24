"""Yahoo Finance (yfinance) lookups for data IB doesn't provide.

yfinance is blocking code, so every call runs in a worker thread (asyncio.to_thread) to keep
the event loop free for ib_async. Calls also run one at a time: yfinance keeps a small
SQLite cache that reports "database is locked" when used from several threads at once.
"""
import asyncio
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import yfinance as yf

import config

if config.IN_APP:
    # Keep yfinance's cache with the app's data instead of the user's shared ~/Library/Caches
    yf.set_tz_cache_location(str(config.DATA_DIR / "yfinance"))

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
    exchange = contract.primaryExchange or contract.exchange
    if exchange == "ASX":
        return ticker_for(contract.symbol, "ASX")
    if exchange in US_EXCHANGES:
        return ticker_for(contract.symbol, "US")
    return None


def ticker_for(symbol, market):
    """IB's symbol on a market ("ASX" or "US") -> Yahoo's ticker: ("TLS", "ASX") -> "TLS.AX"."""
    # IB writes share classes with a space ("BRK B"); Yahoo uses a dash ("BRK-B")
    symbol = symbol.replace(" ", "-")
    return f"{symbol}.AX" if market == "ASX" else symbol


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
    """A plain float, or None for missing/NaN values (yfinance mixes numpy and Python numbers)."""
    return float(value) if isinstance(value, (int, float)) and value == value else None  # value == value drops NaN


# ---------- Company info (one call feeds both About and the slow key statistics) ----------

def _fetch_info(symbol):
    info = yf.Ticker(symbol).info or {}
    if not (info.get("longName") or info.get("shortName")):
        raise YahooUnavailable(f"Yahoo has no company data for {symbol}")
    return info


async def fetch_info(symbol):
    return await _run(_fetch_info, symbol)


def web_link(url):
    """The URL if it's an http(s) link, else None: links from Yahoo are shown in the app and opened in
    the browser, so nothing else (javascript:, file:, …) gets through (#202)."""
    if isinstance(url, str) and re.match(r"https?://[^\s/]+", url.strip(), re.IGNORECASE):
        return url.strip()
    return None


def profile_from_info(info):
    website = web_link(info.get("website"))
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


# ---------- Executives and directors (yfinance's companyOfficers, #112) ----------

TITLE_PREFIXES = re.compile(r"^(?:mr|mrs|ms|miss|mx|dr|prof|professor|sir|dame|hon|rev)\.?\s+", re.IGNORECASE)
# Degrees and professional letters after a name: EMBA, CA, BMS, C.A., J.D., Ph.D., B.Sc., B.Com., L.L.B.
CREDENTIAL = re.compile(r"^(?:[A-Z]{2,6}|(?:[A-Za-z]{1,4}\.){2,}|[A-Za-z]{1,3}\.[A-Za-z]{2,4}\.?)$")
# A board seat: "Director", "Chairman", "Chair of the Board" but not "Director of Investor Relations"
BOARD_SEAT = re.compile(r"\bdirector\b(?!\s+of\b)|\bchair(?:man|woman|person)?\b", re.IGNORECASE)
# What makes someone part of management
MANAGEMENT = re.compile(
    r"\b(?:chief|ceo|cfo|coo|cto|cio|cmo|cro|president|vp|vice president|executive|officer|md|managing|"
    r"general counsel|general manager|secretary|treasurer|controller|head of|founder|partner)\b",
    re.IGNORECASE)


def clean_person_name(name):
    """"Mr. Matthew  Comyn EMBA" -> "Matthew Comyn": no honorific, no degrees, single spaces."""
    text = TITLE_PREFIXES.sub("", " ".join(str(name or "").split()))
    text = text.split(",")[0].strip()
    words = text.split()
    while len(words) > 2 and CREDENTIAL.match(words[-1]):
        words.pop()
    return " ".join(words)


def classify_title(title):
    """(is_executive, is_director) from a job title. Yahoo lists executives and board members
    together. Someone is a director if the title has a board seat ("CEO & Director" is both);
    an executive if it names a management role, and also when it names nothing at all (a listed
    officer is management unless the title says they only sit on the board)."""
    text = str(title or "")
    is_director = bool(BOARD_SEAT.search(text))
    # "Non-Executive Director" is a board seat only; its "executive" must not count as management
    management_text = re.sub(r"non[-\s]?executive", "", text, flags=re.IGNORECASE)
    is_executive = bool(MANAGEMENT.search(management_text)) or not is_director
    return is_executive, is_director


def person_from_officer(officer, pay_currency=None):
    is_executive, is_director = classify_title(officer.get("title"))
    pay = _number(officer.get("totalPay"))
    return {
        "name": clean_person_name(officer.get("name")),
        "listed_as": " ".join(str(officer.get("name") or "").split()),
        "title": officer.get("title"),
        "is_executive": is_executive,
        "is_director": is_director,
        "age": int(officer["age"]) if _number(officer.get("age")) else None,
        "year_born": int(officer["yearBorn"]) if _number(officer.get("yearBorn")) else None,
        # Yahoo doesn't say when someone started, so this stays empty until another source fills it
        "year_started": None,
        "pay": pay,
        "pay_currency": pay_currency if pay is not None else None,
        "pay_fiscal_year": int(officer["fiscalYear"]) if pay is not None and _number(officer.get("fiscalYear")) else None,
        # Wikipedia / Wikidata links for the Connections map (#113, #114): Yahoo has none, so these are
        # filled by matching people later
        "wikidata_id": None,
        "wikipedia_url": None,
    }


def executives_from_info(info):
    """{executives, directors}: management (each with is_director when they also sit on the board)
    and board-only members, which #113 will complete from the proxy statement or annual report."""
    currency = info.get("financialCurrency") or info.get("currency")
    people = [person_from_officer(o, currency) for o in (info.get("companyOfficers") or []) if o.get("name")]
    return {
        "executives": [p for p in people if p["is_executive"]],
        "directors": [p for p in people if not p["is_executive"]],
        "source": "Yahoo Finance",
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
        if not title or not web_link(n.get("link")) or key in seen or not any(p.search(title) for p in patterns):
            continue
        seen.add(key)
        published = n.get("providerPublishTime")
        items.append({
            "title": title,
            "publisher": n.get("publisher"),
            "url": web_link(n["link"]),
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


# ---------- Financial statements, dividends and benchmark prices (for the AI summary) ----------

# Price indexes for short-term "why did it move" comparisons. These match IB's price-only
# history; the Performance section uses total return indexes instead (BENCHMARKS above).
PRICE_INDEXES = {"ASX": "^AXJO", "US": "^GSPC"}


def _row(frame, name):
    """One line of a yfinance statement as {date: value}, skipping empty years."""
    if frame is None or name not in frame.index:
        return {}
    return {col.date(): float(v) for col, v in frame.loc[name].items() if v == v}  # v == v drops NaN


def _fetch_financials(symbol):
    ticker = yf.Ticker(symbol)
    income = ticker.income_stmt
    balance = ticker.balance_sheet
    if income is None or income.empty:
        raise YahooUnavailable(f"Yahoo has no financial statements for {symbol}")

    # Unadjusted closes, so past P/E uses the price people actually paid at the time
    history = ticker.history(period="6y", interval="1d", auto_adjust=False)
    closes = history["Close"].dropna() if "Close" in history else None
    if closes is not None:
        closes.index = closes.index.tz_localize(None).date

    def price_on(day):
        if closes is None:
            return None
        before = closes[closes.index <= day]
        return float(before.iloc[-1]) if len(before) else None

    eps = _row(income, "Diluted EPS")
    latest_balance = balance.columns[0].date() if balance is not None and not balance.empty else None
    surprise = None
    try:
        earnings = ticker.earnings_history
        if earnings is not None and len(earnings):
            last = earnings.iloc[-1]
            surprise = {
                "period_end": earnings.index[-1].date().isoformat() if hasattr(earnings.index[-1], "date") else str(earnings.index[-1]),
                "eps_actual": _number(last.get("epsActual")),
                "eps_estimate": _number(last.get("epsEstimate")),
                "surprise_pct": _number(last.get("surprisePercent") * 100) if _number(last.get("surprisePercent")) is not None else None,  # Yahoo gives 0.0674 for 6.74%
            }
    except Exception:
        surprise = None  # Yahoo often has no estimates for ASX companies

    return {
        "revenue": _row(income, "Total Revenue"),
        "net_income": _row(income, "Net Income"),
        "operating_income": _row(income, "Operating Income"),
        "diluted_eps": eps,
        "price_at_year_end": {day: price_on(day) for day in eps},
        "total_debt": _row(balance, "Total Debt").get(latest_balance),
        "cash": _row(balance, "Cash And Cash Equivalents").get(latest_balance),
        "stockholders_equity": _row(balance, "Stockholders Equity").get(latest_balance),
        "balance_date": latest_balance,
        "last_earnings": surprise,
    }


async def fetch_financials(symbol):
    return await _run(_fetch_financials, symbol)


def _fetch_dividends(symbol):
    # Ticker.dividends returns an empty list when the request fails, which looks the same as
    # "pays no dividends". Price history with raise_errors=True fails loudly instead.
    history = yf.Ticker(symbol).history(period="2y", interval="1d", actions=True, raise_errors=True)
    if history is None or history.empty:
        raise YahooUnavailable(f"Yahoo returned no price history for {symbol}")
    paid = history["Dividends"] if "Dividends" in history else []
    return [(day.date(), float(amount)) for day, amount in paid.items() if amount > 0]


async def fetch_dividends(symbol):
    """All past dividends as [(ex-date, amount per share)]; empty if the company pays none."""
    return await _run(_fetch_dividends, symbol)


def _fetch_index_closes(index_symbol):
    history = yf.Ticker(index_symbol).history(period="6mo", interval="1d", auto_adjust=False)
    closes = history["Close"].dropna() if "Close" in history else None
    if closes is None or closes.empty:
        raise YahooUnavailable(f"Yahoo has no prices for {index_symbol}")
    return [(day.date(), float(v)) for day, v in closes.items()]


async def fetch_index_closes(index_symbol):
    return await _run(_fetch_index_closes, index_symbol)


def _fetch_index_intraday(index_symbol):
    # 5-minute bars reach back about 60 days; a month is enough for "since the last summary"
    history = yf.Ticker(index_symbol).history(period="1mo", interval="5m", auto_adjust=False)
    closes = history["Close"].dropna() if "Close" in history else None
    if closes is None or closes.empty:
        raise YahooUnavailable(f"Yahoo has no intraday prices for {index_symbol}")
    return [(moment.to_pydatetime(), float(v)) for moment, v in closes.items()]


async def fetch_index_intraday(index_symbol):
    """[(bar start time with time zone, close)] in 5-minute bars, about the last month."""
    return await _run(_fetch_index_intraday, index_symbol)


# ---------- Daily closes for the risk analysis (Milestone 8) ----------

# Total return indexes for comparisons with the market (dividends on both sides); the price
# indexes are the fallback when Yahoo has no total return series
RISK_BENCHMARKS = {
    "ASX": {"symbol": "^AXJT", "fallback": "^AXJO", "short": "ASX 200"},
    "US": {"symbol": "^SP500TR", "fallback": "^GSPC", "short": "S&P 500"},
    # Yahoo has no total return series for the Straits Times Index: its price index is all there is
    "SG": {"symbol": "^STI", "fallback": None, "short": "STI", "price_only": True},
}
# The account's home market index, by its base currency (#271): the Risk page's attribution
# compares with it. One line per currency; any other currency uses DEFAULT_HOME, with a note.
HOME_MARKETS = {
    "AUD": "ASX",  # S&P/ASX 200
    "SGD": "SG",  # Straits Times Index
    "USD": "US",  # S&P 500
}
DEFAULT_HOME = "US"


def _fetch_fx_rate(symbol):
    closes = yf.Ticker(symbol).history(period="5d", interval="1d")["Close"].dropna()
    if closes.empty or closes.iloc[-1] <= 0:
        raise YahooUnavailable(f"Yahoo has no rate for {symbol}")
    return float(closes.iloc[-1])


async def fetch_fx_rate(symbol):
    """The latest rate of a currency pair such as USDSGD=X (SGD per US dollar)."""
    return await _run(_fetch_fx_rate, symbol)


SESSION_DONE = time(16, 30)  # ASX and US shares and indexes have closed by then, local time


def finished_days(rows, symbol, now=None):
    """Only the days whose session has finished: [(aware datetime, close)] -> [(date, close)].

    While a market is open, Yahoo's row for the current day holds the latest price, not the close
    (#264). It's left out until the session is over: after 4:30 pm in the exchange's time zone for
    shares and indexes, and not at all on the current day for currencies ("=X"), which trade around
    the clock.
    """
    now = now or datetime.now(timezone.utc)
    out = []
    for moment, close in rows:
        local_now = now.astimezone(moment.tzinfo) if moment.tzinfo else now
        day = moment.date()
        if day > local_now.date():
            continue
        if day == local_now.date() and (symbol.endswith("=X") or local_now.time() < SESSION_DONE):
            continue
        out.append((day, close))
    return out


def _fetch_daily_closes(symbol, start, end=None):
    # auto_adjust folds dividends and splits into the prices, so a stock's returns are total returns
    history = yf.Ticker(symbol).history(start=start.isoformat(), end=end.isoformat() if end else None,
                                        interval="1d", auto_adjust=True)
    closes = history["Close"].dropna() if "Close" in history else None
    if closes is None or closes.empty:
        raise YahooUnavailable(f"Yahoo has no daily prices for {symbol}")
    return finished_days([(moment.to_pydatetime(), float(v)) for moment, v in closes.items() if v > 0], symbol)


async def fetch_daily_closes(symbol, start, end=None):
    """[(date, close)] from start to end (or the latest close), dividend-adjusted."""
    return await _run(_fetch_daily_closes, symbol, start, end)


# ---------- Altman Z score inputs (#244) ----------

def _latest(frame, *names):
    """The most recent value of the first of these statement lines that Yahoo has."""
    for name in names:
        values = _row(frame, name)
        if values:
            return values[max(values)]
    return None


def _fetch_altman_inputs(symbol):
    ticker = yf.Ticker(symbol)
    balance, income = ticker.balance_sheet, ticker.income_stmt
    if balance is None or balance.empty or income is None or income.empty:
        raise YahooUnavailable(f"Yahoo has no annual accounts for {symbol}")
    current_assets = _latest(balance, "Current Assets")
    current_liabilities = _latest(balance, "Current Liabilities")
    working_capital = _latest(balance, "Working Capital")
    if working_capital is None and current_assets is not None and current_liabilities is not None:
        working_capital = current_assets - current_liabilities
    return {
        "balance_date": balance.columns[0].date().isoformat(),
        "total_assets": _latest(balance, "Total Assets"),
        "working_capital": working_capital,
        "retained_earnings": _latest(balance, "Retained Earnings"),
        "total_liabilities": _latest(balance, "Total Liabilities Net Minority Interest", "Total Liabilities"),
        "ebit": _latest(income, "EBIT", "Operating Income"),
        "revenue": _latest(income, "Total Revenue", "Operating Revenue"),
    }


async def fetch_altman_inputs(symbol):
    """The latest annual balance sheet and income statement lines the Altman Z score needs."""
    return await _run(_fetch_altman_inputs, symbol)


# ---------- Market data for index members (constituents.py) ----------

# Yahoo's codes for the US exchanges (NASDAQ, NYSE, NYSE American, Cboe BZX, NYSE Arca); leaving out
# over-the-counter listings halves the pages needed to reach every S&P 500 member
SCREEN_EXCHANGES = {"ASX": ["ASX"], "US": ["NMS", "NYQ", "NGM", "NCM", "ASE", "BTS", "PCX"]}
SCREEN_PAGE = 250  # the most Yahoo's screener sends at once
SCREEN_MAX_PAGES = {"ASX": 2, "US": 8}


def ib_symbol(yahoo_ticker, market):
    """Yahoo's ticker -> IB's symbol: "BHP.AX" -> "BHP", "BRK-B" -> "BRK B" (the reverse of ticker_for)."""
    symbol = yahoo_ticker.removesuffix(".AX") if market == "ASX" else yahoo_ticker
    return symbol.replace("-", " ")


def _fetch_market_stats(market, wanted):
    exchanges = SCREEN_EXCHANGES[market]
    query = yf.EquityQuery("is-in", ["exchange", *exchanges]) if len(exchanges) > 1 else yf.EquityQuery("eq", ["exchange", exchanges[0]])
    stats = {}
    for page in range(SCREEN_MAX_PAGES[market]):
        quotes = yf.screen(query, offset=page * SCREEN_PAGE, sortField="intradaymarketcap", sortAsc=False,
                           size=SCREEN_PAGE).get("quotes") or []
        for quote in quotes:
            cap = _number(quote.get("marketCap"))
            if quote.get("symbol") and cap:
                stats[ib_symbol(quote["symbol"], market)] = {
                    "market_cap": cap,
                    "pe": _number(quote.get("trailingPE")),
                    "return_1y": _number(quote.get("fiftyTwoWeekChangePercent")),  # price change, %
                    "name": quote.get("longName") or quote.get("shortName"),
                }
        # Largest first, so stop once every wanted stock has been seen
        if len(quotes) < SCREEN_PAGE or (wanted and wanted <= stats.keys()):
            break
    if not stats:
        raise YahooUnavailable(f"Yahoo's screener returned nothing for {market}")
    return stats


async def fetch_market_stats(market, wanted=None):
    """Market cap (local currency), trailing P/E, 52-week price change (%) and name of a market's
    largest stocks, from Yahoo's screener a page of 250 at a time (ASX: up to 2 pages, enough for
    the ASX 200; US: up to 8, stopping once every symbol in wanted is found). Keys are IB symbols."""
    return await _run(_fetch_market_stats, market, set(wanted or ()))
