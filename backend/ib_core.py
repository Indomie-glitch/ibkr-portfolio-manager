"""The shared connection to IB Gateway: the IB client, connection status, contract and price
caches, quotes, and the require_ib dependency the IB endpoints use.
"""
import asyncio
import math
import os
import time

from fastapi import HTTPException
from ib_async import IB, Contract

import config  # first: loads .env before other modules read settings
from ib_connection import ConnectionStatus

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
                # Not read only: the app places orders (Milestone 6); every order passes trading.py's checks
                await ib.connectAsync(IB_HOST, port, clientId=connection.client_id, readonly=False)
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

NOT_CONNECTED = "IB Gateway is not connected"

def require_ib():
    """Endpoint dependency: answer 503 straight away instead of waiting on a dead connection."""
    if not ib.isConnected():
        raise HTTPException(status_code=503, detail=NOT_CONNECTED)
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
