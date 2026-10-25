"""What's public about the people we already have (#280): executives (#112) and directors (#113).

For each person: their Wikidata item and English Wikipedia article, and from them a short summary,
a photo with its licence, birth year, education, positions held and other boards. No UI uses it yet.

Matching is careful, because a wrong match is worse than none. A person is matched in one of two ways
and the way is stored with every result (method, detail):
- company_link: Wikidata itself lists them as a board member, CEO or chair of that company (#113's
  lookup), and their name fits exactly one person on that list.
- name_search: a Wikidata search by name finds exactly one human whose name fits AND who has evidence
  tying them to this company: the company in their description, employer or positions held, or the
  companies named for them in the document; or, failing that, a business occupation together with a
  birth year that agrees with the age the document gives.
Anyone with more than one plausible match, a name match without evidence, or no match is skipped, with
the reason ("ambiguous", "no_company_evidence", "no_candidate"). Birth years that disagree rule a
candidate out.

Stored in person_data.sqlite (persons: one row per person per company; facts: one row per Wikidata
item), with a bundled seed (seed/persons.json, built by `python person_data.py --seed`) and a weekly
check for new people (keep_checked).
"""
import asyncio
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
import directors_sources as sources
import people
import wikimedia as wm
from config import DATA_DIR
from secrets_guard import mask_secrets

DB_PATH = DATA_DIR / "person_data.sqlite"
SEED_PATH = Path(__file__).resolve().parent / "seed" / "persons.json"
RETRY_SKIPPED_AFTER = timedelta(days=30)
REFRESH_BATCH = 200  # people per weekly check, so one check never hammers Wikimedia
YAHOO_PAUSE_S = 3.0
POSITION_LIMIT, EMPLOYER_LIMIT, BOARD_LIMIT, EDUCATION_LIMIT = 15, 10, 15, 6


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS persons (
            market TEXT NOT NULL, symbol TEXT NOT NULL, match_key TEXT NOT NULL, name TEXT NOT NULL, kind TEXT, company TEXT,
            status TEXT NOT NULL,        -- matched | skipped
            reason TEXT,                 -- why skipped: ambiguous | no_company_evidence | no_candidate | no_name
            method TEXT, detail TEXT, wikidata_id TEXT, checked_at TEXT,
            PRIMARY KEY (market, symbol, match_key));
        CREATE TABLE IF NOT EXISTS facts (
            wikidata_id TEXT PRIMARY KEY, wikipedia_url TEXT, summary TEXT, photo_url TEXT, photo_page TEXT,
            photo_licence TEXT, photo_artist TEXT, photo_free INTEGER, birth_year INTEGER,
            education TEXT, positions TEXT, employers TEXT, boards TEXT, fetched_at TEXT);
        CREATE TABLE IF NOT EXISTS executives (market TEXT NOT NULL, symbol TEXT NOT NULL, company TEXT, people TEXT, fetched_at TEXT,
            PRIMARY KEY (market, symbol));
        CREATE TABLE IF NOT EXISTS company_people (market TEXT NOT NULL, symbol TEXT NOT NULL, people TEXT, fetched_at TEXT,
            PRIMARY KEY (market, symbol));
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- Matching (pure) ----------

def word_in(needle_key, text):
    """Whether the company key (people.company_key) appears as whole words in the text."""
    return bool(needle_key) and bool(re.search(rf"(?<![a-z0-9]){re.escape(needle_key)}(?![a-z0-9])", people.company_key(text)))


def expected_birth_year(context):
    """The birth year the document implies: Yahoo's year born, else the filing year minus the age."""
    if context.get("year_born"):
        return context["year_born"]
    if context.get("age") and context.get("filed_year"):
        return context["filed_year"] - context["age"]
    return None


