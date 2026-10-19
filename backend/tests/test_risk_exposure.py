"""Exposure by currency, market and sector (#100), and the cash figure for its footnote."""
import unittest
from datetime import date

import numpy as np

import risk_data
import risk_sections
from routers import risk as risk_routes


def inputs(cash=None):
    holdings = [
        {"symbol": "AAPL", "currency": "USD", "market": "US", "sector": "Technology", "value_aud": 6000.0},
        {"symbol": "CBA", "currency": "AUD", "market": "ASX", "sector": "Financial Services", "value_aud": 3000.0},
        {"symbol": "XYZ", "currency": "AUD", "market": "ASX", "sector": None, "value_aud": 1000.0},
    ]
    return risk_data.RiskInputs(
        period="1Y", start=date(2025, 10, 19), base_date=date(2025, 10, 20), dates=[], holdings=holdings,
        returns=np.zeros((0, 3)), local_returns=np.zeros((0, 3)), weights=np.array([0.6, 0.3, 0.1]),
        benchmark_returns={}, fx_returns=np.zeros(0), benchmarks={}, cash_aud=cash,
    )


class ExposureTests(unittest.TestCase):
    def test_splits(self):
        section = risk_sections.exposure_section(inputs(cash=50000.0))
        self.assertEqual(section["currency"], [{"name": "USD", "share": 0.6}, {"name": "AUD", "share": 0.4}])
        self.assertEqual(section["market"], [{"name": "United States", "share": 0.6}, {"name": "Australia", "share": 0.4}])
        # Yahoo's "Financial Services" is shortened; a holding without a sector is "Unknown"
        self.assertEqual(section["sector"], [{"name": "Technology", "share": 0.6}, {"name": "Financials", "share": 0.3},
                                             {"name": "Unknown", "share": 0.1}])
        self.assertEqual(section["holdings_value_aud"], 10000.0)
        self.assertEqual(section["cash_aud"], 50000.0)

    def test_cash_in_aud(self):
        self.assertEqual(risk_routes.cash_in_aud({"cash": 1000.0, "currency": "AUD"}), 1000.0)
        # A US dollar base: 1 AUD = 0.65 USD, so US$650 of cash is A$1,000
        self.assertAlmostEqual(risk_routes.cash_in_aud({"cash": 650.0, "currency": "USD", "fx_rates": {"AUD": 0.65}}), 1000.0)
        self.assertIsNone(risk_routes.cash_in_aud({"cash": 650.0, "currency": "USD", "fx_rates": {}}))
        self.assertIsNone(risk_routes.cash_in_aud({"currency": "AUD"}))


if __name__ == "__main__":
    unittest.main()
