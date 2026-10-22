"""Value at Risk (#240), with numbers small enough to check by hand."""
import unittest
from datetime import date

import numpy as np

import risk
import risk_data
import risk_sections


class ParametricTests(unittest.TestCase):
    def test_one_holding(self):
        # Daily volatility 1% (variance 0.0001): 95% VaR = −1.645 × 1% = −1.645% a day
        self.assertAlmostEqual(risk.parametric_var([1.0], [[0.0001]], 0.95), -0.01645)
        self.assertAlmostEqual(risk.parametric_var([1.0], [[0.0001]], 0.99), -0.02326)

    def test_a_month_scales_with_the_square_root_of_its_days(self):
        self.assertAlmostEqual(risk.parametric_var([1.0], [[0.0001]], 0.95, 21), -0.01645 * np.sqrt(21))

    def test_two_unrelated_holdings_half_each(self):
        # σₚ² = 0.25 × 0.0004 + 0.25 × 0.0001 = 0.000125, σₚ = 1.118%; VaR = −1.645 × 1.118% = −1.839%
        self.assertAlmostEqual(risk.parametric_var([0.5, 0.5], [[0.0004, 0], [0, 0.0001]], 0.95),
                               -1.645 * np.sqrt(0.000125))


class HistoricalTests(unittest.TestCase):
    def test_fifth_percentile_of_days(self):
        # Returns −10%, −9%, …, +9% (20 days): the 5th percentile (linear) is −10% + 0.95 × 1% = −9.05%
        returns = [i / 100 for i in range(-10, 10)]
        self.assertAlmostEqual(risk.historical_var(returns, 0.95), -0.0905)

    def test_overlapping_runs(self):
        # Two-day runs of +10%, −10%, +10%: 1.1 × 0.9 − 1 = −1% twice; the worst is −1%
        self.assertAlmostEqual(risk.historical_var([0.10, -0.10, 0.10], 0.95, days=2), -0.01)
        self.assertIsNone(risk.historical_var([0.01], 0.95, days=2))


class SimulatedTests(unittest.TestCase):
    def test_close_to_the_formula_for_one_day(self):
        cov = [[0.0004, 0], [0, 0.0001]]
        formula = risk.parametric_var([0.5, 0.5], cov, 0.95)
        self.assertAlmostEqual(risk.simulated_var([0.5, 0.5], cov, 0.95), formula, delta=abs(formula) * 0.05)

    def test_the_same_every_time(self):
        cov = [[0.0004, 0.0001], [0.0001, 0.0002]]
        self.assertEqual(risk.simulated_var([0.6, 0.4], cov, 0.95, 21), risk.simulated_var([0.6, 0.4], cov, 0.95, 21))


class VarSectionTests(unittest.TestCase):
    def test_section(self):
        rng = np.random.default_rng(3)
        returns = rng.normal(0, 0.01, size=(120, 2))
        inputs = risk_data.RiskInputs(
            period="1Y", start=date(2025, 10, 19), base_date=date(2025, 10, 20), dates=list(range(120)),
            holdings=[{"symbol": "CBA", "value_base": 6000.0}, {"symbol": "BHP", "value_base": 4000.0}],
            returns=returns, local_returns=returns, weights=np.array([0.6, 0.4]), benchmark_returns={},
            fx_returns={"USD": np.zeros(120)}, benchmarks={},
        )
        section = risk_sections.var_section(inputs)
        self.assertEqual(section["value_base"], 10000.0)
        formula = section["levels"]["95"]["formula"]
        # The return is rounded to 5 decimals, so A$ can differ by up to 5 cents
        self.assertAlmostEqual(formula["day"]["base"], formula["day"]["return"] * 10000, delta=0.06)
        self.assertLess(section["levels"]["99"]["formula"]["day"]["base"], formula["day"]["base"])  # bigger loss
        self.assertLess(formula["month"]["base"], formula["day"]["base"])
        self.assertEqual(set(section["levels"]["95"]), {"formula", "history", "simulated"})


if __name__ == "__main__":
    unittest.main()
