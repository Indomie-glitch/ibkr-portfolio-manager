"""Customer concentration from XBRL (#120): the "major customer" percentages companies tag in their 10-Ks.

A 10-K's XBRL data tags each concentration percentage (us-gaap:ConcentrationRiskPercentage1) with dimensions saying
who and of what:
- the counterparty: srt:MajorCustomersAxis (or a supplier / vendor / counterparty axis), whose member is either a named
  company ("Apple Inc."), an unnamed one ("Customer A", "Customer One", "Undisclosed Customer") or a group ("Top Ten
  Customers", "United States And Europe Based End Customers");
- the benchmark: revenue (the customer's share of the filer's revenue), accounts receivable, or purchases (then the
  counterparty is a supplier and the share is of what the filer buys).

Each fact becomes a relationship with tier 1 evidence pointing at the 10-K: a named company is matched with the name
resolver (#119) and refused (the rejected table, unresolved_company) when it can't be matched; an unnamed one becomes a
placeholder company tied to the filer, one per label and fiscal year, because "Customer A" this year need not be last
year's Customer A; groups, regions and product lines are not one company and are left out.

Only a revenue share fills supplier_revenue_share and only a purchases share fills customer_supply_share; a receivables
share is kept on the evidence as a note (it says who owes the filer money, not how much it buys).
"""
import re
import xml.etree.ElementTree as ET

import sec_client
from supply_chain import graph, resolver, sec
from supply_chain.worker import Permanent, handler

XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "{http://xbrl.org/2006/xbrldi}"
XLINK = "{http://www.w3.org/1999/xlink}"
CONCEPT = "ConcentrationRiskPercentage1"
EXTRACTOR = "xbrl"
CONFIDENCE = 0.9

COUNTERPARTY_AXIS = re.compile(r"MajorCustomers|Customer|Supplier|Vendor|Counterparty", re.I)
# Dimensions that narrow a counterparty's share without changing whose it is: kept as a note
NOTED_AXES = {"StatementBusinessSegmentsAxis": "segment", "ConsolidationItemsAxis": None,
              "RelatedPartyTransactionsByRelatedPartyAxis": "related party", "SubsegmentsAxis": "segment"}
ROLE_WORDS = {"customer", "distributor", "reseller", "client", "supplier", "vendor", "partner", "licensee", "oem", "company",
              "manufacturer", "contract manufacturer"}
QUALIFIERS = {"a", "an", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "first", "second", "third",
              "fourth", "fifth", "major", "largest", "large", "top", "key", "significant", "single", "undisclosed", "unidentified",
              "unnamed", "other", "another", "end", "direct", "indirect", "principal"}
GROUP_WORDS = {"customers", "distributors", "resellers", "clients", "suppliers", "vendors", "partners", "others", "oems", "companies"}


# ---------- Reading the files ----------

def _local(qname):
    return qname.split(":", 1)[-1]


def parse_labels(content):
    """{element id like "nvda_CustomerOneMember": short label}, from a label linkbase (_lab.xml). The terse label is preferred
    ("Apple, Inc."), else the standard one without " [Member]"."""
    root = ET.fromstring(content)
    locs, texts, arcs = {}, {}, []
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "loc":
            locs[el.get(XLINK + "label")] = (el.get(XLINK + "href") or "").rsplit("#", 1)[-1]
        elif tag == "label":
            texts.setdefault(el.get(XLINK + "label"), {})[(el.get(XLINK + "role") or "").rsplit("/", 1)[-1]] = (el.text or "").strip()
        elif tag == "labelArc":
            arcs.append((el.get(XLINK + "from"), el.get(XLINK + "to")))
    found = {}
    for source, target in arcs:
        if source in locs:
            found.setdefault(locs[source], {}).update(texts.get(target, {}))
    return {element: re.sub(r"\s*\[(Member|Domain)\]\s*$", "", roles.get("terseLabel") or roles.get("label")).strip()
            for element, roles in found.items() if roles.get("terseLabel") or roles.get("label")}


def humanize(qname):
    """A readable name from an element name when there is no label: "nvda:CustomerOneMember" -> "Customer One"."""
    name = re.sub(r"(Member|Domain)$", "", _local(qname))
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name).strip()


def label_for(qname, labels):
    return labels.get(qname.replace(":", "_")) or humanize(qname)


def parse_instance(content):
    """(contexts, facts): contexts {id: {"dims": {axis: member qname}, "start", "end"}}; facts: the concentration percentages
    [{id, context, value, decimals}]."""
    root = ET.fromstring(content)
    contexts = {}
    for context in root.iter(XBRLI + "context"):
        period = context.find(XBRLI + "period")
        dims = {_local(m.get("dimension")): (m.text or "").strip() for m in context.iter(XBRLDI + "explicitMember")}
        contexts[context.get("id")] = {
            "dims": dims, "start": period.findtext(XBRLI + "startDate"),
            "end": period.findtext(XBRLI + "endDate") or period.findtext(XBRLI + "instant")}
    facts = []
    for el in root:
        if el.tag.rsplit("}", 1)[-1] == CONCEPT and (el.text or "").strip():
            facts.append({"id": el.get("id"), "context": el.get("contextRef"), "value": el.text.strip(), "decimals": el.get("decimals")})
    return contexts, facts


