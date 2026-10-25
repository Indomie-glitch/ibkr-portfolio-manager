import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import config
import secrets_guard
from supply_chain import graph, openfigi, resolver, themes
from supply_chain.db import open_graph

INDEX = [
    {"market": "US", "symbol": "AAPL", "name": "Apple Inc.", "market_cap": 3.9e12},
    {"market": "US", "symbol": "MU", "name": "Micron Technology, Inc.", "market_cap": 2.0e11},
    {"market": "US", "symbol": "GOOGL", "name": "Alphabet Inc.", "market_cap": 3.0e12},
    {"market": "US", "symbol": "GOOG", "name": "Alphabet Inc.", "market_cap": 3.0e12},
    {"market": "US", "symbol": "TWO", "name": "Twin Co", "market_cap": 1.0e10},
    {"market": "US", "symbol": "TWIN", "name": "Twin Corporation", "market_cap": 5.0e9},
    {"market": "ASX", "symbol": "BHP", "name": "BHP Group Limited", "market_cap": 2.0e11},
    {"market": "US", "symbol": "AT&T", "name": "AT&T Inc.", "market_cap": 1.5e11},
    {"market": "US", "symbol": "JNJ", "name": "Johnson & Johnson", "market_cap": 4.0e11},
]


def run(coro):
    return asyncio.run(coro)


def figi(name, ticker, exch="US", share_class="BBG001S5N8V8", sec_type="Common Stock"):
    return {"figi": "BBG-" + ticker + exch, "name": name, "ticker": ticker, "exchCode": exch, "compositeFIGI": "BBG-C" + ticker,
            "shareClassFIGI": share_class, "securityType": sec_type, "securityType2": sec_type, "marketSector": "Equity"}


class Keys(unittest.TestCase):
    def test_legal_endings_and_punctuation_do_not_matter(self):
        same = ["Micron Technology, Inc.", "MICRON TECHNOLOGY INC", "Micron Technology Incorporated", "micron technology"]
        self.assertEqual({resolver.name_key(n) for n in same}, {"micron technology"})
        self.assertEqual(resolver.name_key("Taiwan Semiconductor Manufacturing Company Limited"),
                         resolver.name_key("Taiwan Semiconductor Manufacturing Co., Ltd."))
        self.assertEqual(resolver.name_key("ASML Holding N.V."), "asml holding")
        self.assertEqual(resolver.name_key("The Coca-Cola Company"), "coca cola")

    def test_ampersand_and_accents(self):
        self.assertEqual(resolver.name_key("AT&T Inc."), resolver.name_key("AT and T Inc"))
        self.assertEqual(resolver.name_key("Nestlé S.A."), "nestle")

    def test_tsmc_is_an_alias_of_the_full_name(self):
        self.assertEqual(resolver.name_key("TSMC"), resolver.name_key("Taiwan Semiconductor Manufacturing Company Limited"))

    def test_a_legal_word_that_is_the_whole_name_is_kept(self):
        self.assertEqual(resolver.name_key("Company"), "company")

    def test_unnamed_customers(self):
        for name in ("Customer A", "customer B", "Customer 1", "One customer", "A large customer", "Distributor A", "Our largest customer",
                     "Two direct customers"):
            self.assertTrue(resolver.is_unnamed(name), name)
        for name in ("Customer Bancorp", "Apple Inc.", "Partner Communications Company"):
            self.assertFalse(resolver.is_unnamed(name), name)


