"""SEC Scout (#118): watches the theme companies for new 10-K, 10-Q and 8-K filings (20-F and 6-K for foreign companies) and queues them.

Two kinds of job, run by the worker (worker.py):
- "scout" (key = company id): looks the company up on EDGAR (CIK from a stored identifier, else SEC's ticker list for US
  tickers, then stored), lists its recent filings, registers each new one as a document and queues a "download" job.
- "download" (key = the document's external id): fetches the filing's main document, records its hash and queues the
  Reader (reader.py, #124) for the forms worth reading.

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
from supply_chain import db, exhibits, graph, jobs, merge, reader, sec, verifier
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
        else:
            document_id = sec.register_filing(conn, company_id, cik, filing)
            new += 1
        # A filing seen before is only downloaded again if its download job was never queued (the app stopped in between)
        if not existing or (existing["status"] == "discovered" and not conn.execute("SELECT 1 FROM jobs WHERE kind = 'download' AND key = ?", (key,)).fetchone()):
            jobs.enqueue(conn, "download", key,
                         {"document_id": document_id, "cik": cik, "accession": filing["accession"], "filename": filing["primary_document"],
                          "form": filing["form"], "items": filing.get("items") or []},
                         priority=FORMS[filing["form"]], company_id=company_id, document_id=document_id)
        # The customer figures of a 10-K with XBRL data, once per filing (also for ones registered before this existed)
        if filing["form"] == "10-K" and filing.get("xbrl") and not conn.execute("SELECT 1 FROM jobs WHERE kind = 'xbrl' AND key = ?", (filing["accession"],)).fetchone():
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
    if p.get("form") == "8-K" and exhibits.has_agreement(p.get("items")):  # the agreement itself first (#322); that job queues the read
        exhibits.queue_exhibits(conn, p["document_id"], {k: p[k] for k in ("cik", "accession", "filename", "items") if k in p}, job.get("company_id"))
        return {"notes": f"{p.get('form', '')} {digest[:12]}; exhibits next"}
    # Jobs queued before #124 have no items: an 8-K among them is read only if the chunker finds Item 1.01 / 1.02
    reader.queue_read(conn, p["document_id"], p.get("form"), p.get("items") if "items" in p else None, job.get("company_id"))
    return {"notes": f"{p.get('form', '')} {digest[:12]}"}


def due_companies(conn, now=None, every_s=SCOUT_EVERY_S):
    """Watched companies (theme or held) that no scout job has covered within `every_s` (or has open)."""
    cutoff = jobs._iso((now or datetime.now(timezone.utc)) - timedelta(seconds=every_s))
    # theme companies and the ones the user holds (orchestrator.py); a company listed only on the ASX waits for an ASX source (#131)
    rows = conn.execute(
        """SELECT c.id FROM companies c
           WHERE (c.held = 1 OR EXISTS (SELECT 1 FROM theme_companies tc WHERE tc.company_id = c.id)) AND c.merged_into IS NULL
             AND NOT (EXISTS (SELECT 1 FROM identifiers i WHERE i.company_id = c.id AND i.scheme = 'ticker' AND i.market = 'ASX')
                      AND NOT EXISTS (SELECT 1 FROM identifiers i WHERE i.company_id = c.id AND i.scheme = 'ticker' AND i.market = 'US'))
             AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.kind = 'scout' AND j.key = CAST(c.id AS TEXT)
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
                backfill = exhibits.queue_backfill(conn)  # 8-Ks downloaded before their exhibits were fetched (#322)
                if backfill:
                    print(f"8-K exhibits: queued {backfill} filing{'' if backfill == 1 else 's'}")
                reads = reader.queue_unread(conn)  # filings downloaded before the Reader existed
                if reads:
                    print(f"Reader: queued {reads} downloaded filing{'' if reads == 1 else 's'}")
                merge.schedule(conn)  # once a day: stale links, placeholder upgrades, confidence (#127)
                checks = verifier.queue_unverified(conn)  # candidates whose check was never queued
                if checks:
                    print(f"Verifier: queued {checks} document{'' if checks == 1 else 's'}")
            except Exception as exc:  # a failed pass is tried again next hour
                print(f"SEC scout scheduling failed: {exc.__class__.__name__}")
            await asyncio.sleep(SCHEDULE_EVERY_S)
    finally:
        conn.close()
