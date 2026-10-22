"""Exposure by currency, market and sector (#100), and the cash figure for its footnote."""
import unittest
from datetime import date

import numpy as np

import risk_data
import risk_sections


def inputs(cash=None):
    holdings = [
        {"symbol": "AAPL", "currency": "USD", "market": "US", "sector": "Technology", "value_base": 6000.0},
        {"symbol": "CBA", "currency": "AUD", "market": "ASX", "sector": "Financial Services", "value_base": 3000.0},
        {"symbol": "XYZ", "currency": "AUD", "market": "ASX", "sector": None, "value_base": 1000.0},
    ]
    return risk_data.RiskInputs(
        period="1Y", start=date(2025, 10, 19), base_date=date(2025, 10, 20), dates=[], holdings=holdings,
        returns=np.zeros((0, 3)), local_returns=np.zeros((0, 3)), weights=np.array([0.6, 0.3, 0.1]),
        benchmark_returns={}, fx_returns={}, benchmarks={}, cash_base=cash,
    )


class ExposureTests(unittest.TestCase):
    def test_splits(self):
        section = risk_sections.exposure_section(inputs(cash=50000.0))
        self.assertEqual(section["currency"], [{"name": "USD", "share": 0.6}, {"name": "AUD", "share": 0.4}])
        self.assertEqual(section["market"], [{"name": "United States", "share": 0.6}, {"name": "Australia", "share": 0.4}])
        # Yahoo's "Financial Services" is shortened; a holding without a sector is "Unknown"
        self.assertEqual(section["sector"], [{"name": "Technology", "share": 0.6}, {"name": "Financials", "share": 0.3},
                                             {"name": "Unknown", "share": 0.1}])
        self.assertEqual(section["holdings_value_base"], 10000.0)
        self.assertEqual(section["cash_base"], 50000.0)


if __name__ == "__main__":
    unittest.main()
