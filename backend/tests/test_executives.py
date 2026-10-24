"""Tests for the executives endpoint: telling executives from directors in Yahoo's one list, tidying
names, optional age and pay, and the one-week cache (#112)."""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PORTFOLIO_DATA_DIR", tempfile.mkdtemp())
from fastapi import HTTPException  # noqa: E402
from ib_async import Contract  # noqa: E402

import cache  # noqa: E402
import yahoo  # noqa: E402
from routers import positions as routes  # noqa: E402


class NameTests(unittest.TestCase):
    def test_honorifics_degrees_and_spaces_are_dropped(self):
        for raw, want in [
            ("Mr. Matthew  Comyn EMBA", "Matthew Comyn"),
            ("Mr. Alan F. Docherty C.A.", "Alan F. Docherty"),
            ("Ms. Vittoria Annabel June Shortt BMS, CA", "Vittoria Annabel June Shortt"),
            ("Mr. Mike P. Henry B.Sc., BSc (Chem)", "Mike P. Henry"),
            ("Ms. Caroline  Cox B.A., L.L.B., M.A.", "Caroline Cox"),
            ("Mr. Johan  van Jaarsveld B.E., Ph.D.", "Johan van Jaarsveld"),
            ("Ms. Jennifer G. Newstead J.D.", "Jennifer G. Newstead"),
            ("Dr. Jane Smith", "Jane Smith"),
            ("Suhasini  Chandramouli", "Suhasini Chandramouli"),
        ]:
            self.assertEqual(yahoo.clean_person_name(raw), want, raw)

    def test_middle_initials_and_short_surnames_stay(self):
        self.assertEqual(yahoo.clean_person_name("Mr. Timothy D. Cook"), "Timothy D. Cook")
        # An all-capitals surname isn't mistaken for a degree when it would leave a single word
        self.assertEqual(yahoo.clean_person_name("Mr. Jin NG"), "Jin NG")
        self.assertEqual(yahoo.clean_person_name(None), "")


class ClassifyTests(unittest.TestCase):
    def roles(self, title):
        executive, director = yahoo.classify_title(title)
        return "both" if executive and director else "executive" if executive else "director" if director else "neither"

    def test_executives(self):
        for title in ["Chief Financial Officer", "Senior VP & CFO", "Group Chief Risk Officer", "Secretary",
                      "Head of Investor Relations", "Principal Accounting Officer", "President of Australia",
                      "Group General Counsel, Company Secretary and Group Executive of Legal & Group Secretariat",
                      "Executive Officer", "Chief Executive & MD of ASB Bank Ltd."]:
            self.assertEqual(self.roles(title), "executive", title)

    def test_director_of_a_department_is_not_a_board_seat(self):
        self.assertEqual(self.roles("Director of Investor Relations"), "executive")
        self.assertEqual(self.roles("Director of Tax"), "executive")

    def test_people_who_are_both(self):
        for title in ["CEO & Director", "CEO, MD & Executive Director", "Executive Chairman of the Board",
                      "Managing Director", "Chief Financial Officer and Director"]:
            self.assertEqual(self.roles(title), "both", title)

    def test_board_members_who_are_not_executives(self):
        for title in ["Independent Non-Executive Director", "Non-Executive Chairman", "Non Executive Director",
                      "Lead Independent Director", "Director", "Chairman of the Board", "Independent Director"]:
            self.assertEqual(self.roles(title), "director", title)

    def test_a_missing_title_counts_as_an_officer(self):
        self.assertEqual(self.roles(None), "executive")
        self.assertEqual(self.roles(""), "executive")


CBA_LIKE = {
    "financialCurrency": "AUD",
    "companyOfficers": [
        {"name": "Mr. Matthew  Comyn EMBA", "age": 49, "title": "CEO, MD & Executive Director", "yearBorn": 1976,
         "fiscalYear": 2026, "totalPay": 4331460, "exercisedValue": 0},
        {"name": "Ms. Emma  Bunnell", "title": "Chief Operations Officer", "fiscalYear": 2026, "exercisedValue": 0},
        {"name": "Mr. Paul  Board", "title": "Independent Non-Executive Director", "age": 61, "yearBorn": 1964},
        {"title": "No name given"},
    ],
}


