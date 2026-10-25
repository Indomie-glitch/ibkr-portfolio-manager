"""Where a company's board comes from (#113): finding and reading the document.

- US stocks: the newest proxy statement (DEF 14A) on SEC EDGAR from the last 18 months, else a 20-F
  (foreign companies list their directors there). EDGAR needs a contact email in every request
  (config.sec_contact_email) and allows 10 requests a second; we stay well under that.
- ASX stocks: the newest "Annual Report" announcement on asx.com.au from this year or last. ASX
  allows this for private and personal use only, so it is fetched on demand in each user's app,
  after that user has accepted ASX's terms (directors.asx_terms_accepted), and never put in the
  shared seed.

The documents are long (CBA's 2025 annual report is 456 pages), so only the passages about the
board go to Claude: select_passages keeps the pages or parts that mention directors most.

Wikidata (no key) gives the people it links to a company, for Wikipedia links (people.py).
"""
import asyncio
import html as html_lib
import io
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from html.parser import HTMLParser

import config
import sec_client

REPO = "https://github.com/Indomie-glitch/ibkr-portfolio-manager"
TIMEOUT_S = 60
MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024  # the largest ASX annual reports are ~40 MB
FILING_MAX_AGE = timedelta(days=548)  # 18 months: a proxy older than that is out of date

SEC_FORMS = ("DEF 14A", "DEF 14C", "20-F")  # in order of preference (14C: an information statement)

ASX_LIST_URL = ("https://www.asx.com.au/asx/v2/statistics/announcements.do"
                "?by=asxCode&asxCode={code}&timeframe=Y&year={year}")
ASX_DISPLAY_URL = "https://www.asx.com.au/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId={ids_id}"
ASX_PDF_HOST = "announcements.asx.com.au"
# Announcements called "annual report" that aren't the annual report. ("Appendix 4E and 2026 Annual
# Report" is the report itself: BHP announces them together.)
ASX_NOT_THE_REPORT = re.compile(
    r"notice|letter|sustainab|modern slavery|tax|climate|remuneration|governance|results|"
    r"presentation|summary|review|proxy|half|webcast|briefing|errat|correction|supplement|fund|trust\b",
    re.IGNORECASE)

US_FILING = re.compile(r"20-F|\bform\b|\bUS annual report\b|\bSEC\b", re.IGNORECASE)

WIKIDATA_URL = "https://query.wikidata.org/sparql"
ASX_WIKIDATA_ID = "Q732670"


class SourceUnavailable(Exception):
    """The document can't be fetched (no contact email, a download failed, …): a plain message."""


class NoDocument(Exception):
    """The company has no suitable document (no proxy or annual report in the last 18 months)."""


class Unreadable(Exception):
    """The document has no usable text (e.g. a scanned PDF)."""


# ---------- HTTP ----------

def _get(url, headers=None, max_bytes=MAX_DOWNLOAD_BYTES):
    request = urllib.request.Request(url, headers={"User-Agent": f"PortfolioManager ({REPO})", **(headers or {})})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise SourceUnavailable("The document is too large to download.")
    return data


async def get(url, headers=None):
    try:
        return await asyncio.to_thread(_get, url, headers)
    except (SourceUnavailable, NoDocument):
        raise
    except Exception as exc:
        host = urllib.parse.urlparse(url).netloc
        raise SourceUnavailable(f"Couldn't download from {host} ({exc.__class__.__name__}).") from exc


# ---------- SEC EDGAR (the fetching is in sec_client.py, shared with the supply chain pipeline) ----------

sec_ticker = sec_client.sec_ticker


def sec_headers():
    try:
        return sec_client.headers()
    except sec_client.SecUnavailable as exc:
        raise SourceUnavailable(str(exc)) from exc


async def sec_get(url):
    """One EDGAR request (rate limited, retried, with the contact User-Agent); SourceUnavailable when it can't be had."""
    try:
        return await sec_client.get_bytes(url)
    except sec_client.SecUnavailable as exc:
        raise SourceUnavailable(str(exc)) from exc


async def sec_cik(ib_symbol):
    """The company's SEC number (CIK) from SEC's ticker list, or None."""
    try:
        return await sec_client.cik_for_ticker(ib_symbol)
    except sec_client.SecUnavailable as exc:
        raise SourceUnavailable(str(exc)) from exc


