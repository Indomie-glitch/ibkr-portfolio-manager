"""Bankruptcy risk with the Altman Z score (#244), with numbers small enough to check by hand."""
import asyncio
import unittest
from unittest import mock

import risk
from routers import risk as risk_routes


class AltmanTests(unittest.TestCase):
    def test_score(self):
        # Total assets 100: A = 20/100, B = 30/100, C = 10/100, D = 150/50 = 3, E = 80/100
        # Z = 1.2 × 0.2 + 1.4 × 0.3 + 3.3 × 0.1 + 0.6 × 3 + 1.0 × 0.8 = 0.24 + 0.42 + 0.33 + 1.8 + 0.8 = 3.59
        score, parts = risk.altman_z(20, 30, 10, 150, 50, 80, 100)
        self.assertAlmostEqual(score, 3.59)
        self.assertEqual(parts, {"A": 0.2, "B": 0.3, "C": 0.1, "D": 3.0, "E": 0.8})

    def test_missing_input(self):
        self.assertEqual(risk.altman_z(20, None, 10, 150, 50, 80, 100), (None, {}))

    def test_zones(self):
        self.assertEqual(risk.altman_zone(3.59), "safe")
        self.assertEqual(risk.altman_zone(3.0), "grey")
        self.assertEqual(risk.altman_zone(1.8), "grey")
        self.assertEqual(risk.altman_zone(1.1), "distress")


ACCOUNTS = {"balance_date": "2026-06-30", "total_assets": 100.0, "working_capital": 20.0, "retained_earnings": 30.0,
            "total_liabilities": 50.0, "ebit": 10.0, "revenue": 80.0}


class MarketCapCurrencyTests(unittest.TestCase):
    def test_converted_to_the_accounts_currency(self):
        from datetime import date

        async def audusd(symbol, today):
            return {date(2026, 10, 16): 0.65}

        async def go(info, currency):
            with mock.patch.object(risk_routes.risk_data, "update", audusd):
                return await risk_routes.market_cap_in(info, currency, date(2026, 10, 19))
        # A$200b listed, accounts in USD: 200 × 0.65 = US$130b
        self.assertAlmostEqual(asyncio.run(go({"marketCap": 200.0, "currency": "AUD"}, "USD")), 130.0)
        self.assertAlmostEqual(asyncio.run(go({"marketCap": 130.0, "currency": "USD"}, "AUD")), 200.0)
        self.assertEqual(asyncio.run(go({"marketCap": 50.0, "currency": "AUD"}, "AUD")), 50.0)
        self.assertIsNone(asyncio.run(go({"marketCap": 50.0, "currency": "GBP"}, "USD")))


class BankruptcyRouteTests(unittest.TestCase):
    def run_route(self, holdings, accounts, failing=()):
        async def fetch_accounts(symbol):
            if symbol in failing:
                raise RuntimeError("Yahoo down")
            return accounts

        async def info(symbol):
            return {"marketCap": 150.0}

        async def go():
            with mock.patch.object(risk_routes, "risk_holdings", mock.AsyncMock(return_value=holdings)), \
                 mock.patch.object(risk_routes.yahoo, "fetch_altman_inputs", fetch_accounts), \
                 mock.patch.object(risk_routes, "yahoo_info", info), \
                 mock.patch.object(risk_routes, "cached", lambda key, ttl, fetch: fetch()):
                return await risk_routes.risk_bankruptcy()
        return asyncio.run(go())

    def holding(self, symbol, sector, yahoo=None):
        return {"symbol": symbol, "name": symbol.title(), "sector": sector, "yahoo": yahoo or symbol}

    def test_rows(self):
        result = self.run_route([self.holding("CBA", "Financial Services", "CBA.AX"), self.holding("APA", "Utilities", "APA.AX"),
                                 self.holding("AAPL", "Technology")], ACCOUNTS, failing={"APA.AX"})
        rows = {r["symbol"]: r for r in result["holdings"]}
        self.assertEqual((rows["AAPL"]["score"], rows["AAPL"]["zone"]), (3.59, "safe"))
        self.assertEqual(rows["CBA"]["zone"], "bank")  # not used for banks
        self.assertEqual(rows["APA"]["zone"], "unavailable")  # Yahoo failed for it alone
        self.assertEqual([r["symbol"] for r in result["holdings"]], ["AAPL", "CBA", "APA"])

    def test_utilities_are_marked(self):
        result = self.run_route([self.holding("APA", "Utilities", "APA.AX")], ACCOUNTS)
        self.assertTrue(result["holdings"][0]["low_by_design"])

    def test_all_failed_is_502(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            self.run_route([self.holding("AAPL", "Technology")], ACCOUNTS, failing={"AAPL"})
        self.assertEqual(caught.exception.status_code, 502)


if __name__ == "__main__":
    unittest.main()
