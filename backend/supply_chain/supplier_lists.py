"""Published supplier lists (#132): the lists some companies publish of their own suppliers, read as tier 1 evidence.

Apple's Supplier List (the suppliers behind 98% of its direct spend on materials, manufacturing and assembly, with
where each makes things for Apple) and Dell's Public Supplier List (the supplier facilities behind at least 95% of its
spend, with each facility's address, products and supplier type) are tables in a PDF. No AI is needed to read them: the
text of each page is laid out as it is printed (pypdf's layout mode), the columns are found from the header row, and
each entry becomes one candidate link "supplier -> list owner".

What comes from where:
- seed/supplier_lists.json lists the sources: the list owner (name, ticker, market), the url, the parser, the month
  and day the owner's fiscal year ends, and notes. seed_lists() adds the owners to the graph (found by ticker, like
  the theme seed) and is safe to run again.
- The job "supplier_list" (key = the list's slug) downloads the url, and only when the file's SHA-256 is new does it
  register a document (source "supplier_list", kind "supplier list", external_id "<slug>/<first 16 hex of the hash>",
  period_end = stated_on = the end of the fiscal year the list covers, filed_at = the date it was published) and
  import the entries. schedule() queues each list at most once every CHECK_EVERY_DAYS: a list changes about once a
  year, so a weekly look is plenty.
- Each entry: the supplier name goes through the name resolver (#119). A name with a trailing bracket ("Hon Hai
  Precision Industry Company Limited (Foxconn)") is tried as printed, then without the bracket, then the bracket alone
  only when seed/aliases.json says it is a common name of one company (Foxconn = Hon Hai). A bracket naming a parent
  ("Unisteel Technology Limited (SFS Group)") is not followed: the parent is another company. A group entry ("X group
  companies", "X and its subsidiaries") is linked to X and says so in the locator. A name the resolver can't match is
  refused (rejected, unresolved_company). The one exception is a list that prints full legal names (seed
  "private_companies": true, Apple's): there a name that can be a private company (resolver.can_be_private: a plain
  no_match on a name that doesn't look listed, "Robert Bosch GmbH") becomes one, because the owner naming its own
  supplier in a published table is the confirmation the Verifier gives a Reader candidate. A list of short trade names
  (Dell's "Finisar", "GT", "TPT") never makes one: such a name is too little to say which company it is.
  The owner's own sites (Dell lists its own factories) are left out, and entries that name no company are refused
  (generic_counterparty).
- Evidence: tier 1, extractor supplier_list, quote = the entry as printed with its cells joined by " | " and its rows
  by " / ", locator = page and row, stated_on = the end of the fiscal year the list covers.

A supplier missing from a newer list is not ended (a list leaving a name out doesn't say the business stopped): its
link keeps the older evidence and turns stale by the merge rules once its newest statement is over 18 months old.
"""
import asyncio
import hashlib
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import sec_client
from supply_chain import graph, jobs, resolver
from supply_chain.db import now
from supply_chain.worker import Permanent, handler

SOURCE = "supplier_list"
KIND = "supplier list"
EXTRACTOR = "supplier_list"
JOB_KIND = "supplier_list"
SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "supplier_lists.json"
SEED_SOURCE = "supplier list seed"
CHECK_EVERY_DAYS = 7
PRIORITY = 55  # as the XBRL figures: free, structured, worth having before the AI reads
USER_AGENT = "Mozilla/5.0 (Macintosh; PortfolioManager)"  # no personal details: these sites ask for none
TIMEOUT_S = 60
MAX_BYTES = 40 * 1024 * 1024
RETRIES = 3
BACKOFF_S = 5  # urllib3 waits about 5, 10, 20 s between tries (or what Retry-After says)
RETRY_STATUS = (429, 500, 502, 503, 504)
GROUP_WORDS = re.compile(r"\s*(?:,?\s*(?:and|&)\s+(?:its\s+)?(?:affiliates|subsidiaries|affiliated companies)|\s+group\s+(?:of\s+)?companies)\s*$", re.I)
GENERIC = re.compile(r"^(?:various|others?|other suppliers?|confidential|undisclosed|n/?a|tbd|-+)$", re.I)
TRAILING_BRACKET = re.compile(r"^(?P<name>.*\S)\s*\((?P<inner>[^()]+)\)\s*$")


