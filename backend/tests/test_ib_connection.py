"""Tests for the connection status: client ID clashes, and connected but not answering (#285)."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ib_connection  # noqa: E402
import ib_core  # noqa: E402
from ib_connection import ConnectionStatus  # noqa: E402
from routers import app as app_routes  # noqa: E402


class NotAnsweringTests(unittest.TestCase):
    def test_one_slow_check_is_not_enough(self):
        status = ConnectionStatus(1)
        status.check_failed()
        self.assertIsNone(status.not_answering())
        status.check_failed()
        self.assertEqual(status.not_answering()["problem"], "not_answering")
        status.answering()
        self.assertIsNone(status.not_answering())
        # The count starts again after an answer
        status.check_failed()
        self.assertIsNone(status.not_answering())

    def test_ibkr_connectivity_errors(self):
        status = ConnectionStatus(1)
        status.on_ib_error(1100)
        self.assertEqual(status.not_answering()["problem"], "not_answering")
        status.on_ib_error(1102)
        self.assertIsNone(status.not_answering())
        status.on_ib_error(2110)
        self.assertIsNotNone(status.not_answering())
        status.connected()  # a fresh connection starts clean
        self.assertIsNone(status.not_answering())

    def test_client_id_clash_unchanged(self):
        status = ConnectionStatus(1)
        status.on_ib_error(326)
        status.failed(OSError())
        self.assertEqual((status.problem, status.client_id), ("client_id_in_use", 2))


class FakeIB:
    """Positions and open orders that answer, or never do (a session taken over elsewhere)."""

    def __init__(self, answers):
        self.answers = answers

    async def _request(self):
        if not self.answers:
            await asyncio.sleep(10)
        return []

    def reqPositionsAsync(self):
        return self._request()

    def reqAllOpenOrdersAsync(self):
        return self._request()

    def isConnected(self):
        return True


class CheckTests(unittest.TestCase):
    def check(self, fake, status):
        with mock.patch.object(ib_core, "ib", fake), mock.patch.object(ib_core, "connection", status):
            return asyncio.run(ib_core.check_answering(timeout=0.01))

    def test_connected_but_not_answering_shows_on_health(self):
        status = ConnectionStatus(1)
        silent = FakeIB(answers=False)
        for _ in range(ib_connection.CHECKS_BEFORE_NOT_ANSWERING):
            self.assertFalse(self.check(silent, status))
        with mock.patch.object(app_routes, "ib", silent), mock.patch.object(app_routes, "connection", status):
            health = app_routes.health()
        self.assertTrue(health["connected"])
        self.assertEqual(health["problem"], "not_answering")
        self.assertIn("port", health)

        # IBKR answers again: back to plain connected
        self.assertTrue(self.check(FakeIB(answers=True), status))
        with mock.patch.object(app_routes, "ib", silent), mock.patch.object(app_routes, "connection", status):
            self.assertEqual(app_routes.health(), {"connected": True})


if __name__ == "__main__":
    unittest.main()
