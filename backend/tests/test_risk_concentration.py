"""Concentration (#99): share of money vs share of risk, effective holdings and warnings."""
import unittest
from datetime import date

import numpy as np

import risk
import risk_data
import risk_sections


class RiskContributionTests(unittest.TestCase):
    def test_two_unrelated_holdings(self):
        # Σ = diag(0.04, 0.01): 20% and 10% swings, unrelated. Half the money in each:
        # Σw = (0.02, 0.005), wᵀΣw = 0.0125, so the shares of risk are 0.01 / 0.0125 = 80% and 20%
        np.testing.assert_allclose(risk.risk_contributions([0.5, 0.5], [[0.04, 0], [0, 0.01]]), [0.8, 0.2])

    def test_a_holding_that_offsets_the_rest_has_a_negative_share(self):
        # Covariance −0.01: Σw = (0.03, −0.006), wᵀΣw = 0.0228; shares 105.3% and −5.3%, adding up to 100%
        shares = risk.risk_contributions([0.8, 0.2], [[0.04, -0.01], [-0.01, 0.01]])
        np.testing.assert_allclose(shares, [0.024 / 0.0228, -0.0012 / 0.0228])
        self.assertAlmostEqual(shares.sum(), 1.0)

    def test_effective_holdings(self):
        self.assertAlmostEqual(risk.effective_holdings([0.5, 0.5]), 2.0)
        self.assertAlmostEqual(risk.effective_holdings([0.25] * 4), 4.0)
        # The design's weights: 1 / (0.682² + 0.213² + 0.083² + 0.016² + 0.007²) = 1.93, "1.9 of 5"
        self.assertAlmostEqual(risk.effective_holdings([0.682, 0.213, 0.083, 0.016, 0.007]), 1.93, places=2)

    def test_shares_by_label(self):
        self.assertEqual(risk.shares_by([0.5, 0.3, 0.2], ["USD", "AUD", "USD"]), [("USD", 0.7), ("AUD", 0.3)])


class ConcentrationSectionTests(unittest.TestCase):
    def test_section(self):
        rng = np.random.default_rng(1)
        returns = rng.normal(0, 0.01, size=(60, 3))
        inputs = risk_data.RiskInputs(
            period="1Y", start=date(2025, 10, 19), base_date=date(2025, 10, 20), dates=list(range(60)),
            holdings=[
                {"symbol": "CBA", "currency": "AUD", "sector": "Financial Services"},
                {"symbol": "AAPL", "currency": "USD", "sector": "Technology"},
                {"symbol": "MSFT", "currency": "USD", "sector": "Technology"},
            ],
            returns=returns, local_returns=returns, weights=np.array([0.1, 0.6, 0.3]),
            benchmark_returns={}, fx_returns={"USD": np.zeros(60)}, benchmarks={},
        )
        section = risk_sections.concentration_section(inputs)
        self.assertEqual([r["symbol"] for r in section["holdings"]], ["AAPL", "MSFT", "CBA"])  # by money
        self.assertAlmostEqual(sum(r["risk_share"] for r in section["holdings"]), 1.0, places=3)
        self.assertEqual(section["top3_share"], 1.0)
        self.assertEqual(section["largest"]["symbol"], "AAPL")
        self.assertEqual(section["effective_holdings"], round(1 / (0.01 + 0.36 + 0.09), 2))  # 2.17
        # Over the AI portfolio summary's thresholds: a stock over 20%, a sector over 40%, a currency over 80%
        self.assertEqual([(w["kind"], w["name"]) for w in section["warnings"]],
                         [("stock", "AAPL"), ("stock", "MSFT"), ("sector", "Technology"), ("currency", "USD")])
        self.assertEqual(section["warnings"][3]["share"], 0.9)


if __name__ == "__main__":
    unittest.main()