class ListUnavailable(Exception):
    """The list's site can't be reached or answered something we can't use (tried again later)."""


class ListNotFound(ListUnavailable):
    """The url has nothing (moved or taken down): needs a new url in the seed."""


# ---------- The seed ----------

def load_seed(path=None):
    return json.loads(Path(path or SEED_PATH).read_text(encoding="utf-8"))["lists"]


def validate(lists):
    """Problems in a seed (missing fields, a slug twice, an unknown parser, a url that isn't https); [] when fine."""
    problems, seen = [], set()
    for entry in lists:
        slug = entry.get("slug") or ""
        customer = entry.get("customer") or {}
        for field in ("slug", "title", "url", "parser", "fiscal_year_end"):
            if not str(entry.get(field) or "").strip():
                problems.append(f"{slug or entry}: needs {field}")
        if not all(str(customer.get(k) or "").strip() for k in ("name", "ticker", "market")):
            problems.append(f"{slug}: the customer needs name, ticker and market")
        if entry.get("parser") and entry["parser"] not in PARSERS:
            problems.append(f"{slug}: unknown parser {entry['parser']!r}")
        if not str(entry.get("url") or "").startswith("https://"):
            problems.append(f"{slug}: the url must be https")
        if not re.fullmatch(r"\d{2}-\d{2}", str(entry.get("fiscal_year_end") or "")):
            problems.append(f"{slug}: fiscal_year_end is MM-DD")
        if slug in seen:
            problems.append(f"{slug}: listed twice")
        seen.add(slug)
    return problems


def seed_lists(conn, lists=None):
    """Adds each list's owner to the graph (found by ticker + market, else created). Returns {slug: company id}."""
    lists = load_seed() if lists is None else lists
    problems = validate(lists)
    if problems:
        raise ValueError("; ".join(problems))
    owners = {}
    for entry in lists:
        customer = entry["customer"]
        company_id = graph.find_company(conn, "ticker", customer["ticker"], customer["market"])
        if company_id is None:
            company_id = graph.add_company(conn, customer["name"], country=customer.get("country"))
            graph.add_identifier(conn, company_id, "ticker", customer["ticker"], customer["market"], source=SEED_SOURCE)
        owners[entry["slug"]] = company_id
    return owners


def entry_for(slug, lists=None):
    return next((e for e in (load_seed() if lists is None else lists) if e["slug"] == slug), None)


# ---------- Reading the PDF ----------

def pdf_pages(content):
    """(page texts laid out as printed, the PDF's creation date as YYYY-MM-DD or None). pypdf's layout mode keeps each
    column at its place on the line and joins letters a plain extraction splits ("T echnology")."""
    from pypdf import PdfReader  # here: only the import job needs it
    reader = PdfReader(io.BytesIO(content))
    created = None
    try:
        stamp = reader.metadata.creation_date if reader.metadata else None
        created = stamp.date().isoformat() if stamp else None
    except (ValueError, TypeError, AttributeError):
        created = None
    return [page.extract_text(extraction_mode="layout") or "" for page in reader.pages], created


def segments(line):
    """The pieces of a laid-out line: [(column, text)]. Pieces are at least 3 spaces apart; inside one, runs of spaces
    are one space."""
    return [(m.start(), re.sub(r"\s+", " ", m.group())) for m in re.finditer(r"\S+(?:\s{1,2}\S+)*", line)]


def fiscal_year(pages):
    """The fiscal year the list says it covers ("... for fiscal year 2023", "during fiscal year 2025"), or None."""
    text = re.sub(r"\s+", " ", " ".join(pages[:2] + pages[-1:]))
    found = re.search(r"fiscal year (\d{4})", text, re.I)
    return int(found.group(1)) if found else None


def published_on(pages):
    """A "Published December 2025" footer -> "2025-12-01" (the month is all it says), or None."""
    found = re.search(r"Published\s+([A-Z][a-z]+)\s+(\d{4})", " ".join(pages))
    if not found:
        return None
    try:
        return datetime.strptime(f"{found.group(1)} {found.group(2)}", "%B %Y").date().isoformat()
    except ValueError:
        return None


