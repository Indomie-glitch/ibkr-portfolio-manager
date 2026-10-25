"""SEC filings in the supply chain store (#117): registers a filing as a document, and downloads and hashes it.

Documents are keyed (source "sec", external_id = accession number + file name), so seeing the same filing twice
registers it once. A document starts "discovered"; fetch_document downloads the file, stores its SHA-256 and path and
marks it "downloaded".
"""
import sec_client
from supply_chain import graph
from supply_chain.db import now

SOURCE = "sec"


def external_id(accession, filename):
    return f"{accession}/{filename}"


def register_filing(conn, company_id, cik, filing):
    """Adds a filing (a dict from sec_client.list_filings) as a document; returns its id, or None when it has no main document."""
    if not filing.get("primary_document"):
        return None
    return graph.add_document(
        conn, SOURCE, filing["form"], external_id(filing["accession"], filing["primary_document"]), filing["url"],
        company_id=company_id, title=f"{filing['form']} {filing['filed']}", filed_at=filing["filed"], period_end=filing.get("period"),
        language="en", status="discovered")


async def fetch_document(conn, document_id, cik, accession, filename):
    """Downloads a registered document and records its hash; one that's already fetched isn't downloaded again."""
    row = conn.execute("SELECT status, content_hash FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        raise ValueError(f"no document {document_id}")
    if row["status"] == "downloaded" and row["content_hash"]:
        return row["content_hash"]
    saved = await sec_client.download(cik, accession, filename)
    conn.execute("UPDATE documents SET content_hash = ?, size_bytes = ?, local_path = ?, fetched_at = ?, status = 'downloaded' WHERE id = ?",
                 (saved["sha256"], saved["size"], saved["path"], now(), document_id))
    return saved["sha256"]
