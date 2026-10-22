"""The Risk page (Milestone 8): GET /risk?period=3M|1Y|3Y.

One answer holds every section of the page. Each section is calculated on its own (SECTIONS), so a
section that fails becomes {"error": "..."} and only that panel says "unavailable". Money is in the
account's base currency (GET /account), with its home market index for attribution (#271).
"""
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

import config
import fx
import risk
import risk_data
import risk_sections
import yahoo
from cache import cached
from ib_core import get_contract_info, require_ib
from routers.positions import account, positions, quotes, yahoo_info
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
            "market_value": position["market_value"], "quantity": position["quantity"],
        })
    for holding in holdings:
        holding["sector"] = await sector_of(holding["yahoo"])
    return holdings


def build_response(inputs, now):
    """meta + holdings + one key per section."""
    benchmarks = inputs.benchmarks
    fallback = [b["short"] for b in benchmarks.values() if not b["total_return"]]
    notes = ([f"No total return series for the {' and '.join(fallback)}: price index used, "
              "so dividends are left out on that side"] if fallback else []) + inputs.notes
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
            "currency": inputs.base_currency,
            "home_market": inputs.home_market,
            # The other currencies held (or compared with), each with its rate series
            "fx_pairs": [{"currency": c, "pair": inputs.pair(c).label, "symbol": inputs.pair(c).symbol}
                         for c in sorted(inputs.fx_returns)],
            "cash_excluded": True,
            "risk_free_rate": config.risk_free_rate(),
            "trading_days_per_year": 252,
            "benchmarks": benchmarks,
            "benchmark_note": ". ".join(notes) or None,
            "stale": inputs.stale,
        },
        "holdings": [{k: h.get(k) for k in ("con_id", "symbol", "name", "market", "currency", "sector", "value_base", "weight")}
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


# Altman Z doesn't suit companies whose debts are their business, or that carry debt by design
NOT_FOR_Z = {"Financial Services"}
LOW_BY_DESIGN = {"Utilities", "Real Estate"}


async def market_cap_in(info, currency, today):
    """The company's market value in the currency of its accounts (BHP is listed in AUD but reports in
    USD), at the latest stored daily close of that pair (fx.Pair). None if there are no rates."""
    market_cap, quoted = info.get("marketCap"), info.get("currency")
    if market_cap is None or not currency or not quoted or quoted == currency:
        return market_cap
    pair = fx.Pair(quoted, currency)  # accounts' currency per 1 unit of the quoted one
    quotes = await risk_data.update(pair.symbol, today)  # stored daily closes
    if not quotes:
        return None
    return pair.to_base(market_cap, quotes[max(quotes)])


async def altman_row(holding):
    """One holding's Altman Z score from its latest annual accounts (cached a day)."""
    row = {"symbol": holding["symbol"], "name": holding["name"], "sector": holding["sector"]}
    if holding["sector"] in NOT_FOR_Z:
        return {**row, "zone": "bank", "score": None}
    if not holding["yahoo"]:
        return {**row, "zone": "unavailable", "score": None}
    try:
        accounts = await cached(("altman", holding["yahoo"]), 24 * 60 * 60,
                                lambda: yahoo.fetch_altman_inputs(holding["yahoo"]))
        info = await yahoo_info(holding["yahoo"])
        market_cap = await market_cap_in(info, info.get("financialCurrency"), datetime.now().date())
    except Exception as exc:
        print(f"Altman Z for {holding['symbol']} unavailable: {mask_secrets(exc)}")
        return {**row, "zone": "unavailable", "score": None}
    score, parts = risk.altman_z(accounts["working_capital"], accounts["retained_earnings"], accounts["ebit"],
                                 market_cap, accounts["total_liabilities"], accounts["revenue"], accounts["total_assets"])
    if score is None:
        return {**row, "zone": "unavailable", "score": None, "balance_date": accounts["balance_date"]}
    return {**row, "zone": risk.altman_zone(score), "score": round(score, 2),
            "parts": {k: round(v, 4) for k, v in parts.items()}, "balance_date": accounts["balance_date"],
            "low_by_design": holding["sector"] in LOW_BY_DESIGN}


@router.get("/risk/bankruptcy", dependencies=[Depends(require_ib)])
async def risk_bankruptcy():
    """RSK 11: each holding's Altman Z score. Separate from GET /risk so a Yahoo failure here only
    affects this panel (502 when no holding could be scored)."""
    holdings = await risk_holdings()
    if not holdings:
        raise HTTPException(404, "There are no share holdings to analyse.")
    rows = [await altman_row(h) for h in holdings]
    if all(r["zone"] == "unavailable" for r in rows):
        raise HTTPException(502, "Couldn't get the companies' accounts from Yahoo.")
    order = {"safe": 0, "grey": 0, "distress": 0, "bank": 1, "unavailable": 2}
    rows.sort(key=lambda r: (order[r["zone"]], -(r["score"] or 0)))
    return {"holdings": rows, "thresholds": {"safe": risk.Z_SAFE, "distress": risk.Z_DISTRESS}}


@router.get("/risk", dependencies=[Depends(require_ib)])
async def risk_overview(period: Literal["3M", "1Y", "3Y"] = "1Y"):
    holdings = await risk_holdings()
    if not holdings:
        raise HTTPException(404, "There are no share holdings to analyse.")
    now = datetime.now().astimezone()
    # Everything is in the account's base currency, and its cash already is
    try:
        summary = await account()
    except Exception as exc:
        print(f"Risk: no account figures: {mask_secrets(exc)}")
        raise HTTPException(502, "Couldn't read the account's currency from IB.")
    base = summary.get("currency")
    if not base:
        raise HTTPException(502, "Couldn't read the account's currency from IB.")
    # The same holdings and quantities on the same day give the same answer
    signature = tuple(sorted((h["con_id"], round(h["market_value"] or 0)) for h in holdings))

    async def compute():
        inputs = await risk_data.build_inputs(holdings, period, now.date(), base=base)
        inputs.cash_base = summary.get("cash")
        # Average daily volume (IB's 3-month average, as on the stock detail) for the liquidity panel
        try:
            volume = {q["con_id"]: q.get("avg_volume") for q in await quotes()}
            for holding in inputs.holdings:
                holding["avg_volume"] = volume.get(holding["con_id"])
        except Exception as exc:
            print(f"Risk: no volumes: {mask_secrets(exc)}")
        # Past crashes for the stress tests: fetched once per symbol, then kept
        symbols = ([h["yahoo"] for h in inputs.holdings] + [inputs.pair(c).symbol for c in inputs.fx_returns]
                   + risk_data.benchmark_symbols(inputs.benchmarks))
        try:
            inputs.scenarios = await risk_data.scenario_returns(symbols)
        except Exception as exc:
            print(f"Risk: no stress test prices: {mask_secrets(exc)}")
        return build_response(inputs, now)

    try:
        return await cached(("risk", period, now.date(), base, signature), RESULT_TTL, compute)
    except risk_data.NotEnoughData as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        print(f"Risk analysis failed: {mask_secrets(exc)}")
        raise HTTPException(502, "Couldn't get the daily prices from Yahoo.")