class OfficerTests(unittest.TestCase):
    def test_executives_and_directors_are_separated(self):
        result = yahoo.executives_from_info(CBA_LIKE)
        self.assertEqual([p["name"] for p in result["executives"]], ["Matthew Comyn", "Emma Bunnell"])
        self.assertEqual([p["name"] for p in result["directors"]], ["Paul Board"])
        self.assertEqual(result["source"], "Yahoo Finance")

    def test_someone_who_is_both_is_an_executive_marked_as_a_director(self):
        [comyn, _] = yahoo.executives_from_info(CBA_LIKE)["executives"]
        self.assertTrue(comyn["is_executive"] and comyn["is_director"])

    def test_age_and_pay_when_given_and_empty_when_not(self):
        [comyn, bunnell] = yahoo.executives_from_info(CBA_LIKE)["executives"]
        self.assertEqual((comyn["age"], comyn["year_born"], comyn["pay"], comyn["pay_currency"], comyn["pay_fiscal_year"]),
                         (49, 1976, 4331460.0, "AUD", 2026))
        self.assertEqual((bunnell["age"], bunnell["year_born"], bunnell["pay"], bunnell["pay_currency"], bunnell["pay_fiscal_year"]),
                         (None, None, None, None, None))

    def test_raw_name_title_and_empty_links_are_kept(self):
        [comyn, _] = yahoo.executives_from_info(CBA_LIKE)["executives"]
        self.assertEqual((comyn["listed_as"], comyn["title"]), ("Mr. Matthew Comyn EMBA", "CEO, MD & Executive Director"))
        # Yahoo gives no start year or Wikipedia / Wikidata links; #113 / #114 fill them by matching
        self.assertEqual((comyn["year_started"], comyn["wikidata_id"], comyn["wikipedia_url"]), (None, None, None))

    def test_nobody_listed(self):
        for info in ({}, {"companyOfficers": None}, {"companyOfficers": []}):
            result = yahoo.executives_from_info(info)
            self.assertEqual((result["executives"], result["directors"]), ([], []))

    def test_pay_currency_falls_back_to_the_trading_currency(self):
        info = {"currency": "USD", "companyOfficers": [{"name": "A B", "title": "CFO", "totalPay": 5}]}
        self.assertEqual(yahoo.executives_from_info(info)["executives"][0]["pay_currency"], "USD")


def run(coro):
    return asyncio.run(coro)


class RouteTests(unittest.TestCase):
    def setUp(self):
        cache._entries.clear()
        cache._locks.clear()
        self.contract = Contract(conId=4036818, symbol="CBA", secType="STK", exchange="ASX", currency="AUD")

    def call(self, info=None, fail=False):
        calls = []

        async def fetch_info(symbol):
            calls.append(symbol)
            if fail:
                raise RuntimeError("yahoo down")
            return info or CBA_LIKE

        with mock.patch.object(routes, "get_contract_info", mock.AsyncMock(return_value=(self.contract, "COMMONWEALTH BANK"))), \
                mock.patch.object(routes.yahoo, "fetch_info", fetch_info):
            return run(routes.executives(4036818)), calls

    def test_the_answer_names_the_yahoo_symbol(self):
        result, _ = self.call()
        self.assertEqual(result["yahoo_symbol"], "CBA.AX")
        self.assertEqual(len(result["executives"]), 2)
        self.assertEqual(len(result["directors"]), 1)

    def test_cached_for_a_week(self):
        self.assertEqual(routes.EXECUTIVES_TTL, 7 * 24 * 60 * 60)
        first, calls = self.call()
        again, calls_again = self.call()
        self.assertEqual(again, first)
        self.assertEqual((len(calls), len(calls_again)), (1, 0))

    def test_cache_entry_lasts_a_week(self):
        self.call()
        expires_at = cache._entries[("executives", "CBA.AX")][0]
        import time
        self.assertAlmostEqual(expires_at - time.monotonic(), routes.EXECUTIVES_TTL, delta=5)

    def test_yahoo_failing_is_a_502(self):
        with self.assertRaises(HTTPException) as caught:
            self.call(fail=True)
        self.assertEqual(caught.exception.status_code, 502)

    def test_an_unmapped_exchange_is_a_404(self):
        self.contract = Contract(conId=1, symbol="X", secType="STK", exchange="LSE", currency="GBP")
        with self.assertRaises(HTTPException) as caught:
            self.call()
        self.assertEqual(caught.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
