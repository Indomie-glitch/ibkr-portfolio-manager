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

import anthropic

import config
import usage_store
from supply_chain import chunker, graph, jobs, xbrl
from supply_chain.db import now
from supply_chain.worker import Permanent, handler

FEATURE = "supply_chain_verifier"
EFFORT = "medium"
MAX_TOKENS = 16000
TIMEOUT_S = 300
BATCH_ITEMS = 10
BATCH_TOKENS = 20_000
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


async def judge(client, group, splits=0):
    """({candidate id: verdict}, the model that answered (None if it declined), attempts). A cut-off answer is asked again in halves."""
    numbered = {n: c for n, c in enumerate(group, 1)}
    response = await client.beta.messages.create(
        model=config.VERIFIER_MODEL,
        max_tokens=MAX_TOKENS,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "\n\n".join(item_text(n, c) for n, c in numbered.items())}],
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    attempts = _attempts(response)
    outcome = "ok" if response.stop_reason == "end_turn" else response.stop_reason
    for attempt in attempts:
        attempt["outcome"] = outcome
    if response.stop_reason == "max_tokens" and len(group) > 1 and splits < 3:
        middle = len(group) // 2
        verdicts, models = {}, []
        for half in (group[:middle], group[middle:]):
            more, model, more_attempts = await judge(client, half, splits + 1)
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


def counterparty_ids(conn, candidate):
    """(supplier id, customer id), making the placeholder company for an unnamed counterparty as xbrl.py does."""
    ids = {"supplier": candidate["supplier_id"], "customer": candidate["customer_id"]}
    for side in ("supplier", "customer"):
        if ids[side] is None and candidate[f"{side}_unnamed"]:
            filer_side = "customer" if side == "supplier" else "supplier"
            filer_id = ids[filer_side]
            filer_name = conn.execute("SELECT name FROM companies WHERE id = ?", (filer_id,)).fetchone()["name"]
            ids[side] = xbrl.placeholder(conn, filer_id, filer_name, {"label": candidate[f"{side}_name"], "end": _period_end(conn, candidate)}, side)
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
    # confidence is left at the schema's default (0, not scored): the merge (#127) sets it from all of a link's evidence
    relationship_id = graph.add_relationship(conn, supplier_id, customer_id, evidence, kind=candidate["kind"], what=keep["what"],
                                             supplier_revenue_share=keep["supplier_revenue_share"],
                                             customer_supply_share=keep["customer_supply_share"],
                                             customer_share_scope=keep["customer_share_scope"], shares_as_of=stated_on)
    graph.refresh_shares(conn, relationship_id)
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

async def verify_document(conn, document_id, client=None, run_id=None):
    """Checks every pending candidate of a document. Returns {candidates, linked, rejected, declined, unanswered, models,
    input_tokens, output_tokens, cost_usd}."""
    pending = conn.execute("SELECT * FROM candidates WHERE document_id = ? AND status = 'pending' ORDER BY id", (document_id,)).fetchall()
    totals = {"candidates": len(pending), "linked": 0, "rejected": 0, "declined": 0, "unanswered": 0, "models": [],
              "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    if not pending:
        return totals
    if client is None:
        if not config.anthropic_api_key():
            raise RuntimeError("no Anthropic API key")  # retried: the key may be added in Settings
        client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key(), timeout=TIMEOUT_S)

    async def run_batch(group):
        verdicts, model, attempts = await judge(client, group)
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
        missed += await run_batch(group)
    for candidate in missed:  # an item the answer skipped is asked about on its own, once
        if await run_batch([candidate]):
            totals["unanswered"] += 1
    return totals


def queue_verify(conn, document_id, company_id=None):
    """Queues the check of a document's pending candidates (once while one is open)."""
    if not conn.execute("SELECT 1 FROM candidates WHERE document_id = ? AND status = 'pending' LIMIT 1", (document_id,)).fetchone():
        return False
    _, created = jobs.enqueue(conn, "verify", str(document_id), priority=VERIFY_PRIORITY, company_id=company_id, document_id=document_id)
    return created


def queue_unverified(conn):
    """Queues checks for documents with pending candidates and no open verify job. Returns how many."""
    rows = conn.execute(
        """SELECT DISTINCT c.document_id, d.company_id FROM candidates c JOIN documents d ON d.id = c.document_id WHERE c.status = 'pending'
           AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.kind = 'verify' AND j.key = CAST(c.document_id AS TEXT) AND j.status IN ('queued', 'running'))""").fetchall()
    return sum(queue_verify(conn, row["document_id"], row["company_id"]) for row in rows)


@handler("verify")
async def verify_job(job, conn):
    document_id = int(job["key"])
    if conn.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone() is None:
        raise Permanent(f"no document {document_id}")
    totals = await verify_document(conn, document_id, run_id=job.get("run_id"))
    if not totals["candidates"]:
        return {"notes": "nothing to check"}
    extra = "".join(f", {totals[k]} {k}" for k in ("declined", "unanswered") if totals[k])
    return {"notes": f"{totals['candidates']} checked: {totals['linked']} linked, {totals['rejected']} rejected{extra}",
            "model": ", ".join(totals["models"]) or config.VERIFIER_MODEL, "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"], "cost_usd": round(totals["cost_usd"], 6)}