def parse_apple(pages):
    """Apple's Supplier List: SUPPLIER NAME, then PRIMARY LOCATIONS WHERE MANUFACTURING FOR APPLE OCCURS in two columns
    (the places, the country). A supplier's first row holds its name; the rows below it, with the name cell empty, are
    more of its locations; a places cell too long for one line goes on in the next, under it. Returns the entries:
    [{name, page, row, locations: ["places, country", ...], quote ("name | places | country / places | country"),
    locator}]."""
    entries = []
    current = None
    for page_number, text in enumerate(pages, start=1):
        lines = text.splitlines()
        header = next((i for i, line in enumerate(lines) if "SUPPLIER NAME" in line and "PRIMARY LOCATIONS" in line), None)
        if header is None:
            continue
        places_at = lines[header].index("PRIMARY LOCATIONS")
        row = 0
        for line in lines[header + 1:]:
            parts = segments(line)
            if not parts:
                continue
            if parts[0][1].startswith(("*", "©")):
                break  # the footnote below the table
            name = [text for at, text in parts if at < places_at - 8]
            rest = [(at, text) for at, text in parts if at >= places_at - 8]
            if name and not rest and current is not None and current["page"] == page_number and current["_last_was_name"]:
                current["name"] = f"{current['name']} {' '.join(name)}"  # a name too long for one line
                continue
            if name:
                row += 1
                current = {"name": " ".join(name), "page": page_number, "row": row, "locations": [], "_last_was_name": not rest}
                entries.append(current)
            elif current is None:
                continue  # locations before any supplier: not part of the table
            current["_last_was_name"] = bool(name) and not rest
            if len(rest) >= 2:
                current["locations"].append([" ".join(t for _, t in rest[:-1]), rest[-1][1]])
            elif len(rest) == 1:
                at, piece = rest[0]
                if abs(at - places_at) <= 8 and current["locations"] and not name:
                    current["locations"][-1][0] = f"{current['locations'][-1][0]} {piece}"  # places that ran onto a second line
                elif abs(at - places_at) <= 8:
                    current["locations"].append([piece, ""])
                else:
                    current["locations"].append(["", piece])
    entries = [e for e in entries if e["locations"]]  # every supplier says where: a line with none is text below the table
    for entry in entries:
        entry.pop("_last_was_name", None)
        rows =[" | ".join(p for p in pair if p) for pair in entry["locations"]]
        entry["locations"] = [", ".join(p for p in pair if p) for pair in entry["locations"]]
        entry["quote"] = " | ".join([entry["name"], " / ".join(rows)]) if rows else entry["name"]
        entry["locator"] = f"page {entry['page']}, row {entry['row']}"
    return entries


DELL_COLUMNS = ("name", "address", "category", "supplier_type", "site")
DELL_HEADINGS = {"category": ("DELL PRODUCTS", "PROCUREMENT CATEGORY"), "supplier_type": ("SUPPLIER TYPE",),
                 "site": ("SUSTAINABILITY", "SITE"), "gri": ("GRI",)}
DELL_MARGIN = 6  # a centred value may start this many characters left of its column's heading


def dell_edges(header_lines):
    """Where the columns right of the address start on a page, from its two heading lines: {column: first character}."""
    edges = {}
    for column, words in DELL_HEADINGS.items():
        starts = [line.find(word) for line in header_lines for word in words if line.find(word) >= 0]
        if not starts:
            return None
        edges[column] = min(starts) - DELL_MARGIN
    return edges


def dell_column(at, piece, edges, name_centre, address_centre):
    """The column a piece starting at `at` is in. Right of the address, the columns start where their headings do; the
    address is wide and wraps unevenly, so anything between the name and the products column is address, except a piece
    centred nearer the supplier name (a name too long for one line)."""
    for column in ("gri", "site", "supplier_type", "category"):
        if at >= edges[column]:
            return column
    middle = at + len(piece) / 2
    return "name" if abs(middle - name_centre) < abs(middle - address_centre) else "address"


