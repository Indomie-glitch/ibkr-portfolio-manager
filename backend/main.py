import asyncio
import json
import math
import os
import secrets
import time
from datetime import date, datetime, timedelta
from typing import Literal
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from ib_async import IB, Contract
import config  # first: loads .env before other modules read settings
import ai_summary
import lots
import portfolio_facts
import portfolio_summary
import trading
from secrets_guard import mask_secrets
import summary_facts
import summary_store
import yahoo
from cache import cached
from ib_connection import ConnectionStatus
from names import display_name, short_company_name

IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
RECONNECT_SECONDS = 5

ib = IB()
# Why we aren't connected (shown to the user after a while) and which client ID to use
connection = ConnectionStatus(config.ib_client_id())
ib.errorEvent += lambda req_id, code, *rest: connection.on_ib_error(code)

# Contract details rarely change, so look each one up once and keep it
contract_cache = {}

async def get_contract_info(con_id):
    """Return (contract, long_name) for a conId, qualified so it can be used for market data."""
    if con_id not in contract_cache:
        details = await ib.reqContractDetailsAsync(Contract(conId=con_id))
        if not details:
            return None, None
        contract = details[0].contract
        contract.exchange = contract.exchange or "SMART"
        contract_cache[con_id] = (contract, details[0].longName)
    return contract_cache[con_id]

