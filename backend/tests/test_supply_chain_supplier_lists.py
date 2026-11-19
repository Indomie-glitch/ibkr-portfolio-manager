import asyncio
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import requests

import sec_client
from supply_chain import db, graph, integrity, jobs, resolver, status, supplier_lists as sl, worker
from supply_chain.db import open_graph
from supply_chain.worker import Permanent

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "supplier_lists"
NOW = datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc)
REAL_PDF_PAGES = sl.pdf_pages  # some tests replace it with the fixture pages


def run(coro):
    return asyncio.run(coro)


def fixture_pages(name):
    """Pages of a real list as pypdf's layout mode gives them (cut down: a few pages), split at form feeds."""
    return (FIXTURES / name).read_text(encoding="utf-8").split("\f")


APPLE = fixture_pages("apple-fy2023-pages.txt")  # Apple Supplier List FY2023: cover, pages 3 and 14, the closing page
DELL = fixture_pages("dell-fy2025-pages.txt")    # Dell Public Supplier List (December 2025): pages 1, 9 and 19


def tiny_pdf(lines, created="D:20240417120234-07'00'"):
    """A one-page PDF with text at the given (x, y) places, in a standard font (nothing embedded)."""
    def escape(text):
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = "".join(f"BT /F1 9 Tf {x} {y} Td ({escape(text)}) Tj ET\n" for x, y, text in lines).encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 792 612] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"endstream",
               f"<< /CreationDate ({created}) >>".encode()]
    body, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R /Info 6 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return body


SOURCE = {"slug": "apple-test", "title": "Apple Supplier List", "url": "https://example.com/Apple-Supplier-List.pdf", "format": "pdf",
          "parser": "apple_pdf", "fiscal_year_end": "09-30", "private_companies": True,
          "customer": {"name": "Apple Inc.", "ticker": "AAPL", "market": "US"}}
DELL_SOURCE = {"slug": "dell-test", "title": "Dell Public Supplier List", "url": "https://example.com/dell.pdf", "format": "pdf",
               "parser": "dell_pdf", "fiscal_year_end": "01-31", "private_companies": False,
               "customer": {"name": "Dell Technologies Inc.", "ticker": "DELL", "market": "US"}}


class ReadingApple(unittest.TestCase):
    def setUp(self):
        self.entries = sl.parse_apple(APPLE)
        self.by_name = {e["name"]: e for e in self.entries}

    def test_the_fiscal_year_comes_from_the_list(self):
        self.assertEqual(sl.fiscal_year(APPLE), 2023)

    def test_one_entry_per_supplier_with_its_rows_as_printed(self):
        self.assertEqual(len(self.entries), 10)
        amkor = self.by_name["Amkor Technology Incorporated"]
        self.assertEqual(amkor["quote"], "Amkor Technology Incorporated | Shanghai | China mainland / Laguna, Metro Manila | Philippines / "
                                         "Gwangju, Incheon | South Korea / Taiwan | Taiwan")
        self.assertEqual(amkor["locations"][1], "Laguna, Metro Manila, Philippines")
        self.assertEqual(amkor["locator"], "page 2, row 2")

    def test_a_places_cell_that_runs_onto_a_second_line_is_one_cell(self):
        murata = self.by_name["Murata Manufacturing Company Limited"]
        japan = next(loc for loc in murata["locations"] if loc.endswith("Japan"))
        self.assertIn("Miyazaki, Nagano, Okayama", japan)
        self.assertEqual(len(murata["locations"]), 10)

    def test_kerned_names_come_out_whole(self):
        self.assertIn("Amphenol Corporation", self.by_name)  # a plain extraction gives "T echnology"-style splits
        self.assertNotIn("T echnology", " ".join(self.by_name))

    def test_pages_without_the_table_give_nothing(self):
        self.assertEqual(sl.parse_apple([APPLE[0], APPLE[-1]]), [])


