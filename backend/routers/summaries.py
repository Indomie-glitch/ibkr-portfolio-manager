"""AI summaries: one stock (Milestone 5) and the whole portfolio (Milestone 5.2)."""
import asyncio
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

import ai_summary
import config
import fx
import lots
import portfolio_facts
import portfolio_summary
import summary_facts
import summary_store
import usage_store
import yahoo
from cache import cached
from ib_core import get_bars, get_contract_info, require_ib
from secrets_guard import mask_secrets
from web import check_origin, sse
from routers import risk as risk_routes
from routers.positions import account, news_items, performance_data, positions, prices, quotes, yahoo_info

router = APIRouter()

# ---------- AI summary ----------

def not_owned_position(contract, long_name, quote):
    """What build_facts needs about a stock the investor doesn't own (#95): names and the price only."""
    return {
        "con_id": contract.conId, "symbol": contract.symbol, "name": long_name or contract.symbol,
        "exchange": contract.primaryExchange or contract.exchange, "currency": contract.currency,
        "market_price": (quote or {}).get("last"), "market_value": None, "owned": False,
    }

async def summary_facts_for(con_id):
    """Gather IB and Yahoo data for one stock and build the facts sheet (no Claude call). Works for
    holdings and for any stock found on Markets (then without D:position)."""
    contract, long_name = await get_contract_info(con_id)
    if contract is None:
        raise HTTPException(status_code=404, detail="Unknown stock")
    all_positions = await positions()
    position = next((p for p in all_positions if p["con_id"] == con_id), None)
    if position is None and contract.secType != "STK":
        raise HTTPException(status_code=404, detail="AI summaries of stocks you don't own are for shares only")
    if position is not None:
        quote = next((q for q in await quotes() if q["con_id"] == con_id), None)
    else:
        found = await prices(str(con_id))
        quote = found[0] if found else None
        position = not_owned_position(contract, long_name, quote)
    owned = position.get("owned", True)
    account_data = await account()
    fx_rates = account_data["fx_rates"]
    base = account_data["currency"]

    def to_base(p):
        rate = fx_rates.get(p["currency"], 1 if p["currency"] == base else None)
        return (p["market_value"] or 0) * rate if rate is not None else 0

    symbol = yahoo.yahoo_symbol(contract)
    is_asx = (contract.primaryExchange or contract.exchange) == "ASX"

    async def unavailable():
        raise yahoo.YahooUnavailable("This exchange isn't covered by Yahoo Finance here")

    def yahoo_loader(load):
        return load if symbol else unavailable

    index_symbol = yahoo.PRICE_INDEXES["ASX" if is_asx else "US"]
    loaders = {
        "info": yahoo_loader(lambda: yahoo_info(symbol)),
        "financials": yahoo_loader(lambda: cached(("financials", symbol), 24 * 60 * 60, lambda: yahoo.fetch_financials(symbol))),
        "dividends": yahoo_loader(lambda: cached(("dividends", symbol), 24 * 60 * 60, lambda: yahoo.fetch_dividends(symbol))),
        "performance": yahoo_loader(lambda: performance_data(contract, symbol)),
        "index_closes": lambda: cached(("index", index_symbol), 60 * 60, lambda: yahoo.fetch_index_closes(index_symbol)),
        "index_intraday": lambda: cached(("index_5m", index_symbol), 5 * 60, lambda: yahoo.fetch_index_intraday(index_symbol)),
        "news": yahoo_loader(lambda: news_items(contract, symbol)),
    }
    inputs = {
        "position": position,
        "quote": quote,
        "bars": await get_bars(con_id, "3 M", "1 day", max_age=15 * 60),
        "base_currency": base,
        # A stock you don't own may be in a currency with no ledger rate (#270)
        "fx_rate": await fx.rate_to_base(position["currency"], base, fx_rates) or 1,
        "total_market_value_base": sum(to_base(p) for p in all_positions),
        "is_asx": is_asx,
        "index_symbol": index_symbol,
        # Purchase lots from the Flex report (local, never waits for IBKR); empty without one
        "lots": lots.lots_for(con_id, position["quantity"]) if owned else None,
    }
    return await summary_facts.build_facts(inputs, loaders, previous=summary_store.latest(con_id))

@router.get("/summary/{con_id}/facts", dependencies=[Depends(require_ib)])
async def summary_facts_preview(con_id: int):
    """Exactly what the model would be given for this holding. Free: no Claude call."""
    result = await summary_facts_for(con_id)
    return {"facts": summary_facts.model_facts(result["facts"]), "links": result["links"],
            "source_ids": summary_facts.source_ids(result["facts"])}

