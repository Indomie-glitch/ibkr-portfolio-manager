import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from ib_async import Contract, Order, OrderStatus, Trade
from ib_async.objects import TradeLogEntry

from trading import orders_overview


def trade(con_id, symbol, perm_id, status="Submitted", order_type="LMT", tif="DAY", logged=True):
    order = Order(orderId=perm_id % 100, permId=perm_id, action="BUY", totalQuantity=10, orderType=order_type,
                  lmtPrice=150.0 if order_type == "LMT" else 0.0, tif=tif)
    log = [TradeLogEntry(time=datetime(2026, 10, 17, 2, 52, tzinfo=timezone.utc), status=status)] if logged else []
    return Trade(contract=Contract(conId=con_id, symbol=symbol, currency="AUD"), order=order,
                 orderStatus=OrderStatus(status=status), log=log)


def fill(perm_id, shares, price, commission, con_id=4, symbol="AAPL", side="BOT"):
    return SimpleNamespace(contract=Contract(conId=con_id, symbol=symbol, currency="USD"),
                           execution=SimpleNamespace(permId=perm_id, orderId=perm_id % 100, side=side, shares=shares, price=price,
                                                     time=datetime(2026, 10, 17, 3, 14, tzinfo=timezone.utc)),
                           commissionReport=SimpleNamespace(commission=commission))


class OrdersOverviewTest(unittest.TestCase):
    def test_sections(self):
        open_trades = [trade(1, "CBA", 101), trade(2, "BHP", 102, tif="GTC"),
                       trade(3, "XYZ", 103, status="Filled")]  # already done: not open
        completed = [trade(4, "AAPL", 104, status="Filled", logged=False),
                     trade(5, "CSL", 105, status="Cancelled", logged=False)]
        fills = [fill(104, 4, 339.0, 0.5), fill(104, 6, 340.0, 0.5),
                 fill(999, 3, 20.0, 1.0, con_id=7, symbol="WES", side="SLD")]  # an order IB no longer lists
        result = orders_overview(open_trades, completed, fills, {1: "Commonwealth Bank"})

        self.assertEqual([r["symbol"] for r in result["open"]], ["CBA", "BHP"])
        cba = result["open"][0]
        self.assertEqual((cba["name"], cba["limit_price"], cba["tif"], cba["status"]), ("Commonwealth Bank", 150.0, "DAY", "Submitted"))
        self.assertEqual(result["open"][1]["tif"], "GTC")

        by_symbol = {r["symbol"]: r for r in result["filled_today"]}
        aapl = by_symbol["AAPL"]
        self.assertEqual((aapl["status"], aapl["filled"], aapl["commission"], aapl["order_type"]), ("Filled", 10, 1.0, "LMT"))
        self.assertAlmostEqual(aapl["avg_fill_price"], 339.6)
        self.assertIsNone(aapl["placed"])  # rebuilt from executions: when it was placed isn't known
        wes = by_symbol["WES"]
        self.assertEqual((wes["action"], wes["quantity"], wes["avg_fill_price"]), ("SELL", 3, 20.0))
        self.assertEqual([r["symbol"] for r in result["cancelled"]], ["CSL"])

    def test_partly_filled_order_stays_open(self):
        result = orders_overview([trade(1, "CBA", 101)], [], [fill(101, 4, 150.0, 0.2, con_id=1, symbol="CBA")], {})
        self.assertEqual(result["filled_today"], [])
        self.assertEqual(result["open"][0]["filled"], 4)


class PlacedTimeTest(unittest.TestCase):
    """#157: IBKR's lists have no placement time, so only orders the app placed itself show one."""

    def test_order_placed_through_the_app_keeps_its_time(self):
        placed_here = trade(1, "CBA", 101, status="Submitted")
        placed_here.log.insert(0, TradeLogEntry(time=datetime(2026, 10, 17, 2, 50, tzinfo=timezone.utc), status="PendingSubmit"))
        [row] = orders_overview([placed_here], [], [], {})["open"]
        self.assertEqual(row["placed"], "2026-10-17T02:50:00+00:00")

    def test_order_from_elsewhere_has_no_time(self):
        # First seen in IBKR's open order list: its log starts with a status update, not the send
        [row] = orders_overview([trade(2, "TLS", 102, status="PreSubmitted")], [], [], {})["open"]
        self.assertIsNone(row["placed"])
        [row] = orders_overview([trade(3, "BHP", 103, logged=False)], [], [], {})["open"]
        self.assertIsNone(row["placed"])


if __name__ == "__main__":
    unittest.main()
