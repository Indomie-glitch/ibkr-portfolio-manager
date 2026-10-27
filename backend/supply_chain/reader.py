"""The Reader (#124): Claude reads each chunk of a filing (chunker.py, #123) and lists the supplier, customer and partner
relationships it states. Readers never write relationships: what they find is saved as candidates for the Verifier
(#125), and what fails the checks below goes to the rejected table.

One Claude call per chunk (config.READER_MODEL, structured output). After the call, in code:
- the quote must be in the chunk (only whitespace and quote characters are normalised);
- exactly one side is the filer, and the other is a different company named in the chunk, not a group ("our customers");
- the counterparty role must agree with the direction;
- a share must be 0-100 and its digits must be in the quote, else only the share is dropped (share_dropped says why);
- the counterparty's name is matched with resolver.resolve; one that can't be matched is rejected (unresolved_company).
  An unnamed one ("Customer A") is kept without a company: the Verifier creates its placeholder.

Job kind "read" (key = document id), queued when a download finishes for 10-Ks, 20-Fs and 8-Ks with Item 1.01 / 1.02.
Every chunk read is recorded in chunk_reads, so a job retried after a failure only pays for the chunks it hadn't read.
"""
import asyncio
import json
import re
from datetime import date
from pathlib import Path

import anthropic

import config
import usage_store
from supply_chain import chunker, db, graph, jobs, orchestrator, resolver, verifier
from supply_chain.db import now
from supply_chain.worker import Permanent, handler
from supply_chain.xbrl import GROUP_WORDS

FEATURE = "supply_chain_reader"
EFFORT = "medium"
MAX_TOKENS = 16000
TIMEOUT_S = 300
MAX_SPLITS = 2  # an answer cut off at MAX_TOKENS is read again as two halves, at most twice over
READ_PRIORITY = {"10-K": 45, "20-F": 45, "8-K": 40}  # below downloads (30-60) and XBRL (55) of the same filing; reading costs money
AGREEMENT_ITEMS = {"1.01", "1.02"}

SYSTEM_PROMPT = """You read one passage of a company's filing and list the business relationships it states between named \
companies: who supplies whom, and partnerships.

You are given the filer (the company whose filing this is), the form, the filing date and the section. "We", "our" \
and "the Company" mean the filer: use the filer's name and set is_filer.

Rules:
- Only what this passage states. Never add anything from your own knowledge, even if you know two companies do \
business together. If the passage doesn't say it, leave it out.
- Every relationship needs a quote: one or two consecutive sentences copied word for word from the passage (same \
words, numbers and punctuation) that state it. Tables appear as rows with cells separated by " | "; a row copied \
exactly as written ("Beta Corp | 48%") counts as a quote. No quote, no relationship.
- Direction: the supplier sells to the customer. "We manufacture our wafers at TSMC" means TSMC is the supplier and \
the filer the customer. "Sales to Apple were 23% of revenue" means the filer supplies Apple. counterparty_role is the \
other company's role for the filer: supplier, customer or partner (a joint venture, co-development or licensing deal \
where neither side simply sells to the other; then put the filer as supplier).
- Unnamed counterparties ("Customer A", "one distributor", "a major customer"): include them only when the passage \
gives a specific fact about that one counterparty (a share, a contract). Set unnamed and use the passage's label as \
the name ("Customer A", "a direct customer").
- Leave out groups and categories: "our customers include hyperscalers and OEMs", "we buy from a limited number of \
suppliers", "our top ten customers". Also leave out government agencies, regulators, lenders, auditors and the \
filer's own subsidiaries, and leases of office or data-centre space unless the passage names the other party.
- Only relationships that exist or existed. An agreement that is planned, proposed, being negotiated or being \
finalized, or that may not happen ("we are finalizing an agreement with", "we expect to enter into", "there is no \
assurance that we will enter into"), is not a relationship: leave it out.
- supplier_revenue_share: the percentage of the supplier's revenue from this customer, only if the passage gives the \
number. customer_supply_share: the percentage of what the customer buys (of customer_share_scope, e.g. "wafers", \
"total purchases") that comes from this supplier, only if the passage gives the number. Never estimate or calculate. \
"Substantially all" or "a significant portion" is not a number: leave the share null and copy the words into \
share_as_written.
- period_as_written: the date or period the statement refers to ("fiscal year 2026", "as of January 25, 2026"); \
stated_on: that date as YYYY-MM-DD when it is a specific day or period end, else null.
- ended: true only if the passage says the relationship has ended or will end (terminated, not renewed, expired, \
"we no longer").
- what: what is supplied, in the passage's words ("foundry services", "HBM3E memory"), or null.
- If the passage states no relationship, return an empty list."""

