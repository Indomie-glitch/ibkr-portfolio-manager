"""Tests for index members: reading the holdings files, weekly refresh with fallback to the last
good copy, market caps, Yahoo sectors, and which indexes a stock is in (#109, #110)."""
import asyncio
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PORTFOLIO_DATA_DIR", tempfile.mkdtemp())
from openpyxl import Workbook  # noqa: E402

import constituents as c  # noqa: E402
import yahoo  # noqa: E402
from routers import indices as routes  # noqa: E402

NOW = datetime(2026, 10, 23, 1, 0, tzinfo=timezone.utc)


def ssga_file(header, rows, as_of="As of 21-Oct-2026"):
    """A State Street holdings .xlsx: fund details, then the header row, the holdings, a note."""
    book = Workbook()
    sheet = book.active
    sheet.append(["Fund Name:", "SPDR test fund"])
    sheet.append(["Ticker Symbol:", "TST"])
    sheet.append(["Holdings:", as_of])
    sheet.append([])
    sheet.append(header)
    for row in rows:
        sheet.append(row)
    sheet.append([])
    sheet.append(["Holdings are subject to change."])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


US_HEADER = ["Name", "Ticker", "Identifier", "SEDOL", "Weight", "Sector", "Shares Held", "Local Currency"]
AU_HEADER = ["ISIN", "SEDOL", "Ticker", "Name", "Local Currency", "Number of Shares", "Weight (%)",
             "Trade Country Name", "Local Price", "Sector Classification", "Industry Classification"]


def us_row(name, ticker, weight):
    return [name, ticker, "000000000", "0000000", weight, "-", "1000", "USD"]


def au_row(ticker, name, weight, sector="Materials", industry="Metals & Mining"):
    return ["AU0000000000", "0000000", ticker, name, "AUD", "1000", weight, "Australia", "10", sector, industry]


def ishares_file(rows, as_of="21/Oct/2026"):
    lines = [f'\ufeffFund Holdings as of,"{as_of}"', " ",
             "Ticker,Name,Sector,Asset Class,Market Value,Weight (%),Notional Value,Shares,Price"]
    lines += [",".join(f'"{v}"' for v in row) for row in rows]
    lines += [" ", '"The content contained herein is owned or licensed by BlackRock."']
    return "\n".join(lines).encode()


def ishares_row(ticker, name, weight, asset_class="Equity", sector="Information Technology"):
    return [ticker, name, sector, asset_class, "1,000.00", weight, "1,000.00", "10.00", "100.00"]


# Two-member indexes for the refresh tests: every index needs at least min_count members
def small_indexes():
    return {
        "sp500": {**c.INDEXES["sp500"], "min_count": 2},
        "asx20": {**c.INDEXES["asx20"], "min_count": 2},
    }


SP500 = ssga_file(US_HEADER, [us_row("APPLE INC", "AAPL", "6.0"), us_row("ALLSTATE CORP", "ALL", "2.0"),
                              us_row("US DOLLAR", "-", "0.5")])
ASX20 = ishares_file([ishares_row("BHP", "BHP GROUP LTD", "12.00", sector="Materials"),
                      ishares_row("ALL", "ARISTOCRAT LEISURE LTD", "4.00", sector="Consumer Discretionary"),
                      ishares_row("AUD", "AUD CASH", "0.10", asset_class="Cash")])


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patcher = mock.patch.object(c, "DB_PATH", Path(self.dir.name) / "indices.sqlite")
        patcher.start()
        self.addCleanup(patcher.stop)
        indexes = mock.patch.object(c, "INDEXES", small_indexes())
        indexes.start()
        self.addCleanup(indexes.stop)

    def download(self, files):
        """A fake download serving each index's file by URL; a missing one raises."""
        by_url = {c.INDEXES[i]["url"]: content for i, content in files.items()}

        def fetch(url):
            if url not in by_url:
                raise OSError("connection refused")
            return by_url[url]
        return fetch

    def refresh_indexes(self, files, now=NOW):
        return asyncio.run(c.refresh_indexes(now, self.download(files)))

    def index(self, index_id):
        return next(i for i in c.status()["indexes"] if i["id"] == index_id)