def evidence(entity, labels, context):
    """What ties a Wikidata person to the company: {"company": [reasons], "born": "ok" | "conflict" | None, "business": bool}."""
    texts = [("description", wm.english(entity, "descriptions"))]
    texts += [("employer " + labels.get(i, ""), labels.get(i, "")) for i in wm.claim_values(entity, wm.EMPLOYER)]
    texts += [("member of " + labels.get(i, ""), labels.get(i, "")) for i in wm.claim_values(entity, wm.MEMBER_OF)]
    texts += [("position at " + labels.get(p["of"], ""), labels.get(p["of"], "")) for p in wm.positions(entity) if p["of"]]
    reasons = []
    for company in context.get("companies", []):
        key = people.company_key(company)
        if len(key) < 4:
            continue
        for label, text in texts:
            if text and word_in(key, text):
                reasons.append(f"{label} names {company}" if label == "description" else f"{label} is {company}")
                break
    expected, born = expected_birth_year(context), wm.birth_year(entity)
    verdict = None
    if expected and born:
        verdict = "ok" if abs(born - expected) <= 1 else "conflict" if abs(born - expected) > 2 else None
    business = bool(set(wm.claim_values(entity, wm.OCCUPATION)) & wm.BUSINESS_OCCUPATIONS)
    return {"company": reasons, "born": verdict, "business": business}


def qualifies(ev):
    """Evidence enough to say it's this person: the company, or a business occupation and a matching birth year."""
    if ev["born"] == "conflict":
        return None
    if ev["company"]:
        return "company_evidence", "; ".join(ev["company"])
    if ev["born"] == "ok" and ev["business"]:
        return "age_and_occupation", "business occupation and a birth year that matches the document"
    return None


def name_fits(name, entity_names):
    return any(people.same_name_loosely(name, n) for n in entity_names if n)


def search_names(name):
    """What to search Wikidata for: the cleaned name, and "first last" when that differs."""
    cleaned = people.clean_person_name(name)
    parts = people.name_parts(name)
    short = f"{parts[0]} {parts[1]}" if parts else None
    names = {}
    for n in (cleaned, short):
        if n:
            names.setdefault(n.lower(), n)  # Wikidata's search ignores case: one search for "Matthew Comyn" and "matthew comyn"
    return list(names.values())


def decide_from_list(name, listed, company):
    """Match within the people Wikidata lists for the company: exactly one name fit, else None."""
    found = {c["id"]: c for c in listed if name_fits(name, [c.get("label"), *(c.get("aliases") or [])])}
    if len(found) == 1:
        return {"status": "matched", "wikidata_id": next(iter(found)), "method": "company_link",
                "detail": f"Wikidata lists them as a board member, CEO or chair of {company}"}
    return None


def decide_from_search(name, entities, labels, context):
    """The decision after a name search. entities: {id: entity} of the search hits."""
    fitting = {i: e for i, e in entities.items() if wm.is_human(e) and name_fits(name, [wm.english(e, "labels"), *wm.aliases(e)])}
    if not fitting:
        return {"status": "skipped", "reason": "no_candidate", "detail": "no person on Wikidata with this name"}
    ok = {}
    for i, e in fitting.items():
        verdict = qualifies(evidence(e, labels, context))
        if verdict:
            ok[i] = verdict
    if len(ok) == 1:
        qid, (method, detail) = next(iter(ok.items()))
        return {"status": "matched", "wikidata_id": qid, "method": f"name_search+{method}", "detail": detail}
    if len(ok) > 1:
        return {"status": "skipped", "reason": "ambiguous", "detail": f"{len(ok)} plausible matches: {', '.join(sorted(ok))}"}
    return {"status": "skipped", "reason": "no_company_evidence",
            "detail": f"{len(fitting)} with this name, none tied to the company: {', '.join(sorted(fitting))}"}


# ---------- Facts (from a matched Wikidata item) ----------