def clean(value):
    """IB uses NaN for 'no value'; JSON can't hold NaN, so turn it into None."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value

# Small time-based cache so repeated requests don't hit IB's history limit (about 60 per 10 min)
history_cache = {}

async def get_bars(con_id, duration, bar_size, max_age):
    key = (con_id, duration, bar_size)
    cached = history_cache.get(key)
    if cached and time.monotonic() - cached[0] < max_age:
        return cached[1]
    contract, _ = await get_contract_info(con_id)
    if contract is None:
        return []
    bars = await ib.reqHistoricalDataAsync(
        contract, endDateTime="", durationStr=duration, barSizeSetting=bar_size,
        whatToShow="TRADES", useRTH=True, timeout=20,
    )
    history_cache[key] = (time.monotonic(), bars)
    return bars

async def keep_connected():
    """Connect to IB Gateway, and reconnect whenever the connection drops.

    Runs for the server's whole life, so the API starts even if Gateway is closed
    and recovers on its own when Gateway comes back.
    """
    connected_port = None
    while True:
        port = config.ib_port()
        if ib.isConnected() and port != connected_port:
            # The port was changed in Settings: connect again on the new one
            print(f"Gateway port changed to {port}; reconnecting")
            ib.disconnect()
        if not ib.isConnected():
            try:
                # Read only unless TRADING_MODE turns trading on (checked again before every order)
                read_only = config.trading_mode() == "off"
                await ib.connectAsync(IB_HOST, port, clientId=connection.client_id, readonly=read_only)
                connection.read_only = read_only
                connected_port = port
                connection.connected()
                # 3 = delayed data, which is free without a market data subscription
                ib.reqMarketDataType(3)
                print(f"Connected to IB Gateway on {IB_HOST}:{port} as client {connection.client_id}")
            except Exception as exc:
                # Gateway closed, still starting up, or not logged in yet; try again shortly
                ib.disconnect()
                connection.failed(exc)
                print(f"IB Gateway not available ({exc.__class__.__name__}, {connection.problem}); "
                      f"retrying in {RECONNECT_SECONDS}s as client {connection.client_id}")
        await asyncio.sleep(RECONNECT_SECONDS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(keep_connected())
    # Purchase dates from IBKR's Flex report, refreshed daily when Flex is set up (docs/flex-query.md)
    lots_task = asyncio.create_task(lots.keep_refreshed())
    yield
    task.cancel()
    lots_task.cancel()
    ib.disconnect()

app = FastAPI(lifespan=lifespan)

# Let the Vite dev server and the Mac app's window (Tauri serves the built frontend from
# tauri://localhost) call the API. Everything is GET-only, except POST /summary/{con_id},
# POST /portfolio-summary (generating a summary) and POST /orders/... (trading), which only these
# origins may call.
ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "tauri://localhost"]

class PathCORS:
    """Two CORS policies chosen by path: GET-only everywhere, GET + POST for the summaries."""

    def __init__(self, app):
        self.get_only = CORSMiddleware(app, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET"],
                                       allow_headers=["X-App-Token"])
        self.get_post = CORSMiddleware(app, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"],
                                       allow_headers=["X-App-Token"])

    async def __call__(self, scope, receive, send):
        summary_path = scope["type"] == "http" and (scope["path"].startswith(("/summary/", "/orders/"))
                                                    or scope["path"] in ("/portfolio-summary", "/orders"))
        await (self.get_post if summary_path else self.get_only)(scope, receive, send)

# In the Mac app, every request must carry the token the app created at launch, so other programs
# on the computer can't use this API. Added before PathCORS so PathCORS wraps it and a 401 still
# carries CORS headers the page can read. Development (no token) is unchanged.
@app.middleware("http")
async def require_app_token(request: Request, call_next):
    if config.API_TOKEN and request.method != "OPTIONS":
        if not secrets.compare_digest(request.headers.get("x-app-token", ""), config.API_TOKEN):
            return JSONResponse({"detail": "Missing or wrong app token"}, status_code=401)
    return await call_next(request)

app.add_middleware(PathCORS)

NOT_CONNECTED = "IB Gateway is not connected"

def require_ib():
    """Endpoint dependency: answer 503 straight away instead of waiting on a dead connection."""
    if not ib.isConnected():
        raise HTTPException(status_code=503, detail=NOT_CONNECTED)

# If Gateway drops in the middle of a request, ib_async raises ConnectionError
@app.exception_handler(ConnectionError)
async def connection_error(request: Request, exc: ConnectionError):
    return JSONResponse(status_code=503, content={"detail": NOT_CONNECTED})

@app.get("/health")
def health():
    """Whether IB Gateway is connected; if not, why (see ib_connection.py) and on which port."""
    if ib.isConnected():
        return {"connected": True}
    return {"connected": False, "port": config.ib_port(), **connection.as_dict()}

@app.get("/positions", dependencies=[Depends(require_ib)])
async def positions():
    items = ib.portfolio()
    infos = await asyncio.gather(*(get_contract_info(i.contract.conId) for i in items))

    result = []
    for item, (contract, long_name) in zip(items, infos):
        c = item.contract
        cost_basis = item.averageCost * item.position
        name, name_truncated = display_name(long_name, c.symbol)
        result.append({
            "con_id": c.conId,
            "symbol": c.symbol,
            "name": name,
            "name_truncated": name_truncated,
            "sec_type": c.secType,
            "currency": c.currency,
            "exchange": (contract.primaryExchange if contract else None) or c.primaryExchange,
            "quantity": item.position,
            "avg_cost": item.averageCost,
            "market_price": clean(item.marketPrice),
            "market_value": clean(item.marketValue),
            "unrealized_pnl": clean(item.unrealizedPNL),
            "unrealized_pnl_pct": clean(item.unrealizedPNL / cost_basis * 100) if cost_basis else None,
        })
    return result

@app.get("/account", dependencies=[Depends(require_ib)])
async def account():
    summary = await ib.accountSummaryAsync()

    wanted = {
        "NetLiquidation": "net_liquidation",
        "TotalCashValue": "cash",
        "GrossPositionValue": "positions_value",
        "BuyingPower": "buying_power",
    }

    result = {"fx_rates": {}}
    for item in summary:
        if item.tag in wanted:
            result[wanted[item.tag]] = float(item.value)
            result["currency"] = item.currency
        # Ledger rows are per currency; BASE is the account's own currency
        elif item.tag == "$LEDGER-UnrealizedPnL" and item.currency == "BASE":
            result["unrealized_pnl"] = float(item.value)
        elif item.tag == "$LEDGER-ExchangeRate" and item.currency != "BASE":
            # How many units of base currency one unit of this currency is worth
            result["fx_rates"][item.currency] = float(item.value)
    return result
# When IB sends no quotes at all (e.g. error 10197), asking again just waits several
# seconds for nothing, so skip quote requests for a while and use the history fallback.
QUOTE_RETRY_SECONDS = 10 * 60
quotes_blocked_until = 0

async def fetch_tickers(contracts):
    global quotes_blocked_until
    if not contracts or time.monotonic() < quotes_blocked_until:
        return {}
    try:
        tickers = await asyncio.wait_for(ib.reqTickersAsync(*contracts), timeout=4)
    except asyncio.TimeoutError:
        tickers = []
    if not any(clean(t.last) is not None or clean(t.close) is not None for t in tickers):
        quotes_blocked_until = time.monotonic() + QUOTE_RETRY_SECONDS
        return {}
    return {t.contract.conId: t for t in tickers}

@app.get("/quotes", dependencies=[Depends(require_ib)])
async def quotes():
    items = ib.portfolio()
    infos = await asyncio.gather(*(get_contract_info(i.contract.conId) for i in items))
    tickers = await fetch_tickers([contract for contract, _ in infos if contract])
    return await asyncio.gather(*(build_quote(i.contract.conId, tickers.get(i.contract.conId), clean(i.marketPrice))
                                  for i in items))

async def build_quote(con_id, ticker, market_price=None):
    """One /quotes item: the delayed quote if IB sent one, otherwise the day change from daily bars.
    market_price: IB's portfolio price for a holding (None for a stock that isn't held)."""
    def from_ticker(field):
        return clean(getattr(ticker, field)) if ticker else None

    # About 3 months of daily bars: the fallback when there's no quote, and the average volume.
    # The last bar is the current (or most recent) session.
    bars = await get_bars(con_id, "3 M", "1 day", max_age=15 * 60)
    session = bars[-1] if bars else None

    last = from_ticker("last")
    prev_close = from_ticker("close")
    source = "delayed"
    if last is None or prev_close is None:
        # No quote (e.g. IB error 10197, a live session elsewhere blocks market data).
        # Fall back to IB's daily history: compare the latest price with the previous session's close.
        if len(bars) < 2:
            return {"con_id": con_id, "last": market_price, "prev_close": None,
                    "day_change": None, "day_change_pct": None, "source": None}
        prev_close = bars[-2].close
        last = market_price or session.close
        source = "history"

    # Volume always comes from the bars so it matches the average (same source and units)
    earlier = bars[:-1][-63:]  # about 3 months of complete sessions
    change = last - prev_close
    return {
        "con_id": con_id,
        "last": last,
        "prev_close": prev_close,
        "day_change": change,
        "day_change_pct": change / prev_close * 100 if prev_close else None,
        "open": from_ticker("open") or (session.open if session else None),
        "day_high": from_ticker("high") or (session.high if session else None),
        "day_low": from_ticker("low") or (session.low if session else None),
        "bid": from_ticker("bid"),
        "ask": from_ticker("ask"),
        "volume": session.volume if session else None,
        "avg_volume": sum(b.volume for b in earlier) / len(earlier) if earlier else None,
        "source": source,
    }

# IB allows about one symbol search a second; results are cached so retyping is free
SEARCH_EXCHANGES = {"ASX": "ASX", "NASDAQ": "US", "NYSE": "US", "ARCA": "US", "AMEX": "US", "BATS": "US", "IEX": "US"}
SEARCH_LIMIT = 10
search_lock = asyncio.Lock()

def search_results(descriptions, owned_ids):
    """IB's matching symbols -> ASX and US stocks (other markets and fund types are left out)."""
    results = []
    for description in descriptions:
        c = description.contract
        market = SEARCH_EXCHANGES.get(c.primaryExchange) if c else None
        if not c or c.secType != "STK" or market is None:
            continue
        name, _ = display_name(c.description, c.symbol)
        results.append({
            "con_id": c.conId, "symbol": c.symbol, "name": name,
            "exchange": c.primaryExchange, "currency": c.currency, "market": market,
            "owned": c.conId in owned_ids,
        })
    return results[:SEARCH_LIMIT]

