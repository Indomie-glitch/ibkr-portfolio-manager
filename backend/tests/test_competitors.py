"""Tests for competitors by industry (#111): the industry, related-industry and sector levels,
ranking across markets in US dollars, the stock itself and stocks you own, and the route."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PORTFOLIO_DATA_DIR", tempfile.mkdtemp())
import competitors  # noqa: E402
from routers import indices as routes  # noqa: E402

RATES = {"USD": 1.0, "AUD": 0.65}
LOOKED_UP = "2026-10-23T00:00:00+00:00"


def company(symbol, industry, cap, market="ASX", sector="Financial Services", looked_up=True, **extra):
    return {"market": market, "symbol": symbol, "name": f"{symbol} Ltd", "sector": sector, "industry": industry,
            "profile_at": LOOKED_UP if looked_up else None, "market_cap": cap, "pe": 15.0, "return_1y": 5.0,
            "market_cap_at": LOOKED_UP, **extra}


# Australian and US banks: CBA has 4 "Banks - Diversified" peers (ANZ and three US banks)
BANKS = [
    company("CBA", "Banks - Diversified", 270e9),
    company("ANZ", "Banks - Diversified", 100e9),
    company("BEN", "Banks - Regional", 7e9),
    company("BOQ", "Banks - Regional", 4.5e9),
    company("JPM", "Banks - Diversified", 800e9, market="US"),
    company("BAC", "Banks - Diversified", 330e9, market="US"),
    company("WFC", "Banks - Diversified", 260e9, market="US"),
    company("USB", "Banks - Regional", 75e9, market="US"),
    company("MQG", "Capital Markets", 75e9),
    company("XYZ", "Banks - Regional", 1e9, looked_up=False),  # sector not looked up yet: left out
]


def bank(symbol):
    return next(c for c in BANKS if c["symbol"] == symbol)


def symbols(result):
    return [c["symbol"] for c in result["companies"]]


class LevelTests(unittest.TestCase):
    def test_same_industry_across_markets_ranked_in_us_dollars(self):
        result = competitors.find(bank("CBA"), BANKS, RATES, owned={})
        self.assertEqual((result["level"], result["label"], result["peers_total"]), ("industry", "Banks - Diversified", 4))
        # CBA's A$270bn is US$175.5bn: below WFC's US$260bn
        self.assertEqual(symbols(result), ["JPM", "BAC", "WFC", "CBA", "ANZ"])
        cba = result["companies"][3]
        self.assertEqual((cba["rank"], cba["is_self"], cba["currency"], cba["market"]), (4, True, "AUD", "ASX"))
        self.assertAlmostEqual(cba["market_cap_usd"], 175.5e9)
        self.assertEqual(cba["market_cap"], 270e9)  # in its own currency too

    def test_too_few_widens_to_related_industries(self):
        asx_banks = [c for c in BANKS if c["market"] == "ASX"]
        result = competitors.find(asx_banks[0], asx_banks + [company("NAB", "Banks - Diversified", 120e9)],
                                  RATES, owned={})
        # Only 2 other diversified banks, so regional banks join: the "Banks" family
        self.assertEqual((result["level"], result["label"]), ("related", "Banks"))
        self.assertEqual(result["industries"], ["Banks - Diversified", "Banks - Regional"])
        self.assertEqual(symbols(result), ["CBA", "NAB", "ANZ", "BEN", "BOQ"])
        self.assertNotIn("MQG", symbols(result))  # Capital Markets is another family
        self.assertNotIn("XYZ", symbols(result))

    def test_then_the_sector(self):
        stock = company("QBE", "Insurance - Property & Casualty", 30e9)
        universe = [stock, company("IAG", "Insurance - Property & Casualty", 20e9),
                    company("AJG", "Insurance Brokers", 60e9, market="US")] + BANKS
        result = competitors.find(stock, universe, RATES, owned={})
        self.assertEqual((result["level"], result["label"]), ("sector", "Financial Services"))
        self.assertIn("CBA", symbols(result))

    def test_families(self):
        self.assertEqual(competitors.family_of("Banks - Regional"), "Banks")
        self.assertEqual(competitors.family_of("Insurance Brokers"), "Insurance")
        self.assertEqual(competitors.family_of("Gold"), "Metals & Mining")
        self.assertEqual(competitors.family_of("Oil & Gas Midstream"), "Oil & Gas")
        self.assertEqual(competitors.family_of("Semiconductor Equipment & Materials"), "Semiconductors")
        self.assertEqual(competitors.family_of("Tobacco"), "Tobacco")


class ListTests(unittest.TestCase):
    def test_owned_and_self_are_kept_beyond_the_limit(self):
        result = competitors.find(bank("BOQ"), BANKS, RATES, owned={("ASX", "BEN"): 111}, limit=2)
        # BOQ is "Banks - Regional" with 2 peers (XYZ isn't looked up), so the Banks family is used:
        # JPM, BAC, WFC, CBA, USB, ANZ, BEN, BOQ in US dollars. Top 2, then BEN (owned) and BOQ (itself)
        self.assertEqual(result["level"], "related")
        self.assertEqual(result["peers_total"], 7)
        self.assertEqual([(c["symbol"], c["rank"]) for c in result["companies"]],
                         [("JPM", 1), ("BAC", 2), ("BEN", 7), ("BOQ", 8)])
        ben, boq = result["companies"][2:]
        self.assertEqual((ben["owned"], ben["owned_con_id"], ben["is_self"]), (True, 111, False))
        self.assertEqual((boq["owned"], boq["is_self"]), (False, True))

    def test_a_stock_outside_the_indexes(self):
        small = company("SMLL", "Banks - Regional", 0.5e9, looked_up=False)  # from its Yahoo profile
        result = competitors.find(small, BANKS, RATES, owned={("ASX", "SMLL"): 222})
        self.assertEqual(result["level"], "related")  # 3 regional banks (XYZ isn't looked up), so all banks
        self.assertEqual(symbols(result)[-1], "SMLL")
        self.assertTrue(result["companies"][-1]["is_self"])

    def test_missing_market_cap_ranks_last(self):
        stock = dict(bank("BEN"), market_cap=None)
        result = competitors.find(stock, BANKS, RATES, owned={})
        self.assertEqual(symbols(result)[-1], "BEN")
        self.assertIsNone(result["companies"][-1]["market_cap_usd"])


class RouteTests(unittest.TestCase):
    def call(self, contract, universe=BANKS, complete=True, info=None, owned=()):
        async def contract_info(con_id):
            return contract, None

        async def rate(currency, base):
            return 0.65

        async def yahoo_info(symbol):
            if info is None:
                raise AssertionError(f"Yahoo shouldn't be asked about {symbol}")
            return info
        portfolio = [SimpleNamespace(contract=SimpleNamespace(secType="STK", symbol=s, primaryExchange="ASX",
                                                              exchange="SMART", conId=i), position=10)
                     for i, s in enumerate(owned, start=1)]
        progress = {"done": 9 if complete else 3, "total": 9, "complete": complete}
        with mock.patch.object(routes, "get_contract_info", contract_info), \
                mock.patch.object(routes.fx, "rate_to_base", rate), \
                mock.patch.object(routes, "yahoo_info", yahoo_info), \
                mock.patch.object(routes.constituents, "universe", lambda: universe), \
                mock.patch.object(routes.constituents, "profile_progress", lambda: progress), \
                mock.patch.object(routes.constituents, "status", lambda: {"market_data": {}}), \
                mock.patch.object(routes.ib, "portfolio", lambda: portfolio):
            return asyncio.run(routes.stock_competitors(5))

    def asx(self, symbol):
        return SimpleNamespace(symbol=symbol, primaryExchange="ASX", exchange="SMART")

    def test_an_index_member(self):
        answer = self.call(self.asx("CBA"), owned=["WBC", "BEN"])
        self.assertEqual((answer["status"], answer["level"]), ("ready", "industry"))
        self.assertEqual([c["symbol"] for c in answer["companies"]], ["JPM", "BAC", "WFC", "CBA", "ANZ"])

    def test_owned_peer(self):
        answer = self.call(self.asx("BOQ"), owned=["BEN"])
        ben = next(c for c in answer["companies"] if c["symbol"] == "BEN")
        self.assertEqual((ben["owned"], ben["owned_con_id"]), (True, 1))

    def test_a_small_cap_uses_its_yahoo_industry(self):
        info = {"longName": "Small Bank Ltd", "sector": "Financial Services", "industry": "Banks - Regional",
                "marketCap": 5e8, "trailingPE": 8.0, "52WeekChange": -0.1}
        answer = self.call(self.asx("SMLL"), info=info)
        me = answer["companies"][-1]
        self.assertEqual((me["symbol"], me["is_self"], me["name"], me["pe"]), ("SMLL", True, "Small Bank Ltd", 8.0))
        self.assertAlmostEqual(me["return_1y"], -10.0)

    def test_still_loading(self):
        answer = self.call(self.asx("CBA"), complete=False)
        self.assertEqual(answer["status"], "loading")
        self.assertEqual(answer["progress"], {"done": 3, "total": 9, "complete": False})
        self.assertTrue(answer["companies"])  # what's found so far, not an empty list

    def test_no_industry(self):
        answer = self.call(self.asx("IOZ"), info={"longName": "iShares Core S&P/ASX 200 ETF"})
        self.assertEqual((answer["status"], answer["companies"]), ("no_industry", []))

    def test_another_market(self):
        answer = self.call(SimpleNamespace(symbol="VOD", primaryExchange="LSE", exchange="SMART"))
        self.assertEqual((answer["status"], answer["market"], answer["companies"]), ("unsupported", None, []))


if __name__ == "__main__":
    unittest.main()