_NULLABLE_STRING = {"type": ["string", "null"]}
_NULLABLE_NUMBER = {"type": ["number", "null"]}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relationships"],
    "properties": {"relationships": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["supplier", "customer", "counterparty_role", "what", "quote", "supplier_revenue_share", "customer_supply_share",
                     "customer_share_scope", "share_as_written", "period_as_written", "stated_on", "ended"],
        "properties": {
            "supplier": {"$ref": "#/$defs/party"},
            "customer": {"$ref": "#/$defs/party"},
            "counterparty_role": {"type": "string", "enum": ["supplier", "customer", "partner"]},
            "what": _NULLABLE_STRING,
            "quote": {"type": "string"},
            "supplier_revenue_share": _NULLABLE_NUMBER,
            "customer_supply_share": _NULLABLE_NUMBER,
            "customer_share_scope": _NULLABLE_STRING,
            "share_as_written": _NULLABLE_STRING,
            "period_as_written": _NULLABLE_STRING,
            "stated_on": _NULLABLE_STRING,
            "ended": {"type": "boolean"},
        },
    }}},
    "$defs": {"party": {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "is_filer", "unnamed"],
        "properties": {"name": {"type": "string"}, "is_filer": {"type": "boolean"}, "unnamed": {"type": "boolean"}},
    }},
}


# ---------- Comparing with the text ----------

_QUOTE_CHARS = str.maketrans({"’": "'", "‘": "'", "‛": "'", "`": "'", "´": "'", "“": '"', "”": '"', "„": '"', "″": '"'})


def normalise(text):
    """Whitespace and quote characters only: the quote must otherwise be the passage's own words."""
    return " ".join(str(text or "").translate(_QUOTE_CHARS).split())


def locate(chunk, quote):
    """(first, last) indexes of the chunk's pieces (paragraphs) the quote is in, or None when it isn't in the chunk."""
    wanted = normalise(quote)
    if not wanted:
        return None
    pieces = chunk.text.split("\n\n")
    joined, starts = "", []
    for piece in pieces:
        starts.append(len(joined) + (1 if joined else 0))
        joined = f"{joined} {normalise(piece)}" if joined else normalise(piece)
    at = joined.find(wanted)
    if at < 0:
        return None
    end = at + len(wanted)
    first = max(i for i, s in enumerate(starts) if s <= at)
    last = max(i for i, s in enumerate(starts) if s < end)
    return first, last


def share_in_quote(value, quote):
    """The number as digits in the quote: 48 in "48%" or "48.0 percent", 12.5 in "12.5%"."""
    digits = f"{value:g}"
    return re.search(rf"(?<![\d.]){re.escape(digits)}(?:\.0+)?(?![\d])", normalise(quote).replace(",", "")) is not None


LEASE = re.compile(r"\b(?:sub)?(?:lease|leases|leased|leasing|license|licensed|licensing)\b[^.]*\bspace\b|\bspace\b[^.]*\b(?:sub)?(?:lease|leased|license|licensed)\b", re.IGNORECASE)


def is_group(name):
    """"our customers", "top ten distributors": a category, not one company."""
    return any(word in GROUP_WORDS for word in re.sub(r"[^a-z0-9 ]+", " ", name.lower()).split())


def _date(text):
    try:
        return date.fromisoformat(str(text)).isoformat() if text else None
    except ValueError:
        return None


# ---------- The checks ----------

class Refused(Exception):
    """A relationship that fails a check: goes to the rejected table with this reason."""
    def __init__(self, reason, detail):
        super().__init__(f"{reason}: {detail}")
        self.reason, self.detail = reason, detail