@app.get("/search", dependencies=[Depends(require_ib)])
async def search(q: str):
    """Stocks on the ASX and US exchanges matching a symbol or company name (IB's symbol search)."""
    q = q.strip()
    if not q:
        return []
    if len(q) > 40:
        raise HTTPException(status_code=422, detail="Search text is too long")

    async def lookup():
        async with search_lock:
            found = await ib.reqMatchingSymbolsAsync(q)
            await asyncio.sleep(1)  # IB's pacing for symbol searches
            return found or []

    descriptions = await cached(("search", q.lower()), 10 * 60, lookup)
    owned = {item.contract.conId for item in ib.portfolio()}
    return search_results(descriptions, owned)

@app.get("/prices", dependencies=[Depends(require_ib)])
async def prices(con_ids: str):
    """Quotes (same shape as /quotes) for any stocks, e.g. search results: ?con_ids=265598,4391"""
    try:
        ids = list(dict.fromkeys(int(part) for part in con_ids.split(",") if part.strip()))
    except ValueError:
        raise HTTPException(status_code=422, detail="con_ids must be numbers separated by commas")
    if len(ids) > SEARCH_LIMIT * 2:
        raise HTTPException(status_code=422, detail=f"At most {SEARCH_LIMIT * 2} stocks at a time")
    infos = await asyncio.gather(*(get_contract_info(con_id) for con_id in ids))
    known = [(con_id, contract) for con_id, (contract, _) in zip(ids, infos) if contract]
    tickers = await fetch_tickers([contract for _, contract in known])
    return await asyncio.gather(*(build_quote(con_id, tickers.get(con_id)) for con_id, _ in known))

# Each range maps to an IB duration and bar size
RANGES = {
    "1D": ("1 D", "5 mins"),
    "1W": ("1 W", "30 mins"),
    "1M": ("1 M", "1 day"),
    "3M": ("3 M", "1 day"),
    "1Y": ("1 Y", "1 day"),
    "All": ("10 Y", "1 week"),
}

@app.get("/history/{con_id}", dependencies=[Depends(require_ib)])
async def history(con_id: int, range: Literal["1D", "1W", "1M", "3M", "1Y", "All"] = "1M"):
    duration, bar_size = RANGES[range]
    bars = await get_bars(con_id, duration, bar_size, max_age=60)
    if not bars:
        raise HTTPException(status_code=502, detail="IB returned no price history for this contract")
    return {
        "con_id": con_id,
        "range": range,
        "bars": [{"time": b.date.isoformat(), "close": b.close} for b in bars],
    }


# ---------- Yahoo Finance: company info, slow key statistics, news, performance ----------

YAHOO_UNAVAILABLE = "Yahoo Finance data is unavailable right now"

async def yahoo_target(con_id):
    """Return (contract, yahoo symbol) for a holding, or answer 404 if we can't map it."""
    contract, _ = await get_contract_info(con_id)
    symbol = yahoo.yahoo_symbol(contract) if contract else None
    if symbol is None:
        raise HTTPException(status_code=404, detail="This exchange isn't covered by Yahoo Finance here")
    return contract, symbol

async def yahoo_info(symbol):
    return await cached(("info", symbol), 60 * 60, lambda: yahoo.fetch_info(symbol))

async def call_yahoo(fetch):
    """Run a Yahoo lookup; any failure becomes a 502 so only that section shows 'unavailable'."""
    try:
        return await fetch()
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Yahoo lookup failed: {exc.__class__.__name__}: {mask_secrets(exc)}")
        raise HTTPException(status_code=502, detail=YAHOO_UNAVAILABLE)

# ---------- Purchase lots (Flex report) ----------

@app.get("/lots/status")
def lots_status():
    """Whether Flex is set up, when the lots were last fetched, the report's date and the last error."""
    return lots.status()

@app.get("/lots/{con_id}", dependencies=[Depends(require_ib)])
def holding_lots(con_id: int):
    """A holding's purchase lots with their 12-month CGT discount dates, matched to the quantity
    held now (lots.lots_for)."""
    held = next((item.position for item in ib.portfolio() if item.contract.conId == con_id), None)
    if held is None:
        raise HTTPException(status_code=404, detail="Not a current holding")
    return lots.lots_for(con_id, held)

@app.get("/profile/{con_id}", dependencies=[Depends(require_ib)])
async def profile(con_id: int):
    """About section: description, sector, industry, employees, fiscal year end, website (cached 1 hour)."""
    _, symbol = await yahoo_target(con_id)
    info = await call_yahoo(lambda: yahoo_info(symbol))
    result = yahoo.profile_from_info(info)
    result["short_name"] = short_company_name(result["long_name"])
    result["yahoo_symbol"] = symbol
    return result