class ReadingDell(unittest.TestCase):
    def setUp(self):
        self.entries = sl.parse_dell(DELL)

    def test_dates(self):
        self.assertEqual(sl.fiscal_year(DELL), 2025)
        self.assertEqual(sl.published_on(DELL), "2025-12-01")

    def test_one_entry_per_facility(self):
        self.assertEqual(len(self.entries), 24)
        self.assertEqual({e["supplier_type"] for e in self.entries},
                         {"Final Assembly and/or Original Design Manufacturers", "Other direct material suppliers"})
        self.assertEqual([e["name"] for e in self.entries[:4]], ["Celestica", "Celestica", "Celestica", "Compal"])

    def test_an_address_split_in_pieces_stays_in_the_address(self):
        celestica = self.entries[0]
        self.assertEqual(celestica["address"], "204 & 215 Zone C, Savan‐SENO Special Economic Zone, Road No-9, Nongdurn Village, Kaison "
                                               "Phomviharn District, Savannakhet Province, Laos PDR")
        self.assertEqual(celestica["category"], "Parts / Components")
        inventec = next(e for e in self.entries if e["name"] == "Inventec")
        self.assertTrue(inventec["address"].startswith("789 Puxing Road, Caohejing Export Processing Zone, Pujiang, Minhang"))

    def test_quote_and_locator(self):
        pegatron = next(e for e in self.entries if e["name"] == "Pegatron")
        self.assertEqual(pegatron["quote"], "Pegatron | 5 Shing Yeh Street, Kwei Shan District, Taoyuan, Taiwan | Latitude Rugged Notebooks, "
                                            "Dell Pro Rugged Laptops, Accessories | Final Assembly and/or Original Design Manufacturers")
        self.assertEqual(pegatron["locator"], "page 2, row 6")

    def test_the_sustainability_column_is_not_part_of_the_quote(self):
        chunqiu = next(e for e in self.entries if e["name"] == "Chunqiu")
        self.assertEqual(chunqiu["site"], "No")
        self.assertFalse(chunqiu["quote"].endswith("No"))


class ReadingPdf(unittest.TestCase):
    def test_layout_text_and_creation_date(self):
        content = tiny_pdf([(40, 560, "SUPPLIER NAME"), (300, 560, "PRIMARY LOCATIONS WHERE MANUFACTURING FOR APPLE OCCURS"),
                            (40, 540, "Example Precision Corporation"), (300, 540, "Jiangsu"), (520, 540, "China mainland"),
                            (300, 525, "Taiwan"), (520, 525, "Taiwan"), (40, 100, "This list reflects suppliers as of the end of fiscal year 2024.")])
        pages, created = sl.pdf_pages(content)
        self.assertEqual(created, "2024-04-17")
        self.assertEqual(sl.fiscal_year(pages), 2024)
        [entry] = sl.parse_apple(pages)
        self.assertEqual(entry["quote"], "Example Precision Corporation | Jiangsu | China mainland / Taiwan | Taiwan")

    def test_segments(self):
        self.assertEqual(sl.segments("  AT & S Austria  AG      Styria     Austria"), [(2, "AT & S Austria AG"), (26, "Styria"), (37, "Austria")])


class Downloading(unittest.TestCase):
    """The download maps what the site answers to the job's outcome: bytes, gone for good, or try again later."""

    def session(self, status=200, body=b"%PDF-1.7", error=None):
        response = mock.MagicMock(status_code=status)
        response.__enter__.return_value = response
        response.raw.read.side_effect = lambda size, decode_content=True: body[:size]
        session = mock.MagicMock()
        session.get.side_effect = error or (lambda *a, **k: response)
        return mock.patch.object(sl, "_session", return_value=session)

    def test_a_list_comes_back_as_bytes(self):
        with self.session():
            self.assertEqual(asyncio.run(sl.fetch("https://example.com/list.pdf")), b"%PDF-1.7")

    def test_a_missing_list_is_gone_for_good(self):
        with self.session(status=404), self.assertRaises(sl.ListNotFound):
            asyncio.run(sl.fetch("https://example.com/list.pdf"))

    def test_a_site_still_busy_after_the_retries_is_tried_later(self):
        with self.session(error=requests.exceptions.RetryError("too many 503 error responses")), self.assertRaises(sl.ListUnavailable) as caught:
            asyncio.run(sl.fetch("https://example.com/list.pdf"))
        self.assertNotIsInstance(caught.exception, sl.ListNotFound)

    def test_too_large_is_refused(self):
        with self.session(body=b"x" * 20), mock.patch.object(sl, "MAX_BYTES", 10), self.assertRaises(sl.ListUnavailable):
            asyncio.run(sl.fetch("https://example.com/list.pdf"))


