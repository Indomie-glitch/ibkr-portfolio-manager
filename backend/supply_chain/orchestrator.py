"""The orchestrator (#126): what the pipeline does first, how much it may spend today, and how it spaces its Claude calls.

On top of the job queue (jobs.py) and the monthly budget (control.py):
- Holdings first. Companies the user holds (ib.portfolio() while IB is connected) are marked companies.held; jobs.claim adds
  jobs.HELD_BOOST to their jobs' priority, so everything about a held company runs before any theme company's. Held companies
  that aren't in the graph yet are added (US tickers are scouted; ASX ones wait for an ASX source, #131).
- Daily pace inside the monthly budget (no setting of its own): today's cap is the money left at the start of the day divided by the
  days left (counting today), never less than a floor of budget / PACE_FLOOR_DIVISOR, never more than what's left. A day and a month
  start at local midnight (control.py). Run now adds one more day's cap to today.
- Before each Claude call the job reserves its estimated cost (read_estimate, verify_estimate); a call that doesn't fit is not made:
  the job keeps what it has saved and queues the rest for the next day (the worker's defer_until). Work that fits goes on, so a
  cheap Haiku chunk can still run when a Sonnet batch doesn't fit. A single call bigger than a whole day's cap runs on a day
  with nothing spent yet; one bigger than what is left of the month waits for next month (Needs attention if no month could fit it).
- Claude calls share one Gate: at most MAX_CONCURRENT at a time, MIN_GAP_S apart, and after a 429 / 529 every worker waits for
  Retry-After (as sec_client does).
"""
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import anthropic

import config
import usage_store
from supply_chain import control, graph, jobs
from supply_chain.db import now as stamp_now

AI_KINDS = ("read", "verify")
PACE_FLOOR_DIVISOR = 60  # the floor of a day's cap: budget / 60, half an even daily share
MIN_USEFUL_USD = 0.002  # below this, the cheapest call (a small Haiku chunk) doesn't fit: AI jobs aren't claimed
DEFER_AFTER = timedelta(minutes=5)  # a deferred job runs a few minutes after the day (or month) turns over

PROMPT_TOKENS = 1_000  # the Reader's instructions and header around a chunk
READ_OUTPUT_RATIO = 0.05  # output tokens per input token: the first real chunk (AMD's risk factors) gave 2,022 for 38,864
READ_OUTPUT_MIN = 500
RATIO_MIN_ROWS = 20  # chunk_reads rows before the measured ratio replaces the default
VERIFY_PROMPT_TOKENS = 700
VERIFY_OUTPUT_PER_ITEM = 120

MAX_CONCURRENT = 2
MIN_GAP_S = 1.0
RETRY_STATUS = {429, 529}
RETRY_TRIES = 3
RETRY_WAIT_S = 30
RETRY_WAIT_MAX_S = 300


class limits:
    """Overrides for a one-off run (scripts/pipeline_run.py): no daily pace, and a hard cap on what the run may spend."""
    pacing = True
    run_cap_usd = None
    run_since = None


# ---------- The daily pace ----------

def run_now_extra(settings, now=None):
    """What Run now has added to today's allowance (it resets with the day)."""
    saved = settings.get("run_now") or {}
    return float(saved.get("usd") or 0) if saved.get("day") == control.today(now).isoformat() else 0.0


def pace(conn, now=None, settings=None):
    """Where today stands: {budget, spent_month, spent_today, month_left, days_left, cap, extra, reserved, allowance}.
    cap = today's base cap, extra = what Run now added, allowance = what may still be started now (after what running
    calls have reserved)."""
    settings = settings or control.load_settings()
    budget = settings["budget_usd"]
    month0, day0 = control.month_start(now), control.day_start(now)
    spent_month, spent_today = jobs.spent_since(conn, month0), jobs.spent_since(conn, day0)
    month_left = max(budget - spent_month, 0.0)
    left_at_day_start = max(budget - (spent_month - spent_today), 0.0)
    days_left = control.days_left_in_month(now)
    cap = min(left_at_day_start, max(left_at_day_start / days_left, budget / PACE_FLOOR_DIVISOR))
    extra = run_now_extra(settings, now)
    reserved = sum(_reserved.values())
    allowance = min(cap + extra - spent_today, month_left) if limits.pacing else month_left
    if limits.run_cap_usd is not None:
        allowance = min(allowance, limits.run_cap_usd - jobs.spent_since(conn, limits.run_since))
    return {"budget": budget, "spent_month": spent_month, "spent_today": spent_today, "month_left": month_left, "days_left": days_left,
            "cap": cap, "extra": extra, "reserved": reserved, "allowance": max(allowance - reserved, 0.0)}