@app.get("/stats/{con_id}", dependencies=[Depends(require_ib)])
async def stats(con_id: int):
    """Slower key statistics from Yahoo (cached 1 hour). Market fields come from /quotes."""
    _, symbol = await yahoo_target(con_id)
    info = await call_yahoo(lambda: yahoo_info(symbol))
    return yahoo.stats_from_info(info)

async def news_items(contract, symbol):
    """Recent headlines that name the company, newest first (cached 15 minutes)."""
    async def fetch():
        info = await yahoo_info(symbol)
        long_name = info.get("longName") or info.get("shortName")
        is_asx = symbol.endswith(".AX")
        bare_ticker_ok = True
        if is_asx:
            # A bare ticker in a headline ("APA") only counts if the US company with that
            # ticker is the same company (BHP yes; APA Corporation and Telos no)
            us_name = await cached(("us-name", contract.symbol), 24 * 60 * 60,
                                   lambda: yahoo.fetch_us_name(contract.symbol))
            bare_ticker_ok = us_name is None or (
                yahoo.search_name(us_name).lower() == yahoo.search_name(long_name).lower()
            )
        return await yahoo.fetch_news(symbol, contract.symbol, long_name,
                                      short_company_name(long_name), is_asx, bare_ticker_ok)

    return await cached(("news", symbol), 15 * 60, fetch)

async def performance_data(contract, symbol):
    """Total return periods for the stock and its benchmark (cached 1 day)."""
    benchmark = yahoo.benchmark_for(contract)
    periods = await cached(("performance", symbol), 24 * 60 * 60,
                           lambda: yahoo.fetch_performance(symbol, benchmark["symbol"]))
    return {"benchmark": benchmark, "periods": periods}

@app.get("/news/{con_id}", dependencies=[Depends(require_ib)])
async def news(con_id: int):
    """Recent headlines that mention the company, newest first (cached 15 minutes)."""
    contract, symbol = await yahoo_target(con_id)
    items = await call_yahoo(lambda: news_items(contract, symbol))
    return {"items": items}

@app.get("/performance/{con_id}", dependencies=[Depends(require_ib)])
async def performance(con_id: int):
    """Total return over YTD, 1Y, 3Y and 5Y for the stock and its benchmark (cached 1 day)."""
    contract, symbol = await yahoo_target(con_id)
    return await call_yahoo(lambda: performance_data(contract, symbol))


# ---------- AI summary ----------

async def summary_facts_for(con_id):
    """Gather IB and Yahoo data for one holding and build the facts sheet (no Claude call)."""
    contract, _ = await get_contract_info(con_id)
    all_positions = await positions()
    position = next((p for p in all_positions if p["con_id"] == con_id), None)
    if contract is None or position is None:
        raise HTTPException(status_code=404, detail="Not a current holding")
    quote = next((q for q in await quotes() if q["con_id"] == con_id), None)
    account_data = await account()
    fx_rates = account_data["fx_rates"]
    base = account_data["currency"]

    def to_base(p):
        rate = fx_rates.get(p["currency"], 1 if p["currency"] == base else None)
        return (p["market_value"] or 0) * rate if rate is not None else 0

    symbol = yahoo.yahoo_symbol(contract)
    is_asx = (contract.primaryExchange or contract.exchange) == "ASX"

    async def unavailable():
        raise yahoo.YahooUnavailable("This exchange isn't covered by Yahoo Finance here")

    def yahoo_loader(load):
        return load if symbol else unavailable

    index_symbol = yahoo.PRICE_INDEXES["ASX" if is_asx else "US"]
    loaders = {
        "info": yahoo_loader(lambda: yahoo_info(symbol)),
        "financials": yahoo_loader(lambda: cached(("financials", symbol), 24 * 60 * 60, lambda: yahoo.fetch_financials(symbol))),
        "dividends": yahoo_loader(lambda: cached(("dividends", symbol), 24 * 60 * 60, lambda: yahoo.fetch_dividends(symbol))),
        "performance": yahoo_loader(lambda: performance_data(contract, symbol)),
        "index_closes": lambda: cached(("index", index_symbol), 60 * 60, lambda: yahoo.fetch_index_closes(index_symbol)),
        "index_intraday": lambda: cached(("index_5m", index_symbol), 5 * 60, lambda: yahoo.fetch_index_intraday(index_symbol)),
        "news": yahoo_loader(lambda: news_items(contract, symbol)),
    }
    inputs = {
        "position": position,
        "quote": quote,
        "bars": await get_bars(con_id, "3 M", "1 day", max_age=15 * 60),
        "base_currency": base,
        "fx_rate": fx_rates.get(position["currency"], 1),
        "total_market_value_base": sum(to_base(p) for p in all_positions),
        "is_asx": is_asx,
        "index_symbol": index_symbol,
        # Purchase lots from the Flex report (local, never waits for IBKR); empty without one
        "lots": lots.lots_for(con_id, position["quantity"]),
    }
    return await summary_facts.build_facts(inputs, loaders, previous=summary_store.latest(con_id))

@app.get("/summary/{con_id}/facts", dependencies=[Depends(require_ib)])
async def summary_facts_preview(con_id: int):
    """Exactly what the model would be given for this holding. Free: no Claude call."""
    result = await summary_facts_for(con_id)
    return {"facts": summary_facts.model_facts(result["facts"]), "links": result["links"],
            "source_ids": summary_facts.source_ids(result["facts"])}

BENCHMARK_NAMES = {"ASX": "S&P/ASX 200", "US": "S&P 500"}

