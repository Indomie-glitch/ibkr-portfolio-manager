import asyncio
import tempfile
import unittest
from datetime import date
from pathlib import Path

from supply_chain import db, graph, integrity, merge, resolver, status, xbrl
from supply_chain.db import now, open_graph

TODAY = date(2026, 10, 27)


class MergeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "g.sqlite"
        self.conn = open_graph(self.path)
        self.addCleanup(self.conn.close)
        self.acme = graph.add_company(self.conn, "Acme Semiconductor Inc.")
        self.beta = graph.add_company(self.conn, "Beta Corp")
        self.delta = graph.add_company(self.conn, "Delta Systems")
        self.gamma = graph.add_company(self.conn, "Gamma Foundry Ltd.")
        self.documents = 0

    def document(self, period_end="2025-12-31", source="sec", url="https://www.sec.gov/x", filed_at=None):
        self.documents += 1
        return graph.add_document(self.conn, source, "10-K", f"doc{self.documents}", url, company_id=self.acme, period_end=period_end,
                                  filed_at=filed_at or period_end)

    def evidence(self, quote, tier=2, document=None, **fields):
        base = {"document_id": document or self.document(), "quote": quote, "tier": tier, "extractor": "xbrl" if tier == 1 else "reader"}
        if tier == 2:
            base["verification"] = "verified"
        base.update(fields)
        return base

    def link(self, supplier, customer, quote, **fields):
        kind = fields.pop("kind", "supplies")
        return graph.add_relationship(self.conn, supplier, customer, self.evidence(quote, **fields), kind=kind)

    def row(self, relationship_id):
        return dict(self.conn.execute("SELECT * FROM relationships WHERE id = ?", (relationship_id,)).fetchone())

    def placeholder(self, label="Customer A", period="2025-12-31"):
        return xbrl.placeholder(self.conn, self.acme, "Acme Semiconductor Inc.", {"label": label, "end": period}, "customer")

    def assertSound(self):
        self.assertEqual(integrity.check(self.conn), [])


class LevelTests(unittest.TestCase):
    def test_levels_come_from_one_place(self):
        self.assertEqual([merge.level(v) for v in (0.9, 0.6, 0.3, 0.0, 1.0)], ["high", "medium", "low", "low", "high"])
        self.assertEqual([merge.level(merge.CONFIDENCE[k]) for k in ("high", "medium", "low")], ["high", "medium", "low"])
        self.assertIsNone(merge.level(None))


class SameLinkTests(MergeCase):
    def test_new_evidence_joins_the_existing_link(self):
        first = self.link(self.acme, self.beta, "Sales to Beta were 12% of revenue.", supplier_revenue_share=12, stated_on="2024-12-31")
        second = self.link(self.acme, self.beta, "Sales to Beta were 14% of revenue.", supplier_revenue_share=14, stated_on="2025-12-31")
        self.assertEqual(first, second)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence WHERE relationship_id = ?", (first,)).fetchone()[0], 2)
        self.assertSound()

    def test_a_partnership_both_ways_is_one_link(self):
        ab = self.link(self.beta, self.acme, "Acme and Beta develop chips together.", kind="partnership")
        ba = self.link(self.acme, self.beta, "Beta and Acme have a joint venture.", kind="partnership")
        self.assertEqual(ab, ba)
        row = self.row(ab)
        self.assertEqual((row["supplier_id"], row["customer_id"]), (min(self.acme, self.beta), max(self.acme, self.beta)))
        self.assertSound()

    def test_supply_links_keep_their_direction(self):
        self.assertNotEqual(self.link(self.acme, self.beta, "We sell to Beta."), self.link(self.beta, self.acme, "We buy from Beta."))

    def test_partnerships_stored_the_other_way_before_are_put_right(self):
        lone = self.link(self.acme, self.gamma, "Acme and Gamma develop packaging together.", kind="partnership")
        both = self.link(self.acme, self.beta, "Acme and Beta develop chips together.", kind="partnership")
        reversed_twin = self.link(self.acme, self.delta, "Acme and Delta license designs to each other.", kind="partnership")
        # as an older version would have stored them: B-A, and a pair stored both ways
        self.conn.execute("UPDATE relationships SET supplier_id = ?, customer_id = ? WHERE id = ?", (self.gamma, self.acme, lone))
        self.conn.execute("UPDATE relationships SET supplier_id = ?, customer_id = ? WHERE id = ?", (self.delta, self.acme, reversed_twin))
        self.conn.execute("UPDATE relationships SET supplier_id = ?, customer_id = ? WHERE id = ?", (self.beta, self.acme, both))
        twin = graph.add_relationship(self.conn, self.acme, self.beta, self.evidence("Beta and Acme have a joint venture."), kind="partnership")
        self.assertTrue(any("lower company id first" in p for p in integrity.check(self.conn)))
        result = merge.recompute_all(self.conn, TODAY)
        self.assertEqual(result["partnerships"], 3)
        self.assertEqual((self.row(lone)["supplier_id"], self.row(lone)["customer_id"]), (self.acme, self.gamma))
        self.assertEqual(self.row(both)["merged_into"], twin)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence WHERE relationship_id = ? AND copied_from IS NOT NULL", (twin,)).fetchone()[0], 1)
        self.assertSound()


