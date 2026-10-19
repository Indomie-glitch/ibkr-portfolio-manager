"""Volatility, beta and max drawdown (#102), with numbers small enough to check by hand."""
import math
import unittest
from datetime import date

import numpy as np

import risk
import risk_data
import risk_sections

ZIGZAG = [0.01, -0.01, 0.01, -0.01]  # mean 0; sample variance 4 × 0.0001 / 3


class VolatilityTests(unittest.TestCase):
    def test_yearly_volatility(self):
        # sd = √(0.0004 / 3) = 1.1547% a day; × √252 = 18.33% a year
        self.assertAlmostEqual(risk.annual_volatility(ZIGZAG), math.sqrt(0.0004 / 3) * math.sqrt(252), places=12)
        self.assertAlmostEqual(risk.annual_volatility(ZIGZAG), 0.1833, places=4)

    def test_column_by_column(self):
        vols = risk.annual_volatility(np.column_stack([ZIGZAG, [2 * r for r in ZIGZAG]]))
        self.assertAlmostEqual(vols[1], 2 * vols[0])

    def test_portfolio_return_is_the_weighted_sum(self):
        # 75% in a stock up 2%, 25% in one down 4%: 1.5% − 1% = +0.5%
        np.testing.assert_allclose(risk.portfolio_returns([[0.02, -0.04]], [0.75, 0.25]), [0.005])


class BetaTests(unittest.TestCase):
    def test_twice_the_index(self):
        self.assertAlmostEqual(risk.beta([2 * r for r in ZIGZAG], ZIGZAG), 2.0)

    def test_unrelated_to_the_index(self):
        # Products with the index: +1, −1, −1, +1 (× 0.0001): covariance 0
        self.assertAlmostEqual(risk.beta([0.01, 0.01, -0.01, -0.01], ZIGZAG), 0.0)

    def test_an_index_that_never_moved(self):
        self.assertIsNone(risk.beta(ZIGZAG, [0.0, 0.0, 0.0, 0.0]))


class DrawdownTests(unittest.TestCase):
    def test_largest_fall_from_a_high(self):
        # Values 1, 1.1, 0.88, 0.924, 0.8316, 1.081: high 1.1 (after day 1), low 0.8316 (after day 4)
        fall, peak, trough = risk.max_drawdown([0.10, -0.20, 0.05, -0.10, 0.30])
        self.assertAlmostEqual(fall, 0.8316 / 1.1 - 1)  # −24.4%
        self.assertEqual((peak, trough), (1, 4))

    def test_a_fall_from_the_start(self):
        self.assertEqual(risk.max_drawdown([-0.1])[1:], (0, 1))
        self.assertAlmostEqual(risk.max_drawdown([-0.1])[0], -0.1)

    def test_never_fell(self):
        self.assertEqual(risk.max_drawdown([0.01, 0.02]), (0.0, 0, 0))


class VolatilitySectionTests(unittest.TestCase):
    def setUp(self):
        days = [date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)]
        index = np.array(ZIGZAG)
        # BHP moves twice the ASX 200 (in AUD); AAPL moves with the S&P 500 in USD, and the AUD return
        # adds a currency move that doesn't change its beta
        local = np.column_stack([2 * index, index])
        fx = np.array([0.005, 0.005, -0.005, -0.005])
        aud = np.column_stack([2 * index, (1 + index) * (1 + fx) - 1])
        self.inputs = risk_data.RiskInputs(
            period="1Y", start=date(2025, 10, 19), base_date=date(2026, 10, 9), dates=days,
            holdings=[
                {"con_id": 1, "symbol": "BHP", "market": "ASX", "weight": 0.75, "value_aud": 7500.0},
                {"con_id": 2, "symbol": "AAPL", "market": "US", "weight": 0.25, "value_aud": 2500.0},
            ],
            returns=aud, local_returns=local, weights=np.array([0.75, 0.25]),
            benchmark_returns={"ASX": index, "US": index}, fx_returns=fx, benchmarks={},
        )

    def test_section(self):
        section = risk_sections.volatility_section(self.inputs)
        bhp, aapl = section["holdings"]
        self.assertEqual((bhp["beta"], bhp["beta_vs"]), (2.0, "ASX 200"))
        self.assertEqual((aapl["beta"], aapl["beta_vs"]), (1.0, "S&P 500"))  # own currency, so FX doesn't change it
        self.assertAlmostEqual(bhp["volatility"], 2 * 0.1833, places=3)
        self.assertEqual(section["portfolio"]["value_aud"], 10000.0)
        self.assertEqual(section["portfolio"]["us_weight"], 0.25)
        self.assertAlmostEqual(section["benchmarks"]["ASX"]["volatility"], 0.1833, places=4)

    def test_drawdown_dates_and_loss_on_todays_value(self):
        section = risk_sections.volatility_section(self.inputs)
        dd = section["max_drawdown"]
        self.assertLess(dd["fall"], 0)
        # Daily portfolio returns +1.876%, −1.626%, +1.624%, −1.874%: values 1, 1.0188, 1.0022, 1.0185,
        # 0.9994. The high is after day 1 (12 Oct) and the low after day 4 (15 Oct): −1.9%
        self.assertEqual((dd["peak"], dd["trough"]), ("2026-10-12", "2026-10-15"))
        self.assertAlmostEqual(dd["fall"], 0.99938 / 1.01876 - 1, places=3)
        self.assertAlmostEqual(dd["loss_aud"], dd["fall"] * 10000, delta=1)


if __name__ == "__main__":
    unittest.main()