class Resolving(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = open_graph(Path(self.tmp.name) / "g.sqlite")
        self.calls = []
        self.figi_rows = {}

    async def search(self, name):
        self.calls.append(name)
        answer = self.figi_rows.get(name, [])
        if isinstance(answer, Exception):
            raise answer
        return answer

    def resolve(self, name, **kwargs):
        return run(resolver.resolve(self.conn, name, index_companies=kwargs.pop("index", INDEX), search=self.search, **kwargs))

    # --- the identifier store first
    def test_store_matches_tsmc_for_the_full_name_and_the_short_one(self):
        themes.seed_themes(self.conn)
        for name in ("TSMC", "Taiwan Semiconductor Manufacturing Co., Ltd.", "Taiwan Semiconductor Manufacturing Company Limited"):
            outcome = self.resolve(name)
            self.assertEqual((outcome["status"], outcome["method"]), ("matched", "identifier_store"), name)
        self.assertEqual(graph.find_company(self.conn, "ticker", "TSM", "US"), outcome["company_id"])
        self.assertEqual(self.calls, [])

    def test_store_wins_over_index_data(self):
        company = graph.add_company(self.conn, "Apple Inc.")
        graph.add_identifier(self.conn, company, "ticker", "AAPL", "US")
        outcome = self.resolve("APPLE INC")
        self.assertEqual((outcome["company_id"], outcome["method"]), (company, "identifier_store"))

    def test_two_store_companies_with_the_name_are_ambiguous(self):
        graph.add_company(self.conn, "Delta Inc")
        graph.add_company(self.conn, "Delta Corporation")
        outcome = self.resolve("Delta Co")
        self.assertEqual((outcome["status"], outcome["reason"]), ("skipped", "ambiguous"))

    def test_placeholder_companies_are_not_matched(self):
        apple = graph.add_company(self.conn, "Apple Inc.")
        graph.add_company(self.conn, "Customer A", placeholder_for=apple)
        self.assertEqual(self.resolve("Customer A")["reason"], "unnamed")

    # --- index data
    def test_index_member_creates_the_company_with_its_ticker(self):
        outcome = self.resolve("Micron Technology Inc")
        self.assertEqual((outcome["status"], outcome["method"]), ("matched", "index_data"))
        self.assertEqual(graph.find_company(self.conn, "ticker", "MU", "US"), outcome["company_id"])
        self.assertEqual(self.conn.execute("SELECT name FROM companies WHERE id = ?", (outcome["company_id"],)).fetchone()[0], "Micron Technology, Inc.")
        self.assertEqual(self.calls, [])

    def test_index_match_reuses_the_theme_company(self):
        themes.seed_themes(self.conn, [{"slug": "t", "name": "T", "companies": [{"name": "Micron", "ticker": "MU", "market": "US"}]}])
        before = self.conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        outcome = self.resolve("Micron Technology, Inc.")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0], before)
        self.assertEqual(graph.find_company(self.conn, "ticker", "MU", "US"), outcome["company_id"])

    def test_share_classes_are_one_company(self):
        outcome = self.resolve("Alphabet Inc.")
        self.assertEqual(outcome["status"], "matched")
        self.assertEqual(graph.find_company(self.conn, "ticker", "GOOG", "US"), graph.find_company(self.conn, "ticker", "GOOGL", "US"))

    def test_same_name_with_different_size_is_ambiguous(self):
        outcome = self.resolve("Twin Co")
        self.assertEqual((outcome["status"], outcome["reason"]), ("skipped", "ambiguous"))
        self.assertIn("TWO", outcome["detail"])

    def test_symbols_in_names(self):
        self.assertEqual(self.resolve("AT&T Inc")["status"], "matched")
        self.assertEqual(self.resolve("Johnson and Johnson")["status"], "matched")

    def test_cross_listed_company_matches_in_its_own_market(self):
        outcome = self.resolve("BHP Group Ltd")
        self.assertEqual(graph.find_company(self.conn, "ticker", "BHP", "ASX"), outcome["company_id"])

    # --- subsidiaries and near misses
    def test_subsidiaries_are_not_matched_to_the_parent(self):
        for name in ("Apple Operations International Limited", "Micron Technology Asia Pte. Ltd.", "Apple Retail UK Ltd"):
            outcome = self.resolve(name)
            self.assertEqual((outcome["status"], outcome["reason"]), ("skipped", "possible_subsidiary"), name)
            self.assertIn(outcome["detail"].split(" of ")[1].split(";")[0][:5], ("Apple", "Micro"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0], 0)

    def test_a_shorter_name_is_not_matched_either(self):
        self.assertEqual(self.resolve("Micron")["reason"], "no_match")
        self.assertEqual(self.resolve("Alpha")["reason"], "no_match")

    def test_unnamed_never_reaches_a_lookup(self):
        self.assertEqual(self.resolve("Customer A")["reason"], "unnamed")
        self.assertEqual(self.resolve("   ")["reason"], "no_name")
        self.assertEqual(self.calls, [])

    # --- OpenFIGI
    def test_openfigi_single_company_matches(self):
        self.figi_rows["Super Micro Computer, Inc."] = [
            figi("SUPER MICRO COMPUTER INC", "SMCI", "US", "BBG-SC1"), figi("SUPER MICRO COMPUTER INC", "SMCI", "UN", "BBG-SC1"),
            figi("SUPER MICRO COMPUTER INC", "SMC", "GR", "BBG-SC1"), figi("SUPER MICRO COMPUTER INC", "SMCI", "UW", "BBG-SC1")]
        outcome = self.resolve("Super Micro Computer, Inc.")
        self.assertEqual((outcome["status"], outcome["method"]), ("matched", "openfigi"))
        company = outcome["company_id"]
        self.assertEqual(graph.find_company(self.conn, "ticker", "SMCI", "US"), company)
        self.assertEqual(graph.find_company(self.conn, "share_class_figi", "BBG-SC1"), company)
        self.assertEqual(self.conn.execute("SELECT name FROM companies WHERE id = ?", (company,)).fetchone()[0], "Super Micro Computer Inc")
        self.assertEqual(self.conn.execute("SELECT source FROM identifiers WHERE company_id = ? AND scheme = 'ticker'", (company,)).fetchone()[0], "openfigi")

    def test_openfigi_other_names_are_ignored(self):
        self.figi_rows["Zeta"] = [figi("ZETA GLOBAL HOLDINGS", "ZETA"), figi("ZETA ENERGY CORP", "ZEN", "US", "BBG-OTHER")]
        outcome = self.resolve("Zeta")
        self.assertEqual(outcome["reason"], "no_match")

    def test_openfigi_two_different_companies_are_ambiguous(self):
        self.figi_rows["Orion Corp"] = [figi("ORION CORP", "ORN", "US", "BBG-A"), figi("ORION CORP", "ORI", "LN", "BBG-B")]
        outcome = self.resolve("Orion Corp")
        self.assertEqual((outcome["status"], outcome["reason"]), ("skipped", "ambiguous"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0], 0)

    def test_openfigi_non_equity_listings_do_not_count(self):
        self.figi_rows["Bond Co"] = [figi("BOND CO", "BND", "US", "BBG-F", sec_type="Mutual Fund")]
        self.assertEqual(self.resolve("Bond Co")["reason"], "no_match")

    def test_openfigi_foreign_listing_gets_the_markets_name(self):
        self.figi_rows["Advantest Corp"] = [figi("ADVANTEST CORP", "6857", "JT", "BBG-ADV")]
        outcome = self.resolve("Advantest Corp")
        self.assertEqual(graph.find_company(self.conn, "ticker", "6857", "JP"), outcome["company_id"])

    def test_openfigi_down_is_not_a_decision(self):
        self.figi_rows["Zed Inc"] = openfigi.OpenFigiUnavailable("busy")
        self.assertEqual(self.resolve("Zed Inc")["status"], "unavailable")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM name_resolutions").fetchone()[0], 0)
        self.figi_rows["Zed Inc"] = [figi("ZED INC", "ZED", "US", "BBG-Z")]
        self.assertEqual(self.resolve("Zed Inc")["status"], "matched")

    # --- remembering
    def test_decisions_are_kept_and_not_looked_up_again(self):
        self.figi_rows["Zeta"] = []
        first = self.resolve("Zeta")
        second = self.resolve("ZETA, INC.")
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(self.calls, ["Zeta"])
        row = self.conn.execute("SELECT status, reason, name FROM name_resolutions").fetchone()
        self.assertEqual((row["status"], row["reason"], row["name"]), ("skipped", "no_match", "Zeta"))

    def test_a_match_records_how_it_was_made(self):
        self.resolve("Micron Technology, Inc.")
        row = self.conn.execute("SELECT status, method, company_id FROM name_resolutions").fetchone()
        self.assertEqual((row["status"], row["method"]), ("matched", "index_data"))
        self.assertEqual(self.conn.execute("SELECT source FROM identifiers WHERE scheme = 'name'").fetchone()[0], "index_data")

    def test_an_old_skip_is_looked_at_again(self):
        self.resolve("Zeta")
        self.conn.execute("UPDATE name_resolutions SET updated_at = '2020-01-01T00:00:00Z'")
        self.figi_rows["Zeta"] = [figi("ZETA", "ZETA", "US", "BBG-Z")]
        self.assertEqual(self.resolve("Zeta")["status"], "matched")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM name_resolutions").fetchone()[0], 1)

    def test_resolve_many_asks_each_name_once(self):
        out = run(resolver.resolve_many(self.conn, ["Zeta", "Zeta", "Apple Inc."], index_companies=INDEX, search=self.search))
        self.assertEqual(list(out), ["Zeta", "Apple Inc."])
        self.assertEqual(self.calls, ["Zeta"])

    def test_the_resolution_table_refuses_inconsistent_rows(self):
        with self.assertRaises(Exception):
            self.conn.execute("INSERT INTO name_resolutions (name_key, name, status, created_at, updated_at) VALUES ('a', 'a', 'matched', 'n', 'n')")
        with self.assertRaises(Exception):
            self.conn.execute("INSERT INTO name_resolutions (name_key, name, status, created_at, updated_at) VALUES ('b', 'b', 'skipped', 'n', 'n')")


