"""The Risk page in the account's base currency (#271): an SGD account holding US and Australian
shares, a EUR account (no home index), and old saved portfolio summaries. Yahoo is a fake and the
price store a temp file; the numbers are small enough to check by hand."""
import asyncio
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import numpy as np
from fastapi import HTTPException

import fx
import portfolio_facts
import risk_data
import summary_store
from routers import risk as risk_routes
from routers import summaries
from summary_facts import MINUS
from tests.test_risk_data import FakeYahoo, StoreTestCase, weekdays

TODAY = date(2026, 10, 19)  # the 3M window starts on 19 Jul


class PairTests(unittest.TestCase):
    def test_pairs_are_stored_the_way_the_market_quotes_them(self):
        self.assertEqual((fx.Pair("USD", "AUD").symbol, fx.Pair("USD", "AUD").inverted), ("AUDUSD=X", True))
        self.assertEqual((fx.Pair("USD", "SGD").symbol, fx.Pair("USD", "SGD").inverted), ("USDSGD=X", False))
        self.assertEqual((fx.Pair("AUD", "SGD").symbol, fx.Pair("AUD", "SGD").inverted), ("AUDSGD=X", False))
        self.assertEqual((fx.Pair("USD", "EUR").symbol, fx.Pair("USD", "EUR").inverted), ("EURUSD=X", True))
        self.assertEqual(fx.Pair("USD", "SGD").label, "USD/SGD")

    def test_direct_and_inverted_quotes(self):
        # US$100 at 1.31 S$ per US$ is S$131; at 0.65 US$ per A$ it's A$153.85
        self.assertAlmostEqual(fx.Pair("USD", "SGD").to_base(100.0, 1.31), 131.0)
        self.assertAlmostEqual(fx.Pair("USD", "AUD").to_base(100.0, 0.65), 153.846, places=3)
        # USDSGD 1.30 -> 1.31: a US dollar gained 0.77% in SGD
        np.testing.assert_allclose(fx.Pair("USD", "SGD").returns([1.30, 1.31]), [1.31 / 1.30 - 1])
        # Over a crash: USDSGD −10% is −10% for a US dollar in SGD; AUDUSD −25% is +33.3% in AUD
        self.assertAlmostEqual(fx.Pair("USD", "SGD").period_return(-0.10), -0.10)
        self.assertAlmostEqual(fx.Pair("USD", "AUD").period_return(-0.25), 1 / 0.75 - 1)


