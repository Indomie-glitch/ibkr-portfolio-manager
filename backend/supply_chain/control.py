"""Pipeline switches (#122): whether it runs, whether it is paused, the monthly budget, and the state the workers are in.

The Settings group and the pipeline sheet change these through routers/pipeline.py. They are kept in a small JSON file
next to the database (pipeline_settings.json, like trading_settings.json for borrowing) so they work the same in
development and in the Mac app and survive restarts. Before anyone has chosen, "run" follows config.pipeline_enabled()
(PIPELINE in .env, or the app's setting).

The supervisor in worker.keep_running asks should_run() every few seconds: workers run while the pipeline is on, not
paused, and this month's spending (the cost of runs, #116) is under the budget; they stop (the job in hand goes back in the queue)
when any of that changes, and start again by themselves, e.g. on the first of next month.
"""
import calendar
import json
from datetime import date, datetime, time, timedelta, timezone

import config
from supply_chain import db, jobs

# The clock for "today" and "this month": the computer's local time, like usage_store's monthly totals, so the daily
# pace (orchestrator.py) and the monthly budget turn over at the same moment (midnight where the user is). Tests set a zone.
clock_zone = None

DEFAULT_BUDGET_USD = 10.0
MAX_BUDGET_USD = 1000.0
SETTINGS_NAME = "pipeline_settings.json"

# Set by worker.keep_running: how many workers are running right now
active_workers = 0


def settings_path():
    return db.DB_PATH.parent / SETTINGS_NAME


def load_settings():
    try:
        saved = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    budget = saved.get("budget_usd")
    return {
        "enabled": saved["enabled"] if isinstance(saved.get("enabled"), bool) else config.pipeline_enabled(),
        "paused": saved.get("paused") is True,
        "budget_usd": float(budget) if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0 else DEFAULT_BUDGET_USD,
        "run_now": saved.get("run_now") if isinstance(saved.get("run_now"), dict) else {},
    }


def save_settings(enabled=None, paused=None, budget_usd=None, run_now=None):
    """Changes what's given; returns the settings now. ValueError for a budget that isn't a sensible amount.
    run_now: {"day": "2026-10-27", "usd": 0.66}, what Run now has added to that day's allowance (orchestrator.py)."""
    if budget_usd is not None:
        if isinstance(budget_usd, bool) or not isinstance(budget_usd, (int, float)) or not 0 < budget_usd <= MAX_BUDGET_USD:
            raise ValueError(f"The budget must be more than 0 and at most US${MAX_BUDGET_USD:,.0f}.")
    current = load_settings()
    current.update({k: v for k, v in (("enabled", enabled), ("paused", paused), ("budget_usd", budget_usd), ("run_now", run_now)) if v is not None})
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(current), encoding="utf-8")
    partial.replace(path)
    return load_settings()


def local(now=None):
    """The moment in the pipeline's clock (local time unless a test set clock_zone)."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(clock_zone) if clock_zone else now.astimezone()


def _midnight(day):
    """Midnight starting `day` (a date) in the pipeline's clock, as an aware datetime."""
    naive = datetime.combine(day, time())
    return naive.replace(tzinfo=clock_zone) if clock_zone else naive.astimezone()


def today(now=None):
    return local(now).date()


def day_start(now=None):
    """When today began, in the pipeline's clock."""
    return _midnight(today(now))


def next_day_start(now=None):
    return _midnight(today(now) + timedelta(days=1))


def month_start(now=None):
    """When this month began, in the pipeline's clock: the monthly budget starts over then, at local midnight."""
    return _midnight(today(now).replace(day=1))


def next_month_start(now=None):
    day = today(now)
    return _midnight(date(day.year + day.month // 12, day.month % 12 + 1, 1))


def days_left_in_month(now=None):
    """Days from today to the end of the month, counting today (1 on the last day)."""
    day = today(now)
    return calendar.monthrange(day.year, day.month)[1] - day.day + 1


def spent_this_month(conn, now=None):
    return jobs.spent_since(conn, month_start(now))


def budget_used_up(conn, settings=None, now=None):
    settings = settings or load_settings()
    return spent_this_month(conn, now) >= settings["budget_usd"]


def should_run(conn, settings=None, now=None):
    settings = settings or load_settings()
    return settings["enabled"] and not settings["paused"] and not budget_used_up(conn, settings, now)


def status_word(conn, settings=None, now=None):
    """off / paused / budget (used up) / running / starting (on, workers about to start)."""
    settings = settings or load_settings()
    if not settings["enabled"]:
        return "off"
    if settings["paused"]:
        return "paused"
    if budget_used_up(conn, settings, now):
        return "budget"
    return "running" if active_workers else "starting"
