"""The one place the app talks to SEC EDGAR (#117): the boards job (#113) and the supply chain pipeline both use it.

SEC's fair-access rules: every request carries a User-Agent that names who is asking and how to reach them
(config.sec_contact_email: SEC_CONTACT_EMAIL in .env, bundled into the Mac app), and at most 10 requests a second;
we send about 6. A request that fails because EDGAR is busy (429, 5xx, the connection dropping) is retried after a
wait, honouring Retry-After; a 404 (no such filing) is not retried.

On top of the fetching: ticker -> CIK, a company's filings (from its submissions file, including the older pages
EDGAR splits long histories into), the documents inside one filing, and downloading a document with its SHA-256.
"""
import asyncio
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

import config

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SUBMISSIONS_PAGE_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{filename}"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/index.json"
MIN_INTERVAL_S = 0.16  # about 6 requests a second (SEC allows 10)
RETRY_WAITS_S = (5, 20, 60)
RETRY_STATUS = {429, 500, 502, 503, 504}
TIMEOUT_S = 60
MAX_BYTES = 150 * 1024 * 1024
TICKERS_MAX_AGE_S = 24 * 3600
SUBMISSIONS_MAX_AGE_S = 3600


class SecUnavailable(Exception):
    """EDGAR can't be reached or won't answer (no contact address, refused, still busy after the retries)."""


class SecNotFound(SecUnavailable):
    """EDGAR has no such page or filing (404)."""


_lock = asyncio.Lock()
_last = 0.0
_tickers = {"at": 0.0, "map": None}
_submissions = {}  # cik -> (time, json)


def headers():
    email = config.sec_contact_email()
    if not email:
        raise SecUnavailable("SEC requires a contact email in every request (SEC_CONTACT_EMAIL).")
    return {"User-Agent": f"PortfolioManager {email}", "Accept-Encoding": "identity"}


def _open(url, request_headers, timeout=TIMEOUT_S, max_bytes=MAX_BYTES):
    """One blocking request: (status, response headers, body). HTTP errors come back as a status; a dropped
    connection raises."""
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read(max_bytes + 1)
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers or {}), b""


async def get_bytes(url, max_bytes=MAX_BYTES):
    """The bytes at an EDGAR url, politely: spaced out, with the contact User-Agent, retried when EDGAR is busy."""
    global _last
    request_headers = headers()
    for attempt in range(len(RETRY_WAITS_S) + 1):
        async with _lock:
            wait = MIN_INTERVAL_S - (time.monotonic() - _last)
            if wait > 0:
                await asyncio.sleep(wait)
            _last = time.monotonic()
        try:
            status, response_headers, body = await asyncio.to_thread(_open, url, request_headers, TIMEOUT_S, max_bytes)
            problem = None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            status, response_headers, body, problem = None, {}, b"", exc.__class__.__name__
        if status == 200:
            if len(body) > max_bytes:
                raise SecUnavailable("The document is too large to download.")
            return body
        if status == 404:
            raise SecNotFound(f"EDGAR has nothing at {url}")
        if status == 403:
            raise SecUnavailable("EDGAR refused the request (403): check SEC_CONTACT_EMAIL, and that requests aren't too frequent.")
        if status is not None and status not in RETRY_STATUS:
            raise SecUnavailable(f"EDGAR answered {status} for {url}")
        if attempt == len(RETRY_WAITS_S):
            raise SecUnavailable(f"EDGAR didn't answer ({status or problem}) after {attempt + 1} tries.")
        retry_after = response_headers.get("Retry-After", "")
        await asyncio.sleep(min(float(retry_after), 120) if retry_after.isdigit() else RETRY_WAITS_S[attempt])


async def get_json(url):
    return json.loads(await get_bytes(url))


# ---------- Tickers and companies ----------

def sec_ticker(symbol):
    """IB's "BRK B" is SEC's "BRK-B"."""
    return symbol.strip().upper().replace(" ", "-").replace(".", "-")


async def cik_for_ticker(symbol):
    """The company's SEC number (CIK) from SEC's ticker list (fetched once a day), or None."""
    if _tickers["map"] is None or time.monotonic() - _tickers["at"] > TICKERS_MAX_AGE_S:
        data = await get_json(TICKERS_URL)
        _tickers["map"] = {row["ticker"].upper(): int(row["cik_str"]) for row in data.values()}
        _tickers["at"] = time.monotonic()
    return _tickers["map"].get(sec_ticker(symbol))


