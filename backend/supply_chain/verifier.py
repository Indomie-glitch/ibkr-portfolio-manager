"""The Verifier (#125): an independent second check of each Reader candidate (reader.py, #124) before it enters the graph.

It sees only the claim, written here from the candidate's stored fields (companies, direction, kind, what, shares,
period, ended), and the candidate's context paragraph. Never the Reader's prompt, reasoning or other candidates' wording.
One call checks a batch of one document's candidates (up to BATCH_ITEMS, about BATCH_TOKENS), each a numbered item
judged only against its own context. Model: config.VERIFIER_MODEL, structured output, with Anthropic's server-side
refusal fallback; the model that actually answered is the one recorded and priced.

Verdicts:
- supported: the relationship and its evidence are written (graph.add_relationship: tier 2, extractor reader,
  verification verified, verified_by = the answering model). An existing link gets the evidence added.
- partly_supported: if the supplier, customer, direction or kind is unsupported, the link itself is, so it is rejected;
  otherwise it is written with only the supported fields.
- not_supported: the rejected table (rejected_by verifier) with the reason.
An unnamed counterparty ("Customer A") becomes a placeholder company the way xbrl.py makes them (per filer, label and
period), so the merge (#127) can later upgrade it. Job kind "verify" (key = document id), queued when a read finds candidates.
"""
import json
from datetime import datetime, timedelta, timezone

import anthropic

import config
import usage_store
from supply_chain import chunker, graph, jobs, orchestrator, reader, resolver, xbrl
from supply_chain.jobs import _iso
from supply_chain.db import now
from supply_chain.worker import Permanent, handler

FEATURE = "supply_chain_verifier"
EFFORT = "medium"
MAX_TOKENS = 16000
TIMEOUT_S = 300
BATCH_ITEMS = 10
BATCH_TOKENS = 20_000
MAX_VERIFY_ATTEMPTS = 2  # a candidate still unchecked after a check is tried once more ...
RETRY_AFTER = timedelta(days=3)  # ... this long after, then left for Needs attention (never in a paid loop)
VERIFY_PRIORITY = 46  # above reads (40-45): each document is verified before the next is read, so links appear steadily
FALLBACK_BETA = "server-side-fallback-2026-07-01"
TIER = 2
EXTRACTOR = "reader"

FIELDS = ("supplier", "customer", "direction", "kind", "what", "supplier_revenue_share", "customer_supply_share",
          "customer_share_scope", "period", "ended")
LINK_FIELDS = {"supplier", "customer", "direction", "kind"}  # unsupported, the link itself is
VERDICTS = ("supported", "partly_supported", "not_supported")

