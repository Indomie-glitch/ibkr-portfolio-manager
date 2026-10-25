"""Tests for the supply chain graph schema (#115): migrations, and above all that every relationship points
to the evidence it came from. Each test gets its own temporary database file."""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PORTFOLIO_DATA_DIR", tempfile.mkdtemp())

from supply_chain import db, graph, integrity  # noqa: E402
from supply_chain.migrations import MIGRATIONS  # noqa: E402

TABLES = {"companies", "identifiers", "documents", "relationships", "evidence", "rejected", "jobs", "runs", "themes",
          "theme_companies", "schema_migrations"}


class GraphCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "supply_chain.sqlite"
        self.conn = db.open_graph(self.path)
        self.addCleanup(self.conn.close)
        self.tsmc = graph.add_company(self.conn, "Taiwan Semiconductor Manufacturing", country="TW")
        self.apple = graph.add_company(self.conn, "Apple Inc.", country="US")
        self.nvidia = graph.add_company(self.conn, "NVIDIA Corporation", country="US")
        self.doc = graph.add_document(self.conn, "sec", "10-K", "0000320193-25-000079", "https://www.sec.gov/x", company_id=self.apple, filed_at="2025-10-31")

    def evidence(self, **extra):
        return {"document_id": self.doc, "quote": "TSMC manufactures substantially all of our chips.", "tier": 2, "extractor": "reader", **extra}

    def relationship(self, **extra):
        return graph.add_relationship(self.conn, self.tsmc, self.apple, self.evidence(), customer_supply_share=100, customer_share_scope="chips", **extra)

    def count(self, table, where="1"):
        return self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


