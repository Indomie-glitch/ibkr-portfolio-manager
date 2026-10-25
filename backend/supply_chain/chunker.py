"""Document chunker (#123): turns a downloaded filing into pieces the Reader agent (#124) can send to Claude. No AI here.

Three steps, each usable on its own:
1. Text: load_paragraphs() turns HTML (or plain text) into a list of paragraphs. Tables stay readable as rows, one row a
   line, cells separated by " | ". Paragraphs are numbered from 1 in this cleaned list; the numbers are what a locator
   points at, so the same file always gives the same numbers.
2. Sections: a section finder keeps the passages that name business relationships and drops the rest (exhibit lists,
   signatures, boilerplate). A finder is a function (paragraphs, form) -> list[Section] | None, registered for a source
   with @finder("sec"). None means "this finder can't tell" and the whole text is used instead; an empty list means
   "I read the structure and nothing here matters". Other sources (MOPS, EDINET, DART, ASX PDFs, #128 to #131) register
   their own finder and call chunk_paragraphs() with paragraphs from their own loader.
3. Chunks: each section is cut into chunks under MAX_CHUNK_TOKENS at paragraph boundaries (a paragraph that is too big
   is cut at line, then sentence, then word boundaries). The next chunk starts with the last paragraphs of the previous
   one (up to OVERLAP_TOKENS), so a relationship that straddles a boundary shows up whole in one of them.

Why 80,000: claude-haiku-5-5 costs 5 times more for a prompt over 100,000 tokens (usage_store.PRICES long_from), and the
Reader's instructions and the answer need room too. estimate_tokens() has no tokenizer to call, so it is deliberately high.
"""
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Comment

MAX_CHUNK_TOKENS = 80_000
OVERLAP_TOKENS = 1_000
MIN_SECTION_CHARS = 100  # an "Item" shorter than this is a table of contents line or a cross-reference

PARAGRAPH_BREAK = "\x1d"
ROW_BREAK = "\x1e"


# ---------- Token estimate ----------

_PIECES = re.compile(r"[^\W\d_]+|\d+|[^\s\w]|_")


def estimate_tokens(text):
    """A cheap estimate that errs high: a word costs one token per 3 letters, a run of digits one per 3 digits and every
    symbol one. Numbers and punctuation are where a letters-per-token rule undercounts ("1,234,567" is five tokens), and
    tables are full of them. Ordinary prose comes out around 1.5 times the real count."""
    total = 0
    for piece in _PIECES.findall(text):
        total += math.ceil(len(piece) / 3) if piece[0].isalnum() else 1
    return total


# ---------- Result types ----------

@dataclass
class Section:
    """A passage worth reading: a name and the paragraphs (0-based indexes into the paragraph list, in order)."""
    name: str
    paragraphs: list


@dataclass
class Chunk:
    """One piece to send to the Reader. first_paragraph / last_paragraph are 1-based numbers in the cleaned text of
    `document`; `overlap` is how many paragraphs at the start repeat the end of the previous chunk of the section."""
    document: str
    section: str
    text: str
    tokens: int
    first_paragraph: int
    last_paragraph: int
    overlap: int = 0
    number: int = 0  # position in the list chunk_filing / chunk_paragraphs returned
    locator: str = field(init=False)

    def __post_init__(self):
        self.locator = locator_for(self.section, self.first_paragraph, self.last_paragraph)


def locator_for(section, first, last):
    where = f"paragraph {first}" if first == last else f"paragraphs {first}-{last}"
    return f"{section}, {where}"


# ---------- Text ----------

_HTML_SNIFF = re.compile(r"<\s*(html|body|div|p|table|font|span|br)\b", re.I)
_BLOCK_TAGS = ["p", "div", "li", "ul", "ol", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "section",
               "article", "center", "pre", "hr", "body", "tr"]
_PREFIX_CELLS = {"$", "(", "€", "£", "¥", "$(", "($"}
_SUFFIX_CELLS = {")", "%", ")%", "%)"}
_JUNK = re.compile(r"^(table of contents|index|back to (top|contents)|\(?continued\)?)$|^[-–—\s]*(page\s*)?[fF]?-?\s*\d{1,3}[-–—\s]*$", re.I)
_SPACES = re.compile(r"[ \t\r\f\v  -​ ⁠﻿]+")


def _clean(text):
    return _SPACES.sub(" ", text.replace("\n", " ")).strip()


