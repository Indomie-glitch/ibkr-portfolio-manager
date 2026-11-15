"""ASX material contract announcements (#131): finds the announcements of ASX-listed companies that are about a
contract, agreement or partnership, registers each as a document, downloads its PDF and queues the Reader.

A company is scouted here when it has an ASX ticker (identifiers scheme ticker, market ASX: "NXT" for NEXTDC) and no
US listing or CIK; one with a US listing files with SEC and is read from EDGAR only, as Taiwan companies with an ADR are
(mops.py, #128).

ASX allows its announcements for private and personal use only. So nothing is fetched until the user has accepted ASX's
terms in the app (directors.asx_terms_accepted, the same acceptance boards of directors need, #113); until then an
ASX-only company isn't scouted and the pipeline says it is "waiting for ASX terms". What is fetched stays in the user's
own data folder: no ASX document or relationship is ever put in a seed.

Which announcements: ASX lists every announcement, most of them about shares, meetings and results. The headline
decides (worth_reading): a SKIP word (financing, securities admin, substantial holders, directors, results, meetings,
governance, trading halts, takeovers, exploration results ...) rules it out; then a DEAL word (contract, agreement,
MoU, offtake, supply, customer, partnership, award, signs, secures ...) takes it; and a price sensitive announcement of
a few pages with neither takes it too, since material news that moves the price is often a deal the headline doesn't
name ("Building the Next Generation of Sovereign AI infrastructure" is NEXTDC's MoU with OpenAI). The words were tuned
on NEXTDC's, Lynas's and Pilbara Minerals' (PLS) listings for 2025-26 (docs/supply-chain-graph.md). Price sensitive
ones are also downloaded first.

Documents: source "asx", kind "ASX announcement" (what the Reader sees as the form), external_id = ASX's idsId,
url = ASX's display address (its terms page, then the PDF), title = the headline, filed_at = the announcement's date.
The scout job (scout.py) calls scan(); the download job (kind "download", payload source "asx") calls
fetch_document().
"""
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone

import asx_client
import directors
from supply_chain import graph, jobs
from supply_chain.db import now

SOURCE = asx_client.SOURCE
KIND = "ASX announcement"
MARKET = "ASX"
LOOKBACK_DAYS = 400  # like annual reports: a year of announcements, and a little more
MAX_PAGES = 40  # a deal announcement is a few pages; booklets, prospectuses and scheme documents are longer
PRICE_SENSITIVE_MAX_PAGES = 10  # a price sensitive announcement without a deal word is read only when it is short
DOWNLOAD_PRIORITY = 30  # as an 8-K
PRICE_SENSITIVE_PRIORITY = 35

# A headline with one of these is never read, whatever else it says ("A$1.8 billion of New Senior Debt Commitments
# Secured", "Convertible Notes Offering", "Appendix 4E and Annual Report")
SKIP = re.compile(r"""\b(?:
    financ\w* | capital\ raising | raising | placement | entitlement | offers? | offering | share\ purchase\ plan | spp
  | convertible | notes? | bonds? | hybrid | debt | loans? | facilit(?:y|ies) | underwrit\w* | dividend\w* | buy-?back
  | appendix\ ?\w+ | quotation | unquoted | cessation | securities | cleansing | substantial\ hold\w* | holder
  | directors?'?s? | board | chair\w* | ceo | cfo | chief\ \w+\ officer | company\ secretary | appoint\w* | resign\w*
  | retire\w* | results? | half[\ -]?year\w* | full[\ -]?year | annual\ report | quarterly | activities\ report | accounts
  | financial\ (?:report|statements?) | interim | presentation | webcast | briefing | conference\ call | investor\ day
  | agm | egm | general\ meeting | meeting | proxy | notice\ of | address | governance | sustainab\w* | esg | climate
  | modern\ slavery | remuneration | constitution | incentive | employee | trading\ halt | suspension | reinstatement
  | pause | response\ to | aware\ letter | price\ query | compliance\ letter | rebalance | index | takeover | scheme
  | bidder'?s? | target'?s?\ statement | share\ raid | merger | acqui\w+ | change\ of\ (?:address|name|auditor|registry)
  | drill\w* | assays? | intercepts? | resource\ estimate | ore\ reserve | mineral\ resource | jorc
)\b""", re.IGNORECASE | re.VERBOSE)

# A headline with one of these (and no SKIP word) is about a deal with another company
DEAL = re.compile(r"""\b(?:
    contract\w* | agreements? | agree[sd]? | mou | memorandum\ of\ understanding | letter\ of\ intent | loi
  | heads\ of\ agreement | term\ sheet | off-?take | suppl(?:y|ies|ier|iers) | customers? | clients? | partner\w*
  | alliance | collaborat\w* | joint\ venture | jv | awards? | awarded | tender | selected | preferred\ (?:bidder|supplier)
  | signs? | signed | signing | executes? | executed | secures? | secured | orders? | deal
)\b""", re.IGNORECASE | re.VERBOSE)