def choose_filings(submissions, cik, now):
    """The proxy statements (DEF 14A, else DEF 14C, else a 20-F) from the last 18 months in EDGAR's
    submissions JSON, newest first. A company's newest proxy can be for a special meeting with no
    director election, so reading falls back to the next one."""
    recent = submissions.get("filings", {}).get("recent", {})
    rows = [dict(zip(recent, values)) for values in zip(*recent.values())] if recent else []
    for form in SEC_FORMS:
        found = []
        for row in rows:  # EDGAR lists the newest first
            if row.get("form") != form:
                continue
            filed = datetime.strptime(row["filingDate"], "%Y-%m-%d")
            if now - filed > FILING_MAX_AGE:
                break
            found.append({
                "source": "sec", "kind": form, "filed": row["filingDate"],
                "title": f"{submissions.get('name') or 'Company'} {form} ({row['filingDate']})",
                "url": sec_client.document_url(cik, row["accessionNumber"], row["primaryDocument"]),
            })
        if found:
            return found
    return []


def choose_filing(submissions, cik, now):
    """The newest of choose_filings, or None."""
    return next(iter(choose_filings(submissions, cik, now)), None)


async def sec_documents(ib_symbol, now=None):
    """The company's recent proxy statements, newest first (NoDocument when there are none)."""
    cik = await sec_cik(ib_symbol)
    if cik is None:
        raise NoDocument(f"SEC has no company with the ticker {sec_ticker(ib_symbol)}.")
    try:
        submissions = await sec_client.submissions(cik)
    except sec_client.SecUnavailable as exc:
        raise SourceUnavailable(str(exc)) from exc
    found = choose_filings(submissions, cik, now or datetime.now())
    if not found:
        raise NoDocument("No proxy statement (DEF 14A) or 20-F on EDGAR in the last 18 months.")
    return [{**d, "cik": cik, "company_name": submissions.get("name")} for d in found]


async def latest_sec_document(ib_symbol, now=None):
    return (await sec_documents(ib_symbol, now))[0]


# ---------- ASX ----------

class _Rows(HTMLParser):
    """The rows of asx.com.au's announcements table: their text and first link."""

    def __init__(self):
        super().__init__()
        self.rows, self._row, self._in_row = [], None, False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = {"text": [], "href": None}
        elif tag == "a" and self._row is not None and self._row["href"] is None:
            self._row["href"] = dict(attrs).get("href")

    def handle_data(self, data):
        if self._row is not None:
            self._row["text"].append(data)

    def handle_endtag(self, tag):
        if tag == "tr" and self._row is not None:
            self.rows.append({"text": " ".join(" ".join(self._row["text"]).split()), "href": self._row["href"]})
            self._row = None


def parse_announcements(page):
    """[{date, headline, ids_id, pages}] from an asx.com.au yearly announcements page."""
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
                      "pages": int(pages.group(1)) if pages else None})
    return found


def choose_annual_report(rows, now):
    """The newest announcement that is the annual report itself, from the last 18 months, or None."""
    reports = [r for r in rows if re.search(r"\bannual report\b", r["headline"], re.IGNORECASE)
               and not ASX_NOT_THE_REPORT.search(r["headline"])
               and now - datetime.strptime(r["date"], "%Y-%m-%d") <= FILING_MAX_AGE]
    if not reports:
        return None
    # Dual-listed companies also announce their US filing ("US Annual Report (Form 20-F)"): prefer the
    # Australian annual report from the newest reporting season, the US one only when it's all there is
    newest = max(r["date"] for r in reports)
    season = [r for r in reports if datetime.strptime(newest, "%Y-%m-%d") - datetime.strptime(r["date"], "%Y-%m-%d") <= timedelta(days=60)]
    local = [r for r in season if not US_FILING.search(r["headline"])]
    return max(local or season, key=lambda r: r["date"])


async def latest_asx_report(code, now=None):
    """The newest annual report announcement (not downloaded yet)."""
    now = now or datetime.now()
    rows = []
    for year in (now.year, now.year - 1):
        page = await get(ASX_LIST_URL.format(code=code.upper(), year=year), {"User-Agent": "Mozilla/5.0"})
        rows += parse_announcements(page.decode("utf-8", "ignore"))
    report = choose_annual_report(rows, now)
    if report is None:
        raise NoDocument("No annual report announced on the ASX in the last 18 months.")
    return {"source": "asx", "kind": "Annual Report", "filed": report["date"], "ids_id": report["ids_id"],
            "title": (report["headline"] if report["headline"].upper().startswith(code.upper() + " ")
                      else f"{code.upper()} {report['headline']}") + f" ({report['date']})", "pages": report["pages"],
            "url": ASX_DISPLAY_URL.format(ids_id=report["ids_id"])}


