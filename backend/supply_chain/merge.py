"""Relationship merge (#127): one link per pair of companies, kept up to date from all of its evidence.

The same link arrives from many documents (XBRL tier 1, Reader tier 2, several years of 10-Ks). graph.add_relationship
and graph.add_evidence add each statement to the one link (a partnership has no direction: A-B and B-A are one link,
stored with the lower company id first), then refresh() recomputes the link from all its evidence:
- shares: per share, the newest statement wins; for the same period, a tier 1 figure beats a tier 2 one;
- confidence (CONFIDENCE, read through level() by every consumer): high = a tier 1 source, or verified tier 2 evidence
  from two different documents (another filing, or another year's); medium = verified tier 2 from one document, or
  tier 3 confirmed by a second independent document; low = one tier 3 source (or unverified tier 2). Whether the
  counterparty is named and whether a share is known are separate fields, not part of confidence (#333);
- first_seen / last_confirmed: the earliest and latest dates the statements are about (stated_on, else the report's
  period end, else its filing date);
- status: ended when the newest statement says it ended (ended_at = that statement's date); otherwise stale when the
  newest statement is over STALE_MONTHS old; otherwise active. A statement dated after ended_at revives an ended link,
  one dated earlier (an older filing read later) doesn't. Nothing is deleted.

upgrade_placeholders() merges a "Customer A" link into the named link when a document names that customer with the
same share for the same period; only when exactly one named company and one placeholder match (a wrong merge is worse
than two links). undo() reverses one. The daily "merge" job (recompute_all) does staleness, upgrades and a full recompute.

join_placeholders() (#335) merges "Customer one", "a direct customer" and "one direct customer" when they are the same filer's
customer for the same period with the same share: see placeholder_groups() for the conditions. Without a share nothing merges.
"""
import re
from datetime import date, datetime, timezone
from urllib.parse import urlparse

from supply_chain import graph, jobs
from supply_chain.db import now, transaction
from supply_chain.worker import handler

CONFIDENCE = {"high": 0.9, "medium": 0.6, "low": 0.3}
STALE_MONTHS = 18
MERGE_PRIORITY = 20  # no AI and quick: after the pipeline's real work
SHARES = (("supplier_revenue_share", ()), ("customer_supply_share", ("customer_share_scope",)))


def level(confidence):
    """"high", "medium" or "low" for a stored confidence: the one place the thresholds live (Milestone 12's UI, and the
    rule that low links are never used, read it from here)."""
    if confidence is None:
        return None
    if confidence >= (CONFIDENCE["high"] + CONFIDENCE["medium"]) / 2:
        return "high"
    if confidence >= (CONFIDENCE["medium"] + CONFIDENCE["low"]) / 2:
        return "medium"
    return "low"


def _today(today=None):
    return today or datetime.now(timezone.utc).date()


