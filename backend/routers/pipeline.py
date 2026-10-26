"""The supply chain pipeline's status and switches (#122): the pipeline sheet and its Settings group.

Reads come straight from the jobs, runs, documents and relationships tables (supply_chain/status.py). The switches (run,
pause, monthly budget) are kept by supply_chain/control.py; the workers notice a change within a few seconds.
"""
from contextlib import contextmanager
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import config
import web
from supply_chain import control, db, status

router = APIRouter()


@contextmanager
def graph_db():
    conn = db.open_graph()
    try:
        yield conn
    finally:
        conn.close()


def settings_answer():
    saved = control.load_settings()
    return {**saved, "budget_default": control.DEFAULT_BUDGET_USD, "max_budget": control.MAX_BUDGET_USD,
            "uses_anthropic_key": True, "sec_contact_email": bool(config.sec_contact_email())}


@router.get("/pipeline")
def pipeline_overview():
    """Status, tiles and costs for the pipeline sheet and the Settings row."""
    with graph_db() as conn:
        return {**status.overview(conn), "settings": settings_answer()}


@router.get("/pipeline/companies")
def pipeline_companies():
    """The watched companies with their latest filing, when it was read, links, status and cost."""
    with graph_db() as conn:
        return {"companies": status.company_rows(conn)}


@router.get("/pipeline/companies/{company_id}/filings")
def pipeline_company_filings(company_id: int):
    with graph_db() as conn:
        return {"company_id": company_id, "filings": status.company_filings(conn, company_id)}


@router.get("/pipeline/log")
def pipeline_log(kind: Literal["all", "links", "failed"] = "all", limit: int = status.LOG_LIMIT):
    """The newest events first: RUN, LINK, DONE, FAIL, SCOUT."""
    with graph_db() as conn:
        return {"events": status.log_events(conn, kind=kind, limit=max(1, min(limit, 500)))}


class SettingsChange(BaseModel):
    enabled: Optional[bool] = None
    paused: Optional[bool] = None
    budget_usd: Optional[float] = None


@router.post("/pipeline/settings")
def change_settings(change: SettingsChange, request: Request):
    web.check_origin(request)
    try:
        control.save_settings(enabled=change.enabled, paused=change.paused, budget_usd=change.budget_usd)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return settings_answer()


@router.post("/pipeline/run-now")
def run_now(request: Request):
    """Looks at every watched company now and resumes a pause. Needs the pipeline switched on."""
    web.check_origin(request)
    if not control.load_settings()["enabled"]:
        raise HTTPException(status_code=409, detail="Turn on Run pipeline in Settings first.")
    with graph_db() as conn:
        return status.run_now(conn)


class Retry(BaseModel):
    job_id: Optional[int] = None
    company_id: Optional[int] = None


@router.post("/pipeline/retry")
def retry(body: Retry, request: Request):
    web.check_origin(request)
    try:
        with graph_db() as conn:
            return {"requeued": status.retry(conn, job_id=body.job_id, company_id=body.company_id)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
