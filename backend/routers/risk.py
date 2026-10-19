"""The Risk page (Milestone 8): GET /risk?period=3M|1Y|3Y.

One answer holds every section of the page. Each section is calculated on its own (SECTIONS), so a
section that fails becomes {"error": "..."} and only that panel says "unavailable".
"""
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

import config
import risk_data
import risk_sections
import yahoo
from cache import cached
from ib_core import get_contract_info, require_ib
from routers.positions import account, positions, yahoo_info
from secrets_guard import mask_secrets

router = APIRouter()

RESULT_TTL = 600  # seconds: prices are daily, so the maths needn't be redone on every refresh

# name -> function(inputs) returning that section (risk_sections.py)
SECTIONS = risk_sections.SECTIONS


def market_of(contract, exchange):
    exchange = (contract.primaryExchange if contract else None) or exchange
    if exchange == "ASX":
        return "ASX"
    if exchange in yahoo.US_EXCHANGES:
        return "US"
    return None


async def sector_of(symbol):
    """The company's sector from its Yahoo profile (cached an hour), or None."""
    if not symbol:
        return None
    try:
        return (await yahoo_info(symbol)).get("sector")
    except Exception as exc:
        print(f"Risk: no sector for {symbol}: {mask_secrets(exc)}")
        return None


async def risk_holdings():
    """Stock positions with what the risk maths needs (from IB, and the sector from Yahoo)."""
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
    for holding in holdings:
        holding["sector"] = await sector_of(holding["yahoo"])
    return holdings


def cash_in_aud(summary):
    """The account's cash in AUD from GET /account's figures, or None if it can't be converted."""
    cash, base = summary.get("cash"), summary.get("currency")
    if cash is None:
        return None
    if base == "AUD":
        return cash
    rate = (summary.get("fx_rates") or {}).get("AUD")  # 1 AUD in the base currency
    return cash / rate if rate else None


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
        "holdings": [{k: h.get(k) for k in ("con_id", "symbol", "name", "market", "currency", "sector", "value_aud", "weight")}
                     for h in inputs.holdings],
    }
    for name, section in SECTIONS.items():
        try:
            response[name] = section(inputs)
            # NaN or infinity isn't valid JSON: the browser couldn't read any of the answer
            json.dumps(response[name], allow_nan=False)
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
        try:
            inputs.cash_aud = cash_in_aud(await account())
        except Exception as exc:
            print(f"Risk: no cash figure: {mask_secrets(exc)}")
        # Past crashes for the stress tests: fetched once per symbol, then kept
        symbols = [h["yahoo"] for h in inputs.holdings] + [yahoo.AUDUSD] + [
            s for b in yahoo.RISK_BENCHMARKS.values() for s in (b["symbol"], b["fallback"])]
        try:
            inputs.scenarios = await risk_data.scenario_returns(symbols)
        except Exception as exc:
            print(f"Risk: no stress test prices: {mask_secrets(exc)}")
        return build_response(inputs, now)

    try:
        return await cached(("risk", period, now.date(), signature), RESULT_TTL, compute)
    except risk_data.NotEnoughData as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        print(f"Risk analysis failed: {mask_secrets(exc)}")
        raise HTTPException(502, "Couldn't get the daily prices from Yahoo.")
