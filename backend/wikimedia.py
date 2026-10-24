"""Wikidata, Wikipedia and Wikimedia Commons clients for the person data job (#280).

Every request carries a User-Agent with a contact address (Wikimedia's policy; config.sec_contact_email
is the one the project already has) and waits between requests: the API at most twice a second, the
SPARQL service one query every 2.5 seconds. Parsing is in plain functions that take already-fetched
JSON, so it is tested without the network (tests/test_person_data.py).
"""
import asyncio
import html
import json
import re
import time
import urllib.parse

import config
import directors_sources as sources

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WIKIPEDIA_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
SPARQL = "https://query.wikidata.org/sparql"
API_PAUSE_S = 0.25
SPARQL_PAUSE_S = 2.5

# Wikidata properties used
HUMAN, BIRTH, IMAGE = "Q5", "P569", "P18"
INSTANCE_OF, OCCUPATION, EMPLOYER, EDUCATED_AT, POSITION, MEMBER_OF = "P31", "P106", "P108", "P69", "P39", "P463"
OF_QUALIFIER, START, END = "P642", "P580", "P582"
# Occupations that make a name match plausible for someone who runs or sits on the board of a company
BUSINESS_OCCUPATIONS = {"Q43845", "Q484876", "Q131524", "Q806798", "Q4182927", "Q1930187", "Q189290", "Q82955", "Q40348", "Q212238"}
# (businessperson, chief executive officer, entrepreneur, banker, financier, investor, ...): checked at run time
# against the person's claims only as supporting evidence together with a matching birth year.

_locks = {"api": asyncio.Lock(), "sparql": asyncio.Lock()}
_last = {"api": 0.0, "sparql": 0.0}


def user_agent():
    email = config.sec_contact_email()
    return f"PortfolioManager/0.4 ({sources.REPO}{'; ' + email if email else ''})"


async def _fetch(kind, url, accept="application/json"):
    pause = SPARQL_PAUSE_S if kind == "sparql" else API_PAUSE_S
    async with _locks[kind]:
        wait = pause - (time.monotonic() - _last[kind])
        if wait > 0:
            await asyncio.sleep(wait)
        _last[kind] = time.monotonic()
    return json.loads(await sources.get(url, {"User-Agent": user_agent(), "Accept": accept}))


def _api(base, params):
    return base + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})


# ---------- Wikidata search and entities ----------

async def search_people(name, limit=7):
    """[{id, label, description}] for a name (Wikidata's search matches labels and aliases)."""
    answer = await _fetch("api", _api(WIKIDATA_API, {"action": "wbsearchentities", "search": name, "language": "en",
                                                      "uselang": "en", "type": "item", "limit": limit}))
    return [{"id": r["id"], "label": r.get("label") or "", "description": r.get("description") or "",
             "alias": (r.get("match") or {}).get("text") if (r.get("match") or {}).get("type") == "alias" else None}
            for r in answer.get("search", [])]


async def get_entities(ids, props="claims|descriptions|labels|aliases|sitelinks"):
    """{id: entity} for up to 50 ids per request."""
    found = {}
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 50):
        answer = await _fetch("api", _api(WIKIDATA_API, {"action": "wbgetentities", "ids": "|".join(ids[i:i + 50]), "props": props,
                                                          "languages": "en", "sitefilter": "enwiki"}))
        found.update(answer.get("entities", {}))
    return found


async def get_labels(ids):
    """{id: English label} for any items (a person's schools, positions, employers)."""
    entities = await get_entities(ids, props="labels")
    return {i: (e.get("labels", {}).get("en", {}) or {}).get("value", "") for i, e in entities.items()}


# ---------- Reading claims ----------

def claim_values(entity, prop):
    """The values of a property: item ids as strings, times as ISO strings, strings as they are."""
    out = []
    for claim in (entity.get("claims") or {}).get(prop, []):
        snak = claim.get("mainsnak", {})
        if snak.get("snaktype") != "value":
            continue
        value = snak["datavalue"]["value"]
        out.append(value["id"] if isinstance(value, dict) and "id" in value else value["time"] if isinstance(value, dict) and "time" in value else value)
    return out


def year_of(time_value):
    """1961 from "+1961-02-01T00:00:00Z" (None when it isn't there or is only a century)."""
    match = re.match(r"^[+-]?(\d{4})-", time_value or "")
    return int(match.group(1)) if match else None


def birth_year(entity):
    years = [year_of(t) for t in claim_values(entity, BIRTH)]
    return next((y for y in years if y), None)


