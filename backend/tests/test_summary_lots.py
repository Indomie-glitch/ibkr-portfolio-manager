"""Tests for the purchase lots in the AI summary's facts (section 9)."""
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PORTFOLIO_DATA_DIR", tempfile.mkdtemp())
import config  # noqa: E402
import lots  # noqa: E402
import summary_facts  # noqa: E402
from test_flex_report import REPORT  # noqa: E402


class PositionLotsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        lots.DB_PATH = Path(self.dir.name) / "lots.sqlite"
        config.SECRETS["flex_token"] = "TOKEN123456789"
        config.SETTINGS["flex_query_id"] = "987"
        asyncio.run(lots.refresh(now=datetime(2026, 10, 17, tzinfo=timezone.utc), force=True, fetch=lambda t, q: REPORT))

    def tearDown(self):
        self.dir.cleanup()

    def test_lots_with_cgt_dates_and_unknown_shares(self):
        facts = summary_facts.position_lots(lots.lots_for(4081863, 130, today=date(2026, 10, 17)))
        self.assertEqual(facts["purchase_date"], "2 lots, bought 15 Jan 2025 to 2 Mar 2026")
        self.assertEqual(facts["cgt_12_month_date"], "Next lot qualifies on 3 Mar 2027")
        self.assertEqual([(l["quantity"], l["purchase_date"], l["cgt_discount_from"], l["discount_applies_now"]) for l in facts["lots"]], [
            (60, "15 Jan 2025", "16 Jan 2026", True),
            (40, "2 Mar 2026", "3 Mar 2027", False),
        ])
        self.assertEqual(facts["shares_with_unknown_purchase_date"], 30)
        self.assertIn("IBKR's own lots", facts["cgt_note"])
        self.assertIn("as of 17 Oct 2026", facts["cgt_note"])
        self.assertIn("30 shares", facts["cgt_note"])

    def test_all_lots_qualify(self):
        facts = summary_facts.position_lots(lots.lots_for(4081863, 100, today=date(2027, 6, 1)))
        self.assertEqual(facts["cgt_12_month_date"], "All lots qualify (the last since 3 Mar 2027)")
        self.assertIsNone(facts["shares_with_unknown_purchase_date"])

    def test_without_a_report_the_date_is_unknown(self):
        facts = summary_facts.position_lots(None)
        self.assertIsNone(facts["purchase_date"])
        self.assertIn("Purchase date unknown", facts["cgt_note"])
        facts = summary_facts.position_lots(lots.lots_for(265598, 10))  # a holding not in the report
        self.assertIsNone(facts["purchase_date"])


if __name__ == "__main__":
    unittest.main()
