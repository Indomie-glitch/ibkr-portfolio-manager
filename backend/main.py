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
from names import display_name

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
        last = clean(ticker.last) if ticker else None
        prev_close = clean(ticker.close) if ticker else None
        source = "delayed"

        if last is None or prev_close is None:
            # No quote (e.g. IB error 10197, a live session elsewhere blocks market data).
            # Fall back to IB's daily history: compare the latest price with the previous session's close.
            bars = await get_bars(con_id, "5 D", "1 day", max_age=15 * 60)
            if len(bars) < 2:
                return {"con_id": con_id, "last": clean(item.marketPrice), "prev_close": None,
                        "day_change": None, "day_change_pct": None, "source": None}
            prev_close = bars[-2].close
            last = clean(item.marketPrice) or bars[-1].close
            source = "history"

        change = last - prev_close
        return {
            "con_id": con_id,
            "last": last,
            "prev_close": prev_close,
            "day_change": change,
            "day_change_pct": change / prev_close * 100 if prev_close else None,
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
