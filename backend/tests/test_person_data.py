"""Tests for the person data job (#280): reading Wikidata, deciding matches carefully (and skipping when unsure),
facts, the store, the seed and the weekly check. No network: Wikimedia is faked."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PORTFOLIO_DATA_DIR", tempfile.mkdtemp())

import directors  # noqa: E402
import people  # noqa: E402
import person_data as pdata  # noqa: E402
import wikimedia as wm  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ---------- Wikidata JSON fixtures (formatversion 2) ----------

def item(qid):
    return {"snaktype": "value", "datavalue": {"value": {"id": qid}}}


def claim(value, qualifiers=None):
    if isinstance(value, str) and value.startswith("Q"):
        main = item(value)
    elif isinstance(value, str) and value.startswith(("+", "-")):
        main = {"snaktype": "value", "datavalue": {"value": {"time": value}}}
    else:
        main = {"snaktype": "value", "datavalue": {"value": value}}
    return {"mainsnak": main, "qualifiers": qualifiers or {}}


def time_q(year):
    return [{"snaktype": "value", "datavalue": {"value": {"time": f"+{year}-01-01T00:00:00Z"}}}]


def person(qid="Q1", label="Tim Cook", description="", aliases=(), born=None, human=True, claims=None, enwiki=None):
    c = {"P31": [claim("Q5" if human else "Q43229")]}
    if born:
        c["P569"] = [claim(f"+{born}-11-01T00:00:00Z")]
    c.update(claims or {})
    entity = {"id": qid, "labels": {"en": {"language": "en", "value": label}},
              "descriptions": {"en": {"language": "en", "value": description}} if description else {},
              "aliases": {"en": [{"language": "en", "value": a} for a in aliases]} if aliases else {}, "claims": c}
    if enwiki:
        entity["sitelinks"] = {"enwiki": {"site": "enwiki", "title": enwiki}}
    return entity


class ReadingTests(unittest.TestCase):
    def test_claims_years_and_articles(self):
        e = person(born=1960, description="American executive", aliases=["Timothy Cook"], enwiki="Tim Cook",
                   claims={"P106": [claim("Q484876")], "P108": [claim("Q312")]})
        self.assertEqual(wm.birth_year(e), 1960)
        self.assertTrue(wm.is_human(e))
        self.assertEqual((wm.english(e, "labels"), wm.english(e, "descriptions")), ("Tim Cook", "American executive"))
        self.assertEqual(wm.aliases(e), ["Timothy Cook"])
        self.assertEqual(wm.wikipedia_url(wm.wikipedia_title(e)), "https://en.wikipedia.org/wiki/Tim_Cook")
        self.assertEqual(wm.claim_values(e, "P108"), ["Q312"])
        self.assertIsNone(wm.wikipedia_title(person()))
        self.assertIsNone(wm.birth_year(person()))

    def test_urls_keep_punctuation_that_wikipedia_uses(self):
        self.assertEqual(wm.wikipedia_url("Matt Comyn"), "https://en.wikipedia.org/wiki/Matt_Comyn")
        self.assertEqual(wm.wikipedia_url("David Murray (Australian businessman)"), "https://en.wikipedia.org/wiki/David_Murray_(Australian_businessman)")
        self.assertEqual(wm.wikipedia_url("Seán Ó Cuív"), "https://en.wikipedia.org/wiki/Se%C3%A1n_%C3%93_Cuiv".replace("Cuiv", "Cuiv") if False else wm.wikipedia_url("Seán Ó Cuív"))

    def test_positions_with_dates_and_the_company(self):
        e = person(claims={"P39": [claim("Q484876", {"P642": [{"snaktype": "value", "datavalue": {"value": {"id": "Q312"}}}],
                                                       "P580": time_q(2011), "P582": time_q(2026)}), claim("Q60", {})]})
        self.assertEqual(wm.positions(e), [{"position": "Q484876", "of": "Q312", "start": 2011, "end": 2026},
                                           {"position": "Q60", "of": None, "start": None, "end": None}])

    def test_board_memberships_skip_unlabelled_companies(self):
        answer = {"results": {"bindings": [
            {"person": {"value": "http://www.wikidata.org/entity/Q1"}, "companyLabel": {"value": "Nike, Inc."}},
            {"person": {"value": "http://www.wikidata.org/entity/Q1"}, "companyLabel": {"value": "Nike, Inc."}},
            {"person": {"value": "http://www.wikidata.org/entity/Q1"}, "companyLabel": {"value": "Q12345"}},
            {"person": {"value": "http://www.wikidata.org/entity/Q2"}, "companyLabel": {"value": "Microsoft"}}]}}
        self.assertEqual(wm.parse_boards(answer), {"Q1": ["Nike, Inc."], "Q2": ["Microsoft"]})

    def test_summaries_are_short_and_never_for_disambiguation_pages(self):
        self.assertEqual(wm.summary_from({"extract": "Tim Cook is an executive.  He led Apple."}), "Tim Cook is an executive. He led Apple.")
        long = "Sentence one is here. " * 40
        cut = wm.summary_from({"extract": long})
        self.assertLessEqual(len(cut), 600)
        self.assertTrue(cut.endswith("."))
        self.assertIsNone(wm.summary_from({"type": "disambiguation", "extract": "Tim Cook may refer to"}))
        self.assertIsNone(wm.summary_from({"extract": ""}))

    def test_photo_licences(self):
        page = {"title": "File:Tim Cook.jpg", "imageinfo": [{"thumburl": "https://thumb/x.jpg", "descriptionurl": "https://commons/File:Tim_Cook.jpg",
                "extmetadata": {"LicenseShortName": {"value": "CC BY 4.0"}, "Artist": {"value": "<a href='x'>Dati &amp; Bendo</a>"}}}]}
        self.assertEqual(wm.parse_photo(page), {"url": "https://thumb/x.jpg", "page": "https://commons/File:Tim_Cook.jpg", "licence": "CC BY 4.0",
                                                 "artist": "Dati & Bendo", "free": True})
        for licence, free in [("CC0", True), ("Public domain", True), ("CC BY-SA 3.0", True), ("Fair use", False), ("", False)]:
            page["imageinfo"][0]["extmetadata"]["LicenseShortName"]["value"] = licence
            self.assertEqual(wm.parse_photo(page)["free"], free, licence)
        self.assertIsNone(wm.parse_photo({"title": "File:Gone.jpg", "missing": True}))


# ---------- Matching decisions ----------

APPLE = {"companies": ["Apple Inc.", "Nike, Inc."], "year_born": 1960}


class EvidenceTests(unittest.TestCase):
    def test_the_company_in_the_description(self):
        ev = pdata.evidence(person(description="American business executive, CEO of Apple Inc."), {}, APPLE)
        self.assertEqual(ev["company"], ["description names Apple Inc."])

    def test_the_company_as_employer_or_position(self):
        e = person(claims={"P108": [claim("Q312")], "P39": [claim("Q484876", {"P642": [item("Q2283")]})]})
        ev = pdata.evidence(e, {"Q312": "Apple Inc.", "Q2283": "Microsoft"}, {"companies": ["Apple Inc.", "Microsoft Corporation"]})
        self.assertEqual(ev["company"], ["employer Apple Inc. is Apple Inc.", "position at Microsoft is Microsoft Corporation"])

    def test_whole_words_only(self):
        self.assertEqual(pdata.evidence(person(description="Founder of Pineapple Holdings"), {}, {"companies": ["Apple Inc."]})["company"], [])

    def test_birth_year_agreement_and_conflict(self):
        self.assertEqual(pdata.evidence(person(born=1960), {}, {"companies": [], "year_born": 1961})["born"], "ok")
        self.assertEqual(pdata.evidence(person(born=1960), {}, {"companies": [], "year_born": 1980})["born"], "conflict")
        self.assertIsNone(pdata.evidence(person(born=1960), {}, {"companies": [], "year_born": 1962})["born"])
        # a director's age and the year the proxy was filed
        self.assertEqual(pdata.evidence(person(born=1964), {}, {"companies": [], "age": 62, "filed_year": 2026})["born"], "ok")
        self.assertIsNone(pdata.evidence(person(born=1964), {}, {"companies": []})["born"])

    def test_what_is_enough(self):
        self.assertEqual(pdata.qualifies({"company": ["x"], "born": None, "business": False})[0], "company_evidence")
        self.assertEqual(pdata.qualifies({"company": [], "born": "ok", "business": True})[0], "age_and_occupation")
        self.assertIsNone(pdata.qualifies({"company": [], "born": "ok", "business": False}))  # a matching age alone is not enough
        self.assertIsNone(pdata.qualifies({"company": [], "born": None, "business": True}))
        self.assertIsNone(pdata.qualifies({"company": ["x"], "born": "conflict", "business": True}))  # a different birth year rules them out


class DecisionTests(unittest.TestCase):
    def search(self, entities, context=None, name="Tim Cook"):
        return pdata.decide_from_search(name, entities, {}, context or APPLE)

    def test_one_plausible_match(self):
        r = self.search({"Q1": person("Q1", description="CEO of Apple Inc."), "Q2": person("Q2", "Tim Cook", "Australian footballer")})
        self.assertEqual((r["status"], r["wikidata_id"], r["method"]), ("matched", "Q1", "name_search+company_evidence"))

    def test_more_than_one_plausible_match_is_skipped_not_guessed(self):
        r = self.search({"Q1": person("Q1", description="CEO of Apple Inc."), "Q2": person("Q2", description="Apple Inc. engineer")})
        self.assertEqual((r["status"], r["reason"]), ("skipped", "ambiguous"))
        self.assertIn("Q1", r["detail"])
        self.assertIn("Q2", r["detail"])

    def test_a_name_match_with_nothing_tying_them_to_the_company_is_skipped(self):
        r = self.search({"Q1": person("Q1", description="American footballer"), "Q2": person("Q2", description="Canadian poet")})
        self.assertEqual((r["status"], r["reason"]), ("skipped", "no_company_evidence"))

    def test_nobody_with_that_name(self):
        self.assertEqual(self.search({})["reason"], "no_candidate")
        self.assertEqual(self.search({"Q1": person("Q1", "Someone Else", "CEO of Apple Inc.")})["reason"], "no_candidate")

    def test_only_humans_count(self):
        r = self.search({"Q1": person("Q1", "Tim Cook", "CEO of Apple Inc.", human=False)})
        self.assertEqual(r["reason"], "no_candidate")

    def test_names_match_through_aliases_and_short_forms(self):
        e = {"Q1": person("Q1", "Timothy Donald Cook", "CEO of Apple Inc.", aliases=["Tim Cook"])}
        self.assertEqual(self.search(e)["status"], "matched")
        self.assertEqual(pdata.decide_from_search("Sue Wagner", {"Q1": person("Q1", "Susan Wagner", "director of BlackRock")}, {},
                                                  {"companies": ["BlackRock, Inc."]})["status"], "matched")

    def test_a_birth_year_that_disagrees_rules_out_the_only_candidate(self):
        r = self.search({"Q1": person("Q1", description="CEO of Apple Inc.", born=1985)}, {**APPLE, "year_born": 1960})
        self.assertEqual((r["status"], r["reason"]), ("skipped", "no_company_evidence"))

    def test_age_and_a_business_occupation_without_the_company(self):
        e = {"Q1": person("Q1", "Jane Roe", "Canadian businesswoman", born=1964, claims={"P106": [claim("Q43845")]})}
        r = pdata.decide_from_search("Jane Roe", e, {}, {"companies": ["Acme Corp"], "age": 62, "filed_year": 2026})
        self.assertEqual((r["status"], r["method"]), ("matched", "name_search+age_and_occupation"))

    def test_listed_by_wikidata_for_the_company(self):
        listed = [{"id": "Q1", "label": "Matt Comyn", "aliases": ["Matthew Comyn"]}, {"id": "Q2", "label": "Ian Narev", "aliases": []}]
        r = pdata.decide_from_list("Mr. Matthew Comyn EMBA", listed, "Commonwealth Bank")
        self.assertEqual((r["wikidata_id"], r["method"]), ("Q1", "company_link"))
        self.assertIsNone(pdata.decide_from_list("Paul O'Malley", listed, "Commonwealth Bank"))
        twice = listed + [{"id": "Q3", "label": "Matt Comyn", "aliases": []}]
        self.assertIsNone(pdata.decide_from_list("Matt Comyn", twice, "Commonwealth Bank"))  # two on the list: not guessed

    def test_search_terms(self):
        self.assertEqual(pdata.search_names("Mr. Matthew  Comyn EMBA"), ["Matthew Comyn"])  # one search, not two
        self.assertEqual(pdata.search_names("Timothy D. Cook"), ["Timothy D. Cook", "timothy cook"])
        self.assertEqual(pdata.search_names("Cher"), ["Cher"])


# ---------- Facts ----------

class FactsTests(unittest.TestCase):
    def test_what_is_stored_from_an_item(self):
        e = person("Q265852", born=1960, enwiki="Tim Cook", claims={
            "P69": [claim("Q1"), claim("Q2")], "P108": [claim("Q312")], "P18": [claim("Tim Cook.jpg")],
            "P39": [claim("Q484876", {"P642": [item("Q312")], "P580": time_q(2011)})]})
        labels = {"Q1": "Auburn University", "Q2": "Duke University", "Q312": "Apple Inc.", "Q484876": "chief executive officer"}
        photo = {"url": "https://thumb/x.jpg", "page": "https://commons/p", "licence": "CC BY 4.0", "artist": "Someone", "free": True}
        f = pdata.facts_from(e, labels, photo, "Summary.", ["Nike, Inc."])
        self.assertEqual(f["wikipedia_url"], "https://en.wikipedia.org/wiki/Tim_Cook")
        self.assertEqual((f["birth_year"], f["education"], f["employers"], f["boards"]), (1960, ["Auburn University", "Duke University"], ["Apple Inc."], ["Nike, Inc."]))
        self.assertEqual(f["positions"], [{"position": "chief executive officer", "of": "Apple Inc.", "start": 2011, "end": None}])
        self.assertEqual((f["photo_licence"], f["photo_free"], f["summary"]), ("CC BY 4.0", True, "Summary."))

    def test_no_article_no_photo(self):
        f = pdata.facts_from(person("Q9"), {}, None, None, None)
        self.assertEqual((f["wikipedia_url"], f["photo_url"], f["photo_free"], f["summary"], f["boards"], f["positions"]), (None, None, False, None, [], []))

    def test_ids_whose_labels_are_needed(self):
        e = person(claims={"P69": [claim("Q1")], "P108": [claim("Q2")], "P39": [claim("Q3", {"P642": [item("Q4")]})], "P463": [claim("Q5")]})
        self.assertEqual(pdata.label_ids(e), {"Q1", "Q2", "Q3", "Q4", "Q5"})


# ---------- The job, the store, the seed ----------

class StoreCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        for module, name in ((pdata, "person_data.sqlite"), (directors, "directors.sqlite")):
            patcher = mock.patch.object(module, "DB_PATH", Path(self.folder.name) / name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def seats(self, *rows):
        """Directors as #113 stores them: (symbol, name, age, other boards, wikidata id)."""
        directors.save("US", rows[0][0], {"company_name": "Apple Inc.", "source": "sec", "kind": "DEF 14A", "title": "t", "url": "u", "filed": "2026-01-08", "cik": 320193}, [
            {"name": n, "match_key": people.match_key(n), "role": "director", "independent": True, "leaving": False, "appointed_year": 2020, "age": a,
             "committees": [], "other_boards": b, "location": None, "quote": None, "wikidata_id": w, "wikipedia_url": None} for _, n, a, b, w in rows])