def is_human(entity):
    return HUMAN in claim_values(entity, INSTANCE_OF)


def english(entity, field):
    """description / label in English."""
    value = (entity.get(field) or {}).get("en") if isinstance(entity.get(field), dict) else None
    return (value or {}).get("value", "") if isinstance(value, dict) else ""


def aliases(entity):
    return [a.get("value", "") for a in (entity.get("aliases") or {}).get("en", [])]


def wikipedia_title(entity):
    link = (entity.get("sitelinks") or {}).get("enwiki")
    return link.get("title") if link else None


def wikipedia_url(title):
    return "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="_(),'%")


def positions(entity):
    """[{position id, of id or None, start year, end year}] from "position held"."""
    out = []
    for claim in (entity.get("claims") or {}).get(POSITION, []):
        snak = claim.get("mainsnak", {})
        if snak.get("snaktype") != "value":
            continue
        qualifiers = claim.get("qualifiers") or {}

        def first(prop):
            for q in qualifiers.get(prop, []):
                if q.get("snaktype") == "value":
                    value = q["datavalue"]["value"]
                    return value.get("id") if isinstance(value, dict) and "id" in value else value.get("time") if isinstance(value, dict) else None
            return None
        out.append({"position": snak["datavalue"]["value"]["id"], "of": first(OF_QUALIFIER),
                    "start": year_of(first(START)), "end": year_of(first(END))})
    return out


# ---------- Board memberships (SPARQL: companies that list the person as a board member) ----------

BOARD_QUERY = """SELECT ?person ?company ?companyLabel WHERE {
  VALUES ?person { %s }
  ?company wdt:P3320 ?person .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}"""


async def board_memberships(ids):
    """{person id: [company names]} for up to 100 people in one query."""
    if not ids:
        return {}
    values = " ".join(f"wd:{i}" for i in ids)
    answer = await _fetch("sparql", SPARQL + "?" + urllib.parse.urlencode({"query": BOARD_QUERY % values, "format": "json"}),
                          accept="application/sparql-results+json")
    return parse_boards(answer)


def parse_boards(answer):
    found = {}
    for row in answer.get("results", {}).get("bindings", []):
        person = row["person"]["value"].rsplit("/", 1)[-1]
        name = row.get("companyLabel", {}).get("value")
        if name and not re.fullmatch(r"Q\d+", name) and name not in found.setdefault(person, []):
            found[person].append(name)
    return found


# ---------- Wikipedia summary ----------

async def wikipedia_summary(title):
    """A short plain-text summary of an English Wikipedia article, or None."""
    try:
        answer = await _fetch("api", WIKIPEDIA_SUMMARY.format(title=urllib.parse.quote(title.replace(" ", "_"), safe="")))
    except sources.SourceUnavailable:
        return None
    return summary_from(answer)


def summary_from(answer):
    if answer.get("type") == "disambiguation":
        return None  # not about a person
    text = " ".join((answer.get("extract") or "").split())
    if len(text) <= 600:
        return text or None
    cut = text[:600]
    sentence = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return cut[: sentence + 1] if sentence > 200 else cut.rsplit(" ", 1)[0] + "…"


# ---------- Photos and their licences (Wikimedia Commons) ----------

FREE_LICENCE = re.compile(r"^(CC[ -]BY|CC0|Public domain|PD|GFDL|Attribution)", re.IGNORECASE)


async def photo_info(filenames):
    """{file name: {url, page, licence, artist, free}} for Commons files (50 per request)."""
    found = {}
    names = list(dict.fromkeys(filenames))
    for i in range(0, len(names), 50):
        titles = "|".join("File:" + n for n in names[i:i + 50])
        answer = await _fetch("api", _api(COMMONS_API, {"action": "query", "titles": titles, "prop": "imageinfo", "iiprop": "url|extmetadata",
                                                         "iiurlwidth": 300, "iiextmetadatafilter": "LicenseShortName|Artist|Credit"}))
        for page in answer.get("query", {}).get("pages", []):
            info = parse_photo(page)
            if info:
                found[page["title"].removeprefix("File:")] = info
    return found


def parse_photo(page):
    infos = page.get("imageinfo") or []
    if not infos:
        return None
    info = infos[0]
    meta = info.get("extmetadata") or {}
    licence = (meta.get("LicenseShortName") or {}).get("value") or ""
    artist = html.unescape(re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value") or "")).strip()
    return {"url": info.get("thumburl") or info.get("url"), "page": info.get("descriptionurl"), "licence": licence,
            "artist": artist[:200], "free": bool(FREE_LICENCE.match(licence))}
