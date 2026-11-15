"""The one place the app talks to Taiwan's MOPS document server (#128): doc.twse.com.tw, where every listed company
(TWSE and TPEx) files its shareholder meeting documents, among them the annual report.

No key or account is needed. The server is slow and known to turn away clients that ask too often, so requests are
spaced MIN_INTERVAL_S apart and a busy answer is retried after a wait. Pages are Big5 encoded.

Two steps, as the site's own pages do them:
- The listing (t57sb01 step 1, mtype F = shareholder meeting documents) for one company and one meeting year, in ROC
  years (Western year - 1911). Each row has the data year, a Chinese description, the file name and the upload time.
- A download (step 9) answers with a page holding a temporary /pdf/... link; that link gives the PDF.

File names are <fiscal year>_<company code>_<meeting date>F<code>.pdf. The annual report is F04 (Chinese) and FE4
(English); F11 / FE6 are the versions revised after the meeting. We read the English report: the Reader's quotes
and the name resolver work in English.
"""
import asyncio
import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup

import sec_client

SOURCE = "mops"
BASE = "https://doc.twse.com.tw"
LIST_URL = BASE + "/server-java/t57sb01"
MIN_INTERVAL_S = 3.0
RETRY_WAITS_S = (10, 30, 90)
RETRY_STATUS = {429, 500, 502, 503, 504}
TIMEOUT_S = 60
DOWNLOAD_TIMEOUT_S = 180
MAX_BYTES = 80 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (Macintosh; PortfolioManager)"  # no personal details: the server asks for none
NO_DATA = "查無所需資料"  # "no matching data"
FILE_RE = re.compile(r"^(?P<year>\d{4})_(?P<co_id>[0-9A-Z]{4,6})_(?P<meeting>\d{8})F(?P<code>E?\d{1,2})\.pdf$", re.I)
ENGLISH_ANNUAL_REPORT = {"E4": False, "E6": True}  # code -> revised after the meeting


class MopsUnavailable(Exception):
    """The document server can't be reached, is busy, or answered something we can't read."""


class MopsNotFound(MopsUnavailable):
    """The server has no such file."""


_lock = asyncio.Lock()
_last = 0.0


def roc_year(year):
    """Taiwan's calendar: 2026 is ROC year 115."""
    return int(year) - 1911


def _open(url, data=None, timeout=TIMEOUT_S, max_bytes=MAX_BYTES):
    """One blocking request: (status, body). HTTP errors come back as a status; a dropped connection raises."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(max_bytes + 1)
    except urllib.error.HTTPError as err:
        return err.code, b""


async def fetch(url, data=None, timeout=TIMEOUT_S):
    """The bytes at a document server url, spaced out and retried while the server is busy."""
    global _last
    for attempt in range(len(RETRY_WAITS_S) + 1):
        async with _lock:
            wait = MIN_INTERVAL_S - (time.monotonic() - _last)
            if wait > 0:
                await asyncio.sleep(wait)
            _last = time.monotonic()
        try:
            status, body = await asyncio.to_thread(_open, url, data, timeout)
            problem = None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            status, body, problem = None, b"", exc.__class__.__name__
        if status == 200:
            if len(body) > MAX_BYTES:
                raise MopsUnavailable("The document is too large to download.")
            return body
        if status == 404:
            raise MopsNotFound(f"MOPS has nothing at {url}")
        if status is not None and status not in RETRY_STATUS:
            raise MopsUnavailable(f"MOPS answered {status}")
        if attempt == len(RETRY_WAITS_S):
            raise MopsUnavailable(f"MOPS didn't answer ({status or problem}) after {attempt + 1} tries.")
        await asyncio.sleep(RETRY_WAITS_S[attempt])


def listing_url(co_id, meeting_year):
    """The public page listing a company's shareholder meeting documents for one meeting year (a Western year)."""
    return f"{LIST_URL}?step=1&colorchg=1&co_id={co_id}&year={roc_year(meeting_year)}&mtype=F&"


