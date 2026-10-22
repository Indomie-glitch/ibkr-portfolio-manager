"""The risk analysis's daily returns pipeline (#98): risk.py helpers and risk_data's price store and
returns matrix. Small hand-checkable numbers; Yahoo is a fake and the database a temp file."""
import asyncio
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import numpy as np

import fx
import risk
import risk_data

D1, D2, D3 = date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)
USD_IN_AUD = fx.Pair("USD", "AUD")  # quoted as AUDUSD


class HelperTests(unittest.TestCase):
    def test_usd_prices_become_aud(self):
        # US$100 at 0.65 US$ per A$ is A$153.85; US$102 at 0.66 is A$154.55
        aud = USD_IN_AUD.convert({D1: 100.0, D2: 102.0, D3: 104.0}, {D1: 0.65, D2: 0.66})
        self.assertEqual(set(aud), {D1, D2})  # no rate on D3
        self.assertAlmostEqual(aud[D1], 153.846, places=3)
        self.assertAlmostEqual(aud[D2], 154.545, places=3)

    def test_align_keeps_only_common_days(self):
        # A US holiday on D2: the ASX stock has a close, the US stock doesn't, so D2 is dropped
        dates, matrix = risk.align({"BHP": {D1: 40.0, D2: 41.0, D3: 42.0}, "AAPL": {D1: 200.0, D3: 210.0}})
        self.assertEqual(dates, [D1, D3])
        np.testing.assert_array_equal(matrix, [[40.0, 200.0], [42.0, 210.0]])

    def test_simple_returns(self):
        returns = risk.simple_returns([[100.0, 50.0], [110.0, 45.0], [99.0, 45.0]])
        np.testing.assert_allclose(returns, [[0.10, -0.10], [-0.10, 0.0]])

    def test_a_stronger_aud_is_a_negative_return_on_us_dollars(self):
        # AUDUSD 0.65 -> 0.66: a US dollar was worth A$1.5385, now A$1.5152, a fall of 1.52%
        np.testing.assert_allclose(USD_IN_AUD.returns([0.65, 0.66]), [0.65 / 0.66 - 1])
        self.assertAlmostEqual(USD_IN_AUD.returns([0.65, 0.66])[0], -0.01515, places=5)

    def test_aud_return_combines_price_and_currency(self):
        # (1 + 2%) × (1 − 1.515%) − 1 = 0.4545%, the same as the change in the AUD price
        aud = USD_IN_AUD.convert({D1: 100.0, D2: 102.0}, {D1: 0.65, D2: 0.66})
        direct = aud[D2] / aud[D1] - 1
        combined = (1 + 0.02) * (1 + USD_IN_AUD.returns([0.65, 0.66])[0]) - 1
        self.assertAlmostEqual(direct, combined, places=12)
        self.assertAlmostEqual(direct, 0.004545, places=6)

    def test_weights(self):
        np.testing.assert_allclose(risk.weights([300.0, 100.0]), [0.75, 0.25])
        with self.assertRaises(ValueError):
            risk.weights([0.0, 0.0])

    def test_windows(self):
        today = date(2026, 10, 19)
        self.assertEqual(risk.window_start("3M", today), date(2026, 7, 19))
        self.assertEqual(risk.window_start("1Y", today), date(2025, 10, 19))
        self.assertEqual(risk.window_start("3Y", today), date(2023, 10, 19))
        # 31 May less three months is the last day of February
        self.assertEqual(risk.window_start("3M", date(2026, 5, 31)), date(2026, 2, 28))

    def test_a_series_must_start_within_a_week_of_the_window(self):
        start = date(2025, 10, 19)
        self.assertTrue(risk.covers_window(date(2025, 10, 20), start))  # Monday after a weekend
        self.assertTrue(risk.covers_window(start + timedelta(days=7), start))
        self.assertFalse(risk.covers_window(start + timedelta(days=8), start))


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(risk_data, "DB_PATH", Path(folder.name) / "risk_prices.sqlite")
        patcher.start()
        self.addCleanup(patcher.stop)


class FakeYahoo:
    """Serves closes from {symbol: {date: close}} and records every call."""

    def __init__(self, prices, failing=()):
        self.prices = prices
        self.failing = set(failing)
        self.calls = []

    async def __call__(self, symbol, start):
        self.calls.append((symbol, start))
        if symbol in self.failing or symbol not in self.prices:
            raise RuntimeError(f"no data for {symbol}")
        return sorted((d, c) for d, c in self.prices[symbol].items() if d >= start)