class ShareTests(MergeCase):
    def test_the_newest_statement_wins(self):
        rid = self.link(self.acme, self.beta, "Beta was 14% of revenue.", supplier_revenue_share=14, stated_on="2025-12-31")
        self.link(self.acme, self.beta, "Beta was 12% of revenue.", supplier_revenue_share=12, stated_on="2024-12-31")  # older, read later
        row = self.row(rid)
        self.assertEqual((row["supplier_revenue_share"], row["shares_as_of"]), (14, "2025-12-31"))

    def test_tier_1_beats_tier_2_for_the_same_period(self):
        rid = self.link(self.acme, self.beta, "Beta: 23.4% of revenue [XBRL]", tier=1, supplier_revenue_share=23.4, stated_on="2025-12-31")
        self.link(self.acme, self.beta, "Beta accounted for 23% of revenue.", supplier_revenue_share=23, stated_on="2025-12-31")  # written later
        self.assertEqual(self.row(rid)["supplier_revenue_share"], 23.4)

    def test_a_newer_tier_2_figure_beats_an_older_tier_1(self):
        rid = self.link(self.acme, self.beta, "Beta: 20% [XBRL]", tier=1, supplier_revenue_share=20, stated_on="2024-12-31")
        self.link(self.acme, self.beta, "Beta was 25% of revenue.", supplier_revenue_share=25, stated_on="2025-12-31")
        self.assertEqual(self.row(rid)["supplier_revenue_share"], 25)

    def test_each_share_on_its_own(self):
        rid = self.link(self.gamma, self.acme, "Gamma made all of our wafers.", customer_supply_share=100, customer_share_scope="wafers", stated_on="2025-12-31")
        self.link(self.gamma, self.acme, "Acme was 30% of Gamma's revenue.", supplier_revenue_share=30, stated_on="2024-12-31")
        row = self.row(rid)
        self.assertEqual((row["customer_supply_share"], row["customer_share_scope"], row["supplier_revenue_share"]), (100, "wafers", 30))


