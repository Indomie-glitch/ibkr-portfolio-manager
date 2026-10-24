"""Tests for boards of directors (#113): finding the document, keeping only the board passages,
checking Claude's answer against the document, matching people across companies without false
matches, the ASX terms, the seed and the newer-document check. No network and no API calls."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PORTFOLIO_DATA_DIR", tempfile.mkdtemp())
from fastapi import HTTPException  # noqa: E402

import directors  # noqa: E402
import directors_sources as sources  # noqa: E402
import people  # noqa: E402
import usage_store  # noqa: E402
from routers import directors as routes  # noqa: E402

NOW = datetime(2026, 10, 24)


def run(coro):
    return asyncio.run(coro)


class StoreTestCase(unittest.TestCase):
    """Every SQLite store points at a temp folder."""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        for module, name in ((directors, "directors.sqlite"), (usage_store, "usage.sqlite")):
            patcher = mock.patch.object(module, "DB_PATH", Path(self.folder.name) / name)
            patcher.start()
            self.addCleanup(patcher.stop)
        directors._locks.clear()


# ---------- people.py ----------

class NameTests(unittest.TestCase):
    def test_titles_degrees_honours_and_middle_names_are_ignored(self):
        self.assertEqual(people.match_key("Ms. Catherine (Cathy) M. Livingstone AO"), "catherine livingstone")
        self.assertEqual(people.match_key("Rob Whitfield AM"), "rob whitfield")
        self.assertEqual(people.match_key("Dr. Anne Smith AC FAA"), "anne smith")
        self.assertIsNone(people.match_key("Cher"))

    def test_honours_come_off_the_end_not_the_start(self):
        # AMD's and Goldman Sachs's director "KC McClure": KC isn't a King's Counsel here
        self.assertEqual(people.match_key("KC McClure"), "kc mcclure")
        self.assertEqual(people.match_key("Jane Smith KC"), "jane smith")
        self.assertEqual(people.match_key("Sir Rod Eddington AC"), "rod eddington")
        self.assertIsNone(people.match_key("Duffy"))  # a surname alone isn't enough to match anyone

    def test_apostrophes_match_whichever_kind_a_document_uses(self):
        self.assertEqual(people.match_key("Paul O’Malley"), people.match_key("Paul O'Malley"))
        self.assertEqual(people.match_key("Christine O’Reilly"), "christine oreilly")

    def test_loose_names_within_one_company(self):
        self.assertTrue(people.same_name_loosely("Matthew Comyn", "Matt Comyn"))
        self.assertTrue(people.same_name_loosely("Art Levinson", "Arthur D. Levinson"))
        self.assertTrue(people.same_name_loosely("Sue Wagner", "Susan Wagner"))
        self.assertTrue(people.same_name_loosely("Catherine (Cathy) Tanna", "Cathy Tanna"))
        self.assertFalse(people.same_name_loosely("Sue Wagner", "Sam Wagner"))
        self.assertFalse(people.same_name_loosely("Al Gore", "Alan Gore"))  # too short to be sure
        self.assertFalse(people.same_name_loosely("Matt Comyn", "Matt Combs"))

    def test_wikidata_match_needs_exactly_one_candidate(self):
        candidates = [{"id": "Q1", "label": "Matt Comyn", "aliases": [], "article": "https://en.wikipedia.org/wiki/Matt_Comyn"},
                      {"id": "Q2", "label": "Ian Narev", "aliases": [], "article": None}]
        self.assertEqual(people.wikidata_match("Matthew Comyn", candidates)["id"], "Q1")
        self.assertIsNone(people.wikidata_match("Paul O'Malley", candidates))
        two = candidates + [{"id": "Q3", "label": "Matthew Comyn", "aliases": [], "article": None}]
        self.assertIsNone(people.wikidata_match("Matthew Comyn", two))  # ambiguous: no ID rather than a guess
        alias = [{"id": "Q4", "label": "Susan J. Wagner", "aliases": ["Sue Wagner"], "article": None}]
        self.assertEqual(people.wikidata_match("Sue Wagner", alias)["id"], "Q4")

    def test_company_named_in_other_boards(self):
        self.assertTrue(people.company_named("BHP Group Limited", ["BHP Group (Chair)", "Orica"]))
        self.assertTrue(people.company_named("Intel Corporation", ["Intel Corporation; Qantas Airways Limited"]))
        self.assertFalse(people.company_named("Apple Inc.", ["Pineapple Holdings"]))
        self.assertFalse(people.company_named("AB", ["AB something"]))  # too short to match on


class LinkTests(unittest.TestCase):
    def seat(self, name, other_boards=(), wikidata_id=None):
        return {"match_key": people.match_key(name), "other_boards": list(other_boards), "wikidata_id": wikidata_id}

    def test_the_same_wikidata_id_is_the_same_person(self):
        self.assertEqual(people.link_basis(self.seat("Dion Weisler", wikidata_id="Q9"), self.seat("Dion Weisler", wikidata_id="Q9"),
                                           "BHP Group Limited", "Intel Corporation"), "wikidata")

    def test_different_wikidata_ids_are_different_people_even_with_the_same_name(self):
        self.assertIsNone(people.link_basis(self.seat("David Smith", wikidata_id="Q1"), self.seat("David Smith", wikidata_id="Q2"),
                                            "A Corp", "B Corp"))

    def test_a_document_naming_the_other_company_links_them(self):
        bhp = self.seat("Dion Weisler", ["Intel Corporation", "Qantas Airways Limited"])
        intel = self.seat("Dion J. Weisler")
        self.assertEqual(people.link_basis(bhp, intel, "BHP Group Limited", "Intel Corporation"), "named_in_document")
        # Either side can name the other
        self.assertEqual(people.link_basis(intel, bhp, "Intel Corporation", "BHP Group Limited"), "named_in_document")

    def test_the_same_name_alone_is_only_a_possible_match(self):
        self.assertEqual(people.link_basis(self.seat("David Smith"), self.seat("David Smith"), "A Corp", "B Corp"), "name_only")

    def test_different_names_are_not_linked(self):
        self.assertIsNone(people.link_basis(self.seat("David Smith"), self.seat("Dana Smith"), "A Corp", "B Corp"))


# ---------- directors_sources.py ----------

def submissions(*filings, name="Apple Inc."):
    keys = ["form", "filingDate", "accessionNumber", "primaryDocument"]
    return {"name": name, "filings": {"recent": {k: [f[i] for f in filings] for i, k in enumerate(keys)}}}


class SecTests(unittest.TestCase):
    def test_the_newest_proxy_from_the_last_18_months(self):
        found = sources.choose_filing(submissions(("10-K", "2026-10-30", "0001-26-000002", "k.htm"),
                                                  ("DEF 14A", "2026-01-08", "0001308179-26-000008", "p.htm"),
                                                  ("DEF 14A", "2025-01-10", "0001308179-25-000001", "old.htm")), 320193, NOW)
        self.assertEqual((found["kind"], found["filed"]), ("DEF 14A", "2026-01-08"))
        self.assertEqual(found["url"], "https://www.sec.gov/Archives/edgar/data/320193/000130817926000008/p.htm")

    def test_a_foreign_company_uses_its_20f(self):
        found = sources.choose_filing(submissions(("20-F", "2026-08-19", "0001-26-1", "f.htm")), 811809, NOW)
        self.assertEqual(found["kind"], "20-F")

    def test_an_old_proxy_is_no_document(self):
        self.assertIsNone(sources.choose_filing(submissions(("DEF 14A", "2024-03-01", "0001-24-1", "p.htm")), 1, NOW))
        self.assertIsNone(sources.choose_filing({"name": "X"}, 1, NOW))

    def test_ib_symbols_become_sec_tickers(self):
        self.assertEqual(sources.sec_ticker("BRK B"), "BRK-B")
        self.assertEqual(sources.sec_ticker("bf.b"), "BF-B")

    def test_no_contact_email_means_no_request(self):
        with mock.patch.object(sources.config, "sec_contact_email", return_value=None):
            with self.assertRaises(sources.SourceUnavailable):
                sources.sec_headers()


ASX_PAGE = """<table>
<tr><th>Date</th><th>Headline</th></tr>
<tr><td>12/08/2026 <span>7:35 am</span></td><td><a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId=03124133">2026 Annual Report</a> 452 pages 21.9MB</td></tr>
<tr><td>12/08/2026 7:36 am</td><td><a href="/x?display=pdf&amp;idsId=03124134">Appendix 4G and 2026 Corporate Governance Statement</a> 36 pages</td></tr>
<tr><td>11/09/2026 9:00 am</td><td><a href="/x?idsId=03130000">2026 Notice of Annual General Meeting</a> 25 pages</td></tr>
<tr><td>19/08/2026 8:00 am</td><td><a href="/x?idsId=03126614">2026 US Annual Report (Form 20-F)</a> 300 pages</td></tr>
<tr><td>13/08/2025 7:35 am</td><td><a href="/x?idsId=02979638">2025 Annual Report</a> 456 pages</td></tr>
</table>"""

BHP_PAGE = """<table>
<tr><td>19/08/2026 8:00 am</td><td><a href="/x?idsId=03126614">2026 US Annual Report (Form 20-F)</a> 1028 pages</td></tr>
<tr><td>18/08/2026 7:30 am</td><td><a href="/x?idsId=03126000">BHP 2026 Economic Contribution Report</a> 36 pages</td></tr>
<tr><td>18/08/2026 7:29 am</td><td><a href="/x?idsId=03125999">BHP Appendix 4E and 2026 Annual Report</a> 250 pages</td></tr>
<tr><td>12/08/2026 7:36 am</td><td><a href="/x?idsId=03124134">Appendix 4G and 2026 Corporate Governance Statement</a> 36 pages</td></tr>
</table>"""


class AsxTests(unittest.TestCase):
    def test_announcement_rows(self):
        rows = sources.parse_announcements(ASX_PAGE)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0], {"date": "2026-08-12", "headline": "2026 Annual Report", "ids_id": "03124133", "pages": 452})

    def test_the_annual_report_not_the_notice_or_the_us_filing(self):
        report = sources.choose_annual_report(sources.parse_announcements(ASX_PAGE), NOW)
        self.assertEqual(report["ids_id"], "03124133")

    def test_an_annual_report_announced_with_its_appendix_4e(self):
        # BHP announces the two together, a day before its US 20-F
        report = sources.choose_annual_report(sources.parse_announcements(BHP_PAGE), NOW)
        self.assertEqual((report["ids_id"], report["pages"]), ("03125999", 250))

    def test_the_us_filing_when_it_is_all_there_is(self):
        rows = [r for r in sources.parse_announcements(ASX_PAGE) if "20-F" in r["headline"]]
        self.assertEqual(sources.choose_annual_report(rows, NOW)["ids_id"], "03126614")

    def test_too_old_is_no_report(self):
        rows = [r for r in sources.parse_announcements(ASX_PAGE) if r["date"].startswith("2025")]
        self.assertIsNone(sources.choose_annual_report(rows, datetime(2027, 6, 1)))

    def test_the_pdf_link_must_be_asxs_own(self):
        page = '<input name="pdfURL" value="https://announcements.asx.com.au/asxpdf/20260812/pdf/abc.pdf" type="hidden">'
        self.assertEqual(sources.asx_pdf_url(page), "https://announcements.asx.com.au/asxpdf/20260812/pdf/abc.pdf")
        for bad in ('<input name="pdfURL" value="https://evil.example/abc.pdf">', '<input name="pdfURL" value="http://announcements.asx.com.au/a.pdf">',
                    "<p>no form</p>"):
            with self.assertRaises(sources.SourceUnavailable):
                sources.asx_pdf_url(bad)


BOARD_PAGE = ("Board of Directors\nPaul O'Malley Chair, Independent Non-Executive Director. Director since 2019. Age 62.\n"
              "Other listed company directorships: BlueScope Steel Limited.\nMatt Comyn Managing Director and CEO. Age 50.")


class TextTests(unittest.TestCase):
    def test_edgar_page_breaks_become_pages(self):
        page = "".join(f'<div><p>Page text {i}</p></div><hr style="page-break-after: always">' for i in range(1, 7))
        sections = sources.html_sections(page)
        self.assertEqual(sections[0], ("Page 1", "Page text 1"))
        self.assertEqual(len(sections), 6)

    def test_without_page_breaks_it_is_split_into_parts(self):
        page = "<p>" + "</p><p>".join("word " * 200 for _ in range(10)) + "</p><script>var x = 1;</script>"
        sections = sources.html_sections(page, chunk_chars=2500)
        self.assertTrue(all(label.startswith("Part ") for label, _ in sections))
        self.assertNotIn("var x", " ".join(text for _, text in sections))

    def test_the_board_pages_are_chosen_in_document_order(self):
        sections = [("Page 1", "Revenue grew. Net profit after tax."), ("Page 2", BOARD_PAGE),
                    ("Page 3", "Continued: committee membership, Audit Committee."), ("Page 4", "Glossary of terms."),
                    ("Page 5", "Directors' report. Non-executive directors fees. Director since 2015.")]
        chosen = [label for label, _ in sources.select_passages(sections)]
        self.assertEqual(chosen[:2], ["Page 2", "Page 3"])
        self.assertIn("Page 5", chosen)
        self.assertNotIn("Page 1", chosen)
        self.assertEqual(chosen, sorted(chosen, key=lambda l: int(l.split()[1])))

    def test_the_budget_is_kept(self):
        sections = [(f"Page {i}", BOARD_PAGE * 20) for i in range(1, 50)]
        chosen = sources.select_passages(sections, budget_chars=10_000)
        self.assertLessEqual(sum(len(t) for _, t in chosen), 10_000)
        self.assertEqual(sources.select_passages([("Page 1", "Nothing about the company's governance.")]), [])


class SelectionTests(unittest.TestCase):
    """Choosing the pages that describe the board (what the seed run found wrong, #113)."""

    BIO = "Jane Doe | Director since 2019 | Age: 61. Other public company directorships: Acme Corp. Committees: Audit."
    BYLAWS = "Section 10. A director may be elected at any meeting. Nomination of candidates to serve as director. " * 40
    COMP = "Director compensation: fees $120,000 stock awards $200,000 total $320,000 " + "1 2 3 4 5 6 7 8 9 0 " * 60

    def test_numbers_pages_score_below_biographies(self):
        self.assertGreater(sources.section_score(self.BIO * 3), sources.section_score(self.COMP))

    def test_biography_pages_come_first_even_when_other_pages_mention_directors_more(self):
        sections = [("Page 1", "Cover page"), ("Page 2", self.BIO * 2), ("Page 3", self.BIO * 2), ("Page 4", self.BYLAWS),
                    ("Page 5", self.BYLAWS), ("Page 6", self.BIO * 2)]
        chosen = [label for label, _ in sources.select_passages(sections, budget_chars=len(self.BIO) * 7)]
        for label in ("Page 2", "Page 3", "Page 6"):
            self.assertIn(label, chosen)

    def test_one_giant_page_is_cut_up_so_its_board_part_can_be_chosen(self):
        filler = "Risk factors and business description.\n" * 400
        giant = [("Page 1", filler + "\n" + (self.BIO + "\n") * 30 + filler)]
        parts = sources.split_large(giant, limit=12_000)
        self.assertTrue(all(len(text) <= 12_000 * 0.8 for _, text in parts))
        self.assertEqual(parts[0][0], "Page 1, part 1")
        chosen = sources.select_passages(giant)
        self.assertTrue(chosen)
        self.assertTrue(all("Director since" in text or "Risk" in text for _, text in chosen))
        self.assertIn("Director since", " ".join(text for _, text in chosen))

    def test_small_sections_are_left_alone(self):
        sections = [("Page 1", "short"), ("Page 2", "also short")]
        self.assertEqual(sources.split_large(sections), sections)


class InformationStatementTests(unittest.TestCase):
    def test_def_14c_when_there_is_no_proxy(self):
        found = sources.choose_filings(submissions(("10-K", "2026-02-23", "0001-26-1", "k.htm"),
                                                   ("DEF 14C", "2026-03-20", "0001-26-2", "i.htm")), 922621, NOW)
        self.assertEqual([f["kind"] for f in found], ["DEF 14C"])

    def test_every_recent_proxy_newest_first_and_the_form_preference(self):
        found = sources.choose_filings(submissions(
            ("DEF 14A", "2026-10-05", "0001-26-3", "special.htm"), ("DEF 14A", "2026-04-30", "0001-26-2", "annual.htm"),
            ("DEF 14A", "2024-04-30", "0001-24-1", "old.htm"), ("DEF 14C", "2026-06-01", "0001-26-4", "c.htm")), 1, NOW)
        self.assertEqual([f["filed"] for f in found], ["2026-10-05", "2026-04-30"])  # the old one is out; 14C only without 14A


class WikidataTests(unittest.TestCase):
    def test_answer_grouped_by_person(self):
        answer = {"results": {"bindings": [
            {"person": {"value": "http://www.wikidata.org/entity/Q47544149"}, "personLabel": {"value": "Matt Comyn"},
             "alias": {"value": "Matthew Comyn"}, "article": {"value": "https://en.wikipedia.org/wiki/Matt_Comyn"}},
            {"person": {"value": "http://www.wikidata.org/entity/Q47544149"}, "personLabel": {"value": "Matt Comyn"},
             "alias": {"value": "Matthew Ian Comyn"}},
            {"person": {"value": "http://www.wikidata.org/entity/Q106028933"}, "personLabel": {"value": "Q106028933"}},
        ]}}
        found = {p["id"]: p for p in sources.parse_wikidata(answer)}
        self.assertEqual(found["Q47544149"]["aliases"], ["Matthew Comyn", "Matthew Ian Comyn"])
        self.assertEqual(found["Q47544149"]["article"], "https://en.wikipedia.org/wiki/Matt_Comyn")
        self.assertIsNone(found["Q106028933"]["label"])  # no English label: it can't match a name

    def test_company_lookup(self):
        self.assertEqual(sources.wikidata_company_clause("US", "AAPL", 320193), '?company wdt:P5531 "0000320193" .')
        self.assertIn('pq:P249 "CBA"', sources.wikidata_company_clause("ASX", "CBA"))
        self.assertIsNone(sources.wikidata_company_clause("ASX", 'X" . } DROP'))  # nothing odd gets into the query
        self.assertIsNone(sources.wikidata_company_clause("US", "AAPL"))


# ---------- directors.py ----------

PASSAGES = [("Page 66", BOARD_PAGE), ("Page 68", "Peter Harmer Independent Non-Executive Director. Director since 2021. "
                                                 "Other directorships: nib holdings limited, AUB Group Limited (Chair).")]


def director(name, **extra):
    base = {"name": name, "role": "director", "independent": True, "leaving": False, "appointed_year": 2021, "age": 65,
            "committees": ["Audit"], "other_boards": [], "location": "Page 68", "quote": None}
    return {**base, **extra}


class CleanTests(unittest.TestCase):
    def test_a_name_not_in_the_document_is_dropped(self):
        kept, warnings = directors.clean_directors({"directors": [director("Peter Harmer"), director("Jane Invented")]}, PASSAGES, 2026)
        self.assertEqual([d["name"] for d in kept], ["Peter Harmer"])
        self.assertIn("Jane Invented", warnings[0])

    def test_an_initial_before_the_surname_counts(self):
        passages = [("Page 1", "Director P. Harmer was appointed in 2021.")]
        kept, _ = directors.clean_directors({"directors": [director("Peter Harmer", location="Page 1")]}, passages, 2026)
        self.assertEqual(len(kept), 1)

    def test_a_quote_not_in_the_document_is_removed(self):
        kept, warnings = directors.clean_directors({"directors": [
            director("Paul O’Malley", role="chair", location="Page 66", quote="Paul O'Malley Chair, Independent Non-Executive Director"),
            director("Matt Comyn", location="Page 66", quote="Matt Comyn founded the bank in 1911"),
        ]}, PASSAGES, 2026)
        self.assertEqual(kept[0]["quote"], "Paul O'Malley Chair, Independent Non-Executive Director")
        self.assertIsNone(kept[1]["quote"])
        self.assertTrue(any("quote" in w for w in warnings))

    def test_unknown_locations_odd_numbers_and_duplicates(self):
        kept, _ = directors.clean_directors({"directors": [
            director("Peter Harmer", location="Page 999", appointed_year=2031, age=7, role="emperor"),
            director("Peter Harmer"),
        ]}, PASSAGES, 2026)
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0]["location"], kept[0]["appointed_year"], kept[0]["age"], kept[0]["role"]), (None, None, None, "director"))


