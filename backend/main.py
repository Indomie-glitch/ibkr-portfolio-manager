import asyncio
import math
import os
import time
from typing import Literal
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from ib_async import IB, Contract
import yahoo
from cache import cached
from names import display_name, short_company_name

load_dotenv()

IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_PORT", "4002"))
IB_CLIENT_ID = int(os.getenv("IB_CLIENT_ID", "1"))
RECONNECT_SECONDS = 5

ib = IB()

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
    while True:
        if not ib.isConnected():
            try:
                await ib.connectAsync(IB_HOST, IB_PORT, clientId=IB_CLIENT_ID, readonly=True)
                # 3 = delayed data, which is free without a market data subscription
                ib.reqMarketDataType(3)
                print(f"Connected to IB Gateway on {IB_HOST}:{IB_PORT}")
            except Exception as exc:
                # Gateway closed, still starting up, or not logged in yet; try again shortly
                ib.disconnect()
                print(f"IB Gateway not available ({exc.__class__.__name__}); retrying in {RECONNECT_SECONDS}s")
        await asyncio.sleep(RECONNECT_SECONDS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(keep_connected())
    yield
    task.cancel()
    ib.disconnect()

app = FastAPI(lifespan=lifespan)

# Let the Vite dev server call the API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
)

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
    return {"connected": ib.isConnected()}

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

    async def quote(item):
        con_id = item.contract.conId
        ticker = tickers.get(con_id)

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
                return {"con_id": con_id, "last": clean(item.marketPrice), "prev_close": None,
                        "day_change": None, "day_change_pct": None, "source": None}
            prev_close = bars[-2].close
            last = clean(item.marketPrice) or session.close
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

    return await asyncio.gather(*(quote(i) for i in items))

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
        print(f"Yahoo lookup failed: {exc.__class__.__name__}: {exc}")
        raise HTTPException(status_code=502, detail=YAHOO_UNAVAILABLE)

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

@app.get("/news/{con_id}", dependencies=[Depends(require_ib)])
async def news(con_id: int):
    """Recent headlines that mention the company, newest first (cached 15 minutes)."""
    contract, symbol = await yahoo_target(con_id)

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

    items = await call_yahoo(lambda: cached(("news", symbol), 15 * 60, fetch))
    return {"items": items}

@app.get("/performance/{con_id}", dependencies=[Depends(require_ib)])
async def performance(con_id: int):
    """Total return over YTD, 1Y, 3Y and 5Y for the stock and its benchmark (cached 1 day)."""
    contract, symbol = await yahoo_target(con_id)
    benchmark = yahoo.benchmark_for(contract)
    periods = await call_yahoo(lambda: cached(
        ("performance", symbol), 24 * 60 * 60,
        lambda: yahoo.fetch_performance(symbol, benchmark["symbol"]),
    ))
    return {"benchmark": benchmark, "periods": periods}
