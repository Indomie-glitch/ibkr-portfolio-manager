"""Exchange rates when IB's ledger has none (#270): an SGD account with no USD balance."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from ib_async import AccountValue, Contract

import cache
import fx
from routers import positions as positions_api
from routers import trading as orders_api


def run(coro):
    return asyncio.run(coro)


def fake(value):
    """A rate source that answers `value` (or raises it, if it's an exception)."""
    async def source(currency, base):
        if isinstance(value, Exception):
            raise value
        return value
    return mock.AsyncMock(side_effect=source)


def ledger(base, rates):
    """accountSummary rows: the account's totals plus an exchange rate row per currency in `rates`."""
    rows = [AccountValue("DU1", tag, str(value), base, "") for tag, value in
            (("NetLiquidation", 100000), ("TotalCashValue", 90000), ("GrossPositionValue", 10000), ("BuyingPower", 400000))]
    rows += [AccountValue("DU1", "$LEDGER-ExchangeRate", str(rate), cur, "") for cur, rate in rates.items()]
    return rows


class FxTestCase(unittest.TestCase):
    def setUp(self):
        cache._entries.clear()
        cache._locks.clear()


class RateTest(FxTestCase):
    def test_the_base_currency_is_one(self):
        self.assertEqual(run(fx.rate_to_base("SGD", "SGD")), 1.0)

    def test_the_ledger_rate_is_used_without_any_lookup(self):
        with mock.patch.object(fx, "ib_rate", fake(9.9)) as ib_source, mock.patch.object(fx, "yahoo_rate", fake(9.9)) as yahoo_source:
            self.assertEqual(run(fx.rate_to_base("USD", "AUD", {"USD": 1.52})), 1.52)
        ib_source.assert_not_called()
        yahoo_source.assert_not_called()

    def test_a_missing_ledger_rate_comes_from_ib(self):
        with mock.patch.object(fx, "ib_rate", fake(1.35)), mock.patch.object(fx, "yahoo_rate", fake(9.9)) as yahoo_source:
            self.assertEqual(run(fx.rate_to_base("USD", "SGD", {})), 1.35)
        yahoo_source.assert_not_called()

    def test_yahoo_is_next_when_ib_has_no_quote(self):
        for ib_answer in (None, RuntimeError("no market data subscription"), asyncio.TimeoutError()):
            with self.subTest(ib_answer=ib_answer):
                cache._entries.clear()
                with mock.patch.object(fx, "ib_rate", fake(ib_answer)), mock.patch.object(fx, "yahoo_rate", fake(1.34)):
                    self.assertEqual(run(fx.rate_to_base("USD", "SGD", {})), 1.34)

    def test_no_rate_anywhere_is_none(self):
        with mock.patch.object(fx, "ib_rate", fake(None)), mock.patch.object(fx, "yahoo_rate", fake(RuntimeError("down"))):
            self.assertIsNone(run(fx.rate_to_base("USD", "SGD", {})))

    def test_nonsense_rates_are_ignored(self):
        with mock.patch.object(fx, "ib_rate", fake(float("nan"))), mock.patch.object(fx, "yahoo_rate", fake(0)):
            self.assertIsNone(run(fx.rate_to_base("USD", "SGD", {})))

    def test_a_found_rate_is_reused_and_a_miss_is_not_retried_at_once(self):
        with mock.patch.object(fx, "ib_rate", fake(1.35)) as ib_source:
            run(fx.rate_to_base("USD", "SGD", {}))
            run(fx.rate_to_base("USD", "SGD", {}))
        self.assertEqual(ib_source.call_count, 1)
        with mock.patch.object(fx, "ib_rate", fake(None)) as ib_source, mock.patch.object(fx, "yahoo_rate", fake(None)):
            run(fx.rate_to_base("EUR", "SGD", {}))
            run(fx.rate_to_base("EUR", "SGD", {}))
        self.assertEqual(ib_source.call_count, 1)

    def test_fill_missing_only_looks_up_what_the_ledger_lacks(self):
        with mock.patch.object(fx, "ib_rate", fake(1.35)) as ib_source:
            rates = run(fx.fill_missing({"EUR": 1.5}, {"EUR", "USD", "SGD", None}, "SGD"))
        self.assertEqual(rates, {"EUR": 1.5, "USD": 1.35})
        ib_source.assert_called_once_with("USD", "SGD")

    def test_yahoo_pair_symbol(self):
        self.assertEqual(fx.pair_symbol("USD", "SGD"), "USDSGD=X")


class IbQuoteTest(FxTestCase):
    def quote(self, qualified, prices):
        """Patches IB: qualifyContractsAsync answers from `qualified`, tickers give `prices` in turn."""
        tickers = iter(prices)

        async def request(contract):
            return [SimpleNamespace(marketPrice=lambda: next(tickers))]

        return (mock.patch.object(fx.ib, "qualifyContractsAsync", mock.AsyncMock(side_effect=qualified)),
                mock.patch.object(fx.ib, "reqTickersAsync", side_effect=request))

    def test_a_pair_listed_the_same_way_round(self):
        qualify, tickers = self.quote([[object()]], [1.35])
        with qualify, tickers:
            self.assertEqual(run(fx.ib_rate("USD", "SGD")), 1.35)

    def test_a_pair_listed_the_other_way_round_is_inverted(self):
        # IB has AUD.USD but no USD.AUD
        qualify, tickers = self.quote([[], [object()]], [0.5])
        with qualify, tickers:
            self.assertEqual(run(fx.ib_rate("USD", "AUD")), 2.0)

    def test_no_quote_is_none(self):
        qualify, tickers = self.quote([[object()], [object()]], [float("nan"), float("nan")])
        with qualify, tickers:
            self.assertIsNone(run(fx.ib_rate("USD", "SGD")))


class SgdAccountTest(FxTestCase):
    """An SGD paper account with no USD cash, holding or buying a US stock."""

    def account(self, rates, held=("USD",)):
        portfolio = [SimpleNamespace(contract=Contract(conId=i, currency=cur), position=10) for i, cur in enumerate(held)]
        return (mock.patch.object(positions_api.ib, "accountSummaryAsync", mock.AsyncMock(return_value=ledger("SGD", rates))),
                mock.patch.object(positions_api.ib, "portfolio", return_value=portfolio))

    def test_account_fills_the_rate_for_a_held_currency(self):
        summary, portfolio = self.account({"SGD": 1})
        with summary, portfolio, mock.patch.object(fx, "ib_rate", fake(1.35)):
            result = run(positions_api.account())
        self.assertEqual(result["currency"], "SGD")
        self.assertEqual(result["fx_rates"], {"SGD": 1.0, "USD": 1.35})

    def test_account_leaves_an_unfindable_rate_out(self):
        summary, portfolio = self.account({"SGD": 1})
        with summary, portfolio, mock.patch.object(fx, "ib_rate", fake(None)), mock.patch.object(fx, "yahoo_rate", fake(None)):
            result = run(positions_api.account())
        self.assertNotIn("USD", result["fx_rates"])

    def checked(self):
        """checked_order for buying 10 AAPL (USD) at a limit of 200 on an SGD account that holds nothing."""
        contract = Contract(conId=265598, symbol="AAPL", secType="STK", currency="USD")
        order = orders_api.OrderRequest(con_id=265598, action="BUY", quantity=10, order_type="LMT", limit_price=200)
        summary, portfolio = self.account({"SGD": 1}, held=())
        with summary, portfolio, \
                mock.patch.object(orders_api, "get_contract_info", mock.AsyncMock(return_value=(contract, "APPLE INC"))), \
                mock.patch.object(orders_api.ib, "portfolio", return_value=[]), \
                mock.patch.object(orders_api.ib, "managedAccounts", return_value=["DU123"]):
            return run(orders_api.checked_order(order))

    def test_a_us_order_works_without_usd_cash(self):
        with mock.patch.object(fx, "ib_rate", fake(1.35)):
            checked = self.checked()
        self.assertEqual(checked["problems"], [])
        self.assertEqual(checked["value"], 2000)
        self.assertAlmostEqual(checked["value_base"], 2700)
        self.assertEqual(checked["base_currency"], "SGD")

    def test_the_order_limit_still_applies_in_the_base_currency(self):
        # 10,000 is the default MAX_ORDER_VALUE; 2000 USD x 8 = 16,000 SGD
        with mock.patch.object(fx, "ib_rate", fake(8)):
            checked = self.checked()
        self.assertEqual(len(checked["problems"]), 1)
        self.assertIn("above the", checked["problems"][0])

    def test_no_rate_anywhere_still_gives_the_old_error(self):
        with mock.patch.object(fx, "ib_rate", fake(None)), mock.patch.object(fx, "yahoo_rate", fake(None)):
            checked = self.checked()
        self.assertEqual(checked["problems"], ["The order's value can't be checked against the limit without an exchange rate."])
        self.assertIsNone(checked["value_base"])


class AudAccountTest(FxTestCase):
    """Nothing changes when the ledger already has the rate."""

    def test_account_with_a_ledger_rate_makes_no_lookups(self):
        portfolio = [SimpleNamespace(contract=Contract(conId=1, currency="USD"), position=10),
                     SimpleNamespace(contract=Contract(conId=2, currency="AUD"), position=10)]
        with mock.patch.object(positions_api.ib, "accountSummaryAsync", mock.AsyncMock(return_value=ledger("AUD", {"AUD": 1, "USD": 1.52}))), \
                mock.patch.object(positions_api.ib, "portfolio", return_value=portfolio), \
                mock.patch.object(fx, "ib_rate", fake(9.9)) as ib_source, mock.patch.object(fx, "yahoo_rate", fake(9.9)) as yahoo_source:
            result = run(positions_api.account())
        self.assertEqual(result["fx_rates"], {"AUD": 1.0, "USD": 1.52})
        ib_source.assert_not_called()
        yahoo_source.assert_not_called()


if __name__ == "__main__":
    unittest.main()