class FakeMessages:
    def __init__(self, answer, stop_reason="end_turn"):
        self.answer, self.stop_reason, self.calls = answer, stop_reason, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, usage=SimpleNamespace(input_tokens=30000, output_tokens=1500),
                               content=[SimpleNamespace(type="text", text=json.dumps(self.answer))])


class FakeClient:
    def __init__(self, answer, **kwargs):
        self.messages = FakeMessages(answer, **kwargs)


DOC = {"source": "sec", "kind": "DEF 14A", "title": "Apple Inc. DEF 14A (2026-01-08)", "filed": "2026-01-08",
       "url": "https://www.sec.gov/Archives/edgar/data/320193/x/p.htm", "cik": 320193}


class ExtractTests(StoreTestCase):
    def test_the_call_uses_the_fixed_model_and_answer_shape_and_logs_usage(self):
        client = FakeClient({"directors": [director("Peter Harmer")]})
        seats, _ = run(directors.extract("Commonwealth Bank", DOC, PASSAGES, client, con_id=7))
        self.assertEqual(seats[0]["name"], "Peter Harmer")
        call = client.messages.calls[0]
        self.assertEqual(call["model"], "claude-haiku-5-5")
        self.assertEqual(call["output_config"]["effort"], "low")
        self.assertEqual(call["output_config"]["format"]["schema"]["properties"]["directors"]["items"]["properties"]["location"]["enum"],
                         ["Page 66", "Page 68"])
        self.assertIn("[[Page 68]]", call["messages"][0]["content"])
        month = usage_store.monthly()
        self.assertEqual(month["by_feature"]["directors"]["calls"], 1)

    def test_a_cut_off_answer_is_logged_and_raises(self):
        with self.assertRaises(RuntimeError):
            run(directors.extract("X", DOC, PASSAGES, FakeClient({"directors": []}, stop_reason="max_tokens")))
        self.assertEqual(usage_store.monthly()["by_feature"]["directors"]["calls"], 1)