def months_before(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    month += 1
    for d in (day.day, 30, 29, 28):  # the 31st of a shorter month
        try:
            return date(year, month, d)
        except ValueError:
            continue


# ---------- Recomputing one link ----------

def evidence_rows(conn, relationship_id):
    """The link's evidence with its document, each with on: the date its statement is about."""
    return conn.execute(
        """SELECT e.*, d.source, d.url, d.content_hash, d.period_end, d.filed_at,
                  COALESCE(e.stated_on, d.period_end, d.filed_at, substr(e.created_at, 1, 10)) AS on_date
           FROM evidence e JOIN documents d ON d.id = e.document_id WHERE e.relationship_id = ? ORDER BY e.id""",
        (relationship_id,)).fetchall()


def _publisher(row):
    host = urlparse(row["url"] or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def confidence_of(rows):
    if any(r["tier"] == 1 for r in rows):
        return CONFIDENCE["high"]
    verified = [r for r in rows if r["tier"] == 2 and r["verification"] == "verified"]
    # one sentence in one document is medium; a second document (another filing or year) makes it high. A document
    # is told apart by its text, so the same filing read twice, or evidence copied by a placeholder upgrade, counts once.
    if len({r["content_hash"] or ("document", r["document_id"]) for r in verified}) >= 2:
        return CONFIDENCE["high"]
    if verified:
        return CONFIDENCE["medium"]
    # tier 3 confirmed by a second independent document: another publisher, not the same text
    news = {(_publisher(r), r["content_hash"] or r["document_id"]) for r in rows if r["tier"] == 3}
    if len({publisher for publisher, _ in news}) >= 2:
        return CONFIDENCE["medium"]
    return CONFIDENCE["low"]


def computed(rows, today=None):
    """What the link should hold, from its evidence."""
    values = {"tier": min(r["tier"] for r in rows), "confidence": confidence_of(rows)}
    as_of = []
    for column, extra in SHARES:
        stating = [r for r in rows if r[column] is not None]
        if stating:
            best = max(stating, key=lambda r: (r["on_date"], -r["tier"], r["id"]))  # newest, then tier 1 over tier 2
            values[column] = best[column]
            for name in extra:
                values[name] = best[name]
            as_of.append(best["on_date"])
        else:
            values[column] = None
            for name in extra:
                values[name] = None
    values["shares_as_of"] = max(as_of) if as_of else None
    dates = [r["on_date"] for r in rows]
    values["first_seen"], values["last_confirmed"] = min(dates), max(dates)
    ended = [r["on_date"] for r in rows if r["states_ended"]]
    ongoing = [r["on_date"] for r in rows if not r["states_ended"]]
    if ended and max(ended) >= max(ongoing, default=""):
        values["status"], values["ended_at"] = "ended", max(ended)
    elif values["last_confirmed"] < months_before(_today(today), STALE_MONTHS).isoformat():
        values["status"], values["ended_at"] = "stale", None
    else:
        values["status"], values["ended_at"] = "active", None
    return values


def refresh(conn, relationship_id, today=None):
    """Recomputes one link from its evidence; writes only what changed. Returns True if anything did."""
    rows = evidence_rows(conn, relationship_id)
    if not rows:
        return False
    values = computed(rows, today)
    current = conn.execute(f"SELECT {', '.join(values)} FROM relationships WHERE id = ?", (relationship_id,)).fetchone()
    changed = {k: v for k, v in values.items() if current[k] != v}
    if not changed:
        return False
    conn.execute(f"UPDATE relationships SET {', '.join(f'{k} = ?' for k in changed)}, updated_at = ? WHERE id = ?",
                 (*changed.values(), now(), relationship_id))
    return True


# ---------- Moving evidence between links ----------

def _copy_evidence(conn, from_id, to_id):
    """Copies a link's own evidence onto another (copied_from marks the copies, so undo can take them back)."""
    copied = 0
    for row in conn.execute("SELECT * FROM evidence WHERE relationship_id = ? AND copied_from IS NULL ORDER BY id", (from_id,)).fetchall():
        fields = {k: row[k] for k in ("document_id", "quote", "tier", "extractor", *graph.EVIDENCE_FIELDS) if k != "copied_from"}
        before = conn.execute("SELECT COUNT(*) FROM evidence WHERE relationship_id = ?", (to_id,)).fetchone()[0]
        graph.add_evidence(conn, to_id, {**fields, "copied_from": row["id"]})
        copied += conn.execute("SELECT COUNT(*) FROM evidence WHERE relationship_id = ?", (to_id,)).fetchone()[0] - before
    return copied


def normalise_partnerships(conn):
    """Stores every partnership with the lower company id first; when both orders exist, B-A's evidence joins A-B and
    B-A is marked merged into it. Returns how many were changed."""
    changed = 0
    for row in conn.execute("""SELECT id, supplier_id, customer_id FROM relationships WHERE kind = 'partnership' AND supplier_id > customer_id
                               AND merged_into IS NULL""").fetchall():
        twin = conn.execute("SELECT id FROM relationships WHERE kind = 'partnership' AND supplier_id = ? AND customer_id = ?",
                            (row["customer_id"], row["supplier_id"])).fetchone()
        if twin:
            _copy_evidence(conn, row["id"], twin["id"])
            conn.execute("UPDATE relationships SET merged_into = ?, updated_at = ? WHERE id = ?", (twin["id"], now(), row["id"]))
        else:
            conn.execute("UPDATE relationships SET supplier_id = ?, customer_id = ?, updated_at = ? WHERE id = ?",
                         (row["customer_id"], row["supplier_id"], now(), row["id"]))
        changed += 1
    return changed


# ---------- Placeholder upgrades ----------

def decimals(value):
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return len(text.split(".")[1]) if "." in text else 0


def same_share(a, b):
    """Equal at the precision of the less precise figure: "23%" covers 22.5 to 23.5, so it matches 23.4; 23.4 and 23.1 don't."""
    tolerance = 0.5 * 10 ** -min(decimals(a), decimals(b))
    return abs(a - b) <= tolerance + 1e-9


def _trusted_facts(conn):
    """Share figures from trusted evidence (tier 1, or verified tier 2) of supply links not merged away."""
    facts = []
    for row in conn.execute(
            """SELECT r.id AS relationship_id, r.supplier_id, r.customer_id, e.supplier_revenue_share, e.customer_supply_share,
                      e.customer_share_scope, COALESCE(e.stated_on, d.period_end, d.filed_at) AS on_date
               FROM evidence e JOIN relationships r ON r.id = e.relationship_id JOIN documents d ON d.id = e.document_id
               WHERE r.kind = 'supplies' AND r.merged_into IS NULL AND e.copied_from IS NULL
                 AND (e.tier = 1 OR (e.tier = 2 AND e.verification = 'verified'))"""):
        for column, _ in SHARES:
            if row[column] is not None:
                facts.append({"relationship_id": row["relationship_id"], "supplier_id": row["supplier_id"], "customer_id": row["customer_id"],
                              "measure": column, "value": row[column], "scope": (row["customer_share_scope"] or "").lower() if column == "customer_supply_share" else "",
                              "on": row["on_date"]})
    return facts


def _matches(fact, other):
    return (fact["measure"] == other["measure"] and fact["on"] == other["on"] and same_share(fact["value"], other["value"])
            and (not fact["scope"] or not other["scope"] or fact["scope"] == other["scope"]))


def upgrade_candidates(conn):
    """[(placeholder link, named link, the matching fact)] that pass every condition:
    - the placeholder belongs to the filer on the other side of its link, and that link is its only one;
    - the named link has the same filer on the same side, a named (not placeholder) counterparty, and is a supply link;
    - a trusted figure (tier 1, or verified tier 2; a share the Reader dropped is no figure) of the same measure and scope,
      for the same period, equal at the precision of the less precise figure;
    - unique both ways: exactly one named link matches the placeholder, and no other placeholder of the filer matches
      that named link's figure;
    - the pair was never undone."""
    companies = {r["id"]: r for r in conn.execute("SELECT id, is_placeholder, placeholder_for, merged_into FROM companies")}
    facts = _trusted_facts(conn)
    by_link = {}
    for fact in facts:
        by_link.setdefault(fact["relationship_id"], []).append(fact)
    links = {r["id"]: r for r in conn.execute("SELECT id, supplier_id, customer_id FROM relationships WHERE kind = 'supplies' AND merged_into IS NULL")}

    def placeholder_side(link):
        for side, other in (("customer", "supplier"), ("supplier", "customer")):
            company = companies[link[f"{side}_id"]]
            if company["is_placeholder"] and company["merged_into"] is None and company["placeholder_for"] == link[f"{other}_id"]:
                return side, other
        return None

    def named_matches(fact, filer_id, side, other):
        return {f["relationship_id"] for f in facts
                if f[f"{other}_id"] == filer_id and not companies[f[f"{side}_id"]]["is_placeholder"] and _matches(fact, f)}

    undone = {(r["placeholder_relationship_id"], r["relationship_id"])
              for r in conn.execute("SELECT * FROM merge_decisions WHERE decision = 'undone'")}
    found = []
    for link_id, link in links.items():
        sides = placeholder_side(link)
        if not sides or link_id not in by_link:
            continue
        side, other = sides
        placeholder, filer_id = link[f"{side}_id"], link[f"{other}_id"]
        if conn.execute("SELECT COUNT(*) FROM relationships WHERE (supplier_id = ? OR customer_id = ?) AND merged_into IS NULL",
                        (placeholder, placeholder)).fetchone()[0] != 1:
            continue  # a placeholder in more than one link: not one simple fact to match
        named = set().union(*(named_matches(f, filer_id, side, other) for f in by_link[link_id]))
        if len(named) != 1:
            continue  # none, or ambiguous: keep both links
        target = named.pop()
        if (link_id, target) in undone:
            continue
        # the other way round: no other placeholder of this filer matches the named link's figures
        rivals = {f["relationship_id"] for g in by_link[target] for f in facts
                  if f["relationship_id"] != link_id and placeholder_side(links[f["relationship_id"]]) == sides
                  and f[f"{other}_id"] == filer_id and _matches(g, f)}
        if rivals:
            continue
        fact = next(f for f in by_link[link_id] if any(_matches(f, g) for g in by_link[target]))
        found.append((link_id, target, fact))
    return found


def upgrade(conn, placeholder_link, named_link, fact):
    """Merges a placeholder link into the named one: its evidence is copied over, and the link and the placeholder company
    are marked merged_into (nothing is deleted)."""
    link = conn.execute("SELECT supplier_id, customer_id FROM relationships WHERE id = ?", (placeholder_link,)).fetchone()
    named = conn.execute("SELECT supplier_id, customer_id FROM relationships WHERE id = ?", (named_link,)).fetchone()
    side = "customer" if conn.execute("SELECT is_placeholder FROM companies WHERE id = ?", (link["customer_id"],)).fetchone()[0] else "supplier"
    _copy_evidence(conn, placeholder_link, named_link)
    with transaction(conn):
        conn.execute("UPDATE relationships SET merged_into = ?, updated_at = ? WHERE id = ?", (named_link, now(), placeholder_link))
        conn.execute("UPDATE companies SET merged_into = ?, updated_at = ? WHERE id = ?", (named[f"{side}_id"], now(), link[f"{side}_id"]))
        # links already merged into this one (#335: duplicates joined into a placeholder that is now itself merged) follow it, so
        # nothing is merged into a merged link, and the evidence they copied here moves with them (undo still finds it by copied_from)
        conn.execute("UPDATE relationships SET merged_into = ?, updated_at = ? WHERE merged_into = ?", (named_link, now(), placeholder_link))
        conn.execute("UPDATE companies SET merged_into = ?, updated_at = ? WHERE merged_into = ?", (named[f"{side}_id"], now(), link[f"{side}_id"]))
        conn.execute("UPDATE merge_decisions SET relationship_id = ? WHERE relationship_id = ? AND decision = 'merged'", (named_link, placeholder_link))
        for copy in conn.execute("SELECT id, document_id, quote_hash FROM evidence WHERE relationship_id = ? AND copied_from IS NOT NULL", (placeholder_link,)).fetchall():
            if conn.execute("SELECT 1 FROM evidence WHERE relationship_id = ? AND document_id = ? AND quote_hash = ?", (named_link, copy["document_id"], copy["quote_hash"])).fetchone():
                conn.execute("DELETE FROM evidence WHERE id = ?", (copy["id"],))
            else:
                conn.execute("UPDATE evidence SET relationship_id = ? WHERE id = ?", (named_link, copy["id"]))
        conn.execute("INSERT INTO merge_decisions (placeholder_relationship_id, relationship_id, decision, detail, created_at) VALUES (?, ?, 'merged', ?, ?)",
                     (placeholder_link, named_link, f"{fact['measure']} {fact['value']:g}% for {fact['on']}", now()))
    refresh(conn, named_link)
    refresh(conn, placeholder_link)  # it may have handed on copies it held (#335), which changes its own confidence


def upgrade_placeholders(conn):
    """Every upgrade that passes the conditions. Returns [(placeholder link, named link)]."""
    done = []
    for placeholder_link, named_link, fact in upgrade_candidates(conn):
        upgrade(conn, placeholder_link, named_link, fact)
        done.append((placeholder_link, named_link))
    return done


# ---------- Placeholders that are the same unnamed counterparty (#335) ----------

IDENTIFIER = re.compile(r"\b(?:customer|supplier|company|partner|distributor|client|vendor)\s+([a-z]|\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b")
NUMBER_WORDS = {w: str(n) for n, w in enumerate("one two three four five six seven eight nine ten".split(), 1)}


def label_identifier(name):
    """The letter or number a filing gives an unnamed counterparty ("Customer A" -> "a", "Customer one" -> "1"), or None for
    "a direct customer". Two labels with different identifiers in one filing are two counterparties."""
    label = re.sub(r" in the .* filed \d{4}-\d{2}-\d{2}$", "", str(name).split(" (unnamed", 1)[0]).lower()
    if re.search(r"\b\d+ of \d+$", label):
        return None  # the Reader's numbering in the order a sentence lists them (#341), not a label the filing gives
    match = IDENTIFIER.search(label)
    return NUMBER_WORDS.get(match.group(1), match.group(1)) if match else None


def _known_different(conn, a, b, names):
    """Whether two placeholder links are provably two counterparties: different identifiers in their labels (names: the
    placeholder company's name per link), a structured (tier 1) list of the same document naming both, or one quote naming both."""
    ids = (label_identifier(names[a]), label_identifier(names[b]))
    if ids[0] and ids[1] and ids[0] != ids[1]:
        return True
    rows = {link: conn.execute("SELECT document_id, tier, quote_hash FROM evidence WHERE relationship_id = ? AND copied_from IS NULL", (link,)).fetchall()
            for link in (a, b)}
    for x in rows[a]:
        for y in rows[b]:
            if x["quote_hash"] == y["quote_hash"] or (x["document_id"] == y["document_id"] and x["tier"] == 1 and y["tier"] == 1):
                return True
    return False


def placeholder_groups(conn):
    """[(links to merge, the shared fact)]: sets of placeholder links that are one unnamed counterparty. Every condition:
    - each placeholder belongs to the same filer, stands on the same side of a supply link and is in no other link;
    - each has a trusted figure (tier 1, or verified tier 2; a link without a share is never merged) of the same measure and
      scope for the same statement date, equal at the precision of the less precise figure (same_share), and every pair in
      the set matches (23.4 and 23.1 don't, so 23 / 23.4 / 23.1 stays apart);
    - unique at that share: the set holds every such placeholder of the filer, and none of its pairs is known to be two
      counterparties (_known_different: "Customer A" and "Customer B", a tier 1 list naming both, one quote naming both);
    - no pair was undone."""
    companies = {r["id"]: r for r in conn.execute("SELECT id, name, is_placeholder, placeholder_for, merged_into FROM companies")}
    facts = _trusted_facts(conn)
    links = {r["id"]: r for r in conn.execute("SELECT id, supplier_id, customer_id FROM relationships WHERE kind = 'supplies' AND merged_into IS NULL")}
    by_link = {}
    for fact in facts:
        if fact["relationship_id"] in links:
            by_link.setdefault(fact["relationship_id"], []).append(fact)
    undone = {frozenset((r["placeholder_relationship_id"], r["relationship_id"]))
              for r in conn.execute("SELECT * FROM merge_decisions WHERE decision = 'undone'")}

    def placeholder_of(link):
        for side, other in (("customer", "supplier"), ("supplier", "customer")):
            company = companies[link[f"{side}_id"]]
            if company["is_placeholder"] and company["merged_into"] is None and company["placeholder_for"] == link[f"{other}_id"]:
                return side, link[f"{other}_id"], link[f"{side}_id"]
        return None

    candidates = {}
    for link_id, link in links.items():
        found = placeholder_of(link)
        if found is None or link_id not in by_link:
            continue
        if conn.execute("SELECT COUNT(*) FROM relationships WHERE (supplier_id = ? OR customer_id = ?) AND merged_into IS NULL",
                        (found[2], found[2])).fetchone()[0] != 1:
            continue
        candidates[link_id] = found

    def match(a, b):
        if candidates[a][:2] != candidates[b][:2]:
            return None
        return next((f for f in by_link[a] for g in by_link[b] if _matches(f, g)), None)

    names = {link_id: companies[found[2]]["name"] for link_id, found in candidates.items()}
    groups, seen = [], set()
    for link_id in sorted(candidates):
        if link_id in seen:
            continue
        group = [link_id] + [other for other in sorted(candidates) if other != link_id and match(link_id, other)]
        seen.update(group)
        if len(group) < 2:
            continue
        pairs = [(a, b) for i, a in enumerate(group) for b in group[i + 1:]]
        if any(match(a, b) is None or frozenset((a, b)) in undone or _known_different(conn, a, b, names) for a, b in pairs):
            continue  # not one clear counterparty: keep every link
        groups.append((group, match(group[0], group[1])))
    return groups


def join_placeholders(conn):
    """Merges each group of placeholder links into one (the one with tier 1 evidence, else the oldest): evidence copied over,
    the others' links and placeholder companies marked merged_into, a merge_decisions row each (undo reverses one).
    Returns [(merged link, kept link)]."""
    done = []
    for group, fact in placeholder_groups(conn):
        tier_one = {r[0] for r in conn.execute(f"SELECT DISTINCT relationship_id FROM evidence WHERE tier = 1 AND relationship_id IN ({', '.join('?' * len(group))})", group)}
        keep = min(group, key=lambda link: (link not in tier_one, link))
        for other in group:
            if other != keep:
                upgrade(conn, other, keep, fact)
                done.append((other, keep))
    return done


def undo(conn, relationship_id):
    """Reverses the upgrade of a placeholder link (its id): the copies of its evidence are taken off the named link, the
    link and its placeholder company are no longer merged, and the pair is never upgraded again. Returns the named link."""
    link = conn.execute("SELECT * FROM relationships WHERE id = ?", (relationship_id,)).fetchone()
    if link is None or link["merged_into"] is None:
        raise ValueError(f"relationship {relationship_id} wasn't merged")
    named_link = link["merged_into"]
    own = [r["id"] for r in conn.execute("SELECT id FROM evidence WHERE relationship_id = ?", (relationship_id,))]
    with transaction(conn):
        conn.execute(f"DELETE FROM evidence WHERE relationship_id = ? AND copied_from IN ({', '.join('?' * len(own))})", (named_link, *own))
        conn.execute("UPDATE relationships SET merged_into = NULL, updated_at = ? WHERE id = ?", (now(), relationship_id))
        for side in ("supplier", "customer"):
            conn.execute("UPDATE companies SET merged_into = NULL, updated_at = ? WHERE id = ? AND is_placeholder = 1", (now(), link[f"{side}_id"]))
        conn.execute("INSERT INTO merge_decisions (placeholder_relationship_id, relationship_id, decision, detail, created_at) VALUES (?, ?, 'undone', NULL, ?)",
                     (relationship_id, named_link, now()))
    refresh(conn, named_link)
    refresh(conn, relationship_id)
    return named_link


# ---------- Everything, and the daily job ----------

def recompute_all(conn, today=None):
    """Partnerships in one order, every link recomputed (no row keeps an old placeholder confidence), then placeholder
    upgrades. Returns {relationships, changed, partnerships, upgraded}."""
    partnerships = normalise_partnerships(conn)
    ids = [r["id"] for r in conn.execute("SELECT id FROM relationships ORDER BY id")]
    changed = sum(refresh(conn, rid, today) for rid in ids)
    upgraded = upgrade_placeholders(conn)
    joined = join_placeholders(conn)
    return {"relationships": len(ids), "changed": changed, "partnerships": partnerships, "upgraded": len(upgraded), "joined": len(joined)}


def schedule(conn, today=None):
    """Queues today's merge job once a day. Returns True when it queued one."""
    key = _today(today).isoformat()
    if conn.execute("SELECT 1 FROM jobs WHERE kind = 'merge' AND key = ?", (key,)).fetchone():
        return False
    jobs.enqueue(conn, "merge", key, priority=MERGE_PRIORITY)
    return True


@handler("merge")
async def merge_job(job, conn):
    result = recompute_all(conn)
    return {"notes": f"{result['relationships']} links, {result['changed']} updated, {result['upgraded']} placeholders upgraded"
                     + (f", {result['joined']} duplicate unnamed counterparties joined" if result["joined"] else "")
                     + (f", {result['partnerships']} partnerships reordered" if result["partnerships"] else "")}
