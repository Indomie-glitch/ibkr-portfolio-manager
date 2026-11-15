"""8-K exhibits (#322): the material agreement itself, not only the 8-K's summary of it.

For an 8-K whose items include 1.01 or 1.02 (entering into or ending a material agreement), the download job queues an
"exhibits" job (key = the document id). It lists the filing's exhibit 10.x files from the filing index, decides for
each one from its description whether it is worth reading, downloads those beside the 8-K, records every decision in
document_files, and then queues the read (reader.queue_read, again=True: chunks already read aren't paid for twice).

Deciding (decide): the description comes from the 8-K's own exhibit table under Item 9.01 ("10.1 | Supply Agreement,
dated ..."), else from the filing index. An allow list is checked first: supply, manufacturing, foundry, wafer,
capacity, purchase (not of securities, stock, notes or shares), distribution (not an equity distribution, which is a
share sale), offtake, collaboration, development, licence, services, master agreement. Then a skip list: financing
(credit and loan agreements, indentures, capped calls, underwriting, securities purchases, guarantees, pledges,
registration rights ...) and employment (employment, severance, separation, retention, compensation and
indemnification agreements ...). A description in neither is read only when the file is under UNCLEAR_MAX_TOKENS,
else skipped as "unclear description". A file over chunker.EXHIBIT_FULL_TOKENS is read only for its parties and
commercial terms (chunker.exhibit_plan: decision "partial").

An 8-K that says the agreement "will be filed as an exhibit to" a later 10-Q or 10-K has that sentence saved in
documents.filed_later and logged; picking those up from the later report is backlog (#347).
"""
import json
import re
from pathlib import Path

import sec_client
from supply_chain import chunker, jobs, reader
from supply_chain.db import now, transaction
from supply_chain.worker import Permanent, handler

PRIORITY = 35  # after the 8-K's download (30 is the download itself; reading it is 40)
UNCLEAR_MAX_TOKENS = 30_000

EXHIBIT_TYPE = re.compile(r"^EX-10(?:\.(\d{1,3}))?\b", re.I)
EXHIBIT_NUMBER = re.compile(r"^\s*(10(?:\.\d{1,3})?)\s*[*†‡#+]*\s*$")
EXHIBIT_LINE = re.compile(r"^(?:\(d\)\s*Exhibits?:?\s*)?(10(?:\.\d{1,3})?)[*†‡#+]*\s+([A-Z].+)$")

# Allowed first; each term can carry the financing words that make it something else
ALLOW = [(re.compile(r"\bsuppl(?:y|ier)\b", re.I), None),
         (re.compile(r"\bmanufactur", re.I), None),
         (re.compile(r"\bfoundry\b", re.I), None),
         (re.compile(r"\bwafers?\b", re.I), None),
         (re.compile(r"\bcapacity\b", re.I), re.compile(r"\bin (?:its|their|his|her) capacity\b", re.I)),
         (re.compile(r"\bpurchase", re.I), re.compile(r"\b(?:securities|stock|notes?|shares?|debentures?|warrants?|units?|initial purchasers?|receivables?|assets?|membership interests?)\b", re.I)),
         (re.compile(r"\bdistribut(?:ion|or)\b", re.I), re.compile(r"\bequity distribution\b", re.I)),
         (re.compile(r"\boff-?take\b", re.I), None),
         (re.compile(r"\bcollaborat", re.I), None),
         (re.compile(r"\bdevelopment\b", re.I), None),
         (re.compile(r"\blicen[cs]e\b|\blicensing\b", re.I), None),
         (re.compile(r"\bservices\b", re.I), None),
         (re.compile(r"\bmaster agreement\b", re.I), None)]
SKIP = [("financing", re.compile(
            r"credit agreement|receivables purchase|\bloan\b|indenture|capped call|underwriting|notes? due|note purchase|securities purchase|stock purchase|"
            r"share purchase|guarant|pledge|security agreement|registration rights|warrant|equity distribution|at[- ]the[- ]market|"
            r"sales agreement|forward (?:sale|purchase)|repurchase|exchange agreement|revolving|term loan|\bfacility\b|bridge|"
            r"subscription agreement|investment agreement|convertible|initial purchasers?|\bnotes\b|\bdebentures\b|\bsecurities\b|\bborrowers?\b|\blenders?\b|"
            r"administrative agent|collateral agent|promissory|\bhedge\b|call option|option counterpart", re.I)),
        ("employment", re.compile(
            r"employment|severance|separation|retention|offer letter|compensation|incentive|equity award|\baward\b|bonus|"
            r"indemnification|change (?:in|of) control|consulting agreement|transition agreement|director agreement", re.I))]

