"""GET /orders with mocked IB calls (#155: it returned 500 as soon as there was an order)."""
import asyncio
import unittest
from unittest import mock

from fastapi import HTTPException
from ib_async import Contract, Order, OrderStatus, Trade

from routers import trading as orders_api


def open_order():
    return Trade(contract=Contract(conId=265598, symbol="AAPL", currency="USD"),
                 order=Order(orderId=28, permId=45937529, action="BUY", totalQuantity=10, orderType="LMT", lmtPrice=342.76),
                 orderStatus=OrderStatus(status="PreSubmitted"))


async def returns(value):
    return value


class OrdersRouteTest(unittest.TestCase):
    def run_orders(self, open_trades=None, completed=None, executions=None):
        contract = Contract(conId=265598, symbol="AAPL")
        with mock.patch.object(orders_api.ib, "reqAllOpenOrdersAsync", return_value=open_trades or returns([open_order()])), \
                mock.patch.object(orders_api.ib, "reqCompletedOrdersAsync", return_value=completed or returns([])), \
                mock.patch.object(orders_api.ib, "reqExecutionsAsync", return_value=executions or returns([])), \
                mock.patch.object(orders_api, "get_contract_info", return_value=(contract, "APPLE INC")):
            return asyncio.run(orders_api.orders())

    def test_an_open_order_gets_its_company_name(self):
        # The cause of #155: names were built without the symbol display_name needs
        result = self.run_orders()
        [row] = result["open"]
        self.assertEqual((row["symbol"], row["name"], row["status"]), ("AAPL", "Apple Inc", "PreSubmitted"))
        self.assertEqual((result["filled_today"], result["cancelled"]), ([], []))

    def test_no_orders_at_all(self):
        result = self.run_orders(open_trades=returns([]))
        self.assertEqual(result, {"open": [], "filled_today": [], "cancelled": []})

    def test_a_failing_ib_call_is_a_readable_502(self):
        async def fails():
            raise RuntimeError("Error 321, API interface is not available")
        with self.assertRaises(HTTPException) as caught:
            self.run_orders(completed=fails())
        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("today's completed orders", caught.exception.detail)
        self.assertIn("Error 321", caught.exception.detail)

    def test_a_timeout_is_a_readable_502(self):
        async def slow():
            raise asyncio.TimeoutError
        with self.assertRaises(HTTPException) as caught:
            self.run_orders(executions=slow())
        self.assertIn("today's executions in time", caught.exception.detail)

    def test_names_skip_unknown_contracts(self):
        self.assertEqual(orders_api.order_names([(Contract(conId=1, symbol="KO"), "COCA-COLA CO/THE"), (None, None),
                                                 (Contract(conId=2, symbol="X"), "")]),
                         {1: "The Coca-Cola Co"})


if __name__ == "__main__":
    unittest.main()