class Names(unittest.TestCase):
    def test_a_bracket_holding_a_common_name_is_tried_last(self):
        plan = sl.name_plan("Hon Hai Precision Industry Company Limited (Foxconn)")
        self.assertEqual(plan["names"], ["Hon Hai Precision Industry Company Limited (Foxconn)", "Hon Hai Precision Industry Company Limited",
                                         "Foxconn"])
        self.assertEqual(plan["private_name"], "Hon Hai Precision Industry Company Limited")

    def test_a_bracket_naming_a_parent_is_not_followed(self):
        plan = sl.name_plan("Unisteel Technology Limited (SFS Group)")
        self.assertEqual(plan["names"], ["Unisteel Technology Limited (SFS Group)", "Unisteel Technology Limited"])

    def test_a_bracket_inside_the_name_stays(self):
        self.assertEqual(sl.name_plan("AKM Meadville Electronics (Xiamen) Company Limited")["names"],
                         ["AKM Meadville Electronics (Xiamen) Company Limited"])

    def test_group_entries_name_the_parent(self):
        plan = sl.name_plan("Foxconn group companies")
        self.assertEqual((plan["names"], plan["note"]), (["Foxconn"], "listed as a group of companies"))
        self.assertEqual(sl.name_plan("Acme Corp and its subsidiaries")["names"], ["Acme Corp"])
        self.assertIsNone(sl.name_plan("Luen Fung Group")["note"])  # a company's own name

    def test_generic_entries(self):
        for name in ("Various", "Others", "Confidential", "", "Supplier A"):
            self.assertTrue(sl.name_plan(name)["generic"], name)


class Seed(unittest.TestCase):
    def test_the_bundled_seed_is_valid(self):
        lists = sl.load_seed()
        self.assertEqual(sl.validate(lists), [])
        self.assertEqual({entry["parser"] for entry in lists}, set(sl.PARSERS))

    def test_problems_are_named(self):
        bad = [dict(SOURCE, url="http://x"), dict(SOURCE, parser="nope"), dict(SOURCE, fiscal_year_end="Sept")]
        problems = " ".join(sl.validate(bad))
        for words in ("must be https", "unknown parser", "fiscal_year_end", "listed twice"):
            self.assertIn(words, problems)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "supply_chain.sqlite"
        patch = mock.patch.object(db, "DB_PATH", self.path)
        patch.start()
        self.addCleanup(patch.stop)
        filings = mock.patch.object(sec_client, "filings_dir", lambda: Path(self.tmp.name) / "filings")
        filings.start()
        self.addCleanup(filings.stop)
        self.conn = open_graph(self.path)
        self.apple = sl.seed_lists(self.conn, [SOURCE])["apple-test"]
        self.known = {}  # name -> company id the fake resolver matches
        self.lookups = []

    def supplier(self, name, ticker):
        company_id = graph.add_company(self.conn, name)
        graph.add_identifier(self.conn, company_id, "ticker", ticker, "US")
        self.known[name] = company_id
        return company_id

    async def resolve(self, conn, name):
        self.lookups.append(name)
        if name in self.known:
            return resolver.result("matched", self.known[name], "identifier_store")
        if name == "Down Corporation":
            return resolver.result("unavailable", reason="openfigi_unavailable", detail="timeout")
        return resolver.result("skipped", reason="no_match", detail="not known")

    def document(self, ext="a"):
        return graph.add_document(self.conn, sl.SOURCE, sl.KIND, ext, "https://x", company_id=self.apple, status="downloaded")

    def entry(self, name, row=1, page=1):
        return {"name": name, "page": page, "row": row, "quote": f"{name} | Taiwan | Taiwan", "locator": f"page {page}, row {row}"}

    def load(self, entries, stated_on="2026-09-30", allow_private=False, document_id=None):
        document_id = document_id or self.document()
        return run(sl.import_entries(self.conn, self.apple, document_id, entries, stated_on, allow_private, resolve=self.resolve))