class SgdAccountTests(StoreTestCase):
    """An SGD account with BHP (A$3,000, rising 1% a day) and Apple (US$650, flat), 30 weekdays.
    USDSGD alternates 1.30 and 1.31; AUDSGD stays at 0.85."""

    def setUp(self):
        super().setUp()
        self.days = weekdays(date(2026, 7, 20), 30)
        self.prices = {
            "BHP.AX": {d: 40.0 * 1.01 ** i for i, d in enumerate(self.days)},
            "AAPL": {d: 100.0 for d in self.days},
            "USDSGD=X": {d: 1.30 if i % 2 == 0 else 1.31 for i, d in enumerate(self.days)},
            "AUDSGD=X": {d: 0.85 for d in self.days},
            "^STI": {d: 3000.0 + i for i, d in enumerate(self.days)},
            "^AXJT": {d: 1000.0 + i for i, d in enumerate(self.days)},
            "^SP500TR": {d: 2000.0 for d in self.days},
        }
        self.yahoo = FakeYahoo(self.prices)

    def holdings(self, extra=()):
        return [
            # A$3,000 at 0.85 is S$2,550
            {"con_id": 1, "symbol": "BHP", "name": "BHP Group", "market": "ASX", "currency": "AUD",
             "yahoo": "BHP.AX", "market_value": 3000.0, "sector": "Basic Materials"},
            # US$650 at the latest rate (1.31) is S$851.50
            {"con_id": 2, "symbol": "AAPL", "name": "Apple", "market": "US", "currency": "USD",
             "yahoo": "AAPL", "market_value": 650.0, "sector": "Technology"},
            *extra,
        ]

    def build(self, holdings=None):
        return asyncio.run(risk_data.build_inputs(holdings or self.holdings(), "3M", TODAY, self.yahoo, base="SGD"))

    def response(self):
        inputs = self.build()
        inputs.cash_base = 5000.0
        inputs.scenarios = {
            "BHP.AX": {"gfc": -0.40, "covid": None, "tech2022": None},
            "AAPL": {"gfc": -0.50, "covid": None, "tech2022": None},
            "USDSGD=X": {"gfc": -0.10, "covid": None, "tech2022": None},
            "AUDSGD=X": {"gfc": 0.05, "covid": None, "tech2022": None},
        }
        return risk_routes.build_response(inputs, datetime(2026, 10, 19, 21, 0))

    def test_rates_come_from_the_pairs_against_sgd(self):
        inputs = self.build()
        fetched = {symbol for symbol, _ in self.yahoo.calls}
        self.assertTrue({"USDSGD=X", "AUDSGD=X", "^STI"} <= fetched)
        self.assertNotIn("AUDUSD=X", fetched)
        self.assertEqual(set(inputs.fx_returns), {"AUD", "USD"})
        self.assertEqual((inputs.base_currency, inputs.home_market, inputs.notes), ("SGD", "SG", []))

    def test_values_and_returns_in_sgd(self):
        inputs = self.build()
        bhp, aapl = inputs.holdings
        self.assertAlmostEqual(bhp["value_base"], 2550.0)
        self.assertAlmostEqual(aapl["value_base"], 851.5)
        np.testing.assert_allclose(inputs.weights, [2550 / 3401.5, 851.5 / 3401.5])
        np.testing.assert_allclose(inputs.returns[:, 0], 0.01)  # AUDSGD is flat: BHP's own 1% a day
        # Apple is flat in USD, so its SGD return is USDSGD's move alone
        self.assertAlmostEqual(inputs.returns[0, 1], 1.31 / 1.30 - 1)
        np.testing.assert_allclose(inputs.fx_returns["USD"], inputs.returns[:, 1])
        np.testing.assert_allclose(inputs.fx_returns["AUD"], 0.0)

    def test_the_sti_is_the_home_index(self):
        inputs = self.build()
        self.assertEqual(inputs.benchmarks["SG"], {"symbol": "^STI", "short": "STI", "total_return": False})
        self.assertEqual(list(inputs.benchmarks), ["ASX", "US", "SG"])

    def test_meta(self):
        meta = self.response()["meta"]
        self.assertEqual((meta["currency"], meta["home_market"]), ("SGD", "SG"))
        self.assertEqual([p["pair"] for p in meta["fx_pairs"]], ["AUD/SGD", "USD/SGD"])
        self.assertIn("STI", meta["benchmark_note"])  # a price index: dividends left out
        self.assertAlmostEqual(self.response()["holdings"][1]["value_base"], 851.5)

    def test_currency_effect_is_each_currency_against_sgd(self):
        section = self.response()["currency"]
        rows = {r["symbol"]: r for r in section["holdings"]}
        self.assertEqual([r["symbol"] for r in section["holdings"]], ["BHP", "AAPL"])  # largest first
        self.assertEqual((rows["BHP"]["currency"], rows["BHP"]["fx_return"]), ("AUD", 0.0))
        usd = 1.31 / 1.30 - 1  # first close 1.30, last 1.31
        self.assertAlmostEqual(rows["AAPL"]["fx_return"], usd, places=4)
        self.assertAlmostEqual(rows["AAPL"]["effect_base"], 851.5 * usd / (1 + usd), places=2)
        self.assertEqual(section["fx_currency"], "AUD")  # the largest foreign holding's currency
        self.assertEqual([c["pair"] for c in section["currencies"]], ["AUD/SGD", "USD/SGD"])

    def test_attribution_compares_with_the_sti(self):
        section = self.response()["attribution"]
        self.assertEqual(section["benchmark"], "STI")
        self.assertAlmostEqual(section["benchmark_return"], 3029 / 3000 - 1, places=4)
        self.assertEqual([(s["market"], s["home"]) for s in section["segments"]], [("ASX", False), ("US", False)])
        self.assertAlmostEqual(section["allocation"] + section["selection"] + section["currency"], section["difference"], places=3)

    def test_stress_tests_in_sgd(self):
        rows = {r["id"]: r for r in self.response()["stress"]["scenarios"]}
        self.assertEqual(rows["currency"]["name"], "SGD rises 10% vs AUD and USD")
        self.assertAlmostEqual(rows["currency"]["impact_base"], 3401.5 * (1 / 1.1 - 1), places=2)
        # GFC: Apple −50% and USDSGD −10%: 851.5 × (0.5 × 0.9 − 1); BHP −40% and AUDSGD +5%: 2550 × (0.6 × 1.05 − 1)
        self.assertAlmostEqual(rows["gfc"]["impact_base"], 851.5 * (0.5 * 0.9 - 1) + 2550 * (0.6 * 1.05 - 1), places=1)

    def test_hedge_cash_var_and_exposure_in_sgd(self):
        response = self.response()
        self.assertEqual(response["mixes"]["currency_hedge"]["currencies"], ["AUD", "USD"])
        self.assertEqual(response["mixes"]["cash"]["cash_base"], 5000.0)
        self.assertEqual(response["exposure"]["cash_base"], 5000.0)
        self.assertAlmostEqual(response["exposure"]["holdings_value_base"], 3401.5)
        self.assertAlmostEqual(response["var"]["value_base"], 3401.5)
        self.assertAlmostEqual(response["volatility"]["portfolio"]["value_base"], 3401.5)

    def test_d_risk_says_sgd(self):
        block = portfolio_facts.risk_block(self.response())
        self.assertEqual(block["currency"], "SGD")
        self.assertIn("Daily returns in SGD", block["basis"])
        self.assertTrue(block["worst_stress_test"]["impact"].startswith(f"{MINUS}S$"))

    def test_a_currency_without_rates_is_left_out(self):
        extra = [{"con_id": 3, "symbol": "VOD", "name": "Vodafone", "market": "US", "currency": "GBP",
                  "yahoo": "VOD", "market_value": 100.0}]
        self.prices["VOD"] = {d: 1.0 for d in self.days}
        inputs = self.build(self.holdings(extra))
        self.assertEqual([h["symbol"] for h in inputs.holdings], ["BHP", "AAPL"])
        self.assertEqual(inputs.left_out, [{"con_id": 3, "symbol": "VOD", "reason": "No exchange rates for GBP"}])

    def test_no_us_dollar_rates_is_an_error(self):
        del self.prices["USDSGD=X"]
        with self.assertRaises(RuntimeError):
            self.build()


