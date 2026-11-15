"""The one place the app talks to asx.com.au: company announcements (boards of directors, #113, and the supply chain
pipeline's material contract announcements, #131).

ASX allows its company announcements for private and personal use only, so nothing here is called before the user has
accepted ASX's terms in the app (directors.asx_terms_accepted), and nothing fetched here goes into a shared seed.

Three steps, as asx.com.au's own pages do them:
- A company's announcements for one calendar year (announcements.do, timeframe Y): date and time, a price sensitive
  mark, the headline, the number of pages and an idsId per announcement.
- displayAnnouncement.do?idsId=... answers with ASX's terms page, whose form holds the PDF's address (pdfURL); the
  address is only followed when it is https on announcements.asx.com.au.
- The PDF itself.

No key is needed. Requests are spaced MIN_INTERVAL_S apart (boards and the pipeline share the spacing); the pipeline's
background requests are retried after a wait when ASX is busy, a board read on request is not (the user is waiting).
"""
import asyncio
import hashlib
import html as html_lib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import sec_client

SOURCE = "asx"
LIST_URL = ("https://www.asx.com.au/asx/v2/statistics/announcements.do"
            "?by=asxCode&asxCode={code}&timeframe=Y&year={year}")
DISPLAY_URL = "https://www.asx.com.au/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId={ids_id}"
PDF_HOST = "announcements.asx.com.au"
USER_AGENT = "Mozilla/5.0"  # asx.com.au turns away clients that don't look like a browser; no personal details
TIMEOUT_S = 60
MAX_BYTES = 80 * 1024 * 1024  # the largest ASX annual reports are ~40 MB
MIN_INTERVAL_S = 3.0
RETRY_WAITS_S = (10, 30, 90)
RETRY_STATUS = {429, 500, 502, 503, 504}
CODE = re.compile(r"^[A-Z0-9]{2,6}$")
IDS_ID = re.compile(r"^\d{5,12}$")


class AsxUnavailable(Exception):
    """asx.com.au can't be reached, is busy, or answered something we can't read: a plain message."""


class AsxNotFound(AsxUnavailable):
    """ASX has no such page or announcement."""


_lock = asyncio.Lock()
_last = 0.0


