"""What the pipeline sheet shows (#122): figures, companies and the live log, read from the jobs, runs, documents and
relationships tables. Nothing is stored for this; every number is a query, so it is always what the database says.

A watched company is one in a theme (theme_companies). Its status:
- failed:      a job for it (or one of its filings) failed for good (failed / dead)
- reading:     a job for it is running now
- waiting:     jobs are queued for it (a retry after an error counts), or it hasn't been looked at yet
- up to date:  every job is done and its newest filing has been downloaded
- not on EDGAR: scouted, but SEC has no filings for it (a company with no US listing)
"""
import json
from datetime import datetime, timedelta, timezone

from supply_chain import control, jobs, orchestrator, verifier

WEEK = timedelta(days=7)
LOG_LIMIT = 150
LINK_LIMIT = 80
VERBS = {"scout": "scout", "download": "fetch", "xbrl": "read"}


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now(now=None):
    return now or datetime.now(timezone.utc)


def _notes(raw):
    if not raw:
        return ""
    try:
        value = json.loads(raw)
    except ValueError:
        return str(raw)
    return value if isinstance(value, str) else json.dumps(value)


def ticker_and_market(conn, company_id):
    row = conn.execute("""SELECT value, market FROM identifiers WHERE company_id = ? AND scheme = 'ticker'
                          ORDER BY (market = 'US') DESC, id LIMIT 1""", (company_id,)).fetchone()
    return (row["value"], row["market"]) if row else (None, None)


def ticker_of(conn, company_id):
    return ticker_and_market(conn, company_id)[0]


def short_name(name):
    """"Customer A (unnamed customer of NVIDIA Corporation, year to 2026-01-25)" -> "Customer A (NVIDIA, FY 2026)"."""
    if " (unnamed " not in name:
        return name
    label, rest = name.split(" (unnamed ", 1)
    owner = rest.split(" of ", 1)[-1].split(", year to", 1)[0]
    year = rest.rsplit("year to ", 1)[-1].rstrip(")")[:4]
    return f"{label} ({owner}, FY{year})"


def filing_label(row):
    """"10-K 2026", "10-Q Jun 2026", "8-K 21 Oct": what the filing is, in few characters."""
    form, filed, period = row["kind"], row["filed_at"] or "", row["period_end"] or ""
    try:
        if form in ("10-K", "20-F"):
            return f"{form} {(period or filed)[:4]}"
        if form == "10-Q" and period:
            return f"{form} {datetime.strptime(period[:10], '%Y-%m-%d').strftime('%b %Y')}"
        if filed:
            return f"{form} {datetime.strptime(filed[:10], '%Y-%m-%d').strftime('%-d %b')}"
    except ValueError:
        pass
    return form


def watched_ids(conn):
    """The theme companies and the ones the user holds (orchestrator.py)."""
    return [r["id"] for r in conn.execute(
        """SELECT id FROM companies WHERE merged_into IS NULL
             AND (held = 1 OR EXISTS (SELECT 1 FROM theme_companies tc WHERE tc.company_id = companies.id)) ORDER BY id""")]


def asx_only_ids(conn):
    """Companies listed only on the ASX: nothing reads them until there is an ASX source (#131)."""
    return {r["company_id"] for r in conn.execute(
        """SELECT DISTINCT company_id FROM identifiers WHERE scheme = 'ticker' AND market = 'ASX'
           AND company_id NOT IN (SELECT company_id FROM identifiers WHERE scheme = 'ticker' AND market = 'US')""")}


def theme_names(conn):
    return [r["name"] for r in conn.execute("SELECT name FROM themes ORDER BY id")]


# ---------- Companies ----------