def check(answer, chunk, filer_name):
    """A relationship from the model as a candidate (without company ids), or raises Refused."""
    quote = " ".join(str(answer.get("quote") or "").split())
    where = locate(chunk, quote)
    if where is None:
        raise Refused("quote_not_found", "the quote isn't in the passage")
    supplier, customer = answer["supplier"], answer["customer"]
    if supplier["is_filer"] == customer["is_filer"]:
        raise Refused("not_about_filer", "both sides are the filer" if supplier["is_filer"] else "neither side is the filer")
    role = answer["counterparty_role"]
    if role == "partner":
        if customer["is_filer"]:  # stored with the filer as supplier: a partnership has no direction
            supplier, customer = customer, supplier
    elif (role == "supplier") != customer["is_filer"]:
        raise Refused("direction_mismatch", f"counterparty_role {role} disagrees with who is supplier")
    counterparty = customer if supplier["is_filer"] else supplier
    name = " ".join(str(counterparty["name"] or "").split())
    if not name:
        raise Refused("no_name", "the counterparty has no name")
    if is_group(name):  # before the unnamed test: "our customers" would pass as an unnamed customer
        raise Refused("generic_counterparty", f"{name!r} is a group, not one company")
    unnamed = bool(counterparty["unnamed"]) or resolver.is_unnamed(name)
    if not unnamed and normalise(name).lower() not in normalise(chunk.text).lower():
        raise Refused("name_not_in_text", f"{name!r} isn't in the passage")

    shares, dropped = {}, []
    for field in ("supplier_revenue_share", "customer_supply_share"):
        value = answer.get(field)
        if value is None:
            shares[field] = None
        elif not 0 <= value <= 100:
            shares[field] = None
            dropped.append(f"{field}: out_of_range")
        elif not share_in_quote(value, quote):
            shares[field] = None
            dropped.append(f"{field}: digits_not_in_quote")
        else:
            shares[field] = float(value)
    if unnamed and shares["supplier_revenue_share"] is None and shares["customer_supply_share"] is None and LEASE.search(quote):
        raise Refused("unnamed_lease", "a lease of space from or to an unnamed party, with no share: nothing to link")

    pieces = chunk.text.split("\n\n")
    first, last = where
    numbers = chunk.numbers or [chunk.first_paragraph] * len(pieces)
    names = {"supplier": filer_name if supplier["is_filer"] else name, "customer": filer_name if customer["is_filer"] else name}
    return {
        "kind": "partnership" if role == "partner" else "supplies",
        "counterparty_role": role,
        "supplier_name": names["supplier"], "customer_name": names["customer"],
        "supplier_is_filer": int(supplier["is_filer"]), "customer_is_filer": int(customer["is_filer"]),
        "supplier_unnamed": int(unnamed and not supplier["is_filer"]), "customer_unnamed": int(unnamed and not customer["is_filer"]),
        "counterparty": name, "unnamed": unnamed,
        "what": answer.get("what") or None,
        "supplier_revenue_share": shares["supplier_revenue_share"],
        "customer_supply_share": shares["customer_supply_share"],
        "customer_share_scope": (answer.get("customer_share_scope") or None) if shares["customer_supply_share"] is not None else None,
        "share_as_written": answer.get("share_as_written") or None,
        "share_dropped": "; ".join(dropped) or None,
        "period_as_written": answer.get("period_as_written") or None,
        "stated_on": _date(answer.get("stated_on")),
        "ended": int(bool(answer.get("ended"))),
        "quote": quote,
        "locator": chunker.locator_for(chunk.section, numbers[first], numbers[last]),
        "context": "\n\n".join(pieces[max(0, first - 1):last + 2]),
    }


# ---------- Calling Claude ----------

def user_message(filer, document, chunk):
    who = f"{filer['name']} ({filer['ticker']})" if filer.get("ticker") else filer["name"]
    period = f", period {document['period_end']}" if document.get("period_end") else ""
    return "\n".join([f"Filer: {who}", f"Form: {document['kind']}, filed {document['filed_at']}{period}",
                      f"Section: {chunk.locator}", "", "Passage:", chunk.text])


