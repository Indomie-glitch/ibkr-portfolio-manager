"""Taiwan annual reports from MOPS (#128): finds each Taiwan-listed theme company's English annual report, registers it
as a document, downloads it and queues the Reader.

A company is scouted here when it has a Taiwan ticker (identifiers scheme ticker, market TW: the company code, "2317"
for Hon Hai) and no US listing. One with a US listing (TSMC's ADR, TSM) files a 20-F with SEC, which says the same in
the SEC's layout, so it is read from EDGAR only and never twice.

Documents: source "mops", kind "annual report", external_id = the file name ("2025_2317_20260529FE4.pdf", which holds
the fiscal year, company code and meeting date), filed_at = the upload date, period_end = 31 December of the fiscal
year (Taiwan companies report by calendar year). The scout job (scout.py) calls scan(); the download job (same kind
"download" as SEC filings, payload source "mops") calls fetch_document().

Companies without an English report (smaller ones file only in Chinese) give nothing for now: the Reader's prompt,
quote checks and the name resolver work in English.
"""
from datetime import date, datetime, timedelta, timezone

import mops_client
from supply_chain import graph, jobs
from supply_chain.db import now

SOURCE = mops_client.SOURCE
KIND = "annual report"
MARKET = "TW"
LOOKBACK_DAYS = 400  # like a 10-K: the newest report, and last year's until this year's is out
DOWNLOAD_PRIORITY = 60  # as a 10-K or 20-F


def company_code(conn, company_id):
    """The company's Taiwan code ("2317"), or None."""
    row = conn.execute("SELECT value FROM identifiers WHERE company_id = ? AND scheme = 'ticker' AND market = ? ORDER BY id LIMIT 1",
                       (company_id, MARKET)).fetchone()
    return row["value"] if row else None


def listing_url(report):
    return mops_client.listing_url(report["co_id"], int(report["meeting_date"][:4]))


def register_report(conn, company_id, report):
    """Adds an annual report (a row from mops_client.english_annual_reports) as a document; returns its id."""
    revised = " (revised after the meeting)" if report.get("revised") else ""
    return graph.add_document(
        conn, SOURCE, KIND, report["filename"], listing_url(report), company_id=company_id,
        title=f"Annual report {report['fiscal_year']}{revised}", filed_at=report["uploaded"] or report["meeting_date"],
        period_end=f"{report['fiscal_year']}-12-31", language="en", status="discovered")


async def scan(conn, company_id, today=None):
    """Registers the company's English annual reports uploaded within LOOKBACK_DAYS that we haven't seen and queues their
    downloads. Returns {"code", "found", "new"} (code None when the company has no Taiwan code)."""
    code = company_code(conn, company_id)
    if code is None:
        return {"code": None, "found": 0, "new": 0}
    today = today or datetime.now(timezone.utc).date()
    since = today - timedelta(days=LOOKBACK_DAYS)
    found = new = 0
    for meeting_year in (today.year, today.year - 1):  # a report is listed under the year of the meeting it is for
        for report in mops_client.english_annual_reports(await mops_client.list_documents(code, meeting_year)):
            if date.fromisoformat(report["uploaded"] or report["meeting_date"]) < since:
                continue
            found += 1
            existing = conn.execute("SELECT id, status FROM documents WHERE source = ? AND external_id = ?",
                                    (SOURCE, report["filename"])).fetchone()
            document_id = existing["id"] if existing else register_report(conn, company_id, report)
            new += not existing
            if not existing or (existing["status"] == "discovered"
                                and not conn.execute("SELECT 1 FROM jobs WHERE kind = 'download' AND key = ?", (_key(report["filename"]),)).fetchone()):
                jobs.enqueue(conn, "download", _key(report["filename"]),
                             {"source": SOURCE, "document_id": document_id, "co_id": code, "filename": report["filename"], "form": KIND},
                             priority=DOWNLOAD_PRIORITY, company_id=company_id, document_id=document_id)
    return {"code": code, "found": found, "new": new}


def _key(filename):
    """The download job's key: "mops/<file name>", apart from SEC's accession/file keys."""
    return f"{SOURCE}/{filename}"


async def fetch_document(conn, document_id, co_id, filename):
    """Downloads a registered report and records its hash; one that's already fetched isn't downloaded again."""
    row = conn.execute("SELECT status, content_hash FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        raise ValueError(f"no document {document_id}")
    if row["status"] in ("downloaded", "processed") and row["content_hash"]:
        return row["content_hash"]
    saved = await mops_client.download(co_id, filename)
    conn.execute("UPDATE documents SET content_hash = ?, size_bytes = ?, local_path = ?, fetched_at = ?, status = 'downloaded' WHERE id = ?",
                 (saved["sha256"], saved["size"], saved["path"], now(), document_id))
    return saved["sha256"]