async def holding_inputs(position, quote, today, missing):
    """IB and Yahoo data for one holding of the portfolio facts sheet; gaps are recorded in missing."""
    contract, _ = await get_contract_info(position["con_id"])
    symbol = yahoo.yahoo_symbol(contract) if contract else None
    market = portfolio_facts.market_of(position)
    index_symbol = yahoo.PRICE_INDEXES[market]
    label = position["symbol"]
    inputs = {"position": position, "quote": quote, "benchmark": BENCHMARK_NAMES[market],
              "sector": None, "beta": None, "events": [], "dividends_12m": None, "closes": None, "index_closes": None}
    if symbol is None:
        missing.append(f"{label}: not covered by Yahoo Finance (sector, beta, events and dividends)")
    else:
        info = await summary_facts.safe(lambda: yahoo_info(symbol), f"{label} company data", missing)
        if info:
            stats = yahoo.stats_from_info(info)
            inputs.update(sector=info.get("sector"), beta=stats["beta"])
            for key, event in (("earnings_date", "Earnings result"), ("ex_dividend_date", "Ex-dividend date")):
                if stats[key]:
                    inputs["events"].append((date.fromisoformat(stats[key]), event))
        dividends = await summary_facts.safe(
            lambda: cached(("dividends", symbol), 24 * 60 * 60, lambda: yahoo.fetch_dividends(symbol)), f"{label} dividends", missing)
        if dividends is not None:
            cutoff = today - timedelta(days=365)
            inputs["dividends_12m"] = sum(amount for day, amount in dividends if cutoff < day <= today)
    try:
        bars = await get_bars(position["con_id"], "3 M", "1 day", max_age=15 * 60)
        inputs["closes"] = [(b.date if isinstance(b.date, date) else b.date.date(), b.close) for b in bars]
    except Exception as exc:
        missing.append(f"{label}: price history unavailable ({exc.__class__.__name__})")
    inputs["index_closes"] = await summary_facts.safe(
        lambda: cached(("index", index_symbol), 60 * 60, lambda: yahoo.fetch_index_closes(index_symbol)),
        f"{BENCHMARK_NAMES[market]} closes", missing)
    return inputs

async def portfolio_facts_for():
    """Gather IB and Yahoo data for every holding and build the portfolio facts sheet (no Claude call)."""
    now = datetime.now().astimezone()
    today = now.date()
    missing = []
    quote_by_id = {q["con_id"]: q for q in await quotes()}
    holdings = []
    for position in await positions():
        if position["sec_type"] == "STK":
            holdings.append(await holding_inputs(position, quote_by_id.get(position["con_id"]), today, missing))
    previous = summary_store.latest_portfolio()
    return portfolio_facts.build_portfolio_facts(await account(), holdings, now, missing,
                                                 previous=previous["facts"] if previous else None)

@app.get("/trading/status")
def trading_status():
    """Paper or live account, whether orders are allowed and why not, and the order limits."""
    accounts = ib.managedAccounts() if ib.isConnected() else []
    return trading.status(accounts, connection_read_only=connection.read_only)

class OrderRequest(BaseModel):
    con_id: int
    action: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0)
    order_type: Literal["MKT", "LMT"]
    limit_price: float | None = None

async def checked_order(order: OrderRequest):
    """Everything an order needs before IB sees it: the contract, the price it's valued at, the
    guardrail status and the problems that stop it (trading.check_order)."""
    contract, _ = await get_contract_info(order.con_id)
    if contract is None or contract.secType != "STK":
        raise HTTPException(status_code=404, detail="Unknown stock")
    if order.order_type == "LMT" and order.limit_price:
        price = order.limit_price
    else:
        tickers = await fetch_tickers([contract])
        price = (await build_quote(order.con_id, tickers.get(order.con_id)))["last"]
    account_data = await account()
    base = account_data["currency"]
    fx_rate = 1 if contract.currency == base else account_data["fx_rates"].get(contract.currency)
    held = next((item.position for item in ib.portfolio() if item.contract.conId == order.con_id), 0)
    status = trading.status(ib.managedAccounts(), connection_read_only=connection.read_only)
    problems, value, value_base = trading.check_order(order.model_dump(), price, fx_rate, held, status)
    return {
        "contract": contract, "price": price, "held": held, "status": status, "problems": problems,
        "value": value, "value_base": value_base, "base_currency": base,
    }

@app.post("/orders/preview", dependencies=[Depends(require_ib)])
async def preview_order(order: OrderRequest, request: Request):
    """What an order would cost (IB's what-if: commission and margin impact), without sending it.
    Only possible while trading is on (TRADING_MODE): IB refuses what-if orders on a read-only connection."""
    check_origin(request)
    checked = await checked_order(order)
    contract = checked["contract"]
    what_if = None
    token = None
    if not checked["problems"]:
        try:
            state = await asyncio.wait_for(ib.whatIfOrderAsync(contract, trading.build_order(order.model_dump())), timeout=10)
            what_if = trading.what_if_summary(state)
            # Placing this exact order needs this token (single use, 2 minutes)
            token = confirmation_tokens.issue(order.con_id, order.model_dump(), time.monotonic())
        except asyncio.TimeoutError:
            checked["problems"].append("IB didn't answer the preview in time. Try again.")
        except Exception as exc:
            checked["problems"].append(f"IB couldn't preview this order ({mask_secrets(exc)}).")
    return {
        "con_id": order.con_id, "symbol": contract.symbol, "exchange": contract.primaryExchange,
        "currency": contract.currency, "action": order.action, "quantity": order.quantity,
        "order_type": order.order_type, "limit_price": order.limit_price,
        "price_used": checked["price"], "estimated_value": checked["value"],
        "estimated_value_base": checked["value_base"], "base_currency": checked["base_currency"],
        "held_quantity": checked["held"], "max_order_value": checked["status"]["max_order_value"],
        "what_if": what_if, "problems": checked["problems"], "can_submit": not checked["problems"],
        "confirmation_token": token, "confirmation_expires_in_s": trading.TOKEN_LIFETIME_S if token else None,
    }