class EurAccountTests(StoreTestCase):
    """A base currency with no home index: attribution falls back to the S&P 500, with a note."""

    def test_falls_back_to_the_sp_500(self):
        days = weekdays(date(2026, 7, 20), 30)
        yahoo = FakeYahoo({
            "AAPL": {d: 100.0 for d in days},
            "EURUSD=X": {d: 1.25 for d in days},  # US dollars per euro
            "^AXJT": {d: 1000.0 + i for i, d in enumerate(days)},
            "^SP500TR": {d: 2000.0 + i for i, d in enumerate(days)},
        })
        holdings = [{"con_id": 2, "symbol": "AAPL", "name": "Apple", "market": "US", "currency": "USD",
                     "yahoo": "AAPL", "market_value": 650.0}]
        inputs = asyncio.run(risk_data.build_inputs(holdings, "3M", TODAY, yahoo, base="EUR"))
        self.assertEqual(inputs.home_market, "US")
        self.assertAlmostEqual(inputs.holdings[0]["value_base"], 520.0)  # US$650 ÷ 1.25
        response = risk_routes.build_response(inputs, datetime(2026, 10, 19, 21, 0))
        self.assertEqual(response["meta"]["benchmark_note"], "No home market index for EUR accounts: attribution compares with the S&P 500")
        self.assertEqual(response["attribution"]["benchmark"], "S&P 500")
        self.assertEqual(list(inputs.benchmarks), ["ASX", "US"])


class RiskRouteTests(unittest.TestCase):
    """GET /risk takes the base currency and cash from GET /account."""

    def run_route(self, account):
        built = mock.AsyncMock(side_effect=lambda holdings, period, today, base: built.inputs)
        built.inputs = risk_data.RiskInputs(
            period="1Y", start=date(2025, 10, 19), base_date=date(2025, 10, 17), dates=[date(2025, 10, 20), date(2026, 10, 16)],
            holdings=[{"con_id": 2, "symbol": "AAPL", "name": "Apple", "market": "US", "currency": "USD", "yahoo": "AAPL",
                       "value_base": 851.5, "weight": 1.0, "quantity": 5}],
            returns=np.zeros((2, 1)), local_returns=np.zeros((2, 1)), weights=np.array([1.0]),
            benchmark_returns={"ASX": np.zeros(2), "US": np.zeros(2), "SG": np.zeros(2)}, fx_returns={"USD": np.zeros(2)},
            benchmarks={m: {"symbol": s, "short": m, "total_return": True} for m, s in (("ASX", "^AXJT"), ("US", "^SP500TR"), ("SG", "^STI"))},
            base_currency="SGD", home_market="SG",
        )
        scenarios = mock.AsyncMock(return_value={})
        holdings = [{"con_id": 2, "symbol": "AAPL", "market_value": 650.0}]
        with mock.patch.object(risk_routes, "risk_holdings", mock.AsyncMock(return_value=holdings)), \
             mock.patch.object(risk_routes, "account", account), \
             mock.patch.object(risk_routes, "quotes", mock.AsyncMock(return_value=[])), \
             mock.patch.object(risk_routes.risk_data, "build_inputs", built), \
             mock.patch.object(risk_routes.risk_data, "scenario_returns", scenarios), \
             mock.patch.object(risk_routes, "cached", lambda key, ttl, fetch: fetch()):
            return asyncio.run(risk_routes.risk_overview("1Y")), built, scenarios

    def test_base_currency_and_cash_from_the_account(self):
        response, built, scenarios = self.run_route(mock.AsyncMock(return_value={"currency": "SGD", "cash": 5000.0}))
        self.assertEqual(built.call_args.kwargs["base"], "SGD")
        self.assertEqual(response["meta"]["currency"], "SGD")
        self.assertEqual(response["exposure"]["cash_base"], 5000.0)
        symbols = scenarios.call_args.args[0]
        self.assertIn("USDSGD=X", symbols)
        self.assertIn("^STI", symbols)
        self.assertNotIn("AUDUSD=X", symbols)

    def test_no_account_figures_is_a_502(self):
        with self.assertRaises(HTTPException) as caught:
            self.run_route(mock.AsyncMock(side_effect=RuntimeError("IB down")))
        self.assertEqual(caught.exception.status_code, 502)