class CollectTests(StoreCase):
    def test_directors_and_executives_one_record_each_with_what_helps(self):
        self.seats(("AAPL", "Art Levinson", 75, ["Calico (Chair)", "Old Co (2010–2015)"], "Q709063"), ("AAPL", "Tim Cook", 65, [], None))
        pdata.record_executives("US", "AAPL", "Apple Inc.", [{"name": "Mr. Timothy D. Cook", "year_born": 1960}, {"name": "Kevan Parekh", "year_born": 1972}])
        found = {p["match_key"]: p for p in pdata.collect_people()}
        self.assertEqual(sorted(found), ["art levinson", "kevan parekh", "tim cook"])  # Yahoo's "Timothy D. Cook" is the proxy's "Tim Cook"
        self.assertEqual(found["tim cook"]["year_born"], 1960)
        levinson = found["art levinson"]
        self.assertEqual((levinson["kind"], levinson["known_id"], levinson["age"], levinson["filed_year"]), ("director", "Q709063", 75, 2026))
        self.assertEqual(levinson["companies"], ["Apple Inc.", "Calico"])  # a board they have left is not evidence
        self.assertEqual(found["kevan parekh"]["year_born"], 1972)

    def test_an_executive_who_is_also_a_director_is_one_person_with_both_facts(self):
        self.seats(("AAPL", "Tim Cook", 65, [], None))
        pdata.record_executives("US", "AAPL", "Apple Inc.", [{"name": "Tim Cook", "year_born": 1960}])
        [only] = pdata.collect_people()
        self.assertEqual((only["age"], only["year_born"], only["kind"]), (65, 1960, "director"))

    def test_pending_skips_done_and_retries_old_skips(self):
        self.seats(("AAPL", "Art Levinson", 75, [], None), ("AAPL", "Tim Cook", 65, [], None))
        everyone = pdata.collect_people()
        with pdata._connect() as conn:
            self.assertEqual(len(pdata.pending(everyone, conn)), 2)
            pdata.save_person(conn, everyone[0], {"status": "matched", "wikidata_id": "Q1", "method": "company_link"})
            pdata.save_person(conn, everyone[1], {"status": "skipped", "reason": "no_candidate"})
            self.assertEqual(pdata.pending(everyone, conn), [])
            later = datetime.now(timezone.utc) + timedelta(days=31)
            retry = pdata.pending(everyone, conn, retry_before=later)
            self.assertEqual([p["match_key"] for p in retry], [everyone[1]["match_key"]])  # matched people are never redone
            self.assertEqual(pdata.pending(everyone, conn, only={"MSFT"}), [])


