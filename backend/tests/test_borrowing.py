"""Tests for the borrowing safeguard maths and setting (#289)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PORTFOLIO_DATA_DIR", tempfile.mkdtemp())
import borrowing as b  # noqa: E402


class BorrowNeededTests(unittest.TestCase):
    def test_a_buy_within_cash_in_the_same_currency_is_fine(self):
        # 1,000 + the A$6 minimum fee, against 5,000 AUD
        self.assertIsNone(b.borrow_needed("BUY", 1000, "AUD", {"AUD": 5000}, "AUD"))

    def test_not_enough_cash_borrows_the_shortfall(self):
        # 10,000 + 10 fees (0.1%) against 4,000 AUD
        borrow = b.borrow_needed("BUY", 10000, "AUD", {"AUD": 4000}, "AUD")
        self.assertEqual((borrow["amount"], borrow["currency"], borrow["reason"]), (6010, "AUD", "cash"))
        self.assertIn("Lower the quantity, or add cash first", b.borrow_message(borrow, "AUD", True))

    def test_fees_alone_can_tip_it_over(self):
        # 1,000 + A$6 against exactly 1,000
        self.assertEqual(b.borrow_needed("BUY", 1000, "AUD", {"AUD": 1000}, "AUD")["amount"], 6)

    def test_wrong_currency_borrows_all_of_it(self):
        # Plenty of SGD but no USD: IBKR doesn't convert, so all 2,000 + 6 is a USD loan
        borrow = b.borrow_needed("BUY", 2000, "USD", {"SGD": 50000}, "SGD")
        self.assertEqual((borrow["amount"], borrow["currency"], borrow["reason"]), (2006, "USD", "currency"))
        message = b.borrow_message(borrow, "SGD", True)
        self.assertIn("no USD cash", message)
        self.assertIn("convert SGD to USD in IBKR first", message)

    def test_some_usd_cash_borrows_the_rest(self):
        borrow = b.borrow_needed("BUY", 2000, "USD", {"AUD": 9000, "USD": 500}, "AUD")
        self.assertEqual((borrow["amount"], borrow["reason"]), (1506, "currency"))
        self.assertIn("only 500.00 USD in USD cash", b.borrow_message(borrow, "AUD", True))

    def test_a_negative_balance_counts_as_no_cash(self):
        borrow = b.borrow_needed("BUY", 100, "USD", {"AUD": 9000, "USD": -300}, "AUD")
        self.assertEqual(borrow["amount"], 106)

    def test_sells_are_never_checked(self):
        self.assertIsNone(b.borrow_needed("SELL", 1e9, "USD", {}, "AUD"))

    def test_allowed_borrowing_still_warns(self):
        borrow = b.borrow_needed("BUY", 2000, "USD", {"SGD": 50000}, "SGD")
        message = b.borrow_message(borrow, "SGD", False)
        self.assertIn("2,006.00 USD", message)
        self.assertIn("interest", message)

    def test_negative_balances_for_overview(self):
        self.assertEqual(b.negative_balances({"AUD": 100, "USD": -1234.567, "SGD": -0.001}),
                         [{"currency": "USD", "amount": 1234.57}])


class SettingTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patcher = mock.patch.object(b, "SETTINGS_FILE", Path(self.dir.name) / "trading_settings.json")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_blocked_by_default_and_per_account(self):
        with mock.patch.object(b.config, "IN_APP", False):
            self.assertFalse(b.borrowing_allowed("DU1"))
            b.save_allowed("DU1", True)
            self.assertTrue(b.borrowing_allowed("DU1"))
            self.assertFalse(b.borrowing_allowed("DU2"))
            self.assertFalse(b.borrowing_allowed(None))
            b.save_allowed("DU1", False)
            self.assertFalse(b.borrowing_allowed("DU1"))

    def test_the_app_uses_what_it_was_sent(self):
        with mock.patch.object(b.config, "IN_APP", True), mock.patch.dict(b.config.SETTINGS, {}, clear=True):
            self.assertFalse(b.borrowing_allowed("DU1"))
            b.config.SETTINGS["allow_borrowing"] = {"DU1": True}
            self.assertTrue(b.borrowing_allowed("DU1"))
            self.assertFalse(b.borrowing_allowed("DU2"))

    def test_a_damaged_file_means_blocked(self):
        b.SETTINGS_FILE.write_text("not json")
        with mock.patch.object(b.config, "IN_APP", False):
            self.assertFalse(b.borrowing_allowed("DU1"))


class RouteTests(SettingTests):
    """POST /trading/borrowing: development only, and switching off needs BORROW typed."""

    def change(self, body, in_app=False):
        from fastapi import HTTPException
        from routers import trading as routes
        request = mock.Mock(headers={})
        with mock.patch.object(routes.config, "IN_APP", in_app), mock.patch.object(b.config, "IN_APP", in_app), \
                mock.patch.object(routes, "account_id", return_value="DU1"):
            try:
                return routes.change_borrowing(routes.BorrowingChange(**body), request)
            except HTTPException as exc:
                return exc.status_code

    def test_switching_off_needs_borrow_typed(self):
        self.assertEqual(self.change({"block": False}), 400)
        self.assertEqual(self.change({"block": False, "confirm": "borrow"}), 400)
        self.assertEqual(self.change({"block": False, "confirm": "BORROW"})["block"], False)
        # Back on needs nothing typed
        self.assertEqual(self.change({"block": True})["block"], True)

    def test_refused_in_the_app(self):
        self.assertEqual(self.change({"block": False, "confirm": "BORROW"}, in_app=True), 403)


if __name__ == "__main__":
    unittest.main()
