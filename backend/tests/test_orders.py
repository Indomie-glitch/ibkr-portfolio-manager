import unittest
from types import SimpleNamespace

from trading import UNSET, build_order, check_order, what_if_summary

OPEN = {"can_trade": True, "reason": None, "max_order_value": 10000.0}


def order(action="BUY", quantity=10, order_type="LMT", limit_price=100.0):
    return {"action": action, "quantity": quantity, "order_type": order_type, "limit_price": limit_price}


class CheckOrderTest(unittest.TestCase):
    def test_valid_order(self):
        problems, value, value_base = check_order(order(), 100.0, 1.5, 0, OPEN)
        self.assertEqual(problems, [])
        self.assertEqual((value, value_base), (1000.0, 1500.0))

    def test_trading_off_is_a_problem(self):
        status = {**OPEN, "can_trade": False, "reason": "Trading is off: the app is read only."}
        problems, _, _ = check_order(order(), 100.0, 1, 0, status)
        self.assertEqual(problems, ["Trading is off: the app is read only."])

    def test_limit_uses_base_currency(self):
        # 70 × 100 USD = 7,000 USD = 10,500 AUD: over a 10,000 AUD limit
        problems, _, value_base = check_order(order(quantity=70), 100.0, 1.5, 0, OPEN)
        self.assertEqual(value_base, 10500.0)
        self.assertTrue(any("above the 10,000 limit" in p for p in problems))

    def test_whole_shares_and_limit_price(self):
        problems, _, _ = check_order(order(quantity=1.5, limit_price=None), None, 1, 0, OPEN)
        self.assertIn("Enter a whole number of shares.", problems)
        self.assertIn("Enter a limit price above zero.", problems)

    def test_no_short_selling(self):
        problems, _, _ = check_order(order(action="SELL", quantity=20), 100.0, 1, 5, OPEN)
        self.assertIn("You can sell at most 5 shares (the number you hold).", problems)
        self.assertEqual(check_order(order(action="SELL", quantity=5), 100.0, 1, 5, OPEN)[0], [])

    def test_unknown_price_or_rate(self):
        self.assertTrue(any("current price" in p for p in check_order(order(order_type="MKT"), None, 1, 0, OPEN)[0]))
        self.assertTrue(any("exchange rate" in p for p in check_order(order(), 100.0, None, 0, OPEN)[0]))


class BuildOrderTest(unittest.TestCase):
    def test_limit_and_market(self):
        limit = build_order(order(limit_price=12.345678))
        self.assertEqual((limit.orderType, limit.action, limit.totalQuantity, limit.lmtPrice, limit.tif),
                         ("LMT", "BUY", 10, 12.3457, "DAY"))
        self.assertFalse(limit.outsideRth)
        market = build_order(order(action="SELL", order_type="MKT"))
        self.assertEqual((market.orderType, market.action), ("MKT", "SELL"))


class WhatIfTest(unittest.TestCase):
    def test_unset_values_become_none(self):
        state = SimpleNamespace(commission=UNSET, minCommission=1.0, maxCommission=2.5, commissionCurrency="USD",
                                initMarginChange="250.5", maintMarginChange="", equityWithLoanChange="-3.2",
                                warningText="")
        summary = what_if_summary(state)
        self.assertIsNone(summary["commission"])
        self.assertEqual((summary["min_commission"], summary["max_commission"]), (1.0, 2.5))
        self.assertEqual(summary["init_margin_change"], 250.5)
        self.assertIsNone(summary["maint_margin_change"])
        self.assertIsNone(summary["warning"])


if __name__ == "__main__":
    unittest.main()