def parse_dell(pages):
    """Dell's Public Supplier List: one row per supplier facility, CORPORATE PROFILE (the supplier) | ADDRESS | DELL
    PRODUCTS / PROCUREMENT CATEGORY | SUPPLIER TYPE | SUSTAINABILITY SITE | GRI (Yes / No). Cells are centred and run
    over several lines, so a facility starts at a line whose last piece is the GRI answer and every piece goes to the
    column it sits in (dell_column). Returns one entry per facility:
    [{name, page, row, address, category, supplier_type, site, quote, locator}]."""
    entries = []
    current = None
    for page_number, text in enumerate(pages, start=1):
        lines = text.splitlines()
        header = next((i for i, line in enumerate(lines) if "CORPORATE" in line and "ADDRESS" in line), None)
        edges = dell_edges(lines[header:header + 2]) if header is not None else None
        if edges is None:
            continue
        row = 0
        for line in lines[header + 2:]:
            parts = segments(line)
            if not parts or "Public Supplier List |" in line:
                continue
            if len(parts) >= 3 and parts[-1][1] in ("Yes", "No") and parts[-1][0] >= edges["gri"]:
                row += 1
                (name_at, name), (address_at, address) = parts[0], parts[1]
                current = {"page": page_number, "row": row, "cells": {c: [] for c in DELL_COLUMNS},
                           "centres": (name_at + len(name) / 2, address_at + len(address) / 2)}
                entries.append(current)
            elif current is None:
                continue
            for at, piece in parts:
                column = dell_column(at, piece, edges, *current["centres"])
                if column != "gri":
                    current["cells"][column].append(piece)
    for entry in entries:
        cells = entry.pop("cells")
        entry.pop("centres")
        entry.update({column: _join(cells[column], ", " if column == "category" else " ") for column in DELL_COLUMNS})
        entry["quote"] = " | ".join(entry[k] for k in ("name", "address", "category", "supplier_type") if entry[k])
        entry["locator"] = f"page {entry['page']}, row {entry['row']}"
    return entries


def _join(pieces, separator=" "):
    """A cell's pieces as one line of text, with no space left before a comma or full stop."""
    text = separator.join(p.strip() for p in pieces if p.strip())
    return re.sub(r"\s+([,.;)])", r"\1", re.sub(r"\s+", " ", text)).strip()


PARSERS = {"apple_pdf": parse_apple, "dell_pdf": parse_dell}


# ---------- Downloading ----------

def _session():
    """requests with urllib3's Retry: a busy site (429, 5xx) or a dropped connection is tried again after a growing wait,
    honouring Retry-After."""
    session = requests.Session()
    retry = Retry(total=RETRIES, backoff_factor=BACKOFF_S, status_forcelist=RETRY_STATUS, allowed_methods={"GET"},
                  respect_retry_after_header=True)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = USER_AGENT
    return session


def _download(url):
    """One blocking download of a list's url (at most MAX_BYTES)."""
    try:
        with _session().get(url, timeout=TIMEOUT_S, stream=True) as response:
            if response.status_code in (404, 410):
                raise ListNotFound(f"nothing at {url} any more ({response.status_code})")
            if response.status_code != 200:
                raise ListUnavailable(f"the site answered {response.status_code}")
            body = response.raw.read(MAX_BYTES + 1, decode_content=True)
    except requests.RequestException as exc:
        raise ListUnavailable(f"the site didn't answer ({exc.__class__.__name__})") from exc
    if len(body) > MAX_BYTES:
        raise ListUnavailable("The list is too large to download.")
    return body


async def fetch(url):
    """The file at a list's url, as bytes. Lists are checked weekly, so no spacing between requests is needed."""
    return await asyncio.to_thread(_download, url)


def save(slug, content, folder=None):
    """Writes the file to data/filings/supplier_list/<slug>/<hash>.pdf (whole or not at all): {path, sha256, size}."""
    digest = hashlib.sha256(content).hexdigest()
    target = Path(folder or sec_client.filings_dir() / SOURCE / sec_client.safe_name(slug)) / f"{digest[:16]}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(content)
    partial.replace(target)
    return {"path": str(target), "sha256": digest, "size": len(content)}


# ---------- Names ----------

def name_plan(name):
    """How an entry's name is looked up: {"names": the names to try in order, "private_name": the one a private company
    would be made from, "note": what the locator adds, "generic": True for an entry that names no company}."""
    name = " ".join(str(name or "").split())
    if not name or GENERIC.match(name) or resolver.is_unnamed(name):
        return {"names": [], "private_name": None, "note": None, "generic": True}
    note = None
    if GROUP_WORDS.search(name):  # "Foxconn group companies": the group's parent is the company we can link
        name, note = GROUP_WORDS.sub("", name).strip(" ,"), "listed as a group of companies"
    names = [name]
    bracket = TRAILING_BRACKET.match(name)
    if bracket:
        names.append(bracket.group("name"))
        inner = bracket.group("inner").strip()
        alias = resolver.alias_entries().get(resolver.name_key(inner))
        if alias and not alias.get("private"):
            names.append(inner)  # "(Foxconn)": a common name of one company, per seed/aliases.json
    return {"names": names, "private_name": names[1] if bracket else names[0], "note": note, "generic": False}