def _open(url, max_bytes):
    """One blocking request: (status, body). HTTP errors come back as a status; a dropped connection raises."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status, response.read(max_bytes + 1)
    except urllib.error.HTTPError as err:
        return err.code, b""


async def fetch(url, retries=RETRY_WAITS_S, max_bytes=MAX_BYTES):
    """The bytes at an asx.com.au address, spaced out from the last request; retried after each wait in `retries` while
    ASX is busy or the connection drops (pass () for a single try)."""
    global _last
    host = urllib.parse.urlparse(url).netloc
    for attempt in range(len(retries) + 1):
        async with _lock:
            wait = MIN_INTERVAL_S - (time.monotonic() - _last)
            if wait > 0:
                await asyncio.sleep(wait)
            _last = time.monotonic()
        try:
            status, body = await asyncio.to_thread(_open, url, max_bytes)
            problem = None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            status, body, problem = None, b"", exc.__class__.__name__
        if status == 200:
            if len(body) > max_bytes:
                raise AsxUnavailable("The document is too large to download.")
            return body
        if status == 404:
            raise AsxNotFound(f"{host} has nothing at that address.")
        if status is not None and status not in RETRY_STATUS:
            raise AsxUnavailable(f"Couldn't download from {host} (it answered {status}).")
        if attempt == len(retries):
            raise AsxUnavailable(f"Couldn't download from {host} ({status or problem}).")
        await asyncio.sleep(retries[attempt])


# ---------- The announcements listing ----------

class _Rows(HTMLParser):
    """The rows of asx.com.au's announcements table: their text, first link, and whether the row has the price
    sensitive mark (an <img> titled "price sensitive")."""

    def __init__(self):
        super().__init__()
        self.rows, self._row = [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self._row = {"text": [], "href": None, "price_sensitive": False}
        elif self._row is None:
            return
        elif tag == "a" and self._row["href"] is None:
            self._row["href"] = attrs.get("href")
        elif tag == "img" and ((attrs.get("title") or "").lower() == "price sensitive" or "price-sensitive" in (attrs.get("src") or "")):
            self._row["price_sensitive"] = True

    def handle_data(self, data):
        if self._row is not None:
            self._row["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "tr" and self._row is not None:
            self.rows.append({**self._row, "text": " ".join(" ".join(self._row["text"]).split())})
            self._row = None


def parse_announcements(page):
    """[{date, headline, ids_id, pages, price_sensitive}] from an asx.com.au yearly announcements page, newest first as
    listed. Rows without a date and an idsId (the header) are skipped."""
    parser = _Rows()
    parser.feed(page)
    found = []
    for row in parser.rows:
        ids = re.search(r"idsId=(\d+)", html_lib.unescape(row["href"] or ""))
        when = re.match(r"(\d{2}/\d{2}/\d{4})\s+\d{1,2}:\d{2}\s*[ap]m\s+(.*)", row["text"], re.IGNORECASE)
        if not ids or not when:
            continue
        rest = when.group(2)
        pages = re.search(r"(\d+)\s+pages?\b", rest)
        headline = re.sub(r"\s+\d+\s+pages?\b.*$", "", rest).strip()
        found.append({"date": datetime.strptime(when.group(1), "%d/%m/%Y").strftime("%Y-%m-%d"),
                      "headline": headline, "ids_id": ids.group(1),
                      "pages": int(pages.group(1)) if pages else None, "price_sensitive": row["price_sensitive"]})
    return found


def listing_url(code, year):
    if not CODE.match(code or ""):
        raise ValueError(f"not an ASX code: {code!r}")
    return LIST_URL.format(code=code, year=int(year))


async def announcements(code, year, retries=RETRY_WAITS_S):
    """A company's announcements in one calendar year (ASX code, e.g. "NXT")."""
    page = await fetch(listing_url(code.upper(), year), retries)
    return parse_announcements(page.decode("utf-8", "ignore"))


def display_url(ids_id):
    if not IDS_ID.match(str(ids_id or "")):
        raise ValueError(f"not an ASX announcement id: {ids_id!r}")
    return DISPLAY_URL.format(ids_id=ids_id)


# ---------- The PDF ----------

def pdf_url(terms_page):
    """The PDF's address from ASX's terms page (the form's hidden pdfURL), checked to be ASX's own."""
    found = re.search(r'name="pdfURL"\s+value="([^"]+)"|value="([^"]+)"\s+[^>]*name="pdfURL"', terms_page)
    url = html_lib.unescape(next((g for g in (found.groups() if found else ()) if g), ""))
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != PDF_HOST or not parsed.path.endswith(".pdf"):
        raise AsxUnavailable("ASX didn't give a link to the announcement's PDF.")
    return url


async def fetch_pdf(display, retries=RETRY_WAITS_S):
    """(pdf url, bytes) for an announcement's display address (its terms page)."""
    terms_page = (await fetch(display, retries)).decode("utf-8", "ignore")
    url = pdf_url(terms_page)
    return url, await fetch(url, retries)


async def download(ids_id, code, folder=None):
    """Downloads one announcement's PDF (default: data/filings/asx/<code>/<idsId>.pdf) and returns {path, sha256, size,
    pdf_url}. The file is written whole or not at all."""
    url, body = await fetch_pdf(display_url(ids_id))
    if not body.startswith(b"%PDF"):
        raise AsxUnavailable(f"ASX sent something other than a PDF for announcement {ids_id}.")
    target = Path(folder or sec_client.filings_dir() / SOURCE / sec_client.safe_name(code)) / f"{ids_id}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(body)
    partial.replace(target)
    return {"path": str(target), "sha256": hashlib.sha256(body).hexdigest(), "size": len(body), "pdf_url": url}
