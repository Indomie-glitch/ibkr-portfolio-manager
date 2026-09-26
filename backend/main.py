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