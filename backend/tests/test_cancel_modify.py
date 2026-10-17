import asyncio
import unittest
from unittest import mock

from fastapi import HTTPException
from ib_async import Contract, OrderStatus, Trade
from ib_async.objects import TradeLogEntry

from routers import trading as orders_api
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
            mock.patch.object(orders_api.ib, "openTrades", return_value=[self.trade]),
            mock.patch.object(orders_api, "settled", side_effect=lambda trade, waiting: orders_api.trade_summary(trade)),
            mock.patch.object(orders_api, "MODIFY_CHECK_S", 0.2),  # don't wait 2 s per test
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_cancel(self):
        with mock.patch.object(orders_api.ib, "cancelOrder") as cancel:
            asyncio.run(orders_api.cancel_order(9, FakeRequest()))
        cancel.assert_called_once_with(self.trade.order)

    def test_cancel_unknown_or_finished_order(self):
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(orders_api.cancel_order(10, FakeRequest()))
        self.assertEqual(caught.exception.status_code, 404)
        self.trade.orderStatus.status = "Filled"
        with self.assertRaises(HTTPException):
            asyncio.run(orders_api.cancel_order(9, FakeRequest()))

    def change(self, token, quantity=8, limit_price=41.0):
        return orders_api.ModifyOrderRequest(quantity=quantity, limit_price=limit_price, confirmation_token=token)

    def test_modify_needs_a_preview_of_the_new_order(self):
        token = orders_api.confirmation_tokens.issue(1, {"action": "BUY", "quantity": 8, "order_type": "LMT", "limit_price": 41.0}, orders_api.time.monotonic())
        with mock.patch.object(orders_api, "checked_order", return_value=OK_CHECK), \
                mock.patch.object(orders_api.ib, "placeOrder") as place:
            asyncio.run(orders_api.modify_order(9, self.change(token), FakeRequest()))
        place.assert_called_once_with(self.trade.contract, self.trade.order)
        self.assertEqual((self.trade.order.totalQuantity, self.trade.order.lmtPrice), (8, 41.0))

    def test_modify_with_token_for_other_numbers_is_refused(self):
        token = orders_api.confirmation_tokens.issue(1, {"action": "BUY", "quantity": 8, "order_type": "LMT", "limit_price": 41.0}, orders_api.time.monotonic())
        with mock.patch.object(orders_api.ib, "placeOrder") as place, self.assertRaises(HTTPException) as caught:
            asyncio.run(orders_api.modify_order(9, self.change(token, quantity=50), FakeRequest()))
        self.assertIn("changed", caught.exception.detail)
        place.assert_not_called()
        self.assertEqual(self.trade.order.totalQuantity, 5)

    def test_modify_refused_by_checks(self):
        token = orders_api.confirmation_tokens.issue(1, {"action": "BUY", "quantity": 8, "order_type": "LMT", "limit_price": 41.0}, orders_api.time.monotonic())
        refused = {"problems": ["The order is worth about 20,000.00 in the account's currency, above the 10,000 limit (MAX_ORDER_VALUE)."], "contract": None}
        with mock.patch.object(orders_api, "checked_order", return_value=refused), \
                mock.patch.object(orders_api.ib, "placeOrder") as place, self.assertRaises(HTTPException):
            asyncio.run(orders_api.modify_order(9, self.change(token), FakeRequest()))
        place.assert_not_called()