def company_rows(conn, now=None):
    now = _now(now)
    week_ago = _iso(now - WEEK)
    month = _iso(control.month_start(now))
    ids = watched_ids(conn)
    job_rows = conn.execute("SELECT company_id, status, kind, attempts, last_error, finished_at FROM jobs WHERE company_id IS NOT NULL").fetchall()
    by_company = {}
    for row in job_rows:
        by_company.setdefault(row["company_id"], []).append(row)
    latest = {r["company_id"]: r for r in conn.execute(
        """SELECT d.* FROM documents d WHERE d.company_id IS NOT NULL AND d.filed_at = (
               SELECT MAX(filed_at) FROM documents WHERE company_id = d.company_id AND source = 'sec') AND d.source = 'sec'
           GROUP BY d.company_id""")}
    links = {r["company_id"]: r for r in conn.execute(
        """SELECT cid AS company_id, COUNT(*) AS total, SUM(created_at >= ?) AS week FROM (
               SELECT supplier_id AS cid, created_at FROM relationships WHERE status != 'ended' AND merged_into IS NULL
               UNION ALL SELECT customer_id, created_at FROM relationships WHERE status != 'ended' AND merged_into IS NULL) GROUP BY cid""", (week_ago,))}
    costs = {r["company_id"]: r["cost"] for r in conn.execute(
        """SELECT j.company_id, SUM(r.cost_usd) AS cost FROM runs r JOIN jobs j ON j.id = r.job_id
           WHERE j.company_id IS NOT NULL AND r.started_at >= ? GROUP BY j.company_id""", (month,))}
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM companies")}
    asx_only = asx_only_ids(conn)
    held = {r["id"] for r in conn.execute("SELECT id FROM companies WHERE held = 1")}
    scouted_empty = {r["company_id"] for r in conn.execute(
        """SELECT j.company_id FROM jobs j JOIN runs r ON r.job_id = j.id WHERE j.kind = 'scout' AND j.status = 'done' AND r.notes LIKE '%no SEC listing%'""")}
    document_count = {r["company_id"]: r["n"] for r in conn.execute(
        "SELECT company_id, COUNT(*) AS n FROM documents WHERE source = 'sec' GROUP BY company_id")}
    rows = []
    for company_id in ids:
        company_jobs = by_company.get(company_id, [])
        statuses = {j["status"] for j in company_jobs}
        retrying = any(j["status"] == "queued" and j["attempts"] and j["last_error"] for j in company_jobs)
        doc = latest.get(company_id)
        finished = [j["finished_at"] for j in company_jobs if j["finished_at"]]
        if statuses & {"failed", "dead"}:
            status = "failed"
        elif company_id in asx_only and not document_count.get(company_id):
            status = "waiting for ASX source"
        elif "running" in statuses:
            status = "reading"
        elif "queued" in statuses or not company_jobs:
            status = "waiting"
        elif company_id in asx_only:
            status = "waiting for ASX source"
        elif company_id in scouted_empty and not document_count.get(company_id):
            status = "not on EDGAR"
        else:
            status = "up to date"
        link = links.get(company_id)
        symbol, market = ticker_and_market(conn, company_id)
        rows.append({
            "company_id": company_id, "symbol": symbol or "", "market": market or "", "name": names.get(company_id, ""),
            "latest_filing": filing_label(doc) if doc else None, "latest_filed": doc["filed_at"] if doc else None,
            "read_at": max(finished) if finished else None,
            "links": link["total"] if link else 0, "links_week": int(link["week"] or 0) if link else 0,
            "status": status, "retrying": retrying, "cost_usd": round(costs.get(company_id) or 0, 4), "held": company_id in held,
            "filings": document_count.get(company_id, 0),
        })
    rows.sort(key=lambda r: (r["read_at"] or ""), reverse=True)
    return rows


def company_filings(conn, company_id):
    """One company's filings with where each stands, newest first."""
    rows = conn.execute(
        """SELECT d.id, d.kind, d.filed_at, d.period_end, d.status, d.url,
                  (SELECT j.id FROM jobs j WHERE j.document_id = d.id AND j.kind = 'download' ORDER BY j.id DESC LIMIT 1) AS job_id,
                  (SELECT j.status FROM jobs j WHERE j.document_id = d.id AND j.kind = 'download' ORDER BY j.id DESC LIMIT 1) AS job_status,
                  (SELECT j.last_error FROM jobs j WHERE j.document_id = d.id AND j.kind = 'download' ORDER BY j.id DESC LIMIT 1) AS error
           FROM documents d WHERE d.company_id = ? AND d.source = 'sec' ORDER BY d.filed_at DESC, d.id DESC""", (company_id,)).fetchall()
    return [{**dict(r), "label": filing_label(r)} for r in rows]


# ---------- Figures ----------

