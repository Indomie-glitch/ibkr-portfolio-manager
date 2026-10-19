"""Stress tests (#241): past crashes replayed on today's holdings, and simple shocks. Hand-checked."""
import asyncio
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import numpy as np

import risk
import risk_data
import risk_sections
import yahoo


class PeriodReturnTests(unittest.TestCase):
    def test_from_the_close_before_the_start_to_the_close_before_the_end(self):
        # Friday 29 Aug 2008 is the last close before Sunday 31 Aug: 100 -> 60 is −40%
        closes = {date(2008, 8, 29): 100.0, date(2008, 12, 1): 80.0, date(2009, 3, 9): 60.0, date(2009, 3, 10): 61.0}
        self.assertAlmostEqual(risk.period_return(closes, date(2008, 8, 31), date(2009, 3, 9)), -0.4)

    def test_no_prices_then(self):
        # Listed in 2015: nothing within a week before 31 Aug 2008
        self.assertIsNone(risk.period_return({date(2015, 1, 2): 10.0}, date(2008, 8, 31), date(2009, 3, 9)))

    def test_us_dollar_in_aud(self):
        # AUDUSD 0.80 -> 0.60 (−25%): a US dollar went from A$1.25 to A$1.667, +33.3%
        self.assertAlmostEqual(risk.usd_in_aud_return(-0.25), 1 / 0.75 - 1)


class ScenarioStoreTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.object(risk_data, "DB_PATH", Path(folder.name) / "risk_prices.sqlite")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fetched_once_and_kept(self):
        calls = []

        async def fetch(symbol, start, end):
            calls.append(symbol)
            if symbol == "NEW.AX":
                raise yahoo.YahooUnavailable("no prices then")
            if symbol == "DOWN":
                raise RuntimeError("network")
            return [(date(2020, 2, 19), 100.0), (date(2020, 3, 23), 70.0)]

        got = asyncio.run(risk_data.scenario_returns(["AAPL", "NEW.AX", "DOWN"], fetch))
        self.assertAlmostEqual(got["AAPL"]["covid"], -0.3)
        self.assertIsNone(got["AAPL"]["gfc"])
        self.assertEqual(got["NEW.AX"], {"gfc": None, "covid": None, "tech2022": None})  # kept: never had prices
        self.assertNotIn("DOWN", got)  # a failed call is tried again next time
        asyncio.run(risk_data.scenario_returns(["AAPL", "NEW.AX", "DOWN"], fetch))
        self.assertEqual(calls, ["AAPL", "NEW.AX", "DOWN", "DOWN"])


class StressSectionTests(unittest.TestCase):
    def setUp(self):
        index = np.array([0.01, -0.01, 0.01, -0.01])
        local = np.column_stack([2 * index, index])  # BHP beta 2 vs the ASX 200, AAPL beta 1 vs the S&P 500
        self.inputs = risk_data.RiskInputs(
            period="1Y", start=date(2025, 10, 19), base_date=date(2025, 10, 20), dates=list(range(4)),
            holdings=[
                {"symbol": "BHP", "name": "BHP Group", "market": "ASX", "currency": "AUD", "yahoo": "BHP.AX", "value_aud": 6000.0},
                {"symbol": "AAPL", "name": "Apple", "market": "US", "currency": "USD", "yahoo": "AAPL", "value_aud": 4000.0},
            ],
            returns=local, local_returns=local, weights=np.array([0.6, 0.4]),
            benchmark_returns={"ASX": index, "US": index}, fx_returns=np.zeros(4), benchmarks={},
            scenarios={
                "BHP.AX": {"gfc": -0.5, "covid": None, "tech2022": None},
                "AAPL": {"gfc": None, "covid": None, "tech2022": None},  # no prices then: S&P 500 × beta
                "^SP500TR": {"gfc": -0.4, "covid": None, "tech2022": None},
                "AUDUSD=X": {"gfc": -0.25, "covid": None, "tech2022": None},
            },
        )

    def test_section(self):
        section = risk_sections.stress_section(self.inputs)
        rows = {r["id"]: r for r in section["scenarios"]}
        # GFC: BHP −50% of A$6,000 = −A$3,000. Apple: the S&P 500's −40% × beta 1 in USD, and a US dollar
        # gained 33.3% in AUD: 0.6 × 1.333 − 1 = −20% of A$4,000 = −A$800. Total −A$3,800 (−38%)
        self.assertAlmostEqual(rows["gfc"]["impact_aud"], -3800.0)
        self.assertEqual(rows["gfc"]["impact_pct"], -0.38)
        self.assertEqual(rows["gfc"]["estimated"], ["AAPL"])
        self.assertAlmostEqual(rows["largest"]["impact_aud"], -1200.0)  # BHP falls 20%
        self.assertEqual(rows["largest"]["name"], "BHP Group falls 20%")
        # S&P 500 −10%: only Apple moves, 4,000 × 1 × −10% = −A$400; as a whole-portfolio beta, 0.40
        self.assertAlmostEqual(rows["index_us"]["impact_aud"], -400.0)
        self.assertEqual(rows["index_us"]["label"], "Using your beta 0.40")
        self.assertAlmostEqual(rows["index_asx"]["impact_aud"], -1200.0)  # 6,000 × 2 × −10%
        # AUD +10%: US$ holdings lose 1 − 1/1.1 = 9.09% in AUD
        self.assertAlmostEqual(rows["aud"]["impact_aud"], -363.64)
        # Worst first; crashes without data last, with no figure
        self.assertEqual([r["id"] for r in section["scenarios"]][:5], ["gfc", "largest", "index_asx", "index_us", "aud"])
        self.assertIsNone(rows["covid"]["impact_aud"])

    def test_no_stress_prices_at_all(self):
        self.inputs.scenarios = {}
        rows = {r["id"]: r for r in risk_sections.stress_section(self.inputs)["scenarios"]}
        self.assertIsNone(rows["gfc"]["impact_aud"])
        self.assertAlmostEqual(rows["aud"]["impact_aud"], -363.64)  # the shocks still work


if __name__ == "__main__":
    unittest.main()
