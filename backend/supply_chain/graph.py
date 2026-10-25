"""Writing to the graph (#115). Small on purpose: the checks that matter are in the schema itself;
these functions make the common writes correct and repeatable (the same fact twice is one row).

A relationship is always created together with the evidence it came from, in one transaction, because
the schema refuses a relationship without it."""
import hashlib
import json
import re
import sqlite3

from supply_chain.db import now, transaction

IDENTIFIER_SCHEMES = ("ticker", "isin", "figi", "share_class_figi", "cik", "lei", "wikidata", "mops", "edinet", "dart", "asx", "name")
RELATIONSHIP_KINDS = ("supplies", "partnership")
EVIDENCE_FIELDS = ("locator", "supplier_revenue_share", "customer_supply_share", "customer_share_scope", "share_note", "stated_on",
                   "verification", "verified_by", "states_ended", "run_id")


class IdentifierConflict(Exception):
    """That identifier already belongs to another company."""


def text_hash(*parts):
    """SHA-256 of the parts with whitespace and case normalised: "The same quote" however it was spaced."""
    joined = "␟".join(re.sub(r"\s+", " ", str(p or "")).strip().lower() for p in parts)
    return hashlib.sha256(joined.encode()).hexdigest()


# ---------- Companies and identifiers ----------

