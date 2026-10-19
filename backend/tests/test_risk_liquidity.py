"""Liquidity (#245): how long each holding would take to sell. Hand-checkable numbers."""
import unittest
from datetime import date

import numpy as np

import risk
import risk_data
import risk_sections


class TimeToSellTests(unittest.TestCase):
    def test_small_position(self):
        # 100 shares, 1,000,000 a day: 10% of a day is 100,000 shares, so 100 shares take 0.001 days,
        # 0.39 minutes of a 390-minute US session
        days, minutes = risk.time_to_sell(100, 1_000_000, "US")
        self.assertAlmostEqual(days, 0.001)
        self.assertAlmostEqual(minutes, 0.39)

    def test_big_position(self):
        # 50,000 shares of a stock trading 100,000 a day: 10,000 a day, so 5 trading days
        self.assertAlmostEqual(risk.time_to_sell(50_000, 100_000, "ASX")[0], 5.0)
        self.assertAlmostEqual(risk.time_to_sell(5_000, 100_000, "ASX")[1], 180.0)  # half of a 360-minute ASX day

    def test_no_volume(self):
        self.assertEqual(risk.time_to_sell(100, None, "US"), (None, None))


class LiquiditySectionTests(unittest.TestCase):
    def test_slowest_holding(self):
        inputs = risk_data.RiskInputs(
            period="1Y", start=date(2025, 10, 19), base_date=date(2025, 10, 20), dates=[],
            holdings=[{"symbol": "AAPL", "market": "US", "quantity": 100, "avg_volume": 50_000_000},
                      {"symbol": "XYZ", "market": "ASX", "quantity": 20_000, "avg_volume": 100_000},
                      {"symbol": "NEW", "market": "ASX", "quantity": 10, "avg_volume": None}],
            returns=np.zeros((0, 3)), local_returns=np.zeros((0, 3)), weights=np.full(3, 1 / 3),
            benchmark_returns={}, fx_returns=np.zeros(0), benchmarks={},
        )
        section = risk_sections.liquidity_section(inputs)
        self.assertEqual(section["slowest"]["symbol"], "XYZ")
        self.assertEqual(section["slowest"]["days"], 2.0)  # 20,000 ÷ 10,000 a day
        self.assertIsNone(section["holdings"][2]["days"])


if __name__ == "__main__":
    unittest.main()