def _uploaded(text):
    """'115/05/22 10:58:09' (ROC date, Taiwan time) -> '2026-05-22'."""
    m = re.match(r"^\s*(\d{2,3})/(\d{1,2})/(\d{1,2})", text or "")
    if not m:
        return None
    return datetime(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))).date().isoformat()


def parse_listing(html):
    """The rows of a listing page: [{co_id, fiscal_year, meeting_date, code, description, filename, size, uploaded}].
    A page saying there is no data gives []; a page that is neither raises MopsUnavailable (a busy or changed site)."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True).replace("\xa0", " ").strip() for td in tr.find_all("td")]
        name = next((c for c in cells if FILE_RE.match(c)), None)
        if not name:
            continue
        m = FILE_RE.match(name)
        at = cells.index(name)
        meeting = m.group("meeting")
        rows.append({
            "co_id": m.group("co_id"), "fiscal_year": int(m.group("year")), "code": m.group("code").upper(),
            "meeting_date": f"{meeting[:4]}-{meeting[4:6]}-{meeting[6:]}",
            "description": cells[at - 2] if at >= 2 else "", "filename": name,
            "size": int(re.sub(r"\D", "", cells[at + 1]) or 0) if len(cells) > at + 1 else None,
            "uploaded": _uploaded(cells[at + 2]) if len(cells) > at + 2 else None})
    if not rows and NO_DATA not in html and "t57sb01" not in html:
        raise MopsUnavailable("MOPS answered a page we can't read (busy, or the site changed).")
    return rows


def english_annual_reports(rows):
    """The English annual reports among a listing's rows, one per fiscal year: the report as filed for the meeting
    (FE4), or the version revised after it (FE6) when that is the only one. Each gets revised: True / False."""
    best = {}
    for row in rows:
        if row["code"] not in ENGLISH_ANNUAL_REPORT:
            continue
        row = {**row, "revised": ENGLISH_ANNUAL_REPORT[row["code"]]}
        held = best.get(row["fiscal_year"])
        if held is None or (held["revised"] and not row["revised"]):
            best[row["fiscal_year"]] = row
    return [best[year] for year in sorted(best, reverse=True)]


async def list_documents(co_id, meeting_year):
    """A company's shareholder meeting documents for one meeting year (Western year)."""
    html = (await fetch(listing_url(co_id, meeting_year))).decode("big5", errors="replace")
    return parse_listing(html)


def _pdf_link(html):
    m = re.search(r"href=['\"](/pdf/[^'\"]+\.pdf)['\"]", html, re.I)
    return BASE + m.group(1) if m else None


async def download(co_id, filename, folder=None):
    """Downloads one document to disk (default: data/filings/mops/<company code>/) and returns {path, sha256, size}.
    The file is written whole or not at all."""
    if not FILE_RE.match(filename or ""):
        raise ValueError(f"not a MOPS document name: {filename!r}")
    page = (await fetch(LIST_URL, {"colorchg": "1", "step": "9", "kind": "F", "co_id": co_id, "filename": filename})).decode("big5", errors="replace")
    link = _pdf_link(page)
    if not link:
        if NO_DATA in page:
            raise MopsNotFound(f"MOPS has no file {filename}")
        raise MopsUnavailable("MOPS didn't give a download link (busy, or the site changed).")
    body = await fetch(link, timeout=DOWNLOAD_TIMEOUT_S)
    if not body.startswith(b"%PDF"):
        raise MopsUnavailable(f"MOPS sent something other than a PDF for {filename}")
    target = Path(folder or sec_client.filings_dir() / SOURCE / sec_client.safe_name(co_id)) / sec_client.safe_name(filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(body)
    partial.replace(target)
    return {"path": str(target), "sha256": hashlib.sha256(body).hexdigest(), "size": len(body)}
