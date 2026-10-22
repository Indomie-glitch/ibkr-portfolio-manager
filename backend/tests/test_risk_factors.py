"""Hidden factors by principal component analysis (#105), with matrices small enough to solve by hand."""
import math
import unittest
from datetime import date

import numpy as np

import risk
import risk_data
import risk_sections

A = [0.01, -0.01, 0.01, -0.01]
C = [0.01, 0.01, -0.01, -0.01]  # unrelated to A: correlation 0


class PcaTests(unittest.TestCase):
    def test_two_holdings(self):
        # Correlation matrix [[1, ρ], [ρ, 1]] has eigenvalues 1 + ρ and 1 − ρ, with eigenvectors
        # (1, 1)/√2 and (1, −1)/√2. With ρ = 3/√12 = 0.866 the first factor explains (1 + ρ)/2 = 93.3%
        rho = 3 / math.sqrt(12)
        shares, loadings, _ = risk.pca(np.column_stack([[0.02, 0.0, -0.02], [0.01, 0.01, -0.02]]))
        np.testing.assert_allclose(shares, [(1 + rho) / 2, (1 - rho) / 2])
        # Loading = eigenvector × √eigenvalue = √((1 + ρ)/2) = 0.966 for both on the first factor
        np.testing.assert_allclose(loadings[:, 0], [math.sqrt((1 + rho) / 2)] * 2)

    def test_two_that_move_together_and_one_on_its_own(self):
        # Correlations [[1, 1, 0], [1, 1, 0], [0, 0, 1]]: eigenvalues 2, 1, 0, so the shares are 2/3, 1/3, 0.
        # F1 is the pair (loadings 1, 1, 0); F2 is the third holding alone (0, 0, 1)
        shares, loadings, factor_returns = risk.pca(np.column_stack([A, [2 * a for a in A], C]))
        np.testing.assert_allclose(shares, [2 / 3, 1 / 3, 0], atol=1e-12)
        np.testing.assert_allclose(loadings[:, 0], [1, 1, 0], atol=1e-9)
        np.testing.assert_allclose(np.abs(loadings[:, 1]), [0, 0, 1], atol=1e-9)
        self.assertEqual(factor_returns.shape, (4, 3))

    def test_signs_make_the_loadings_add_up_to_a_positive_number(self):
        _, loadings, _ = risk.pca(np.column_stack([A, [2 * a for a in A], C]))
        self.assertTrue(all(loadings[:, k].sum() >= -1e-12 for k in range(3)))


def inputs(columns, holdings, asx, us):
    returns = np.column_stack(columns)
    return risk_data.RiskInputs(
        period="1Y", start=date(2025, 10, 19), base_date=date(2025, 10, 20), dates=list(range(len(returns))),
        holdings=holdings, returns=returns, local_returns=returns, weights=np.full(len(holdings), 1 / len(holdings)),
        benchmark_returns={"ASX": np.array(asx), "US": np.array(us)}, fx_returns={"USD": np.zeros(len(returns))}, benchmarks={},
    )


class FactorSectionTests(unittest.TestCase):
    HOLDINGS = [{"symbol": "CBA", "name": "Commonwealth Bank", "sector": "Financial Services"},
                {"symbol": "BHP", "name": "BHP Group", "sector": "Basic Materials"},
                {"symbol": "AAPL", "name": "Apple", "sector": "Technology"}]

    def test_names_from_the_indexes(self):
        # F1 (CBA and BHP) follows the ASX 200; F2 (Apple alone) follows the S&P 500
        section = risk_sections.factors_section(inputs([A, [2 * a for a in A], C], self.HOLDINGS, asx=A, us=C))
        f1, f2, _ = section["factors"]
        self.assertEqual((f1["name"], f1["share"]), ("Australian market", round(2 / 3, 4)))
        self.assertEqual((f2["name"], f2["top_holding"]), ("US tech (Apple)", "AAPL"))
        self.assertEqual(section["top2_share"], 1.0)
        self.assertEqual(section["loadings"][2]["f2"], 1.0)

    def test_every_number_is_valid_json(self):
        # The third factor explains nothing, so its correlation with an index is undefined (NaN):
        # it must come out as null, or the whole answer can't be read by the browser
        import json
        section = risk_sections.factors_section(inputs([A, [2 * a for a in A], C], self.HOLDINGS, asx=A, us=C))
        json.dumps(section, allow_nan=False)

    def test_a_factor_unlike_either_index(self):
        # Neither index moves like Apple's factor: it's named after its main holding
        section = risk_sections.factors_section(inputs([A, [2 * a for a in A], C], self.HOLDINGS, asx=A, us=A))
        self.assertEqual(section["factors"][1]["name"], "Mostly Apple")

    def test_one_holding(self):
        section = risk_sections.factors_section(inputs([A], self.HOLDINGS[:1], asx=A, us=A))
        self.assertEqual(section["factors"], [])
        self.assertIn("at least two", section["note"])


if __name__ == "__main__":
    unittest.main()