confirmation_tokens = trading.ConfirmationTokens()
order_lock = asyncio.Lock()
# Statuses that mean IB hasn't accepted or rejected the order yet (PreSubmitted = accepted, waiting
# for the market to open)
PENDING_STATUSES = {"PendingSubmit", "ApiPending"}

class PlaceOrderRequest(OrderRequest):
    confirmation_token: str

def trade_summary(trade):
    """An order's state for the app (also used by the order status stream later)."""
    status = trade.orderStatus
    messages = [entry.message for entry in trade.log if entry.message]
    # Commission is reported per fill, a moment after the fill itself
    commissions = [clean(f.commissionReport.commission) for f in trade.fills
                   if f.commissionReport and clean(f.commissionReport.commission) is not None
                   and f.commissionReport.commission < trading.UNSET]
    return {
        "order_id": trade.order.orderId, "perm_id": trade.order.permId or None,
        "con_id": trade.contract.conId, "symbol": trade.contract.symbol,
        "action": trade.order.action, "quantity": trade.order.totalQuantity, "order_type": trade.order.orderType,
        "limit_price": clean(trade.order.lmtPrice) if trade.order.orderType == "LMT" else None,
        "status": status.status, "filled": status.filled, "remaining": status.remaining,
        "avg_fill_price": clean(status.avgFillPrice) or None,
        "message": messages[-1] if messages else None,
        "commission": sum(commissions) if commissions else None,
        "commission_currency": next((f.commissionReport.currency for f in trade.fills
                                     if f.commissionReport and f.commissionReport.currency), None),
    }

@app.post("/orders", dependencies=[Depends(require_ib)])
async def place_order(order: PlaceOrderRequest, request: Request):
    """Place an order that was previewed: needs the preview's confirmation token for exactly this
    order, and passes every guardrail check again (trading status, limits) right before sending."""
    check_origin(request)
    if order_lock.locked():
        raise HTTPException(status_code=409, detail="Another order is being placed")
    async with order_lock:
        details = order.model_dump(exclude={"confirmation_token"})
        problem = confirmation_tokens.redeem(order.confirmation_token, order.con_id, details, time.monotonic())
        if problem:
            raise HTTPException(status_code=409, detail=problem)
        checked = await checked_order(order)
        if checked["problems"]:
            raise HTTPException(status_code=409, detail=" ".join(checked["problems"]))
        trade = ib.placeOrder(checked["contract"], trading.build_order(details))
        print(f"Order placed: {order.action} {order.quantity:g} {checked['contract'].symbol} {order.order_type} "
              f"(order {trade.order.orderId})")
        # Give IB a moment to accept or reject it, so the app can say which
        for _ in range(25):
            if trade.orderStatus.status not in PENDING_STATUSES:
                break
            await asyncio.sleep(0.2)
        return trade_summary(trade)

# Orders IB still might fill: these can be cancelled or changed
OPEN_STATUSES = {"PendingSubmit", "ApiPending", "PreSubmitted", "Submitted"}

def open_trade(order_id):
    trade = next((t for t in ib.openTrades() if t.order.orderId == order_id), None)
    if trade is None or trade.orderStatus.status not in OPEN_STATUSES:
        raise HTTPException(status_code=404, detail="No open order with that id (it may have filled or been cancelled)")
    return trade

async def settled(trade, waiting_for):
    """Wait up to 5 s for IB to confirm a cancel or change, then describe the order."""
    for _ in range(25):
        if trade.orderStatus.status not in waiting_for:
            break
        await asyncio.sleep(0.2)
    return trade_summary(trade)

@app.post("/orders/{order_id}/cancel", dependencies=[Depends(require_ib)])
async def cancel_order(order_id: int, request: Request):
    """Cancel an open order. No confirmation token: cancelling only reduces what can happen."""
    check_origin(request)
    if connection.read_only:
        raise HTTPException(status_code=409, detail="The connection to IB Gateway is read only, so orders can't be changed.")
    trade = open_trade(order_id)
    ib.cancelOrder(trade.order)
    print(f"Order cancel requested: order {order_id} ({trade.contract.symbol})")
    return await settled(trade, OPEN_STATUSES | {"PendingCancel"})

class ModifyOrderRequest(BaseModel):
    quantity: float = Field(gt=0)
    limit_price: float | None = None
    confirmation_token: str

@app.post("/orders/{order_id}/modify", dependencies=[Depends(require_ib)])
async def modify_order(order_id: int, change: ModifyOrderRequest, request: Request):
    """Change an open order's quantity or limit price. The changed order must be previewed first
    (POST /orders/preview with the new numbers) and its token passed here; side and type stay."""
    check_origin(request)
    async with order_lock:
        trade = open_trade(order_id)
        details = {
            "con_id": trade.contract.conId, "action": trade.order.action, "quantity": change.quantity,
            "order_type": trade.order.orderType, "limit_price": change.limit_price if trade.order.orderType == "LMT" else None,
        }
        if details["order_type"] not in trading.ORDER_TYPES:
            raise HTTPException(status_code=409, detail="Only market and limit orders placed here can be changed.")
        problem = confirmation_tokens.redeem(change.confirmation_token, details["con_id"], details, time.monotonic())
        if problem:
            raise HTTPException(status_code=409, detail=problem)
        checked = await checked_order(OrderRequest(**details))
        if checked["problems"]:
            raise HTTPException(status_code=409, detail=" ".join(checked["problems"]))
        trade.order.totalQuantity = change.quantity
        if details["order_type"] == "LMT":
            trade.order.lmtPrice = round(change.limit_price, 4)
        ib.placeOrder(trade.contract, trade.order)  # same order id = a change, not a new order
        print(f"Order change requested: order {order_id} ({trade.contract.symbol}) to {change.quantity:g}")
        return await settled(trade, {"PendingSubmit", "ApiPending"})

