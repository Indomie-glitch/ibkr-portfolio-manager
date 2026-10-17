import asyncio
import unittest
from unittest import mock

from ib_async import Contract, OrderStatus, Trade

import main
from trading import build_order


def trade(status):
    t = Trade(contract=Contract(conId=1, symbol="BHP"),
              order=build_order({"action": "BUY", "quantity": 5, "order_type": "MKT", "limit_price": None}),
              orderStatus=OrderStatus(status=status, filled=0, remaining=5))
    t.order.orderId = 3
    return t


class FakeRequest:
    def __init__(self):
        self.closed = False

    async def is_disconnected(self):
        return self.closed


async def read_stream(request, updates):
    response = await main.order_stream(request)
    chunks = []
    body = response.body_iterator
    chunks.append(await body.__anext__())  # the opening snapshot
    for status in updates:
        main.publish_trade(trade(status))
        chunks.append(await body.__anext__())
    request.closed = True
    await body.aclose()
    return chunks


class OrderStreamTest(unittest.TestCase):
    def test_snapshot_then_updates(self):
        request = FakeRequest()
        with mock.patch.object(main.ib, "trades", return_value=[trade("Submitted")]):
            chunks = asyncio.run(read_stream(request, ["Filled", "Cancelled"]))
        self.assertTrue(chunks[0].startswith("event: orders\n"))
        self.assertIn('"status": "Submitted"', chunks[0])
        self.assertTrue(chunks[1].startswith("event: order\n") and '"status": "Filled"' in chunks[1])
        self.assertIn('"status": "Cancelled"', chunks[2])
        self.assertEqual(main.order_listeners, set())  # closed streams stop listening

    def test_publish_without_listeners_does_nothing(self):
        main.publish_trade(trade("Filled"))  # no error, nothing queued
        self.assertEqual(main.order_listeners, set())


if __name__ == "__main__":
    unittest.main()
