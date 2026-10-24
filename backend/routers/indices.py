"""Company connections (Milestone 9): index members (#109), the indexes a stock belongs to (#110)
and its competitors (#111)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

import competitors
import constituents
import fx
import yahoo
from ib_core import get_contract_info, ib, require_ib
from routers.positions import call_yahoo, yahoo_info

router = APIRouter()


def market_of(contract):
    """"ASX" or "US" for the markets whose indexes we load, else None."""
    exchange = contract.primaryExchange or contract.exchange
    if exchange == "ASX":
        return "ASX"
    return "US" if exchange in yahoo.US_EXCHANGES else None


@router.get("/indices")
def indices_status():
    """Each index: member count, the holdings file's date (as_of), when it was fetched, and whether
    the last download failed (stale: an older copy is shown), plus the market caps' dates."""
    return constituents.status()


@router.get("/indices/{con_id}", dependencies=[Depends(require_ib)])
async def stock_indices(con_id: int):
    """The indexes a stock belongs to, with its weight (%) and rank (1 = largest weight) in each.
    Stocks on other markets, or in none of the indexes, get an empty list."""
    contract, _ = await get_contract_info(con_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Unknown contract")
    market = market_of(contract)
    return {
        "con_id": con_id,
        "symbol": contract.symbol,
        "market": market,
        "indices": constituents.indices_for(contract.symbol, market) if market else [],
    }


@router.get("/indices/{index_id}/members")
def index_members(index_id: str):
    """One index's members, largest weight first: symbol, name, weight, rank, sector, industry
    (Yahoo's, or the fund's GICS ones until looked up: classification), market cap (USD or AUD)."""
    if index_id not in constituents.INDEXES:
        raise HTTPException(status_code=404, detail=f"Unknown index; one of {', '.join(constituents.INDEXES)}")
    return constituents.members(index_id)


def owned_stocks():
    """{(market, symbol): con_id} of the stocks held now."""
    owned = {}
    for item in ib.portfolio():
        market = market_of(item.contract)
        if item.contract.secType == "STK" and market and item.position:
            owned[(market, item.contract.symbol)] = item.contract.conId
    return owned


async def competitor_target(contract, market, universe):
    """The stock as competitors.find wants it: from the index universe once its Yahoo profile is in,
    else (not in an index, or not looked up yet) from its Yahoo profile now (cached an hour)."""
    member = next((c for c in universe if (c["market"], c["symbol"]) == (market, contract.symbol)), None)
    if member and member["profile_at"]:
        return member
    info = await call_yahoo(lambda: yahoo_info(yahoo.ticker_for(contract.symbol, market)))
    change = yahoo._number(info.get("52WeekChange"))
    return {
        "market": market, "symbol": contract.symbol, "name": info.get("longName") or info.get("shortName"),
        "sector": info.get("sector"), "industry": info.get("industry"),
        "market_cap": yahoo._number(info.get("marketCap")), "pe": yahoo._number(info.get("trailingPE")),
        "return_1y": change * 100 if change is not None else None,
    }


@router.get("/competitors/{con_id}", dependencies=[Depends(require_ib)])
async def stock_competitors(con_id: int, scope: Literal["all", "same_market"] = "all"):
    """Companies in the stock's Yahoo industry among the index members (both markets), largest
    market cap first, each with market, market cap, 1-year price change, P/E and whether you own it;
    the stock itself is marked (is_self). Fewer than 4 competitors widens to related industries,
    then the sector (level, label). status: "ready", "loading" (sectors are still being looked up,
    so the list may be incomplete; progress says how far), "no_industry" (Yahoo has none, e.g. an
    ETF) or "unsupported" (a market whose indexes aren't loaded). scope "same_market" compares only
    with companies on the stock's own market (ranked among them, so ASX peers aren't crowded out by
    larger US ones); "all" (the default) uses both markets."""
    contract, _ = await get_contract_info(con_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Unknown contract")
    market = market_of(contract)
    answer = {"con_id": con_id, "symbol": contract.symbol, "market": market}
    if market is None:
        return {**answer, "status": "unsupported", "companies": []}
    universe = constituents.universe()
    progress = constituents.profile_progress()
    target = await competitor_target(contract, market, universe)
    if not target["industry"]:
        return {**answer, "status": "no_industry", "progress": progress, "companies": []}
    aud = await fx.rate_to_base("AUD", "USD")
    if aud is None:
        raise HTTPException(status_code=502, detail="No AUD to USD exchange rate to compare market caps")
    pool = [c for c in universe if c["market"] == market] if scope == "same_market" else universe
    found = competitors.find(target, pool, {"USD": 1.0, "AUD": aud}, owned_stocks())
    return {**answer, "scope": scope, "status": "ready" if progress["complete"] else "loading", "progress": progress,
            "market_data": constituents.status()["market_data"], **found}
