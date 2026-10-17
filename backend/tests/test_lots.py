"""Tests for lot storage, refresh and matching (run from backend/: python -m unittest discover tests)."""
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PORTFOLIO_DATA_DIR", tempfile.mkdtemp())  # app mode: settings from config.SETTINGS
import config  # noqa: E402
import flex_report as flex  # noqa: E402
import lots  # noqa: E402
from test_flex_report import REPORT  # noqa: E402

NOW = datetime(2026, 10, 17, 1, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 17)


class LotsTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        lots.DB_PATH = Path(self.dir.name) / "lots.sqlite"
        config.SECRETS["flex_token"] = "TOKEN123456789"
        config.SETTINGS["flex_query_id"] = "987"
        # App mode (Flex settings from SECRETS/SETTINGS), even if another test imported config first
        in_app, config.IN_APP = config.IN_APP, True
        self.addCleanup(setattr, config, "IN_APP", in_app)

    def tearDown(self):
        self.dir.cleanup()

    def refresh(self, fetch, now=NOW, force=False):
        return asyncio.run(lots.refresh(now=now, force=force, fetch=fetch))


class CgtDateTests(unittest.TestCase):
    def test_day_after_the_first_anniversary(self):
        self.assertEqual(lots.cgt_discount_date(date(2025, 1, 15)), date(2026, 1, 16))
        self.assertEqual(lots.cgt_discount_date(date(2024, 2, 29)), date(2025, 3, 1))
        self.assertEqual(lots.cgt_discount_date(date(2025, 12, 31)), date(2027, 1, 1))


class FifoTests(unittest.TestCase):
    def test_sells_the_oldest_first(self):
        trades = [
            {"quantity": 10, "price": 1, "traded": date(2026, 1, 1)},
            {"quantity": 5, "price": 2, "traded": date(2026, 2, 1)},
            {"quantity": -12, "price": 3, "traded": date(2026, 3, 1)},
        ]
        open_lots, unmatched = lots.fifo_open_lots(trades)
        self.assertEqual([(l["quantity"], l["opened"]) for l in open_lots], [(3, date(2026, 2, 1))])
        self.assertEqual(unmatched, 0)

    def test_sales_of_older_shares_are_counted(self):
        open_lots, unmatched = lots.fifo_open_lots([{"quantity": -4, "price": 1, "traded": date(2026, 3, 1)}])
        self.assertEqual((open_lots, unmatched), ([], 4))


class RefreshAndMatchTests(LotsTestCase):
    def test_uses_ibkr_lots_and_their_cgt_dates(self):
        self.assertTrue(self.refresh(lambda token, query: REPORT))
        result = lots.lots_for(4081863, 100, today=TODAY)
        self.assertEqual(result["source"], "flex_lots")
        self.assertEqual(result["report_date"], "2026-10-17")
        self.assertEqual([(l["quantity"], l["opened"], l["cgt_discount_from"], l["days_until_discount"]) for l in result["lots"]], [
            (60, "2025-01-15", "2026-01-16", 0),
            (40, "2026-03-02", "2027-03-03", 137),
        ])
        self.assertEqual(result["unknown_quantity"], 0)

    def test_shares_bought_since_the_report_are_unknown(self):
        self.refresh(lambda token, query: REPORT)
        self.assertEqual(lots.lots_for(4081863, 130, today=TODAY)["unknown_quantity"], 30)

    def test_shares_sold_since_the_report_come_off_the_oldest_lot(self):
        self.refresh(lambda token, query: REPORT)
        result = lots.lots_for(4081863, 70, today=TODAY)
        self.assertEqual([(l["quantity"], l["opened"]) for l in result["lots"]], [(30, "2025-01-15"), (40, "2026-03-02")])

    def test_falls_back_to_trades_and_marks_older_shares_unknown(self):
        self.refresh(lambda token, query: REPORT)
        result = lots.lots_for(4036812, 25, today=TODAY)  # BHP: only a 10-share buy in the report
        self.assertEqual(result["source"], "flex_trades")
        self.assertEqual([(l["quantity"], l["opened"]) for l in result["lots"]], [(10, "2026-05-20")])
        self.assertEqual(result["unknown_quantity"], 15)

    def test_no_report_yet(self):
        result = lots.lots_for(4081863, 100, today=TODAY)
        self.assertEqual((result["source"], result["lots"], result["unknown_quantity"]), (None, [], 100))

    def test_refreshes_once_a_day(self):
        calls = []
        fetch = lambda token, query: calls.append(1) or REPORT  # noqa: E731
        self.refresh(fetch)
        self.refresh(fetch, now=NOW + timedelta(hours=5))
        self.assertEqual(len(calls), 1)
        self.refresh(fetch, now=NOW + timedelta(days=1, minutes=1))
        self.assertEqual(len(calls), 2)

    def test_a_failure_is_recorded_masked_and_retried_after_an_hour(self):
        def failing(token, query):
            raise flex.FlexError(f"bad token {token}")
        self.assertFalse(self.refresh(failing))
        status = lots.status()
        self.assertIn("bad token", status["last_error"])
        self.assertNotIn("TOKEN123456789", status["last_error"])
        calls = []
        self.refresh(lambda t, q: calls.append(1) or REPORT, now=NOW + timedelta(minutes=30))
        self.assertEqual(calls, [])
        self.refresh(lambda t, q: calls.append(1) or REPORT, now=NOW + timedelta(minutes=61))
        self.assertEqual(calls, [1])
        self.assertIsNone(lots.status()["last_error"])

    def test_nothing_happens_without_flex_settings(self):
        config.SECRETS.pop("flex_token")
        self.assertFalse(self.refresh(lambda t, q: REPORT, force=True))
        self.assertFalse(lots.status()["configured"])


if __name__ == "__main__":
    unittest.main()