class MigrationTests(GraphCase):
    def test_creates_every_table_and_records_the_version(self):
        names = {r[0] for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue(TABLES <= names)
        self.assertEqual(db.version(self.conn), len(MIGRATIONS))

    def test_running_again_changes_nothing(self):
        self.assertEqual(db.migrate(self.conn), [])
        self.assertEqual(self.count("schema_migrations"), len(MIGRATIONS))

    def test_reopening_an_existing_file_keeps_its_data(self):
        self.conn.close()
        again = db.open_graph(self.path)
        self.addCleanup(again.close)
        self.assertEqual(again.execute("SELECT COUNT(*) FROM companies").fetchone()[0], 3)

    def test_a_later_migration_is_applied_once_and_in_order(self):
        extra = [*MIGRATIONS, (2, "add a note to companies", "ALTER TABLE companies ADD COLUMN note TEXT;"),
                 (3, "and an index", "CREATE INDEX companies_country ON companies (country);")]
        self.assertEqual(db.migrate(self.conn, extra), [2, 3])
        self.assertEqual(db.migrate(self.conn, extra), [])
        self.conn.execute("UPDATE companies SET note = 'x' WHERE id = ?", (self.apple,))
        self.assertEqual(db.version(self.conn), 3)

    def test_a_failing_migration_is_undone_completely(self):
        bad = [*MIGRATIONS, (2, "half works", "CREATE TABLE half (id INTEGER);\nINSERT INTO nowhere VALUES (1);")]
        with self.assertRaises(sqlite3.OperationalError):
            db.migrate(self.conn, bad)
        self.assertIsNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name = 'half'").fetchone())
        self.assertEqual(db.version(self.conn), 1)

    def test_a_newer_database_is_refused(self):
        newer = [(1, *MIGRATIONS[0][1:]), (2, "from the future", "CREATE TABLE future (id INTEGER);")]
        db.migrate(self.conn, newer)
        with self.assertRaises(db.SchemaError):
            db.migrate(self.conn)

    def test_an_edited_migration_is_noticed(self):
        edited = [(1, MIGRATIONS[0][1], MIGRATIONS[0][2] + "\n-- edited")]
        with self.assertRaises(db.SchemaError):
            db.migrate(self.conn, edited)

    def test_foreign_keys_are_enforced(self):
        self.assertEqual(self.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO identifiers (company_id, scheme, value, created_at) VALUES (9999, 'ticker', 'X', 'now')")


class EvidenceRuleTests(GraphCase):
    def test_a_relationship_is_created_with_its_evidence_and_points_to_it(self):
        rid = self.relationship()
        rel = self.conn.execute("SELECT * FROM relationships WHERE id = ?", (rid,)).fetchone()
        ev = self.conn.execute("SELECT * FROM evidence WHERE id = ?", (rel["primary_evidence_id"],)).fetchone()
        self.assertEqual((ev["relationship_id"], ev["document_id"], ev["tier"], ev["extractor"]), (rid, self.doc, 2, "reader"))
        self.assertEqual(ev["quote"], "TSMC manufactures substantially all of our chips.")
        self.assertEqual(integrity.check(self.conn), [])

    def test_a_relationship_without_evidence_cannot_be_saved(self):
        stamp = db.now()
        with self.assertRaises(sqlite3.IntegrityError):
            with db.transaction(self.conn):
                self.conn.execute("""INSERT INTO relationships (supplier_id, customer_id, tier, first_seen, last_seen, primary_evidence_id, created_at, updated_at)
                                     VALUES (?, ?, 2, ?, ?, 0, ?, ?)""", (self.tsmc, self.apple, stamp, stamp, stamp, stamp))
        self.assertEqual(self.count("relationships"), 0)

    def test_it_cannot_point_at_another_relationships_evidence(self):
        first = self.relationship()
        other_doc = graph.add_document(self.conn, "sec", "10-K", "other", "https://www.sec.gov/y")
        second = graph.add_relationship(self.conn, self.tsmc, self.nvidia, {**self.evidence(), "document_id": other_doc, "quote": "TSMC makes our GPUs."})
        stolen = self.conn.execute("SELECT primary_evidence_id FROM relationships WHERE id = ?", (first,)).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            with db.transaction(self.conn):
                self.conn.execute("UPDATE relationships SET primary_evidence_id = ? WHERE id = ?", (stolen, second))
        self.assertEqual(integrity.check(self.conn), [])

    def test_the_evidence_it_points_to_cannot_be_deleted(self):
        rid = self.relationship()
        primary = self.conn.execute("SELECT primary_evidence_id FROM relationships WHERE id = ?", (rid,)).fetchone()[0]
        with self.assertRaises(sqlite3.IntegrityError):
            with db.transaction(self.conn):
                self.conn.execute("DELETE FROM evidence WHERE id = ?", (primary,))
        self.assertEqual(self.count("evidence"), 1)

    def test_other_evidence_can_come_and_go_and_the_primary_can_move_to_better_evidence(self):
        rid = self.relationship()
        better_doc = graph.add_document(self.conn, "sec", "10-K", "newer", "https://www.sec.gov/z", filed_at="2026-10-30")
        second = graph.add_evidence(self.conn, rid, {"document_id": better_doc, "quote": "Customer A is 100% TSMC.", "tier": 1, "extractor": "xbrl"})
        with db.transaction(self.conn):
            self.conn.execute("UPDATE relationships SET primary_evidence_id = ? WHERE id = ?", (second, rid))
        first = self.conn.execute("SELECT id FROM evidence WHERE relationship_id = ? AND id <> ?", (rid, second)).fetchone()[0]
        with db.transaction(self.conn):
            self.conn.execute("DELETE FROM evidence WHERE id = ?", (first,))
        self.assertEqual(self.count("evidence", f"relationship_id = {rid}"), 1)
        self.assertEqual(integrity.check(self.conn), [])

    def test_deleting_a_relationship_takes_its_evidence_with_it(self):
        rid = self.relationship()
        with db.transaction(self.conn):
            self.conn.execute("DELETE FROM relationships WHERE id = ?", (rid,))
        self.assertEqual((self.count("relationships"), self.count("evidence")), (0, 0))

    def test_evidence_needs_a_document_and_words(self):
        for broken in ({"document_id": None}, {"quote": ""}, {"quote": "   "}, {"tier": None}, {"extractor": ""}):
            with self.assertRaises(ValueError):
                graph.add_relationship(self.conn, self.tsmc, self.apple, {**self.evidence(), **broken})
        with self.assertRaises(sqlite3.IntegrityError):
            graph.add_relationship(self.conn, self.tsmc, self.apple, {**self.evidence(), "document_id": 9999})
        self.assertEqual(self.count("relationships"), 0)  # nothing half written

    def test_unknown_evidence_fields_are_refused(self):
        with self.assertRaises(ValueError):
            graph.add_relationship(self.conn, self.tsmc, self.apple, {**self.evidence(), "colour": "red"})

    def test_the_integrity_check_finds_damage_done_from_outside(self):
        rid = self.relationship()
        self.conn.execute("PRAGMA foreign_keys = OFF")
        self.conn.execute("DELETE FROM evidence")
        problems = integrity.check(self.conn)
        self.assertIn(f"relationship {rid} has no evidence", problems)
        self.assertTrue(any("missing evidence row" in p for p in problems))


class ShareTests(GraphCase):
    def test_both_dependencies_are_stored_and_both_are_optional(self):
        # a filing gives the customer's side only: "TSMC makes all of Apple's chips"
        rid = self.relationship()
        rel = self.conn.execute("SELECT * FROM relationships WHERE id = ?", (rid,)).fetchone()
        self.assertEqual((rel["customer_supply_share"], rel["customer_share_scope"], rel["supplier_revenue_share"]), (100, "chips", None))
        # another gives the supplier's side only: "Customer A is 23% of our revenue"
        other = graph.add_relationship(self.conn, self.nvidia, self.apple, self.evidence(quote="Customer A 23%"), supplier_revenue_share=23)
        rel = self.conn.execute("SELECT * FROM relationships WHERE id = ?", (other,)).fetchone()
        self.assertEqual((rel["supplier_revenue_share"], rel["customer_supply_share"]), (23, None))
        # a third gives both, or neither
        both = graph.add_relationship(self.conn, self.apple, self.nvidia, self.evidence(quote="both"), supplier_revenue_share=4.5, customer_supply_share=60)
        neither = graph.add_relationship(self.conn, self.nvidia, self.tsmc, self.evidence(quote="none"))
        self.assertEqual(self.count("relationships", "supplier_revenue_share IS NULL AND customer_supply_share IS NULL"), 1)
        self.assertEqual((both, neither > 0), (3, True))

    def test_each_piece_of_evidence_keeps_the_shares_it_stated(self):
        rid = self.relationship()
        doc2 = graph.add_document(self.conn, "sec", "10-K", "later", "https://www.sec.gov/l")
        graph.add_evidence(self.conn, rid, {"document_id": doc2, "quote": "TSMC makes 90% of our chips.", "tier": 2, "extractor": "reader",
                                           "customer_supply_share": 90, "customer_share_scope": "chips", "stated_on": "2026-09-27"})
        shares = [r[0] for r in self.conn.execute("SELECT customer_supply_share FROM evidence WHERE relationship_id = ? ORDER BY id", (rid,))]
        self.assertEqual(shares, [None, 90])

    def test_percentages_stay_between_0_and_100(self):
        for column in ("supplier_revenue_share", "customer_supply_share"):
            for bad in (-1, 100.5, 250):
                with self.assertRaises(sqlite3.IntegrityError, msg=f"{column} {bad}"):
                    graph.add_relationship(self.conn, self.tsmc, self.nvidia, self.evidence(quote=f"{column}{bad}"), **{column: bad})
        self.assertEqual(self.count("relationships"), 0)
        with self.assertRaises(sqlite3.IntegrityError):
            graph.add_relationship(self.conn, self.tsmc, self.nvidia, {**self.evidence(), "customer_supply_share": 101})
        graph.add_relationship(self.conn, self.tsmc, self.nvidia, self.evidence(quote="edges"), supplier_revenue_share=0, customer_supply_share=100)


class RelationshipTests(GraphCase):
    def test_a_company_cannot_supply_itself(self):
        with self.assertRaises(sqlite3.IntegrityError):
            graph.add_relationship(self.conn, self.apple, self.apple, self.evidence())

    def test_the_same_link_is_one_relationship_with_more_evidence(self):
        first = self.relationship()
        doc2 = graph.add_document(self.conn, "sec", "10-K", "later", "https://www.sec.gov/l")
        second = graph.add_relationship(self.conn, self.tsmc, self.apple, {"document_id": doc2, "quote": "Our chips come from TSMC.", "tier": 1, "extractor": "xbrl"})
        self.assertEqual(first, second)
        self.assertEqual(self.count("evidence", f"relationship_id = {first}"), 2)
        tier = self.conn.execute("SELECT tier FROM relationships WHERE id = ?", (first,)).fetchone()[0]
        self.assertEqual(tier, 1)  # the best evidence's tier
        self.assertEqual(integrity.check(self.conn), [])

    def test_the_same_quote_from_the_same_document_is_stored_once(self):
        rid = self.relationship()
        self.assertEqual(graph.add_evidence(self.conn, rid, self.evidence(quote="  TSMC manufactures   substantially ALL of our chips. ")),
                         self.conn.execute("SELECT primary_evidence_id FROM relationships WHERE id = ?", (rid,)).fetchone()[0])
        self.assertEqual(self.count("evidence"), 1)

    def test_direction_matters(self):
        a = self.relationship()
        b = graph.add_relationship(self.conn, self.apple, self.tsmc, self.evidence(quote="the other way"))
        self.assertNotEqual(a, b)

    def test_statuses_and_tiers_are_limited(self):
        rid = self.relationship()
        for sql in ("UPDATE relationships SET status = 'maybe'", "UPDATE relationships SET tier = 4", "UPDATE relationships SET confidence = 1.5",
                    "UPDATE evidence SET tier = 0", "UPDATE evidence SET verification = 'sort of'"):
            with self.assertRaises(sqlite3.IntegrityError, msg=sql):
                self.conn.execute(sql)
        self.conn.execute("UPDATE relationships SET status = 'ended', ended_at = ? WHERE id = ?", (db.now(), rid))  # ended links stay

    def test_unknown_kinds_are_refused(self):
        with self.assertRaises(ValueError):
            graph.add_relationship(self.conn, self.tsmc, self.apple, self.evidence(), kind="rumour")


class CompanyAndDocumentTests(GraphCase):
    def test_identifiers_are_unique_per_market_and_idempotent(self):
        first = graph.add_identifier(self.conn, self.apple, "ticker", "AAPL", market="US", source="seed")
        self.assertEqual(graph.add_identifier(self.conn, self.apple, "ticker", "AAPL", market="US"), first)
        self.assertEqual(graph.find_company(self.conn, "ticker", "AAPL", "US"), self.apple)
        with self.assertRaises(graph.IdentifierConflict):
            graph.add_identifier(self.conn, self.nvidia, "ticker", "AAPL", market="US")
        graph.add_identifier(self.conn, self.nvidia, "ticker", "AAPL", market="XETRA")  # the same symbol on another market is another company
        graph.add_identifier(self.conn, self.apple, "isin", "US0378331005")
        self.assertIsNone(graph.find_company(self.conn, "ticker", "NOPE", "US"))
        with self.assertRaises(ValueError):
            graph.add_identifier(self.conn, self.apple, "passport", "X")

    def test_identifiers_go_with_the_company(self):
        graph.add_identifier(self.conn, self.nvidia, "cik", "0001045810")
        with db.transaction(self.conn):
            self.conn.execute("DELETE FROM companies WHERE id = ?", (self.nvidia,))
        self.assertEqual(self.count("identifiers"), 0)

    def test_a_placeholder_says_whose_filing_named_it(self):
        customer_a = graph.add_company(self.conn, "Customer A", placeholder_for=self.nvidia)
        row = self.conn.execute("SELECT is_placeholder, placeholder_for FROM companies WHERE id = ?", (customer_a,)).fetchone()
        self.assertEqual((row[0], row[1]), (1, self.nvidia))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE companies SET placeholder_for = NULL WHERE id = ?", (customer_a,))
        graph.add_relationship(self.conn, self.nvidia, customer_a, self.evidence(quote="Customer A accounted for 23%"), supplier_revenue_share=23)

    def test_documents_are_unique_by_source_and_id(self):
        again = graph.add_document(self.conn, "sec", "10-K", "0000320193-25-000079", "https://elsewhere")
        self.assertEqual(again, self.doc)
        self.assertEqual(self.count("documents"), 1)
        other = graph.add_document(self.conn, "mops", "annual_report", "0000320193-25-000079", "https://mops.twse.com.tw/x")
        self.assertNotEqual(other, self.doc)
        with self.assertRaises(ValueError):
            graph.add_document(self.conn, "sec", "10-K", "new", "u", colour="red")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE documents SET status = 'lost' WHERE id = ?", (self.doc,))

    def test_themes(self):
        theme = graph.add_theme(self.conn, "ai-hardware", "AI hardware")
        self.assertEqual(graph.add_theme(self.conn, "ai-hardware", "AI hardware"), theme)
        graph.add_to_theme(self.conn, theme, self.nvidia, "GPUs")
        graph.add_to_theme(self.conn, theme, self.nvidia)  # again: kept, segment unchanged
        self.assertEqual(self.conn.execute("SELECT segment FROM theme_companies").fetchone()[0], "GPUs")
        self.assertEqual(self.count("theme_companies"), 1)


class RejectedTests(GraphCase):
    def test_a_refusal_points_at_its_document_and_quote_and_is_stored_once(self):
        first = graph.reject(self.conn, self.doc, "We compete with Samsung.", "not_a_supply_relationship", "verifier",
                             supplier_name="Samsung", customer_name="Apple", detail="a competitor, not a supplier", payload={"confidence": 0.4})
        again = graph.reject(self.conn, self.doc, "we compete  with samsung.", "not_a_supply_relationship", "verifier", supplier_name="samsung", customer_name="apple")
        self.assertEqual(first, again)
        row = self.conn.execute("SELECT * FROM rejected WHERE id = ?", (first,)).fetchone()
        self.assertEqual((row["document_id"], row["reason"], row["rejected_by"]), (self.doc, "not_a_supply_relationship", "verifier"))
        other = graph.reject(self.conn, self.doc, "We compete with Samsung.", "wrong_direction", "verifier", supplier_name="Apple", customer_name="Samsung")
        self.assertNotEqual(first, other)  # the other way round is another candidate

    def test_it_needs_a_document_a_quote_and_a_known_rejecter(self):
        with self.assertRaises(sqlite3.IntegrityError):
            graph.reject(self.conn, 9999, "q", "r", "verifier")
        with self.assertRaises(sqlite3.IntegrityError):
            graph.reject(self.conn, self.doc, "  ", "r", "verifier")
        with self.assertRaises(sqlite3.IntegrityError):
            graph.reject(self.conn, self.doc, "q", "r", "a guess")


class JobAndRunTests(GraphCase):
    def job(self, kind="download", key="acc-1", status="queued", **extra):
        stamp = db.now()
        return self.conn.execute("INSERT INTO jobs (kind, key, status, run_after, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                                 (kind, key, status, stamp, stamp, stamp)).lastrowid

    def test_only_one_open_job_per_kind_and_key(self):
        job = self.job()
        with self.assertRaises(sqlite3.IntegrityError):
            self.job()
        self.job(kind="resolve")  # another kind: fine
        self.conn.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (job,))
        self.job()  # once finished, the same work can be queued again
        self.job(status="failed")
        self.job(status="failed")  # failed jobs don't block either

    def test_defaults_and_limits(self):
        job = self.job()
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job,)).fetchone()
        self.assertEqual((row["priority"], row["attempts"], row["max_attempts"], row["payload"]), (100, 0, 3, "{}"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE jobs SET status = 'sleeping' WHERE id = ?", (job,))

    def test_runs_belong_to_a_job_and_carry_the_cost(self):
        job = self.job()
        run = self.conn.execute("INSERT INTO runs (job_id, started_at, worker) VALUES (?, ?, 'w1')", (job, db.now())).lastrowid
        self.conn.execute("UPDATE runs SET outcome = 'ok', model = 'claude-haiku-5-5', input_tokens = 30000, output_tokens = 900, cost_usd = 0.0034, finished_at = ? WHERE id = ?",
                          (db.now(), run))
        self.assertEqual(self.conn.execute("SELECT ROUND(SUM(cost_usd), 4) FROM runs").fetchone()[0], 0.0034)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO runs (job_id, started_at) VALUES (9999, ?)", (db.now(),))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE runs SET outcome = 'fine' WHERE id = ?", (run,))

    def test_evidence_can_name_the_run_that_found_it(self):
        job = self.job(kind="read")
        run = self.conn.execute("INSERT INTO runs (job_id, started_at) VALUES (?, ?)", (job, db.now())).lastrowid
        rid = graph.add_relationship(self.conn, self.tsmc, self.apple, self.evidence(run_id=run))
        self.assertEqual(self.conn.execute("SELECT run_id FROM evidence WHERE relationship_id = ?", (rid,)).fetchone()[0], run)


class UseCaseTests(GraphCase):
    def test_what_depends_on_one_supplier(self):
        """The investor's question: which of my companies depend heavily on a single supplier."""
        graph.add_relationship(self.conn, self.tsmc, self.apple, self.evidence(), customer_supply_share=100, customer_share_scope="chips")
        graph.add_relationship(self.conn, self.nvidia, self.apple, self.evidence(quote="some GPUs"), customer_supply_share=15, customer_share_scope="chips")
        rows = self.conn.execute("""SELECT s.name, r.customer_supply_share FROM relationships r JOIN companies s ON s.id = r.supplier_id
                                    WHERE r.customer_id = ? AND r.customer_supply_share >= 50 AND r.status = 'active'""", (self.apple,)).fetchall()
        self.assertEqual([(r[0], r[1]) for r in rows], [("Taiwan Semiconductor Manufacturing", 100)])

    def test_a_chain_of_three_layers_is_one_query(self):
        """What Milestone 12's graph API will do: suppliers up to three layers, from one company."""
        asml = graph.add_company(self.conn, "ASML")
        zeiss = graph.add_company(self.conn, "Zeiss")
        for supplier, customer, quote in ((self.tsmc, self.apple, "a"), (asml, self.tsmc, "b"), (zeiss, asml, "c")):
            graph.add_relationship(self.conn, supplier, customer, self.evidence(quote=quote))
        rows = self.conn.execute("""WITH RECURSIVE chain (company_id, depth) AS (
                                        SELECT ?, 0 UNION ALL
                                        SELECT r.supplier_id, c.depth + 1 FROM chain c JOIN relationships r ON r.customer_id = c.company_id
                                        WHERE c.depth < 3)
                                    SELECT co.name, MIN(depth) FROM chain JOIN companies co ON co.id = chain.company_id GROUP BY co.name ORDER BY 2""", (self.apple,)).fetchall()
        self.assertEqual([(r[0], r[1]) for r in rows], [("Apple Inc.", 0), ("Taiwan Semiconductor Manufacturing", 1), ("ASML", 2), ("Zeiss", 3)])
        plan = " ".join(r[3] for r in self.conn.execute("EXPLAIN QUERY PLAN SELECT supplier_id FROM relationships WHERE customer_id = 1"))
        self.assertIn("relationships_customer", plan)  # looked up by index, not by scanning


if __name__ == "__main__":
    unittest.main()