# ---------- Deciding what each fact means ----------

def measure_of(benchmark):
    """revenue / receivables / purchases from the benchmark member, or None for anything else (segments, assets ...)."""
    name = _local(benchmark or "")
    if "Segment" in name:
        return None
    if "Receivable" in name:
        return "receivables"
    if "Purchase" in name or "CostOf" in name or "Supplies" in name:
        return "purchases"
    if "Revenue" in name or name.startswith("Sales"):
        return "revenue"
    return None


def classify(label):
    """named / unnamed / group, from a member's label. "Customer A", "Major Customer One", "Undisclosed Customer 1",
    "Two Customer", "Supplier One", "Company A" are unnamed; "Top Ten Customers", "Three Largest Customers", "United States
    And Europe Based End Customers" and "Ablecom and Compuware" are groups; anything else names a company."""
    words = re.sub(r"[^a-z0-9 ]+", " ", label.lower()).split()
    if not words:
        return "unnamed"
    if any(w in GROUP_WORDS for w in words) or re.search(r"\S \b(and|&)\b \S", label, re.I):
        return "group"  # "Top Ten Customers"; "Ablecom and Compuware" is two companies, so not one share
    rest = [w for w in words if w not in QUALIFIERS and not w.isdigit() and not (len(w) == 1 and w.isalpha())]
    if rest and " ".join(rest) in ROLE_WORDS:
        return "unnamed"
    return "named"


def percent(value):
    """XBRL percentages are ratios (0.25); a few filers tag 25. Both are 25."""
    number = float(value)
    return round(number * 100 if number <= 1 else number, 4)


def concentration_rows(instance, labels=None):
    """The facts that are one counterparty's share, and those left out with the reason: (rows, skipped)."""
    labels = labels or {}
    contexts, facts = parse_instance(instance)
    rows, skipped, seen = [], [], {}
    for fact in facts:
        context = contexts.get(fact["context"])
        if context is None:
            continue
        dims = dict(context["dims"])
        benchmark = dims.pop("ConcentrationRiskByBenchmarkAxis", None)
        risk_type = dims.pop("ConcentrationRiskByTypeAxis", None)
        counterparty_axes = [axis for axis in dims if COUNTERPARTY_AXIS.search(axis)]
        base = {"fact": fact["id"], "context": fact["context"], "percent": percent(fact["value"]), "start": context["start"],
                "end": context["end"], "benchmark": benchmark, "benchmark_label": label_for(benchmark, labels) if benchmark else None,
                "risk_type": risk_type}
        if len(counterparty_axes) != 1:
            if counterparty_axes:
                skipped.append({**base, "reason": "several_counterparties"})
            continue  # a region, product line or segment share: not about one company, not reported
        axis = counterparty_axes[0]
        member = dims.pop(axis)
        notes = []
        for other, value in list(dims.items()):
            if other in NOTED_AXES:
                if NOTED_AXES[other]:
                    notes.append(f"{NOTED_AXES[other]}: {label_for(value, labels)}")
                dims.pop(other)
        label = label_for(member, labels)
        row = {**base, "member": member, "axis": axis, "label": label, "kind": classify(label), "measure": measure_of(benchmark),
               "notes": notes}
        if dims:
            skipped.append({**row, "reason": "narrowed_by_" + "_".join(sorted(dims))})
            continue
        if row["measure"] is None:
            skipped.append({**row, "reason": "unknown_benchmark"})
            continue
        if row["kind"] == "group":
            skipped.append({**row, "reason": "group_not_a_company"})
            continue
        key = (member, row["measure"], row["end"], tuple(notes))
        precision = int(fact["decimals"]) if (fact["decimals"] or "").lstrip("-").isdigit() else 0
        if key in seen and seen[key][0] >= precision:
            continue  # the same number tagged twice (once rounded): the more precise one is kept
        if key in seen:
            rows.remove(seen[key][1])
        seen[key] = (precision, row)
        rows.append(row)
    return rows, skipped


# ---------- Writing to the graph ----------

def quote_for(row):
    what = {"revenue": "of revenue", "receivables": "of accounts receivable", "purchases": f"of {row['benchmark_label'].lower()}"}[row["measure"]]
    period = f"{row['start']} to {row['end']}" if row["start"] else f"at {row['end']}"
    noted = f" ({'; '.join(row['notes'])})" if row["notes"] else ""
    return f"{row['label']}: {row['percent']:g}% {what}, {period}{noted} [us-gaap:{CONCEPT}, {_local(row['axis'])} = {row['member']}]"


