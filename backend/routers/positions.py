"""Positions, account, quotes, search, price history and the Yahoo Finance stock sections."""
import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

import yahoo
from cache import cached
from ib_core import build_quote, clean, fetch_tickers, get_bars, get_contract_info, ib, require_ib
from names import display_name, short_company_name
from secrets_guard import mask_secrets

router = APIRouter()

@router.get("/positions", dependencies=[Depends(require_ib)])
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

@router.get("/account", dependencies=[Depends(require_ib)])
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

@router.get("/quotes", dependencies=[Depends(require_ib)])
async def quotes():
    items = ib.portfolio()
    infos = await asyncio.gather(*(get_contract_info(i.contract.conId) for i in items))
    tickers = await fetch_tickers([contract for contract, _ in infos if contract])
    return await asyncio.gather(*(build_quote(i.contract.conId, tickers.get(i.contract.conId), clean(i.marketPrice))
                                  for i in items))

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

@router.get("/search", dependencies=[Depends(require_ib)])
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

@router.get("/prices", dependencies=[Depends(require_ib)])
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

@router.get("/history/{con_id}", dependencies=[Depends(require_ib)])
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

@router.get("/profile/{con_id}", dependencies=[Depends(require_ib)])
async def profile(con_id: int):
    """About section: description, sector, industry, employees, fiscal year end, website (cached 1 hour)."""
    _, symbol = await yahoo_target(con_id)
    info = await call_yahoo(lambda: yahoo_info(symbol))
    result = yahoo.profile_from_info(info)
    result["short_name"] = short_company_name(result["long_name"])
    result["yahoo_symbol"] = symbol
    return result

@router.get("/stats/{con_id}", dependencies=[Depends(require_ib)])
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

@router.get("/news/{con_id}", dependencies=[Depends(require_ib)])
async def news(con_id: int):
    """Recent headlines that mention the company, newest first (cached 15 minutes)."""
    contract, symbol = await yahoo_target(con_id)
    items = await call_yahoo(lambda: news_items(contract, symbol))
    return {"items": items}

@router.get("/performance/{con_id}", dependencies=[Depends(require_ib)])
async def performance(con_id: int):
    """Total return over YTD, 1Y, 3Y and 5Y for the stock and its benchmark (cached 1 day)."""
    contract, symbol = await yahoo_target(con_id)
    return await call_yahoo(lambda: performance_data(contract, symbol))