def facts_from(entity, labels, photo, summary, boards):
    """The row stored for a Wikidata item."""
    title = wm.wikipedia_title(entity)
    positions = []
    for p in wm.positions(entity)[:POSITION_LIMIT]:
        positions.append({"position": labels.get(p["position"], ""), "of": labels.get(p["of"], "") if p["of"] else None,
                          "start": p["start"], "end": p["end"]})
    return {
        "wikipedia_url": wm.wikipedia_url(title) if title else None, "summary": summary,
        "photo_url": photo and photo["url"], "photo_page": photo and photo["page"], "photo_licence": photo and photo["licence"],
        "photo_artist": photo and photo["artist"], "photo_free": bool(photo and photo["free"]),
        "birth_year": wm.birth_year(entity),
        "education": [labels[i] for i in wm.claim_values(entity, wm.EDUCATED_AT) if labels.get(i)][:EDUCATION_LIMIT],
        "positions": [p for p in positions if p["position"]],
        "employers": [labels[i] for i in wm.claim_values(entity, wm.EMPLOYER) if labels.get(i)][:EMPLOYER_LIMIT],
        "boards": (boards or [])[:BOARD_LIMIT],
    }


def label_ids(entity):
    """Every item id whose label the facts need."""
    ids = set(wm.claim_values(entity, wm.EDUCATED_AT)) | set(wm.claim_values(entity, wm.EMPLOYER)) | set(wm.claim_values(entity, wm.MEMBER_OF))
    for p in wm.positions(entity)[:POSITION_LIMIT]:
        ids.add(p["position"])
        if p["of"]:
            ids.add(p["of"])
    return ids


# ---------- Store ----------