def add_company(conn, name, country=None, sector=None, industry=None, placeholder_for=None):
    """A new company (a placeholder when placeholder_for is the company whose filing said "Customer A")."""
    stamp = now()
    return conn.execute(
        "INSERT INTO companies (name, country, sector, industry, is_placeholder, placeholder_for, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, country, sector, industry, 1 if placeholder_for else 0, placeholder_for, stamp, stamp)).lastrowid


def find_company(conn, scheme, value, market=""):
    row = conn.execute("SELECT company_id FROM identifiers WHERE scheme = ? AND market = ? AND value = ?", (scheme, market, value)).fetchone()
    return row["company_id"] if row else None


def add_identifier(conn, company_id, scheme, value, market="", source=None):
    """Attaches an identifier to a company. The same one again is a no-op; one that belongs to another
    company raises IdentifierConflict (two companies sharing a ticker is a mistake to look at, not hide)."""
    if scheme not in IDENTIFIER_SCHEMES:
        raise ValueError(f"unknown identifier scheme {scheme!r}")
    owner = find_company(conn, scheme, value, market)
    if owner is not None:
        if owner != company_id:
            raise IdentifierConflict(f"{scheme} {value} ({market or 'any market'}) already belongs to company {owner}")
        return conn.execute("SELECT id FROM identifiers WHERE scheme = ? AND market = ? AND value = ?", (scheme, market, value)).fetchone()["id"]
    return conn.execute("INSERT INTO identifiers (company_id, scheme, value, market, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (company_id, scheme, value, market, source, now())).lastrowid


# ---------- Documents ----------

def add_document(conn, source, kind, external_id, url, **fields):
    """A document we know of. The same (source, external_id) again returns the existing one."""
    row = conn.execute("SELECT id FROM documents WHERE source = ? AND external_id = ?", (source, external_id)).fetchone()
    if row:
        return row["id"]
    allowed = ("company_id", "title", "filed_at", "period_end", "language", "content_hash", "size_bytes", "local_path", "fetched_at", "status")
    extra = {k: v for k, v in fields.items() if k in allowed}
    if len(extra) != len(fields):
        raise ValueError(f"unknown document fields: {sorted(set(fields) - set(allowed))}")
    columns = ["source", "kind", "external_id", "url", "created_at", *extra]
    return conn.execute(f"INSERT INTO documents ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})",
                        [source, kind, external_id, url, now(), *extra.values()]).lastrowid


# ---------- Relationships and their evidence ----------

def _evidence_row(relationship_id, evidence):
    for needed in ("document_id", "quote", "tier", "extractor"):
        value = evidence.get(needed)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"evidence needs {needed}")
    unknown = set(evidence) - set(EVIDENCE_FIELDS) - {"document_id", "quote", "tier", "extractor"}
    if unknown:
        raise ValueError(f"unknown evidence fields: {sorted(unknown)}")
    return {"relationship_id": relationship_id, "quote_hash": text_hash(evidence["quote"]), "created_at": now(), **evidence}


def _insert_evidence(conn, row):
    columns = list(row)
    return conn.execute(f"INSERT INTO evidence ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})", list(row.values())).lastrowid


def add_evidence(conn, relationship_id, evidence):
    """More evidence for an existing relationship; the same quote from the same document is stored once.
    Returns the evidence id. Updates the relationship's last_seen and, if this evidence is better, its tier."""
    row = _evidence_row(relationship_id, evidence)
    with transaction(conn):
        found = conn.execute("SELECT id FROM evidence WHERE relationship_id = ? AND document_id = ? AND quote_hash = ?",
                             (relationship_id, row["document_id"], row["quote_hash"])).fetchone()
        evidence_id = found["id"] if found else _insert_evidence(conn, row)
        conn.execute("UPDATE relationships SET last_seen = ?, updated_at = ?, tier = MIN(tier, ?) WHERE id = ?",
                     (now(), now(), row["tier"], relationship_id))
    return evidence_id


def add_relationship(conn, supplier_id, customer_id, evidence, kind="supplies", what=None, supplier_revenue_share=None,
                     customer_supply_share=None, customer_share_scope=None, shares_as_of=None, confidence=0.0):
    """The supplier sells to the customer, with the evidence it came from (a dict: document_id, quote, tier,
    extractor, and optionally locator, shares, stated_on, ...). Both rows are written in one transaction;
    without evidence nothing is written. If the link already exists the evidence is added to it. Returns
    the relationship id."""
    if kind not in RELATIONSHIP_KINDS:
        raise ValueError(f"unknown relationship kind {kind!r}")
    row = _evidence_row(None, evidence)
    existing = conn.execute("SELECT id FROM relationships WHERE supplier_id = ? AND customer_id = ? AND kind = ?",
                            (supplier_id, customer_id, kind)).fetchone()
    if existing:
        add_evidence(conn, existing["id"], evidence)
        return existing["id"]
    stamp = now()
    with transaction(conn):
        # primary_evidence_id 0 is a placeholder until the evidence row exists; the deferred foreign key
        # is only checked at the commit, by which time it points at the real one
        relationship_id = conn.execute(
            """INSERT INTO relationships (supplier_id, customer_id, kind, what, supplier_revenue_share, customer_supply_share, customer_share_scope,
               shares_as_of, confidence, tier, first_seen, last_seen, primary_evidence_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (supplier_id, customer_id, kind, what, supplier_revenue_share, customer_supply_share, customer_share_scope, shares_as_of,
             confidence, row["tier"], stamp, stamp, stamp, stamp)).lastrowid
        evidence_id = _insert_evidence(conn, {**row, "relationship_id": relationship_id})
        conn.execute("UPDATE relationships SET primary_evidence_id = ? WHERE id = ?", (evidence_id, relationship_id))
    return relationship_id


def refresh_shares(conn, relationship_id):
    """Sets the relationship's shares from its newest evidence that states each one (by stated_on), so a later filing's
    figure replaces an older one while the older stays as evidence."""
    stamp = now()
    for columns in (("supplier_revenue_share",), ("customer_supply_share", "customer_share_scope")):
        row = conn.execute(f"""SELECT {', '.join(columns)}, stated_on FROM evidence WHERE relationship_id = ? AND {columns[0]} IS NOT NULL
                               ORDER BY stated_on DESC, id DESC LIMIT 1""", (relationship_id,)).fetchone()
        if row:
            assignments = ", ".join(f"{c} = ?" for c in columns)
            conn.execute(f"UPDATE relationships SET {assignments}, shares_as_of = MAX(COALESCE(shares_as_of, ''), ?), updated_at = ? WHERE id = ?",
                         (*[row[c] for c in columns], row["stated_on"], stamp, relationship_id))


# ---------- Rejected candidates ----------

def reject(conn, document_id, quote, reason, rejected_by, supplier_name=None, customer_name=None, supplier_id=None, customer_id=None,
           detail=None, payload=None, run_id=None):
    """Records a candidate relationship that was refused, so it isn't extracted and checked again. The same
    candidate (names and quote) from the same document is stored once."""
    candidate = text_hash(supplier_name, customer_name, quote)
    row = conn.execute("SELECT id FROM rejected WHERE document_id = ? AND candidate_hash = ?", (document_id, candidate)).fetchone()
    if row:
        return row["id"]
    return conn.execute(
        """INSERT INTO rejected (document_id, run_id, supplier_name, customer_name, supplier_id, customer_id, quote, candidate_hash, payload,
           reason, detail, rejected_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (document_id, run_id, supplier_name, customer_name, supplier_id, customer_id, quote, candidate,
         json.dumps(payload) if payload is not None else None, reason, detail, rejected_by, now())).lastrowid


# ---------- Themes ----------

def add_theme(conn, slug, name, description=None):
    row = conn.execute("SELECT id FROM themes WHERE slug = ?", (slug,)).fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO themes (slug, name, description, created_at) VALUES (?, ?, ?, ?)", (slug, name, description, now())).lastrowid


def add_to_theme(conn, theme_id, company_id, segment=None):
    try:
        conn.execute("INSERT INTO theme_companies (theme_id, company_id, segment, added_at) VALUES (?, ?, ?, ?)", (theme_id, company_id, segment, now()))
    except sqlite3.IntegrityError:
        conn.execute("UPDATE theme_companies SET segment = COALESCE(?, segment) WHERE theme_id = ? AND company_id = ?", (segment, theme_id, company_id))
