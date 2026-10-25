"""SEC Scout (#118): watches the theme companies for new 10-K, 10-Q and 8-K filings (20-F and 6-K for foreign companies) and queues them.

Two kinds of job, run by the worker (worker.py):
- "scout" (key = company id): looks the company up on EDGAR (CIK from a stored identifier, else SEC's ticker list for US
  tickers, then stored), lists its recent filings, registers each new one as a document and queues a "download" job.
- "download" (key = the document's external id): fetches the filing's main document and records its hash.

schedule() queues a scout job for every theme company not scouted within SCOUT_EVERY_S; keep_scheduling() calls it
every hour while the pipeline runs. Asking again is safe: documents are unique per accession number + file, and the queue
holds one open job per kind and key.

Forms watched: 10-K, 10-Q, 8-K, and for foreign private issuers (TSMC, ASML ...) the 20-F annual report and 6-K
reports. 8-Ks and 6-Ks are mostly press releases, so they only go back 60 days on the first look; annual reports go back
13 months. Companies with no US ticker (so no EDGAR number) produce nothing.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import sec_client
from supply_chain import db, graph, jobs, sec
from supply_chain.worker import Permanent, handler

FORMS = {"10-K": 60, "20-F": 60, "10-Q": 50, "8-K": 30, "6-K": 30}  # form -> download priority (higher runs first)
LOOKBACK_DAYS = {"10-K": 400, "20-F": 400, "10-Q": 200, "8-K": 60, "6-K": 60}
SCOUT_EVERY_S = 12 * 3600
SCHEDULE_EVERY_S = 3600
SCOUT_PRIORITY = 70
XBRL_PRIORITY = 55  # the tagged customer figures in a 10-K (#120)


def cik_of(conn, company_id):
    row = conn.execute("SELECT value FROM identifiers WHERE company_id = ? AND scheme = 'cik' ORDER BY id LIMIT 1", (company_id,)).fetchone()
    return int(row["value"]) if row else None


def us_ticker(conn, company_id):
    row = conn.execute("SELECT value FROM identifiers WHERE company_id = ? AND scheme = 'ticker' AND market = 'US' ORDER BY id LIMIT 1", (company_id,)).fetchone()
    return row["value"] if row else None


async def resolve_cik(conn, company_id):
    """The company's CIK: stored, else found from its US ticker and stored. None when it has no US ticker or SEC has none."""
    cik = cik_of(conn, company_id)
    if cik:
        return cik
    ticker = us_ticker(conn, company_id)
    cik = await sec_client.cik_for_ticker(ticker) if ticker else None
    if cik:
        try:
            graph.add_identifier(conn, company_id, "cik", str(cik), source="sec")
        except graph.IdentifierConflict:
            return None  # another company already has this CIK: a mistake in the data to look at, not to guess around
    return cik


def lookback_since(form, today):
    return today - timedelta(days=LOOKBACK_DAYS[form])


async def scan(conn, company_id, today=None):
    """Registers the company's filings of the watched forms that we haven't seen and queues their downloads.
    Returns {"cik", "found", "new"} (cik None when it can't be looked up)."""
    cik = await resolve_cik(conn, company_id)
    if cik is None:
        return {"cik": None, "found": 0, "new": 0}
    today = today or datetime.now(timezone.utc).date()
    earliest = min(lookback_since(form, today) for form in FORMS)
    found = new = 0
    for filing in await sec_client.list_filings(cik, forms=tuple(FORMS), since=earliest):
        if _day(filing["filed"]) < lookback_since(filing["form"], today) or not filing.get("primary_document"):
            continue
        found += 1
        key = sec.external_id(filing["accession"], filing["primary_document"])
        existing = conn.execute("SELECT id, status FROM documents WHERE source = ? AND external_id = ?", (sec.SOURCE, key)).fetchone()
        if existing:
            document_id = existing["id"]
            # seen before: only picked up again if its download job was never queued (the app stopped in between)
            if existing["status"] != "discovered" or conn.execute("SELECT 1 FROM jobs WHERE kind = 'download' AND key = ?", (key,)).fetchone():
                continue
        else:
            document_id = sec.register_filing(conn, company_id, cik, filing)
            new += 1
        jobs.enqueue(conn, "download", key,
                     {"document_id": document_id, "cik": cik, "accession": filing["accession"], "filename": filing["primary_document"],
                      "form": filing["form"]},
                     priority=FORMS[filing["form"]], company_id=company_id, document_id=document_id)
        if filing["form"] == "10-K" and filing.get("xbrl"):
            jobs.enqueue(conn, "xbrl", filing["accession"], {"cik": cik, "filing": filing}, priority=XBRL_PRIORITY,
                         company_id=company_id, document_id=document_id)
    return {"cik": cik, "found": found, "new": new}


def _day(text):
    return datetime.strptime(text[:10], "%Y-%m-%d").date()


@handler("scout")
async def scout_job(job, conn):
    company_id = int(job["key"])
    try:
        result = await scan(conn, company_id)
    except sec_client.SecNotFound as exc:
        raise Permanent(str(exc)) from exc
    if result["cik"] is None:
        return {"notes": "no SEC listing (no US ticker, or SEC doesn't know it)"}
    return {"notes": f"{result['found']} filings seen, {result['new']} new"}


@handler("download")
async def download_job(job, conn):
    p = job["payload"]
    try:
        digest = await sec.fetch_document(conn, p["document_id"], p["cik"], p["accession"], p["filename"])
    except sec_client.SecNotFound as exc:
        conn.execute("UPDATE documents SET status = 'failed' WHERE id = ?", (p["document_id"],))
        raise Permanent(str(exc)) from exc
    return {"notes": f"{p.get('form', '')} {digest[:12]}"}


def due_companies(conn, now=None, every_s=SCOUT_EVERY_S):
    """Theme companies that no scout job has covered within `every_s` (or has open)."""
    cutoff = jobs._iso((now or datetime.now(timezone.utc)) - timedelta(seconds=every_s))
    rows = conn.execute(
        """SELECT DISTINCT c.id FROM theme_companies tc JOIN companies c ON c.id = tc.company_id
           WHERE NOT EXISTS (SELECT 1 FROM jobs j WHERE j.kind = 'scout' AND j.key = CAST(c.id AS TEXT)
                             AND (j.status IN ('queued', 'running') OR j.created_at > ?))
           ORDER BY c.id""", (cutoff,)).fetchall()
    return [row["id"] for row in rows]


def schedule(conn, now=None, every_s=SCOUT_EVERY_S):
    """Queues a scout job for each due company; returns how many."""
    due = due_companies(conn, now, every_s)
    for company_id in due:
        jobs.enqueue(conn, "scout", str(company_id), priority=SCOUT_PRIORITY, company_id=company_id, now=now)
    return len(due)


async def keep_scheduling(path=None):
    """Background loop: queue scout jobs for the due companies every hour."""
    conn = db.open_graph(path)
    try:
        while True:
            try:
                queued = schedule(conn)
                if queued:
                    print(f"SEC scout: queued {queued} compan{'y' if queued == 1 else 'ies'}")
            except Exception as exc:  # a failed pass is tried again next hour
                print(f"SEC scout scheduling failed: {exc.__class__.__name__}")
            await asyncio.sleep(SCHEDULE_EVERY_S)
    finally:
        conn.close()