async def resolve_entry(conn, name, resolve, allow_private):
    """{status matched / skipped, company_id, how, reason, detail, note} for one entry's name."""
    plan = name_plan(name)
    if plan["generic"]:
        return {"status": "skipped", "company_id": None, "how": None, "reason": "generic", "detail": "the entry names no company", "note": None}
    tried = {}
    for candidate in dict.fromkeys(plan["names"]):
        match = await resolve(conn, candidate)
        if match["status"] == "unavailable":
            raise RuntimeError(f"name lookup unavailable for {candidate}: {match.get('detail')}")  # the job is tried again later
        if match["status"] == "matched":
            return {**match, "how": match["method"], "note": plan["note"]}
        tried[candidate] = match
    last = tried.get(plan["private_name"]) or next(iter(tried.values()))
    if allow_private and resolver.can_be_private(plan["private_name"], last):
        company_id = resolver.private_company(conn, plan["private_name"], method="supplier_list_private")
        return {"status": "matched", "company_id": company_id, "how": "supplier_list_private", "reason": None, "detail": None,
                "note": plan["note"]}
    return {**last, "how": None, "note": plan["note"]}


# ---------- Writing to the graph ----------

async def import_entries(conn, customer_id, document_id, entries, stated_on, allow_private=False, resolve=None):
    """Writes the entries as "supplier -> customer" links with tier 1 evidence. Returns one result per entry: {entry,
    status (linked / rejected / left_out), reason, how, relationship_id, supplier_id}. Each distinct name is looked up
    once and refused once (with its first entry as the quote)."""
    resolve = resolve or resolver.resolve
    customer = graph.current_company(conn, customer_id)
    customer_name = conn.execute("SELECT name FROM companies WHERE id = ?", (customer,)).fetchone()["name"]
    looked_up, refused, results = {}, set(), []
    for entry in entries:
        name = entry["name"]
        if name not in looked_up:
            looked_up[name] = await resolve_entry(conn, name, resolve, allow_private)
        match = looked_up[name]
        base = {"entry": entry, "how": match.get("how"), "relationship_id": None, "supplier_id": None}
        if match["status"] == "matched" and graph.current_company(conn, match["company_id"]) == customer:
            results.append({**base, "status": "left_out", "reason": "list_owner"})  # the owner's own sites (Dell's factories)
            continue
        if match["status"] != "matched":
            reason = "generic_counterparty" if match.get("reason") == "generic" else "unresolved_company"
            if name not in refused:
                graph.reject(conn, document_id, entry["quote"], reason, "rule", supplier_name=name, customer_name=customer_name,
                             customer_id=customer, detail=f"{match.get('reason') or ''}: {match.get('detail') or ''}".strip(": "))
                refused.add(name)
            results.append({**base, "status": "rejected", "reason": match.get("reason")})
            continue
        locator = entry["locator"] + (f"; {match['note']}" if match.get("note") else "")
        evidence = {"document_id": document_id, "quote": entry["quote"], "tier": 1, "extractor": EXTRACTOR, "locator": locator,
                    "stated_on": stated_on}
        relationship_id = graph.add_relationship(conn, match["company_id"], customer, evidence)  # merge.refresh sets the rest
        results.append({**base, "status": "linked", "reason": None, "relationship_id": relationship_id, "supplier_id": match["company_id"]})
    return results


def summarise(results):
    """{entries, suppliers (distinct names), linked (entries), linked_suppliers (companies), rejected {reason: names},
    left_out (names), private (companies made private)}."""
    linked = [r for r in results if r["status"] == "linked"]
    rejected = {}
    for r in results:
        if r["status"] == "rejected":
            rejected.setdefault(r["reason"] or "unknown", set()).add(r["entry"]["name"])
    return {"entries": len(results), "suppliers": len({r["entry"]["name"] for r in results}), "linked": len(linked),
            "linked_suppliers": len({r["supplier_id"] for r in linked}),
            "rejected": {reason: len(names) for reason, names in sorted(rejected.items())},
            "left_out": len({r["entry"]["name"] for r in results if r["status"] == "left_out"}),
            "private": len({r["supplier_id"] for r in linked if r["how"] == "supplier_list_private"})}