def decode(raw):
    """Bytes to text: UTF-8 when it is, else Windows-1252 (older filings)."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _table_rows(table):
    rows = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        cells, pending = [], ""
        for cell in tr.find_all(["td", "th"]):
            if cell.find_parent("tr") is not tr:
                continue
            text = _clean(cell.get_text(" "))
            if not text:
                continue
            if text in _PREFIX_CELLS:  # EDGAR puts "$" and ")" in cells of their own
                pending += text
            elif text in _SUFFIX_CELLS and cells:
                cells[-1] += text
            else:
                cells.append(pending + text)
                pending = ""
        if cells:
            rows.append(cells)
    return rows


def html_paragraphs(html):
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head", "title", "ix:header"]):  # ix:header is the hidden XBRL block
        tag.decompose()
    for node in soup.find_all(string=lambda s: isinstance(s, Comment)):
        node.extract()
    for node in list(soup.find_all(string=True)):
        node.replace_with(re.sub(r"\s+", " ", str(node)))
    for br in soup.find_all("br"):
        br.replace_with(" ")
    for table in [t for t in soup.find_all("table") if not t.find_parent("table")]:
        rows = _table_rows(table)
        if len(rows) == 1:  # a one-row table is layout ("Item 1." | "Business"), not data
            text = " ".join(rows[0])
        else:
            text = ROW_BREAK.join(" | ".join(row) for row in rows)
        table.replace_with(PARAGRAPH_BREAK + text + PARAGRAPH_BREAK)
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before(PARAGRAPH_BREAK)
        tag.insert_after(PARAGRAPH_BREAK)
    return _finish(soup.get_text().split(PARAGRAPH_BREAK))


def text_paragraphs(text):
    """Plain text: blocks are separated by blank lines. A hard-wrapped block is joined into one paragraph; one laid out in
    columns (lines with wide gaps, as in older filings' tables) keeps its lines."""
    blocks = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n")):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        columns = sum(1 for line in lines if re.search(r"\S {3,}\S", line))
        blocks.append(ROW_BREAK.join(lines) if len(lines) > 1 and columns * 2 >= len(lines) else " ".join(lines))
    return _finish(blocks)


def _finish(blocks):
    paragraphs = []
    for block in blocks:
        rows = [_clean(row) for row in block.split(ROW_BREAK)]
        rows = [row for row in rows if row]
        if not rows or (len(rows) == 1 and _JUNK.match(rows[0])):
            continue
        paragraphs.append("\n".join(rows))
    return paragraphs


def paragraphs_from(content):
    """Paragraphs from the text of an HTML or plain text document."""
    return html_paragraphs(content) if _HTML_SNIFF.search(content[:5000]) else text_paragraphs(content)


def load_paragraphs(path):
    return paragraphs_from(decode(Path(path).read_bytes()))


# ---------- Finding sections: registry ----------

FINDERS = {}


def finder(source):
    """Registers a section finder for a source: fn(paragraphs, form) -> list[Section] | None."""
    def register(fn):
        FINDERS[source] = fn
        return fn
    return register


def find_sections(paragraphs, source, form):
    fn = FINDERS.get(source)
    found = fn(paragraphs, form) if fn else None
    if found is None:
        return [Section("Full text", list(range(len(paragraphs))))] if paragraphs else []
    return [s for s in found if s.paragraphs]


# ---------- Finding sections: SEC filings ----------

WHOLE, PASSAGES, STATEMENTS = "whole", "passages", "statements"

# form -> {item key: (section name, how it is kept)}; 10-Q keys are (part, item) because Part I and II both have an Item 1
SEC_ITEMS = {
    "10-K": {"1": ("Item 1. Business", WHOLE), "1A": ("Item 1A. Risk Factors", WHOLE),
             "7": ("Item 7. MD&A (customer and supplier passages)", PASSAGES), "8": ("Item 8. Financial Statements", STATEMENTS)},
    "10-Q": {("I", "1"): ("Item 1. Financial Statements", STATEMENTS), ("I", "2"): ("Item 2. MD&A (customer and supplier passages)", PASSAGES),
             ("II", "1A"): ("Part II Item 1A. Risk Factors", WHOLE)},
    "20-F": {"3": ("Item 3. Key Information", WHOLE), "4": ("Item 4. Information on the Company", WHOLE),
             "5": ("Item 5. Operating and Financial Review (customer and supplier passages)", PASSAGES),
             "18": ("Item 18. Financial Statements", STATEMENTS), "17": ("Item 17. Financial Statements", STATEMENTS)},
    "8-K": {"1.01": ("Item 1.01 Entry into a Material Definitive Agreement", WHOLE),
            "1.02": ("Item 1.02 Termination of a Material Definitive Agreement", WHOLE)},
}
# Items whose body may hold the notes to the financial statements (10-Ks often put the F-pages under Item 15)
STATEMENT_ITEMS = {"10-K": {"8", "15"}, "10-Q": {("I", "1")}, "20-F": {"17", "18"}}

ITEM_RE = re.compile(r"^(?:PART\s+(?P<part>IV|I{1,3})\s*[,.\-–—:|]?\s*)?ITEM\s*(?P<item>\d{1,2}(?:\.\d{1,2})?[A-C]?)\s*[.:\-–—|]*\s*(?P<title>.*)$", re.I | re.S)
PART_RE = re.compile(r"^PART\s+(IV|I{1,3})\b.{0,60}$", re.I)
NOTE_RE = re.compile(r"^NOTE\s+(?P<number>\d{1,2}[A-Z]?)\s*[.:\-–—]*\s*(?P<title>[A-Z][^\n]{0,110})$", re.I)
NUMBERED_RE = re.compile(r"^(?P<number>\d{1,2})\.\s+(?P<title>[A-Z][^.\n]{2,90})$")
END_OF_NOTES_RE = re.compile(r"^(SIGNATURES?|EXHIBIT INDEX|INDEX TO EXHIBITS|EXHIBITS?)$", re.I)

RELATION_RE = re.compile(
    r"\b(customers?|suppliers?|vendors?|distributors?|resellers?|foundr(?:y|ies)|contract manufactur\w*|sole[- ]source|single[- ]source|"
    r"supply (?:agreements?|arrangements?)|purchase (?:commitments?|obligations?|agreements?)|strategic partners?|OEMs?|licensees?|licensors?)\b", re.I)
NOTE_TITLE_RE = re.compile(
    r"revenue|segment|concentration|customer|supplier|vendor|related[- ]part|commitment|purchase|geograph|significant accounting policies|"
    r"summary of accounting|collaborat|licens|major", re.I)


@dataclass
class _Heading:
    index: int
    key: object
    item: str


def _item_number(item):
    digits = re.match(r"\d+(?:\.\d+)?", item)
    return float(digits.group()) if digits else 0.0


def _headings(paragraphs, form):
    """Every paragraph that opens an Item, with its key: the item (10-Q: (part, item))."""
    found, part, last = [], None, 0.0
    for i, text in enumerate(paragraphs):
        if len(text) <= 200 and PART_RE.match(text) and not ITEM_RE.match(text):
            part, last = PART_RE.match(text).group(1).upper(), 0.0
            continue
        m = ITEM_RE.match(text) if len(text) <= 200 and "\n" not in text else None
        if not m:
            continue
        title = m.group("title").strip()
        if title and (not title[0].isupper() or len(title) > 150):  # "Item 7 of this report ..." is prose
            continue
        item = m.group("item").upper()
        if m.group("part"):
            part, last = m.group("part").upper(), 0.0
        number = _item_number(item)
        if part is None:
            part = "I"
        elif part == "I" and number < last and not m.group("part") and form == "10-Q":
            part = "II"  # no PART line, but the numbering started over
        last = number
        found.append(_Heading(i, (part, item) if form == "10-Q" else item, item))
    return found


def _runs(headings, total):
    """Consecutive headings with one key are one run (a page header repeating "Item 1A. Risk Factors" doesn't cut it in two).
    Returns {key: [(start, end)]}, end exclusive."""
    runs, k = {}, 0
    while k < len(headings):
        j = k
        while j + 1 < len(headings) and headings[j + 1].key == headings[k].key:
            j += 1
        end = headings[j + 1].index if j + 1 < len(headings) else total
        runs.setdefault(headings[k].key, []).append((headings[k].index, end))
        k = j + 1
    return runs


def _biggest(runs, paragraphs):
    """The run with the most text: the real item rather than its line in the table of contents."""
    return max(runs, key=lambda r: sum(len(p) for p in paragraphs[r[0] + 1:r[1]]) - r[0] * 1e-6)


def _passages(paragraphs, start, end):
    """Paragraphs naming customers, suppliers and the like, with the paragraph either side for context."""
    keep = set()
    for i in range(start, end):
        if RELATION_RE.search(paragraphs[i]):
            keep.update(j for j in (i - 1, i, i + 1) if start <= j < end)
    return sorted(keep)


def _note_blocks(paragraphs, start, stops):
    """[(title, [paragraph indexes])] for the notes after `start`. Headings are "Note 3 - Revenue"; failing that, numbered
    titles ("3. Revenue"). A note ends at the next note, a heading in `stops` or the signatures / exhibit list."""
    def candidates(regex):
        out = []
        for i in range(start, len(paragraphs)):
            text = paragraphs[i]
            m = regex.match(text) if len(text) <= 150 and "\n" not in text else None
            if m and not text.rstrip().endswith((".", ",", ";")):
                out.append((i, m.group("number").upper(), m.group("title").strip()))
        return out

    heads = candidates(NOTE_RE)
    if len({number for _, number, _ in heads}) < 2:
        heads = candidates(NUMBERED_RE)
        if len({number for _, number, _ in heads}) < 3:
            return []
    boundaries = sorted({i for i, _, _ in heads} | {i for i in stops if i >= start}
                        | {i for i in range(start, len(paragraphs)) if END_OF_NOTES_RE.match(paragraphs[i])})
    best = {}
    for i, number, title in heads:
        limit = next((b for b in boundaries if b > i), len(paragraphs))
        size = sum(len(p) for p in paragraphs[i + 1:limit])
        if number not in best or size > best[number][0]:  # the same number twice: a contents list and the note; the longer wins
            best[number] = (size, title, i, limit)
    return [(title, list(range(i, limit))) for _, title, i, limit in sorted(best.values(), key=lambda b: b[2])]


@finder("sec")
def sec_sections(paragraphs, form):
    spec = SEC_ITEMS.get(form)
    if spec is None:
        return None  # 6-K, 10-K/A ... : no structure to rely on
    headings = _headings(paragraphs, form)
    if not headings:
        return None
    runs = _runs(headings, len(paragraphs))
    best = {key: _biggest(r, paragraphs) for key, r in runs.items()}

    sections = []
    for key, (name, how) in spec.items():
        if key not in best:
            continue
        start, end = best[key]
        body = sum(len(p) for p in paragraphs[start + 1:end])
        if how == STATEMENTS:
            allowed = STATEMENT_ITEMS.get(form, set())
            region = min([best[k][0] for k in allowed if k in best] or [start])
            stops = [h.index for h in headings if h.key not in allowed]
            notes = _note_blocks(paragraphs, region, stops)
            blocks = [b for b in notes if NOTE_TITLE_RE.search(b[0])]
            if blocks:
                titles = "; ".join(title for title, _ in blocks)
                label = f"{name}, notes: {titles}"
                sections.append(Section(label if len(label) <= 200 else label[:197] + "...", [i for _, idx in blocks for i in idx]))
            elif not notes and body >= MIN_SECTION_CHARS:
                sections.append(Section(name, list(range(start, end))))  # no notes to pick from: keep what is there
        elif body < MIN_SECTION_CHARS:
            continue
        elif how == PASSAGES:
            kept = _passages(paragraphs, start, end)
            if kept:
                sections.append(Section(name, kept))
        else:
            sections.append(Section(name, list(range(start, end))))

    if sections or form == "8-K":
        return sections  # an 8-K about something else (results, a director leaving) has nothing for us
    return None


# ---------- Chunks ----------

@dataclass
class _Unit:
    number: int  # 1-based paragraph number in the cleaned text
    text: str
    tokens: int


_SENTENCE_END = re.compile(r"(?<=[.!?])[\"”’)]?\s+(?=[A-Z(\"“])")


def _sentences(text):
    pieces, last = [], 0
    for m in _SENTENCE_END.finditer(text):
        pieces.append(text[last:m.end()].rstrip())
        last = m.end()
    pieces.append(text[last:])
    return pieces


def split_text(text, limit, level=0):
    """Cuts text that is over `limit` tokens: at line breaks, then sentence ends, then spaces, and only if a single word is
    still too long, anywhere (a character is never more than a token in estimate_tokens)."""
    if estimate_tokens(text) <= limit:
        return [text]
    if level == 3:
        return [text[i:i + limit] for i in range(0, len(text), limit)]
    separator = "\n" if level == 0 else " "
    splitter = (lambda t: t.split("\n"), _sentences, lambda t: t.split(" "))[level]
    parts, current, size = [], [], 0

    def flush():
        nonlocal current, size
        if current:
            parts.append(separator.join(current))
        current, size = [], 0

    for piece in splitter(text):
        tokens = estimate_tokens(piece) + 1
        if tokens > limit:
            flush()
            parts.extend(split_text(piece, limit, level + 1))
        else:
            if current and size + tokens > limit:
                flush()
            current.append(piece)
            size += tokens
    flush()
    return parts


def _units(paragraphs, indexes, limit):
    units = []
    for i in indexes:
        for part in split_text(paragraphs[i], limit - 1):
            units.append(_Unit(i + 1, part, estimate_tokens(part) + 1))
    return units


def pack(units, limit, overlap):
    """[(units, overlap_count)]: units are added until the next would pass `limit`; a new chunk then starts with the last
    units of the previous one that fit in `overlap`."""
    chunks, current, size, repeated = [], [], 0, 0
    for unit in units:
        if current and size + unit.tokens > limit:
            chunks.append((current, repeated))
            tail, tail_size = [], 0
            for previous in reversed(current):
                if tail_size + previous.tokens > overlap or tail_size + previous.tokens + unit.tokens > limit:
                    break
                tail.insert(0, previous)
                tail_size += previous.tokens
            current, size, repeated = tail, tail_size, len(tail)
        current.append(unit)
        size += unit.tokens
    if current:
        chunks.append((current, repeated))
    return chunks


def _section_chunks(paragraphs, section, document, max_tokens, overlap_tokens):
    chunks = []
    for units, repeated in pack(_units(paragraphs, section.paragraphs, max_tokens), max_tokens, overlap_tokens):
        text = "\n\n".join(u.text for u in units)
        chunks.append(Chunk(document, section.name, text, estimate_tokens(text), units[0].number, units[-1].number, repeated))
    return chunks


def chunk_paragraphs(paragraphs, source="sec", form="", document="", max_tokens=MAX_CHUNK_TOKENS, overlap_tokens=OVERLAP_TOKENS):
    """The chunks of one document's paragraphs: the source's sections, or the whole text when it has none it can find."""
    chunks = []
    for section in find_sections(paragraphs, source, form):
        chunks.extend(_section_chunks(paragraphs, section, document, max_tokens, overlap_tokens))
    return chunks


def chunk_file(path, source="sec", form="", **limits):
    path = Path(path)
    return chunk_paragraphs(load_paragraphs(path), source, form, path.name, **limits)


EXHIBIT_FILE = re.compile(r"ex[-_]?10(?:[-_.]?(\d{1,2}))?(?!\d)", re.I)


def exhibit_label(filename):
    """"Exhibit 10.1" for ex10-1.htm / ex101.htm / a2026ex10_1.htm; None for files that aren't exhibit 10.x."""
    name = Path(filename).stem
    if "index" in name.lower() or Path(filename).suffix.lower() not in {".htm", ".html", ".txt"}:
        return None
    m = EXHIBIT_FILE.search(name)
    return f"Exhibit 10.{m.group(1)}" if m and m.group(1) else ("Exhibit 10" if m else None)


def chunk_filing(folder, form, primary_document, source="sec", max_tokens=MAX_CHUNK_TOKENS, overlap_tokens=OVERLAP_TOKENS):
    """The chunks of a downloaded filing (data/filings/<cik>/<accession>/): the main document by its sections and, for an
    8-K, every exhibit 10.x agreement in the folder as a whole. Chunks are numbered in order."""
    folder = Path(folder)
    chunks = chunk_file(folder / primary_document, source, form, max_tokens=max_tokens, overlap_tokens=overlap_tokens)
    if form == "8-K":
        for path in sorted(folder.iterdir()):
            label = exhibit_label(path.name)
            if label and path.name != primary_document:
                paragraphs = load_paragraphs(path)
                chunks.extend(_section_chunks(paragraphs, Section(label, list(range(len(paragraphs)))), path.name, max_tokens, overlap_tokens))
    for number, chunk in enumerate(chunks, 1):
        chunk.number = number
    return chunks
