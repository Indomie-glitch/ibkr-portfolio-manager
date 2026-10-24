"""Matching people across companies (#113): is the director in one company's annual report the same
person as a director in another's?

Pure functions, no network. The rules, strictest first:
1. The same Wikidata ID: the same person.
2. The same name (first and last, ignoring titles, degrees, honours and middle names) AND one of
   the two documents names the other company among that person's other boards: the same person.
3. The same name only: a possible match, kept apart and never drawn on the map, because two
   different people can share a name ("David Smith").

Wikidata IDs come from wikidata_match: the people Wikidata links to that one company (board member,
CEO, chair), matched by name within that short list only, so a common name can't pick up a
stranger's ID.
"""
import re
import unicodedata

from yahoo import clean_person_name, search_name

# Common English short forms that don't begin the full name ("Sue" isn't the start of "Susan"),
# used only when matching within one company's short Wikidata list (same_name_loosely)
SHORT_NAMES = {
    "sue": "susan", "bill": "william", "will": "william", "bob": "robert", "rob": "robert", "dick": "richard",
    "rick": "richard", "jim": "james", "jimmy": "james", "jack": "john", "johnny": "john", "ted": "edward",
    "ned": "edward", "tony": "anthony", "chuck": "charles", "charlie": "charles", "kate": "katherine",
    "kathy": "katherine", "cathy": "catherine", "liz": "elizabeth", "beth": "elizabeth", "betty": "elizabeth",
    "peggy": "margaret", "meg": "margaret", "maggie": "margaret", "hank": "henry", "harry": "henry",
    "sandy": "sandra", "patty": "patricia", "trish": "patricia", "jenny": "jennifer", "jen": "jennifer",
    "andy": "andrew", "drew": "andrew", "mike": "michael", "mick": "michael", "steve": "stephen",
    "geoff": "geoffrey", "jeff": "jeffrey", "greg": "gregory", "chris": "christopher", "matt": "matthew",
    "nick": "nicholas", "dan": "daniel", "dave": "david", "sam": "samuel", "pete": "peter", "tom": "thomas",
}

# Honours and suffixes that can follow a name in Australian and US documents
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "ac", "ao", "am", "oam", "kc", "qc", "sc", "frs", "obe", "cbe", "mbe"}


def _ascii(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def name_parts(name):
    """(first, last) in lower case ASCII, or None: "Ms. Catherine (Cathy) M. Livingstone AO" ->
    ("catherine", "livingstone"). Middle names and initials are ignored."""
    text = re.sub(r"\([^)]*\)|\"[^\"]*\"", " ", clean_person_name(name))  # nicknames in brackets or quotes
    # Apostrophes vary between documents (O'Malley, O’Malley): drop them all
    text = re.sub(r"['‘’`´]", "", text)
    words = [w for w in re.split(r"[\s]+", _ascii(text).lower().replace(".", " ")) if w]
    words = [re.sub(r"[^a-z-]", "", w) for w in words]
    words = [w for w in words if w and w not in SUFFIXES]
    if len(words) < 2:
        return None
    return words[0], words[-1]


def match_key(name):
    """"first last", the key used to compare names across documents; None if there isn't one."""
    parts = name_parts(name)
    return f"{parts[0]} {parts[1]}" if parts else None


def nicknames(name):
    """First names in brackets or quotes: 'Catherine (Cathy) Livingstone' -> {'cathy'}."""
    found = re.findall(r"\(([^)]+)\)|\"([^\"]+)\"", name or "")
    return {_ascii(nick).lower().strip() for pair in found for nick in pair if nick}


def same_name_loosely(a, b):
    """Same last name, and first names equal, a nickname of the other, or one starting the other
    ("Matt" / "Matthew"). Only used within one company's short list of people."""
    pa, pb = name_parts(a), name_parts(b)
    if not pa or not pb or pa[1] != pb[1]:
        return False
    fa, fb = pa[0], pb[0]
    if fa == fb or fa in nicknames(b) or fb in nicknames(a):
        return True
    if SHORT_NAMES.get(fa) == fb or SHORT_NAMES.get(fb) == fa:
        return True
    return len(min(fa, fb, key=len)) >= 3 and (fa.startswith(fb) or fb.startswith(fa))


def wikidata_match(name, candidates):
    """The one Wikidata person among a company's candidates ([{id, label, aliases, article}]) whose
    label or an alias matches name; None if there is none, or more than one (ambiguous)."""
    found = {c["id"]: c for c in candidates
             if any(same_name_loosely(name, n) for n in [c.get("label") or "", *(c.get("aliases") or [])])}
    return next(iter(found.values())) if len(found) == 1 else None


def company_named(company_name, texts):
    """Whether any of texts (a person's other boards, as written in a document) names the company,
    e.g. "BHP Group Limited" in ["Director of BHP Group", "Chair of Orica"]."""
    target = search_name(company_name or "").lower()
    target = re.sub(r"[^a-z0-9& ]", " ", _ascii(target))
    target = " ".join(target.split())
    if len(target) < 3:
        return False
    for text in texts or []:
        haystack = " ".join(re.sub(r"[^a-z0-9& ]", " ", _ascii(str(text)).lower()).split())
        if re.search(rf"\b{re.escape(target)}\b", haystack):
            return True
    return False


def link_basis(seat, other, seat_company, other_company):
    """How two board seats in different companies are the same person: "wikidata", "named_in_document",
    "name_only" (a possible match, not shown as a link) or None (different people)."""
    if seat.get("wikidata_id") and other.get("wikidata_id"):
        return "wikidata" if seat["wikidata_id"] == other["wikidata_id"] else None
    if not seat.get("match_key") or seat["match_key"] != other.get("match_key"):
        return None
    if company_named(other_company, seat.get("other_boards")) or company_named(seat_company, other.get("other_boards")):
        return "named_in_document"
    return "name_only"