def weekdays(start, count):
    days, day = [], start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


class PriceStoreTests(StoreTestCase):
    TODAY = date(2026, 10, 19)

    def test_first_fetch_gets_three_years_then_only_once_a_day(self):
        yahoo = FakeYahoo({"BHP.AX": {D1: 40.0, D2: 41.0}})
        closes = asyncio.run(risk_data.update("BHP.AX", self.TODAY, yahoo))
        self.assertEqual(closes, {D1: 40.0, D2: 41.0})
        self.assertEqual(yahoo.calls, [("BHP.AX", self.TODAY - timedelta(days=risk_data.HISTORY_DAYS))])
        asyncio.run(risk_data.update("BHP.AX", self.TODAY, yahoo))
        self.assertEqual(len(yahoo.calls), 1)  # same day: from the database

    def test_next_day_fetches_only_the_recent_days(self):
        yahoo = FakeYahoo({"BHP.AX": {D1: 40.0, D2: 41.0}})
        asyncio.run(risk_data.update("BHP.AX", self.TODAY, yahoo))
        yahoo.prices["BHP.AX"][D3] = 42.0
        closes = asyncio.run(risk_data.update("BHP.AX", self.TODAY + timedelta(days=1), yahoo))
        self.assertEqual(closes, {D1: 40.0, D2: 41.0, D3: 42.0})
        # Two weeks before the last stored close, to catch re-adjusted prices
        self.assertEqual(yahoo.calls[1], ("BHP.AX", D2 - timedelta(days=risk_data.OVERLAP_DAYS)))
        self.assertEqual(len(yahoo.calls), 2)

    def test_a_dividend_readjustment_fetches_everything_again(self):
        old = date(2026, 9, 1)
        yahoo = FakeYahoo({"BHP.AX": {old: 30.0, D1: 40.0, D2: 41.0}})
        asyncio.run(risk_data.update("BHP.AX", self.TODAY, yahoo))
        # A dividend: Yahoo lowers every earlier adjusted close by 2%
        yahoo.prices["BHP.AX"] = {old: 29.4, D1: 39.2, D2: 40.18, D3: 41.0}
        closes = asyncio.run(risk_data.update("BHP.AX", self.TODAY + timedelta(days=1), yahoo))
        self.assertEqual(closes, {old: 29.4, D1: 39.2, D2: 40.18, D3: 41.0})
        self.assertEqual(len(yahoo.calls), 3)  # first fetch, recent days, then everything

    def test_a_failed_update_keeps_the_stored_prices(self):
        yahoo = FakeYahoo({"BHP.AX": {D1: 40.0}})
        asyncio.run(risk_data.update("BHP.AX", self.TODAY, yahoo))
        yahoo.failing.add("BHP.AX")
        stale = []
        closes = asyncio.run(risk_data.update("BHP.AX", self.TODAY + timedelta(days=1), yahoo, stale))
        self.assertEqual(closes, {D1: 40.0})
        self.assertEqual(stale, ["BHP.AX"])

    def test_a_failure_with_nothing_stored_raises(self):
        with self.assertRaises(RuntimeError):
            asyncio.run(risk_data.update("BHP.AX", self.TODAY, FakeYahoo({})))