def read_list(source, content):
    """(entries, fiscal year, published date) from a downloaded list; raises Permanent when it can't be read."""
    from pypdf.errors import PdfReadError
    try:
        pages, created = pdf_pages(content)
    except PdfReadError as exc:
        raise Permanent(f"{source['title']} isn't a readable PDF: {exc}") from exc
    entries = PARSERS[source["parser"]](pages)
    if not entries:
        raise Permanent(f"no entries found in {source['title']}: the layout may have changed")
    year = fiscal_year(pages)
    if year is None:
        raise Permanent(f"{source['title']} doesn't say which fiscal year it covers")
    return entries, year, published_on(pages) or created


async def import_list(conn, source, customer_id, content, resolve=None, folder=None):
    """Registers a downloaded list as a document and imports it. Returns {document_id, fiscal_year, results, unchanged}.
    A file imported before (the same SHA-256) is not read again."""
    digest = hashlib.sha256(content).hexdigest()
    seen = conn.execute("SELECT id, period_end FROM documents WHERE source = ? AND content_hash = ? AND status = 'processed'",
                        (SOURCE, digest)).fetchone()
    if seen:
        return {"document_id": seen["id"], "fiscal_year": int(seen["period_end"][:4]), "results": [], "unchanged": True}
    if not content.startswith(b"%PDF"):
        raise Permanent(f"{source['url']} no longer gives a PDF (moved?): update seed/supplier_lists.json")
    entries, year, published = await asyncio.to_thread(read_list, source, content)
    stated_on = f"{year}-{source['fiscal_year_end']}"
    saved = save(source["slug"], content, folder)
    document_id = graph.add_document(
        conn, SOURCE, KIND, f"{source['slug']}/{digest[:16]}", source["url"], company_id=customer_id,
        title=f"{source['title']} FY{year}", filed_at=published, period_end=stated_on, language="en",
        content_hash=digest, size_bytes=saved["size"], local_path=saved["path"], fetched_at=now(), status="downloaded")
    results = await import_entries(conn, customer_id, document_id, entries, stated_on, source.get("private_companies", False), resolve)
    conn.execute("UPDATE documents SET status = 'processed' WHERE id = ?", (document_id,))
    return {"document_id": document_id, "fiscal_year": year, "results": results, "unchanged": False}


@handler(JOB_KIND)
async def supplier_list_job(job, conn):
    source = entry_for(job["key"])
    if source is None:
        raise Permanent(f"no supplier list {job['key']!r} in seed/supplier_lists.json")
    customer_id = seed_lists(conn, [source])[source["slug"]]
    try:
        content = await fetch(source["url"])
    except ListNotFound as exc:
        raise Permanent(str(exc)) from exc
    outcome = await import_list(conn, source, customer_id, content)
    if outcome["unchanged"]:
        return {"notes": f"FY{outcome['fiscal_year']} unchanged"}
    s = summarise(outcome["results"])
    rejected = sum(s["rejected"].values())
    return {"notes": f"FY{outcome['fiscal_year']}: {s['linked_suppliers']} suppliers linked, {rejected} unresolved"
                     + (f", {s['left_out']} own sites left out" if s["left_out"] else "")}


# ---------- Scheduling ----------

def schedule(conn, now=None, every_days=CHECK_EVERY_DAYS, lists=None):
    """Queues a check of each list not looked at within `every_days` (and not queued now). Returns how many."""
    lists = load_seed() if lists is None else lists
    owners = seed_lists(conn, lists)
    cutoff = jobs._iso((now or datetime.now(timezone.utc)) - timedelta(days=every_days))
    queued = 0
    for source in lists:
        recent = conn.execute("SELECT 1 FROM jobs WHERE kind = ? AND key = ? AND (status IN ('queued', 'running') OR created_at > ?)",
                              (JOB_KIND, source["slug"], cutoff)).fetchone()
        if recent:
            continue
        jobs.enqueue(conn, JOB_KIND, source["slug"], {"slug": source["slug"], "form": KIND}, priority=PRIORITY,
                     company_id=owners[source["slug"]], now=now)
        queued += 1
    return queued
