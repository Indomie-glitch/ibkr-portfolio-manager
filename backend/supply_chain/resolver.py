"""Company name resolver (#119): maps a company name from a filing ("TSMC", "Micron Technology, Inc.") to a company
in the graph, and says how it did so. A name that isn't clearly one company is skipped, never guessed.

Order, stopping at the first that gives a clear answer:
1. the identifier store: a company already in the graph whose name (or a stored alias) is the same name
2. our index data (S&P 500, Nasdaq 100, Dow, ASX 20/50/200 members, constituents.py)
3. OpenFIGI: a name search where every listing of the same name belongs to one company (one share class)

"Same name" means the same after normalising: case, accents, punctuation, "&" = "and", and legal endings (Inc,
Incorporated, Corp, Corporation, Co, Company, Ltd, Limited, plc, N.V., AG, SA ...) removed. A few well-known short
names are aliases ("TSMC"). Nothing looser is used: a name that only starts like a known company ("Apple Operations
International") is probably a subsidiary and is skipped as such.

Every decision is saved in name_resolutions (method for a match, reason for a skip), so the same name isn't looked up
twice; a skip is looked at again after RETRY_SKIPPED_DAYS (the index data or OpenFIGI may know more by then).
OpenFIGI being unreachable is not a decision and is not saved.
"""
import json
import re
import unicodedata
from pathlib import Path
from datetime import datetime, timedelta, timezone

import constituents
from supply_chain import graph, openfigi
from supply_chain.db import now, transaction

ALIASES_PATH = Path(__file__).resolve().parent.parent / "seed" / "aliases.json"
RETRY_SKIPPED_DAYS = 30
DOMINANT_LISTINGS = 3  # a share class with this many times the listings of the next is the company's primary one
LEGAL_ENDINGS = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "llc", "lp", "llp", "plc", "sa", "ag",
    "nv", "bv", "se", "spa", "sas", "oyj", "ab", "asa", "as", "gmbh", "kk", "pty", "pcl", "tbk", "sab", "de", "cv", "the",
}
EXCHANGE_MARKETS = {  # also: HK, SG, CH, SE, IT, ES
    "HK": "HK", "SP": "SG", "SW": "CH", "SS": "SE", "IM": "IT", "SM": "ES", "C1": "CN", "C2": "CN", "CH": "CN",  # OpenFIGI exchange codes -> the market names the store uses
    "US": "US", "UN": "US", "UW": "US", "UQ": "US", "UA": "US", "UR": "US", "UP": "US", "UV": "US",
    "AU": "ASX", "KS": "KR", "KP": "KR", "JT": "JP", "TT": "TW", "FP": "FR", "LN": "GB", "CT": "CA", "NA": "NL", "GY": "DE",
}
UNNAMED = re.compile(r"^(?:(?:one|two|three|a|an|our|the|certain|several|major|large|largest|significant|top)\s+)*"
                     r"(?:(?:large|major|significant|key|principal|enterprise|direct|indirect|end|channel|oem|retail)\s+)*"
                     r"(?:customer|customers|distributor|distributors|partner|partners|reseller|resellers|client|clients|supplier|suppliers|"
                     r"licensee|licensees|vendor|vendors)(?:\s+(?:[a-z]|\d+|one|two|three|four|five))?$")
SAME_COMPANY_CAP_RATIO = 1.01  # share classes report one company market cap


def name_key(name):
    """A name in its comparable form: "Taiwan Semiconductor Manufacturing Co., Ltd." -> "taiwan semiconductor manufacturing"."""
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\b(?:[a-z]\.){2,}", lambda m: m.group().replace(".", ""), text)  # N.V. -> NV, S.A. -> SA
    text = text.replace("&", " and ").replace("'", "")
    words = re.sub(r"[^a-z0-9]+", " ", text).split()
    while len(words) > 1 and words[-1] in LEGAL_ENDINGS:
        words.pop()
    while len(words) > 1 and words[0] == "the":
        words.pop(0)
    return " ".join(words)


def is_unnamed(name):
    """"Customer A", "one customer", "a large distributor": the filing didn't say who."""
    return bool(UNNAMED.match(re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()))


_alias_cache = {}


def alias_entries(path=None):
    """{name key of a common name: the entry it belongs to} from seed/aliases.json (names filings use that differ from the
    legal name: Foxconn = Hon Hai Precision). The company's own legal name is not an alias, so it is matched the usual way."""
    path = Path(path or ALIASES_PATH)
    if path not in _alias_cache:
        entries = json.loads(path.read_text(encoding="utf-8"))["aliases"]
        _alias_cache[path] = {name_key(alias): entry for entry in entries for alias in entry["aliases"]}
    return _alias_cache[path]


def result(status, company_id=None, method=None, reason=None, detail=None, cached=False):
    return {"status": status, "company_id": company_id, "method": method, "reason": reason, "detail": detail, "cached": cached}


# ---------- Where names are looked up ----------