def overview(conn, now=None):
    now = _now(now)
    settings = control.load_settings()
    rows = company_rows(conn, now)
    counts = {key: sum(1 for r in rows if r["status"] == key)
              for key in ("reading", "waiting", "failed", "up to date", "not on EDGAR", "waiting for ASX source")}
    read = sum(1 for r in rows if r["status"] == "up to date" and r["latest_filing"])
    week_ago = _iso(now - WEEK)
    link_total, link_week, link_ended = conn.execute(
        """SELECT SUM(status != 'ended'), SUM(status != 'ended' AND created_at >= ?), SUM(status = 'ended') FROM relationships
           WHERE merged_into IS NULL""", (week_ago,)).fetchone()  # found this week (first_seen is the statement's date)
    stuck = conn.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('failed', 'dead')").fetchone()[0]
    unchecked = verifier.unchecked_count(conn)  # links Claude couldn't check (verifier.MAX_VERIFY_ATTEMPTS)
    # work put off by the daily pace (orchestrator.py), and jobs no month's budget could ever take: they need a bigger budget
    waiting = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued' AND last_error LIKE 'waiting for %'").fetchone()[0]
    oversized = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued' AND last_error LIKE 'too big for the budget%'").fetchone()[0]
    pace = orchestrator.pace(conn, now, settings)
    stages = {kind: round(cost or 0, 4) for kind, cost in conn.execute(
        """SELECT j.kind, SUM(r.cost_usd) FROM runs r JOIN jobs j ON j.id = r.job_id WHERE r.started_at >= ? AND j.kind IN ('read', 'verify')
           GROUP BY j.kind""", (_iso(control.month_start(now)),))}
    stages = {"read": stages.get("read", 0.0), "verify": stages.get("verify", 0.0)}
    retrying = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued' AND attempts > 0 AND last_error IS NOT NULL").fetchone()[0]
    month = control.spent_this_month(conn, now)
    week = jobs.spent_since(conn, now - WEEK)
    per_filing = conn.execute(
        "SELECT AVG(cost_usd) FROM runs WHERE cost_usd > 0 AND started_at >= ?", (_iso(control.month_start(now)),)).fetchone()[0]
    budget = settings["budget_usd"]
    job_counts = jobs.counts(conn)
    return {
        "status": control.status_word(conn, settings, now),
        "enabled": settings["enabled"], "paused": settings["paused"], "workers": control.active_workers,
        "account_problem": {k: settings["account_problem"][k] for k in ("kind", "message", "since", "checked_at")} if settings["account_problem"] else None,
        "themes": theme_names(conn), "watched": len(rows),
        "coverage": {"read": read, "total": len(rows), "not_on_edgar": counts["not on EDGAR"], "waiting_for_asx": counts["waiting for ASX source"]},
        "links": {"total": link_total or 0, "week": link_week or 0, "ended": link_ended or 0},
        "attention": {"stuck": stuck, "retrying": retrying, "unchecked": unchecked, "oversized": oversized,
                      "total": stuck + retrying + unchecked + oversized},
        "cost": {"month": round(month, 4), "week": round(week, 4), "per_filing": round(per_filing, 4) if per_filing else None,
                 "budget": budget, "budget_left": round(max(budget - month, 0), 4), "percent": round(100 * month / budget) if budget else 0,
                 "today": round(pace["spent_today"], 4), "today_cap": round(pace["cap"] + pace["extra"], 4), "run_now_extra": round(pace["extra"], 4),
                 "waiting_for_tomorrow": waiting, "by_stage": stages},
        "companies": {"all": len(rows), **{key.replace(" ", "_"): value for key, value in counts.items()}},
        "jobs": job_counts,
        "started": bool(conn.execute("SELECT 1 FROM jobs LIMIT 1").fetchone()),
    }


# ---------- Live log ----------

def _event_text(row, symbol):
    payload = {}
    try:
        payload = json.loads(row["payload"] or "{}")
    except ValueError:
        pass
    verb = VERBS.get(row["kind"], row["kind"])
    what = payload.get("form") or ("10-K" if row["kind"] == "xbrl" else "")
    if row["kind"] == "xbrl":
        what = (payload.get("filing") or {}).get("form", "10-K")
    return f"{verb} {symbol or row['company_name'] or ''} {what}".replace("  ", " ").strip()