class ConfidenceTests(MergeCase):
    def confidence(self, *evidence):
        rid = graph.add_relationship(self.conn, self.acme, self.beta, evidence[0])
        for more in evidence[1:]:
            graph.add_evidence(self.conn, rid, more)
        return self.row(rid)["confidence"]

    def test_a_tier_1_source_is_high(self):
        self.assertEqual(self.confidence(self.evidence("XBRL fact", tier=1)), 0.9)

    def test_one_verified_quote_from_a_filing_is_medium(self):
        self.assertEqual(self.confidence(self.evidence("From the 10-K.")), 0.6)

    def test_verified_tier_2_from_a_second_document_is_high(self):
        self.assertEqual(self.confidence(self.evidence("FY2024 10-K.", stated_on="2024-12-31"), self.evidence("FY2025 10-K.")), 0.9)

    def test_verified_tier_2_from_two_filings_by_another_source_is_high_too(self):
        web = self.document(source="web", url="https://acme.example/suppliers")
        self.assertEqual(self.confidence(self.evidence("From the company website.", document=web), self.evidence("From the 10-K.")), 0.9)

    def test_two_quotes_from_one_document_are_still_medium(self):
        doc = self.document()
        self.assertEqual(self.confidence(self.evidence("Risk factors say so.", document=doc), self.evidence("Note 4 says so too.", document=doc)), 0.6)

    def test_the_same_filing_text_under_two_documents_counts_once(self):
        a, b = self.document(), self.document()
        self.conn.execute("UPDATE documents SET content_hash = 'same' WHERE id IN (?, ?)", (a, b))
        self.assertEqual(self.confidence(self.evidence("Once.", document=a), self.evidence("Again.", document=b)), 0.6)

    def test_an_unverified_second_document_does_not_lift_it(self):
        self.assertEqual(self.confidence(self.evidence("Checked."), self.evidence("Not checked.", verification="unchecked")), 0.6)

    def test_tier_1_beside_a_verified_quote_is_high(self):
        self.assertEqual(self.confidence(self.evidence("From the 10-K."), self.evidence("XBRL fact", tier=1)), 0.9)

    def test_unnamed_or_shareless_links_are_not_scored_down(self):
        placeholder = self.placeholder()
        rid = graph.add_relationship(self.conn, self.acme, placeholder, self.evidence("One customer was 20%.", supplier_revenue_share=20))
        shareless = self.link(self.acme, self.beta, "We sell to Beta.")
        self.assertEqual((self.row(rid)["confidence"], self.row(shareless)["confidence"]), (0.6, 0.6))

    def test_confidence_rises_when_a_second_document_arrives_later(self):
        rid = self.link(self.acme, self.beta, "FY2024.", stated_on="2024-12-31")
        self.assertEqual(self.row(rid)["confidence"], 0.6)
        self.link(self.acme, self.beta, "FY2025.")
        self.assertEqual(self.row(rid)["confidence"], 0.9)

    def test_unverified_tier_2_is_low(self):
        self.assertEqual(self.confidence(self.evidence("Not checked.", verification="unchecked")), 0.3)

    def test_one_tier_3_source_is_low(self):
        news = self.document(source="news", url="https://www.reuters.com/a")
        self.assertEqual(self.confidence(self.evidence("Reuters says.", tier=3, document=news)), 0.3)

    def test_tier_3_confirmed_by_a_second_independent_document_is_medium(self):
        one = self.document(source="news", url="https://www.reuters.com/a")
        other = self.document(source="news", url="https://www.ft.com/b")
        self.assertEqual(self.confidence(self.evidence("Reuters says.", tier=3, document=one), self.evidence("FT says.", tier=3, document=other)), 0.6)

    def test_two_articles_from_one_publisher_are_not_independent(self):
        one = self.document(source="news", url="https://www.reuters.com/a")
        other = self.document(source="news", url="https://reuters.com/b")
        self.assertEqual(self.confidence(self.evidence("Reuters says.", tier=3, document=one), self.evidence("Reuters again.", tier=3, document=other)), 0.3)

    def test_every_existing_row_is_rescored_including_old_placeholder_values(self):
        xbrl_link = self.link(self.acme, self.beta, "XBRL fact", tier=1)
        verified = self.link(self.gamma, self.acme, "We rely on Gamma.")
        news = self.document(source="news", url="https://www.reuters.com/a")
        weak = self.link(self.acme, self.delta, "Reuters says.", tier=3, document=news)
        for rid, old in ((xbrl_link, 0.9), (verified, 0.0), (weak, 0.0)):  # as XBRL and the Verifier wrote them before #127
            self.conn.execute("UPDATE relationships SET confidence = ? WHERE id = ?", (old, rid))
        self.assertEqual(sum("confidence isn't the one" in p for p in integrity.check(self.conn)), 2)
        merge.recompute_all(self.conn, TODAY)
        self.assertEqual([self.row(r)["confidence"] for r in (xbrl_link, verified, weak)], [0.9, 0.6, 0.3])
        self.assertSound()

    def test_opening_the_database_when_a_rescoring_migration_arrives_rescores_every_row(self):
        path = Path(self.tmp.name) / "old.sqlite"
        conn = db.connect(path)
        db.migrate(conn, db.MIGRATIONS[:5])
        stamp = now()
        company = [conn.execute("INSERT INTO companies (name, created_at, updated_at) VALUES (?, ?, ?)", (n, stamp, stamp)).lastrowid for n in ("A", "B")]
        doc = conn.execute("INSERT INTO documents (source, kind, external_id, url, period_end, created_at) VALUES ('sec', '10-K', 'x', 'u', '2025-12-31', ?)",
                           (stamp,)).lastrowid
        conn.execute("BEGIN")
        rid = conn.execute("""INSERT INTO relationships (supplier_id, customer_id, confidence, tier, first_seen, last_seen, primary_evidence_id, created_at, updated_at)
                              VALUES (?, ?, 0, 2, ?, ?, 0, ?, ?)""", (*company, stamp, stamp, stamp, stamp)).lastrowid
        evidence = conn.execute("""INSERT INTO evidence (relationship_id, document_id, quote, quote_hash, tier, extractor, verification, created_at)
                                   VALUES (?, ?, 'q', 'h', 2, 'reader', 'verified', ?)""", (rid, doc, stamp)).lastrowid
        conn.execute("UPDATE relationships SET primary_evidence_id = ? WHERE id = ?", (evidence, rid))
        conn.execute("COMMIT")
        conn.close()
        reopened = open_graph(path)
        self.addCleanup(reopened.close)
        row = reopened.execute("SELECT confidence, last_confirmed FROM relationships").fetchone()
        self.assertEqual((row["confidence"], row["last_confirmed"]), (0.6, "2025-12-31"))
        self.assertEqual(integrity.check(reopened), [])


