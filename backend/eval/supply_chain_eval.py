"""The supply chain evaluation set (#133): how many known relationships the pipeline finds, and how many wrong ones it adds.

    cd backend && python -m eval.supply_chain_eval --check            # every quote still found in its filing (no API; downloads filings if missing)
    cd backend && python -m eval.supply_chain_eval                    # run chunker, Reader, Verifier and merge on the evaluation filings
    cd backend && python -m eval.supply_chain_eval --reader-effort low --label low
    cd backend && python -m eval.supply_chain_eval --fresh --runs 3      # a Reader prompt change: read again, three times, mean and range

Reader answers are saved in backend/eval/reader_cache/ (eval/reader_cache.py), keyed by the whole Reader request (chunk text, prompt,
schema, model, effort), one per run number. A run reuses them, so a change to the Verifier, merge or confidence is measured on the same
Reader output; a changed prompt or chunk reads afresh by itself; --fresh reads everything again and replaces what is saved.

backend/eval/supply_chain_eval.json lists 10 filings and what each states: the relationships known to be true (30 of them the "headline" cases:
named customers with percentages, named suppliers in risk factors, 8-K agreements, unnamed customers, ended relationships, private counterparties),
optional ones the text states ambiguously, and traps that must not become links. Each has the filing's quote, cut from the cleaned text.

A run uses the real Claude API (never part of the unit tests): it prints the estimated cost and asks first (--yes skips the question). It works
on a temporary database (the watch-list companies, the real name resolver), so nothing in data/ changes except filings downloaded for the
check and the usage log (usage.sqlite). The report goes to docs/eval/ as markdown and JSON.

Matching: a found relationship is an output link whose two companies are the truth's (by name, through the aliases in the file) with an accepted kind,
and whose evidence comes from that filing. An unnamed one ("one direct customer, 22%") is a placeholder link of the filer with the same share
(equal at the precision of the less precise figure, merge.same_share) and the same fiscal year; the same share with another year counts as found
loosely. Links matching nothing are listed as wrong: the list is for review, because the truth only covers what was annotated.
"""
import argparse
import asyncio
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import anthropic  # noqa: E402

import config  # noqa: E402
from eval.reader_cache import CachingClient  # noqa: E402
from supply_chain import chunker, db, graph, jobs, merge, orchestrator, reader, resolver, themes, verifier  # noqa: E402

TRUTH = Path(__file__).with_name("supply_chain_eval.json")
REPORTS = BACKEND.parent / "docs" / "eval"
PERIOD = re.compile(r"year to (\d{4}-\d{2}-\d{2})")


# ---------- The truth file ----------