def store_candidates(conn, key):
    """Companies in the graph with this name: by a stored name alias or by the company's own name."""
    found = {row["company_id"] for row in conn.execute("SELECT company_id FROM identifiers WHERE scheme = 'name' AND value = ?", (key,))}
    for row in conn.execute("SELECT id, name FROM companies WHERE is_placeholder = 0"):
        if name_key(row["name"]) == key:
            found.add(row["id"])
    return sorted(found)


def store_prefix_hit(conn, key):
    """A known company whose name this one starts with ("apple" for "apple operations international")."""
    for row in conn.execute("SELECT name FROM companies WHERE is_placeholder = 0"):
        known = name_key(row["name"])
        if len(known) >= 4 and key.startswith(known + " "):
            return row["name"]
    return None


def index_hits(key, index_companies):
    return [c for c in index_companies if c.get("name") and name_key(c["name"]) == key]


def index_prefix_hit(key, index_companies):
    for c in index_companies:
        known = name_key(c.get("name"))
        if len(known) >= 4 and key.startswith(known + " "):
            return c["name"]
    return None


def one_company(hits):
    """True when several index rows with the same name are one company (share classes: one market cap), or there is one row."""
    if len(hits) == 1:
        return True
    caps = [h.get("market_cap") for h in hits]
    if any(not cap for cap in caps):
        return False
    return max(caps) / min(caps) <= SAME_COMPANY_CAP_RATIO


COMMON_TYPES = ("Common Stock", "Ordinary Shares", "REIT", "Preferred Stock")
DEPOSITARY_TYPES = ("ADR", "Depositary Receipt", "GDR")


def figi_groups(key, rows):
    """OpenFIGI equity listings whose name is this name, grouped by share class: {share class figi: [rows]}.
    The company's own shares decide how many companies there are; depositary receipts (ADRs) of the same name are the
    same company and only add their listings. Only when there are no own shares do the receipts stand in."""
    own, receipts = {}, {}
    for row in rows:
        if name_key(row.get("name")) != key:
            continue
        kind = row.get("securityType2") or row.get("securityType")
        group = row.get("shareClassFIGI") or row.get("compositeFIGI") or row["figi"]
        if kind in COMMON_TYPES:
            own.setdefault(group, []).append(row)
        elif kind in DEPOSITARY_TYPES:
            receipts.setdefault(group, []).append(row)
    if not own:
        return receipts
    merged = dict(own)
    if len(own) == 1 and receipts:
        merged[next(iter(own))] = next(iter(own.values())) + [r for rows_ in receipts.values() for r in rows_]
    return merged


def primary_group(groups):
    """The share class to use: the only one, or the one with most of the listings when it has DOMINANT_LISTINGS times as many
    as the next (Lenovo: the Hong Kong shares with their dollar, euro and yuan counters, against two stray lines). Otherwise
    None: several companies of one name, which is not for us to pick."""
    if not groups:
        return None
    if len(groups) == 1:
        return next(iter(groups))
    ranked = sorted(groups, key=lambda g: len(groups[g]), reverse=True)
    if len(groups[ranked[0]]) >= DOMINANT_LISTINGS * max(len(groups[ranked[1]]), 1) and len(groups[ranked[0]]) >= DOMINANT_LISTINGS:
        return ranked[0]
    return None


async def search_figi(search, name, key):
    """The OpenFIGI answer for a name; when the full name finds nothing with that name, the name without its legal ending
    is tried too (OpenFIGI finds nothing for "Wistron Corporation", and only warrants for "Lenovo Group Limited", but the
    companies themselves for "wistron" and "lenovo group")."""
    rows = await search(name)
    if not any(name_key(row.get("name")) == key for row in rows) and key != re.sub(r"[^a-z0-9]+", " ", name.lower()).strip():
        rows = await search(key)
    return rows


# ---------- Writing the answer ----------

