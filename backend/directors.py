"""Boards of directors (#113), read from each company's own document by Claude.

US stocks: the proxy statement (DEF 14A) on SEC EDGAR. ASX stocks: the annual report, fetched in
the user's app only, after they accept ASX's terms (personal use; see directors_sources.py).
The passages about the board go to config.DIRECTORS_MODEL with a fixed answer shape. Every name
must appear in the document and every quote must be found in it, or that director is dropped.
Each seat keeps the document's link and the page or part it came from.

Stored in directors.sqlite: documents (one per company: where it came from, when, status, any newer
document found since), seats (one per director per company). A bundled seed (seed/directors.json,
US index members only) is merged in at startup; `python directors.py --seed` rebuilds it.

People: a seat's Wikidata ID comes from the people Wikidata links to that company (people.py);
"also on BHP's board" is worked out when a board is read (also_on).
"""
import asyncio
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic

import config
import directors_sources as sources
import people
import usage_store
from config import DATA_DIR
from secrets_guard import mask_secrets

DB_PATH = DATA_DIR / "directors.sqlite"
SEED_PATH = Path(__file__).resolve().parent / "seed" / "directors.json"
MAX_TOKENS = 16000
TIMEOUT_S = 120
ROLES = ("chair", "deputy_chair", "lead_independent_director", "managing_director_ceo", "executive_director", "director")
# Checking for a newer document (no AI): once a week per company
CHECK_EVERY = timedelta(days=7)
# Documents tried for one company when the newest has no directors (a special meeting's proxy)
MAX_DOCUMENTS = 3

SYSTEM_PROMPT = """You read one company's proxy statement or annual report and list its board of \
directors: the people who are directors now, or are standing for election at the next meeting.

Rules:
- Only people the document says are (or are nominated to be) directors of this company. Not
  executives who aren't directors, not the company secretary, not former directors who have left.
- name: the full first and last name as the document writes it in the director's own biography or
  nomination, without "Mr", "Ms", "Dr" and without degrees. Never just a surname.
- role: chair, deputy_chair, lead_independent_director, managing_director_ceo (the CEO or managing
  director who is also on the board), executive_director (another executive on the board), or director.
- independent: true or false only if the document says so, else null.
- leaving: true if the document says they are retiring or not standing for re-election.
- appointed_year: the year they joined this board, if given ("Director since 2019"), else null.
- age: only if the document gives it, else null.
- committees: the board committees they sit on, as named in the document.
- other_boards: their other current company boards as the document lists them, e.g.
  "BHP Group Limited (Chair)". Empty if none are listed.
- location: the label of the page or part the details are on ("Page 87"), exactly as given.
- quote: a short exact quote (under 20 words) from that page or part that names them as a director.
Copy facts from the document only. Never add anything from your own knowledge."""


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            market TEXT NOT NULL, symbol TEXT NOT NULL, company_name TEXT,
            status TEXT NOT NULL,          -- ready | no_document | unreadable | error
            source TEXT, kind TEXT, title TEXT, url TEXT, pdf_url TEXT, filed TEXT, cik INTEGER,
            error TEXT, model TEXT, extracted_at TEXT, checked_at TEXT,
            newer_title TEXT, newer_url TEXT, newer_filed TEXT,
            PRIMARY KEY (market, symbol));
        CREATE TABLE IF NOT EXISTS seats (
            market TEXT NOT NULL, symbol TEXT NOT NULL, name TEXT NOT NULL, match_key TEXT,
            role TEXT, independent INTEGER, leaving INTEGER, appointed_year INTEGER, age INTEGER,
            committees TEXT, other_boards TEXT, location TEXT, quote TEXT,
            wikidata_id TEXT, wikipedia_url TEXT);
        CREATE INDEX IF NOT EXISTS seats_company ON seats (market, symbol);
        CREATE INDEX IF NOT EXISTS seats_key ON seats (match_key);
        CREATE INDEX IF NOT EXISTS seats_wikidata ON seats (wikidata_id);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- ASX's terms (personal use, accepted by the user) ----------