class SymbolTests(unittest.TestCase):
    def test_ib_form(self):
        self.assertEqual(c.clean_symbol("BRK.B"), "BRK B")
        self.assertEqual(c.clean_symbol("BRK/B"), "BRK B")
        self.assertEqual(c.clean_symbol("BHP-AU"), "BHP")
        self.assertEqual(c.clean_symbol("360-AU"), "360")  # Life360: ASX tickers can start with a digit
        self.assertEqual(c.clean_symbol(" googl "), "GOOGL")

    def test_cash_and_codes_are_not_stocks(self):
        for raw in ["-", "", None, "954FAV004", "2602335D", "ABR^D", "US DOLLAR"]:
            self.assertIsNone(c.clean_symbol(raw), raw)


class ParseTests(unittest.TestCase):
    def test_us_ssga_file(self):
        content = ssga_file(US_HEADER, [us_row("APPLE INC", "AAPL", "6.0"), us_row("BERKSHIRE HATHAWAY INC CL B", "BRK.B", "3.0"),
                                        us_row("US DOLLAR", "-", "0.3"), us_row("TPG INC", "2602335D", "0.000003")])
        as_of, rows = c.parse_ssga(content)
        self.assertEqual(as_of, "2026-10-21")
        members = c.members_from(rows)
        self.assertEqual([m["symbol"] for m in members], ["AAPL", "BRK B"])
        # Cash left out, so the stocks are rescaled to add up to 100
        self.assertAlmostEqual(members[0]["weight"], 6 / 9 * 100)
        self.assertEqual([m["rank"] for m in members], [1, 2])
        self.assertIsNone(members[0]["fund_sector"])  # US files have "-" for the sector

    def test_australian_ssga_file(self):
        content = ssga_file(AU_HEADER, [au_row("CBA-AU", "Cmnwlth Bk Of Aust", "4.0", "Financials", "Banks"),
                                        au_row("BHP-AU", "Bhp Group Ltd", "6.0"),
                                        au_row("954FAV004", "Avz Minerals Limited", "0.01")])
        _, rows = c.parse_ssga(content)
        members = c.members_from(rows)
        self.assertEqual([(m["symbol"], m["rank"]) for m in members], [("BHP", 1), ("CBA", 2)])
        self.assertEqual((members[1]["fund_sector"], members[1]["fund_industry"]), ("Financials", "Banks"))
        self.assertAlmostEqual(sum(m["weight"] for m in members), 100)

    def test_ishares_file(self):
        as_of, rows = c.parse_ishares(ASX20.decode())
        self.assertEqual(as_of, "2026-10-21")
        self.assertEqual([r["symbol"] for r in rows], ["BHP", "ALL"])  # cash and the disclaimer left out
        self.assertEqual(rows[0]["fund_sector"], "Materials")

    def test_dates_in_either_form(self):
        self.assertEqual(c._as_of("21-Oct-2026"), "2026-10-21")
        self.assertEqual(c._as_of("As of 3/Feb/2027"), "2027-02-03")

    def test_not_a_holdings_file(self):
        with self.assertRaises(c.SourceError):
            c.parse_ishares("<!DOCTYPE html><html>")