@app.get("/orders", dependencies=[Depends(require_ib)])
async def orders():
    """Open orders (from every client, including TWS and mobile), and today's filled and cancelled
    orders, for the Orders page."""
    open_trades, completed, fills = await asyncio.gather(
        asyncio.wait_for(ib.reqAllOpenOrdersAsync(), timeout=10),
        asyncio.wait_for(ib.reqCompletedOrdersAsync(apiOnly=False), timeout=10),
        asyncio.wait_for(ib.reqExecutionsAsync(), timeout=10),
    )
    con_ids = {t.contract.conId for t in [*open_trades, *completed]}
    infos = await asyncio.gather(*(get_contract_info(con_id) for con_id in con_ids))
    names = {con_id: display_name(long_name, None)[0] for con_id, (_, long_name) in zip(con_ids, infos) if long_name}
    return trading.orders_overview(open_trades, completed, fills, names)

# ---------- order status stream ----------

# One queue per open stream; IB's order events are copied into every queue
order_listeners = set()
STREAM_HEARTBEAT_S = 15

def publish_trade(trade, *_):
    """Called by ib_async for every order status change and fill."""
    if not order_listeners:
        return
    update = trade_summary(trade)
    for queue in list(order_listeners):
        queue.put_nowait(update)

ib.orderStatusEvent += publish_trade
ib.execDetailsEvent += publish_trade

@app.get("/orders/stream", dependencies=[Depends(require_ib)])
async def order_stream(request: Request):
    """Server-Sent Events: "orders" (every order this connection knows, at the start), then "order"
    whenever one is submitted, filled or cancelled. A comment every 15 s keeps the connection open."""
    queue = asyncio.Queue()
    order_listeners.add(queue)

    async def events():
        try:
            yield sse("orders", [trade_summary(t) for t in ib.trades()])
            while not await request.is_disconnected():
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=STREAM_HEARTBEAT_S)
                except asyncio.TimeoutError:
                    yield ": still here\n\n"
                    continue
                yield sse("order", update)
        finally:
            order_listeners.discard(queue)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/portfolio-summary/facts", dependencies=[Depends(require_ib)])
async def portfolio_summary_facts():
    """Exactly what the model would be given for the portfolio summary. Free: no Claude call."""
    facts = await portfolio_facts_for()
    return {"facts": facts, "source_ids": portfolio_facts.source_ids(facts)}

def saved_summary_response(record):
    facts = record["facts"]
    # Re-run the citation and rule checks, so improved checks also apply to older summaries
    allowed = set(summary_facts.source_ids(facts))
    summary, warnings = {}, []
    for name in ai_summary.SECTIONS:
        summary[name], section_warnings = ai_summary.validate_section(name, record["summary"][name], allowed, facts)
        warnings += section_warnings
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "as_of_text": facts.get("as_of_text"),
        "model": record["model"],
        "summary": summary,
        "warnings": warnings,
        "links": facts.get("links", {}),
        "missing": facts.get("D:missing", []),
        "facts": summary_facts.model_facts(facts),
    }

@app.get("/summary/{con_id}")
def latest_summary(con_id: int):
    """The last saved summary for a holding (shown instantly), and whether an API key is set."""
    record = summary_store.latest(con_id)
    return {
        "ai_configured": ai_summary.api_key_configured(),
        "missing_key_message": config.MISSING_KEY_MESSAGE,
        "model": config.ai_model(),
        "latest": saved_summary_response(record) if record else None,
    }

@app.get("/summary/{con_id}/history")
def summary_history(con_id: int):
    """Saved summaries of a holding, newest first: id, created_at, model and the price at the time."""
    return summary_store.history(con_id)

