import unittest
from types import SimpleNamespace

from trading import UNSET, ConfirmationTokens, build_order, check_order, what_if_summary

OPEN = {"can_trade": True, "reason": None, "max_order_value": 10000.0}


def order(action="BUY", quantity=10, order_type="LMT", limit_price=100.0):
    return {"action": action, "quantity": quantity, "order_type": order_type, "limit_price": limit_price}


class CheckOrderTest(unittest.TestCase):
    def test_valid_order(self):
        problems, value, value_base = check_order(order(), 100.0, 1.5, 0, OPEN)
        self.assertEqual(problems, [])
        self.assertEqual((value, value_base), (1000.0, 1500.0))

    def test_not_connected_is_a_problem(self):
        status = {**OPEN, "can_trade": False, "reason": "Trading is unavailable until IB Gateway is connected."}
        problems, _, _ = check_order(order(), 100.0, 1, 0, status)
        self.assertEqual(problems, ["Trading is unavailable until IB Gateway is connected."])

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


class ConfirmationTokensTest(unittest.TestCase):
    def test_single_use(self):
        tokens = ConfirmationTokens()
        token = tokens.issue(1, order(), now=0)
        self.assertIsNone(tokens.redeem(token, 1, order(), now=10))
        self.assertIn("already used", tokens.redeem(token, 1, order(), now=11))

    def test_expires(self):
        tokens = ConfirmationTokens(lifetime_s=120)
        token = tokens.issue(1, order(), now=0)
        self.assertIn("expired", tokens.redeem(token, 1, order(), now=121))

    def test_bound_to_the_order(self):
        tokens = ConfirmationTokens()
        for changed in (order(quantity=11), order(limit_price=101), order(action="SELL"), order(order_type="MKT")):
            token = tokens.issue(1, order(), now=0)
            self.assertIn("changed", tokens.redeem(token, 1, changed, now=1))
        token = tokens.issue(1, order(), now=0)
        self.assertIn("changed", tokens.redeem(token, 2, order(), now=1))

    def test_missing_token(self):
        self.assertIn("expired", ConfirmationTokens().redeem(None, 1, order(), now=0))


class TradeSummaryTest(unittest.TestCase):
    def test_summary(self):
        from ib_async import Contract, OrderStatus, Trade
        from ib_async.objects import TradeLogEntry
        from routers.trading import trade_summary
        trade = Trade(contract=Contract(conId=1, symbol="BHP"), order=build_order(order(quantity=5, limit_price=40.0)),
                      orderStatus=OrderStatus(status="Submitted", filled=2, remaining=3, avgFillPrice=39.9),
                      log=[TradeLogEntry(time=None, status="Submitted", message="Order accepted")])
        trade.order.orderId = 7
        summary = trade_summary(trade)
        self.assertEqual((summary["order_id"], summary["symbol"], summary["status"], summary["filled"], summary["remaining"]),
                         (7, "BHP", "Submitted", 2, 3))
        self.assertEqual((summary["limit_price"], summary["avg_fill_price"], summary["message"]), (40.0, 39.9, "Order accepted"))


if __name__ == "__main__":
    unittest.main()