class DateAndStatusTests(MergeCase):
    def test_first_seen_and_last_confirmed_are_statement_dates(self):
        rid = self.link(self.acme, self.beta, "2023", stated_on="2023-12-31")
        self.link(self.acme, self.beta, "2025", stated_on="2025-12-31")
        self.link(self.acme, self.beta, "no date of its own", document=self.document(period_end="2024-12-31"))
        row = self.row(rid)
        self.assertEqual((row["first_seen"], row["last_confirmed"]), ("2023-12-31", "2025-12-31"))

    def test_stale_after_18_months_without_new_evidence(self):
        fresh = self.link(self.acme, self.beta, "fresh", stated_on="2025-04-27")
        old = self.link(self.acme, self.delta, "old", stated_on="2025-04-26")
        merge.recompute_all(self.conn, TODAY)
        self.assertEqual((self.row(fresh)["status"], self.row(old)["status"]), ("active", "stale"))

    def test_new_evidence_revives_a_stale_link(self):
        rid = self.link(self.acme, self.beta, "old", stated_on="2023-12-31")
        merge.refresh(self.conn, rid, TODAY)
        self.assertEqual(self.row(rid)["status"], "stale")
        self.link(self.acme, self.beta, "this year", stated_on="2026-06-30")
        self.assertEqual(self.row(rid)["status"], "active")

    def test_a_newer_statement_that_it_ended_ends_it(self):
        rid = self.link(self.gamma, self.acme, "We buy wafers from Gamma.", stated_on="2025-06-30")
        self.link(self.gamma, self.acme, "Our agreement with Gamma was terminated.", stated_on="2026-03-31", states_ended=1)
        row = self.row(rid)
        self.assertEqual((row["status"], row["ended_at"]), ("ended", "2026-03-31"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0], 1)  # kept, not deleted

    def test_a_statement_dated_after_the_end_revives_it(self):
        rid = self.link(self.gamma, self.acme, "Terminated.", stated_on="2026-03-31", states_ended=1)
        self.link(self.gamma, self.acme, "Gamma supplies us again.", stated_on="2026-09-30")
        self.assertEqual((self.row(rid)["status"], self.row(rid)["ended_at"]), ("active", None))

    def test_an_older_filing_read_later_does_not_revive_it(self):
        rid = self.link(self.gamma, self.acme, "Terminated.", stated_on="2026-03-31", states_ended=1)
        self.link(self.gamma, self.acme, "We buy wafers from Gamma (the 2024 10-K, backfilled today).", stated_on="2024-12-31")
        self.assertEqual((self.row(rid)["status"], self.row(rid)["ended_at"]), ("ended", "2026-03-31"))

    def test_an_end_and_an_ongoing_statement_of_the_same_date(self):
        rid = self.link(self.gamma, self.acme, "We bought wafers from Gamma in 2025.", stated_on="2025-12-31")
        self.link(self.gamma, self.acme, "The agreement ended at the end of 2025.", stated_on="2025-12-31", states_ended=1)
        self.assertEqual(self.row(rid)["status"], "ended")


