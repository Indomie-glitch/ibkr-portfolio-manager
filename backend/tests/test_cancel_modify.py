import asyncio
import unittest
from unittest import mock

from fastapi import HTTPException
from ib_async import Contract, OrderStatus, Trade

import main
from trading import build_order


class FakeRequest:
    headers = {}


def open_limit_order(status="Submitted"):
    t = Trade(contract=Contract(conId=1, symbol="BHP"),
              order=build_order({"action": "BUY", "quantity": 5, "order_type": "LMT", "limit_price": 40.0}),
              orderStatus=OrderStatus(status=status, remaining=5))
    t.order.orderId = 9
    return t


OK_CHECK = {"problems": [], "contract": None}


class CancelModifyTest(unittest.TestCase):
    def setUp(self):
        self.trade = open_limit_order()
        patches = [
            mock.patch.object(main.ib, "openTrades", return_value=[self.trade]),
            mock.patch.object(main, "settled", side_effect=lambda trade, waiting: main.trade_summary(trade)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_cancel(self):
        with mock.patch.object(main.ib, "cancelOrder") as cancel:
            asyncio.run(main.cancel_order(9, FakeRequest()))
        cancel.assert_called_once_with(self.trade.order)

    def test_cancel_unknown_or_finished_order(self):
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(main.cancel_order(10, FakeRequest()))
        self.assertEqual(caught.exception.status_code, 404)
        self.trade.orderStatus.status = "Filled"
        with self.assertRaises(HTTPException):
            asyncio.run(main.cancel_order(9, FakeRequest()))

    def change(self, token, quantity=8, limit_price=41.0):
        return main.ModifyOrderRequest(quantity=quantity, limit_price=limit_price, confirmation_token=token)

    def test_modify_needs_a_preview_of_the_new_order(self):
        token = main.confirmation_tokens.issue(1, {"action": "BUY", "quantity": 8, "order_type": "LMT", "limit_price": 41.0}, main.time.monotonic())
        with mock.patch.object(main, "checked_order", return_value=OK_CHECK), \
                mock.patch.object(main.ib, "placeOrder") as place:
            asyncio.run(main.modify_order(9, self.change(token), FakeRequest()))
        place.assert_called_once_with(self.trade.contract, self.trade.order)
        self.assertEqual((self.trade.order.totalQuantity, self.trade.order.lmtPrice), (8, 41.0))

    def test_modify_with_token_for_other_numbers_is_refused(self):
        token = main.confirmation_tokens.issue(1, {"action": "BUY", "quantity": 8, "order_type": "LMT", "limit_price": 41.0}, main.time.monotonic())
        with mock.patch.object(main.ib, "placeOrder") as place, self.assertRaises(HTTPException) as caught:
            asyncio.run(main.modify_order(9, self.change(token, quantity=50), FakeRequest()))
        self.assertIn("changed", caught.exception.detail)
        place.assert_not_called()
        self.assertEqual(self.trade.order.totalQuantity, 5)

    def test_modify_refused_by_checks(self):
        token = main.confirmation_tokens.issue(1, {"action": "BUY", "quantity": 8, "order_type": "LMT", "limit_price": 41.0}, main.time.monotonic())
        refused = {"problems": ["The order is worth about 20,000.00 in the account's currency, above the 10,000 limit (MAX_ORDER_VALUE)."], "contract": None}
        with mock.patch.object(main, "checked_order", return_value=refused), \
                mock.patch.object(main.ib, "placeOrder") as place, self.assertRaises(HTTPException):
            asyncio.run(main.modify_order(9, self.change(token), FakeRequest()))
        place.assert_not_called()


if __name__ == "__main__":
    unittest.main()