def asx_pdf_url(terms_page):
    """The PDF's address from ASX's terms page (the form's hidden pdfURL), checked to be ASX's own."""
    found = re.search(r'name="pdfURL"\s+value="([^"]+)"|value="([^"]+)"\s+[^>]*name="pdfURL"', terms_page)
    url = html_lib.unescape(next((g for g in (found.groups() if found else ()) if g), ""))
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != ASX_PDF_HOST or not parsed.path.endswith(".pdf"):
        raise SourceUnavailable("ASX didn't give a link to the annual report.")
    return url


async def asx_pdf(document):
    """Downloads the annual report PDF. Only called once the user has accepted ASX's terms."""
    terms_page = (await get(document["url"], {"User-Agent": "Mozilla/5.0"})).decode("utf-8", "ignore")
    pdf_url = asx_pdf_url(terms_page)
    return pdf_url, await get(pdf_url, {"User-Agent": "Mozilla/5.0"})


# ---------- Text and the passages about the board ----------

class _Text(HTMLParser):
    """Visible text of an HTML filing, split at page breaks (EDGAR filings mark them in CSS)."""

    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table"}

    def __init__(self):
        super().__init__()
        self.pages, self._parts, self._skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        style = (dict(attrs).get("style") or "").replace(" ", "").lower()
        if "page-break-before:always" in style or "break-before:page" in style:
            self._new_page()
        if tag in self.BLOCK:
            self._parts.append("\n")
        if tag == "hr" and ("page-break-after:always" in style or "break-after:page" in style):
            self._new_page()

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag in ("td", "th"):
            self._parts.append(" | ")
        if tag in self.BLOCK:
            self._parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)  # <hr style="page-break-after: always"/>

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def _new_page(self):
        self.pages.append("".join(self._parts))
        self._parts = []

    def close(self):
        super().close()
        self._new_page()


def _tidy(text):
    lines = [" ".join(line.split()) for line in text.replace("\xa0", " ").split("\n")]
    return "\n".join(line for line in lines if line)


def html_sections(page_html, chunk_chars=6000):
    """[(label, text)]: "Page N" when the filing marks page breaks, else "Part N" chunks."""
    parser = _Text()
    parser.feed(page_html)
    parser.close()
    pages = [_tidy(p) for p in parser.pages]
    if sum(1 for p in pages if p) >= 5:
        return [(f"Page {i}", p) for i, p in enumerate(pages, start=1) if p]
    text = _tidy("\n".join(pages))
    chunks, current = [], []
    for line in text.split("\n"):
        current.append(line)
        if sum(len(c) for c in current) >= chunk_chars:
            chunks.append("\n".join(current))
            current = []
    if current:
        chunks.append("\n".join(current))
    return [(f"Part {i}", c) for i, c in enumerate(chunks, start=1)]


def pdf_sections(data):
    """[(\"Page N\", text)] from a PDF; Unreadable when it has (almost) no text, e.g. a scan."""
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(f"Page {i}", _tidy(page.extract_text() or "")) for i, page in enumerate(reader.pages, start=1)]
    except Exception as exc:
        raise Unreadable(f"The PDF couldn't be read ({exc.__class__.__name__}).") from exc
    if sum(len(text) for _, text in pages) < 2000:
        raise Unreadable("The PDF has no readable text (it may be scanned images).")
    return [(label, text) for label, text in pages if text]


# What the board pages talk about, with weights
BOARD_WORDS = [
    (re.compile(r"\bdirectors?\b", re.I), 0.3),
    (re.compile(r"non[-\s]?executive|independent director|lead independent", re.I), 1.5),
    (re.compile(r"director since|since 20\d\d|since 19\d\d|appointed (?:as )?(?:a )?director|appointed to the board", re.I), 8.0),
    (re.compile(r"\belected\b", re.I), 0.3),
    (re.compile(r"\bchair(?:man|woman|person)?\b", re.I), 1.0),
    (re.compile(r"\bage\b[ds]?\s*:?\s*\d{2}\b|\b\d{2} years old", re.I), 6.0),
    (re.compile(r"other (?:current |public company |listed company )?directorships?|other boards?|public company boards?", re.I), 8.0),
    (re.compile(r"\bcommittee\b", re.I), 0.5),
    (re.compile(r"\bnominees?\b", re.I), 1.5),
    (re.compile(r"\bboard of directors\b|directors'? report", re.I), 1.0),
    (re.compile(r"\bexperience\b|\bqualifications\b|\bskills\b", re.I), 1.0),
]


def section_score(text):
    """How much a section is about the board. Pages of numbers (compensation tables, ownership tables)
    repeat "director" without describing anyone, so the score falls as the share of digits rises; a
    biography page has few digits (a few years and an age)."""
    score = sum(weight * len(pattern.findall(text)) for pattern, weight in BOARD_WORDS)
    digits = sum(ch.isdigit() for ch in text) / max(len(text), 1)
    return score / (1 + 25 * digits)