def log_events(conn, now=None, kind="all", limit=LOG_LIMIT):
    """Newest first: {at, tag (RUN, LINK, DONE, FAIL, SCOUT), text, job_id (a FAIL line's job, for Retry), company_id}."""
    events = []
    if kind in ("all", "failed"):
        rows = conn.execute(
            """SELECT r.id, r.started_at, r.finished_at, r.outcome, r.error, r.notes, r.cost_usd, j.id AS job_id, j.kind, j.payload, j.status AS job_status,
                      j.run_after, j.company_id, c.name AS company_name
               FROM runs r JOIN jobs j ON j.id = r.job_id LEFT JOIN companies c ON c.id = j.company_id
               ORDER BY COALESCE(r.finished_at, r.started_at) DESC, r.id DESC LIMIT ?""", (limit * 2,)).fetchall()
        for row in rows:
            symbol = ticker_of(conn, row["company_id"]) if row["company_id"] else None
            text = _event_text(row, symbol)
            at = row["finished_at"] or row["started_at"]
            if row["outcome"] == "running":
                event = ("RUN", text)
            elif row["outcome"] == "ok":
                note = _notes(row["notes"])
                cost = f" · US${row['cost_usd']:.2f}" if row["cost_usd"] else ""
                event = ("SCOUT" if row["kind"] == "scout" else "DONE", f"{text} · {note}{cost}" if note else f"{text}{cost}")
            else:
                retry = ""
                if row["outcome"] == "retry" and row["run_after"]:
                    retry = f" · retry {row['run_after'][11:16]} UTC"
                error = (row["error"] or "stopped").splitlines()[0][:90]
                event = ("FAIL", f"{text} · {error}{retry}")
            if kind == "failed" and event[0] != "FAIL":
                continue
            events.append({"at": at, "tag": event[0], "text": event[1], "job_id": row["job_id"] if event[0] == "FAIL" and row["job_status"] != "done" else None,
                           "company_id": row["company_id"]})
    if kind in ("all", "links"):
        rows = conn.execute(
            """SELECT r.created_at, r.supplier_revenue_share AS rev, r.customer_supply_share AS supply, r.customer_share_scope AS scope,
                      s.id AS supplier_id, s.name AS supplier, c.id AS customer_id, c.name AS customer, r.tier, r.kind,
                      e.verification
               FROM relationships r JOIN companies s ON s.id = r.supplier_id JOIN companies c ON c.id = r.customer_id
               JOIN evidence e ON e.id = r.primary_evidence_id WHERE r.merged_into IS NULL
               ORDER BY r.created_at DESC, r.id DESC LIMIT ?""", (LINK_LIMIT,)).fetchall()
        for row in rows:
            supplier = ticker_of(conn, row["supplier_id"]) or short_name(row["supplier"])
            customer = ticker_of(conn, row["customer_id"]) or short_name(row["customer"])
            share = f" · {row['rev']:g}% of revenue" if row["rev"] is not None else (
                f" · {row['supply']:g}% of {row['scope'] or 'purchases'}" if row["supply"] is not None else "")
            arrow = "↔" if row["kind"] == "partnership" else "→"  # a partnership has no direction
            checked = " · verified" if row["verification"] == "verified" else ""
            events.append({"at": row["created_at"], "tag": "LINK", "text": f"{supplier} {arrow} {customer}{share}{checked}", "job_id": None,
                           "company_id": row["supplier_id"]})
    events.sort(key=lambda e: e["at"], reverse=True)
    return events[:limit]


# ---------- Actions ----------

def retry(conn, job_id=None, company_id=None):
    """Queues failed (or dead) jobs again, one or all of a company's; a company's unchecked candidates get fresh attempts
    too. Returns how many."""
    if job_id is not None:
        rows = conn.execute("SELECT id FROM jobs WHERE id = ? AND status IN ('failed', 'dead')", (job_id,)).fetchall()
    elif company_id is not None:
        rows = conn.execute("SELECT id FROM jobs WHERE company_id = ? AND status IN ('failed', 'dead')", (company_id,)).fetchall()
    else:
        raise ValueError("Say which job or company to retry.")
    for row in rows:
        jobs.requeue(conn, row["id"])
    unchecked = verifier.retry_unchecked(conn, company_id) if company_id is not None else 0
    return len(rows) + unchecked


def run_now(conn, now=None):
    """Looks at every watched company again now, not waiting for the twelve hours between checks, resumes a pause, and adds
    one more day's cap to today's allowance (orchestrator.add_run_now; the monthly budget stays the limit).
    Returns {queued, added_usd}."""
    added = orchestrator.add_run_now(conn, now)
    queued = 0
    for company_id in watched_ids(conn):
        _, created = jobs.enqueue(conn, "scout", str(company_id), priority=70, company_id=company_id, now=now)
        queued += 1 if created else 0
    control.save_settings(paused=False)
    return {"queued": queued, "added_usd": added}