def asx_terms_accepted():
    with _connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'asx_terms_accepted_at'").fetchone()
    return row["value"] if row else None


def accept_asx_terms(accepted):
    with _connect() as conn:
        if accepted:
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('asx_terms_accepted_at', ?)", (_now(),))
        else:
            conn.execute("DELETE FROM meta WHERE key = 'asx_terms_accepted_at'")
    return asx_terms_accepted()


# ---------- The answer shape and the checks ----------

def build_schema(locations):
    nullable_int = {"type": ["integer", "null"]}
    return {
        "type": "object",
        "properties": {
            "directors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "role": {"type": "string", "enum": list(ROLES)},
                        "independent": {"type": ["boolean", "null"]},
                        "leaving": {"type": "boolean"},
                        "appointed_year": nullable_int,
                        "age": nullable_int,
                        "committees": {"type": "array", "items": {"type": "string"}},
                        "other_boards": {"type": "array", "items": {"type": "string"}},
                        "location": {"type": "string", "enum": list(locations)},
                        "quote": {"type": "string"},
                    },
                    "required": ["name", "role", "independent", "leaving", "appointed_year", "age",
                                 "committees", "other_boards", "location", "quote"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["directors"],
        "additionalProperties": False,
    }


def user_message(company_name, document, passages):
    parts = [f"Company: {company_name}", f"Document: {document['title']}", ""]
    for label, text in passages:
        parts += [f"[[{label}]]", text, ""]
    return "\n".join(parts)


def _plain(text):
    """Lower case letters and digits only, for comparing with the document. Apostrophes are removed
    (not spaced) so "O'Malley", "O’Malley" and people.match_key's "omalley" all agree."""
    text = re.sub(r"['‘’`´]", "", str(text or ""))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", people._ascii(text).lower()).split())


def clean_directors(answer, passages, now_year):
    """The directors that pass the checks, and a warning for each one dropped or corrected."""
    texts = {label: _plain(text) for label, text in passages}
    everything = " ".join(texts.values())
    kept, warnings, seen = [], [], set()
    for entry in answer.get("directors", []):
        name = " ".join(str(entry.get("name") or "").split())
        parts = people.name_parts(name)
        if not parts:
            warnings.append(f"Dropped a director without a full name: {name!r}")
            continue
        first, last = _plain(parts[0]), _plain(parts[1])
        # The surname, and the first name (or its initial right before the surname: "J. Smith")
        named = (f" {last} " in f" {everything} "
                 and (f" {first} " in f" {everything} " or re.search(rf"\b{first[:1]}\w* (?:\w+ )?{re.escape(last)}\b", everything)))
        if not named:
            warnings.append(f"Dropped {name}: the name isn't in the document")
            continue
        key = people.match_key(name)
        if key in seen:
            continue
        seen.add(key)
        location = entry.get("location") if entry.get("location") in texts else None
        quote = " ".join(str(entry.get("quote") or "").split())[:300] or None
        if quote and _plain(quote) not in (texts.get(location) or everything):
            warnings.append(f"Removed a quote for {name} that isn't in the document")
            quote = None
        year = entry.get("appointed_year")
        age = entry.get("age")
        kept.append({
            "name": name, "match_key": key,
            "role": entry.get("role") if entry.get("role") in ROLES else "director",
            "independent": entry.get("independent") if isinstance(entry.get("independent"), bool) else None,
            "leaving": bool(entry.get("leaving")),
            "appointed_year": year if isinstance(year, int) and 1900 <= year <= now_year else None,
            "age": age if isinstance(age, int) and 25 <= age <= 105 else None,
            "committees": [" ".join(str(c).split()) for c in entry.get("committees") or [] if str(c).strip()][:12],
            "other_boards": [" ".join(str(b).split()) for b in entry.get("other_boards") or [] if str(b).strip()][:15],
            "location": location, "quote": quote,
        })
    return kept, warnings


def add_wikidata(seats, candidates):
    """Wikidata IDs and Wikipedia links for the seats that match one of the company's Wikidata people."""
    for seat in seats:
        match = people.wikidata_match(seat["name"], candidates)
        seat["wikidata_id"] = match["id"] if match else None
        seat["wikipedia_url"] = match["article"] if match else None
    return seats


async def extract(company_name, document, passages, client, con_id=None):
    """Ask Claude for the board; returns (seats, warnings). Logs usage. Raises on API errors."""
    labels = [label for label, _ in passages]
    response = await client.messages.create(
        model=config.DIRECTORS_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message(company_name, document, passages)}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": build_schema(labels)}},
    )
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    ok = response.stop_reason == "end_turn"
    await asyncio.to_thread(usage_store.record, "directors", config.DIRECTORS_MODEL, usage, con_id,
                            "ok" if ok else response.stop_reason)
    if not ok:
        raise RuntimeError(f"stopped early ({response.stop_reason})")
    text = next(b.text for b in response.content if b.type == "text")
    return clean_directors(json.loads(text), passages, datetime.now().year)


