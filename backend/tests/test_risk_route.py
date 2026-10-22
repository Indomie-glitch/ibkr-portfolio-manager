"""GET /risk's answer (#98): meta, holdings, and one failing section not breaking the others."""
import unittest
from datetime import date, datetime
from unittest import mock

import numpy as np

import risk_data
from routers import risk as risk_routes


def inputs():
    return risk_data.RiskInputs(
        period="1Y", start=date(2025, 10, 19), base_date=date(2025, 10, 17), dates=[date(2025, 10, 20), date(2026, 10, 16)],
        holdings=[{"con_id": 1, "symbol": "BHP", "name": "BHP Group", "market": "ASX", "currency": "AUD",
                   "yahoo": "BHP.AX", "value_base": 3000.0, "weight": 1.0}],
        returns=np.zeros((2, 1)), local_returns=np.zeros((2, 1)), weights=np.array([1.0]),
        benchmark_returns={"ASX": np.zeros(2), "US": np.zeros(2)}, fx_returns={"USD": np.zeros(2)},
        benchmarks={"ASX": {"symbol": "^AXJT", "short": "ASX 200", "total_return": True},
                    "US": {"symbol": "^GSPC", "short": "S&P 500", "total_return": False}},
        left_out=[{"con_id": 2, "symbol": "SAP", "reason": "Only AUD and USD holdings are included (EUR)"}],
    )


class BuildResponseTests(unittest.TestCase):
    def test_meta_and_holdings(self):
        response = risk_routes.build_response(inputs(), datetime(2026, 10, 19, 9, 0))
        meta = response["meta"]
        self.assertEqual(meta["days_used"], 2)
        self.assertEqual(meta["currency"], "AUD")
        self.assertTrue(meta["cash_excluded"])
        self.assertEqual(meta["last_day"], "2026-10-16")
        self.assertEqual(meta["left_out"][0]["symbol"], "SAP")
        self.assertIn("S&P 500", meta["benchmark_note"])  # the price index fallback is mentioned
        self.assertEqual(response["holdings"][0]["weight"], 1.0)
        self.assertNotIn("yahoo", response["holdings"][0])

    def test_a_failing_section_only_breaks_itself(self):
        sections = {"good": lambda i: {"value": 1}, "bad": lambda i: 1 / 0, "nan": lambda i: {"value": float("nan")}}
        with mock.patch.object(risk_routes, "SECTIONS", sections):
            response = risk_routes.build_response(inputs(), datetime(2026, 10, 19, 9, 0))
        self.assertEqual(response["good"], {"value": 1})
        self.assertEqual(response["bad"], {"error": "Couldn't calculate this section."})
        self.assertEqual(response["nan"], {"error": "Couldn't calculate this section."})


if __name__ == "__main__":
    unittest.main()