class ReadBoardTests(StoreTestCase):
    def read(self, market, symbol, name, answer, document=None, passages=PASSAGES, wikidata=()):
        document = document or {**DOC, "title": f"{name} document"}
        with mock.patch.object(directors, "find_documents", mock.AsyncMock(return_value=[document])), \
                mock.patch.object(directors, "read_document", mock.AsyncMock(return_value=(document, passages))), \
                mock.patch.object(sources, "wikidata_people", mock.AsyncMock(return_value=list(wikidata))):
            return run(directors.read_board(market, symbol, name, client=FakeClient(answer)))

    def test_a_board_is_saved_with_document_links(self):
        result = self.read("ASX", "CBA", "Commonwealth Bank of Australia",
                           {"directors": [director("Paul O’Malley", role="chair", location="Page 66")]},
                           document={"source": "asx", "kind": "Annual Report", "title": "CBA 2026 Annual Report", "filed": "2026-08-12",
                                     "url": "https://www.asx.com.au/asx/v2/statistics/displayAnnouncement.do?idsId=1",
                                     "pdf_url": "https://announcements.asx.com.au/asxpdf/x.pdf"},
                           wikidata=[{"id": "Q1", "label": "Paul O'Malley", "aliases": [], "article": "https://en.wikipedia.org/wiki/P"}])
        self.assertEqual(result["status"], "ready")
        [chair] = result["directors"]
        self.assertEqual(chair["document_url"], "https://announcements.asx.com.au/asxpdf/x.pdf#page=66")
        self.assertEqual((chair["wikidata_id"], chair["wikipedia_url"], chair["person_id"]), ("Q1", "https://en.wikipedia.org/wiki/P", "Q1"))

    def test_also_on_another_board_only_with_corroboration(self):
        self.read("US", "INTC", "Intel Corporation", {"directors": [director("Dion Weisler", location="Page 66"),
                                                                     director("Matt Comyn", location="Page 66")]},
                  passages=[("Page 66", "Dion Weisler, director. Matt Comyn, director.")])
        result = self.read("ASX", "BHP", "BHP Group Limited", {"directors": [
            director("Dion Weisler", location="Page 66", other_boards=["Intel Corporation", "Qantas Airways Limited"]),
            director("Matt Comyn", location="Page 66"),
        ]}, passages=[("Page 66", "Dion Weisler, director. Matt Comyn, director.")])
        weisler, comyn = result["directors"]
        self.assertEqual([(a["symbol"], a["basis"]) for a in weisler["also_on"]], [("INTC", "named_in_document")])
        # Same name, nothing to back it up: a possible match, not a link
        self.assertEqual(comyn["also_on"], [])
        self.assertEqual([a["symbol"] for a in comyn["possible_matches"]], ["INTC"])
        found = directors.person(weisler["person_id"])
        self.assertEqual(sorted(s["symbol"] for s in found["seats"]), ["BHP", "INTC"])

    def test_no_document_is_saved_without_calling_claude(self):
        with mock.patch.object(directors, "find_documents", mock.AsyncMock(side_effect=sources.NoDocument("No proxy"))):
            client = FakeClient({"directors": []})
            result = run(directors.read_board("US", "XYZ", "XYZ Corp", client=client))
        self.assertEqual((result["status"], result["error"]), ("no_document", "No proxy"))
        self.assertEqual(client.messages.calls, [])

    def test_a_download_failure_keeps_the_stored_board(self):
        self.read("US", "AAPL", "Apple Inc.", {"directors": [director("Peter Harmer")]})
        with mock.patch.object(directors, "find_documents", mock.AsyncMock(side_effect=sources.SourceUnavailable("SEC down"))):
            with self.assertRaises(sources.SourceUnavailable):
                run(directors.read_board("US", "AAPL", "Apple Inc.", client=FakeClient({"directors": []})))
        self.assertEqual(len(directors.board("US", "AAPL")["directors"]), 1)

    def test_nothing_found_in_the_document_is_unreadable(self):
        result = self.read("US", "AAPL", "Apple Inc.", {"directors": [director("Jane Invented")]})
        self.assertEqual(result["status"], "unreadable")


