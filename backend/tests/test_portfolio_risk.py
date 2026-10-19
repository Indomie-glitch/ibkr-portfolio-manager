"""D:risk (#108): the Risk page's main findings in the AI portfolio summary's facts, and the prompt."""
import unittest

import portfolio_summary
from portfolio_facts import risk_block

RISK = {
    "meta": {"period": "1Y", "first_day": "2025-10-21", "last_day": "2026-10-16", "days_used": 244},
    "holdings": [{"con_id": 265598, "symbol": "AAPL"}, {"con_id": 4036812, "symbol": "BHP"}],
    "volatility": {
        "portfolio": {"volatility": 0.198, "beta_asx": 0.47, "beta_us": 0.89},
        "benchmarks": {"ASX": {"volatility": 0.13}, "US": {"volatility": 0.16}},
        "max_drawdown": {"fall": -0.163, "peak": "2026-04-02", "trough": "2026-04-21", "loss_aud": -11801.0},
    },
    "concentration": {
        "holdings": [{"symbol": "AAPL", "weight": 0.682, "risk_share": 0.916}, {"symbol": "BHP", "weight": 0.318, "risk_share": 0.084}],
        "count": 2, "effective_holdings": 1.77,
        "warnings": [{"kind": "stock", "name": "AAPL", "share": 0.682, "threshold": 0.2}],
    },
    "var": {"levels": {"95": {"formula": {"day": {"aud": -1485.0}}}}},
    "stress": {"scenarios": [{"name": "GFC 2008 replay", "label": "Sep 2008 to Mar 2009", "impact_aud": -34030.0, "impact_pct": -0.47}]},
}


class RiskBlockTests(unittest.TestCase):
    def test_findings(self):
        block = risk_block(RISK)
        self.assertTrue(block["available"])
        self.assertIn("21 Oct 2025 to 16 Oct 2026, 244 trading days", block["basis"])
        self.assertIn("not forecasts", block["basis"])
        self.assertEqual((block["volatility_pct"], block["asx_200_volatility_pct"]), (19.8, 13.0))
        self.assertEqual((block["beta_vs_asx_200"], block["beta_vs_sp_500"]), (0.47, 0.89))
        self.assertEqual(block["effective_holdings"], {"behaves_like": 1.8, "out_of": 2})
        # The top risk contributor is cited by its holding id, so the app can link it
        self.assertEqual(block["largest_risk_contributor"],
                         {"holding": "H:265598", "share_of_money_pct": 68.2, "share_of_risk_pct": 91.6})
        self.assertEqual(block["max_drawdown"], {"fall_pct": -16.3, "from": "2 Apr 2026", "to": "21 Apr 2026",
                                                 "same_fall_on_todays_holdings": "−A$11,801.00"})
        self.assertEqual(block["value_at_risk_1_day_95"], {"loss_exceeded_on_about_1_day_in_20": "A$1,485.00"})
        self.assertEqual(block["worst_stress_test"]["impact"], "−A$34,030.00")
        self.assertEqual(block["warnings"], ["AAPL is 68.2% of the holdings (above 20%)"])
        self.assertNotIn("unavailable", block)

    def test_failed_sections_are_listed(self):
        block = risk_block({**RISK, "var": {"error": "Couldn't calculate this section."}, "stress": None})
        self.assertEqual(block["unavailable"], ["var", "stress"])
        self.assertNotIn("value_at_risk_1_day_95", block)
        self.assertIn("volatility_pct", block)

    def test_no_risk_analysis(self):
        self.assertEqual(risk_block(None), {"available": False})


class PromptTests(unittest.TestCase):
    def test_key_risks_cite_d_risk_and_keep_the_advice_rule(self):
        prompt = portfolio_summary.SYSTEM_PROMPT
        self.assertIn("D:risk", prompt)
        self.assertIn("not a forecast", prompt)
        self.assertIn("Never give advice", prompt)

    def test_advice_is_still_flagged(self):
        # The extra checks still catch advice, whatever the facts cite
        section = {"status": "ok", "points": [{"text": "You should trim Apple to cut the volatility.", "sources": ["D:risk"]}]}
        _, warnings = portfolio_summary.validate_section("key_risks", section, {"D:risk"}, {})
        self.assertTrue(any("advice" in w.lower() or "trim" in w.lower() for w in warnings), warnings)


if __name__ == "__main__":
    unittest.main()