FILED_LATER = re.compile(
    r"[^.]*\b(?:will be|intends to|expects to|plans to)\b[^.]{0,80}\bfiled?\b[^.]{0,120}\bas an exhibit to\b[^.]{0,160}"
    r"(?:Form 10-Q|Form 10-K|Quarterly Report|Annual Report)[^.]*\.", re.I)


def label_of(exhibit_type):
    """"Exhibit 10.1" for EX-10.1, "Exhibit 10" for EX-10, None for any other type."""
    m = EXHIBIT_TYPE.match(exhibit_type or "")
    return (f"Exhibit 10.{m.group(1)}" if m.group(1) else "Exhibit 10") if m else None


def item_901_descriptions(paragraphs):
    """{"Exhibit 10.1": "Supply Agreement, dated ..."} from the exhibit table under Item 9.01 of the 8-K."""
    starts = [i for i, p in enumerate(paragraphs) if re.match(r"^item\s*9\.01\b", p.strip(), re.I) and len(p) < 200]
    descriptions = {}
    for start in starts[-1:]:
        for text in paragraphs[start + 1:start + 12]:
            if re.match(r"^signatures?\b", text.strip(), re.I):
                break
            for line in text.split("\n"):
                cells = [c.strip() for c in line.split(" | ")]
                m = EXHIBIT_NUMBER.match(cells[0]) if len(cells) >= 2 else None
                if m:  # a table row: "10.1 | Supply Agreement, dated ..."
                    number, description = m.group(1), " ".join(c for c in cells[1:] if c)
                else:  # a line: "10.1 Supply Agreement, dated ..."
                    m = EXHIBIT_LINE.match(line)
                    if not m:
                        continue
                    number, description = m.group(1), m.group(2)
                descriptions[f"Exhibit {number}" if "." in number else "Exhibit 10"] = description.strip()
    return descriptions


def decide(description):
    """("read", None), ("skip", reason) or ("unclear", None) from an exhibit's description: allow list, then skip list."""
    text = description or ""
    for term, unless in ALLOW:
        if term.search(text) and not (unless and unless.search(text)):
            return "read", None
    for reason, pattern in SKIP:
        if pattern.search(text):
            return "skip", reason
    return "unclear", None


def filed_later(paragraphs):
    """The 8-K's sentence saying the agreement will be filed with a later report, or None."""
    for text in paragraphs:
        m = FILED_LATER.search(text)
        if m:
            return " ".join(m.group(0).split())
    return None


def choose(description, paragraphs, label):
    """(decision read / partial / skipped, reason, tokens) for one downloaded exhibit, by the rules above; used by the
    job and by the exhibit evaluation set, so both decide alike."""
    decision, reason = decide(description)
    if decision == "skip":
        return "skipped", reason, None
    tokens = chunker.estimate_tokens("\n\n".join(paragraphs))
    if decision == "unclear" and tokens > UNCLEAR_MAX_TOKENS:
        return "skipped", "unclear description", tokens
    _, note = chunker.exhibit_plan(paragraphs, label)
    return ("partial" if note else "read"), note, tokens