class FallbackTests(StoreTestCase):
    """A company's newest proxy can be for a special meeting, with no directors in it."""

    def run_read(self, docs, answers):
        client = FakeClient({"directors": []})
        replies = iter(answers)

        async def create(**kwargs):
            client.messages.calls.append(kwargs)
            return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=1000, output_tokens=100),
                                   content=[SimpleNamespace(type="text", text=json.dumps(next(replies)))])
        client.messages.create = create

        async def read_document(document):
            return document, PASSAGES
        with mock.patch.object(directors, "find_documents", mock.AsyncMock(return_value=docs)), \
                mock.patch.object(directors, "read_document", read_document), \
                mock.patch.object(sources, "wikidata_people", mock.AsyncMock(return_value=[])):
            return run(directors.read_board("US", "MSTR", "Strategy Inc", client=client)), client

    def test_the_next_proxy_is_used_when_the_newest_has_no_directors(self):
        docs = [{**DOC, "title": "special meeting", "filed": "2026-10-05"}, {**DOC, "title": "annual meeting", "filed": "2026-04-30"}]
        result, client = self.run_read(docs, [{"directors": []}, {"directors": [director("Peter Harmer")]}])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["document"]["title"], "annual meeting")
        self.assertEqual(len(client.messages.calls), 2)  # one call per document tried
        self.assertEqual(usage_store.monthly()["by_feature"]["directors"]["calls"], 2)

    def test_stops_at_the_first_proxy_with_directors(self):
        docs = [{**DOC, "title": "newest"}, {**DOC, "title": "older"}]
        result, _ = self.run_read(docs, [{"directors": [director("Peter Harmer")]}])
        self.assertEqual(result["document"]["title"], "newest")
        self.assertEqual(usage_store.monthly()["by_feature"]["directors"]["calls"], 1)

    def test_gives_up_after_three_documents(self):
        docs = [{**DOC, "title": f"proxy {i}"} for i in range(5)]
        result, _ = self.run_read(docs, [{"directors": []}] * 5)
        self.assertEqual((result["status"], result["error"]), ("unreadable", "No directors were found in the document."))
        self.assertEqual(usage_store.monthly()["by_feature"]["directors"]["calls"], directors.MAX_DOCUMENTS)


