"""Performance attribution vs the ASX 200 (#242), with numbers small enough to check by hand."""
import unittest
from datetime import date

import numpy as np

import risk
import risk_data
import risk_sections


class AttributionTests(unittest.TestCase):
    def test_parts_add_up_to_the_difference(self):
        # 40% in Australian shares that rose 12%, 60% in US shares that rose 30% in USD.
        # ASX 200 +10%, S&P 500 +20% in USD, and a US dollar lost 5% in AUD.
        portfolio, allocation, selection, currency, cross = risk.attribution(0.4, 0.12, 0.6, 0.30, 0.10, 0.20, -0.05)
        # Portfolio in AUD: 0.4 × 12% + 0.6 × (1.3 × 0.95 − 1) = 4.8% + 0.6 × 23.5% = 18.9%
        self.assertAlmostEqual(portfolio, 0.189)
        self.assertAlmostEqual(allocation, 0.6 * (0.20 - 0.10))  # +6 points: being in the US
        self.assertAlmostEqual(selection, 0.4 * 0.02 + 0.6 * 0.10)  # +0.8 + 6 = +6.8 points
        self.assertAlmostEqual(currency, 0.6 * -0.05)  # −3 points
        self.assertAlmostEqual(cross, 0.6 * 0.30 * -0.05)  # −0.9 points
        self.assertAlmostEqual(allocation + selection + currency + cross, portfolio - 0.10)  # +8.9 points

    def test_only_australian_shares(self):
        portfolio, allocation, selection, currency, cross = risk.attribution(1.0, 0.08, 0.0, 0.0, 0.10, 0.25, 0.1)
        self.assertAlmostEqual(portfolio, 0.08)
        self.assertEqual((allocation, currency, cross), (0.0, 0.0, 0.0))
        self.assertAlmostEqual(selection, -0.02)


class AttributionSectionTests(unittest.TestCase):
    def test_section_adds_up(self):
        rng = np.random.default_rng(5)
        local = rng.normal(0.0005, 0.01, size=(60, 3))
        fx = rng.normal(0, 0.005, size=60)
        inputs = risk_data.RiskInputs(
            period="1Y", start=date(2025, 10, 19), base_date=date(2025, 10, 20), dates=list(range(60)),
            holdings=[{"symbol": "CBA", "market": "ASX"}, {"symbol": "AAPL", "market": "US"}, {"symbol": "MSFT", "market": "US"}],
            returns=local, local_returns=local, weights=np.array([0.5, 0.3, 0.2]),
            benchmark_returns={"ASX": rng.normal(0.0003, 0.008, 60), "US": rng.normal(0.0004, 0.009, 60)},
            fx_returns=fx, benchmarks={},
        )
        s = risk_sections.attribution_section(inputs)
        self.assertAlmostEqual(s["allocation"] + s["selection"] + s["currency"], s["difference"], places=3)
        self.assertEqual(s["us_weight"], 0.5)


if __name__ == "__main__":
    unittest.main()