BENCHMARK_NAMES = {"ASX": "S&P/ASX 200", "US": "S&P 500"}

async def holding_inputs(position, quote, today, missing):
    """IB and Yahoo data for one holding of the portfolio facts sheet; gaps are recorded in missing."""
    contract, _ = await get_contract_info(position["con_id"])
    symbol = yahoo.yahoo_symbol(contract) if contract else None
    market = portfolio_facts.market_of(position)
    index_symbol = yahoo.PRICE_INDEXES[market]
    label = position["symbol"]
    inputs = {"position": position, "quote": quote, "benchmark": BENCHMARK_NAMES[market],
              "sector": None, "beta": None, "events": [], "dividends_12m": None, "closes": None, "index_closes": None}
    if symbol is None:
        missing.append(f"{label}: not covered by Yahoo Finance (sector, beta, events and dividends)")
    else:
        info = await summary_facts.safe(lambda: yahoo_info(symbol), f"{label} company data", missing)
        if info:
            stats = yahoo.stats_from_info(info)
            inputs.update(sector=info.get("sector"), beta=stats["beta"])
            for key, event in (("earnings_date", "Earnings result"), ("ex_dividend_date", "Ex-dividend date")):
                if stats[key]:
                    inputs["events"].append((date.fromisoformat(stats[key]), event))
        dividends = await summary_facts.safe(
            lambda: cached(("dividends", symbol), 24 * 60 * 60, lambda: yahoo.fetch_dividends(symbol)), f"{label} dividends", missing)
        if dividends is not None:
            cutoff = today - timedelta(days=365)
            inputs["dividends_12m"] = sum(amount for day, amount in dividends if cutoff < day <= today)
    try:
        bars = await get_bars(position["con_id"], "3 M", "1 day", max_age=15 * 60)
        inputs["closes"] = [(b.date if isinstance(b.date, date) else b.date.date(), b.close) for b in bars]
    except Exception as exc:
        missing.append(f"{label}: price history unavailable ({exc.__class__.__name__})")
    inputs["index_closes"] = await summary_facts.safe(
        lambda: cached(("index", index_symbol), 60 * 60, lambda: yahoo.fetch_index_closes(index_symbol)),
        f"{BENCHMARK_NAMES[market]} closes", missing)
    return inputs

async def portfolio_facts_for():
    """Gather IB and Yahoo data for every holding and build the portfolio facts sheet (no Claude call)."""
    now = datetime.now().astimezone()
    today = now.date()
    missing = []
    quote_by_id = {q["con_id"]: q for q in await quotes()}
    holdings = []
    for position in await positions():
        if position["sec_type"] == "STK":
            holdings.append(await holding_inputs(position, quote_by_id.get(position["con_id"]), today, missing))
    previous = summary_store.latest_portfolio()
    # The Risk page's findings (1Y) for D:risk; without them the summary still works
    try:
        risk = await risk_routes.risk_overview(period="1Y")
    except Exception as exc:
        print(f"Portfolio facts: risk analysis unavailable: {mask_secrets(exc)}")
        risk = None
    return portfolio_facts.build_portfolio_facts(await account(), holdings, now, missing,
                                                 previous=previous["facts"] if previous else None, risk=risk)

@router.get("/portfolio-summary/facts", dependencies=[Depends(require_ib)])
async def portfolio_summary_facts():
    """Exactly what the model would be given for the portfolio summary. Free: no Claude call."""
    facts = await portfolio_facts_for()
    return {"facts": facts, "source_ids": portfolio_facts.source_ids(facts)}

def saved_summary_response(record):
    facts = record["facts"]
    # Re-run the citation and rule checks, so improved checks also apply to older summaries
    allowed = set(summary_facts.source_ids(facts))
    summary, warnings = {}, []
    # A stock the investor didn't own when it was written has no your_position section (#95)
    for name in ai_summary.SECTIONS:
        if name not in record["summary"]:
            continue
        summary[name], section_warnings = ai_summary.validate_section(name, record["summary"][name], allowed, facts)
        warnings += section_warnings
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "as_of_text": facts.get("as_of_text"),
        "model": record["model"],
        "owned": facts.get("company", {}).get("owned_by_investor", True),
        "summary": summary,
        "warnings": warnings,
        "links": facts.get("links", {}),
        "missing": facts.get("D:missing", []),
        "facts": summary_facts.model_facts(facts),
    }

