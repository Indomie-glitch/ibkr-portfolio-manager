"""The Risk page (Milestone 8): GET /risk?period=3M|1Y|3Y.

One answer holds every section of the page. Each section is calculated on its own (SECTIONS), so a
section that fails becomes {"error": "..."} and only that panel says "unavailable".
"""
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

import config
import risk_data
import yahoo
from cache import cached
from ib_core import get_contract_info, require_ib
from routers.positions import positions
from secrets_guard import mask_secrets

router = APIRouter()

RESULT_TTL = 600  # seconds: prices are daily, so the maths needn't be redone on every refresh

# name -> function(inputs) returning that section; later issues add theirs here
SECTIONS = {}


def market_of(contract, exchange):
    exchange = (contract.primaryExchange if contract else None) or exchange
    if exchange == "ASX":
        return "ASX"
    if exchange in yahoo.US_EXCHANGES:
        return "US"
    return None


async def risk_holdings():
    """Stock positions with what the risk maths needs (from IB)."""
    holdings = []
    for position in await positions():
        if position["sec_type"] != "STK":
            continue
        contract, _ = await get_contract_info(position["con_id"])
        holdings.append({
            "con_id": position["con_id"], "symbol": position["symbol"], "name": position["name"],
            "market": market_of(contract, position["exchange"]), "currency": position["currency"],
            "yahoo": yahoo.yahoo_symbol(contract) if contract else None,
            "market_value": position["market_value"],
        })
    return holdings


def build_response(inputs, now):
    """meta + holdings + one key per section."""
    benchmarks = inputs.benchmarks
    fallback = [b["short"] for b in benchmarks.values() if not b["total_return"]]
    response = {
        "meta": {
            "period": inputs.period,
            "calculated_at": now.isoformat(timespec="seconds"),
            "start": inputs.start.isoformat(),
            "first_day": inputs.dates[0].isoformat(),
            "last_day": inputs.dates[-1].isoformat(),
            "days_used": inputs.days_used,
            "holdings_count": len(inputs.holdings),
            "left_out": inputs.left_out,
            "currency": "AUD",
            "cash_excluded": True,
            "risk_free_rate": config.risk_free_rate(),
            "trading_days_per_year": 252,
            "benchmarks": benchmarks,
            "benchmark_note": (f"No total return series for the {' and '.join(fallback)}: price index used, "
                               "so dividends are left out on that side") if fallback else None,
            "stale": inputs.stale,
        },
        "holdings": [{k: h[k] for k in ("con_id", "symbol", "name", "market", "currency", "value_aud", "weight")}
                     for h in inputs.holdings],
    }
    for name, section in SECTIONS.items():
        try:
            response[name] = section(inputs)
        except Exception as exc:
            print(f"Risk section {name} failed: {mask_secrets(exc)}")
            response[name] = {"error": "Couldn't calculate this section."}
    return response


@router.get("/risk", dependencies=[Depends(require_ib)])
async def risk_overview(period: Literal["3M", "1Y", "3Y"] = "1Y"):
    holdings = await risk_holdings()
    if not holdings:
        raise HTTPException(404, "There are no share holdings to analyse.")
    now = datetime.now().astimezone()
    # The same holdings and quantities on the same day give the same answer
    signature = tuple(sorted((h["con_id"], round(h["market_value"] or 0)) for h in holdings))

    async def compute():
        inputs = await risk_data.build_inputs(holdings, period, now.date())
        return build_response(inputs, now)

    try:
        return await cached(("risk", period, now.date(), signature), RESULT_TTL, compute)
    except risk_data.NotEnoughData as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        print(f"Risk analysis failed: {mask_secrets(exc)}")
        raise HTTPException(502, "Couldn't get the daily prices from Yahoo.")