def _save(conn, name, key, outcome):
    stamp = now()
    with transaction(conn):
        old = conn.execute("SELECT created_at FROM name_resolutions WHERE name_key = ?", (key,)).fetchone()
        conn.execute("DELETE FROM name_resolutions WHERE name_key = ?", (key,))
        conn.execute(
            """INSERT INTO name_resolutions (name_key, name, status, company_id, method, reason, detail, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (key, name, outcome["status"], outcome["company_id"], outcome["method"], outcome["reason"], outcome["detail"],
             old["created_at"] if old else stamp, stamp))
    return outcome


def _company_for(conn, tickers, canonical_name, method, figi=None):
    """The company that owns one of these (ticker, market) pairs or this share class, else a new one; all the tickers are attached to it."""
    company_id = next((c for c in (graph.find_company(conn, "ticker", t, m) for t, m in tickers) if c), None)
    company_id = company_id or (graph.find_company(conn, "share_class_figi", figi) if figi else None)
    if company_id is None:
        company_id = graph.add_company(conn, canonical_name)
    for ticker, market in tickers:
        try:
            graph.add_identifier(conn, company_id, "ticker", ticker, market, source=method)
        except graph.IdentifierConflict:
            pass  # that ticker already belongs to another company: the one found above stays the answer
    return company_id


def _remember_alias(conn, company_id, key, method):
    """Keeps the name as an alias of the company (no-op when it already is one)."""
    graph.add_identifier(conn, company_id, "name", key, source=method)


def _decided(conn, key, retry_after_days):
    row = conn.execute("SELECT * FROM name_resolutions WHERE name_key = ?", (key,)).fetchone()
    if row is None:
        return None
    if row["status"] == "skipped" and row["updated_at"] < _iso_days_ago(retry_after_days):
        return None
    return result(row["status"], row["company_id"], row["method"], row["reason"], row["detail"], cached=True)


def _iso_days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def resolve(conn, name, index_companies=None, search=None, retry_skipped_days=RETRY_SKIPPED_DAYS):
    """Resolves one name. Returns {status "matched"|"skipped"|"unavailable", company_id, method, reason, detail, cached}.
    index_companies: rows {market, symbol, name, market_cap} (default: the current index members); search: the OpenFIGI
    search function (default: openfigi.search)."""
    key = name_key(name)
    if not key or is_unnamed(name):
        return result("skipped", reason="unnamed" if key else "no_name", detail="the filing doesn't name the company")
    held = _decided(conn, key, retry_skipped_days)
    if held:
        return held
    index_companies = constituents.universe() if index_companies is None else index_companies
    search = search or openfigi.search

    # 1. companies we already know
    known = store_candidates(conn, key)
    if len(known) == 1:
        _remember_alias(conn, known[0], key, "identifier_store")
        return _save(conn, name, key, result("matched", known[0], "identifier_store", detail=f"same name as company {known[0]}"))
    if len(known) > 1:
        return _save(conn, name, key, result("skipped", reason="ambiguous", detail=f"{len(known)} companies in the store have this name: {known}"))

    # 1b. the alias list: stored with the company as a name identifier, so the next time it's the store that answers
    entry = alias_entries().get(key)
    if entry:
        return _matched(conn, name, key, [(entry["ticker"], entry["market"])], entry["name"], "alias_list",
                        f"common name of {entry['name']} ({entry['ticker']}, {entry['market']})")

    # 2. index members
    hits = index_hits(key, index_companies)
    if hits:
        if not one_company(hits):
            listed = ", ".join(f"{h['symbol']} ({h['market']})" for h in hits)
            return _save(conn, name, key, result("skipped", reason="ambiguous", detail=f"several index companies have this name: {listed}"))
        tickers = [(h["symbol"], h["market"]) for h in sorted(hits, key=lambda h: h["symbol"])]
        return _matched(conn, name, key, tickers, hits[0]["name"], "index_data",
                        "index member " + ", ".join(f"{s} ({m})" for s, m in tickers))

    # 3. OpenFIGI
    try:
        rows = await search_figi(search, name, key)
    except openfigi.OpenFigiUnavailable as exc:
        return result("unavailable", reason="openfigi_unavailable", detail=str(exc))
    groups = figi_groups(key, rows)
    primary = primary_group(groups)
    if primary:
        listings = groups[primary]
        tickers = sorted({(r["ticker"], EXCHANGE_MARKETS[r["exchCode"]]) for r in listings if r.get("ticker") and r.get("exchCode") in EXCHANGE_MARKETS})
        canonical = listings[0]["name"].title() if listings[0]["name"].isupper() else listings[0]["name"]
        outcome = _matched(conn, name, key, tickers, canonical, "openfigi",
                           f"OpenFIGI: {', '.join(f'{t} ({m})' for t, m in tickers) or 'no listing on a known exchange'}", figi=primary)
        if outcome["status"] == "matched":
            try:
                graph.add_identifier(conn, outcome["company_id"], "share_class_figi", primary, source="openfigi")
            except graph.IdentifierConflict:
                pass
        return outcome
    if len(groups) > 1:
        return _save(conn, name, key, result("skipped", reason="ambiguous", detail=f"OpenFIGI lists {len(groups)} different companies with this name"))

    # nothing clear
    near = store_prefix_hit(conn, key) or index_prefix_hit(key, index_companies)
    if near:
        return _save(conn, name, key, result("skipped", reason="possible_subsidiary", detail=f"starts with the name of {near}; not matched to it"))
    return _save(conn, name, key, result("skipped", reason="no_match", detail="not a known company, an index member or an OpenFIGI equity"))


def _matched(conn, name, key, tickers, canonical_name, method, detail, figi=None):
    try:
        company_id = _company_for(conn, tickers, canonical_name, method, figi)
        _remember_alias(conn, company_id, key, method)
    except graph.IdentifierConflict:
        return _save(conn, name, key, result("skipped", reason="conflict", detail="the name already belongs to another company"))
    return _save(conn, name, key, result("matched", company_id, method, detail=detail))


async def resolve_many(conn, names, **kwargs):
    """Resolves each distinct name once, in order; returns {name: result}."""
    return {name: await resolve(conn, name, **kwargs) for name in dict.fromkeys(names)}
