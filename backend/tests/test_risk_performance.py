"""Sharpe ratio and tracking error (#239), with numbers small enough to check by hand."""
import math
import unittest
from datetime import date
from unittest import mock

import numpy as np

import config
import risk
import risk_data
import risk_sections


class AnnualReturnTests(unittest.TestCase):
    def test_a_year_of_days_is_the_total_return(self):
        # 252 days of +0.1%: 1.001^252 − 1 = 28.6%, and over exactly 252 days that is the yearly rate
        self.assertAlmostEqual(risk.annual_return([0.001] * 252), 1.001 ** 252 - 1)

    def test_a_quarter_is_scaled_to_a_year(self):
        # 63 days that add up to +5%: a year at that pace is 1.05^(252/63) − 1 = 1.05⁴ − 1 = 21.6%
        daily = 1.05 ** (1 / 63) - 1
        self.assertAlmostEqual(risk.annual_return([daily] * 63), 1.05 ** 4 - 1)


class SharpeTests(unittest.TestCase):
    def test_sharpe(self):
        # Alternating +2% and 0%: a yearly return r, volatility σ = sd × √252; Sharpe = (r − 4.6%) / σ
        returns = [0.02, 0.0] * 126
        expected = (risk.annual_return(returns) - 0.046) / (np.std(returns, ddof=1) * math.sqrt(252))
        self.assertAlmostEqual(risk.sharpe_ratio(returns, 0.046), expected)

    def test_a_series_that_never_moved(self):
        self.assertIsNone(risk.sharpe_ratio([0.0, 0.0, 0.0], 0.046))


class TrackingErrorTests(unittest.TestCase):
    def test_same_as_the_index(self):
        self.assertEqual(risk.tracking_error([0.01, -0.02, 0.03], [0.01, -0.02, 0.03]), 0.0)

    def test_a_steady_gap_is_no_tracking_error(self):
        # Always 0.1% ahead of the index: the difference never varies, so it doesn't drift
        self.assertAlmostEqual(risk.tracking_error([0.011, -0.019, 0.031], [0.01, -0.02, 0.03]), 0.0)

    def test_drift(self):
        # Differences +1%, −1%, +1%, −1%: sd 1.1547% a day, × √252 = 18.33% a year
        self.assertAlmostEqual(risk.tracking_error([0.01, -0.01, 0.01, -0.01], [0, 0, 0, 0]), 0.1833, places=4)


class PerformanceSectionTests(unittest.TestCase):
    def test_section(self):
        days = 20
        asx = np.array([0.01, -0.005] * (days // 2))
        us = np.array([0.0, 0.002] * (days // 2))
        returns = np.column_stack([asx, us])  # one holding follows each index
        inputs = risk_data.RiskInputs(
            period="1Y", start=date(2025, 10, 19), base_date=date(2025, 10, 20), dates=list(range(days)),
            holdings=[{"symbol": "CBA"}, {"symbol": "AAPL"}], returns=returns, local_returns=returns,
            weights=np.array([0.5, 0.5]), benchmark_returns={"ASX": asx, "US": us}, fx_returns=np.zeros(days),
            benchmarks={},
        )
        with mock.patch.object(config, "risk_free_rate", return_value=0.046):
            section = risk_sections.performance_section(inputs)
        portfolio = 0.5 * asx + 0.5 * us
        self.assertAlmostEqual(section["portfolio"]["sharpe"], round(risk.sharpe_ratio(portfolio, 0.046), 3))
        self.assertAlmostEqual(section["benchmarks"]["ASX"]["sharpe"], round(risk.sharpe_ratio(asx, 0.046), 3))
        self.assertAlmostEqual(section["tracking_error"]["ASX"], round(risk.tracking_error(portfolio, asx), 4))
        self.assertEqual(section["risk_free_rate"], 0.046)


if __name__ == "__main__":
    unittest.main()