class BuildInputsTests(StoreTestCase):
    """30 weekdays of prices. The window (3M before 19 Oct 2026) starts on 19 Jul."""
    TODAY = date(2026, 10, 19)

    def setUp(self):
        super().setUp()
        self.days = weekdays(date(2026, 7, 20), 30)
        n = len(self.days)
        # BHP rises 1% a day; AAPL is flat at US$100; AUDUSD alternates 0.65 and 0.66
        self.prices = {
            "BHP.AX": {d: 40.0 * 1.01 ** i for i, d in enumerate(self.days)},
            "AAPL": {d: 100.0 for d in self.days},
            "AUDUSD=X": {d: 0.65 if i % 2 == 0 else 0.66 for i, d in enumerate(self.days)},
            "^AXJT": {d: 1000.0 + i for i, d in enumerate(self.days)},
            "^SP500TR": {d: 2000.0 for d in self.days},
            "^AXJO": {d: 500.0 for d in self.days},
            "^GSPC": {d: 600.0 for d in self.days},
        }
        self.n = n

    def holdings(self, extra=()):
        return [
            {"con_id": 1, "symbol": "BHP", "name": "BHP Group", "market": "ASX", "currency": "AUD",
             "yahoo": "BHP.AX", "market_value": 3000.0},
            # US$650 at the latest rate (0.66): A$984.85
            {"con_id": 2, "symbol": "AAPL", "name": "Apple", "market": "US", "currency": "USD",
             "yahoo": "AAPL", "market_value": 650.0},
            *extra,
        ]

    def build(self, holdings=None, yahoo=None):
        return asyncio.run(risk_data.build_inputs(holdings or self.holdings(), "3M", self.TODAY,
                                                  yahoo or FakeYahoo(self.prices)))

    def test_returns_matrix_in_aud(self):
        inputs = self.build()
        self.assertEqual(inputs.days_used, self.n - 1)
        self.assertEqual(inputs.dates[0], self.days[1])
        np.testing.assert_allclose(inputs.returns[:, 0], 0.01)  # BHP, already in AUD
        # Apple's price is flat, so its AUD return is the currency move alone
        np.testing.assert_allclose(inputs.returns[0, 1], 0.65 / 0.66 - 1)
        np.testing.assert_allclose(inputs.returns[1, 1], 0.66 / 0.65 - 1)
        np.testing.assert_allclose(inputs.local_returns[:, 1], 0.0)
        np.testing.assert_allclose(inputs.fx_returns["USD"], inputs.returns[:, 1])
        np.testing.assert_allclose(inputs.benchmark_returns["ASX"][0], 1001 / 1000 - 1)

    def test_weights_use_aud_values(self):
        inputs = self.build()
        aapl_aud = 650.0 / 0.66
        np.testing.assert_allclose(inputs.weights, [3000 / (3000 + aapl_aud), aapl_aud / (3000 + aapl_aud)])
        self.assertAlmostEqual(inputs.holdings[1]["value_base"], 984.85, places=2)

    def test_total_return_indexes_are_used(self):
        inputs = self.build()
        self.assertEqual(inputs.benchmarks["ASX"], {"symbol": "^AXJT", "short": "ASX 200", "total_return": True})
        self.assertEqual(inputs.benchmarks["US"]["symbol"], "^SP500TR")

    def test_price_index_fallback(self):
        del self.prices["^SP500TR"]
        inputs = self.build()
        self.assertEqual(inputs.benchmarks["US"], {"symbol": "^GSPC", "short": "S&P 500", "total_return": False})

    def test_left_out_holdings(self):
        short = {d: 5.0 for d in self.days[10:]}  # listed two weeks into the window
        self.prices["NEW.AX"] = short
        extra = [
            {"con_id": 3, "symbol": "NEW", "name": "New Co", "market": "ASX", "currency": "AUD",
             "yahoo": "NEW.AX", "market_value": 100.0},
            {"con_id": 4, "symbol": "SAP", "name": "SAP", "market": None, "currency": "EUR",
             "yahoo": None, "market_value": 100.0},
            {"con_id": 5, "symbol": "XYZ", "name": "Xyz", "market": "US", "currency": "USD",
             "yahoo": "XYZ", "market_value": 100.0},  # Yahoo has nothing
        ]
        inputs = self.build(self.holdings(extra))
        self.assertEqual([h["symbol"] for h in inputs.holdings], ["BHP", "AAPL"])
        reasons = {o["symbol"]: o["reason"] for o in inputs.left_out}
        self.assertEqual(reasons["NEW"], f"Prices only from {self.days[10].strftime('%-d %b %Y')}")
        self.assertEqual(reasons["SAP"], "No daily prices for this exchange")
        self.assertEqual(reasons["XYZ"], "Couldn't get its prices from Yahoo")
        self.assertEqual(inputs.days_used, self.n - 1)  # the short holding doesn't shrink the window

    def test_days_missing_from_any_series_are_dropped(self):
        del self.prices["AAPL"][self.days[5]]  # a US holiday
        inputs = self.build()
        self.assertEqual(inputs.days_used, self.n - 2)
        self.assertNotIn(self.days[5], inputs.dates)

    def test_no_usable_holdings(self):
        with self.assertRaises(risk_data.NotEnoughData):
            self.build([{"con_id": 4, "symbol": "SAP", "name": "SAP", "market": None, "currency": "EUR",
                         "yahoo": None, "market_value": 100.0}])

    def test_too_few_days(self):
        for symbol in self.prices:
            self.prices[symbol] = {d: c for d, c in self.prices[symbol].items() if d >= self.days[0]}
        # Keep only the first 15 days of AUDUSD: 14 returns is too few
        self.prices["AUDUSD=X"] = {d: 0.65 for d in self.days[:15]}
        with self.assertRaises(risk_data.NotEnoughData):
            self.build()


if __name__ == "__main__":
    unittest.main()
