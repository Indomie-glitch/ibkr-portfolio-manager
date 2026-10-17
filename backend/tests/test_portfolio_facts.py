import unittest
from datetime import date, datetime, timedelta, timezone

from portfolio_facts import build_portfolio_facts, month_move, source_ids

TODAY = date(2026, 10, 17)
NOW = datetime(2026, 10, 17, 10, 30, tzinfo=timezone(timedelta(hours=11), "AEDT"))
ACCOUNT = {"currency": "AUD", "net_liquidation": 12000.0, "cash": 2000.0, "fx_rates": {"USD": 1.5}}


def position(con_id, symbol, currency, value, pnl, quantity=10, exchange="ASX"):
    return {"con_id": con_id, "symbol": symbol, "name": symbol.title(), "currency": currency, "exchange": exchange,
            "sec_type": "STK", "quantity": quantity, "market_value": value, "unrealized_pnl": pnl,
            "unrealized_pnl_pct": 10.0}


def closes(start, daily_step, days=30):
    return [(TODAY - timedelta(days=days - i), start + daily_step * i) for i in range(days)]


HOLDINGS = [
    {   # 3000 AUD
        "position": position(1, "CBA", "AUD", 3000.0, 300.0), "quote": {"day_change_pct": 2.0},
        "sector": "Financial Services", "beta": 1.0, "benchmark": "S&P/ASX 200",
        "closes": closes(100, 1), "index_closes": closes(1000, 0),
        "events": [(TODAY + timedelta(days=10), "Ex-dividend date"), (TODAY - timedelta(days=5), "Earnings result")],
        "dividends_12m": 4.0,
    },
    {   # 4000 USD = 6000 AUD
        "position": position(2, "AAPL", "USD", 4000.0, -200.0, exchange="NASDAQ"), "quote": {"day_change_pct": -1.0},
        "sector": "Technology", "beta": None, "benchmark": "S&P 500",
        "closes": None, "index_closes": None,
        "events": [(TODAY + timedelta(days=90), "Earnings result")], "dividends_12m": None,
    },
    {   # 1000 AUD
        "position": position(3, "BHP", "AUD", 1000.0, 50.0), "quote": None,
        "sector": None, "beta": None, "benchmark": "S&P/ASX 200",
        "closes": None, "index_closes": None, "events": [(TODAY + timedelta(days=3), "Earnings result")],
        "dividends_12m": 0,
    },
]