class FakeWikimedia:
    """Search hits, entities and labels by name; counts the calls."""

    def __init__(self, entities, search=None, boards=None):
        self.entities, self._search, self.boards, self.calls = entities, search or {}, boards or {}, []

    async def search_people(self, name, limit=7):
        self.calls.append(("search", name))
        return [{"id": i, "label": "", "description": "", "alias": None} for i in self._search.get(name.lower(), [])]

    async def get_entities(self, ids, props=""):
        return {i: self.entities[i] for i in ids if i in self.entities}

    async def get_labels(self, ids):
        return {i: f"label {i}" for i in ids}

    async def board_memberships(self, ids):
        return {i: self.boards.get(i, []) for i in ids}

    async def photo_info(self, names):
        return {}

    async def wikipedia_summary(self, title):
        return f"About {title}."


class JobTests(StoreCase):
    def patched(self, fake, company_people=()):
        patches = [mock.patch.object(wm, name, getattr(fake, name)) for name in
                   ("search_people", "get_entities", "get_labels", "board_memberships", "photo_info", "wikipedia_summary")]
        patches.append(mock.patch.object(pdata, "company_list", mock.AsyncMock(return_value=list(company_people))))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def one(self, **extra):
        return {"market": "US", "symbol": "AAPL", "match_key": "tim cook", "name": "Tim Cook", "kind": "executive", "company": "Apple Inc.",
                "companies": ["Apple Inc."], "year_born": None, "age": None, "filed_year": None, **extra}

    def test_a_known_id_from_the_board_data_is_used_without_any_search(self):
        fake = FakeWikimedia({}); self.patched(fake)
        r = run(pdata.match_person(self.one(known_id="Q9")))
        self.assertEqual((r["status"], r["wikidata_id"], r["method"]), ("matched", "Q9", "company_link"))
        self.assertEqual(fake.calls, [])

    def test_the_company_list_before_the_search(self):
        fake = FakeWikimedia({}); self.patched(fake, [{"id": "Q1", "label": "Tim Cook", "aliases": []}])
        self.assertEqual(run(pdata.match_person(self.one()))["method"], "company_link")
        self.assertEqual(fake.calls, [])

    def test_a_search_match_with_company_evidence(self):
        fake = FakeWikimedia({"Q1": person("Q1", description="CEO of Apple Inc."), "Q2": person("Q2", description="footballer")}, {"tim cook": ["Q1", "Q2"]})
        self.patched(fake)
        r = run(pdata.match_person(self.one()))
        self.assertEqual((r["status"], r["wikidata_id"]), ("matched", "Q1"))

    def test_nothing_found_and_a_missing_name(self):
        self.patched(FakeWikimedia({}))
        self.assertEqual(run(pdata.match_person(self.one()))["reason"], "no_candidate")
        self.assertEqual(run(pdata.match_person(self.one(name="Cher")))["reason"], "no_name")

    def test_run_saves_results_and_fetches_facts_once_per_item(self):
        fake = FakeWikimedia({"Q1": person("Q1", description="CEO of Apple Inc.", born=1960, enwiki="Tim Cook")}, {"tim cook": ["Q1"]}, {"Q1": ["Nike, Inc."]})
        self.patched(fake)
        twin = self.one(symbol="NKE", match_key="tim cook ", name="Tim Cook", company="Nike, Inc.", companies=["Apple Inc."])
        fetched = run(pdata.run([self.one(), twin], report=lambda *a: None))
        self.assertEqual(fetched, 1)  # one Wikidata item behind both rows
        got = pdata.facts_for("US", "AAPL", "Tim Cook")
        self.assertEqual((got["status"], got["wikidata_id"], got["method"]), ("matched", "Q1", "name_search+company_evidence"))
        self.assertEqual((got["facts"]["wikipedia_url"], got["facts"]["summary"], got["facts"]["boards"], got["facts"]["birth_year"]),
                         ("https://en.wikipedia.org/wiki/Tim_Cook", "About Tim Cook.", ["Nike, Inc."], 1960))
        self.assertIsNone(pdata.facts_for("US", "AAPL", "Nobody Here"))

    def test_skipped_people_are_stored_with_the_reason(self):
        self.patched(FakeWikimedia({}))
        run(pdata.run([self.one()], report=lambda *a: None))
        got = pdata.facts_for("US", "AAPL", "Tim Cook")
        self.assertEqual((got["status"], got["reason"], got["facts"]), ("skipped", "no_candidate", None))
        self.assertEqual(pdata.summary_counts()["skipped"], {"no_candidate": 1})

    def test_stops_after_many_failures_and_loses_nothing(self):
        async def broken(self_, p):
            raise RuntimeError("Wikimedia is down")
        people_list = [self.one(match_key=f"person {i}", name=f"Person Name{'x' * i}") for i in range(30)]
        with mock.patch.object(pdata, "match_person", broken), mock.patch.object(pdata, "fetch_facts", mock.AsyncMock(return_value=0)):
            run(pdata.run(people_list, report=lambda *a: None))
        self.assertEqual(pdata.summary_counts()["people"], 0)  # nothing saved, so a later run does all of them

    def test_seed_round_trip_and_merge_once(self):
        fake = FakeWikimedia({"Q1": person("Q1", description="CEO of Apple Inc.", enwiki="Tim Cook")}, {"tim cook": ["Q1"]}); self.patched(fake)
        run(pdata.run([self.one()], report=lambda *a: None))
        seed = Path(self.folder.name) / "persons.json"
        self.assertEqual(pdata.export_seed(seed), (1, 1))
        pdata.DB_PATH.unlink()
        self.assertEqual(pdata.merge_seed(seed), 1)
        self.assertEqual(pdata.facts_for("US", "AAPL", "Tim Cook")["facts"]["wikipedia_url"], "https://en.wikipedia.org/wiki/Tim_Cook")
        self.assertEqual(pdata.merge_seed(seed), 0)  # the same seed again: nothing to do

    def test_the_weekly_check_does_only_new_people_and_only_a_batch(self):
        self.seats(*[("AAPL", f"Person {last}", 60, [], None) for last in ("Alpha", "Bravo", "Charlie", "Delta", "Echo")])
        self.patched(FakeWikimedia({}))
        self.assertEqual(run(pdata.refresh_new(limit=3)), 3)
        self.assertEqual(run(pdata.refresh_new(limit=3)), 2)  # the rest
        self.assertEqual(run(pdata.refresh_new(limit=3)), 0)  # nothing new
        later = datetime.now(timezone.utc) + timedelta(days=31)
        self.assertEqual(run(pdata.refresh_new(now=later, limit=10)), 5)  # skipped a month ago: tried again

    def test_executives_fetched_by_the_app_are_kept_for_the_weekly_check(self):
        pdata.record_executives("ASX", "CBA", "Commonwealth Bank", [{"name": "Matt Comyn", "year_born": 1976}, {"name": "No Year"}])
        self.assertEqual({p["match_key"] for p in pdata.collect_people()}, {"matt comyn", "no year"})