def _halves(chunk):
    """The chunk as two smaller chunks (by paragraphs, or a single paragraph cut at sentence ends)."""
    pieces = chunk.text.split("\n\n")
    numbers = chunk.numbers or [chunk.first_paragraph] * len(pieces)
    if len(pieces) == 1:
        parts = chunker.split_text(chunk.text, max(1, chunk.tokens // 2))
        groups = [([p], [numbers[0]]) for p in parts]
    else:
        middle = len(pieces) // 2
        groups = [(pieces[:middle], numbers[:middle]), (pieces[middle:], numbers[middle:])]
    halves = []
    for texts, nums in groups:
        text = "\n\n".join(texts)
        halves.append(chunker.Chunk(chunk.document, chunk.section, text, chunker.estimate_tokens(text), nums[0], nums[-1],
                                    number=chunk.number, numbers=nums))
    return halves


async def extract(client, filer, document, chunk, splits=0, charge=None):
    """[(relationship, the piece of the chunk it was read from)] and the calls' usage [{input_tokens, output_tokens,
    outcome}]. An answer cut off by MAX_TOKENS is read again in halves; a refusal reads as nothing found. charge(usage) is
    called as soon as each call is made, so what a job spends is on its run even if it fails afterwards."""
    response = await orchestrator.gate().call(lambda: client.messages.create(
        model=config.READER_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message(filer, document, chunk)}],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
    ))
    usage = [{"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens,
              "outcome": "ok" if response.stop_reason == "end_turn" else response.stop_reason}]
    if charge:
        charge(usage)
    if response.stop_reason == "max_tokens" and splits < MAX_SPLITS:
        found = []
        for half in _halves(chunk):
            more, more_usage = await extract(client, filer, document, half, splits + 1, charge)
            found += more
            usage += more_usage
        return found, usage
    if response.stop_reason == "refusal":
        return [], usage
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"chunk {chunk.number}: answer stopped early ({response.stop_reason})")
    text = next(b.text for b in response.content if b.type == "text")
    return [(r, chunk) for r in json.loads(text).get("relationships", [])], usage


def _record_usage(usage):
    for call in usage:
        usage_store.record(FEATURE, config.READER_MODEL, call, outcome=call["outcome"])


def _cost(usage):
    costs = [usage_store.cost_usd(config.READER_MODEL, u["input_tokens"], u["output_tokens"]) for u in usage]
    return sum(c for c in costs if c is not None)


# ---------- Reading a document ----------

def filer_of(conn, company_id):
    row = conn.execute("SELECT id, name FROM companies WHERE id = ?", (company_id,)).fetchone()
    ticker = conn.execute("SELECT value FROM identifiers WHERE company_id = ? AND scheme = 'ticker' ORDER BY market = 'US' DESC, id LIMIT 1",
                          (company_id,)).fetchone()
    return {"id": row["id"], "name": row["name"], "ticker": ticker["value"] if ticker else None}


def _already_read(conn, document_id, chunk):
    row = conn.execute("SELECT text_hash FROM chunk_reads WHERE document_id = ? AND chunker_version = ? AND chunk_number = ?",
                       (document_id, chunker.CHUNKER_VERSION, chunk.number)).fetchone()
    return row is not None and row["text_hash"] == graph.text_hash(chunk.text)


async def _outcomes(conn, found, filer, resolve):
    """Each relationship checked and its counterparty matched: [("candidate", row) or ("rejected", reason, detail, answer)].
    Raises when the name lookup is unavailable (the job is retried; chunks already saved aren't read again)."""
    outcomes = []
    for answer, piece in found:
        try:
            row = check(answer, piece, filer["name"])
        except (Refused, KeyError, TypeError) as exc:
            reason, detail = (exc.reason, exc.detail) if isinstance(exc, Refused) else ("malformed", f"{exc.__class__.__name__}")
            outcomes.append(("rejected", reason, detail, answer))
            continue
        side = "customer" if row["supplier_is_filer"] else "supplier"
        row["supplier_id" if side == "customer" else "customer_id"] = filer["id"]
        row[f"{side}_id"] = None
        row["resolved_by"] = None
        row["supplier_private"] = row["customer_private"] = 0
        if not row["unnamed"]:
            match = await resolve(conn, row["counterparty"])
            if match["status"] == "unavailable":
                raise RuntimeError(f"name lookup unavailable for {row['counterparty']}: {match.get('detail')}")
            if resolver.can_be_private(row["counterparty"], match):  # kept for the Verifier; the company is made only if it confirms
                row[f"{side}_private"], row["resolved_by"] = 1, "private_pending"
                outcomes.append(("candidate", row))
                continue
            if match["status"] != "matched":
                outcomes.append(("rejected", "unresolved_company", f"{match.get('reason')}: {match.get('detail') or ''}".strip(": "), answer, row))
                continue
            if match["company_id"] == filer["id"]:
                outcomes.append(("rejected", "same_company", f"{row['counterparty']} is the filer", answer, row))
                continue
            row[f"{side}_id"], row["resolved_by"] = match["company_id"], match["method"]
        outcomes.append(("candidate", row))
    return outcomes