def save_person(conn, p, result):
    conn.execute(
        """INSERT OR REPLACE INTO persons (market, symbol, match_key, name, kind, company, status, reason, method, detail, wikidata_id, checked_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (p["market"], p["symbol"], p["match_key"], p["name"], p.get("kind"), p.get("company"), result["status"], result.get("reason"),
         result.get("method"), result.get("detail"), result.get("wikidata_id"), _now()))


def save_facts(conn, qid, f):
    conn.execute(
        """INSERT OR REPLACE INTO facts (wikidata_id, wikipedia_url, summary, photo_url, photo_page, photo_licence, photo_artist, photo_free,
           birth_year, education, positions, employers, boards, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (qid, f["wikipedia_url"], f["summary"], f["photo_url"], f["photo_page"], f["photo_licence"], f["photo_artist"], int(f["photo_free"]),
         f["birth_year"], json.dumps(f["education"]), json.dumps(f["positions"]), json.dumps(f["employers"]), json.dumps(f["boards"]), _now()))


def _facts_row(row):
    f = dict(row)
    for key in ("education", "positions", "employers", "boards"):
        f[key] = json.loads(f[key] or "[]")
    f["photo_free"] = bool(f["photo_free"])
    return f


def facts_for(market, symbol, name):
    """{status, method, detail, wikidata_id, facts} for a person at a company (None if never looked at).
    The fallback when there's no article is what the caller already has: name, initials, roles."""
    key = people.match_key(name)
    with _connect() as conn:
        row = conn.execute("SELECT * FROM persons WHERE market = ? AND symbol = ? AND match_key = ?", (market, symbol, key)).fetchone()
        if row is None:
            return None
        facts = conn.execute("SELECT * FROM facts WHERE wikidata_id = ?", (row["wikidata_id"],)).fetchone() if row["wikidata_id"] else None
    return {**{k: row[k] for k in ("status", "reason", "method", "detail", "wikidata_id", "checked_at")}, "facts": _facts_row(facts) if facts else None}


def summary_counts():
    with _connect() as conn:
        return {
            "people": conn.execute("SELECT COUNT(*) FROM persons").fetchone()[0],
            "matched": conn.execute("SELECT COUNT(*) FROM persons WHERE status = 'matched'").fetchone()[0],
            "by_method": dict(conn.execute("SELECT method, COUNT(*) FROM persons WHERE status = 'matched' GROUP BY method").fetchall()),
            "skipped": dict(conn.execute("SELECT reason, COUNT(*) FROM persons WHERE status = 'skipped' GROUP BY reason").fetchall()),
            "facts": conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
            "photos": conn.execute("SELECT COUNT(*) FROM facts WHERE photo_url IS NOT NULL").fetchone()[0],
            "free_photos": conn.execute("SELECT COUNT(*) FROM facts WHERE photo_free = 1").fetchone()[0],
            "articles": conn.execute("SELECT COUNT(*) FROM facts WHERE wikipedia_url IS NOT NULL").fetchone()[0],
        }


# ---------- Collecting the people ----------

def _merge(a, b):
    """Two records for one person at one company (an executive who is also a director)."""
    return {**b, **{k: v for k, v in a.items() if v not in (None, "", [])}, "companies": list(dict.fromkeys(a.get("companies", []) + b.get("companies", [])))}


def collect_people():
    """Everyone we have: directors from directors.sqlite (#113, with their age and other boards) and executives
    from person_data.sqlite's executives table (#112, with Yahoo's year born), one record per person per company."""
    found = {}

    def add(record):
        key = (record["market"], record["symbol"], record["match_key"])
        if key not in found:
            # "Timothy D. Cook" (Yahoo) and "Tim Cook" (the proxy) at one company are one person: merged under the first key
            key = next((k for k, other in found.items() if k[:2] == key[:2] and people.same_name_loosely(record["name"], other["name"])), key)
        found[key] = _merge(found[key], record) if key in found else record

    import directors
    with directors._connect() as conn:
        rows = conn.execute("""SELECT s.market, s.symbol, s.name, s.match_key, s.role, s.age, s.other_boards, s.wikidata_id, d.company_name, d.cik, d.filed
                               FROM seats s JOIN documents d ON d.market = s.market AND d.symbol = s.symbol""").fetchall()
    for r in rows:
        if not r["match_key"]:
            continue
        boards = [people_board(b) for b in json.loads(r["other_boards"] or "[]")]
        add({"market": r["market"], "symbol": r["symbol"], "match_key": r["match_key"], "name": r["name"], "kind": "director",
             "company": r["company_name"], "cik": r["cik"], "age": r["age"], "known_id": r["wikidata_id"],
             "filed_year": int(r["filed"][:4]) if r["filed"] else None, "companies": [r["company_name"], *[b for b in boards if b]]})
    with _connect() as conn:
        for r in conn.execute("SELECT market, symbol, company, people FROM executives").fetchall():
            for e in json.loads(r["people"] or "[]"):
                key = people.match_key(e["name"])
                if key:
                    add({"market": r["market"], "symbol": r["symbol"], "match_key": key, "name": e["name"], "kind": "executive",
                         "company": r["company"], "year_born": e.get("year_born"), "age": None, "companies": [r["company"]]})
    return list(found.values())


def people_board(text):
    """The company in "BlueScope Steel Limited (Chair)", unless it's a past board (a date range)."""
    match = re.match(r"^(.*?)\s*(?:\(([^)]*)\))?\s*$", text or "")
    name, role = (match.group(1).strip(), match.group(2) or "") if match else ((text or "").strip(), "")
    return None if re.search(r"\b(19|20)\d\d\b", role) else name or None


def pending(all_people, conn, only=None, retry_before=None):
    """The people without a result yet, or skipped long enough ago to try again."""
    done = {(r["market"], r["symbol"], r["match_key"]): r for r in conn.execute("SELECT market, symbol, match_key, status, checked_at FROM persons")}
    todo = []
    for p in all_people:
        if only and p["symbol"] not in only:
            continue
        row = done.get((p["market"], p["symbol"], p["match_key"]))
        if row is None or (row["status"] == "skipped" and retry_before and row["checked_at"] < retry_before.isoformat(timespec="seconds")):
            todo.append(p)
    return todo


# ---------- Running the job ----------

async def company_list(market, symbol, cik):
    """The people Wikidata lists for a company (board member, CEO, chair), fetched once and kept."""
    with _connect() as conn:
        row = conn.execute("SELECT people FROM company_people WHERE market = ? AND symbol = ?", (market, symbol)).fetchone()
    if row:
        return json.loads(row["people"])
    clause = sources.wikidata_company_clause(market, symbol, cik)
    listed = []
    if clause:
        query = sources.WIKIDATA_QUERY % clause
        try:
            answer = await wm._fetch("sparql", wm.SPARQL + "?" + sources.urllib.parse.urlencode({"query": query, "format": "json"}),
                                     accept="application/sparql-results+json")
            listed = sources.parse_wikidata(answer)
        except Exception as exc:
            print(f"  company list {market}:{symbol} failed: {exc.__class__.__name__}")
            return []  # not saved: tried again next time
    with _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO company_people (market, symbol, people, fetched_at) VALUES (?, ?, ?, ?)",
                     (market, symbol, json.dumps(listed), _now()))
    return listed