_reserved = {}
_counter = 0


@dataclass
class Reservation:
    ok: bool
    estimate: float
    key: int = 0
    until: datetime = None  # when to try again (not ok)
    reason: str = ""

    def release(self):
        _reserved.pop(self.key, None)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


def _usd(value):
    return f"US${value:.2f}" if value >= 0.1 else f"US${value:.3f}"


def reserve(conn, estimate, now=None, settings=None):
    """Asks to make a call expected to cost `estimate` US$. ok: go ahead (use it as a context manager; the reservation counts
    against the allowance until released). Not ok: until / reason say when and why to try again."""
    global _counter
    p = pace(conn, now, settings)
    fits = estimate <= p["allowance"]
    if not fits and estimate <= p["month_left"] and p["reserved"] == 0 and p["spent_today"] == 0 and (
            limits.run_cap_usd is None or estimate <= limits.run_cap_usd - jobs.spent_since(conn, limits.run_since)):
        # bigger than a whole day's cap, but nothing has been spent today and nothing is running: it gets its day
        fits = estimate > p["cap"] + p["extra"]
    if fits:
        _counter += 1
        _reserved[_counter] = estimate
        return Reservation(True, estimate, _counter)
    if estimate > p["month_left"]:
        too_big = estimate > p["budget"]
        text = (f"too big for the budget (needs about {_usd(estimate)}, the monthly budget is {_usd(p['budget'])})" if too_big
                else f"waiting for next month's budget (needs about {_usd(estimate)}, {_usd(p['month_left'])} left)")
        return Reservation(False, estimate, until=control.next_month_start(now) + DEFER_AFTER, reason=text)
    return Reservation(False, estimate, until=control.next_day_start(now) + DEFER_AFTER,
                       reason=f"waiting for tomorrow's allowance (needs about {_usd(estimate)}, {_usd(p['allowance'])} left today)")


def add_run_now(conn, now=None, settings=None):
    """Run now: one more day's cap on today's allowance, as far as the month has money left. Returns the US$ added."""
    settings = settings or control.load_settings()
    p = pace(conn, now, settings)
    room = max(p["month_left"] - max(p["cap"] + p["extra"] - p["spent_today"], 0.0), 0.0)
    added = round(min(p["cap"], room), 6)
    if added > 0:
        control.save_settings(run_now={"day": control.today(now).isoformat(), "usd": round(p["extra"] + added, 6)})
    return added


def claimable_kinds(conn, kinds, now=None):
    """The kinds a worker may claim: the AI ones only while some allowance is left, so they aren't claimed and put off in a loop.
    Free work (scouting, downloads, XBRL, merging) always goes on."""
    kinds = list(kinds)
    if not set(AI_KINDS) & set(kinds):
        return kinds
    if pace(conn, now)["allowance"] >= MIN_USEFUL_USD:
        return kinds
    return [k for k in kinds if k not in AI_KINDS]


def requeue_later(conn, job, until, reason):
    """Queues the rest of a job's work again for `until` (the job itself is done; it did what it could)."""
    new_id, created = jobs.enqueue(conn, job["kind"], job["key"], job["payload"], priority=job["priority"], run_after=until,
                                   company_id=job.get("company_id"), document_id=job.get("document_id"), parent_job_id=job.get("parent_job_id"))
    if created:
        conn.execute("UPDATE jobs SET last_error = ? WHERE id = ?", (reason, new_id))
    return new_id


# ---------- Cost estimates ----------

def output_ratio(conn):
    """Output tokens per input token for a chunk read: measured from chunk_reads once there are enough, else the default."""
    out, inp, rows = conn.execute("SELECT SUM(output_tokens), SUM(input_tokens), COUNT(*) FROM chunk_reads WHERE input_tokens > 0").fetchone()
    return min(out / inp * 1.2, 0.3) if rows >= RATIO_MIN_ROWS and inp else READ_OUTPUT_RATIO  # 20% headroom on the measured ratio


def read_estimate(conn, chunk_tokens):
    """US$ for reading one chunk: its estimated tokens (which run 7-24% above the real count) plus the prompt, and the answer."""
    inp = chunk_tokens + PROMPT_TOKENS
    out = max(READ_OUTPUT_MIN, inp * output_ratio(conn))
    return usage_store.cost_usd(config.READER_MODEL, inp, out) or 0.0


def verify_estimate(item_tokens, items):
    """US$ for checking a batch of `items` candidates whose claims and contexts are about `item_tokens`."""
    inp = item_tokens + VERIFY_PROMPT_TOKENS
    return usage_store.cost_usd(config.VERIFIER_MODEL, inp, VERIFY_OUTPUT_PER_ITEM * items + 100) or 0.0


