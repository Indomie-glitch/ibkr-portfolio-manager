"""Tests for the borrowing safeguard maths and setting (#289)."""
import asyncio
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

    def test_two_buys_that_each_fit_but_together_borrow(self):
        # 10,000 AUD cash. The first buy (6,000 + 6 fee) fits. With it open, the second (6,000)
        # can't be covered: 10,000 - 6,006 = 3,994 left, so 2,012 would be borrowed
        cash = {"AUD": 10000}
        self.assertIsNone(b.borrow_needed("BUY", 6000, "AUD", cash, "AUD"))
        reserved = b.reserved_by_open_buys([("AUD", 6000)])
        self.assertEqual(reserved, {"AUD": 6006})
        borrow = b.borrow_needed("BUY", 6000, "AUD", cash, "AUD", reserved)
        self.assertEqual((borrow["amount"], borrow["available"], borrow["reserved"]), (2012, 3994, 6006))
        self.assertIn("3,994.00 AUD left after 6,006.00 AUD for your open buy orders", b.borrow_message(borrow, "AUD", True))

    def test_open_buys_are_counted_per_currency(self):
        # 3,000 USD cash, an open AUD buy and two open USD buys: only the USD ones count for USD
        cash = {"AUD": 50000, "USD": 3000}
        reserved = b.reserved_by_open_buys([("AUD", 9000), ("USD", 1000), ("USD", 1000)])
        self.assertEqual(reserved, {"AUD": 9009, "USD": 2012})
        self.assertIsNone(b.borrow_needed("BUY", 900, "USD", cash, "AUD", reserved))  # 906 <= 988
        borrow = b.borrow_needed("BUY", 1000, "USD", cash, "AUD", reserved)            # 1,006 > 988
        self.assertEqual((borrow["amount"], borrow["reason"]), (18, "currency"))

    def test_open_buys_using_all_the_cash(self):
        borrow = b.borrow_needed("BUY", 100, "USD", {"AUD": 9000, "USD": 500}, "AUD", {"USD": 800})
        self.assertEqual((borrow["amount"], borrow["available"], borrow["reserved"]), (106, 0, 500))

    def test_open_buys_in_the_base_currency_stop_a_convert_first_hint(self):
        # No USD, and the AUD is already spoken for: converting AUD isn't the advice, adding cash is
        borrow = b.borrow_needed("BUY", 100, "USD", {"AUD": 1000}, "AUD", {"AUD": 1000})
        self.assertEqual(borrow["reason"], "cash")

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


class CheckedOrderTests(unittest.TestCase):
    """The route: open orders (from this app, TWS or the phone) are taken off the cash (#289)."""

    def check(self, order, cash, open_trades, currency="AUD", price=100.0, allowed=False, replacing=None):
        from types import SimpleNamespace

        from ib_async import Contract, Order, OrderStatus, Trade
        from routers import trading as routes

        contract = Contract(conId=1, symbol="BHP", secType="STK", currency=currency)
        account = {"currency": "AUD", "fx_rates": {"AUD": 1.0, "USD": 1.5}, "cash_by_currency": cash}
        trades = [Trade(contract=Contract(conId=cid, symbol="X", secType="STK", currency=ccy),
                        order=Order(orderId=oid, action=action, totalQuantity=qty, orderType=kind, lmtPrice=limit),
                        orderStatus=OrderStatus(status="PreSubmitted")) for oid, cid, ccy, action, qty, kind, limit in open_trades]
        request = routes.OrderRequest(con_id=1, **order)
        # The 10,000 order limit stops a real order from reaching the not-enough-cash case, so lift it here
        status = {"can_trade": True, "reason": None, "max_order_value": 1e9, "account": "paper", "account_label": "Paper"}
        with mock.patch.object(routes, "get_contract_info", mock.AsyncMock(return_value=(contract, "BHP"))), \
                mock.patch.object(routes, "account", mock.AsyncMock(return_value=account)), \
                mock.patch.object(routes.ib, "portfolio", return_value=[]), \
                mock.patch.object(routes.ib, "openTrades", return_value=trades), \
                mock.patch.object(routes.ib, "reqAllOpenOrdersAsync", mock.AsyncMock(return_value=[])), \
                mock.patch.object(routes.ib, "isConnected", return_value=True), \
                mock.patch.object(routes.ib, "managedAccounts", return_value=["DU1"]), \
                mock.patch.object(routes.trading, "status", return_value=status), \
                mock.patch.object(routes.borrowing, "borrowing_allowed", return_value=allowed):
            return asyncio.run(routes.checked_order(request, replacing_order_id=replacing))

    LIMIT_BUY = {"action": "BUY", "quantity": 60, "order_type": "LMT", "limit_price": 100}

    def test_the_first_buy_fits_and_the_second_does_not(self):
        cash = {"AUD": 10000}
        self.assertEqual(self.check(self.LIMIT_BUY, cash, [])["problems"], [])
        # An open limit buy of 60 x 100 (a market order is valued at the last price seen)
        open_buy = [(5, 2, "AUD", "BUY", 60, "LMT", 100.0)]
        checked = self.check(self.LIMIT_BUY, cash, open_buy)
        self.assertEqual(checked["borrow"]["amount"], 2012)
        self.assertEqual(len(checked["problems"]), 1)
        self.assertIn("open buy orders", checked["problems"][0])

    def test_open_market_orders_use_the_last_price_seen(self):
        from routers import trading as routes
        routes.last_prices[2] = 100.0
        checked = self.check(self.LIMIT_BUY, {"AUD": 10000}, [(5, 2, "AUD", "BUY", 60, "MKT", 0.0)])
        self.assertEqual(checked["borrow"]["reserved"], 6006)

    def test_sells_and_other_currencies_do_not_use_up_the_cash(self):
        cash = {"AUD": 10000, "USD": 500}
        open_orders = [(5, 2, "AUD", "SELL", 60, "LMT", 100.0), (6, 3, "USD", "BUY", 100, "LMT", 100.0)]
        self.assertEqual(self.check(self.LIMIT_BUY, cash, open_orders)["problems"], [])

    def test_changing_an_open_order_does_not_count_the_old_one(self):
        cash = {"AUD": 10000}
        open_buy = [(5, 2, "AUD", "BUY", 60, "LMT", 100.0)]
        self.assertEqual(self.check(self.LIMIT_BUY, cash, open_buy, replacing=5)["problems"], [])

    def test_not_enough_cash_even_with_nothing_open(self):
        # 100 x 100 = 10,000 against 4,000 AUD in the account
        checked = self.check({"action": "BUY", "quantity": 100, "order_type": "LMT", "limit_price": 100}, {"AUD": 4000}, [])
        self.assertEqual((checked["borrow"]["amount"], checked["borrow"]["reason"]), (6010, "cash"))
        self.assertIn("Lower the quantity, or add cash first", checked["problems"][0])

    def test_with_borrowing_allowed_it_still_warns(self):
        open_buy = [(5, 2, "AUD", "BUY", 60, "LMT", 100.0)]
        checked = self.check(self.LIMIT_BUY, {"AUD": 10000}, open_buy, allowed=True)
        self.assertEqual(checked["problems"], [])
        self.assertFalse(checked["borrow"]["blocked"])
        self.assertIn("2,012.00 AUD", checked["borrow"]["message"])


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