class RefreshTests(StoreTestCase):
    def test_stores_members_and_their_date(self):
        self.assertEqual(self.refresh_indexes({"sp500": SP500, "asx20": ASX20}), 2)
        sp500 = self.index("sp500")
        self.assertEqual((sp500["count"], sp500["as_of"], sp500["stale"]), (2, "2026-10-21", False))
        self.assertEqual([m["symbol"] for m in c.members("sp500")["members"]], ["AAPL", "ALL"])
        self.assertEqual(c.members("asx20")["members"][0]["name"], "BHP Group Ltd")

    def test_too_few_members_is_a_failure(self):
        one_stock = ssga_file(US_HEADER, [us_row("APPLE INC", "AAPL", "6.0")])
        self.refresh_indexes({"sp500": one_stock, "asx20": ASX20})
        sp500 = self.index("sp500")
        self.assertEqual(sp500["count"], 0)
        self.assertIn("only 1 stocks", sp500["last_error"])

    def test_a_failed_download_keeps_the_last_copy_and_its_date(self):
        self.refresh_indexes({"sp500": SP500, "asx20": ASX20})
        later = NOW + timedelta(days=8)
        self.refresh_indexes({"asx20": ASX20}, now=later)  # the S&P 500 file is unavailable
        sp500 = self.index("sp500")
        self.assertEqual((sp500["count"], sp500["as_of"]), (2, "2026-10-21"))
        self.assertTrue(sp500["stale"])
        self.assertEqual(sp500["last_error"], "Couldn't load the SPY holdings file (OSError).")
        self.assertFalse(self.index("asx20")["stale"])
        # The stock still shows its indexes, marked stale
        self.assertTrue(c.indices_for("AAPL", "US")[0]["stale"])

    def test_weekly_and_retries_after_a_failure(self):
        self.refresh_indexes({"sp500": SP500, "asx20": ASX20})
        self.assertEqual(self.refresh_indexes({}, now=NOW + timedelta(days=6)), 0)  # not due: nothing fetched
        self.refresh_indexes({}, now=NOW + timedelta(days=7))  # due, both fail
        self.assertEqual(self.refresh_indexes({"sp500": SP500, "asx20": ASX20}, now=NOW + timedelta(days=7, hours=1)), 0)
        self.assertEqual(self.refresh_indexes({"sp500": SP500, "asx20": ASX20}, now=NOW + timedelta(days=7, hours=6)), 2)
        self.assertFalse(self.index("sp500")["stale"])


class MarketCapTests(StoreTestCase):
    def test_caps_and_better_names(self):
        self.refresh_indexes({"sp500": SP500, "asx20": ASX20})

        async def us():
            return {"AAPL": {"market_cap": 5e12, "name": None}, "MSFT": {"market_cap": 4e12, "name": None}}

        async def asx():
            return {"BHP": {"market_cap": 2.9e11, "name": "BHP Group Limited"}}
        asyncio.run(c.refresh_market_caps(NOW, us, asx, force=True))
        apple = c.members("sp500")["members"][0]
        self.assertEqual((apple["market_cap"], apple["name"]), (5e12, "Apple Inc"))
        bhp = c.members("asx20")["members"][0]
        self.assertEqual((bhp["market_cap"], bhp["name"]), (2.9e11, "BHP Group Limited"))

    def test_a_failure_keeps_the_last_caps(self):
        self.refresh_indexes({"sp500": SP500, "asx20": ASX20})

        async def us():
            return {"AAPL": {"market_cap": 5e12, "name": None}}

        async def down():
            raise OSError("timed out")
        asyncio.run(c.refresh_market_caps(NOW, us, us, force=True))
        asyncio.run(c.refresh_market_caps(NOW + timedelta(days=8), down, down))
        self.assertEqual(c.members("sp500")["members"][0]["market_cap"], 5e12)
        caps = c.status()["market_caps"]["US"]
        self.assertEqual(caps["as_of"], NOW.isoformat())
        self.assertEqual(caps["last_error"], "Couldn't load US market caps (OSError).")


