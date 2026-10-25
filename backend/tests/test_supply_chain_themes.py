import tempfile
import unittest
from pathlib import Path

from supply_chain import themes
from supply_chain.db import open_graph

SEGMENTS = {"chips", "foundry", "equipment", "memory", "networking", "servers", "power and cooling", "data centres"}


class Seed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = open_graph(Path(self.tmp.name) / "g.sqlite")
        self.seed = themes.load_seed()
        self.hardware = next(t for t in self.seed if t["slug"] == "ai-hardware")

    def test_seed_file_is_valid_and_about_fifty(self):
        self.assertEqual(themes.validate(self.seed), [])
        self.assertTrue(45 <= len(self.hardware["companies"]) <= 65)

    def test_covers_every_requested_category(self):
        self.assertTrue(SEGMENTS <= {c["segment"] for c in self.hardware["companies"]})

    def test_known_names_present(self):
        tickers = {c["ticker"] for c in self.hardware["companies"]}
        self.assertTrue({"NVDA", "TSM", "ASML", "MU", "ANET", "VRT", "EQIX"} <= tickers)

    def test_every_company_has_a_country(self):
        self.assertTrue(all(c.get("country") for c in self.hardware["companies"]))

    def test_seeding_twice_adds_nothing_new(self):
        first = themes.seed_themes(self.conn)
        second = themes.seed_themes(self.conn)
        total = len(self.hardware["companies"])
        self.assertEqual(first["ai-hardware"], {"added": total, "already": 0})
        self.assertEqual(second["ai-hardware"], {"added": 0, "already": total})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0], total)
        self.assertEqual(len(themes.members(self.conn, "ai-hardware")), total)

    def test_members_carry_ticker_market_segment(self):
        themes.seed_themes(self.conn)
        tsm = next(m for m in themes.members(self.conn, "ai-hardware") if m["ticker"] == "TSM")
        self.assertEqual((tsm["segment"], tsm["market"]), ("foundry", "US"))

    def test_existing_company_is_reused_and_segment_updated(self):
        small = [{"slug": "t", "name": "T", "companies": [{"name": "X Inc", "ticker": "X", "market": "US", "segment": "a"}]}]
        themes.seed_themes(self.conn, small)
        small[0]["companies"][0]["segment"] = "b"
        self.assertEqual(themes.seed_themes(self.conn, small)["t"], {"added": 0, "already": 1})
        self.assertEqual(themes.members(self.conn, "t")[0]["segment"], "b")

    def test_validate_catches_mistakes(self):
        bad = [{"slug": "t", "name": "T", "companies": [
            {"name": "", "ticker": "A", "market": "US"},
            {"name": "B", "ticker": "B", "market": "US"}, {"name": "B2", "ticker": "B", "market": "US"}]}]
        self.assertEqual(len(themes.validate(bad)), 2)
        with self.assertRaises(ValueError):
            themes.seed_themes(self.conn, bad)

    def test_same_ticker_in_another_market_is_another_company(self):
        two = [{"slug": "t", "name": "T", "companies": [
            {"name": "A US", "ticker": "A", "market": "US"}, {"name": "A AU", "ticker": "A", "market": "AU"}]}]
        self.assertEqual(themes.seed_themes(self.conn, two)["t"]["added"], 2)


if __name__ == "__main__":
    unittest.main()
