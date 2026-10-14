import asyncio
import math
import os
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from fastapi import FastAPI
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

@asynccontextmanager
async def lifespan(app: FastAPI):
    await ib.connectAsync(IB_HOST, IB_PORT, clientId=1, readonly=True)
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