class ProfileTests(StoreTestCase):
    def test_yahoo_sector_and_industry_replace_the_funds(self):
        self.refresh_indexes({"sp500": SP500, "asx20": ASX20})
        bhp = c.members("asx20")["members"][0]
        self.assertEqual((bhp["sector"], bhp["industry"], bhp["classification"]), ("Materials", None, "gics"))
        calls = []

        async def info(symbol):
            calls.append(symbol)
            return {"sector": "Basic Materials", "industry": "Other Industrial Metals & Mining", "longName": "BHP Group Limited"}
        self.assertEqual(asyncio.run(c.fill_profiles(NOW, info, pause_s=0)), 4)
        self.assertIn("BHP.AX", calls)
        self.assertIn("AAPL", calls)
        bhp = c.members("asx20")["members"][0]
        self.assertEqual((bhp["sector"], bhp["industry"], bhp["classification"]),
                         ("Basic Materials", "Other Industrial Metals & Mining", "yahoo"))
        # Looked up: not again until the lookup is 90 days old
        self.assertEqual(asyncio.run(c.fill_profiles(NOW + timedelta(days=30), info, pause_s=0)), 0)

    def test_profile_market_cap_only_fills_a_gap(self):
        self.refresh_indexes({"sp500": SP500, "asx20": ASX20})

        async def us():
            return {"AAPL": {"market_cap": 5e12, "name": None}}
        asyncio.run(c.refresh_market_caps(NOW, us, us, force=True))

        async def info(symbol):
            return {"sector": "Technology", "marketCap": 1e9}
        asyncio.run(c.fill_profiles(NOW, info, pause_s=0))
        caps = {m["symbol"]: m["market_cap"] for m in c.members("sp500")["members"]}
        self.assertEqual(caps, {"AAPL": 5e12, "ALL": 1e9})  # the screener's cap is kept

    def test_stops_when_yahoo_keeps_failing(self):
        self.refresh_indexes({"sp500": SP500, "asx20": ASX20})
        calls = []

        async def failing(symbol):
            calls.append(symbol)
            raise OSError("429 Too Many Requests")
        self.assertEqual(asyncio.run(c.fill_profiles(NOW, failing, pause_s=0)), 0)
        self.assertEqual(len(calls), c.PROFILE_FAILURES_TO_STOP)

    def test_no_yahoo_data_is_not_asked_again(self):
        self.refresh_indexes({"sp500": SP500, "asx20": ASX20})

        async def none(symbol):
            raise yahoo.YahooUnavailable("no data")
        self.assertEqual(asyncio.run(c.fill_profiles(NOW, none, pause_s=0)), 4)
        self.assertEqual(asyncio.run(c.fill_profiles(NOW, none, pause_s=0)), 0)


class StockIndicesTests(StoreTestCase):
    def test_weight_and_rank_in_each_index(self):
        self.refresh_indexes({"sp500": SP500, "asx20": ASX20})
        [aapl] = c.indices_for("AAPL", "US")
        self.assertEqual((aapl["id"], aapl["rank"], aapl["count"], aapl["as_of"]), ("sp500", 1, 2, "2026-10-21"))
        self.assertAlmostEqual(aapl["weight"], 75.0)

    def test_the_same_ticker_on_two_markets(self):
        self.refresh_indexes({"sp500": SP500, "asx20": ASX20})
        # ALL is Allstate in the US and Aristocrat on the ASX
        self.assertEqual([i["id"] for i in c.indices_for("ALL", "US")], ["sp500"])
        self.assertEqual([i["id"] for i in c.indices_for("ALL", "ASX")], ["asx20"])
        self.assertEqual(c.indices_for("MSFT", "US"), [])

    def test_route(self):
        self.refresh_indexes({"sp500": SP500, "asx20": ASX20})

        async def contract_info(con_id):
            exchange = {1: "ASX", 2: "LSE"}.get(con_id, "NASDAQ")
            return SimpleNamespace(symbol="ALL" if con_id == 1 else "AAPL", primaryExchange=exchange, exchange="SMART"), None
        with mock.patch.object(routes, "get_contract_info", contract_info):
            asx = asyncio.run(routes.stock_indices(1))
            self.assertEqual((asx["market"], [i["id"] for i in asx["indices"]]), ("ASX", ["asx20"]))
            london = asyncio.run(routes.stock_indices(2))
            self.assertEqual((london["market"], london["indices"]), (None, []))
        json.dumps(asx)  # the answer is plain JSON


if __name__ == "__main__":
    unittest.main()
