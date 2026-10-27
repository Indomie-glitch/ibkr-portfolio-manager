import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from eval import supply_chain_eval as ev
from supply_chain import graph, xbrl
from supply_chain.db import open_graph

TRUTH = ev.load_truth()


class TruthFileTests(unittest.TestCase):
    def items(self):
        return [(d, r) for d in TRUTH["documents"] for r in d["relationships"]]

    def test_thirty_headline_cases_with_the_required_mix(self):
        headline = [r for _, r in self.items() if r["headline"]]
        self.assertEqual(len(headline), 30)
        cats = lambda r: set(r["categories"])
        self.assertGreaterEqual(sum("ended" in cats(r) for r in headline), 3)
        self.assertGreaterEqual(sum(r["private"] for r in headline), 3)
        self.assertTrue(any(r["supplier_revenue_share"] and "named_customer" in cats(r) for r in headline))  # a named customer with a percentage
        self.assertTrue(any("risk_factor" in cats(r) and "named_supplier" in cats(r) for r in headline))
        self.assertTrue(any("8k_agreement" in cats(r) for r in headline))
        self.assertTrue(any("unnamed_customer" in cats(r) for r in headline))
        self.assertTrue(any("unnamed_supplier" in cats(r) for r in headline))

    def test_every_entry_is_complete(self):
        ids = set()
        for doc, r in self.items() + [(d, r) for d in TRUTH["documents"] for r in d["optional"]]:
            self.assertNotIn(r["id"], ids)
            ids.add(r["id"])
            self.assertTrue(r["quote"].strip())
            self.assertGreater(r["paragraph"], 0)
            self.assertIn(r["kind"], r["accept_kinds"])
            for side in ("supplier", "customer"):
                if r[side] is not None:
                    self.assertIn(r[side], TRUTH["companies"], f"{r['id']} names {r[side]!r}, which has no aliases")
            if r["unnamed"]:
                self.assertEqual([r["supplier"], r["customer"]].count(None), 1, r["id"])
                self.assertTrue(r["supplier_revenue_share"] is not None or r["customer_supply_share"] is not None or r in doc["optional"], r["id"])
            else:
                self.assertIsNotNone(r["supplier"])
                self.assertIsNotNone(r["customer"])
            if r["ended"]:
                self.assertIn("ended", r["categories"])
        for doc in TRUTH["documents"]:
            for trap in doc["not_relationships"]:
                self.assertTrue(trap["quote"].strip() and trap["why"])

    def test_the_documents_are_real_filings(self):
        for doc in TRUTH["documents"]:
            self.assertRegex(doc["accession"], r"^\d{10}-\d{2}-\d{6}$")
            self.assertIn(doc["form"], ("10-K", "20-F", "8-K"))
            self.assertTrue(ev.filing_path(doc).name.endswith(".htm"))