class Client(unittest.TestCase):
    def setUp(self):
        openfigi._last = 0.0
        sleeps = mock.patch.object(openfigi.asyncio, "sleep", mock.AsyncMock())
        self.sleeps = sleeps.start()
        self.addCleanup(sleeps.stop)

    def post(self, *replies):
        queue = list(replies)
        calls = []

        def fake(body, headers):
            calls.append((body, headers))
            reply = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(reply, Exception):
                raise reply
            return reply
        return calls, mock.patch.object(openfigi, "_post", fake)

    def test_key_is_sent_when_set_and_equities_are_kept(self):
        calls, patch = self.post((200, {}, b'{"data": [{"name": "A", "marketSector": "Equity"}, {"name": "B", "marketSector": "Corp"}]}'))
        with patch, mock.patch.object(config, "openfigi_api_key", lambda: "k" * 12):
            rows = run(openfigi.search("A"))
        self.assertEqual([r["name"] for r in rows], ["A"])
        self.assertEqual(calls[0][1]["X-OPENFIGI-APIKEY"], "k" * 12)

    def test_works_without_a_key(self):
        calls, patch = self.post((200, {}, b'{"data": []}'))
        with patch, mock.patch.object(config, "openfigi_api_key", lambda: None):
            self.assertEqual(run(openfigi.search("A")), [])
        self.assertNotIn("X-OPENFIGI-APIKEY", calls[0][1])

    def test_rate_limit_waits_then_retries(self):
        calls, patch = self.post((429, {"Retry-After": "7"}, b""), (200, {}, b'{"data": []}'))
        with patch, mock.patch.object(config, "openfigi_api_key", lambda: None):
            run(openfigi.search("A"))
        self.assertEqual(len(calls), 2)
        self.assertIn(7, [c.args[0] for c in self.sleeps.call_args_list])

    def test_gives_up_when_it_keeps_failing(self):
        calls, patch = self.post((503, {}, b""))
        with patch, self.assertRaises(openfigi.OpenFigiUnavailable):
            run(openfigi.search("A"))
        self.assertEqual(len(calls), 4)

    def test_a_refusal_is_not_retried(self):
        calls, patch = self.post((400, {}, b""))
        with patch, self.assertRaises(openfigi.OpenFigiUnavailable):
            run(openfigi.search("A"))
        self.assertEqual(len(calls), 1)

    def test_the_key_is_masked_in_logs(self):
        with mock.patch.object(config, "openfigi_api_key", lambda: "abcd1234efgh5678"):
            self.assertNotIn("abcd1234efgh5678", secrets_guard.mask_secrets("oops abcd1234efgh5678"))


if __name__ == "__main__":
    unittest.main()
