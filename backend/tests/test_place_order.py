"""POST /orders sends the chosen time in force, and the confirmation is bound to it (#158)."""
import asyncio
import unittest
from unittest import mock

from fastapi import HTTPException
from ib_async import Contract, OrderStatus, Trade

from routers import trading as orders_api


class FakeRequest:
    headers = {}


ORDER = {"con_id": 1, "action": "BUY", "quantity": 5, "order_type": "LMT", "limit_price": 40.0}


class PlaceOrderTest(unittest.TestCase):
    def setUp(self):
        self.sent = []

        def place(contract, order):
            self.sent.append(order)
            order.orderId = 50
            return Trade(contract=contract, order=order, orderStatus=OrderStatus(status="PreSubmitted"))

        for p in [
            mock.patch.object(orders_api, "checked_order", return_value={"problems": [], "contract": Contract(conId=1, symbol="BHP")}),
            mock.patch.object(orders_api.ib, "placeOrder", side_effect=place),
        ]:
            p.start()
            self.addCleanup(p.stop)

    def place(self, confirmed_tif, sent_tif):
        token = orders_api.confirmation_tokens.issue(1, {**ORDER, "tif": confirmed_tif}, orders_api.time.monotonic())
        request = orders_api.PlaceOrderRequest(**ORDER, tif=sent_tif, confirmation_token=token)
        return asyncio.run(orders_api.place_order(request, FakeRequest()))

    def test_gtc_order_is_sent_as_gtc(self):
        result = self.place("GTC", "GTC")
        self.assertEqual(self.sent[0].tif, "GTC")
        self.assertEqual(result["tif"], "GTC")

    def test_day_is_the_default(self):
        token = orders_api.confirmation_tokens.issue(1, ORDER, orders_api.time.monotonic())
        asyncio.run(orders_api.place_order(orders_api.PlaceOrderRequest(**ORDER, confirmation_token=token), FakeRequest()))
        self.assertEqual(self.sent[0].tif, "DAY")

    def test_a_day_confirmation_cannot_send_gtc(self):
        with self.assertRaises(HTTPException) as caught:
            self.place("DAY", "GTC")
        self.assertIn("changed", caught.exception.detail)
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