class ChangeTypeAndTifTest(unittest.TestCase):
    """#159: order type and time in force can change; IBKR refuses some changes in place (it
    rejected market -> limit with error 329 on the paper account), so those are cancelled and
    placed again."""

    def setUp(self):
        self.trade = open_limit_order()
        self.trade.order.orderType, self.trade.order.lmtPrice = "MKT", 0.0  # a market order now
        for p in [
            mock.patch.object(orders_api.ib, "openTrades", return_value=[self.trade]),
            mock.patch.object(orders_api, "settled", side_effect=lambda trade, waiting: orders_api.trade_summary(trade)),
            mock.patch.object(orders_api, "checked_order", return_value=OK_CHECK),
            mock.patch.object(orders_api, "MODIFY_CHECK_S", 0.2),
        ]:
            p.start()
            self.addCleanup(p.stop)

    def to_limit(self, tif="GTC"):
        new = {"action": "BUY", "quantity": 5, "order_type": "LMT", "limit_price": 41.0, "tif": tif}
        token = orders_api.confirmation_tokens.issue(1, new, orders_api.time.monotonic())
        return orders_api.ModifyOrderRequest(quantity=5, limit_price=41.0, order_type="LMT", tif=tif, confirmation_token=token)

    def test_accepted_in_place(self):
        with mock.patch.object(orders_api.ib, "placeOrder") as place, mock.patch.object(orders_api.ib, "cancelOrder") as cancel:
            result = asyncio.run(orders_api.modify_order(9, self.to_limit(), FakeRequest()))
        place.assert_called_once()
        cancel.assert_not_called()
        self.assertEqual((self.trade.order.orderType, self.trade.order.lmtPrice, self.trade.order.tif), ("LMT", 41.0, "GTC"))
        self.assertNotIn("replaced", result)

    def test_refused_change_is_cancelled_and_replaced(self):
        replacement = open_limit_order("PreSubmitted")
        replacement.order.orderId = 10

        def place(contract, order):
            if order is self.trade.order:  # the change: IBKR refuses it
                self.trade.log.append(TradeLogEntry(time=None, status="ValidationError", errorCode=329,
                                                    message="Order modify failed. Cannot change to the new order type.LMT"))
                return self.trade
            self.assertEqual((order.orderType, order.lmtPrice, order.tif), ("LMT", 41.0, "GTC"))
            return replacement

        def cancel(order):
            self.trade.orderStatus.status = "Cancelled"

        with mock.patch.object(orders_api.ib, "placeOrder", side_effect=place), \
                mock.patch.object(orders_api.ib, "cancelOrder", side_effect=cancel) as cancelled:
            result = asyncio.run(orders_api.modify_order(9, self.to_limit(), FakeRequest()))
        cancelled.assert_called_once()
        self.assertEqual(result["order_id"], 10)
        self.assertEqual(result["replaced"]["order_id"], 9)
        self.assertIn("Cannot change to the new order type", result["replaced"]["reason"])
        self.assertEqual(self.trade.order.orderType, "MKT")  # our copy of the original is put back

    def test_partly_filled_order_is_not_replaced(self):
        self.trade.orderStatus.filled = 2

        def place(contract, order):
            self.trade.log.append(TradeLogEntry(time=None, status="ValidationError", errorCode=329, message="Cannot change"))
            return self.trade

        with mock.patch.object(orders_api.ib, "placeOrder", side_effect=place), \
                mock.patch.object(orders_api.ib, "cancelOrder") as cancel, self.assertRaises(HTTPException) as caught:
            asyncio.run(orders_api.modify_order(9, self.to_limit(), FakeRequest()))
        cancel.assert_not_called()
        self.assertIn("already filled", caught.exception.detail)

    def test_market_closed_warning_is_not_a_rejection(self):
        def place(contract, order):
            self.trade.log.append(TradeLogEntry(time=None, status="PreSubmitted", errorCode=399,
                                                message="Your order will not be placed at the exchange until 09:30"))
            return self.trade

        with mock.patch.object(orders_api.ib, "placeOrder", side_effect=place), mock.patch.object(orders_api.ib, "cancelOrder") as cancel:
            result = asyncio.run(orders_api.modify_order(9, self.to_limit(), FakeRequest()))
        cancel.assert_not_called()
        self.assertEqual(result["order_id"], 9)

    def test_token_covers_time_in_force(self):
        new = {"action": "BUY", "quantity": 5, "order_type": "LMT", "limit_price": 41.0, "tif": "DAY"}
        token = orders_api.confirmation_tokens.issue(1, new, orders_api.time.monotonic())
        change = orders_api.ModifyOrderRequest(quantity=5, limit_price=41.0, order_type="LMT", tif="GTC", confirmation_token=token)
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(orders_api.modify_order(9, change, FakeRequest()))
        self.assertIn("changed", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