def tiny_truth():
    companies = {
        "Acme": {"aliases": ["Acme Inc."], "private": False},
        "Beta": {"aliases": ["Beta Corporation", "Beta Corp"], "private": False},
        "Gamma": {"aliases": ["Gamma Foundry Ltd."], "private": False},
        "Delta": {"aliases": ["Delta Systems"], "private": True},
        "Omega": {"aliases": ["Omega"], "private": False},
    }

    def item(n, supplier, customer, **kw):
        base = {"id": f"d#{n}", "headline": False, "categories": [], "supplier": supplier, "customer": customer, "unnamed": None, "kind": "supplies",
                "accept_kinds": ["supplies"], "what": None, "supplier_revenue_share": None, "customer_supply_share": None, "customer_share_scope": None,
                "stated_on": None, "ended": False, "private": False, "paragraph": 1, "quote": f"quote {n}"}
        base.update(kw)
        return base
    relationships = [
        item(1, "Acme", "Beta", supplier_revenue_share=48, headline=True, categories=["named_customer"]),
        item(2, "Gamma", "Acme", categories=["named_supplier"]),
        item(3, "Acme", "Delta", private=True, categories=["private"]),                      # never found: Delta unresolved
        item(4, "Acme", None, unnamed="one customer", supplier_revenue_share=22, stated_on="2026-01-25", categories=["unnamed_customer"]),
        item(5, "Acme", None, unnamed="another customer", supplier_revenue_share=14, stated_on="2026-01-25", categories=["unnamed_customer"]),
        item(6, None, "Acme", unnamed="a supplier", customer_supply_share=63.1, customer_share_scope="purchases", stated_on="2026-06-30", categories=["unnamed_supplier"]),
        item(7, "Gamma", "Beta", kind="partnership", accept_kinds=["partnership"], categories=["partnership"]),
        item(8, "Omega", "Acme", ended=True, categories=["ended"]),
        item(9, "Acme", "Omega", supplier_revenue_share=10),
    ]
    optional = [item(20, "Acme", "Gamma", categories=["x"])]
    traps = [{"paragraph": 3, "quote": "OpenAI talks are not final", "why": "not agreed yet"}]
    doc = {"id": "d", "company": "Acme Inc.", "ticker": "ACME", "market": "US", "form": "10-K", "cik": 1, "accession": "0000000001-26-000001",
           "primary_document": "x.htm", "filed": "2026-02-01", "period_end": "2026-01-25", "items": [], "relationships": relationships, "optional": optional,
           "not_relationships": traps}
    return {"companies": companies, "documents": [doc]}


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = open_graph(Path(self.tmp.name) / "g.sqlite")
        self.addCleanup(self.conn.close)
        self.truth = tiny_truth()
        self.company = {n: graph.add_company(self.conn, n) for n in ("Acme Inc.", "Beta Corporation", "Gamma Foundry Ltd.", "Omega", "Stray Co")}
        self.document = graph.add_document(self.conn, "sec", "10-K", "x", "u", company_id=self.company["Acme Inc."], period_end="2026-01-25", filed_at="2026-02-01")
        self.ids = {"d": self.document}

    def link(self, supplier, customer, quote="q", kind="supplies", **evidence):
        row = {"document_id": self.document, "quote": quote, "tier": 2, "extractor": "reader", "verification": "verified"}
        row.update(evidence)
        return graph.add_relationship(self.conn, supplier, customer, row, kind=kind)

    def placeholder(self, label, year):
        return xbrl.placeholder(self.conn, self.company["Acme Inc."], "Acme Inc.", {"label": label, "end": year}, "customer")

    def scored(self):
        out = ev.collect(self.conn, self.ids)
        return out, ev.score(self.truth, out, self.ids)

    def test_named_unnamed_and_partnership_matching(self):
        c = self.company
        self.link(c["Acme Inc."], c["Beta Corporation"], supplier_revenue_share=48)
        self.link(c["Gamma Foundry Ltd."], c["Acme Inc."])
        # unnamed: "22%" is covered by 22.4 (the precision rule), the year comes from the placeholder's name
        self.link(c["Acme Inc."], self.placeholder("Customer A", "2026-01-25"), supplier_revenue_share=22.4)
        self.link(c["Acme Inc."], self.placeholder("Customer B", "2025-01-26"), supplier_revenue_share=14)  # right share, wrong year
        # a partnership is stored lower id first, so Gamma-Beta comes back in either order
        self.link(c["Beta Corporation"], c["Gamma Foundry Ltd."], kind="partnership")
        _, m = self.scored()
        self.assertEqual(m["found"], 4)
        self.assertEqual(m["found_other_year"], 1)
        self.assertEqual(m["per_item"]["d#4"]["result"], "found")
        self.assertEqual(m["per_item"]["d#5"]["result"], "found_other_year")
        self.assertEqual(m["per_item"]["d#7"]["result"], "found")
        self.assertEqual(m["per_item"]["d#1"]["level"], "high")
        self.assertEqual({i["id"] for _, i in m["_missed"]}, {"d#3", "d#6", "d#8", "d#9"})
        self.assertEqual(m["headline_found"], 1)
        self.assertAlmostEqual(m["recall"], 4 / 9, places=3)

    def test_wrong_kind_wrong_direction_and_wrong_numbers(self):
        c = self.company
        self.link(c["Beta Corporation"], c["Acme Inc."], supplier_revenue_share=48)    # the wrong way round: not Acme -> Beta
        self.link(c["Gamma Foundry Ltd."], c["Beta Corporation"], kind="supplies")      # right pair, kind not accepted (a partnership was known)
        self.link(c["Acme Inc."], c["Omega"], supplier_revenue_share=25)                # found, but 25 is not 10
        _, m = self.scored()
        self.assertEqual(m["per_item"]["d#1"]["result"], "missed")
        self.assertEqual(m["per_item"]["d#7"]["result"], "missed")
        self.assertEqual(m["per_item"]["d#9"]["result"], "found")
        self.assertEqual(m["wrong_numbers"], 1)
        self.assertEqual(m["wrong_links"], 2)
        self.assertAlmostEqual(m["precision"], 1 / 3, places=3)

    def test_extra_links_are_wrong_and_optional_ones_are_not(self):
        c = self.company
        self.link(c["Acme Inc."], c["Gamma Foundry Ltd."])        # the optional item
        self.link(c["Stray Co"], c["Acme Inc."])                  # matches nothing
        _, m = self.scored()
        self.assertEqual(m["wrong_links"], 1)
        self.assertEqual(len(m["_optional_found"]), 1)
        self.assertEqual(m["found"], 0)

    def test_ended_relationships(self):
        c = self.company
        self.link(c["Omega"], c["Acme Inc."], states_ended=1, quote="it ended")
        _, m = self.scored()
        self.assertEqual((m["ended_truth"], m["ended_found"], m["ended_marked"], m["ended_missed"]), (1, 1, 1, 0))
        self.assertEqual(m["per_item"]["d#8"]["result"], "found")
        # the same pair without an ending statement
        other = ev.score(self.truth, {"links": [], "candidates": [], "rejected": []}, self.ids)
        self.assertEqual(other["found"], 0)

    def test_a_link_made_from_a_trap_sentence(self):
        c = self.company
        self.link(c["Stray Co"], c["Acme Inc."], quote="OpenAI talks are not final")
        _, m = self.scored()
        self.assertEqual(m["trap_links"], 1)
        self.assertEqual(m["wrong_links"], 1)

    def test_a_placeholder_whose_label_holds_a_known_name_counts_as_that_company(self):
        truth = self.truth
        truth["companies"]["Delta"]["aliases"] += ["Corporate Venture"]
        self.assertTrue(ev.name_matches(truth, "Delta", "Corporate Venture (unnamed customer of Acme Inc., year to 2026-06-30)"))
        self.assertTrue(ev.name_matches(truth, "Delta", "the Corporate Venture (unnamed customer of Acme Inc., year to 2026-06-30)"))
        self.assertTrue(ev.name_matches(truth, "Beta", "an affiliate of Beta Corp (unnamed customer of Acme Inc., year to 2026-06-30)"))
        self.assertFalse(ev.name_matches(truth, "Beta", "Customer A (unnamed customer of Acme Inc., year to 2026-06-30)"))
        self.assertFalse(ev.name_matches(truth, "Beta", "Betamax (unnamed customer of Acme Inc., year to 2026-06-30)"))   # whole words only
        c = self.company
        self.link(c["Acme Inc."], self.placeholder("Delta Systems", "2026-01-25"))
        _, m = self.scored()
        self.assertEqual(m["per_item"]["d#3"]["result"], "found")   # the private company, kept under its own label

    def test_unnamed_items_without_a_share_match_by_their_quote(self):
        truth = self.truth
        doc = truth["documents"][0]
        base = doc["relationships"][3]
        receivable = dict(base, id="d#30", supplier_revenue_share=None, quote="one customer was 11% of receivables")
        doc["optional"].append(receivable)
        c = self.company
        self.link(c["Acme Inc."], self.placeholder("Customer A", "2025-12-31"), quote="one customer was 11% of receivables")
        self.link(c["Acme Inc."], self.placeholder("Customer B", "2025-12-31"), quote="something else entirely")
        _, m = self.scored()
        self.assertEqual(len(m["_optional_found"]), 1)
        self.assertEqual(m["wrong_links"], 1)

    def test_a_link_that_lost_its_number_is_found_without_it(self):
        c = self.company
        self.link(c["Acme Inc."], self.placeholder("one customer", "2026-01-25"), quote="quote 4")   # no share kept
        _, m = self.scored()
        self.assertEqual((m["found"], m["found_no_number"], m["wrong_links"]), (0, 1, 0))
        self.assertEqual(m["per_item"]["d#4"]["result"], "found_no_number")

    def test_duplicate_unnamed_counterparties(self):
        c = self.company
        self.link(c["Acme Inc."], self.placeholder("Customer A", "2026-01-25"), supplier_revenue_share=22, quote="a")
        self.link(c["Acme Inc."], self.placeholder("one direct customer", "2026-01-25"), supplier_revenue_share=22, quote="b")
        _, m = self.scored()
        self.assertEqual((m["duplicate_groups"], m["duplicate_links"]), (1, 1))
        self.assertEqual(m["found"], 1)       # one of them is the known customer
        self.assertEqual(m["wrong_links"], 1)  # the other is a duplicate

    def test_rejections_and_diagnosis(self):
        c = self.company
        graph.reject(self.conn, self.document, "quote 3", "unresolved_company", "rule", supplier_name="Acme Inc.", customer_name="Delta Systems", detail="no_match: x")
        out, m = self.scored()
        self.assertEqual(m["rejected"], {"unresolved_company (rule)": 1})
        item = self.truth["documents"][0]["relationships"][2]
        self.assertIn("rejected: unresolved_company (rule)", ev.diagnose(self.truth, self.truth["documents"][0], item, out, []))
        self.assertIn("chunker", ev.diagnose(self.truth, self.truth["documents"][0], item, out, [("d#3", "x")]))
        other = self.truth["documents"][0]["relationships"][5]
        self.assertEqual(ev.diagnose(self.truth, self.truth["documents"][0], other, out, []), "the Reader did not return it")

    def test_a_saved_run_scores_the_same_after_a_round_trip(self):
        import json
        c = self.company
        self.link(c["Acme Inc."], c["Beta Corporation"], supplier_revenue_share=48)
        out, m = self.scored()
        raw = json.loads(json.dumps({"links": out["links"], "candidates": out["candidates"], "rejected": out["rejected"]}, default=str))
        again = ev.score(self.truth, raw, self.ids)
        self.assertEqual(ev.jsonable(again), ev.jsonable(m))

    def test_categories_and_report(self):
        c = self.company
        self.link(c["Acme Inc."], c["Beta Corporation"], supplier_revenue_share=48)
        out, m = self.scored()
        self.assertEqual(m["categories"]["named_customer"], {"truth": 1, "found": 1})
        self.assertEqual(m["categories"]["private"], {"truth": 1, "found": 0})
        out["diagnosis"] = {i["id"]: "the Reader did not return it" for _, i in m["_missed"]}
        run = {"reader_effort": "low", "verifier_effort": "medium", "reader_cost": 0.05, "verifier_cost": 0.1, "reader_in": 1000, "reader_out": 100,
               "verifier_in": 500, "verifier_out": 50}
        report = ev.render(self.truth, self.ids, out, m, run, "low", datetime(2026, 10, 27, 9, 0))
        for heading in ("# Supply chain evaluation: low", "## Summary", "## Recall by kind of case", "## Missed", "## Wrong links", "## Every known relationship"):
            self.assertIn(heading, report)
        self.assertIn("US$0.150", report)
        self.assertNotIn("_missed", ev.jsonable(m))


if __name__ == "__main__":
    unittest.main()
