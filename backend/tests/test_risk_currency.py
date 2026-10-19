"""The currency effect on US holdings (#101), with numbers small enough to check by hand."""
import unittest
from datetime import date

import numpy as np

import risk
import risk_data
import risk_sections


class CurrencyMathsTests(unittest.TestCase):
    def test_compound(self):
        # +10% then −10% is −1% overall, not 0
        self.assertAlmostEqual(risk.compound([0.10, -0.10]), -0.01)
        np.testing.assert_allclose(risk.compound([[0.1, 0.0], [0.1, 0.5]]), [0.21, 0.5])

    def test_effect_in_dollars(self):
        # Worth A$10,800 today after the US dollar lost 10% against the AUD: at the old rate it would be
        # A$12,000, so the currency cost A$1,200
        self.assertAlmostEqual(risk.currency_effect_aud(10800, -0.10), -1200)
        self.assertAlmostEqual(risk.currency_effect_aud(11000, 0.10), 1000)


class CurrencySectionTests(unittest.TestCase):
    def test_section(self):
        # AAPL: +20% then 0% in USD; a US dollar loses 5% then 5% in AUD
        local = np.array([[0.0, 0.20], [0.01, 0.0]])
        fx = np.array([-0.05, -0.05])
        # AUD returns: CBA's as they are; AAPL's combine its price and the currency each day
        aud = np.column_stack([local[:, 0], (1 + local[:, 1]) * (1 + fx) - 1])
        inputs = risk_data.RiskInputs(
            period="1Y", start=date(2025, 10, 19), base_date=date(2026, 10, 14), dates=[date(2026, 10, 15), date(2026, 10, 16)],
            holdings=[{"symbol": "CBA", "name": "CBA", "currency": "AUD", "value_aud": 5000.0},
                      {"symbol": "AAPL", "name": "Apple", "currency": "USD", "value_aud": 10830.0}],
            returns=aud, local_returns=local, weights=np.array([0.3, 0.7]),
            benchmark_returns={}, fx_returns=fx, benchmarks={},
        )
        section = risk_sections.currency_section(inputs)
        (aapl,) = section["holdings"]  # only US holdings
        self.assertEqual(aapl["price_return"], 0.2)
        # 0.95 × 0.95 − 1 = −9.75%; (1.2)(0.9025) − 1 = +8.3%
        self.assertEqual(aapl["fx_return"], -0.0975)
        self.assertEqual(aapl["aud_return"], 0.083)
        # A$10,830 × −0.0975 / 0.9025 = −A$1,170
        self.assertAlmostEqual(aapl["effect_aud"], -1170.0, places=0)
        self.assertEqual(section["total_effect_aud"], aapl["effect_aud"])


if __name__ == "__main__":
    unittest.main()
