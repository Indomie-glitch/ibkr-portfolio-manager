import asyncio
import math
import os
import time
from typing import Literal
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from ib_async import IB, Contract

load_dotenv()

IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_PORT", "4002"))

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    await ib.connectAsync(IB_HOST, IB_PORT, clientId=1, readonly=True)
    # 3 = delayed data, which is free without a market data subscription
    ib.reqMarketDataType(3)
    yield
    ib.disconnect()

app = FastAPI(lifespan=lifespan)

# Let the Vite dev server call the API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
)

@app.get("/health")
def health():
    return {"connected": ib.isConnected()}

@app.get("/positions")
async def positions():
    items = ib.portfolio()
    infos = await asyncio.gather(*(get_contract_info(i.contract.conId) for i in items))

    result = []
    for item, (contract, long_name) in zip(items, infos):
        c = item.contract
        cost_basis = item.averageCost * item.position
        result.append({
            "con_id": c.conId,
            "symbol": c.symbol,
            "name": long_name or c.symbol,
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

@app.get("/account")
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
@app.get("/quotes")
async def quotes():
    items = ib.portfolio()
    infos = await asyncio.gather(*(get_contract_info(i.contract.conId) for i in items))
    contracts = [contract for contract, _ in infos if contract]
    tickers = {t.contract.conId: t for t in await ib.reqTickersAsync(*contracts)}

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

@app.get("/history/{con_id}")
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