# ---------- Store ----------

def save(market, symbol, document, seats=None, status="ready", error=None, model=None):
    """Replaces the company's document row and seats."""
    with _connect() as conn:
        conn.execute("DELETE FROM seats WHERE market = ? AND symbol = ?", (market, symbol))
        conn.execute(
            """INSERT OR REPLACE INTO documents (market, symbol, company_name, status, source, kind, title, url,
               pdf_url, filed, cik, error, model, extracted_at, checked_at, newer_title, newer_url, newer_filed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)""",
            (market, symbol, document.get("company_name"), status, document.get("source"), document.get("kind"),
             document.get("title"), document.get("url"), document.get("pdf_url"), document.get("filed"),
             document.get("cik"), error, model, _now() if status == "ready" else None, _now()))
        for seat in seats or []:
            conn.execute(
                """INSERT INTO seats (market, symbol, name, match_key, role, independent, leaving, appointed_year,
                   age, committees, other_boards, location, quote, wikidata_id, wikipedia_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (market, symbol, seat["name"], seat["match_key"], seat["role"], seat["independent"],
                 int(seat["leaving"]), seat["appointed_year"], seat["age"], json.dumps(seat["committees"]),
                 json.dumps(seat["other_boards"]), seat["location"], seat["quote"],
                 seat.get("wikidata_id"), seat.get("wikipedia_url")))


def _seat(row):
    seat = dict(row)
    seat["committees"] = json.loads(seat["committees"] or "[]")
    seat["other_boards"] = json.loads(seat["other_boards"] or "[]")
    seat["leaving"] = bool(seat["leaving"])
    seat["independent"] = None if seat["independent"] is None else bool(seat["independent"])
    return seat


def link_for(document, location):
    """The document's address, at the page for a PDF ("#page=87")."""
    url = document.get("pdf_url") or document.get("url")
    page = re.fullmatch(r"Page (\d+)", location or "")
    if url and page and document.get("pdf_url"):
        return f"{url}#page={page.group(1)}"
    return url


def also_on(seat, market, symbol, company_name, conn):
    """Other boards this person sits on among the companies read so far: (links, possible)."""
    rows = conn.execute(
        """SELECT s.*, d.company_name FROM seats s JOIN documents d ON d.market = s.market AND d.symbol = s.symbol
           WHERE NOT (s.market = ? AND s.symbol = ?) AND (s.match_key = ? OR (s.wikidata_id IS NOT NULL AND s.wikidata_id = ?))""",
        (market, symbol, seat["match_key"], seat.get("wikidata_id"))).fetchall()
    links, possible = [], []
    for row in rows:
        other = _seat(row)
        basis = people.link_basis(seat, other, company_name, row["company_name"])
        entry = {"market": row["market"], "symbol": row["symbol"], "company_name": row["company_name"],
                 "role": other["role"], "basis": basis}
        if basis in ("wikidata", "named_in_document"):
            links.append(entry)
        elif basis == "name_only":
            possible.append(entry)
    return links, possible


def board(market, symbol):
    """The stored board for a company, or None if it hasn't been read."""
    with _connect() as conn:
        doc = conn.execute("SELECT * FROM documents WHERE market = ? AND symbol = ?", (market, symbol)).fetchone()
        if doc is None:
            return None
        document = dict(doc)
        directors = []
        rows = conn.execute("SELECT * FROM seats WHERE market = ? AND symbol = ? ORDER BY rowid", (market, symbol))
        for row in rows.fetchall():
            seat = _seat(row)
            links, possible = also_on(seat, market, symbol, document["company_name"], conn)
            directors.append({
                **{k: seat[k] for k in ("name", "role", "independent", "leaving", "appointed_year", "age",
                                        "committees", "other_boards", "location", "quote", "wikidata_id",
                                        "wikipedia_url")},
                "person_id": seat["wikidata_id"] or f"{market}:{symbol}:{seat['match_key']}",
                "document_url": link_for(document, seat["location"]),
                "also_on": links, "possible_matches": possible,
            })
    newer = ({"title": document["newer_title"], "url": document["newer_url"], "filed": document["newer_filed"]}
             if document["newer_url"] else None)
    return {
        "status": document["status"], "error": document["error"],
        "document": {k: document[k] for k in ("source", "kind", "title", "url", "pdf_url", "filed")},
        "company_name": document["company_name"], "model": document["model"],
        "extracted_at": document["extracted_at"], "newer_document": newer, "directors": directors,
    }


def person(person_id):
    """Every seat for a person: by Wikidata ID, or one company's seat by its local ID (market:symbol:key)."""
    with _connect() as conn:
        if re.fullmatch(r"Q\d+", person_id):
            rows = conn.execute("SELECT s.*, d.company_name FROM seats s JOIN documents d USING (market, symbol) "
                                "WHERE s.wikidata_id = ?", (person_id,)).fetchall()
        else:
            market, symbol, key = (person_id.split(":", 2) + ["", ""])[:3]
            rows = conn.execute("SELECT s.*, d.company_name FROM seats s JOIN documents d USING (market, symbol) "
                                "WHERE s.market = ? AND s.symbol = ? AND s.match_key = ?", (market, symbol, key)).fetchall()
            if rows:
                seat = _seat(rows[0])
                links, _ = also_on(seat, market, symbol, rows[0]["company_name"], conn)
                more = [conn.execute("SELECT s.*, d.company_name FROM seats s JOIN documents d USING (market, symbol) "
                                     "WHERE s.market = ? AND s.symbol = ? AND s.match_key = ?",
                                     (link["market"], link["symbol"], key)).fetchone() for link in links]
                rows = list(rows) + [r for r in more if r]
    if not rows:
        return None
    first = _seat(rows[0])
    return {"person_id": person_id, "name": first["name"], "wikidata_id": first["wikidata_id"],
            "wikipedia_url": next((r["wikipedia_url"] for r in rows if r["wikipedia_url"]), None),
            "seats": [{"market": r["market"], "symbol": r["symbol"], "company_name": r["company_name"],
                       "role": r["role"], "leaving": bool(r["leaving"])} for r in rows]}


# ---------- Reading a company's board (find the document, trim, extract, save) ----------

_locks = {}


def can_read(market):
    """What's missing before a board can be read: [] or a list of "api_key", "sec_contact_email", "asx_terms"."""
    needs = [] if config.anthropic_api_key() else ["api_key"]
    if market == "US" and not config.sec_contact_email():
        needs.append("sec_contact_email")
    if market == "ASX" and not asx_terms_accepted():
        needs.append("asx_terms")
    if market not in ("US", "ASX"):
        needs.append("unsupported_market")
    return needs


async def find_documents(market, symbol):
    """The company's recent documents, newest first (ASX: just the latest annual report)."""
    if market == "US":
        return await sources.sec_documents(symbol)
    return [await sources.latest_asx_report(symbol)]


async def find_document(market, symbol):
    return (await find_documents(market, symbol))[0]


async def read_document(document):
    """(document with pdf_url when it's a PDF, the passages about the board)."""
    if document["source"] == "asx":
        pdf_url, data = await sources.asx_pdf(document)
        document = {**document, "pdf_url": pdf_url}
        sections = await asyncio.to_thread(sources.pdf_sections, data)
    else:
        data = await sources.sec_get(document["url"])
        sections = await asyncio.to_thread(sources.html_sections, data.decode("utf-8", "ignore"))
    passages = sources.select_passages(sections)
    if not passages:
        raise sources.Unreadable("No part of the document is about the board.")
    return document, passages


async def read_board(market, symbol, company_name, con_id=None, client=None):
    """Finds, reads and saves a company's board; returns board(). One at a time per company."""
    async with _locks.setdefault((market, symbol), asyncio.Lock()):
        document = {"company_name": company_name}
        try:
            candidates = await find_documents(market, symbol)
            client = client or anthropic.AsyncAnthropic(api_key=config.anthropic_api_key(), timeout=TIMEOUT_S)
            seats, warnings = [], []
            # The newest document first; a proxy for a special meeting has no directors to list, so the
            # next one is tried (up to three: each is one call, a fraction of a cent)
            for candidate in candidates[:MAX_DOCUMENTS]:
                document = {**candidate, "company_name": company_name}
                read, passages = await read_document(document)
                document = {**read, "company_name": company_name}
                seats, warnings = await extract(company_name, document, passages, client, con_id)
                if seats:
                    break
            if not seats:
                raise sources.Unreadable("No directors were found in the document.")
            candidates = await sources.wikidata_people(market, symbol, document.get("cik"))
            add_wikidata(seats, candidates)
            for warning in warnings:
                print(f"Directors {market}:{symbol}: {warning}")
            await asyncio.to_thread(save, market, symbol, document, seats, "ready", None, config.DIRECTORS_MODEL)
        except sources.NoDocument as exc:
            await asyncio.to_thread(save, market, symbol, document, None, "no_document", str(exc))
        except sources.Unreadable as exc:
            await asyncio.to_thread(save, market, symbol, document, None, "unreadable", str(exc))
        except sources.SourceUnavailable:
            raise  # nothing learnt about the company: don't overwrite a stored board
        except Exception as exc:
            message = f"{exc.__class__.__name__}: {mask_secrets(exc)}"
            print(f"Directors {market}:{symbol} failed: {message}")
            raise
        return board(market, symbol)


# ---------- Newer documents (no AI) ----------

def companies_to_check(now):
    with _connect() as conn:
        rows = conn.execute("SELECT market, symbol, url, checked_at FROM documents WHERE status = 'ready'").fetchall()
    due = []
    for row in rows:
        checked = datetime.fromisoformat(row["checked_at"]) if row["checked_at"] else None
        if checked is None or now - checked >= CHECK_EVERY:
            due.append(dict(row))
    return due


def mark_checked(market, symbol, newer, now):
    with _connect() as conn:
        conn.execute("UPDATE documents SET checked_at = ?, newer_title = ?, newer_url = ?, newer_filed = ? "
                     "WHERE market = ? AND symbol = ?",
                     (now.isoformat(timespec="seconds"), newer and newer["title"], newer and newer["url"],
                      newer and newer["filed"], market, symbol))


async def check_for_newer(now=None):
    """Marks companies whose proxy or annual report has been replaced. Skips a market whose source
    isn't set up (no SEC contact email; ASX terms not accepted). Returns how many were checked."""
    now = now or datetime.now(timezone.utc)
    checked = 0
    for row in companies_to_check(now):
        if (row["market"] == "US" and not config.sec_contact_email()) or (row["market"] == "ASX" and not asx_terms_accepted()):
            continue
        try:
            latest = await find_document(row["market"], row["symbol"])
        except (sources.NoDocument, sources.SourceUnavailable) as exc:
            print(f"Directors {row['market']}:{row['symbol']}: newer document check failed ({exc})")
            continue
        newer = latest if latest["url"] != row["url"] else None
        await asyncio.to_thread(mark_checked, row["market"], row["symbol"], newer, now)
        checked += 1
    return checked


async def keep_checked(check_every=timedelta(hours=6)):
    """Background task: looks for newer documents now and then (each company at most weekly)."""
    while True:
        try:
            await check_for_newer()
        except Exception as exc:
            print(f"Directors: newer document check failed: {mask_secrets(exc)}")
        await asyncio.sleep(check_every.total_seconds())


# ---------- Seed (US index members; ASX boards are never shared) ----------

def merge_seed(path=SEED_PATH):
    """Brings in the bundled seed's US boards (index members): each company not stored yet, or stored
    from an older document than the seed's. Runs at startup; a seed already merged is skipped.
    Returns how many companies were added or updated."""
    if not path.exists():
        return 0
    data = json.loads(path.read_text())
    built = (data.get("meta") or {}).get("built_at")
    with _connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'seed_built_at'").fetchone()
        stored = {(r["market"], r["symbol"]): r["filed"] for r in conn.execute("SELECT market, symbol, filed FROM documents")}
    if row and row["value"] == built:
        return 0
    changed = 0
    for company in data.get("companies", []):
        if company["market"] != "US":
            continue  # never ship ASX documents' contents (ASX's terms)
        key = (company["market"], company["symbol"])
        seed_filed = company["document"].get("filed") or ""
        if key in stored and (stored[key] or "") >= seed_filed:
            continue
        save(company["market"], company["symbol"], company["document"], company.get("seats"),
             company["status"], company.get("error"), company.get("model"))
        changed += 1
    with _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('seed_built_at', ?)", (built,))
    return changed


def export_seed(path=SEED_PATH):
    with _connect() as conn:
        docs = conn.execute("SELECT * FROM documents WHERE market = 'US' ORDER BY symbol").fetchall()
        companies = []
        for doc in docs:
            seats = [_seat(r) for r in conn.execute("SELECT * FROM seats WHERE market = ? AND symbol = ? ORDER BY rowid",
                                                     (doc["market"], doc["symbol"]))]
            for seat in seats:
                seat.pop("market"), seat.pop("symbol")
            companies.append({"market": doc["market"], "symbol": doc["symbol"], "status": doc["status"],
                              "error": doc["error"], "model": doc["model"],
                              "document": {k: doc[k] for k in ("company_name", "source", "kind", "title", "url",
                                                               "pdf_url", "filed", "cik")},
                              "seats": seats})
    path.write_text(json.dumps({"meta": {"built_at": _now(), "model": config.DIRECTORS_MODEL,
                                         "count": len(companies)}, "companies": companies}, indent=0))
    return len(companies)


async def build_seed(symbols=None, limit=None):
    """Reads the boards of the US index members (or the symbols given) that aren't stored yet."""
    import constituents
    us = sorted({(c["symbol"], c["name"]) for c in constituents.universe() if c["market"] == "US"})
    if symbols:
        us = [(s, n) for s, n in us if s in symbols]
    done = 0
    for symbol, name in us[:limit] if limit else us:
        if board("US", symbol):
            continue
        try:
            result = await read_board("US", symbol, name)
            print(f"{symbol:6} {result['status']:12} {len(result['directors']):>3} directors")
        except Exception as exc:
            print(f"{symbol:6} failed: {mask_secrets(exc)}")
        done += 1
    return done


if __name__ == "__main__":
    # python directors.py --seed [SYMBOL ...]  (run from backend/; needs ANTHROPIC_API_KEY and SEC_CONTACT_EMAIL)
    if sys.argv[1:2] != ["--seed"]:
        sys.exit("usage: python directors.py --seed [SYMBOL ...]")
    asyncio.run(build_seed(set(sys.argv[2:]) or None))
    print(f"Wrote {export_seed()} companies to {SEED_PATH}")