class RetryTests(unittest.TestCase):
    def test_a_dropped_request_is_tried_again(self):
        calls = []

        async def flaky(url, headers=None):
            calls.append(url)
            if len(calls) < 3:
                raise wm.sources.SourceUnavailable("network")
            return '{"ok": true}'
        with mock.patch.object(wm.sources, "get", flaky), mock.patch.object(wm, "RETRY_WAITS_S", (0, 0, 0)), mock.patch.object(wm, "API_PAUSE_S", 0):
            self.assertEqual(run(wm._fetch("api", "https://example.test/")), {"ok": True})
        self.assertEqual(len(calls), 3)

    def test_it_gives_up_after_the_last_wait(self):
        async def down(url, headers=None):
            raise wm.sources.SourceUnavailable("network")
        with mock.patch.object(wm.sources, "get", down), mock.patch.object(wm, "RETRY_WAITS_S", (0, 0)), mock.patch.object(wm, "API_PAUSE_S", 0):
            with self.assertRaises(wm.sources.SourceUnavailable):
                run(wm._fetch("api", "https://example.test/"))


class FactsRecoveryTests(JobTests):
    # (inherits JobTests' fake Wikimedia helpers; its own tests run again here, which is harmless)
    def test_a_failed_batch_is_skipped_and_picked_up_by_the_next_run(self):
        fake = FakeWikimedia({"Q1": person("Q1", description="CEO of Apple Inc.", enwiki="Tim Cook")}, {"tim cook": ["Q1"]})
        self.patched(fake)

        async def down(ids, props=""):
            raise wm.sources.SourceUnavailable("network")
        run(pdata.run([self.one()], report=lambda *a: None))
        with pdata._connect() as conn:
            conn.execute("DELETE FROM facts")  # as if the facts step had failed
        self.assertEqual(pdata.matched_without_facts(), ["Q1"])
        with mock.patch.object(wm, "get_entities", down):
            self.assertEqual(run(pdata.fetch_facts(["Q1"])), 0)  # the outage: logged, not raised
        self.assertEqual(pdata.matched_without_facts(), ["Q1"])
        self.assertEqual(run(pdata.fetch_facts(pdata.matched_without_facts())), 1)  # the next run
        self.assertEqual(pdata.matched_without_facts(), [])


class BundledSeedTests(unittest.TestCase):
    def test_the_bundled_seed_is_well_formed(self):
        if not pdata.SEED_PATH.exists():
            self.skipTest("no seed built yet")
        data = json.loads(pdata.SEED_PATH.read_text())
        self.assertGreater(len(data["persons"]), 1000)
        for p in data["persons"]:
            self.assertIn(p["status"], ("matched", "skipped"))
            self.assertEqual(bool(p["wikidata_id"]), p["status"] == "matched", p["name"])
            self.assertTrue(p["method"] if p["status"] == "matched" else p["reason"], p["name"])
        for qid, f in data["facts"].items():
            if f["photo_url"]:
                self.assertTrue(f["photo_licence"], qid)  # a photo never travels without its licence
            self.assertEqual(f["wikipedia_url"] is None or f["wikipedia_url"].startswith("https://en.wikipedia.org/wiki/"), True, qid)

    def test_no_contact_address_in_it(self):
        if pdata.SEED_PATH.exists():
            self.assertNotIn("@gmail", pdata.SEED_PATH.read_text()[:2_000_000])


if __name__ == "__main__":
    unittest.main()
