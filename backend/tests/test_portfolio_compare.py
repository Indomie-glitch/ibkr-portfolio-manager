"""Compare mode for portfolio summaries (#22): GET /portfolio-summary/compare and its data rows."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import HTTPException

import portfolio_facts
import summary_store
from routers import summaries
from summary_facts import MINUS


def facts(net, cash, pnl, dividends, holdings, base="AUD"):
    sheet = {"base_currency": base, "as_of_text": "now",
             "D:portfolio": {"net_liquidation": net, "holdings_value": net, "cash": cash, "unrealised_gain_or_loss": pnl,
                             "number_of_holdings": len(holdings)},
             "D:income": {"expected_yearly_total": dividends}, "D:missing": []}
    for i, symbol in enumerate(holdings):
        sheet[f"H:{i + 1}"] = {"symbol": symbol}
    return sheet


OLDER = facts("A$50,000.00", "A$4,000.00", "+A$3,000.00", "A$900.00", ["AAPL", "BHP", "CBA"])
NEWER = facts("A$52,500.00", "A$4,000.00", f"{MINUS}A$1,000.00", "A$905.00", ["AAPL", "BHP", "CBA", "TLS"])


class PortfolioCompareDataTests(unittest.TestCase):
    def rows(self, older=OLDER, newer=NEWER):
        return {r["label"]: r for r in portfolio_facts.compare_data(older, newer)}

    def test_money_changes(self):
        r = self.rows()
        self.assertEqual((r["Net liquidation"]["change"], r["Net liquidation"]["tone"]), ("+A$2,500.00", "gain"))
        self.assertEqual(r["Cash"]["change"], "No change")
        self.assertEqual((r["Unrealised P&L"]["change"], r["Unrealised P&L"]["tone"]), (f"{MINUS}A$4,000.00", "loss"))
        # +A$5 on A$900 is under 1%: shown, marked minor
        self.assertTrue(r["Expected yearly dividends"]["minor"])

    def test_holdings_count_added_and_sold(self):
        r = self.rows()
        self.assertEqual((r["Holdings"]["old"], r["Holdings"]["new"], r["Holdings"]["change"]), ("3", "4", "+1"))
        self.assertEqual(r["Holdings added"]["new"], "TLS")
        self.assertEqual(r["Holdings sold"]["new"], "None")
        self.assertEqual(self.rows(NEWER, OLDER)["Holdings sold"]["new"], "TLS")

    def test_money_isnt_compared_across_base_currencies(self):
        usd = facts("US$34,000.00", "US$2,600.00", "+US$2,000.00", "US$590.00", ["AAPL"], base="USD")
        r = self.rows(OLDER, usd)
        self.assertIsNone(r["Net liquidation"]["change"])
        self.assertEqual(r["Net liquidation"]["new"], "US$34,000.00")


class PortfolioCompareRouteTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(summary_store, "DB_PATH", Path(folder.name) / "summaries.sqlite")
        patcher.start()
        self.addCleanup(patcher.stop)
        empty = {name: {"status": "ok", "points": []} for name in summaries.portfolio_summary.SECTIONS}
        self.first = summary_store.save_portfolio("2026-10-17T09:00:00+11:00", "m", OLDER, empty, [])
        self.second = summary_store.save_portfolio("2026-10-18T09:00:00+11:00", "m", NEWER, empty, [])

    def test_older_first_whatever_the_order(self):
        result = summaries.compare_portfolio_summaries(self.second, self.first)
        self.assertEqual((result["older"]["id"], result["newer"]["id"]), (self.first, self.second))
        self.assertEqual(result["data_changes"][0]["label"], "Net liquidation")

    def test_unknown_id(self):
        with self.assertRaises(HTTPException) as caught:
            summaries.compare_portfolio_summaries(self.first, 999)
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