def split_large(sections, limit=12_000):
    """Sections longer than limit (a filing with no page breaks, or one giant "page") cut into parts
    at line breaks, so the board part of it can be chosen on its own: "Page 4" -> "Page 4, part 2"."""
    result = []
    for label, text in sections:
        if len(text) <= limit:
            result.append((label, text))
            continue
        parts, current, size = [], [], 0
        for line in text.split("\n"):
            current.append(line)
            size += len(line) + 1
            if size >= limit * 0.6:
                parts.append("\n".join(current))
                current, size = [], 0
        if current:
            parts.append("\n".join(current))
        result += [(f"{label}, part {i}", part) for i, part in enumerate(parts, start=1)]
    return result


# A director's biography: how long they've served, their age, their other boards
BIO_SIGNALS = re.compile(
    r"director since|\bage\b[ds]?\s*:?\s*\d{2}\b|\b\d{2} years old|other (?:current |public company |listed company )?directorships?|"
    r"public company boards?|appointed (?:as )?(?:a )?director|appointed to the board", re.I)


def select_passages(sections, budget_chars=110_000):
    """The sections most about the board, up to budget_chars (~28K tokens), in document order. Pages
    that look like biographies (two or more signals: "Director since", an age, other boards) come
    first, up to 70% of the budget, so a long run of nominee pages isn't cut short by other pages that
    only mention directors; the rest is filled by score. Each chosen page brings its next page when
    there's room, since a director's profile often runs over."""
    sections = split_large(sections)
    scored = sorted(((section_score(text), i) for i, (_, text) in enumerate(sections)), reverse=True)
    if not scored or scored[0][0] == 0:
        return []
    keep, used = set(), 0

    def add(i, limit):
        nonlocal used
        if i < len(sections) and i not in keep and used + len(sections[i][1]) <= limit:
            keep.add(i)
            used += len(sections[i][1])

    bios = [i for i, (_, text) in enumerate(sections) if len(BIO_SIGNALS.findall(text)) >= 2]
    for i in sorted(bios, key=lambda i: -section_score(sections[i][1])):
        add(i, budget_chars * 0.7)
    for score, i in scored:
        if score < scored[0][0] * 0.25:
            break
        for j in (i, i + 1):
            add(j, budget_chars)
    return [sections[i] for i in sorted(keep)]


# ---------- Wikidata ----------

WIKIDATA_QUERY = """SELECT ?company ?person ?personLabel ?alias ?article WHERE {
  %s
  { ?company wdt:P3320 ?person } UNION { ?company wdt:P169 ?person } UNION { ?company wdt:P488 ?person }
  OPTIONAL { ?person skos:altLabel ?alias . FILTER(LANG(?alias) = "en") }
  OPTIONAL { ?article schema:about ?person ; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""


def wikidata_company_clause(market, symbol, cik=None):
    if market == "US" and cik:
        return f'?company wdt:P5531 "{int(cik):010d}" .'
    if market == "ASX" and re.fullmatch(r"[A-Z0-9]{1,6}", symbol.upper()):
        return f'?company p:P414 ?st . ?st ps:P414 wd:{ASX_WIKIDATA_ID} ; pq:P249 "{symbol.upper()}" .'
    return None


def parse_wikidata(answer):
    """[{id, label, aliases, article}] per person from a SPARQL JSON answer."""
    people = {}
    for row in answer.get("results", {}).get("bindings", []):
        person_id = row["person"]["value"].rsplit("/", 1)[-1]
        person = people.setdefault(person_id, {"id": person_id, "label": None, "aliases": [], "article": None})
        label = row.get("personLabel", {}).get("value")
        if label and label != person_id:
            person["label"] = label
        alias = row.get("alias", {}).get("value")
        if alias and alias not in person["aliases"]:
            person["aliases"].append(alias)
        article = row.get("article", {}).get("value")
        if article and article.startswith("https://en.wikipedia.org/"):
            person["article"] = article
    return list(people.values())


async def wikidata_people(market, symbol, cik=None):
    """The people Wikidata links to the company (board, CEO, chair); [] when it knows none or fails
    (the links are optional)."""
    clause = wikidata_company_clause(market, symbol, cik)
    if clause is None:
        return []
    url = WIKIDATA_URL + "?" + urllib.parse.urlencode({"query": WIKIDATA_QUERY % clause, "format": "json"})
    try:
        return parse_wikidata(json.loads(await get(url, {"Accept": "application/sparql-results+json"})))
    except Exception as exc:
        print(f"Wikidata lookup failed for {market}:{symbol}: {exc.__class__.__name__}")
        return []