def saved_record(con_id, summary_id):
    record = summary_store.get(con_id, summary_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No saved summary with that id for this holding")
    return record

@app.get("/summary/{con_id}/history/{summary_id}")
def past_summary(con_id: int, summary_id: int):
    """One saved summary in full, in the same shape as the latest one."""
    return saved_summary_response(saved_record(con_id, summary_id))

@app.get("/summary/{con_id}/compare")
def compare_summaries(con_id: int, a: int, b: int):
    """Two saved summaries (older first) and the exact changes between their facts sheets."""
    older, newer = sorted((saved_record(con_id, a), saved_record(con_id, b)), key=lambda r: (r["created_at"], r["id"]))
    return {
        "older": saved_summary_response(older),
        "newer": saved_summary_response(newer),
        "data_changes": summary_facts.compare_data(older["facts"], newer["facts"]),
    }

def check_origin(request):
    # A cross-site form POST skips the CORS preflight, so check the origin here as well.
    # Requests without an Origin header come from local tools like curl, not other websites.
    origin = request.headers.get("origin")
    if origin is not None and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Origin not allowed")

def check_generate_request(request):
    check_origin(request)
    if not ai_summary.api_key_configured():
        raise HTTPException(status_code=503, detail=config.MISSING_KEY_MESSAGE)

# One generation per holding at a time, so a double click doesn't pay twice
summary_locks = {}

def sse(event, data):
    """One Server-Sent Event: a named event with a JSON payload (masked, as a safety net)."""
    return f"event: {event}\ndata: {mask_secrets(json.dumps(data, ensure_ascii=False))}\n\n"

@app.post("/summary/{con_id}", dependencies=[Depends(require_ib)])
async def generate_summary(con_id: int, request: Request):
    """Generate a new summary and stream it as Server-Sent Events:
    facts -> section (one per finished section) -> done, or error."""
    check_generate_request(request)
    lock = summary_locks.setdefault(con_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(status_code=409, detail="A summary for this holding is already being written")

    async def events():
        async with lock:
            yield sse("status", {"message": "Gathering data"})
            try:
                built = await summary_facts_for(con_id)
            except Exception as exc:
                print(f"Summary facts failed: {exc.__class__.__name__}: {mask_secrets(exc)}")
                yield sse("error", {"code": "facts_failed", "message": "Couldn't gather the data for this holding."})
                return
            facts, links = built["facts"], built["links"]
            ids = summary_facts.source_ids(facts)
            yield sse("facts", {"as_of_text": facts["as_of_text"], "links": links,
                                "missing": facts["D:missing"], "facts": summary_facts.model_facts(facts)})
            try:
                async for kind, *payload in ai_summary.stream_sections(summary_facts.model_facts(facts), ids):
                    if kind == "section":
                        name, section, warnings = payload
                        yield sse("section", {"name": name, "section": section, "warnings": warnings})
                    else:
                        summary, warnings, usage = payload
                        saved_facts = {**facts, "links": links}
                        summary_store.save(con_id, facts["company"]["symbol"], facts["as_of"],
                                           config.ai_model(), saved_facts, summary, warnings)
                        print(f"Summary for {facts['company']['symbol']}: {usage['input_tokens']} in, "
                              f"{usage['output_tokens']} out, {len(warnings)} warnings")
                        yield sse("done", saved_summary_response(summary_store.latest(con_id)))
            except ai_summary.SummaryError as exc:
                yield sse("error", {"code": exc.code, "message": exc.message})
            except Exception as exc:
                print(f"Summary failed: {exc.__class__.__name__}: {mask_secrets(exc)}")
                yield sse("error", {"code": "unexpected", "message": "Something went wrong while writing the summary."})

    # no-cache and X-Accel-Buffering stop anything in between from holding events back
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- AI portfolio summary (Milestone 5.2) ----------

def saved_portfolio_response(record):
    facts = record["facts"]
    allowed = set(portfolio_facts.source_ids(facts))
    summary, warnings = {}, []
    for name in portfolio_summary.SECTIONS:
        summary[name], section_warnings = portfolio_summary.validate_section(name, record["summary"][name], allowed, facts)
        warnings += section_warnings
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "as_of_text": facts.get("as_of_text"),
        "model": record["model"],
        "summary": summary,
        "warnings": warnings,
        "missing": facts.get("D:missing", []),
        "facts": facts,
    }

@app.get("/portfolio-summary")
def latest_portfolio_summary():
    """The last saved portfolio summary (shown instantly), and whether an API key is set."""
    record = summary_store.latest_portfolio()
    return {
        "ai_configured": ai_summary.api_key_configured(),
        "missing_key_message": config.MISSING_KEY_MESSAGE,
        "model": config.ai_model(),
        "latest": saved_portfolio_response(record) if record else None,
    }

@app.get("/portfolio-summary/history")
def portfolio_summary_history():
    """Saved portfolio summaries, newest first: id, created_at, model and net liquidation at the time."""
    return summary_store.portfolio_history()

@app.get("/portfolio-summary/history/{summary_id}")
def past_portfolio_summary(summary_id: int):
    """One saved portfolio summary in full, in the same shape as the latest one."""
    record = summary_store.get_portfolio(summary_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No saved portfolio summary with that id")
    return saved_portfolio_response(record)

portfolio_summary_lock = asyncio.Lock()

@app.post("/portfolio-summary", dependencies=[Depends(require_ib)])
async def generate_portfolio_summary(request: Request):
    """Generate a portfolio summary, streamed as Server-Sent Events like POST /summary/{con_id}:
    status -> facts -> section (one per finished section) -> done, or error."""
    check_generate_request(request)
    if portfolio_summary_lock.locked():
        raise HTTPException(status_code=409, detail="A portfolio summary is already being written")

    async def events():
        async with portfolio_summary_lock:
            yield sse("status", {"message": "Gathering data"})
            try:
                facts = await portfolio_facts_for()
            except Exception as exc:
                print(f"Portfolio facts failed: {exc.__class__.__name__}: {mask_secrets(exc)}")
                yield sse("error", {"code": "facts_failed", "message": "Couldn't gather the data for the portfolio."})
                return
            if not facts["D:portfolio"]["number_of_holdings"]:
                yield sse("error", {"code": "no_holdings", "message": "There are no share holdings to summarise."})
                return
            yield sse("facts", {"as_of_text": facts["as_of_text"], "missing": facts["D:missing"], "facts": facts})
            try:
                async for kind, *payload in portfolio_summary.stream_sections(facts, portfolio_facts.source_ids(facts)):
                    if kind == "section":
                        name, section, warnings = payload
                        yield sse("section", {"name": name, "section": section, "warnings": warnings})
                    else:
                        summary, warnings, usage = payload
                        summary_store.save_portfolio(facts["as_of"], config.ai_model(), facts, summary, warnings)
                        print(f"Portfolio summary: {usage['input_tokens']} in, {usage['output_tokens']} out, "
                              f"{len(warnings)} warnings")
                        yield sse("done", saved_portfolio_response(summary_store.latest_portfolio()))
            except ai_summary.SummaryError as exc:
                yield sse("error", {"code": exc.code, "message": exc.message})
            except Exception as exc:
                print(f"Portfolio summary failed: {exc.__class__.__name__}: {mask_secrets(exc)}")
                yield sse("error", {"code": "unexpected", "message": "Something went wrong while writing the summary."})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