class PortfolioFactsTest(unittest.TestCase):
    def setUp(self):
        self.facts = build_portfolio_facts(ACCOUNT, HOLDINGS, NOW, missing=["BHP company data (Yahoo Finance unavailable)"])

    def test_weights_in_base_currency(self):
        allocation = self.facts["D:allocation"]
        self.assertEqual(allocation["by_holding"], {"AAPL": 60.0, "CBA": 30.0, "BHP": 10.0})
        self.assertEqual(allocation["by_market"], {"US": 60.0, "ASX": 40.0})
        self.assertEqual(allocation["by_currency"], {"USD": 60.0, "AUD": 40.0})
        self.assertEqual(allocation["by_sector"], {"Technology": 60.0, "Financial Services": 30.0, "Unknown": 10.0})
        self.assertEqual(allocation["cash_pct_of_net_liquidation"], 16.7)
        self.assertIn("6,000.00", self.facts["H:2"]["value"])  # 4000 USD × 1.5

    def test_portfolio_totals(self):
        portfolio = self.facts["D:portfolio"]
        self.assertEqual(portfolio["number_of_holdings"], 3)
        self.assertIn("10,000.00", portfolio["holdings_value"])
        # 300 + (−200 × 1.5) + 50 = +50
        self.assertIn("50.00", portfolio["unrealised_gain_or_loss"])
        self.assertTrue(portfolio["unrealised_gain_or_loss"].startswith("+"))

    def test_pnl_contributors(self):
        pnl = self.facts["D:pnl"]
        self.assertEqual([g["holding"] for g in pnl["since_purchase_biggest_gains"]], ["H:1", "H:3"])
        self.assertEqual([l["holding"] for l in pnl["since_purchase_biggest_losses"]], ["H:2"])
        self.assertIn("300.00", pnl["since_purchase_biggest_losses"][0]["amount"])
        # Today: AAPL −1% of 6000 is about −60.6; CBA +2% of 3000 is about +58.8; BHP has no quote
        self.assertEqual([m["holding"] for m in pnl["today_biggest_moves"]], ["H:2", "H:1"])

    def test_concentration_flags(self):
        concentration = self.facts["D:concentration"]
        self.assertEqual(concentration["top_3_share_pct"], 100.0)
        flags = " | ".join(concentration["flags"])
        self.assertIn("AAPL is 60.0%", flags)
        self.assertIn("CBA is 30.0%", flags)
        self.assertIn("Technology is 60.0%", flags)
        self.assertNotIn("USD", flags)  # 60% is under the 80% currency threshold
        self.assertNotIn("BHP", flags)

    def test_events_only_next_60_days_in_order(self):
        upcoming = self.facts["D:events"]["upcoming"]
        self.assertEqual([(e["holding"], e["event"]) for e in upcoming],
                         [("H:3", "Earnings result"), ("H:1", "Ex-dividend date")])
        self.assertEqual(self.facts["H:1"]["next_event"]["event"], "Ex-dividend date")
        self.assertIsNone(self.facts["H:2"]["next_event"])

    def test_income(self):
        income = self.facts["D:income"]
        self.assertIn("40.00", income["expected_yearly_total"])  # 4 per share × 10 shares
        self.assertEqual([h["holding"] for h in income["by_holding"]], ["H:1"])
        self.assertEqual(income["yield_on_holdings_value_pct"], 0.4)

    def test_market_moves_and_ids(self):
        moves = self.facts["D:market_moves"]["holdings"]
        self.assertEqual([m["holding"] for m in moves], ["H:1"])
        self.assertEqual(moves[0]["benchmark_pct"], 0.0)
        self.assertEqual(moves[0]["rest_pct"], moves[0]["stock_pct"])
        self.assertEqual(self.facts["D:missing"], ["BHP company data (Yahoo Finance unavailable)"])
        self.assertEqual(set(source_ids(self.facts)), {
            "H:1", "H:2", "H:3", "D:portfolio", "D:allocation", "D:pnl", "D:market_moves",
            "D:concentration", "D:events", "D:income", "D:since_last", "D:missing"})

    def test_missing_exchange_rate_skips_holding(self):
        facts = build_portfolio_facts({**ACCOUNT, "fx_rates": {}}, HOLDINGS, NOW)
        self.assertNotIn("H:2", facts)
        self.assertIn("AAPL: no exchange rate for USD", facts["D:missing"])
        self.assertEqual(facts["D:allocation"]["by_holding"], {"CBA": 75.0, "BHP": 25.0})

    def test_empty_portfolio(self):
        facts = build_portfolio_facts(ACCOUNT, [], NOW)
        self.assertEqual(facts["D:portfolio"]["number_of_holdings"], 0)
        self.assertEqual(facts["D:allocation"]["by_market"], {})
        self.assertIsNone(facts["D:concentration"]["top_3_share_pct"])

    def test_month_move_needs_a_month_of_closes(self):
        self.assertIsNone(month_move(closes(100, 1, days=21), closes(1000, 1, days=21), 1.0))
        move = month_move(closes(100, 1), closes(1000, 10), 1.5)
        self.assertEqual(move["beta"], 1.5)
        self.assertAlmostEqual(move["explained_by_market_pct"], round(1.5 * move["benchmark_pct"], 2), places=1)


class SinceLastTest(unittest.TestCase):
    def test_first_summary(self):
        facts = build_portfolio_facts(ACCOUNT, HOLDINGS, NOW)
        self.assertEqual(facts["D:since_last"]["note"], "This is the first portfolio summary")

    def test_changes_since_previous(self):
        # Then: CBA and BHP only, worth less; now AAPL is added and CBA's weight fell
        sold = {**HOLDINGS[2], "position": position(4, "WES", "AUD", 500.0, 0.0)}
        previous = build_portfolio_facts({**ACCOUNT, "net_liquidation": 6500.0}, [HOLDINGS[0], HOLDINGS[2], sold],
                                         NOW - timedelta(days=7))
        since = build_portfolio_facts(ACCOUNT, HOLDINGS, NOW, previous=previous)["D:since_last"]
        self.assertEqual(since["previous_summary"], "10 Oct 2026, 10:30am AEDT")
        self.assertIn("5,500.00", since["net_liquidation"]["change"])   # 12000 − 6500
        self.assertTrue(since["net_liquidation"]["change"].startswith("+"))
        self.assertEqual(since["holdings_added"], [{"holding": "H:2", "symbol": "AAPL"}])
        self.assertEqual(since["holdings_sold"], ["WES"])
        self.assertEqual(since["number_of_holdings"], {"then": 3, "now": 3})
        # CBA 3000/4500 = 66.7% -> 30.0%; BHP 1000/4500 = 22.2% -> 10.0%
        self.assertEqual([(c["holding"], c["weight_then_pct"], c["weight_now_pct"]) for c in since["weight_changes"]],
                         [("H:1", 66.7, 30.0), ("H:3", 22.2, 10.0)])
        self.assertIsNone(since["note"])

    def test_base_currency_change_skips_money(self):
        previous = build_portfolio_facts({**ACCOUNT, "currency": "USD", "fx_rates": {"AUD": 0.66}}, HOLDINGS, NOW)
        since = build_portfolio_facts(ACCOUNT, HOLDINGS, NOW, previous=previous)["D:since_last"]
        self.assertIsNone(since["net_liquidation"])
        self.assertIn("USD to AUD", since["note"])


if __name__ == "__main__":
    unittest.main()