class NeedsTests(StoreTestCase):
    def test_what_each_market_needs(self):
        with mock.patch.object(directors.config, "anthropic_api_key", return_value=None), \
                mock.patch.object(directors.config, "sec_contact_email", return_value=None):
            self.assertEqual(directors.can_read("US"), ["api_key", "sec_contact_email"])
            self.assertEqual(directors.can_read("ASX"), ["api_key", "asx_terms"])
            self.assertIn("unsupported_market", directors.can_read(None))
        with mock.patch.object(directors.config, "anthropic_api_key", return_value="k"), \
                mock.patch.object(directors.config, "sec_contact_email", return_value="a@b.c"):
            self.assertEqual(directors.can_read("US"), [])
            directors.accept_asx_terms(True)
            self.assertEqual(directors.can_read("ASX"), [])
            directors.accept_asx_terms(False)
            self.assertEqual(directors.can_read("ASX"), ["asx_terms"])


class SeedTests(StoreTestCase):
    def seed(self, built_at, filed, symbol="AAPL", market="US", name="Peter Harmer"):
        seed = Path(self.folder.name) / f"seed-{built_at}.json"
        seed.write_text(json.dumps({"meta": {"built_at": built_at}, "companies": [{
            "market": market, "symbol": symbol, "status": "ready", "error": None, "model": "claude-haiku-5-5",
            "document": {**DOC, "company_name": "Apple Inc.", "filed": filed},
            "seats": [{**directors.clean_directors({"directors": [director(name)]}, PASSAGES, 2026)[0][0]}],
        }]}))
        return seed

    def test_merged_once_and_newer_documents_only(self):
        self.assertEqual(directors.merge_seed(self.seed("v1", "2026-01-08")), 1)
        self.assertEqual(directors.merge_seed(self.seed("v1", "2026-01-08")), 0)  # same seed: skipped
        self.assertEqual(directors.merge_seed(self.seed("v2", "2025-01-01")), 0)  # older than what's stored
        self.assertEqual(directors.merge_seed(self.seed("v3", "2027-01-08")), 1)
        self.assertEqual(directors.board("US", "AAPL")["document"]["filed"], "2027-01-08")

    def test_asx_boards_are_never_taken_from_a_seed(self):
        self.assertEqual(directors.merge_seed(self.seed("v1", "2026-08-12", symbol="CBA", market="ASX")), 0)
        self.assertIsNone(directors.board("ASX", "CBA"))

    def test_export_and_merge_round_trip(self):
        directors.save("US", "AAPL", {**DOC, "company_name": "Apple Inc."},
                       directors.clean_directors({"directors": [director("Peter Harmer")]}, PASSAGES, 2026)[0])
        directors.save("ASX", "CBA", {**DOC, "company_name": "CBA"}, [])
        out = Path(self.folder.name) / "out.json"
        self.assertEqual(directors.export_seed(out), 1)  # US only
        directors.DB_PATH.unlink()
        self.assertEqual(directors.merge_seed(out), 1)
        self.assertEqual(directors.board("US", "AAPL")["directors"][0]["name"], "Peter Harmer")