def placeholder(conn, filer_id, filer_name, row, side):
    """The unnamed counterparty for one label and fiscal year (found again, not duplicated)."""
    name = f"{row['label']} (unnamed {side} of {filer_name}, year to {row['end']})"
    found = conn.execute("SELECT id FROM companies WHERE is_placeholder = 1 AND placeholder_for = ? AND name = ?", (filer_id, name)).fetchone()
    return found["id"] if found else graph.add_company(conn, name, placeholder_for=filer_id)


async def import_rows(conn, filer_id, document_id, rows, resolve=None):
    """Writes the rows as relationships with their evidence. Returns one result per row: {row, status (linked / rejected),
    relationship_id, counterparty_id, how}."""
    resolve = resolve or resolver.resolve
    filer_name = conn.execute("SELECT name FROM companies WHERE id = ?", (filer_id,)).fetchone()["name"]
    results = []
    for row in rows:
        supplier_side = row["measure"] == "purchases"
        quote = quote_for(row)
        if row["kind"] == "unnamed":
            counterparty, how = placeholder(conn, filer_id, filer_name, row, "supplier" if supplier_side else "customer"), "placeholder"
        else:
            match = await resolve(conn, row["label"])
            if match["status"] == "unavailable":
                raise RuntimeError(f"name lookup unavailable for {row['label']}: {match['detail']}")  # retried later
            if match["status"] != "matched" or match["company_id"] == filer_id:
                detail = match.get("detail") or "matched the filer itself"
                graph.reject(conn, document_id, quote, "unresolved_company", "rule",
                             supplier_name=row["label"] if supplier_side else filer_name,
                             customer_name=filer_name if supplier_side else row["label"], detail=f"{match.get('reason') or ''}: {detail}".strip(": "))
                results.append({"row": row, "status": "rejected", "how": match.get("reason") or "same_company", "relationship_id": None,
                                "counterparty_id": None})
                continue
            counterparty, how = match["company_id"], match["method"]
        evidence = {"document_id": document_id, "quote": quote, "tier": 1, "extractor": EXTRACTOR,
                    "locator": f"XBRL fact {row['fact'] or '(no id)'}, context {row['context']}",
                    "stated_on": row["end"], "share_note": "; ".join(row["notes"]) or None}
        if row["measure"] == "revenue":
            evidence["supplier_revenue_share"] = row["percent"]
        elif row["measure"] == "purchases":
            evidence["customer_supply_share"] = row["percent"]
            evidence["customer_share_scope"] = row["benchmark_label"].lower()
        else:
            evidence["share_note"] = "; ".join([f"{row['percent']:g}% of accounts receivable", *row["notes"]])
        supplier, customer = (counterparty, filer_id) if supplier_side else (filer_id, counterparty)
        relationship_id = graph.add_relationship(conn, supplier, customer, evidence, confidence=CONFIDENCE)
        graph.refresh_shares(conn, relationship_id)
        results.append({"row": row, "status": "linked", "how": how, "relationship_id": relationship_id, "counterparty_id": counterparty})
    return results


def instance_and_labels(files):
    """The instance document and label linkbase among a filing's files (inline XBRL: <doc>_htm.xml; older: <name>.xml)."""
    names = [f["name"] for f in files]
    instance = next((n for n in names if n.endswith("_htm.xml")), None) or next(
        (n for n in names if n.endswith(".xml") and not re.search(r"_(cal|def|lab|pre)\.xml$|FilingSummary", n)), None)
    labels = next((n for n in names if n.endswith("_lab.xml")), None)
    return instance, labels


async def import_filing(conn, company_id, cik, filing):
    """Reads one 10-K's tagged concentration figures into the graph. Returns {document_id, rows, skipped, results}."""
    document_id = sec.register_filing(conn, company_id, cik, filing)
    if document_id is None:
        raise Permanent("the filing has no main document")
    instance_name, labels_name = instance_and_labels(await sec_client.filing_files(cik, filing["accession"]))
    if instance_name is None:
        return {"document_id": document_id, "rows": [], "skipped": [], "results": [], "note": "no XBRL data in the filing"}
    instance = await sec_client.get_bytes(sec_client.document_url(cik, filing["accession"], instance_name))
    labels = parse_labels(await sec_client.get_bytes(sec_client.document_url(cik, filing["accession"], labels_name))) if labels_name else {}
    rows, skipped = concentration_rows(instance, labels)
    results = await import_rows(conn, company_id, document_id, rows)
    return {"document_id": document_id, "rows": rows, "skipped": skipped, "results": results}


@handler("xbrl")
async def xbrl_job(job, conn):
    p = job["payload"]
    try:
        outcome = await import_filing(conn, job["company_id"], p["cik"], p["filing"])
    except sec_client.SecNotFound as exc:
        raise Permanent(str(exc)) from exc
    linked = sum(1 for r in outcome["results"] if r["status"] == "linked")
    rejected = len(outcome["results"]) - linked
    return {"notes": outcome.get("note") or f"{linked} linked, {rejected} unresolved, {len(outcome['skipped'])} left out"}
