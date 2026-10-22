"""Example mixes and hedges (#243), with numbers small enough to check by hand."""
import unittest
from datetime import date
from unittest import mock

import numpy as np

import config
import risk
import risk_data
import risk_sections


class CapTests(unittest.TestCase):
    def test_excess_spread_in_proportion(self):
        # 70% capped at 40%: the 30% excess goes to the others in proportion to 20% and 10%: +20%, +10%
        np.testing.assert_allclose(risk.cap_weights([0.7, 0.2, 0.1], 0.4), [0.4, 0.4, 0.2])

    def test_repeated_until_nothing_is_over(self):
        # 60% capped: 20% spread over 30% and 10% in proportion: 45% and 15%. 45% is now over: 5% more
        # goes to the last one: 40%, 40%, 20%
        np.testing.assert_allclose(risk.cap_weights([0.6, 0.3, 0.1], 0.4), [0.4, 0.4, 0.2])

    def test_impossible_with_two_holdings(self):
        self.assertIsNone(risk.cap_weights([0.7, 0.3], 0.4))  # 2 × 40% is only 80%


class SimplexTests(unittest.TestCase):
    def test_already_allowed(self):
        np.testing.assert_allclose(risk.project_to_simplex([0.3, 0.7]), [0.3, 0.7])

    def test_nearest_allowed_point(self):
        # (1, 1): the nearest weights adding to 1 are (0.5, 0.5); (2, 0): (1, 0)
        np.testing.assert_allclose(risk.project_to_simplex([1.0, 1.0]), [0.5, 0.5])
        np.testing.assert_allclose(risk.project_to_simplex([2.0, 0.0]), [1.0, 0.0])
        np.testing.assert_allclose(risk.project_to_simplex([0.5, -0.5]), [1.0, 0.0])


class MinVarianceTests(unittest.TestCase):
    def test_two_unrelated_holdings(self):
        # Variances 0.04 and 0.01, unrelated: the lowest risk mix weights each by 1/variance:
        # (25, 100) / 125 = 20% and 80%
        np.testing.assert_allclose(risk.min_variance_weights([[0.04, 0], [0, 0.01]]), [0.2, 0.8], atol=1e-6)

    def test_never_short(self):
        # A holding that only adds risk (it moves with the calm one but much more) gets 0, not a negative
        w = risk.min_variance_weights([[0.01, 0.015], [0.015, 0.09]])
        self.assertGreaterEqual(w.min(), 0)
        self.assertAlmostEqual(w.sum(), 1)
        np.testing.assert_allclose(w, [1.0, 0.0], atol=1e-6)


class MixesSectionTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        local = rng.normal(0.0005, [0.02, 0.01, 0.01], size=(120, 3))
        fx = rng.normal(0, 0.005, size=120)
        aud = local.copy()
        aud[:, 0] = (1 + local[:, 0]) * (1 + fx) - 1
        self.inputs = risk_data.RiskInputs(
            period="1Y", start=date(2025, 10, 19), base_date=date(2025, 10, 20), dates=list(range(120)),
            holdings=[{"symbol": "AAPL", "name": "Apple", "currency": "USD", "value_base": 7000.0},
                      {"symbol": "CBA", "name": "CBA", "currency": "AUD", "value_base": 2000.0},
                      {"symbol": "BHP", "name": "BHP", "currency": "AUD", "value_base": 1000.0}],
            returns=aud, local_returns=local, weights=np.array([0.7, 0.2, 0.1]), benchmark_returns={},
            fx_returns={"USD": fx}, benchmarks={}, cash_base=30000.0,
        )

    def section(self):
        with mock.patch.object(config, "risk_free_rate", return_value=0.046):
            return risk_sections.mixes_section(self.inputs)

    def test_mixes(self):
        section = self.section()
        mixes = {m["id"]: m for m in section["mixes"]}
        self.assertEqual(list(mixes), ["current", "capped", "equal", "lowest_risk"])
        self.assertEqual([w["weight"] for w in mixes["capped"]["weights"]], [0.4, 0.4, 0.2])
        self.assertEqual(mixes["capped"]["name"], "Apple")
        # The lowest risk mix has the lowest volatility of all
        self.assertLessEqual(mixes["lowest_risk"]["volatility"], min(m["volatility"] for m in section["mixes"]))

    def test_hedges(self):
        section = self.section()
        # Cash is 30,000 of a 40,000 account: 75%, and the whole account swings a quarter as much
        self.assertEqual(section["cash"]["share"], 0.75)
        self.assertAlmostEqual(section["cash"]["account_volatility"], section["mixes"][0]["volatility"] * 0.25, places=4)
        fx = float(np.prod(1 + self.inputs.fx_returns["USD"]) - 1)
        self.assertAlmostEqual(section["currency_hedge"]["result_base"], -7000 * fx / (1 + fx), places=1)

    def test_no_cap_row_when_nothing_is_over_40_percent(self):
        self.inputs.weights = np.array([0.4, 0.35, 0.25])
        self.assertNotIn("capped", [m["id"] for m in self.section()["mixes"]])


if __name__ == "__main__":
    unittest.main()
