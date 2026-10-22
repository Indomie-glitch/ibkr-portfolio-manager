"""Index members (Milestone 9: #109) and the indexes a stock belongs to (#110)."""

from fastapi import APIRouter, Depends, HTTPException

import constituents
import yahoo
from ib_core import get_contract_info, require_ib

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