class BundledSeedTests(StoreTestCase):
    """The seed that ships with the app (seed/directors.json)."""

    def test_us_only_complete_and_loadable(self):
        data = json.loads(directors.SEED_PATH.read_text())
        companies = data["companies"]
        self.assertGreater(len(companies), 500)
        self.assertEqual({c["market"] for c in companies}, {"US"})  # never ASX documents (ASX's terms)
        for c in companies:
            self.assertIn(c["status"], ("ready", "no_document", "unreadable"))
            if c["status"] == "ready":
                self.assertTrue(c["document"]["url"].startswith("https://www.sec.gov/"), c["symbol"])
                self.assertTrue(c["seats"], c["symbol"])
                for seat in c["seats"]:
                    self.assertTrue(seat["match_key"], (c["symbol"], seat["name"]))
        self.assertEqual(directors.merge_seed(directors.SEED_PATH), sum(1 for c in companies))
        self.assertEqual(len(directors.board("US", "AAPL")["directors"]) > 5, True)

    def test_no_contact_email_in_it(self):
        self.assertNotIn("@", "".join(c["document"].get("url") or "" for c in json.loads(directors.SEED_PATH.read_text())["companies"]))


class NewerDocumentTests(StoreTestCase):
    def test_a_newer_proxy_is_marked_without_calling_claude(self):
        directors.save("US", "AAPL", {**DOC, "company_name": "Apple Inc."}, [])
        newer = {**DOC, "title": "Apple Inc. DEF 14A (2027-01-07)", "url": "https://www.sec.gov/new.htm", "filed": "2027-01-07"}
        later = datetime.now(timezone.utc).replace(year=datetime.now().year + 1)
        with mock.patch.object(directors.config, "sec_contact_email", return_value="a@b.c"), \
                mock.patch.object(directors, "find_document", mock.AsyncMock(return_value=newer)):
            self.assertEqual(run(directors.check_for_newer(later)), 1)
            self.assertEqual(directors.board("US", "AAPL")["newer_document"]["url"], "https://www.sec.gov/new.htm")
            # Checked just now: not again for a week
            self.assertEqual(run(directors.check_for_newer(later)), 0)

    def test_skipped_without_the_source_set_up(self):
        directors.save("ASX", "CBA", {**DOC, "company_name": "CBA"}, [])
        later = datetime.now(timezone.utc).replace(year=datetime.now().year + 1)
        with mock.patch.object(directors, "find_document", mock.AsyncMock()) as find:
            self.assertEqual(run(directors.check_for_newer(later)), 0)  # ASX terms not accepted
        find.assert_not_called()