def charge(conn, run_id, attempts):
    """Records Claude calls on the run as they are made: attempts = [{model, input_tokens, output_tokens}]."""
    for a in attempts:
        cost = usage_store.cost_usd(a["model"], a["input_tokens"], a["output_tokens"])
        jobs.add_usage(conn, run_id, a["model"], a["input_tokens"], a["output_tokens"], cost)


# ---------- Spacing Claude calls ----------

def retry_after(exc, attempt):
    """Seconds to wait after a 429 / 529: the Retry-After header when it is a number, else RETRY_WAIT_S more each time."""
    header = str(getattr(getattr(exc, "response", None), "headers", {}).get("retry-after", "") or "")
    wait = float(header) if header.replace(".", "", 1).isdigit() else RETRY_WAIT_S * attempt
    return min(wait, RETRY_WAIT_MAX_S)


class Gate:
    """Shared by every worker: Claude calls start at least MIN_GAP_S apart, at most MAX_CONCURRENT run at once, and a 429 or
    overload makes all of them wait for Retry-After before the call is tried again (up to RETRY_TRIES times)."""

    def __init__(self, concurrent=None, gap_s=None, clock=time.monotonic, sleep=asyncio.sleep):
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT if concurrent is None else concurrent)
        self.gap_s = MIN_GAP_S if gap_s is None else gap_s
        self.clock, self.sleep = clock, sleep
        self.paused_until = 0.0
        self.last_start = float("-inf")

    async def _wait_turn(self):
        while True:
            now = self.clock()
            target = max(self.paused_until, self.last_start + self.gap_s)
            if target <= now:
                self.last_start = now
                return
            await self.sleep(target - now)

    async def call(self, make):
        for attempt in range(1, RETRY_TRIES + 1):
            async with self.semaphore:
                await self._wait_turn()
                try:
                    return await make()
                except anthropic.APIStatusError as exc:
                    if exc.status_code not in RETRY_STATUS or attempt == RETRY_TRIES:
                        raise
                    self.paused_until = max(self.paused_until, self.clock() + retry_after(exc, attempt))


_gate = None
_gate_loop = None


def gate():
    """The one Gate of the running event loop."""
    global _gate, _gate_loop
    loop = asyncio.get_running_loop()
    if _gate is None or _gate_loop is not loop:
        _gate, _gate_loop = Gate(), loop
    return _gate


# ---------- Holdings ----------

def market_of(contract):
    """Our market name for an IB contract ("US" or "ASX"), None for markets the pipeline has no source for."""
    from yahoo import US_EXCHANGES  # here: yahoo pulls in yfinance
    exchange = contract.primaryExchange or contract.exchange
    if exchange == "ASX":
        return "ASX"
    return "US" if exchange in US_EXCHANGES else None


def refresh_holdings(conn, items):
    """Marks the companies behind IB's portfolio items as held (following merged companies), adding any the graph doesn't have.
    Returns {held, added}. Only called with a live portfolio: when IB is down the last known holdings stay."""
    held, added = set(), 0
    for item in items:
        contract = item.contract
        if getattr(contract, "secType", "STK") != "STK" or not getattr(item, "position", 1):
            continue
        market = market_of(contract)
        if market is None or not contract.symbol:
            continue
        company_id = graph.find_company(conn, "ticker", contract.symbol, market)
        if company_id is None:
            company_id = graph.add_company(conn, getattr(contract, "longName", None) or contract.symbol)
            graph.add_identifier(conn, company_id, "ticker", contract.symbol, market, source="holding")
            added += 1
        held.add(company_id)
    conn.execute("UPDATE companies SET held = 0 WHERE held = 1")
    for company_id in held:
        conn.execute("UPDATE companies SET held = 1, updated_at = ? WHERE id = ?", (stamp_now(), company_id))
    return {"held": len(held), "added": added}


HOLDINGS_EVERY_S = 60


async def keep_holdings(path=None, every_s=HOLDINGS_EVERY_S):
    """Background loop: every minute, while IB is connected, mark the companies the user holds."""
    from supply_chain import db
    conn = db.open_graph(path)
    try:
        while True:
            try:
                from ib_core import ib  # here: the app's one IB connection
                if ib.isConnected():
                    refresh_holdings(conn, ib.portfolio())
            except Exception as exc:  # no IB, or a hiccup: the last known holdings stay
                print(f"Pipeline holdings not refreshed: {exc.__class__.__name__}")
            await asyncio.sleep(every_s)
    finally:
        conn.close()