SYSTEM_PROMPT = """You check claims about business relationships against passages from company filings.

Each item has one claim and one context passage. Judge each item only against its own context: ignore every other \
item, and never use your own knowledge, even about well-known companies. If the context doesn't state it, it isn't \
supported.

For each item give:
- verdict: "supported" if the context states everything in the claim; "partly_supported" if it states the \
relationship but not every detail; "not_supported" if it doesn't state this relationship between these companies.
- unsupported_fields: every field of the claim the context doesn't support:
  - supplier / customer: the context doesn't name (or, for an unnamed one, describe) that company in that role;
  - direction: the context says the other company sells to the first, or doesn't say who sells to whom;
  - kind: a supply relationship is claimed but the context describes a partnership, or the other way round;
  - what: what is supplied isn't what the context says;
  - supplier_revenue_share / customer_supply_share: the context doesn't state that number for that measure (a number \
for a different measure, year or company doesn't count; "substantially all" is not a number);
  - customer_share_scope: the share isn't of what the claim says;
  - period: the context doesn't say the statement is about that date or period;
  - ended: the claim says the relationship ended (or is ongoing) and the context doesn't say so.
  Empty when supported.
- "Customer 2 of 4" means the second of the unnamed counterparties the context lists, in its order. Its share must be \
the one the context gives that counterparty alone; a total for several together ("top three customers were 40%") \
supports no single one, so the share is unsupported. For a table row, the period is the column's header.
- An agreement the context describes as planned, proposed, being negotiated or being finalized, or one it says may \
not happen ("there is no assurance that we will enter into"), is not a relationship: not_supported. Only relationships \
that exist or existed count.
- reason: one short sentence saying what the context does or doesn't say."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdicts"],
    "properties": {"verdicts": {"type": "array", "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["item", "verdict", "unsupported_fields", "reason"],
        "properties": {
            "item": {"type": "integer"},
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "unsupported_fields": {"type": "array", "items": {"type": "string", "enum": list(FIELDS)}},
            "reason": {"type": "string"},
        },
    }}},
}


# ---------- The claim, from the stored fields ----------

def _party(candidate, side):
    name = candidate[f"{side}_name"]
    numbered = reader.NUMBERED.match(name) if candidate[f"{side}_unnamed"] else None
    if numbered:  # "Customer 2 of 4": the Reader's numbering of a sentence that gives a share for each (#341)
        number, count = name.split()[1], name.split()[3]
        return f"{name} (unnamed: number {number} of the {count} unnamed counterparties the passage gives a share for, in its order)"
    return f"{name} (unnamed in the passage)" if candidate[f"{side}_unnamed"] else name


def claim_lines(candidate):
    supplier, customer = _party(candidate, "supplier"), _party(candidate, "customer")
    if candidate["kind"] == "partnership":
        lines = [f"{supplier} and {customer} are partners (a joint venture, co-development or licensing deal, not one simply "
                 f"selling to the other)."]
    else:
        lines = [f"{supplier} (supplier) sells to {customer} (customer)."]
    if candidate["what"]:
        lines.append(f"What is supplied: {candidate['what']}")
    if candidate["supplier_revenue_share"] is not None:
        lines.append(f"Share of {supplier}'s revenue from {customer}: {candidate['supplier_revenue_share']:g}%")
    if candidate["customer_supply_share"] is not None:
        scope = candidate["customer_share_scope"] or "what it buys"
        lines.append(f"Share of {customer}'s {scope} that comes from {supplier}: {candidate['customer_supply_share']:g}%")
    period = " ".join(p for p in (candidate["period_as_written"], f"({candidate['stated_on']})" if candidate["stated_on"] else None) if p)
    if period:
        lines.append(f"Period: {period}")
    lines.append("Ended: the relationship has ended or will end." if candidate["ended"] else "Ended: no (the relationship is not said to have ended).")
    return lines


def item_text(number, candidate):
    return "\n".join([f"Item {number}", "Claim:", *claim_lines(candidate), "Context:", "<<<", candidate["context"], ">>>"])


def batches(candidates, max_items=BATCH_ITEMS, max_tokens=BATCH_TOKENS):
    """Candidates in groups of at most max_items and about max_tokens (a single bigger one goes alone)."""
    groups, current, size = [], [], 0
    for candidate in candidates:
        tokens = chunker.estimate_tokens(item_text(0, candidate))
        if current and (len(current) >= max_items or size + tokens > max_tokens):
            groups.append(current)
            current, size = [], 0
        current.append(candidate)
        size += tokens
    if current:
        groups.append(current)
    return groups


# ---------- Calling Claude ----------

def _attempts(response):
    """[{model, input_tokens, output_tokens}] for every attempt the call made (a fallback adds one), from usage.iterations
    when the API gives it, else the top-level usage of the model that answered."""
    iterations = getattr(response.usage, "iterations", None) or []
    attempts = [{"model": getattr(i, "model", None) or response.model, "input_tokens": i.input_tokens, "output_tokens": i.output_tokens}
                for i in iterations if getattr(i, "input_tokens", None) is not None]
    return attempts or [{"model": response.model, "input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}]


async def judge(client, group, splits=0, charge=None):
    """({candidate id: verdict}, the model that answered (None if it declined), attempts). A cut-off answer is asked again in
    halves. charge(attempts) is called as soon as each call is made, so what a job spends is on its run even if it fails afterwards."""
    numbered = {n: c for n, c in enumerate(group, 1)}
    response = await orchestrator.gate().call(lambda: client.beta.messages.create(
        model=config.VERIFIER_MODEL,
        max_tokens=MAX_TOKENS,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n\n".join(item_text(n, c) for n, c in numbered.items())}],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
    ))
    attempts = _attempts(response)
    outcome = "ok" if response.stop_reason == "end_turn" else response.stop_reason
    for attempt in attempts:
        attempt["outcome"] = outcome
    if charge:
        charge(attempts)
    if response.stop_reason == "max_tokens" and len(group) > 1 and splits < 3:
        middle = len(group) // 2
        verdicts, models = {}, []
        for half in (group[:middle], group[middle:]):
            more, model, more_attempts = await judge(client, half, splits + 1, charge)
            verdicts.update(more)
            models.append(model)
            attempts += more_attempts
        return verdicts, next((m for m in models if m), None), attempts
    if response.stop_reason == "refusal":
        return {}, None, attempts
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"verifier answer stopped early ({response.stop_reason})")
    text = next(b.text for b in response.content if b.type == "text")
    verdicts = {}
    for entry in json.loads(text).get("verdicts", []):
        candidate = numbered.get(entry.get("item"))
        if candidate is not None and entry.get("verdict") in VERDICTS and candidate["id"] not in verdicts:
            verdicts[candidate["id"]] = {"verdict": entry["verdict"], "reason": " ".join(str(entry.get("reason") or "").split()),
                                         "unsupported_fields": sorted({f for f in entry.get("unsupported_fields") or [] if f in FIELDS})}
    return verdicts, response.model, attempts


def _record(attempts):
    for attempt in attempts:
        usage_store.record(FEATURE, attempt["model"], attempt, outcome=attempt["outcome"])


def _cost(attempts):
    costs = [usage_store.cost_usd(a["model"], a["input_tokens"], a["output_tokens"]) for a in attempts]
    return sum(c for c in costs if c is not None)


# ---------- Applying a verdict ----------

def _period_end(conn, candidate):
    document = conn.execute("SELECT period_end, filed_at FROM documents WHERE id = ?", (candidate["document_id"],)).fetchone()
    return candidate["stated_on"] or document["period_end"] or document["filed_at"]


def placeholder_label(conn, candidate, side):
    """The label a Reader placeholder is kept under: the filing's own words plus the filing (#341). Labels are per filing
    and period only: "Customer 1 of 4" or "Customer B" in the 2025 10-K and in the 2024 10-K are not taken for the same
    company (CoreWeave: "the customer references of A through D may represent different customers than those reported in a
    previous period"); two that are the same can still be joined by their share (merge.join_placeholders)."""
    document = conn.execute("SELECT kind, filed_at FROM documents WHERE id = ?", (candidate["document_id"],)).fetchone()
    filing = " ".join(p for p in (document["kind"], f"filed {document['filed_at']}" if document["filed_at"] else None) if p)
    return f"{candidate[f'{side}_name']} in the {filing}" if filing else candidate[f"{side}_name"]


def counterparty_ids(conn, candidate):
    """(supplier id, customer id), making the placeholder company for an unnamed counterparty as xbrl.py does."""
    ids = {"supplier": candidate["supplier_id"], "customer": candidate["customer_id"]}
    for side in ("supplier", "customer"):
        if ids[side] is None and candidate[f"{side}_private"]:  # confirmed by the Verifier: now the private company may exist (#334)
            ids[side] = resolver.private_company(conn, candidate[f"{side}_name"])
        if ids[side] is None and candidate[f"{side}_unnamed"]:
            filer_side = "customer" if side == "supplier" else "supplier"
            filer_id = ids[filer_side]
            filer_name = conn.execute("SELECT name FROM companies WHERE id = ?", (filer_id,)).fetchone()["name"]
            ids[side] = xbrl.placeholder(conn, filer_id, filer_name, {"label": placeholder_label(conn, candidate, side), "end": _period_end(conn, candidate)}, side)
    return ids["supplier"], ids["customer"]


def link(conn, candidate, verdict, model, run_id=None):
    """Writes a supported (or partly supported) candidate as a relationship with its evidence. Returns the relationship id."""
    unsupported = set(verdict["unsupported_fields"])
    keep = {field: candidate[field] if field not in unsupported else None
            for field in ("what", "supplier_revenue_share", "customer_supply_share", "customer_share_scope")}
    if keep["customer_supply_share"] is None:
        keep["customer_share_scope"] = None
    stated_on = candidate["stated_on"] if "period" not in unsupported else None
    notes = [n for n in (candidate["share_as_written"] and f"as written: {candidate['share_as_written']}",
                         candidate["share_dropped"] and f"dropped by the Reader: {candidate['share_dropped']}",
                         unsupported and f"not supported by the passage: {', '.join(sorted(unsupported))}") if n]
    evidence = {"document_id": candidate["document_id"], "quote": candidate["quote"], "tier": TIER, "extractor": EXTRACTOR,
                "locator": candidate["locator"], "stated_on": stated_on,
                "supplier_revenue_share": keep["supplier_revenue_share"], "customer_supply_share": keep["customer_supply_share"],
                "customer_share_scope": keep["customer_share_scope"], "share_note": "; ".join(notes) or None,
                "verification": "verified", "verified_by": model,
                "states_ended": int(bool(candidate["ended"]) and "ended" not in unsupported), "run_id": run_id}
    supplier_id, customer_id = counterparty_ids(conn, candidate)
    # shares, confidence, dates and status are set from all of the link's evidence by the merge rules (merge.refresh)
    relationship_id = graph.add_relationship(conn, supplier_id, customer_id, evidence, kind=candidate["kind"], what=keep["what"],
                                             supplier_revenue_share=keep["supplier_revenue_share"],
                                             customer_supply_share=keep["customer_supply_share"],
                                             customer_share_scope=keep["customer_share_scope"], shares_as_of=stated_on)
    return relationship_id


def apply(conn, candidate, verdict, model, run_id=None):
    """Links, or rejects, one candidate by its verdict; returns "linked" or "rejected"."""
    stored = json.dumps({**verdict, "model": model})
    unsupported_link = LINK_FIELDS & set(verdict["unsupported_fields"])
    if verdict["verdict"] == "not_supported" or unsupported_link:
        reason = "not_supported" if verdict["verdict"] == "not_supported" else "partly_supported_link"
        detail = verdict["reason"] + (f" (unsupported: {', '.join(sorted(unsupported_link))})" if unsupported_link else "")
        graph.reject(conn, candidate["document_id"], candidate["quote"], reason, "verifier",
                     supplier_name=candidate["supplier_name"], customer_name=candidate["customer_name"],
                     supplier_id=candidate["supplier_id"], customer_id=candidate["customer_id"], detail=detail,
                     payload={k: candidate[k] for k in candidate.keys() if k not in ("context",)}, run_id=run_id)
        conn.execute("UPDATE candidates SET status = ?, verdict = ?, verified_run_id = ?, updated_at = ? WHERE id = ?",
                     (verdict["verdict"], stored, run_id, now(), candidate["id"]))
        return "rejected"
    relationship_id = link(conn, candidate, verdict, model, run_id)
    conn.execute("UPDATE candidates SET status = 'linked', verdict = ?, verified_run_id = ?, relationship_id = ?, updated_at = ? WHERE id = ?",
                 (stored, run_id, relationship_id, now(), candidate["id"]))
    return "linked"


# ---------- Verifying a document ----------

# Pending candidates the Verifier may check now: not given up on, and not waiting after an unanswered check
DUE = "status = 'pending' AND verify_attempts < ? AND (verify_after IS NULL OR verify_after <= ?)"


def _now(now=None):
    return now or datetime.now(timezone.utc)


def unchecked_count(conn):
    """Candidates the Verifier gave up on (Needs attention)."""
    return conn.execute("SELECT COUNT(*) FROM candidates WHERE status = 'pending' AND verify_attempts >= ?", (MAX_VERIFY_ATTEMPTS,)).fetchone()[0]


def retry_unchecked(conn, company_id):
    """Gives the company's unchecked candidates fresh attempts and queues their documents. Returns how many candidates."""
    rows = conn.execute(
        """SELECT c.id, c.document_id FROM candidates c JOIN documents d ON d.id = c.document_id
           WHERE d.company_id = ? AND c.status = 'pending' AND c.verify_attempts >= ?""", (company_id, MAX_VERIFY_ATTEMPTS)).fetchall()
    for row in rows:
        conn.execute("UPDATE candidates SET verify_attempts = 0, verify_after = NULL, updated_at = ? WHERE id = ?", (now(), row["id"]))
    for document_id in {row["document_id"] for row in rows}:
        queue_verify(conn, document_id, company_id)
    return len(rows)


async def verify_document(conn, document_id, client=None, run_id=None, now_at=None):
    """Checks every due pending candidate of a document. One still unchecked afterwards (the whole fallback chain declined,
    or the answer skipped it twice) counts an attempt and waits RETRY_AFTER. Returns {candidates, linked, rejected,
    declined, unanswered, models, input_tokens, output_tokens, cost_usd}."""
    moment = _now(now_at)
    pending = conn.execute(f"SELECT * FROM candidates WHERE document_id = ? AND {DUE} ORDER BY id",
                           (document_id, MAX_VERIFY_ATTEMPTS, _iso(moment))).fetchall()
    totals = {"candidates": len(pending), "linked": 0, "rejected": 0, "declined": 0, "unanswered": 0, "models": [], "deferred": None,
              "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    attempted = set()  # candidates a call was made for: only those use up one of their attempts
    if not pending:
        return totals
    if client is None:
        if not config.anthropic_api_key():
            raise RuntimeError("no Anthropic API key")  # retried: the key may be added in Settings
        client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key(), timeout=TIMEOUT_S)

    async def run_batch(group):
        """The candidates the answer skipped; None when today's allowance can't take the call (the rest waits)."""
        tokens = sum(chunker.estimate_tokens(item_text(0, c)) for c in group)
        reservation = orchestrator.reserve(conn, orchestrator.verify_estimate(tokens, len(group)), moment)
        if not reservation.ok:
            totals["deferred"] = reservation
            return None
        with reservation:
            verdicts, model, attempts = await judge(
                client, group, charge=lambda calls: orchestrator.charge(conn, run_id, calls))
        attempted.update(c["id"] for c in group)
        _record(attempts)
        totals["input_tokens"] += sum(a["input_tokens"] for a in attempts)
        totals["output_tokens"] += sum(a["output_tokens"] for a in attempts)
        totals["cost_usd"] += _cost(attempts)
        for attempt in attempts:
            if attempt["model"] not in totals["models"] and attempt["outcome"] != "refusal":
                totals["models"].append(attempt["model"])
        if model is None:
            totals["declined"] += len(group)
            return []
        for candidate in group:
            if candidate["id"] in verdicts:
                totals[apply(conn, candidate, verdicts[candidate["id"]], model, run_id)] += 1
        return [c for c in group if c["id"] not in verdicts]

    missed = []
    for group in batches(pending):
        skipped = await run_batch(group)
        if skipped is None:
            break
        missed += skipped
    for candidate in missed:  # an item the answer skipped is asked about on its own, once
        again = await run_batch([candidate])
        if again is None:
            break
        if again:
            totals["unanswered"] += 1
    if attempted:
        conn.execute(
            f"""UPDATE candidates SET verify_attempts = verify_attempts + 1, verify_after = ?, updated_at = ?
                WHERE status = 'pending' AND id IN ({", ".join("?" * len(attempted))})""",
            (_iso(moment + RETRY_AFTER), now(), *attempted))
    return totals


def queue_verify(conn, document_id, company_id=None, now_at=None):
    """Queues the check of a document's due candidates (once while one is open)."""
    if not conn.execute(f"SELECT 1 FROM candidates WHERE document_id = ? AND {DUE} LIMIT 1",
                        (document_id, MAX_VERIFY_ATTEMPTS, _iso(_now(now_at)))).fetchone():
        return False
    _, created = jobs.enqueue(conn, "verify", str(document_id), priority=VERIFY_PRIORITY, company_id=company_id, document_id=document_id)
    return created


def queue_unverified(conn, now_at=None):
    """Queues checks for documents with due candidates and no open verify job. A document whose verify job failed for good
    (the API refusing the request, say) waits RETRY_AFTER too, so an error can't turn into an hourly loop. Returns how many."""
    moment = _now(now_at)
    rows = conn.execute(
        """SELECT DISTINCT c.document_id, d.company_id FROM candidates c JOIN documents d ON d.id = c.document_id
            WHERE c.status = 'pending' AND c.verify_attempts < ? AND (c.verify_after IS NULL OR c.verify_after <= ?)
            AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.kind = 'verify' AND j.key = CAST(c.document_id AS TEXT)
                            AND (j.status IN ('queued', 'running') OR (j.status IN ('failed', 'dead') AND j.updated_at > ?)))""",
        (MAX_VERIFY_ATTEMPTS, _iso(moment), _iso(moment - RETRY_AFTER))).fetchall()
    return sum(queue_verify(conn, row["document_id"], row["company_id"], moment) for row in rows)


@handler("verify")
async def verify_job(job, conn):
    document_id = int(job["key"])
    if conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone() is None:
        raise Permanent(f"no document {document_id}")
    totals = await verify_document(conn, document_id, run_id=job.get("run_id"))
    if not totals["candidates"]:
        return {"notes": "nothing to check"}
    extra = "".join(f", {totals[k]} {k}" for k in ("declined", "unanswered") if totals[k])
    result = {"notes": f"{totals['candidates']} checked: {totals['linked']} linked, {totals['rejected']} rejected{extra}",
              "model": ", ".join(totals["models"]) or config.VERIFIER_MODEL, "input_tokens": totals["input_tokens"],
              "output_tokens": totals["output_tokens"], "cost_usd": round(totals["cost_usd"], 6)}
    if totals["deferred"] is not None:  # the worker queues the rest again for when the allowance allows (orchestrator.requeue_later)
        result["notes"] += f"; the rest {totals['deferred'].reason}"
        result["defer_until"], result["defer_reason"] = totals["deferred"].until, totals["deferred"].reason
    return result