@router.get("/summary/{con_id}")
def latest_summary(con_id: int):
    """The last saved summary for a holding (shown instantly), and whether an API key is set."""
    record = summary_store.latest(con_id)
    return {
        "ai_configured": ai_summary.api_key_configured(),
        "missing_key_message": config.MISSING_KEY_MESSAGE,
        "model": config.ai_model(),
        "latest": saved_summary_response(record) if record else None,
    }

@router.get("/summary/{con_id}/history")
def summary_history(con_id: int):
    """Saved summaries of a holding, newest first: id, created_at, model and the price at the time."""
    return summary_store.history(con_id)

def saved_record(con_id, summary_id):
    record = summary_store.get(con_id, summary_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No saved summary with that id for this holding")
    return record

@router.get("/summary/{con_id}/history/{summary_id}")
def past_summary(con_id: int, summary_id: int):
    """One saved summary in full, in the same shape as the latest one."""
    return saved_summary_response(saved_record(con_id, summary_id))

@router.get("/summary/{con_id}/compare")
def compare_summaries(con_id: int, a: int, b: int):
    """Two saved summaries (older first) and the exact changes between their facts sheets."""
    older, newer = sorted((saved_record(con_id, a), saved_record(con_id, b)), key=lambda r: (r["created_at"], r["id"]))
    return {
        "older": saved_summary_response(older),
        "newer": saved_summary_response(newer),
        "data_changes": summary_facts.compare_data(older["facts"], newer["facts"]),
    }

def check_generate_request(request):
    check_origin(request)
    if not ai_summary.api_key_configured():
        raise HTTPException(status_code=503, detail=config.MISSING_KEY_MESSAGE)

# One generation per holding at a time, so a double click doesn't pay twice
summary_locks = {}

async def summary_events(lock, *, gather, feature, con_id=None, subject, log_name, facts_log_name):
    """The Server-Sent Events of generating a summary, shared by the stock and the portfolio summary:
    status -> facts -> section (one per finished section) -> done, or error. One at a time per lock.

    gather(): an async function returning {"facts_event", "stream", "finish"} (stream() yields
    stream_sections' events; finish(summary, warnings, usage) saves and returns the done payload), or
    {"problem": {code, message}} to stop with that error. Every call to Claude is logged in
    usage_store, including a refused or cut-off answer (it's still billed)."""
    async with lock:
        yield sse("status", {"message": "Gathering data"})
        try:
            plan = await gather()
        except Exception as exc:
            print(f"{facts_log_name} failed: {exc.__class__.__name__}: {mask_secrets(exc)}")
            yield sse("error", {"code": "facts_failed", "message": f"Couldn't gather the data for {subject}."})
            return
        if "problem" in plan:
            yield sse("error", plan["problem"])
            return
        yield sse("facts", plan["facts_event"])
        try:
            async for kind, *payload in plan["stream"]():
                if kind == "section":
                    name, section, warnings = payload
                    yield sse("section", {"name": name, "section": section, "warnings": warnings})
                else:
                    summary, warnings, usage = payload
                    usage_store.record(feature, config.ai_model(), usage, con_id)
                    yield sse("done", plan["finish"](summary, warnings, usage))
        except ai_summary.SummaryError as exc:
            if exc.usage:
                usage_store.record(feature, config.ai_model(), exc.usage, con_id, outcome=exc.code)
            yield sse("error", {"code": exc.code, "message": exc.message})
        except Exception as exc:
            print(f"{log_name} failed: {exc.__class__.__name__}: {mask_secrets(exc)}")
            yield sse("error", {"code": "unexpected", "message": "Something went wrong while writing the summary."})

def event_stream(events):
    # no-cache and X-Accel-Buffering stop anything in between from holding events back
    return StreamingResponse(events, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@router.post("/summary/{con_id}", dependencies=[Depends(require_ib)])
async def generate_summary(con_id: int, request: Request):
    """Generate a new summary and stream it as Server-Sent Events:
    facts -> section (one per finished section) -> done, or error."""
    check_generate_request(request)
    lock = summary_locks.setdefault(con_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(status_code=409, detail="A summary for this holding is already being written")

    async def gather():
        built = await summary_facts_for(con_id)
        facts, links = built["facts"], built["links"]
        ids = summary_facts.source_ids(facts)
        sections, system = ai_summary.briefing_for(facts["company"]["owned_by_investor"])

        def finish(summary, warnings, usage):
            summary_store.save(con_id, facts["company"]["symbol"], facts["as_of"],
                               config.ai_model(), {**facts, "links": links}, summary, warnings)
            print(f"Summary for {facts['company']['symbol']}: {usage['input_tokens']} in, "
                  f"{usage['output_tokens']} out, {len(warnings)} warnings")
            return saved_summary_response(summary_store.latest(con_id))

        return {
            "facts_event": {"as_of_text": facts["as_of_text"], "links": links,
                            "missing": facts["D:missing"], "facts": summary_facts.model_facts(facts)},
            "stream": lambda: ai_summary.stream_sections(summary_facts.model_facts(facts), ids,
                                                         sections=sections, system=system),
            "finish": finish,
        }

    return event_stream(summary_events(lock, gather=gather, feature="stock_summary", con_id=con_id,
                                       subject="this holding", log_name="Summary", facts_log_name="Summary facts"))


# ---------- AI portfolio summary (Milestone 5.2) ----------

def saved_portfolio_response(record):
    facts = record["facts"]
    allowed = set(portfolio_facts.source_ids(facts))
    summary, warnings = {}, []
    for name in portfolio_summary.SECTIONS:
        summary[name], section_warnings = portfolio_summary.validate_section(name, record["summary"][name], allowed, facts)
        warnings += section_warnings
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "as_of_text": facts.get("as_of_text"),
        "model": record["model"],
        "summary": summary,
        "warnings": warnings,
        "missing": facts.get("D:missing", []),
        "facts": facts,
    }

@router.get("/portfolio-summary")
def latest_portfolio_summary():
    """The last saved portfolio summary (shown instantly), and whether an API key is set."""
    record = summary_store.latest_portfolio()
    return {
        "ai_configured": ai_summary.api_key_configured(),
        "missing_key_message": config.MISSING_KEY_MESSAGE,
        "model": config.ai_model(),
        "latest": saved_portfolio_response(record) if record else None,
    }

@router.get("/portfolio-summary/history")
def portfolio_summary_history():
    """Saved portfolio summaries, newest first: id, created_at, model and net liquidation at the time."""
    return summary_store.portfolio_history()

@router.get("/portfolio-summary/history/{summary_id}")
def past_portfolio_summary(summary_id: int):
    """One saved portfolio summary in full, in the same shape as the latest one."""
    return saved_portfolio_response(saved_portfolio_record(summary_id))

def saved_portfolio_record(summary_id):
    record = summary_store.get_portfolio(summary_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No saved portfolio summary with that id")
    return record

@router.get("/portfolio-summary/compare")
def compare_portfolio_summaries(a: int, b: int):
    """Two saved portfolio summaries (older first) and the exact changes between their facts sheets."""
    older, newer = sorted((saved_portfolio_record(a), saved_portfolio_record(b)), key=lambda r: (r["created_at"], r["id"]))
    return {
        "older": saved_portfolio_response(older),
        "newer": saved_portfolio_response(newer),
        "data_changes": portfolio_facts.compare_data(older["facts"], newer["facts"]),
    }

portfolio_summary_lock = asyncio.Lock()

@router.post("/portfolio-summary", dependencies=[Depends(require_ib)])
async def generate_portfolio_summary(request: Request):
    """Generate a portfolio summary, streamed as Server-Sent Events like POST /summary/{con_id}:
    status -> facts -> section (one per finished section) -> done, or error."""
    check_generate_request(request)
    if portfolio_summary_lock.locked():
        raise HTTPException(status_code=409, detail="A portfolio summary is already being written")

    async def gather():
        facts = await portfolio_facts_for()
        if not facts["D:portfolio"]["number_of_holdings"]:
            return {"problem": {"code": "no_holdings", "message": "There are no share holdings to summarise."}}

        def finish(summary, warnings, usage):
            summary_store.save_portfolio(facts["as_of"], config.ai_model(), facts, summary, warnings)
            print(f"Portfolio summary: {usage['input_tokens']} in, {usage['output_tokens']} out, "
                  f"{len(warnings)} warnings")
            return saved_portfolio_response(summary_store.latest_portfolio())

        return {
            "facts_event": {"as_of_text": facts["as_of_text"], "missing": facts["D:missing"], "facts": facts},
            "stream": lambda: portfolio_summary.stream_sections(facts, portfolio_facts.source_ids(facts)),
            "finish": finish,
        }

    return event_stream(summary_events(portfolio_summary_lock, gather=gather, feature="portfolio_summary",
                                       subject="the portfolio", log_name="Portfolio summary",
                                       facts_log_name="Portfolio facts"))


# ---------- Claude API usage and cost (#86) ----------

@router.get("/usage")
def usage(month: str | None = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):
    """Tokens and estimated cost (US$) of every Claude call in a month (default this month): stock
    summaries, portfolio summaries and news sentiment. Works without IB Gateway."""
    return usage_store.monthly(month)
