from contextlib import asynccontextmanager
from fastapi import FastAPI
from ib_async import IB
ib = IB()

@asynccontextmanager
async def lifespan(app: FastAPI):
    await ib.connectAsync("127.0.0.1", 4002, clientId=1, readonly=True)
    yield
    ib.disconnect()

app = FastAPI(lifespan=lifespan)

@app.get("/health")
def health():
    return {"connected": ib.isConnected()}

@app.get("/positions")
async def positions():
    result = []
    for p in ib.positions():
        result.append({
            "symbol": p.contract.symbol,
            "quantity": p.position,
            "avg_cost": p.avgCost,
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

    result = {}
    for item in summary:
        if item.tag in wanted: 
            result[wanted[item.tag]] = float(item.value)
            result["currency"] = item.currency
    return result