class Importing(Base):
    def test_a_listed_supplier_is_a_tier_1_link_to_the_list_owner(self):
        tsmc = self.supplier("Taiwan Semiconductor Manufacturing Company Limited", "TSM")
        [result] = self.load([self.entry("Taiwan Semiconductor Manufacturing Company Limited", row=3, page=21)])
        self.assertEqual(result["status"], "linked")
        link = self.conn.execute("SELECT * FROM relationships WHERE id = ?", (result["relationship_id"],)).fetchone()
        self.assertEqual((link["supplier_id"], link["customer_id"], link["tier"], link["status"]), (tsmc, self.apple, 1, "active"))
        self.assertEqual(link["confidence"], 0.9)  # tier 1: high (merge.CONFIDENCE)
        evidence = self.conn.execute("SELECT * FROM evidence WHERE relationship_id = ?", (link["id"],)).fetchone()
        self.assertEqual((evidence["extractor"], evidence["tier"], evidence["locator"], evidence["stated_on"]),
                         ("supplier_list", 1, "page 21, row 3", "2026-09-30"))
        self.assertEqual(evidence["quote"], "Taiwan Semiconductor Manufacturing Company Limited | Taiwan | Taiwan")
        self.assertIsNone(link["supplier_revenue_share"])  # a list says who, not how much
        self.assertEqual(integrity.check(self.conn), [])

    def test_an_unmatched_name_is_refused_once_not_guessed(self):
        results = self.load([self.entry("Shenzhen Example Co., Ltd.", row=1), self.entry("Shenzhen Example Co., Ltd.", row=2)])
        self.assertEqual([r["status"] for r in results], ["rejected", "rejected"])
        rows = self.conn.execute("SELECT * FROM rejected").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["reason"], rows[0]["rejected_by"], rows[0]["supplier_name"], rows[0]["customer_name"]),
                         ("unresolved_company", "rule", "Shenzhen Example Co., Ltd.", "Apple Inc."))
        self.assertEqual(self.lookups, ["Shenzhen Example Co., Ltd."])  # each name is looked up once
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM relationships").fetchone()[0], 0)

    def test_a_generic_entry_is_refused_as_such(self):
        [result] = self.load([self.entry("Various")])
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.conn.execute("SELECT reason FROM rejected").fetchone()["reason"], "generic_counterparty")
        self.assertEqual(self.lookups, [])

    def test_the_bracket_is_dropped_when_the_full_name_finds_nothing(self):
        hon_hai = self.supplier("Hon Hai Precision Industry Company Limited", "HNHPF")
        [result] = self.load([self.entry("Hon Hai Precision Industry Company Limited (Foxconn)")])
        self.assertEqual((result["status"], result["supplier_id"]), ("linked", hon_hai))
        self.assertEqual(self.lookups, ["Hon Hai Precision Industry Company Limited (Foxconn)", "Hon Hai Precision Industry Company Limited"])

    def test_the_list_owners_own_sites_are_left_out(self):
        self.known["Apple"] = self.apple
        [result] = self.load([self.entry("Apple")])
        self.assertEqual((result["status"], result["reason"]), ("left_out", "list_owner"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM rejected").fetchone()[0], 0)

    def test_a_private_company_only_from_a_list_of_legal_names(self):
        [refused] = self.load([self.entry("Robert Bosch GmbH")])
        self.assertEqual(refused["status"], "rejected")
        [linked] = self.load([self.entry("Robert Bosch GmbH")], allow_private=True, document_id=self.document("b"))
        self.assertEqual((linked["status"], linked["how"]), ("linked", "supplier_list_private"))
        company = self.conn.execute("SELECT name, is_private FROM companies WHERE id = ?", (linked["supplier_id"],)).fetchone()
        self.assertEqual((company["name"], company["is_private"]), ("Robert Bosch GmbH", 1))
        saved = self.conn.execute("SELECT method FROM name_resolutions WHERE name_key = ?", (resolver.name_key("Robert Bosch GmbH"),)).fetchone()
        self.assertEqual(saved["method"], "supplier_list_private")

    def test_a_name_that_looks_listed_never_becomes_a_private_company(self):
        [result] = self.load([self.entry("Shenzhen Example Co., Ltd.")], allow_private=True)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM companies WHERE is_private = 1").fetchone()[0], 0)

    def test_loading_again_adds_nothing(self):
        self.supplier("Micron Technology Incorporated", "MU")
        document_id = self.document()
        entries = [self.entry("Micron Technology Incorporated"), self.entry("Nobody Ltd")]
        self.load(entries, document_id=document_id)
        self.load(entries, document_id=document_id)
        counts = [self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("relationships", "evidence", "rejected")]
        self.assertEqual(counts, [1, 1, 1])

    def test_name_lookup_down_raises_so_the_job_is_retried(self):
        with self.assertRaises(RuntimeError):
            self.load([self.entry("Down Corporation")])

    def test_a_new_years_list_adds_evidence_and_a_dropped_supplier_is_not_ended(self):
        self.supplier("Kept Corporation", "KEPT")
        self.supplier("Dropped Corporation", "DROP")
        self.load([self.entry("Kept Corporation"), self.entry("Dropped Corporation")], stated_on="2025-09-30", document_id=self.document("fy25"))
        self.load([self.entry("Kept Corporation")], stated_on="2026-09-30", document_id=self.document("fy26"))
        rows = {r["name"]: r for r in self.conn.execute(
            """SELECT c.name, r.status, r.first_seen, r.last_confirmed, (SELECT COUNT(*) FROM evidence e WHERE e.relationship_id = r.id) AS n
               FROM relationships r JOIN companies c ON c.id = r.supplier_id""")}
        self.assertEqual((rows["Kept Corporation"]["n"], rows["Kept Corporation"]["first_seen"], rows["Kept Corporation"]["last_confirmed"]),
                         (2, "2025-09-30", "2026-09-30"))
        self.assertEqual((rows["Dropped Corporation"]["status"], rows["Dropped Corporation"]["last_confirmed"]), ("active", "2025-09-30"))
        self.assertEqual(integrity.check(self.conn), [])

    def test_an_old_list_gives_stale_links(self):
        self.supplier("Old Corporation", "OLD")
        [result] = self.load([self.entry("Old Corporation")], stated_on="2023-09-30")
        status_ = self.conn.execute("SELECT status FROM relationships WHERE id = ?", (result["relationship_id"],)).fetchone()["status"]
        self.assertEqual(status_, "stale")  # over merge.STALE_MONTHS since the fiscal year it covers

    def test_summary(self):
        self.supplier("Micron Technology Incorporated", "MU")
        self.known["Apple"] = self.apple
        results = self.load([self.entry("Micron Technology Incorporated", 1), self.entry("Micron Technology Incorporated", 2),
                             self.entry("Nobody Ltd"), self.entry("Apple")])
        self.assertEqual(sl.summarise(results), {"entries": 4, "suppliers": 3, "linked": 2, "linked_suppliers": 1,
                                                 "rejected": {"no_match": 1}, "left_out": 1, "private": 0})


class ImportingAList(Base):
    def setUp(self):
        super().setUp()
        for name, ticker in (("Amkor Technology Incorporated", "AMKR"), ("Amphenol Corporation", "APH"), ("Murata Manufacturing Company Limited", "MRAAY")):
            self.supplier(name, ticker)
        patch = mock.patch.object(sl, "pdf_pages", lambda content: (APPLE, "2024-04-17"))
        patch.start()
        self.addCleanup(patch.stop)

    def import_list(self, content=b"%PDF-1.7 apple"):
        return run(sl.import_list(self.conn, dict(SOURCE, private_companies=False), self.apple, content, resolve=self.resolve))

    def test_the_list_becomes_a_document_with_its_links(self):
        outcome = self.import_list()
        self.assertEqual(outcome["fiscal_year"], 2023)
        doc = self.conn.execute("SELECT * FROM documents WHERE id = ?", (outcome["document_id"],)).fetchone()
        self.assertEqual((doc["source"], doc["kind"], doc["company_id"], doc["status"], doc["period_end"], doc["filed_at"], doc["title"]),
                         ("supplier_list", "supplier list", self.apple, "processed", "2023-09-30", "2024-04-17", "Apple Supplier List FY2023"))
        self.assertTrue(doc["external_id"].startswith("apple-test/"))
        self.assertTrue(Path(doc["local_path"]).exists())
        summary = sl.summarise(outcome["results"])
        self.assertEqual((summary["entries"], summary["linked_suppliers"]), (10, 3))
        self.assertEqual(integrity.check(self.conn), [])

    def test_the_same_file_again_is_not_read_again(self):
        self.import_list()
        again = self.import_list()
        self.assertTrue(again["unchanged"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0], 1)

    def test_a_page_instead_of_a_pdf_needs_a_new_url(self):
        with self.assertRaises(Permanent):
            self.import_list(b"<!DOCTYPE html><title>Supply chain</title>")

    def test_a_damaged_pdf_is_a_permanent_failure(self):
        with mock.patch.object(sl, "pdf_pages", REAL_PDF_PAGES), self.assertRaises(Permanent):
            self.import_list(b"%PDF-1.7 not really a pdf")

    def test_a_list_with_no_entries_is_a_permanent_failure(self):
        with mock.patch.object(sl, "pdf_pages", lambda content: ([APPLE[0]], None)), self.assertRaises(Permanent):
            self.import_list(b"%PDF-1.7 other")


class Job(Base):
    def setUp(self):
        super().setUp()
        self.supplier("Amkor Technology Incorporated", "AMKR")
        for patch in (mock.patch.object(sl, "pdf_pages", lambda content: (APPLE, "2024-04-17")),
                      mock.patch.object(sl, "load_seed", lambda path=None: [dict(SOURCE, private_companies=False)]),
                      mock.patch.object(resolver, "resolve", self.resolve)):
            patch.start()
            self.addCleanup(patch.stop)

    def test_the_job_downloads_imports_and_says_what_it_did(self):
        async def fetch(url):
            self.assertEqual(url, SOURCE["url"])
            return b"%PDF-1.7 apple"
        with mock.patch.object(sl, "fetch", fetch):
            first = run(sl.supplier_list_job({"key": "apple-test", "payload": {}}, self.conn))
            second = run(sl.supplier_list_job({"key": "apple-test", "payload": {}}, self.conn))
        self.assertEqual(first["notes"], "FY2023: 1 suppliers linked, 9 unresolved")
        self.assertEqual(second["notes"], "FY2023 unchanged")

    def test_a_list_too_long_for_one_run_goes_on_in_the_next(self):
        clock = [0.0]
        looked_up = self.resolve

        async def slow_resolve(conn, name):  # each lookup takes a "second"
            clock[0] += 1
            return await looked_up(conn, name)

        async def fetch(url):
            return b"%PDF-1.7 apple"
        fake_time = types.SimpleNamespace(monotonic=lambda: clock[0])
        with mock.patch.object(sl, "fetch", fetch), mock.patch.object(sl, "time", fake_time), \
                mock.patch.object(resolver, "resolve", slow_resolve), mock.patch.object(sl, "LOOKUP_BUDGET_S", 2.5):
            jobs.enqueue(self.conn, sl.JOB_KIND, "apple-test", {})
            w = worker.Worker(self.path, handlers={sl.JOB_KIND: sl.supplier_list_job}, name="t")
            self.assertTrue(run(w.run_once()))
            done, again = self.conn.execute("SELECT status, run_after, last_error FROM jobs ORDER BY id").fetchall()
            self.assertEqual(done["status"], "done")
            self.assertEqual(self.conn.execute("SELECT notes FROM runs").fetchone()[0], '"3 of 10 names looked up; continuing"')
            self.assertEqual((again["status"], again["last_error"]), ("queued", "3 of 10 names looked up; continuing"))
            self.assertTrue(again["run_after"] > db.now())  # a minute from now
            self.assertEqual(self.conn.execute("SELECT status FROM documents").fetchone()[0], "downloaded")
            links = self.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
            with mock.patch.object(sl, "LOOKUP_BUDGET_S", 100):
                second = run(sl.supplier_list_job({"key": "apple-test", "payload": {}}, self.conn))
        self.assertEqual(second["notes"], "FY2023: 1 suppliers linked, 9 unresolved")
        self.assertNotIn("defer_until", second)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0], max(links, 1))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM rejected").fetchone()[0], 9)  # each refusal once
        self.assertEqual(self.conn.execute("SELECT status FROM documents").fetchone()[0], "processed")

    def test_a_url_with_nothing_is_permanent(self):
        async def gone(url):
            raise sl.ListNotFound("nothing at the url any more (404)")
        with mock.patch.object(sl, "fetch", gone), self.assertRaises(Permanent):
            run(sl.supplier_list_job({"key": "apple-test", "payload": {}}, self.conn))

    def test_a_list_taken_out_of_the_seed_is_permanent(self):
        with self.assertRaises(Permanent):
            run(sl.supplier_list_job({"key": "gone", "payload": {}}, self.conn))

    def test_each_list_is_checked_once_a_week(self):
        self.assertEqual(sl.schedule(self.conn, now=NOW, lists=[SOURCE, DELL_SOURCE]), 2)
        dell = graph.find_company(self.conn, "ticker", "DELL", "US")
        job = self.conn.execute("SELECT * FROM jobs WHERE key = 'dell-test'").fetchone()
        self.assertEqual((job["kind"], job["company_id"], job["priority"]), ("supplier_list", dell, sl.PRIORITY))
        self.assertEqual(sl.schedule(self.conn, now=NOW, lists=[SOURCE, DELL_SOURCE]), 0)  # open
        for row in self.conn.execute("SELECT id FROM jobs").fetchall():
            self.conn.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (row["id"],))
        self.assertEqual(sl.schedule(self.conn, now=NOW + timedelta(days=3), lists=[SOURCE, DELL_SOURCE]), 0)
        self.assertEqual(sl.schedule(self.conn, now=NOW + timedelta(days=8), lists=[SOURCE, DELL_SOURCE]), 2)

    def test_the_owner_is_found_by_ticker_not_made_twice(self):
        self.assertEqual(sl.seed_lists(self.conn, [SOURCE])["apple-test"], self.apple)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM companies WHERE name = 'Apple Inc.'").fetchone()[0], 1)