CANDIDATE_COLUMNS = ("kind", "counterparty_role", "supplier_name", "customer_name", "supplier_is_filer", "customer_is_filer",
                     "supplier_unnamed", "customer_unnamed", "supplier_private", "customer_private", "supplier_id", "customer_id", "resolved_by", "what",
                     "supplier_revenue_share", "customer_supply_share", "customer_share_scope", "share_as_written", "share_dropped",
                     "period_as_written", "stated_on", "ended", "quote", "locator", "context")


def _save(conn, document_id, chunk, outcomes, usage, found_count, run_id):
    """The chunk's read, its candidates and its rejections, in one transaction. Returns (new candidates, rejected)."""
    added = rejected = 0
    stamp = now()
    with db.transaction(conn):
        conn.execute("DELETE FROM chunk_reads WHERE document_id = ? AND chunker_version = ? AND chunk_number = ?",
                     (document_id, chunker.CHUNKER_VERSION, chunk.number))  # a changed chunk is read again
        read_id = conn.execute(
            """INSERT INTO chunk_reads (document_id, chunker_version, chunk_number, locator, text_hash, run_id, model, input_tokens,
               output_tokens, cost_usd, found, read_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (document_id, chunker.CHUNKER_VERSION, chunk.number, chunk.locator, graph.text_hash(chunk.text), run_id, config.READER_MODEL,
             sum(u["input_tokens"] for u in usage), sum(u["output_tokens"] for u in usage), _cost(usage), found_count, stamp)).lastrowid
        for outcome in outcomes:
            if outcome[0] == "candidate":
                row = outcome[1]
                digest = graph.text_hash(row["supplier_name"], row["customer_name"], row["kind"], row["quote"])
                cursor = conn.execute(
                    f"""INSERT OR IGNORE INTO candidates (document_id, chunk_read_id, run_id, {", ".join(CANDIDATE_COLUMNS)}, candidate_hash,
                        created_at, updated_at) VALUES ({", ".join("?" * (len(CANDIDATE_COLUMNS) + 6))})""",
                    (document_id, read_id, run_id, *(row[c] for c in CANDIDATE_COLUMNS), digest, stamp, stamp))
                added += cursor.rowcount
            else:
                _, reason, detail, answer, *checked = outcome
                row = checked[0] if checked else {}
                names = {side: row.get(f"{side}_name") or (answer.get(side) or {}).get("name") for side in ("supplier", "customer")}
                graph.reject(conn, document_id, " ".join(str(answer.get("quote") or "").split()) or "(no quote given)", reason, "rule",
                             supplier_name=names["supplier"], customer_name=names["customer"],
                             supplier_id=row.get("supplier_id"), customer_id=row.get("customer_id"), detail=detail, payload=answer, run_id=run_id)
                rejected += 1
    return added, rejected


async def read_document(conn, document_id, client=None, resolve=None, run_id=None):
    """Reads every chunk of a downloaded document not read yet. Returns {chunks, skipped, candidates, rejected, declined,
    input_tokens, output_tokens, cost_usd}."""
    document = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if document is None:
        raise Permanent(f"no document {document_id}")
    if document["status"] not in ("downloaded", "processed") or not document["local_path"] or not Path(document["local_path"]).exists():
        raise Permanent(f"document {document_id} isn't downloaded")
    if document["company_id"] is None:
        raise Permanent(f"document {document_id} has no filer")
    path = Path(document["local_path"])
    chunks = await asyncio.to_thread(chunker.chunk_filing, path.parent, document["kind"], path.name, document["source"])
    filer = filer_of(conn, document["company_id"])
    resolve = resolve or resolver.resolve
    totals = {"chunks": len(chunks), "skipped": 0, "candidates": 0, "rejected": 0, "declined": 0, "deferred": None,
              "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    for chunk in chunks:
        if _already_read(conn, document_id, chunk):
            totals["skipped"] += 1
            continue
        reservation = orchestrator.reserve(conn, orchestrator.read_estimate(conn, chunk.tokens))
        if not reservation.ok:  # today's allowance (or the month's) can't take this chunk: the rest waits
            totals["deferred"] = reservation
            break
        if client is None:
            if not config.anthropic_api_key():
                reservation.release()
                raise RuntimeError("no Anthropic API key")  # retried: the key may be added in Settings
            client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key(), timeout=TIMEOUT_S)
        with reservation:
            found, usage = await extract(client, filer, dict(document), chunk,
                                         charge=lambda calls: orchestrator.charge(conn, run_id, [{**c, "model": config.READER_MODEL} for c in calls]))
        await asyncio.to_thread(_record_usage, usage)
        totals["input_tokens"] += sum(u["input_tokens"] for u in usage)
        totals["output_tokens"] += sum(u["output_tokens"] for u in usage)
        totals["cost_usd"] += _cost(usage)
        totals["declined"] += any(u["outcome"] == "refusal" for u in usage)
        outcomes = await _outcomes(conn, found, filer, resolve)
        added, rejected = _save(conn, document_id, chunk, outcomes, usage, len(found), run_id)
        totals["candidates"] += added
        totals["rejected"] += rejected
    if totals["deferred"] is None:
        conn.execute("UPDATE documents SET status = 'processed' WHERE id = ? AND status = 'downloaded'", (document_id,))
    return totals


# ---------- The job ----------

def should_read(form, items=None):
    """10-Ks and 20-Fs; 8-Ks only with a material agreement (or when the items aren't known: the chunker then finds nothing
    to read in one about something else, so no call is made)."""
    if form not in READ_PRIORITY:
        return False
    return form != "8-K" or items is None or bool(AGREEMENT_ITEMS & set(items))


def queue_read(conn, document_id, form, items=None, company_id=None):
    """Queues the read of a downloaded document once (a document already read, or queued, isn't queued again)."""
    if not should_read(form, items) or conn.execute("SELECT 1 FROM jobs WHERE kind = 'read' AND key = ?", (str(document_id),)).fetchone():
        return False
    jobs.enqueue(conn, "read", str(document_id), {"form": form}, priority=READ_PRIORITY[form], company_id=company_id, document_id=document_id)
    return True


def queue_unread(conn):
    """Queues reads for documents downloaded before the Reader existed (or whose read was never queued). Returns how many."""
    rows = conn.execute(
        f"""SELECT d.id, d.kind, d.company_id FROM documents d WHERE d.status = 'downloaded' AND d.kind IN ({", ".join("?" * len(READ_PRIORITY))})
            AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.kind = 'read' AND j.key = CAST(d.id AS TEXT))""", tuple(READ_PRIORITY)).fetchall()
    return sum(queue_read(conn, row["id"], row["kind"], company_id=row["company_id"]) for row in rows)


@handler("read")
async def read_job(job, conn):
    totals = await read_document(conn, int(job["key"]), run_id=job.get("run_id"))
    verifier.queue_verify(conn, int(job["key"]), job.get("company_id"))  # the Verifier (#125) checks what was found
    if not totals["chunks"]:
        return {"notes": "nothing to read"}
    notes = (f"{totals['chunks']} chunks ({totals['skipped']} read before), {totals['candidates']} candidates, "
             f"{totals['rejected']} rejected" + (f", {totals['declined']} declined" if totals["declined"] else ""))
    result = {"notes": notes, "model": config.READER_MODEL, "input_tokens": totals["input_tokens"],
              "output_tokens": totals["output_tokens"], "cost_usd": round(totals["cost_usd"], 6)}
    if totals["deferred"] is not None:  # the worker queues the rest again for when the allowance allows (orchestrator.requeue_later)
        result["notes"] += f"; the rest {totals['deferred'].reason}"
        result["defer_until"], result["defer_reason"] = totals["deferred"].until, totals["deferred"].reason
    return result