def load_truth(path=TRUTH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def all_items(doc):
    return doc["relationships"] + doc["optional"]


def alias_keys(truth, name):
    """The comparable forms of a canonical name in the truth file."""
    names = truth["companies"].get(name, {}).get("aliases", []) + [name]
    return {resolver.name_key(n) for n in names}


def filing_folder(doc):
    return config.DATA_DIR / "filings" / str(doc["cik"]) / doc["accession"].replace("-", "")


def filing_path(doc):
    return filing_folder(doc) / doc["primary_document"]


async def ensure_downloaded(doc):
    import sec_client
    if not filing_path(doc).exists():
        await sec_client.download(doc["cik"], doc["accession"], doc["primary_document"])
    return filing_path(doc)


def check_quotes(truth, docs=None):
    """Problems finding each quote in its filing, and which quotes the chunker would not send to the Reader.
    Returns ([problem text], [(item id, why)] for quotes outside the chunks)."""
    problems, outside = [], []
    for doc in truth["documents"]:
        if docs and doc["id"] not in docs:
            continue
        path = filing_path(doc)
        if not path.exists():
            problems.append(f"{doc['id']}: {path} is missing (run without --check once, or --check downloads it)")
            continue
        paragraphs = chunker.load_paragraphs(path)
        chunks = chunker.chunk_filing(path.parent, doc["form"], doc["primary_document"])
        sent = reader.normalise(" ".join(c.text for c in chunks))
        for item in all_items(doc) + doc["not_relationships"]:
            text = reader.normalise(paragraphs[item["paragraph"] - 1]) if 0 < item["paragraph"] <= len(paragraphs) else ""
            quote = reader.normalise(item["quote"])
            label = item.get("id") or f"{doc['id']} trap ¶{item['paragraph']}"
            if not quote or quote not in text:
                problems.append(f"{label}: the quote is not in paragraph {item['paragraph']} of {doc['id']}")
            elif quote not in sent:
                outside.append((label, "the chunker does not send this quote to the Reader"))
    return problems, outside


# ---------- The database ----------

def company_for(conn, ticker, market="US"):
    row = conn.execute("SELECT company_id FROM identifiers WHERE scheme = 'ticker' AND value = ? AND market = ?", (ticker, market)).fetchone()
    return row["company_id"] if row else None


def setup_database(truth, folder, docs=None):
    """A temporary graph database with the watch list and the evaluation filings registered as downloaded. Returns (conn, {doc id: document id})."""
    conn = db.open_graph(Path(folder) / "eval.sqlite")
    themes.seed_themes(conn)
    ids = {}
    for doc in truth["documents"]:
        if docs and doc["id"] not in docs:
            continue
        company = company_for(conn, doc["ticker"], doc["market"])
        if company is None:
            company = graph.add_company(conn, doc["company"])
            graph.add_identifier(conn, company, "ticker", doc["ticker"], doc["market"])
        ids[doc["id"]] = graph.add_document(
            conn, "sec", doc["form"], f"{doc['accession']}/{doc['primary_document']}", f"https://www.sec.gov/Archives/edgar/data/{doc['cik']}/{doc['primary_document']}",
            company_id=company, title=f"{doc['form']} {doc['filed']}", filed_at=doc["filed"], period_end=doc["period_end"], status="downloaded")
        conn.execute("UPDATE documents SET local_path = ? WHERE id = ?", (str(filing_path(doc)), ids[doc["id"]]))
    return conn, ids


def estimate_cost(conn, truth, ids):
    """(Reader US$, Verifier US$, chunks) before any call: the orchestrator's estimates for every chunk, and for the claims expected."""
    reader_cost, chunks_total, expected = 0.0, 0, 0
    for doc in truth["documents"]:
        if doc["id"] not in ids:
            continue
        for chunk in chunker.chunk_filing(filing_folder(doc), doc["form"], doc["primary_document"]):
            reader_cost += orchestrator.read_estimate(conn, chunk.tokens)
            chunks_total += 1
        expected += round(1.4 * (len(doc["relationships"]) + len(doc["optional"])))
    batches = -(-expected // verifier.BATCH_ITEMS)
    verifier_cost = batches * orchestrator.verify_estimate(verifier.BATCH_ITEMS * 450, verifier.BATCH_ITEMS)
    return reader_cost, verifier_cost, chunks_total


# ---------- Running the pipeline ----------

async def run_pipeline(conn, ids, reader_effort="medium", verifier_effort="medium", say=print, run_index=0, fresh=False):
    """Reader, Verifier and merge on each document; the Reader's answers come from the cache when saved (answer number
    run_index; fresh reads them all again). Returns {reader_cost, verifier_cost, tokens..., reader_cache}."""
    reader.EFFORT, verifier.EFFORT = reader_effort, verifier_effort
    client = CachingClient(anthropic.AsyncAnthropic(api_key=config.anthropic_api_key(), timeout=reader.TIMEOUT_S), run_index, fresh)
    totals = {"reader_cost": 0.0, "verifier_cost": 0.0, "reader_in": 0, "reader_out": 0, "verifier_in": 0, "verifier_out": 0, "declined": 0, "deferred": 0}
    def start(kind, key):
        """A run row, so what each call costs is on it and the spend cap sees it."""
        jobs.enqueue(conn, kind, key)
        return jobs.claim(conn, "eval", kinds=[kind])

    for eval_id, document_id in ids.items():
        say(f"  {eval_id}: reading…")
        job = start("read", f"eval-{eval_id}")
        read = await reader.read_document(conn, document_id, client=client, run_id=job["run_id"])
        jobs.finish(conn, job)
        for key, name in (("cost_usd", "reader_cost"), ("input_tokens", "reader_in"), ("output_tokens", "reader_out")):
            totals[name] += read[key]
        totals["declined"] += read["declined"]
        totals["deferred"] += 1 if read["deferred"] else 0
        say(f"  {eval_id}: {read['chunks']} chunks, {read['candidates']} candidates, {read['rejected']} rejected; checking…")
        for _ in range(2):  # an item the answer skipped is asked again once
            job = start("verify", f"eval-{eval_id}")
            checked = await verifier.verify_document(conn, document_id, run_id=job["run_id"])
            jobs.finish(conn, job)
            for key, name in (("cost_usd", "verifier_cost"), ("input_tokens", "verifier_in"), ("output_tokens", "verifier_out")):
                totals[name] += checked[key]
            totals["deferred"] += 1 if checked["deferred"] else 0
            if not conn.execute("SELECT 1 FROM candidates WHERE document_id = ? AND status = 'pending' AND verify_attempts < ?",
                                (document_id, verifier.MAX_VERIFY_ATTEMPTS)).fetchone():
                break
            conn.execute("UPDATE candidates SET verify_after = NULL WHERE document_id = ? AND status = 'pending'", (document_id,))
        say(f"  {eval_id}: {checked['linked']} linked, {checked['rejected']} rejected")
    totals["merge"] = merge.recompute_all(conn)
    totals["reader_cache"] = {"hits": client.hits, "misses": client.misses, "saved_usd": client.saved_usd}
    return totals


def full_cost(run):
    """What the run would cost read afresh: today's spend plus what the cached Reader answers cost when first read."""
    return run["reader_cost"] + (run.get("reader_cache") or {}).get("saved_usd", 0.0) + run["verifier_cost"]


# ---------- Reading the result ----------

def collect(conn, ids):
    """Everything the run produced, per link and per candidate, for scoring."""
    by_doc = {document_id: eval_id for eval_id, document_id in ids.items()}
    links = []
    for row in conn.execute("""SELECT r.*, s.name AS supplier_name, s.is_placeholder AS supplier_placeholder, c.name AS customer_name,
                                      c.is_placeholder AS customer_placeholder FROM relationships r JOIN companies s ON s.id = r.supplier_id
                               JOIN companies c ON c.id = r.customer_id WHERE r.merged_into IS NULL"""):
        evidence = [dict(e) for e in conn.execute("SELECT * FROM evidence WHERE relationship_id = ?", (row["id"],))]
        links.append({**dict(row), "evidence": [{**e, "eval_doc": by_doc.get(e["document_id"])} for e in evidence if e["document_id"] in by_doc]})
    candidates = [dict(r) | {"eval_doc": by_doc.get(r["document_id"])} for r in conn.execute("SELECT * FROM candidates")]
    rejected = [dict(r) | {"eval_doc": by_doc.get(r["document_id"])} for r in conn.execute("SELECT * FROM rejected")]
    return {"links": [link for link in links if link["evidence"]], "candidates": candidates, "rejected": rejected}


# ---------- Scoring ----------

def label_of(name):
    """The label of a placeholder company ("an affiliate of SoftBank Group (unnamed customer of Arm, year to ...)" -> "an affiliate of SoftBank Group")."""
    return name.split(" (unnamed ", 1)[0]


def name_matches(truth, canonical, name):
    """The company is the canonical one: its name is an alias. A placeholder also counts when its label contains an alias as whole words
    ("an affiliate of SoftBank Group", "the Corporate Venture"): the filing's own label for a company it doesn't name."""
    if " (unnamed " in name:
        label = f" {resolver.name_key(label_of(name))} "
        return any(f" {key} " in label for key in alias_keys(truth, canonical))
    return resolver.name_key(name) in alias_keys(truth, canonical)


def placeholder_year(name):
    m = PERIOD.search(name or "")
    return m.group(1) if m else None


def same_passage(link, doc, item):
    quote = reader.normalise(item["quote"])
    return any(reader.normalise(e["quote"]) and (reader.normalise(e["quote"]) in quote or quote in reader.normalise(e["quote"]))
               for e in link["evidence"] if e["eval_doc"] == doc["id"])


def find_link(truth, doc, item, links, used, strict=True, ignore_share=False):
    """The output link that satisfies a truth item, or None. Named: both companies match (swapped for a partnership), kind accepted. Unnamed:
    a placeholder link of the filer with the same share (and, if strict, the same fiscal year); with ignore_share, one whose evidence is the
    same passage whatever number it kept (a number the Verifier dropped)."""
    for link in links:
        if link["id"] in used or not any(e["eval_doc"] == doc["id"] for e in link["evidence"]):
            continue
        if item["unnamed"]:
            filer_is_supplier = item["supplier"] is not None
            filer = item["supplier"] if filer_is_supplier else item["customer"]
            if filer_is_supplier:
                ok = name_matches(truth, filer, link["supplier_name"]) and link["customer_placeholder"] and link["kind"] in item["accept_kinds"]
                column, share, placeholder = "supplier_revenue_share", item["supplier_revenue_share"], link["customer_name"]
            else:
                ok = name_matches(truth, filer, link["customer_name"]) and link["supplier_placeholder"] and link["kind"] in item["accept_kinds"]
                column, share, placeholder = "customer_supply_share", item["customer_supply_share"], link["supplier_name"]
            if not ok:
                continue
            if share is None or ignore_share:
                # no share to compare (receivables only), or the number was lost: the link's evidence quotes the same passage as the truth
                if not same_passage(link, doc, item):
                    continue
                return link
            shares = [e[column] for e in link["evidence"] if e["eval_doc"] == doc["id"] and e[column] is not None]
            if not any(merge.same_share(share, s) for s in shares):
                continue
            if strict and placeholder_year(placeholder) != item["stated_on"]:
                continue
            return link
        else:
            if link["kind"] not in item["accept_kinds"]:
                continue
            direct = name_matches(truth, item["supplier"], link["supplier_name"]) and name_matches(truth, item["customer"], link["customer_name"])
            swapped = (link["kind"] == "partnership" and name_matches(truth, item["supplier"], link["customer_name"])
                       and name_matches(truth, item["customer"], link["supplier_name"]))
            if direct or swapped:
                return link
    return None


def side_name(item, side):
    return item[side] or f"({item['unnamed']})"


def score(truth, out, ids):
    """The metrics of a run: found per truth item, wrong links, wrong numbers, rejected by reason, duplicates, traps."""
    links = out["links"]
    used, found, loose, lost, missed = set(), [], [], [], []
    wrong_numbers, ended_missed, wrongly_ended = [], [], []
    ended_found = 0
    per_item = {}
    for doc in truth["documents"]:
        if doc["id"] not in ids:
            continue
        for item in doc["relationships"]:
            link = find_link(truth, doc, item, links, used, strict=True)
            how = "found"
            if link is None and item["unnamed"]:
                link = find_link(truth, doc, item, links, used, strict=False)
                how = "found_other_year"
            if link is None and item["unnamed"] and (item["supplier_revenue_share"] is not None or item["customer_supply_share"] is not None):
                link = find_link(truth, doc, item, links, used, ignore_share=True)
                how = "found_no_number"
            if link is None:
                missed.append((doc["id"], item))
                per_item[item["id"]] = {"result": "missed"}
                continue
            used.add(link["id"])
            (found if how == "found" else loose if how == "found_other_year" else lost).append((doc["id"], item, link))
            per_item[item["id"]] = {"result": how, "link": link["id"], "confidence": link["confidence"], "level": merge.level(link["confidence"])}
            if not item["unnamed"]:
                for column in ("supplier_revenue_share", "customer_supply_share"):
                    wanted = item[column]
                    # every figure the file gives this pair in this filing is right (one link, several known statements)
                    stated = [i[column] for kind in ("relationships", "optional") for i in doc[kind]
                              if (i["supplier"], i["customer"]) == (item["supplier"], item["customer"]) and i[column] is not None]
                    mine = [e[column] for e in link["evidence"] if e["eval_doc"] == doc["id"] and e[column] is not None
                            and not any(merge.same_share(w, e[column]) for w in stated)]
                    if wanted is not None and mine and not any(merge.same_share(wanted, s) for s in mine):
                        wrong_numbers.append((doc["id"], item, column, mine))
                    elif wanted is None and mine:
                        wrong_numbers.append((doc["id"], item, column, mine))
            states_ended = any(e["states_ended"] for e in link["evidence"] if e["eval_doc"] == doc["id"])
            if item["ended"]:
                ended_found += 1
                if not (states_ended or link["status"] == "ended"):
                    ended_missed.append((doc["id"], item))
            if not item["ended"] and states_ended and not item["unnamed"]:
                wrongly_ended.append((doc["id"], item))
    # optional items use up their link too (so they are not "wrong"), without counting for or against
    optional_found = []
    for doc in truth["documents"]:
        if doc["id"] not in ids:
            continue
        for item in doc["optional"]:
            link = find_link(truth, doc, item, links, used, strict=False)
            if link is not None:
                used.add(link["id"])
                optional_found.append((doc["id"], item, link))
    wrong = [link for link in links if link["id"] not in used]
    # traps: a link whose evidence quote is one of the trap sentences
    trap_hits = []
    for doc in truth["documents"]:
        if doc["id"] not in ids:
            continue
        for trap in doc["not_relationships"]:
            tq = reader.normalise(trap["quote"])
            for link in links:
                for e in link["evidence"]:
                    eq = reader.normalise(e["quote"])
                    if e["eval_doc"] == doc["id"] and eq and (eq in tq or tq in eq):
                        # a trap with shares (a total for several customers, #341) is hit only by a link carrying one of them
                        stated = [e[c] for c in ("supplier_revenue_share", "customer_supply_share") if e[c] is not None]
                        if not trap.get("shares") or any(merge.same_share(w, s) for w in trap["shares"] for s in stated):
                            trap_hits.append((doc["id"], trap, link))
    # the same unnamed customer or supplier more than once: placeholder links of one filer, side and year with one share
    groups = defaultdict(list)
    for link in links:
        for side in ("supplier", "customer"):
            if link[f"{side}_placeholder"]:
                filer = link["customer_id"] if side == "supplier" else link["supplier_id"]
                share = link["supplier_revenue_share"] if side == "customer" else link["customer_supply_share"]
                groups[(filer, side, placeholder_year(link[f"{side}_name"]), share)].append(link["id"])
    duplicates = {k: v for k, v in groups.items() if len(v) > 1 and k[3] is not None}
    # truth items per category
    categories = defaultdict(lambda: [0, 0])
    for doc in truth["documents"]:
        if doc["id"] not in ids:
            continue
        for item in doc["relationships"]:
            hit = per_item[item["id"]]["result"] == "found"
            for cat in item["categories"] or ["other"]:
                categories[cat][0] += 1
                categories[cat][1] += hit
    rejected = Counter((r["reason"], r["rejected_by"]) for r in out["rejected"] if r["eval_doc"])
    candidates = Counter(c["status"] for c in out["candidates"] if c["eval_doc"])
    total = sum(len(d["relationships"]) for d in truth["documents"] if d["id"] in ids)
    headline = [i for d in truth["documents"] if d["id"] in ids for i in d["relationships"] if i["headline"]]
    headline_found = sum(per_item[i["id"]]["result"] == "found" for i in headline)
    levels = Counter(per_item[i]["level"] for i in per_item if "level" in per_item[i])
    return {
        "truth": total, "found": len(found), "found_other_year": len(loose), "found_no_number": len(lost), "missed": len(missed),
        "recall": round(len(found) / total, 3) if total else None, "recall_loose": round((len(found) + len(loose) + len(lost)) / total, 3) if total else None,
        "headline": len(headline), "headline_found": headline_found,
        "links": len(links), "wrong_links": len(wrong), "precision": round(len(used) / len(links), 3) if links else None,
        "wrong_numbers": len(wrong_numbers), "ended_truth": sum(1 for d in truth["documents"] if d["id"] in ids for i in d["relationships"] if i["ended"]),
        "ended_found": ended_found, "ended_marked": ended_found - len(ended_missed), "ended_missed": len(ended_missed), "wrongly_ended": len(wrongly_ended), "trap_links": len(trap_hits),
        "duplicate_groups": len(duplicates), "duplicate_links": sum(len(v) - 1 for v in duplicates.values()),
        "rejected": {f"{reason} ({by})": n for (reason, by), n in sorted(rejected.items(), key=lambda kv: -kv[1])},
        "candidates": dict(candidates), "confidence_levels_of_found": dict(levels),
        "categories": {k: {"truth": v[0], "found": v[1]} for k, v in sorted(categories.items())},
        "per_item": per_item,
        "_missed": missed, "_loose": loose, "_lost": lost, "_wrong": wrong, "_wrong_numbers": wrong_numbers, "_ended_missed": ended_missed, "_wrongly_ended": wrongly_ended,
        "_trap_hits": trap_hits, "_duplicates": duplicates, "_optional_found": optional_found,
    }


def diagnose(truth, doc, item, out, outside):
    """Why a truth item was not found: the chunker did not send the quote, a rule or the Verifier refused a candidate, or the Reader never gave one.
    A named item is matched to rejections and candidates by its two companies; an unnamed one (only the filer has a name) by its quote."""
    if any(label == item["id"] for label, _ in outside):
        return "the chunker does not send this passage to the Reader"
    named = not item["unnamed"]
    keys = [alias_keys(truth, item[side]) for side in ("supplier", "customer")] if named else []
    quote = reader.normalise(item["quote"])

    def about(row):
        names = {resolver.name_key(row["supplier_name"] or ""), resolver.name_key(row["customer_name"] or "")}
        if named:
            return all(k & names for k in keys)
        other = reader.normalise(row["quote"])
        return bool(other) and (other in quote or quote in other)

    for row in out["rejected"]:
        if row["eval_doc"] == doc["id"] and about(row):
            return f"rejected: {row['reason']} ({row['rejected_by']})" + (f" - {row['detail'][:90]}" if row["detail"] else "")
    for cand in out["candidates"]:
        if cand["eval_doc"] == doc["id"] and cand["status"] != "linked" and about(cand):
            return f"candidate left {cand['status']}"
    return "the Reader did not return it"


# ---------- The report ----------

def money(value):
    return f"US${value:.3f}"


def reader_cache_line(run):
    cache = run.get("reader_cache")
    if not cache:
        return []
    return [f"| Reader answers | {cache['hits']} from the cache (they cost {money(cache['saved_usd'])} when first read), {cache['misses']} read now"
            f"{' (--fresh)' if run.get('fresh') else ''}; cost read afresh {money(full_cost(run))} |"]


def render(truth, ids, out, metrics, run, label, started):
    m = metrics
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=BACKEND).stdout.strip()
    if subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, cwd=BACKEND).stdout.strip():
        commit += " + uncommitted changes"
    late = sum(1 for d in truth["documents"] if d["id"] in ids for r in d["relationships"] if r.get("late"))
    lines = [f"# Supply chain evaluation: {label}", "",
             f"Run {started:%Y-%m-%d %H:%M} · commit {commit} · chunker v{chunker.CHUNKER_VERSION} · Reader {config.READER_MODEL} (effort {run['reader_effort']}) · "
             f"Verifier {config.VERIFIER_MODEL} (effort {run['verifier_effort']}) · {len(ids)} filings", "",
             "## Summary", "",
             "| | |", "|---|---|",
             f"| Known relationships | {m['truth']} (30 headline; {late} added to the file after reviewing the first run) |",
             f"| **Found** (right companies, and for unnamed ones the right share and year) | **{m['found']}** ({m['recall']:.0%} recall) |",
             f"| Found with the right share but another year | {m['found_other_year']} |",
             f"| Found, but the number was lost (the customer and passage are right) | {m['found_no_number']} (recall counting these two: {m['recall_loose']:.0%}) |",
             f"| Headline cases found | {m['headline_found']} of {m['headline']} |",
             f"| Missed | {m['missed']} |",
             f"| Links in the result | {m['links']} |",
             f"| **Wrong links** (match nothing in the truth; to review below) | **{m['wrong_links']}** (precision {m['precision']:.0%}) |",
             f"| Wrong numbers on found links | {m['wrong_numbers']} |",
             f"| Ended relationships | {m['ended_found']} of {m['ended_truth']} found; {m['ended_marked']} of those marked ended |",
             f"| Wrongly ended | {m['wrongly_ended']} |",
             f"| Links made from a trap sentence | {m['trap_links']} |",
             f"| Duplicate unnamed counterparties | {m['duplicate_links']} extra links in {m['duplicate_groups']} groups |",
             f"| Confidence level of the found links | {', '.join(f'{k} {v}' for k, v in sorted(m['confidence_levels_of_found'].items())) or 'none'} |",
             f"| **Cost** | **{money(run['reader_cost'] + run['verifier_cost'])}** (Reader {money(run['reader_cost'])}, Verifier {money(run['verifier_cost'])}) |",
             f"| Tokens | Reader {run['reader_in']:,} in / {run['reader_out']:,} out · Verifier {run['verifier_in']:,} in / {run['verifier_out']:,} out |",
             *reader_cache_line(run), "",
             "## Recall by kind of case", "", "| Case | Known | Found |", "|---|---|---|"]
    for cat, v in m["categories"].items():
        lines.append(f"| {cat.replace('_', ' ')} | {v['truth']} | {v['found']} |")
    lines += ["", "## Candidates and rejections", "", "Candidates by status: " + ", ".join(f"{k} {v}" for k, v in sorted(m["candidates"].items())), "",
              "| Rejected | Count |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in m["rejected"].items()] or ["| none | 0 |"]
    lines += ["", "## Missed", ""]
    docs = {d["id"]: d for d in truth["documents"]}
    for doc_id, item in m["_missed"]:
        flag = " (headline)" if item["headline"] else ""
        lines.append(f"- **{doc_id}** {side_name(item, 'supplier')} → {side_name(item, 'customer')}{flag}: {out['diagnosis'][item['id']]}")
    if not m["_missed"]:
        lines.append("- none")
    if m["_loose"]:
        lines += ["", "## Found with another year", ""]
        for doc_id, item, link in m["_loose"]:
            placeholder = link["customer_name"] if item["supplier"] else link["supplier_name"]
            lines.append(f"- **{doc_id}** {side_name(item, 'supplier')} → {side_name(item, 'customer')} (known: year to {item['stated_on']}) was made as `{placeholder}`")
    if m["_wrong_numbers"] or m["_ended_missed"] or m["_wrongly_ended"] or m["_lost"]:
        lines += ["", "## Wrong numbers and endings", ""]
        for doc_id, item, link in m["_lost"]:
            lines.append(f"- **{doc_id}** {side_name(item, 'supplier')} → {side_name(item, 'customer')}: the link exists but lost its number (known {item['supplier_revenue_share'] or item['customer_supply_share']}%)")
        for doc_id, item, column, mine in m["_wrong_numbers"]:
            lines.append(f"- **{doc_id}** {item['supplier']} → {item['customer']}: {column} is {mine}, known {item[column]}")
        lines += [f"- **{d}** {i['supplier'] or '?'} → {i['customer'] or '?'}: ended in the filing, not marked ended" for d, i in m["_ended_missed"]]
        lines += [f"- **{d}** {i['supplier'] or '?'} → {i['customer'] or '?'}: marked ended, the filing says no" for d, i in m["_wrongly_ended"]]
    lines += ["", f"## Wrong links ({len(m['_wrong'])})", "",
              "These match nothing in the truth. Each needs a look: a wrong link, or a true one the annotation missed (then it goes into the file).", ""]
    for link in m["_wrong"]:
        e = link["evidence"][0]
        arrow = "↔" if link["kind"] == "partnership" else "→"
        shares = f" · {link['supplier_revenue_share']:g}% of revenue" if link["supplier_revenue_share"] is not None else (
            f" · {link['customer_supply_share']:g}% of purchases" if link["customer_supply_share"] is not None else "")
        lines.append(f"- **{e['eval_doc']}** {link['supplier_name']} {arrow} {link['customer_name']} ({link['kind']}{shares}, {merge.level(link['confidence'])}): {e['quote'][:200]}")
    if not m["_wrong"]:
        lines.append("- none")
    if m["_trap_hits"]:
        lines += ["", "## Links made from trap sentences", ""]
        for doc_id, trap, link in m["_trap_hits"]:
            lines.append(f"- **{doc_id}** {link['supplier_name']} → {link['customer_name']}: {trap['why']}")
    if m["_duplicates"]:
        lines += ["", "## Duplicate unnamed counterparties", ""]
        for (filer, side, year, share), ids_ in m["_duplicates"].items():
            lines.append(f"- {len(ids_)} placeholder {side}s with {share:g}% for the year to {year} (filer company {filer})")
    lines += ["", "## Every known relationship", "", "| Filing | Supplier | Customer | Result | Confidence |", "|---|---|---|---|---|"]
    for doc in truth["documents"]:
        if doc["id"] not in ids:
            continue
        for item in doc["relationships"]:
            r = m["per_item"][item["id"]]
            lines.append(f"| {doc['id']} | {side_name(item, 'supplier')} | {side_name(item, 'customer')} | {r['result'].replace('_', ' ')}{' (headline)' if item['headline'] else ''} | {r.get('level', '')} |")
    return "\n".join(lines) + "\n"


def jsonable(metrics):
    return {k: v for k, v in metrics.items() if not k.startswith("_")}


# ---------- Command line ----------

def build_report(truth, ids, out, outside, run, label, started):
    """Score, diagnose and render: a pure function of the truth file and what the run produced."""
    metrics = score(truth, out, ids)
    docs = {d["id"]: d for d in truth["documents"]}
    out["diagnosis"] = {item["id"]: diagnose(truth, docs[doc_id], item, out, outside) for doc_id, item in metrics["_missed"]}
    return metrics, render(truth, ids, out, metrics, run, label, started)


def save(stem, report, label, run, metrics, raw):
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{stem}.md").write_text(report, encoding="utf-8")
    (REPORTS / f"{stem}.json").write_text(json.dumps({"label": label, "run": run, "metrics": jsonable(metrics)}, indent=1), encoding="utf-8")
    if raw is not None:
        (REPORTS / f"{stem}.raw.json").write_text(json.dumps(raw, default=str), encoding="utf-8")


async def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="only check that every quote is found in its filing (downloads missing filings)")
    parser.add_argument("--docs", help="comma-separated filing ids to use (default all)")
    parser.add_argument("--reader-effort", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("--verifier-effort", default="medium", choices=["low", "medium", "high"])
    parser.add_argument("--label", help="name of the run in the report (default: reader-<effort>)")
    parser.add_argument("--yes", action="store_true", help="don't ask before spending")
    parser.add_argument("--estimate-only", action="store_true", help="print the estimated cost and stop")
    parser.add_argument("--fresh", action="store_true", help="read every chunk again instead of using saved Reader answers (and save the new ones)")
    parser.add_argument("--runs", type=int, default=1, help="run N times (each Reader answer number i is run i's) and report mean and range")
    parser.add_argument("--rescore", metavar="STEM", help="score a saved run again (docs/eval/<STEM>.raw.json) against the current truth file: no API calls")
    args = parser.parse_args(argv)
    truth = load_truth()
    if args.rescore and not (REPORTS / f"{args.rescore}.raw.json").exists():  # a --runs summary: rescore each run, then the summary
        summary = json.loads((REPORTS / f"{args.rescore}.json").read_text(encoding="utf-8"))
        results = []
        for stem in summary["reports"]:
            raw = json.loads((REPORTS / f"{stem}.raw.json").read_text(encoding="utf-8"))
            started = datetime.fromisoformat(raw["started"])
            metrics, report = build_report(truth, raw["ids"], raw["out"], [tuple(x) for x in raw["outside"]], raw["run"], raw["label"], started)
            save(stem, report, raw["label"], raw["run"], metrics, raw)
            results.append((stem, raw["run"], metrics))
        text = render_runs(summary.get("label") or args.rescore, started, results, truth, raw["ids"])
        (REPORTS / f"{args.rescore}.md").write_text(text, encoding="utf-8")
        (REPORTS / f"{args.rescore}.json").write_text(json.dumps({**runs_summary(results), "label": summary.get("label")}, indent=1), encoding="utf-8")
        print(text)
        return 0
    if args.rescore:
        raw = json.loads((REPORTS / f"{args.rescore}.raw.json").read_text(encoding="utf-8"))
        started = datetime.fromisoformat(raw["started"])
        metrics, report = build_report(truth, raw["ids"], raw["out"], [tuple(x) for x in raw["outside"]], raw["run"], raw["label"], started)
        save(args.rescore, report, raw["label"], raw["run"], metrics, raw)
        print(report)
        return 0
    wanted = set(args.docs.split(",")) if args.docs else None
    for doc in truth["documents"]:
        if not wanted or doc["id"] in wanted:
            await ensure_downloaded(doc)
    problems, outside = check_quotes(truth, wanted)
    for p in problems:
        print("PROBLEM:", p)
    for label, why in outside:
        print("NOTE:", label, "-", why)
    count = sum(len(all_items(d)) + len(d["not_relationships"]) for d in truth["documents"] if not wanted or d["id"] in wanted)
    print(f"{count} quotes checked: {len(problems)} not found, {len(outside)} outside the chunks")
    if args.check or problems:
        return 1 if problems else 0
    if not config.anthropic_api_key():
        print("No ANTHROPIC_API_KEY in .env")
        return 1
    label = args.label or f"reader-{args.reader_effort}"
    with tempfile.TemporaryDirectory(prefix="supply-chain-eval-") as folder:
        conn, ids = setup_database(truth, folder, wanted)
        low, high_, chunks = estimate_cost(conn, truth, ids)
        conn.close()
    reading = "every chunk read again" if args.fresh else "Reader answers from the cache where saved (then only the Verifier is paid for)"
    print(f"\n{len(ids)} filings, {chunks} chunks, {args.runs} run(s), {reading}. Estimated cost at most about {money(args.runs * (low + high_))} "
          f"(per run: Reader {money(low)}, Verifier {money(high_)}). The estimate is deliberately high.")
    if args.estimate_only:
        return 0
    if not args.yes and input("Run it with the real Claude API? [y/N] ").strip().lower() != "y":
        print("Not run.")
        return 0
    started = datetime.now(timezone.utc).astimezone()
    orchestrator.limits.pacing = False
    orchestrator.limits.run_cap_usd = max(2.0, 4 * args.runs * (low + high_))
    orchestrator.limits.run_since = started.astimezone(timezone.utc)
    stem = f"{started:%Y-%m-%d}-{label}"
    results = []
    for index in range(args.runs):
        run_stem = f"{stem}-run{index + 1}" if args.runs > 1 else stem
        run_label = f"{label} (run {index + 1} of {args.runs})" if args.runs > 1 else label
        with tempfile.TemporaryDirectory(prefix="supply-chain-eval-") as folder:
            conn, ids = setup_database(truth, folder, wanted)
            print(f"\nRun {index + 1} of {args.runs}", flush=True)
            run = await run_pipeline(conn, ids, args.reader_effort, args.verifier_effort, say=lambda text: print(text, flush=True),
                                     run_index=index, fresh=args.fresh)
            run.update(reader_effort=args.reader_effort, verifier_effort=args.verifier_effort, fresh=args.fresh, run_index=index)
            out = collect(conn, ids)
            conn.close()
        raw = {"label": run_label, "started": started.isoformat(), "run": run, "ids": ids, "outside": outside, "out": {k: out[k] for k in ("links", "candidates", "rejected")}}
        metrics, report = build_report(truth, ids, out, outside, run, run_label, started)
        save(run_stem, report, run_label, run, metrics, raw)
        results.append((run_stem, run, metrics))
        if args.runs == 1:
            print("\n" + report)
        print(f"Saved docs/eval/{run_stem}.md, .json and .raw.json")
    if args.runs > 1:
        summary = render_runs(label, started, results, truth, ids)
        (REPORTS / f"{stem}.md").write_text(summary, encoding="utf-8")
        (REPORTS / f"{stem}.json").write_text(json.dumps({**runs_summary(results), "label": label}, indent=1), encoding="utf-8")
        print("\n" + summary)
        print(f"Saved docs/eval/{stem}.md and .json")
    return 0


RUN_FIGURES = (("found", "Found"), ("headline_found", "Headline cases found"), ("wrong_links", "Wrong links"),
               ("wrong_numbers", "Wrong numbers"), ("trap_links", "Links made from traps"), ("duplicate_links", "Duplicate placeholder links"))


def runs_summary(results):
    """Mean, lowest and highest of each figure over the runs, and of the cost read afresh."""
    summary = {}
    for key, _ in RUN_FIGURES:
        values = [m[key] for _, _, m in results]
        summary[key] = {"mean": sum(values) / len(values), "min": min(values), "max": max(values), "runs": values}
    costs = [full_cost(run) for _, run, _ in results]
    summary["cost_usd"] = {"mean": sum(costs) / len(costs), "min": min(costs), "max": max(costs), "runs": costs}
    summary["truth"] = results[0][2]["truth"]
    summary["reports"] = [stem for stem, _, _ in results]
    return summary


def render_runs(label, started, results, truth, ids):
    s = runs_summary(results)
    run = results[0][1]
    lines = [f"# Supply chain evaluation: {label} ({len(results)} runs)", "",
             f"Run {started:%Y-%m-%d %H:%M} · Reader {config.READER_MODEL} (effort {run['reader_effort']}) · Verifier {config.VERIFIER_MODEL} "
             f"(effort {run['verifier_effort']}) · {len(ids)} filings · {'every chunk read again' if run.get('fresh') else 'Reader answers from the cache where saved'}", "",
             "| | Mean | Lowest | Highest | Each run |", "|---|---|---|---|---|"]
    for key, name in RUN_FIGURES:
        v = s[key]
        name = f"{name} (of {s['truth']})" if key == "found" else name
        lines.append(f"| {name} | {v['mean']:.1f} | {v['min']} | {v['max']} | {', '.join(map(str, v['runs']))} |")
    c = s["cost_usd"]
    lines.append(f"| Cost (read afresh) | {money(c['mean'])} | {money(c['min'])} | {money(c['max'])} | {', '.join(money(x) for x in c['runs'])} |")
    lines += ["", "Each run's report: " + ", ".join(f"[{stem}]({stem}.md)" for stem in s["reports"]), ""]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