async def submissions(cik, max_age_s=SUBMISSIONS_MAX_AGE_S):
    """The company's submissions file (its name and recent filings); kept for an hour so one pass over many
    questions about one company asks EDGAR once."""
    held = _submissions.get(int(cik))
    if held and time.monotonic() - held[0] < max_age_s:
        return held[1]
    data = await get_json(SUBMISSIONS_URL.format(cik=int(cik)))
    _submissions[int(cik)] = (time.monotonic(), data)
    return data


# ---------- Filings ----------

def document_url(cik, accession, filename):
    """The address of a file in a filing: accession "0000320193-25-000079" and a file name."""
    return ARCHIVE_URL.format(cik=int(cik), accession=accession.replace("-", ""), filename=filename)


def filings_from(page, cik):
    """The filings in a submissions page ("recent", or an older page's own columns) as dicts, newest first."""
    columns = page.get("filings", {}).get("recent", page) if "filings" in page else page
    if not columns or "accessionNumber" not in columns:
        return []
    found = []
    for i, accession in enumerate(columns["accessionNumber"]):
        def col(name, i=i):
            values = columns.get(name) or []
            return values[i] if i < len(values) else None
        primary = col("primaryDocument")
        found.append({
            "accession": accession, "form": col("form"), "filed": col("filingDate"), "period": col("reportDate") or None,
            "items": [item for item in (col("items") or "").split(",") if item],
            "primary_document": primary, "description": col("primaryDocDescription"), "size": col("size"),
            "xbrl": bool(col("isXBRL")), "inline_xbrl": bool(col("isInlineXBRL")),
            "url": document_url(cik, accession, primary) if primary else None,
            "index_url": INDEX_URL.format(cik=int(cik), accession=accession.replace("-", "")),
        })
    return found


async def list_filings(cik, forms=None, since=None, until=None):
    """A company's filings, newest first, optionally only some forms ("10-K", "10-Q", "8-K"; amendments like "10-K/A" are
    different forms) and only filed from `since` to `until` (dates or "YYYY-MM-DD"). EDGAR keeps about a thousand recent
    filings in the main file and the rest on older pages, which are fetched only when `since` reaches that far back."""
    since, until = _day(since), _day(until)
    data = await submissions(cik)
    found = filings_from(data, cik)
    oldest_recent = found[-1]["filed"] if found else None
    if since is None or (oldest_recent and _day(oldest_recent) > since):
        for older in data.get("filings", {}).get("files", []):
            if since is not None and older.get("filingTo") and _day(older["filingTo"]) < since:
                continue
            found += filings_from(await get_json(SUBMISSIONS_PAGE_URL.format(name=older["name"])), cik)
    return [f for f in found
            if (not forms or f["form"] in forms) and (since is None or _day(f["filed"]) >= since) and (until is None or _day(f["filed"]) <= until)]


def _day(value):
    if value is None or isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def parse_index(answer, cik, accession):
    """The files in a filing from its index.json: [{name, type, size, url}]."""
    items = (answer.get("directory") or {}).get("item") or []
    return [{"name": item["name"], "type": item.get("type") or "", "size": int(item["size"]) if str(item.get("size", "")).isdigit() else None,
             "url": document_url(cik, accession, item["name"])} for item in items if item.get("name") and item.get("type") != "folder.gif"]


async def filing_files(cik, accession):
    """Every file in one filing (the main document, exhibits, the XBRL data)."""
    return parse_index(await get_json(INDEX_URL.format(cik=int(cik), accession=accession.replace("-", ""))), cik, accession)


# ---------- Downloading ----------

def filings_dir():
    return config.DATA_DIR / "filings"


def safe_name(name):
    """A file name that can't escape its folder."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(name or "")) or "document"
    return cleaned.lstrip(".") or "document"


async def download(cik, accession, filename, folder=None):
    """Downloads one file of a filing to disk (default: data/filings/<cik>/<accession>/) and returns
    {path, sha256, size, url}. The hash is of the bytes as received; the file is written whole or not at all."""
    url = document_url(cik, accession, filename)
    body = await get_bytes(url)
    target = Path(folder or filings_dir() / str(int(cik)) / accession.replace("-", "")) / safe_name(filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(body)
    partial.replace(target)
    return {"path": str(target), "sha256": hashlib.sha256(body).hexdigest(), "size": len(body), "url": url}


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()