class Status(Base):
    def test_links_and_runs_in_the_log_and_the_list_among_the_owners_documents(self):
        self.supplier("Amkor Technology Incorporated", "AMKR")
        document_id = graph.add_document(self.conn, sl.SOURCE, sl.KIND, "apple-test/abc", SOURCE["url"], company_id=self.apple,
                                         filed_at="2024-04-17", period_end="2023-09-30", status="processed")
        self.load([self.entry("Amkor Technology Incorporated")], document_id=document_id)
        job_id, _ = jobs.enqueue(self.conn, sl.JOB_KIND, "apple-test", {"slug": "apple-test", "form": sl.KIND}, company_id=self.apple, now=NOW)
        jobs.finish(self.conn, jobs.claim(self.conn, "w", now=NOW), notes="FY2023: 1 suppliers linked, 0 unresolved", now=NOW)
        events = status.log_events(self.conn, now=NOW)
        texts = [e["text"] for e in events]
        self.assertIn("AMKR → AAPL · supplier list", texts)
        self.assertIn("import AAPL supplier list · FY2023: 1 suppliers linked, 0 unresolved", texts)
        [filing] = status.company_filings(self.conn, self.apple)
        self.assertEqual((filing["label"], filing["status"]), ("Supplier list FY2023", "processed"))


if __name__ == "__main__":
    unittest.main()
