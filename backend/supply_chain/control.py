"""Pipeline switches (#122): whether it runs, whether it is paused, the monthly budget, and the state the workers are in.

The Settings group and the pipeline sheet change these through routers/pipeline.py. They are kept in a small JSON file
next to the database (pipeline_settings.json, like trading_settings.json for borrowing) so they work the same in
development and in the Mac app and survive restarts. Before anyone has chosen, "run" follows config.pipeline_enabled()
(PIPELINE in .env, or the app's setting).

The supervisor in worker.keep_running asks should_run() every few seconds: workers run while the pipeline is on, not
paused, and this month's spending (the cost of runs, #116) is under the budget; they stop (the job in hand goes back in the queue)
when any of that changes, and start again by themselves, e.g. on the first of next month.
"""
import json
from datetime import datetime, timezone

import config
from supply_chain import db, jobs

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
    }


def save_settings(enabled=None, paused=None, budget_usd=None):
    """Changes what's given; returns the settings now. ValueError for a budget that isn't a sensible amount."""
    if budget_usd is not None:
        if isinstance(budget_usd, bool) or not isinstance(budget_usd, (int, float)) or not 0 < budget_usd <= MAX_BUDGET_USD:
            raise ValueError(f"The budget must be more than 0 and at most US${MAX_BUDGET_USD:,.0f}.")
    current = load_settings()
    current.update({k: v for k, v in (("enabled", enabled), ("paused", paused), ("budget_usd", budget_usd)) if v is not None})
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_text(json.dumps(current), encoding="utf-8")
    partial.replace(path)
    return load_settings()


def month_start(now=None):
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


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