def worth_reading(row):
    """Why an announcement (a row from asx_client.parse_announcements) is read: "deal" or "price sensitive", or None
    when it isn't."""
    headline, pages = row.get("headline") or "", row.get("pages")
    if SKIP.search(headline) or (pages is not None and pages > MAX_PAGES):
        return None
    if DEAL.search(headline):
        return "deal"
    if row.get("price_sensitive") and pages is not None and pages <= PRICE_SENSITIVE_MAX_PAGES:
        return "price sensitive"
    return None


def terms_accepted():
    """Whether the user has accepted ASX's terms in the app (directors.sqlite); False when that can't be read. A missing
    file means never accepted (and isn't created by asking)."""
    if not directors.DB_PATH.exists():
        return False
    try:
        return bool(directors.asx_terms_accepted())
    except sqlite3.Error:
        return False


def company_code(conn, company_id):
    """The company's ASX code ("NXT"), or None."""
    row = conn.execute("SELECT value FROM identifiers WHERE company_id = ? AND scheme = 'ticker' AND market = ? ORDER BY id LIMIT 1",
                       (company_id, MARKET)).fetchone()
    return row["value"].upper() if row else None


def register_announcement(conn, company_id, row):
    """Adds an announcement as a document; returns its id."""
    return graph.add_document(conn, SOURCE, KIND, row["ids_id"], asx_client.display_url(row["ids_id"]), company_id=company_id,
                              title=row["headline"], filed_at=row["date"], language="en", status="discovered")


def _key(ids_id):
    """The download job's key: "asx/<idsId>", apart from SEC's accession/file keys."""
    return f"{SOURCE}/{ids_id}"


async def scan(conn, company_id, today=None):
    """Registers the company's announcements worth reading from the last LOOKBACK_DAYS that we haven't seen and queues
    their downloads. Returns {"code", "listed", "found", "new"} (code None when the company has no ASX code; listed =
    announcements seen in the window, found = the ones worth reading). Call only once ASX's terms are accepted."""
    code = company_code(conn, company_id)
    if code is None:
        return {"code": None, "listed": 0, "found": 0, "new": 0}
    today = today or datetime.now(timezone.utc).date()
    since = today - timedelta(days=LOOKBACK_DAYS)
    listed = found = new = 0
    for year in range(today.year, since.year - 1, -1):  # ASX lists by calendar year: this year's page, then earlier ones
        for row in await asx_client.announcements(code, year):
            if date.fromisoformat(row["date"]) < since:
                continue
            listed += 1
            why = worth_reading(row)
            if why is None:
                continue
            found += 1
            key = _key(row["ids_id"])
            existing = conn.execute("SELECT id, status FROM documents WHERE source = ? AND external_id = ?", (SOURCE, row["ids_id"])).fetchone()
            document_id = existing["id"] if existing else register_announcement(conn, company_id, row)
            new += not existing
            # One seen before is queued again only while it waits for a download that isn't queued, running or done
            # (the app stopped in between, or a download that died after its retries)
            if not existing or (existing["status"] == "discovered" and not conn.execute(
                    "SELECT 1 FROM jobs WHERE kind = 'download' AND key = ? AND status IN ('queued', 'running', 'done')", (key,)).fetchone()):
                jobs.enqueue(conn, "download", key,
                             {"source": SOURCE, "document_id": document_id, "ids_id": row["ids_id"], "code": code, "form": KIND, "why": why},
                             priority=PRICE_SENSITIVE_PRIORITY if row.get("price_sensitive") else DOWNLOAD_PRIORITY,
                             company_id=company_id, document_id=document_id)
    return {"code": code, "listed": listed, "found": found, "new": new}


async def fetch_document(conn, document_id, ids_id, code):
    """Downloads a registered announcement's PDF and records its hash; one already fetched isn't downloaded again."""
    row = conn.execute("SELECT status, content_hash FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        raise ValueError(f"no document {document_id}")
    if row["status"] in ("downloaded", "processed") and row["content_hash"]:
        return row["content_hash"]
    saved = await asx_client.download(ids_id, code)
    conn.execute("UPDATE documents SET content_hash = ?, size_bytes = ?, local_path = ?, fetched_at = ?, status = 'downloaded' WHERE id = ?",
                 (saved["sha256"], saved["size"], saved["path"], now(), document_id))
    return saved["sha256"]