async def match_person(p):
    """The result for one person: matched (with how) or skipped (with why)."""
    if not people.name_parts(p["name"]):
        return {"status": "skipped", "reason": "no_name", "detail": "no first and last name to look for"}
    if p.get("known_id"):
        return {"status": "matched", "wikidata_id": p["known_id"], "method": "company_link",
                "detail": f"Wikidata lists them as a board member, CEO or chair of {p['company']} (#113)"}
    listed = await company_list(p["market"], p["symbol"], p.get("cik"))
    result = decide_from_list(p["name"], listed, p["company"]) if listed else None
    if result:
        return result
    hits = {}
    for term in search_names(p["name"]):
        for hit in await wm.search_people(term):
            hits.setdefault(hit["id"], hit)
    if not hits:
        return {"status": "skipped", "reason": "no_candidate", "detail": "no person on Wikidata with this name"}
    entities = await wm.get_entities(hits)
    plausible = {i: e for i, e in entities.items() if wm.is_human(e) and name_fits(p["name"], [wm.english(e, "labels"), *wm.aliases(e)])}
    labels = await wm.get_labels(set().union(*(label_ids(e) for e in plausible.values())) if plausible else set())
    context = {"companies": p["companies"], "year_born": p.get("year_born"), "age": p.get("age"), "filed_year": p.get("filed_year")}
    return decide_from_search(p["name"], plausible, labels, context)


async def fetch_facts(qids):
    """Fills facts for Wikidata items we don't have yet; returns how many."""
    with _connect() as conn:
        have = {r[0] for r in conn.execute("SELECT wikidata_id FROM facts")}
    need = [q for q in dict.fromkeys(qids) if q not in have]
    done = 0
    for i in range(0, len(need), 40):
        batch = need[i:i + 40]
        try:
            entities = await wm.get_entities(batch)
            labels = await wm.get_labels(set().union(*(label_ids(e) for e in entities.values())) if entities else set())
            boards = await wm.board_memberships(list(entities))
            files = {q: (wm.claim_values(e, wm.IMAGE) or [None])[0] for q, e in entities.items()}
            photos = await wm.photo_info([f for f in files.values() if f])
            rows = {}
            for qid, entity in entities.items():
                title = wm.wikipedia_title(entity)
                summary = await wm.wikipedia_summary(title) if title else None
                rows[qid] = facts_from(entity, labels, photos.get(files[qid]) if files[qid] else None, summary, boards.get(qid))
        except Exception as exc:  # this batch is tried again on the next run; the others carry on
            print(f"  facts for {len(batch)} people failed: {mask_secrets(exc)}", flush=True)
            continue
        with _connect() as conn:
            for qid, row in rows.items():
                save_facts(conn, qid, row)
        done += len(rows)
    return done


def matched_without_facts():
    """Wikidata items of matched people whose facts haven't been fetched (a batch that failed, or a run that stopped)."""
    with _connect() as conn:
        return [r[0] for r in conn.execute("""SELECT DISTINCT p.wikidata_id FROM persons p LEFT JOIN facts f ON f.wikidata_id = p.wikidata_id
                                              WHERE p.status = 'matched' AND f.wikidata_id IS NULL""")]


