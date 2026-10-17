import asyncio
import unittest
from unittest import mock

from ib_async import Contract, OrderStatus, Trade

from routers import trading as orders_api
import web
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
    response = await orders_api.order_stream(request)
    chunks = []
    body = response.body_iterator
    chunks.append(await body.__anext__())  # the opening snapshot
    for status in updates:
        orders_api.publish_trade(trade(status))
        chunks.append(await body.__anext__())
    request.closed = True
    await body.aclose()
    return chunks


class OrderStreamTest(unittest.TestCase):
    def test_snapshot_then_updates(self):
        request = FakeRequest()
        with mock.patch.object(orders_api.ib, "trades", return_value=[trade("Submitted")]):
            chunks = asyncio.run(read_stream(request, ["Filled", "Cancelled"]))
        self.assertTrue(chunks[0].startswith("event: orders\n"))
        self.assertIn('"status": "Submitted"', chunks[0])
        self.assertTrue(chunks[1].startswith("event: order\n") and '"status": "Filled"' in chunks[1])
        self.assertIn('"status": "Cancelled"', chunks[2])
        self.assertEqual(orders_api.order_listeners, set())  # closed streams stop listening

    def test_publish_without_listeners_does_nothing(self):
        orders_api.publish_trade(trade("Filled"))  # no error, nothing queued
        self.assertEqual(orders_api.order_listeners, set())


class StreamStopsWithServerTest(unittest.TestCase):
    """#168: a live stream kept uvicorn's reload / quit waiting forever."""

    def test_stream_ends_when_the_server_is_stopping(self):
        async def run():
            web.stopping = asyncio.Event()  # a fresh one for this event loop
            with mock.patch.object(orders_api.ib, "trades", return_value=[]), \
                    mock.patch.object(orders_api, "STREAM_HEARTBEAT_S", 60):
                response = await orders_api.order_stream(FakeRequest())
                body = response.body_iterator
                await body.__anext__()  # the opening snapshot
                waiting = asyncio.ensure_future(body.__anext__())
                await asyncio.sleep(0.05)
                web.stopping.set()  # what SIGTERM / SIGINT do
                with self.assertRaises(StopAsyncIteration):
                    await asyncio.wait_for(waiting, timeout=1)  # ends at once, not after the 60 s heartbeat
            self.assertEqual(orders_api.order_listeners, set())

        try:
            asyncio.run(run())
        finally:
            web.stopping = asyncio.Event()

    def test_stop_signal_sets_the_flag_and_runs_the_previous_handler(self):
        import signal
        calls = []
        original = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, lambda signum, frame: calls.append(signum))  # stands in for uvicorn's

        async def run():
            web.stopping = asyncio.Event()
            web.end_streams_on_stop()
            signal.raise_signal(signal.SIGTERM)
            await asyncio.sleep(0.05)
            return web.stopping.is_set()

        try:
            self.assertTrue(asyncio.run(run()))
            self.assertEqual(calls, [signal.SIGTERM])
        finally:
            signal.signal(signal.SIGTERM, original)
            signal.signal(signal.SIGINT, signal.default_int_handler)
            web.stopping = asyncio.Event()


if __name__ == "__main__":
    unittest.main()
