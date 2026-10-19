"""Covariance and correlation (#103), with returns small enough to check by hand.

A = +2%, 0%, −2% and B = +1%, +1%, −2%. Both average 0, so
var(A) = (0.02² + 0 + 0.02²) / 2 = 0.0004, var(B) = (0.01² + 0.01² + 0.02²) / 2 = 0.0003,
cov(A, B) = (0.02 × 0.01 + 0 × 0.01 + 0.02 × 0.02) / 2 = 0.0003,
corr = 0.0003 / √(0.0004 × 0.0003) = 3 / √12 = 0.866.
"""
import math
import unittest
from datetime import date

import numpy as np

import risk
import risk_data
import risk_sections

A = [0.02, 0.0, -0.02]
B = [0.01, 0.01, -0.02]


class CorrelationMathsTests(unittest.TestCase):
    def test_covariance(self):
        cov = risk.covariance(np.column_stack([A, B]))
        np.testing.assert_allclose(cov, [[0.0004, 0.0003], [0.0003, 0.0003]], atol=1e-12)

    def test_correlation(self):
        corr = risk.correlation(np.column_stack([A, B]))
        self.assertAlmostEqual(corr[0, 1], 3 / math.sqrt(12), places=9)
        self.assertEqual(corr[0, 0], 1.0)

    def test_perfectly_together_and_perfectly_opposite(self):
        corr = risk.correlation(np.column_stack([A, [2 * a for a in A], [-a for a in A]]))
        self.assertAlmostEqual(corr[0, 1], 1.0)
        self.assertAlmostEqual(corr[0, 2], -1.0)

    def test_a_holding_that_never_moved(self):
        corr = risk.correlation(np.column_stack([A, [0.0, 0.0, 0.0]]))
        self.assertEqual(corr[0, 1], 0.0)
        self.assertEqual(corr[1, 1], 1.0)

    def test_same_direction_counts_only_days_both_moved(self):
        # Day 2: A didn't move, so it isn't counted. Days 1 and 3: same way. 2 of 2.
        self.assertEqual(risk.same_direction_share(A, B), 1.0)
        # Up/up, up/down, down/down, down/up: half the days
        self.assertEqual(risk.same_direction_share([1, 1, -1, -1], [1, -1, -1, 1]), 0.5)
        self.assertIsNone(risk.same_direction_share([0, 0], [1, -1]))

    def test_pairs(self):
        self.assertEqual(risk.pairs([[1, 0.5, 0.2], [0.5, 1, -0.1], [0.2, -0.1, 1]]),
                         [(0, 1, 0.5), (0, 2, 0.2), (1, 2, -0.1)])


def inputs(columns, symbols):
    returns = np.column_stack(columns)
    n = returns.shape[1]
    return risk_data.RiskInputs(
        period="1Y", start=date(2025, 10, 19), base_date=date(2026, 10, 13), dates=[date(2026, 10, 14 + i) for i in range(len(returns))],
        holdings=[{"con_id": i, "symbol": s} for i, s in enumerate(symbols)],
        returns=returns, local_returns=returns, weights=np.full(n, 1 / n),
        benchmark_returns={}, fx_returns=np.zeros(len(returns)), benchmarks={},
    )


class CorrelationSectionTests(unittest.TestCase):
    def test_section(self):
        C = [-a for a in A]
        section = risk_sections.correlation_section(inputs([A, B, C], ["AAA", "BBB", "CCC"]))
        self.assertEqual(section["symbols"], ["AAA", "BBB", "CCC"])
        self.assertEqual(section["matrix"][0][1], 0.866)
        self.assertEqual(section["most_related"]["a"], "AAA")
        self.assertEqual(section["most_related"]["b"], "BBB")
        self.assertEqual(section["least_related"]["correlation"], -1.0)  # AAA and CCC
        self.assertEqual(section["least_related"]["same_direction"], 0.0)
        # B moved 0.0003 / 0.0004 = 0.75% for each 1% A moved; C exactly opposite
        self.assertEqual(section["pairs"][0]["b_per_a"], 0.75)
        self.assertEqual(section["least_related"]["b_per_a"], -1.0)
        # (0.866 − 1 − 0.866) / 3
        self.assertAlmostEqual(section["average"], -0.333, places=3)

    def test_one_holding_has_no_pairs(self):
        section = risk_sections.correlation_section(inputs([A], ["AAA"]))
        self.assertEqual(section["matrix"], [[1.0]])
        self.assertIsNone(section["most_related"])
        self.assertIsNone(section["average"])


if __name__ == "__main__":
    unittest.main()