# ---------- routes ----------

class RouteTests(StoreTestCase):
    def call(self, coro_or_value):
        return run(coro_or_value) if asyncio.iscoroutine(coro_or_value) else coro_or_value

    def setUp(self):
        super().setUp()
        # Company names come from Yahoo when it answers; here it doesn't
        patcher = mock.patch.object(routes, "yahoo_info", mock.AsyncMock(side_effect=RuntimeError("offline")))
        patcher.start()
        self.addCleanup(patcher.stop)

    def contract(self, exchange="NASDAQ", symbol="AAPL"):
        contract = SimpleNamespace(symbol=symbol, primaryExchange=exchange, exchange=exchange)
        return mock.patch.object(routes, "get_contract_info", mock.AsyncMock(return_value=(contract, "APPLE INC")))

    def test_the_full_company_name_comes_from_yahoo(self):
        contract = SimpleNamespace(symbol="CBA", primaryExchange="ASX", exchange="ASX")
        with mock.patch.object(routes, "get_contract_info", mock.AsyncMock(return_value=(contract, "COMMONWEALTH BANK OF AUSTRAL"))), \
                mock.patch.object(routes, "yahoo_info", mock.AsyncMock(return_value={"longName": "Commonwealth Bank of Australia"})):
            self.assertEqual(run(routes.company(4036818)), ("ASX", "CBA", "Commonwealth Bank of Australia"))
        with self.contract(exchange="ASX", symbol="CBA"):
            self.assertEqual(run(routes.company(4036818))[2], "Apple Inc")  # Yahoo down: IB's name

    def test_a_board_not_read_says_what_is_needed(self):
        with self.contract(), mock.patch.object(directors.config, "anthropic_api_key", return_value=None), \
                mock.patch.object(directors.config, "sec_contact_email", return_value=None):
            result = run(routes.get_board(265598))
        self.assertEqual((result["status"], result["can_read"]), ("not_read", False))
        self.assertEqual([n["id"] for n in result["needs"]], ["api_key", "sec_contact_email"])

    def test_reading_without_what_is_needed_is_a_409(self):
        request = SimpleNamespace(headers={})
        with self.contract(exchange="ASX", symbol="CBA"), mock.patch.object(directors.config, "anthropic_api_key", return_value="k"):
            with self.assertRaises(HTTPException) as caught:
                run(routes.read_board(4036818, request))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("ASX allows for personal use only", caught.exception.detail)

    def test_a_source_failure_is_a_502(self):
        request = SimpleNamespace(headers={})
        with self.contract(), mock.patch.object(directors.config, "anthropic_api_key", return_value="k"), \
                mock.patch.object(directors.config, "sec_contact_email", return_value="a@b.c"), \
                mock.patch.object(directors, "read_board", mock.AsyncMock(side_effect=sources.SourceUnavailable("SEC is down"))):
            with self.assertRaises(HTTPException) as caught:
                run(routes.read_board(265598, request))
        self.assertEqual((caught.exception.status_code, caught.exception.detail), (502, "SEC is down"))

    def test_asx_terms_are_recorded_and_withdrawn(self):
        request = SimpleNamespace(headers={})
        self.assertIsNone(routes.asx_terms()["accepted_at"])
        self.assertIsNotNone(routes.change_asx_terms(routes.AsxTerms(accept=True), request)["accepted_at"])
        self.assertIsNone(routes.change_asx_terms(routes.AsxTerms(accept=False), request)["accepted_at"])

    def test_unknown_person_is_a_404(self):
        with self.assertRaises(HTTPException) as caught:
            routes.get_person("Q123")
        self.assertEqual(caught.exception.status_code, 404)


class AppConfigTests(unittest.TestCase):
    def test_the_app_reads_the_bundled_address_and_development_reads_env(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "app_config.json"
            path.write_text(json.dumps({"sec_contact_email": "bundled@example.com"}))
            with mock.patch.object(directors.config, "APP_CONFIG_PATH", path), mock.patch.object(directors.config, "IN_APP", True), \
                    mock.patch.dict(directors.config.SETTINGS, {}, clear=True):
                self.assertEqual(directors.config.sec_contact_email(), "bundled@example.com")
            with mock.patch.object(directors.config, "IN_APP", False), mock.patch.dict(os.environ, {"SEC_CONTACT_EMAIL": "dev@example.com"}):
                self.assertEqual(directors.config.sec_contact_email(), "dev@example.com")
            path.unlink()
            with mock.patch.object(directors.config, "APP_CONFIG_PATH", path), mock.patch.object(directors.config, "IN_APP", True), \
                    mock.patch.dict(directors.config.SETTINGS, {}, clear=True):
                self.assertIsNone(directors.config.sec_contact_email())


if __name__ == "__main__":
    unittest.main()