async def run(todo, report=print):
    """Matches each person (saving as it goes, so a stopped run carries on), then fetches the facts of the matches."""
    matched, failures = [], 0
    for n, p in enumerate(todo, start=1):
        try:
            result = await match_person(p)
            failures = 0
        except Exception as exc:
            failures += 1
            print(f"  {p['name']} ({p['symbol']}) failed: {mask_secrets(exc)}")
            if failures >= 20:
                print("  Wikimedia keeps failing: stopping (nothing is lost; run again to carry on)")
                break
            continue
        with _connect() as conn:
            save_person(conn, p, result)
        if result["status"] == "matched":
            matched.append(result["wikidata_id"])
        report(n, len(todo), p, result)
    return await fetch_facts(matched + matched_without_facts())


async def collect_executives(companies, report=print):
    """Yahoo's executives for companies not fetched yet (one at a time, with a pause: Yahoo rate-limits)."""
    import yahoo
    with _connect() as conn:
        have = {(r[0], r[1]) for r in conn.execute("SELECT market, symbol FROM executives")}
    failures = 0
    for n, c in enumerate(companies, start=1):
        if (c["market"], c["symbol"]) in have:
            continue
        try:
            info = await yahoo.fetch_info(yahoo.ticker_for(c["symbol"], c["market"]))
            execs = yahoo.executives_from_info(info)["executives"]
            failures = 0
        except Exception as exc:
            failures += 1
            print(f"  executives {c['market']}:{c['symbol']} failed: {exc.__class__.__name__}")
            if failures >= 5:
                print("  Yahoo keeps failing: stopping; run again later to continue")
                return False
            await asyncio.sleep(YAHOO_PAUSE_S * 5)
            continue
        with _connect() as conn:
            conn.execute("INSERT OR REPLACE INTO executives (market, symbol, company, people, fetched_at) VALUES (?, ?, ?, ?, ?)",
                         (c["market"], c["symbol"], c["name"], json.dumps([{"name": e["name"], "year_born": e["year_born"]} for e in execs]), _now()))
        if n % 25 == 0:
            report(n, len(companies), c, None)
        await asyncio.sleep(YAHOO_PAUSE_S)
    return True


def record_executives(market, symbol, company, executives):
    """Called when the app fetched a company's executives (GET /executives): keeps them for the weekly check."""
    with _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO executives (market, symbol, company, people, fetched_at) VALUES (?, ?, ?, ?, ?)",
                     (market, symbol, company, json.dumps([{"name": e["name"], "year_born": e.get("year_born")} for e in executives]), _now()))


# ---------- Seed and the weekly check ----------

def export_seed(path=SEED_PATH):
    """Writes everything found: every person's result (skipped ones too, so they aren't looked up again) and the facts."""
    with _connect() as conn:
        persons = [dict(r) for r in conn.execute("SELECT * FROM persons ORDER BY market, symbol, match_key")]
        facts = {r["wikidata_id"]: {k: v for k, v in dict(r).items() if k != "wikidata_id"} for r in conn.execute("SELECT * FROM facts")}
    path.write_text(json.dumps({"meta": {"built_at": _now(), "people": len(persons), "facts": len(facts)}, "persons": persons, "facts": facts}, separators=(",", ":")))
    return len(persons), len(facts)