def _record(conn, document_id, name, label, description, decision, reason=None, tokens=None, saved=None):
    conn.execute(
        """INSERT OR IGNORE INTO document_files (document_id, file_name, label, description, decision, reason, tokens, content_hash,
           size_bytes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (document_id, name, label, description, decision, reason, tokens, saved and saved["sha256"], saved and saved["size"], now()))


async def fetch_exhibits(conn, document_id, cik, accession, primary_document):
    """Looks at every exhibit 10.x of the filing once, downloads the ones worth reading and records each decision.
    Returns {read, partial, skipped: [(label, reason)], filed_later}."""
    document = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if document is None or not document["local_path"] or not Path(document["local_path"]).exists():
        raise Permanent(f"document {document_id} isn't downloaded")
    folder = Path(document["local_path"]).parent
    paragraphs = chunker.load_paragraphs(folder / primary_document)
    described = item_901_descriptions(paragraphs)
    later = filed_later(paragraphs)
    if later:
        conn.execute("UPDATE documents SET filed_later = ? WHERE id = ?", (later, document_id))
    seen = {r["file_name"] for r in conn.execute("SELECT file_name FROM document_files WHERE document_id = ?", (document_id,))}
    outcome = {"read": [], "partial": [], "skipped": [], "filed_later": later}
    for row in await sec_client.filing_index(cik, accession):
        label = label_of(row["type"])
        if not label or row["name"] == primary_document or row["name"] in seen:
            continue
        index_description = row["description"] if row["description"] and row["description"].upper() != row["type"].upper() else None
        description = described.get(label) or index_description
        decision, reason = decide(description)
        if decision == "skip":
            _record(conn, document_id, row["name"], label, description, "skipped", reason)
            outcome["skipped"].append((label, reason))
            continue
        saved = await sec_client.download(cik, accession, row["name"], folder=folder)
        decision, reason, tokens = choose(description, chunker.load_paragraphs(Path(saved["path"])), label)
        if decision == "skipped":  # unclear and long
            Path(saved["path"]).unlink()  # our own download: an unclear agreement this long isn't worth its cost
            _record(conn, document_id, row["name"], label, description, "skipped", reason, tokens, saved)
            outcome["skipped"].append((label, f"{reason}, about {tokens:,} tokens"))
            continue
        _record(conn, document_id, row["name"], label, description, decision, reason, tokens, saved)
        outcome[decision].append((label, reason or description or "no description"))
    return outcome


def describe(outcome):
    parts = []
    if outcome["read"]:
        parts.append(f"read {', '.join(label for label, _ in outcome['read'])}")
    if outcome["partial"]:
        parts.append(f"read part of {', '.join(label for label, _ in outcome['partial'])}")
    if outcome["skipped"]:
        parts.append("skipped " + ", ".join(f"{label} ({reason})" for label, reason in outcome["skipped"]))
    if outcome["filed_later"]:
        parts.append("agreement to be filed with a later report")
    return "; ".join(parts) or "no exhibit 10.x files"


@handler("exhibits")
async def exhibits_job(job, conn):
    p = job["payload"]
    try:
        outcome = await fetch_exhibits(conn, int(job["key"]), p["cik"], p["accession"], p["filename"])
    except sec_client.SecNotFound as exc:
        raise Permanent(str(exc)) from exc
    notes = describe(outcome)
    print(f"Supply chain: 8-K exhibits of document {job['key']}: {notes}")
    reader.queue_read(conn, int(job["key"]), "8-K", p.get("items"), job.get("company_id"), again=True)
    return {"notes": notes}


def queue_exhibits(conn, document_id, payload, company_id=None):
    """Queues the exhibits job of an 8-K with a material agreement (download job's payload: cik, accession, filename, items)."""
    jobs.enqueue(conn, "exhibits", str(document_id), payload, priority=PRIORITY, company_id=company_id, document_id=document_id)


def has_agreement(items):
    return bool(reader.AGREEMENT_ITEMS & set(items or []))


def queue_backfill(conn):
    """8-Ks downloaded before #322 with Item 1.01 or 1.02 whose exhibits were never looked at. Returns how many were queued."""
    rows = conn.execute(
        """SELECT d.id, d.company_id, j.payload FROM documents d JOIN jobs j ON j.kind = 'download' AND j.document_id = d.id
           WHERE d.kind = '8-K' AND d.status IN ('downloaded', 'processed')
             AND NOT EXISTS (SELECT 1 FROM jobs e WHERE e.kind = 'exhibits' AND e.key = CAST(d.id AS TEXT))""").fetchall()
    queued = 0
    with transaction(conn):
        for row in rows:
            payload = json.loads(row["payload"] or "{}")
            if has_agreement(payload.get("items")) and payload.get("cik") and payload.get("accession"):
                queue_exhibits(conn, row["id"], payload, row["company_id"])
                queued += 1
    return queued