class PlaceholderTests(MergeCase):
    def setUp(self):
        super().setUp()
        self.customer_a = self.placeholder()
        self.placeholder_link = self.link(self.acme, self.customer_a, "Customer A: 23.4% of revenue [XBRL]", tier=1,
                                          supplier_revenue_share=23.4, stated_on="2025-12-31")

    def named(self, company, share, stated_on="2025-12-31", **fields):
        return self.link(self.acme, company, f"{share}% of revenue came from this customer.", supplier_revenue_share=share,
                         stated_on=stated_on, **fields)

    def test_23_matches_23_point_4_and_the_placeholder_is_upgraded(self):
        beta_link = self.named(self.beta, 23)
        result = merge.recompute_all(self.conn, TODAY)
        self.assertEqual(result["upgraded"], 1)
        self.assertEqual(self.row(self.placeholder_link)["merged_into"], beta_link)
        self.assertEqual(self.conn.execute("SELECT merged_into FROM companies WHERE id = ?", (self.customer_a,)).fetchone()[0], self.beta)
        copies = self.conn.execute("SELECT quote FROM evidence WHERE relationship_id = ? AND copied_from IS NOT NULL", (beta_link,)).fetchall()
        self.assertEqual([r[0] for r in copies], ["Customer A: 23.4% of revenue [XBRL]"])
        row = self.row(beta_link)
        self.assertEqual((row["supplier_revenue_share"], row["tier"], row["confidence"]), (23.4, 1, 0.9))  # tier 1 figure, same period
        decision = self.conn.execute("SELECT decision, detail FROM merge_decisions").fetchone()
        self.assertEqual((decision[0], decision[1]), ("merged", "supplier_revenue_share 23.4% for 2025-12-31"))
        self.assertSound()

    def test_precision_rule(self):
        self.assertTrue(merge.same_share(23, 23.4))
        self.assertTrue(merge.same_share(23, 22.5))
        self.assertFalse(merge.same_share(23, 23.6))
        self.assertFalse(merge.same_share(23.4, 23.1))
        self.assertTrue(merge.same_share(23.40, 23.4))
        self.assertTrue(merge.same_share(12.25, 12.3))

    def test_23_point_4_and_23_point_1_dont_match(self):
        self.named(self.beta, 23.1)
        self.assertEqual(merge.upgrade_candidates(self.conn), [])

    def test_two_customers_that_both_round_to_23_means_no_merge(self):
        # placeholder 23 (from text), Beta 23.4 and Delta 22.8: both are "23" at the placeholder's precision
        self.conn.execute("UPDATE evidence SET supplier_revenue_share = 23 WHERE relationship_id = ?", (self.placeholder_link,))
        self.named(self.beta, 23.4)
        self.named(self.delta, 22.8)
        self.assertEqual(merge.upgrade_candidates(self.conn), [])
        self.assertEqual(merge.recompute_all(self.conn, TODAY)["upgraded"], 0)

    def test_two_placeholders_matching_one_customer_means_no_merge(self):
        customer_b = self.placeholder("Customer B")
        self.link(self.acme, customer_b, "Customer B: 23.1% of revenue [XBRL]", tier=1, supplier_revenue_share=23.1, stated_on="2025-12-31")
        self.named(self.beta, 23)
        self.assertEqual(merge.upgrade_candidates(self.conn), [])

    def test_a_different_period_means_no_merge(self):
        self.named(self.beta, 23, stated_on="2024-12-31")
        self.assertEqual(merge.upgrade_candidates(self.conn), [])

    def test_another_filers_customer_means_no_merge(self):
        self.link(self.gamma, self.beta, "23% of Gamma's revenue came from Beta.", supplier_revenue_share=23, stated_on="2025-12-31")
        self.assertEqual(merge.upgrade_candidates(self.conn), [])

    def test_unverified_or_dropped_figures_are_not_trusted(self):
        self.named(self.beta, 23, verification="unchecked")
        self.assertEqual(merge.upgrade_candidates(self.conn), [])
        # a share the Reader dropped is no figure: the link is there, the number isn't
        self.link(self.acme, self.delta, "Delta was a large customer.", stated_on="2025-12-31",
                  share_note="dropped by the Reader: supplier_revenue_share: digits_not_in_quote")
        self.assertEqual(merge.upgrade_candidates(self.conn), [])

    def test_undo_reverses_an_upgrade_and_it_is_not_redone(self):
        beta_link = self.named(self.beta, 23)
        merge.recompute_all(self.conn, TODAY)
        self.assertEqual(merge.undo(self.conn, self.placeholder_link), beta_link)
        self.assertIsNone(self.row(self.placeholder_link)["merged_into"])
        self.assertIsNone(self.conn.execute("SELECT merged_into FROM companies WHERE id = ?", (self.customer_a,)).fetchone()[0])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence WHERE relationship_id = ? AND copied_from IS NOT NULL", (beta_link,)).fetchone()[0], 0)
        self.assertEqual(self.row(beta_link)["supplier_revenue_share"], 23)  # back to its own figure
        self.assertEqual([r[0] for r in self.conn.execute("SELECT decision FROM merge_decisions ORDER BY id")], ["merged", "undone"])
        self.assertEqual(merge.recompute_all(self.conn, TODAY)["upgraded"], 0)
        self.assertSound()
        with self.assertRaises(ValueError):
            merge.undo(self.conn, beta_link)

    def test_a_later_document_attaches_to_the_named_company_not_the_retired_placeholder(self):
        beta_link = self.named(self.beta, 23)
        merge.recompute_all(self.conn, TODAY)
        # xbrl.py looking up the same "Customer A" of the same year gets Beta
        self.assertEqual(self.placeholder(), self.beta)
        # writing to the old placeholder id lands on the named link
        self.assertEqual(self.link(self.acme, self.customer_a, "Customer A: 23.4% again [XBRL]", tier=1), beta_link)
        # identifiers and the resolver's saved decisions follow merged_into
        self.conn.execute("INSERT INTO identifiers (company_id, scheme, value, market, created_at) VALUES (?, 'ticker', 'CUSTA', 'US', ?)", (self.customer_a, now()))
        self.assertEqual(graph.find_company(self.conn, "ticker", "CUSTA", "US"), self.beta)
        self.conn.execute("""INSERT INTO name_resolutions (name_key, name, status, company_id, method, created_at, updated_at)
                             VALUES ('custa', 'CustA', 'matched', ?, 'identifier_store', ?, ?)""", (self.customer_a, now(), now()))
        found = asyncio.run(resolver.resolve(self.conn, "CustA", index_companies=[], search=None))
        self.assertEqual(found["company_id"], self.beta)
        graph.add_identifier(self.conn, self.customer_a, "name", "custb")
        self.assertEqual(resolver.store_candidates(self.conn, "custb"), [self.beta])

    def test_merged_links_are_left_out_of_counts_and_the_log(self):
        self.named(self.beta, 23)
        merge.recompute_all(self.conn, TODAY)
        lines = [e["text"] for e in status.log_events(self.conn, kind="links")]
        self.assertEqual(len(lines), 1)
        self.assertNotIn("Customer A", lines[0])
        self.assertEqual(status.overview(self.conn)["links"]["total"], 1)