def merge_seed(path=SEED_PATH):
    """Brings in the bundled seed: people and facts we don't have yet. A seed already merged is skipped."""
    if not path.exists():
        return 0
    data = json.loads(path.read_text())
    built = data["meta"]["built_at"]
    with _connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'seed_built_at'").fetchone()
        if row and row["value"] == built:
            return 0
        have = {(r[0], r[1], r[2]) for r in conn.execute("SELECT market, symbol, match_key FROM persons")}
        added = 0
        for p in data["persons"]:
            if (p["market"], p["symbol"], p["match_key"]) in have:
                continue
            conn.execute("""INSERT INTO persons (market, symbol, match_key, name, kind, company, status, reason, method, detail, wikidata_id, checked_at)
                            VALUES (:market, :symbol, :match_key, :name, :kind, :company, :status, :reason, :method, :detail, :wikidata_id, :checked_at)""", p)
            added += 1
        for qid, f in data["facts"].items():
            conn.execute("""INSERT OR IGNORE INTO facts (wikidata_id, wikipedia_url, summary, photo_url, photo_page, photo_licence, photo_artist, photo_free,
                            birth_year, education, positions, employers, boards, fetched_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (qid, f["wikipedia_url"], f["summary"], f["photo_url"], f["photo_page"], f["photo_licence"], f["photo_artist"], f["photo_free"],
                          f["birth_year"], f["education"], f["positions"], f["employers"], f["boards"], f["fetched_at"]))
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('seed_built_at', ?)", (built,))
    return added


async def refresh_new(now=None, limit=REFRESH_BATCH):
    """The weekly check: people we haven't looked at (a newly read board, a newly fetched company's executives), and
    skipped people last tried over a month ago. At most `limit` per run. Returns how many were looked at."""
    now = now or datetime.now(timezone.utc)
    with _connect() as conn:
        todo = pending(collect_people(), conn, retry_before=now - RETRY_SKIPPED_AFTER)[:limit]
    if todo:
        await run(todo, report=lambda *a: None)
    return len(todo)


async def keep_checked(check_every=timedelta(days=7)):
    """Background task: looks up new people once a week (config.person_data_enabled switches it off)."""
    while True:
        if config.person_data_enabled():
            try:
                looked = await refresh_new()
                if looked:
                    print(f"Person data: looked up {looked} new people")
            except Exception as exc:
                print(f"Person data: weekly check failed: {mask_secrets(exc)}")
        await asyncio.sleep(check_every.total_seconds())


# ---------- Command line ----------

def _show(n, total, p, result):
    if result is None:
        print(f"  executives {n}/{total} ({p['market']}:{p['symbol']})", flush=True)
        return
    tag = result.get("wikidata_id") or result.get("reason")
    print(f"[{n}/{total}] {p['name']} ({p['symbol']}, {p['kind']}) -> {result['status']} {tag} | {result.get('method') or ''} {result.get('detail') or ''}"[:230], flush=True)


async def _sample(size=20):
    """A trial on a few companies' people, to check the matches by hand: executives from Yahoo for six companies,
    then a seeded random mix of their executives and directors."""
    import random
    chosen = [("US", "AAPL", "Apple Inc."), ("US", "MSFT", "Microsoft Corporation"), ("US", "JPM", "JPMorgan Chase & Co."),
              ("US", "TDY", "Teledyne Technologies"), ("ASX", "CBA", "Commonwealth Bank of Australia"), ("ASX", "BHP", "BHP Group Limited")]
    await collect_executives([{"market": m, "symbol": s, "name": n} for m, s, n in chosen])
    pool = [p for p in collect_people() if p["symbol"] in {s for _, s, _ in chosen}]
    random.Random(280).shuffle(pool)
    execs = [p for p in pool if p["kind"] == "executive"][: size // 2]
    directors = [p for p in pool if p["kind"] == "director"][: size - len(execs)]
    with _connect() as conn:
        conn.execute("DELETE FROM persons")  # the trial starts clean
    await run(execs + directors, report=_show)
    print(json.dumps(summary_counts(), indent=1))


async def _seed():
    """Everything: Yahoo's executives for the index members, then every person, then the seed file."""
    import constituents
    universe = [{"market": c["market"], "symbol": c["symbol"], "name": c["name"]} for c in constituents.universe()]
    print(f"{len(universe)} companies", flush=True)
    await collect_executives(universe, report=_show)
    with _connect() as conn:
        todo = pending(collect_people(), conn)
    print(f"{len(todo)} people to look up", flush=True)
    await run(todo, report=_show)
    print(json.dumps(summary_counts(), indent=1))
    print("seed:", export_seed(), "->", SEED_PATH)


if __name__ == "__main__":
    # From backend/:  python person_data.py --sample | --seed | --export   (needs .env for the contact address)
    mode = sys.argv[1:2]
    if mode == ["--sample"]:
        asyncio.run(_sample())
    elif mode == ["--seed"]:
        asyncio.run(_seed())
    elif mode == ["--export"]:
        print(export_seed(), "->", SEED_PATH)
    else:
        sys.exit("usage: python person_data.py --sample | --seed | --export")