def sheet(net, holdings, risk=None):
    """A saved portfolio facts sheet, optionally with a D:risk block."""
    facts = {"base_currency": "AUD", "as_of_text": "now",
             "D:portfolio": {"net_liquidation": net, "holdings_value": net, "cash": "A$4,000.00",
                             "unrealised_gain_or_loss": "+A$3,000.00", "number_of_holdings": len(holdings)},
             "D:income": {"expected_yearly_total": "A$900.00"}, "D:missing": []}
    for i, symbol in enumerate(holdings):
        facts[f"H:{i + 1}"] = {"symbol": symbol}
    if risk:
        facts["D:risk"] = risk
    return facts


# D:risk exactly as the AUD-only version (before #271) saved it: GET /risk's *_aud fields were only
# read while building it, so the saved block holds labels and money strings, no *_aud names
OLD_D_RISK = {
    "available": True, "currency": "AUD",
    "basis": "Daily returns in AUD of today's holdings over the last 1Y (23 Oct 2025 to 20 Oct 2026, 244 trading days); "
             "cash left out; worked out from past prices, not forecasts",
    "volatility_pct": 19.0, "asx_200_volatility_pct": 12.6, "beta_vs_asx_200": 0.03, "beta_vs_sp_500": 0.44,
    "max_drawdown": {"fall_pct": -12.3, "from": "2 Dec 2025", "to": "23 Jan 2026", "same_fall_on_todays_holdings": f"{MINUS}A$13,721.96"},
    "value_at_risk_1_day_95": {"loss_exceeded_on_about_1_day_in_20": "A$2,198.97"},
    "worst_stress_test": {"scenario": "GFC 2008 replay", "period_or_shock": "Sep 2008 to Mar 2009",
                          "impact": f"{MINUS}A$35,756.45", "impact_pct": -32.0},
}


class OldSavedSummaryTests(unittest.TestCase):
    """Portfolio summaries saved before #271 still load, compare and feed "since last"."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(summary_store, "DB_PATH", Path(folder.name) / "summaries.sqlite")
        patcher.start()
        self.addCleanup(patcher.stop)
        empty = {name: {"status": "ok", "points": []} for name in summaries.portfolio_summary.SECTIONS}
        self.old = sheet("A$50,000.00", ["AAPL", "BHP"], OLD_D_RISK)
        self.new = sheet("A$52,500.00", ["AAPL", "BHP", "TLS"], {**OLD_D_RISK, "volatility_pct": 18.0})
        self.old_id = summary_store.save_portfolio("2026-10-17T09:00:00+11:00", "m", self.old, empty, [])
        self.new_id = summary_store.save_portfolio("2026-10-22T09:00:00+11:00", "m", self.new, empty, [])

    def test_an_old_summary_loads(self):
        saved = summaries.past_portfolio_summary(self.old_id)
        self.assertEqual(saved["facts"]["D:risk"]["max_drawdown"]["same_fall_on_todays_holdings"], f"{MINUS}A$13,721.96")

    def test_compare_with_an_old_summary(self):
        result = summaries.compare_portfolio_summaries(self.old_id, self.new_id)
        rows = {r["label"]: r for r in result["data_changes"]}
        self.assertEqual(rows["Net liquidation"]["change"], "+A$2,500.00")
        self.assertEqual(rows["Holdings added"]["new"], "TLS")

    def test_since_last_reads_an_old_summary(self):
        # The previous sheet as the database gives it back; the new one as build_portfolio_facts makes it
        previous = summary_store.get_portfolio(self.old_id)["facts"]
        facts = {**self.new, "D:allocation": {"by_holding": {"AAPL": 60.0, "BHP": 30.0, "TLS": 10.0}}}
        since = portfolio_facts.since_last(previous, facts)
        self.assertEqual(since["net_liquidation"]["change"], "+A$2,500.00")
        self.assertEqual(since["holdings_added"], [{"holding": "H:3", "symbol": "TLS"}])
        self.assertIsNone(since["note"])


if __name__ == "__main__":
    unittest.main()