class JobTests(MergeCase):
    def test_once_a_day(self):
        self.assertTrue(merge.schedule(self.conn, TODAY))
        self.assertFalse(merge.schedule(self.conn, TODAY))
        self.assertTrue(merge.schedule(self.conn, date(2026, 10, 28)))
        self.assertEqual(self.conn.execute("SELECT priority FROM jobs WHERE kind = 'merge' LIMIT 1").fetchone()[0], 20)

    def test_the_job_recomputes_everything(self):
        rid = self.link(self.acme, self.beta, "old", stated_on="2020-12-31")
        self.conn.execute("UPDATE relationships SET status = 'active' WHERE id = ?", (rid,))
        result = asyncio.run(merge.merge_job({"key": TODAY.isoformat()}, self.conn))
        self.assertIn("1 links, 1 updated, 0 placeholders upgraded", result["notes"])
        self.assertEqual(self.row(rid)["status"], "stale")


if __name__ == "__main__":
    unittest.main()


class JoinPlaceholderTests(MergeCase):
    """Placeholders that are the same unnamed counterparty (#335)."""

    def unnamed(self, label, share=22, tier=2, filer=None, side="customer", period="2025-12-31", **fields):
        filer = filer or self.acme
        company = xbrl.placeholder(self.conn, filer, "Filer", {"label": label, "end": period}, side)
        quote = fields.pop("quote", f"{label} was {share}% [{tier}]")
        supplier, customer = (filer, company) if side == "customer" else (company, filer)
        return graph.add_relationship(self.conn, supplier, customer, self.evidence(quote, tier=tier, supplier_revenue_share=share if side == "customer" else None,
                                                                                   customer_supply_share=share if side == "supplier" else None,
                                                                                   stated_on=period, **fields)), company

    def joined(self):
        return merge.recompute_all(self.conn, TODAY)["joined"]

    def merged_links(self):
        return [r[0] for r in self.conn.execute("SELECT id FROM relationships WHERE merged_into IS NOT NULL ORDER BY id")]

    def test_one_customer_found_three_times_becomes_one_link(self):
        xbrl_link, xbrl_company = self.unnamed("Customer one", tier=1)
        direct, direct_company = self.unnamed("a direct customer")
        one_direct, one_direct_company = self.unnamed("one direct customer")
        self.assertEqual(self.joined(), 2)
        self.assertEqual(self.merged_links(), [direct, one_direct])
        self.assertEqual(self.row(direct)["merged_into"], xbrl_link)  # the one with tier 1 evidence is kept
        self.assertIsNone(self.row(xbrl_link)["merged_into"])
        self.assertEqual(self.conn.execute("SELECT merged_into FROM companies WHERE id = ?", (direct_company,)).fetchone()[0], xbrl_company)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence WHERE relationship_id = ?", (xbrl_link,)).fetchone()[0], 3)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence WHERE relationship_id = ? AND copied_from IS NOT NULL", (xbrl_link,)).fetchone()[0], 2)
        self.assertEqual([r[0] for r in self.conn.execute("SELECT decision FROM merge_decisions")], ["merged", "merged"])
        self.assertEqual(self.row(xbrl_link)["confidence"], 0.9)
        self.assertSound()

    def test_without_tier_1_the_oldest_link_is_kept(self):
        first, _ = self.unnamed("a direct customer")
        second, _ = self.unnamed("one direct customer")
        self.assertEqual(self.joined(), 1)
        self.assertEqual(self.row(second)["merged_into"], first)

    def test_the_precision_rule_applies(self):
        a, _ = self.unnamed("a direct customer", share=22)
        b, _ = self.unnamed("one direct customer", share=22.4)
        self.assertEqual(self.joined(), 1)
        c, _ = self.unnamed("our main customer", share=23.0)
        self.assertEqual(merge.recompute_all(self.conn, TODAY)["joined"], 0)  # 23.0 isn't 22 at the finer precision: left apart
        self.assertIsNone(self.row(c)["merged_into"])

    def test_not_a_clique_means_no_merge(self):
        self.unnamed("a direct customer", share=23)
        self.unnamed("one direct customer", share=23.4)
        self.unnamed("our main customer", share=22.6)  # 23.4 and 22.6 aren't the same share
        self.assertEqual(self.joined(), 0)

    def test_without_a_share_nothing_merges(self):
        for label in ("a direct customer", "one direct customer"):
            company = xbrl.placeholder(self.conn, self.acme, "Filer", {"label": label, "end": "2025-12-31"}, "customer")
            graph.add_relationship(self.conn, self.acme, company, self.evidence(f"{label} buys from us.", stated_on="2025-12-31"))
        self.assertEqual(self.joined(), 0)

    def test_different_shares_periods_filers_and_sides_stay_apart(self):
        self.unnamed("a direct customer", share=22)
        self.unnamed("one direct customer", share=14)
        self.unnamed("a direct customer", share=22, period="2024-12-31")
        self.unnamed("a direct customer", share=22, filer=self.gamma)
        self.unnamed("a direct supplier", share=22, side="supplier")
        self.assertEqual(self.joined(), 0)

    def test_two_different_customers_with_the_same_share_stay_apart(self):
        self.unnamed("Customer A", share=12)
        self.unnamed("Customer B", share=12)
        self.assertEqual(self.joined(), 0)
        self.assertEqual(merge.label_identifier("Customer one (unnamed customer of X, year to 2025-12-31)"), "1")
        self.assertIsNone(merge.label_identifier("a direct customer"))
        self.assertIsNone(merge.label_identifier("Customer 2 of 4 in the 10-K filed 2026-08-31 (unnamed customer of X, year to 2025-06-30)"))
        self.assertEqual(merge.label_identifier("Customer B in the 10-K filed 2026-02-27 (unnamed customer of X, year to 2024-12-31)"), "b")

    def test_a_tier_1_list_naming_both_means_two_counterparties(self):
        document = self.document()
        self.unnamed("Customer one", share=12, tier=1, document=document)
        self.unnamed("the other member", share=12, tier=1, document=document)
        self.assertEqual(self.joined(), 0)

    def test_one_quote_naming_both_means_two_counterparties(self):
        quote = "Two direct customers each accounted for 12% of revenue."
        self.unnamed("a direct customer", share=12, quote=quote)
        self.unnamed("another direct customer", share=12, quote=quote)
        self.assertEqual(self.joined(), 0)

    def test_untrusted_figures_dont_count(self):
        self.unnamed("a direct customer")
        self.unnamed("one direct customer", verification="unchecked")
        self.assertEqual(self.joined(), 0)

    def test_a_placeholder_in_two_links_is_left_alone(self):
        _, company = self.unnamed("a direct customer")
        self.unnamed("one direct customer")
        graph.add_relationship(self.conn, self.gamma, company, self.evidence("Gamma sells to it too."))
        self.assertEqual(self.joined(), 0)

    def test_the_scope_must_agree(self):
        self.unnamed("a direct supplier", share=95, side="supplier", customer_share_scope="chassis")
        self.unnamed("one direct supplier", share=95, side="supplier", customer_share_scope="power supplies")
        self.assertEqual(self.joined(), 0)
        self.unnamed("our supplier", share=95, side="supplier", customer_share_scope="chassis")
        self.assertEqual(self.joined(), 1)

    def test_two_placeholders_for_one_named_customer_join_first_and_then_upgrade(self):
        a, _ = self.unnamed("a direct customer")
        b, _ = self.unnamed("one direct customer")
        beta = self.link(self.acme, self.beta, "Beta Corp was 22% of revenue.", supplier_revenue_share=22, stated_on="2025-12-31")
        first = merge.recompute_all(self.conn, TODAY)
        self.assertEqual((first["upgraded"], first["joined"]), (0, 1))  # two placeholders match Beta: ambiguous, so they join instead
        second = merge.recompute_all(self.conn, TODAY)
        self.assertEqual((second["upgraded"], second["joined"]), (1, 0))  # the one left matches Beta alone
        self.assertEqual((self.row(a)["merged_into"], self.row(b)["merged_into"]), (beta, beta))  # no chain: b follows a
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence WHERE relationship_id = ?", (beta,)).fetchone()[0], 3)
        self.assertSound()
        self.assertEqual(merge.undo(self.conn, b), beta)  # undoing the joined one takes only its own evidence off Beta
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence WHERE relationship_id = ?", (beta,)).fetchone()[0], 2)
        self.assertSound()

    def test_undo_reverses_a_join_and_it_is_not_redone(self):
        keep, keep_company = self.unnamed("a direct customer")
        other, other_company = self.unnamed("one direct customer")
        self.joined()
        self.assertEqual(merge.undo(self.conn, other), keep)
        self.assertIsNone(self.row(other)["merged_into"])
        self.assertIsNone(self.conn.execute("SELECT merged_into FROM companies WHERE id = ?", (other_company,)).fetchone()[0])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence WHERE relationship_id = ? AND copied_from IS NOT NULL", (keep,)).fetchone()[0], 0)
        self.assertEqual(self.joined(), 0)
        self.assertSound()

    def test_a_later_document_attaches_to_the_kept_counterparty(self):
        keep, keep_company = self.unnamed("a direct customer")
        self.unnamed("one direct customer")
        self.joined()
        again = xbrl.placeholder(self.conn, self.acme, "Filer", {"label": "one direct customer", "end": "2025-12-31"}, "customer")
        self.assertEqual(again, keep_company)
        self.assertEqual(self.joined(), 0)  # nothing left to join
        self.assertSound()

    def test_running_it_again_changes_nothing(self):
        self.unnamed("a direct customer")
        self.unnamed("one direct customer")
        self.assertEqual(self.joined(), 1)
        self.assertEqual(self.joined(), 0)
