"""Taiwan annual reports from MOPS (#128): the document server client, the scout and download jobs, the PDF paragraphs
and the section finder. No network: the listing page is a saved copy (Hon Hai, meetings in 2025) and fetches are faked."""
import asyncio
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import mops_client
from supply_chain import chunker, graph, mops, reader, scout, status, worker
from supply_chain.db import open_graph

FIXTURES = Path(__file__).parent / "fixtures" / "mops"
LISTING = (FIXTURES / "t57sb01_2317_2025.html").read_bytes().decode("big5", errors="replace")
TODAY = date(2025, 11, 15)


def run(coro):
    return asyncio.run(coro)


def report_row(code, year=2024, uploaded="2025-05-09", meeting="2025-05-29"):
    return {"co_id": "2317", "fiscal_year": year, "code": code, "meeting_date": meeting, "description": "",
            "filename": f"{year}_2317_{meeting.replace('-', '')}F{code}.pdf", "size": 1, "uploaded": uploaded}


class Client(unittest.TestCase):
    def test_listing_rows(self):
        rows = mops_client.parse_listing(LISTING)
        self.assertEqual(len(rows), 14)
        english = next(r for r in rows if r["code"] == "E4")
        self.assertEqual(english, {"co_id": "2317", "fiscal_year": 2024, "code": "E4", "meeting_date": "2025-05-29",
                                   "description": "英文版-股東會年報(尚未適用永續揭露準則)", "filename": "2024_2317_20250529FE4.pdf",
                                   "size": 4308473, "uploaded": "2025-05-09"})

    def test_the_english_report_as_filed_wins_over_the_revised_one(self):
        reports = mops_client.english_annual_reports(mops_client.parse_listing(LISTING))
        self.assertEqual([(r["filename"], r["revised"]) for r in reports], [("2024_2317_20250529FE4.pdf", False)])

    def test_a_revised_report_alone_is_used(self):
        reports = mops_client.english_annual_reports([report_row("E6"), report_row("04"), report_row("E4", year=2023, meeting="2024-05-31")])
        self.assertEqual([(r["fiscal_year"], r["code"], r["revised"]) for r in reports], [(2024, "E6", True), (2023, "E4", False)])

    def test_no_data_page_is_empty_and_a_strange_page_is_an_error(self):
        self.assertEqual(mops_client.parse_listing("<html><body>查無所需資料</body></html>"), [])
        with self.assertRaises(mops_client.MopsUnavailable):
            mops_client.parse_listing("<html><body>Service Unavailable</body></html>")

    def test_roc_years_and_dates(self):
        self.assertEqual(mops_client.roc_year(2026), 115)
        self.assertEqual(mops_client._uploaded("115/05/22 10:58:09"), "2026-05-22")
        self.assertIn("year=115", mops_client.listing_url("2317", 2026))

    def test_download_follows_the_temporary_link_and_saves_the_pdf(self):
        asked = []

        async def fetch(url, data=None, timeout=None):
            asked.append((url, data))
            if data:
                return "電子檔案：<a href='/pdf/2024_2317_20250529FE4_20261115_174824.pdf'>x</a>".encode("big5")
            return b"%PDF-1.7 body"
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(mops_client, "fetch", fetch):
            saved = run(mops_client.download("2317", "2024_2317_20250529FE4.pdf", folder=folder))
            self.assertEqual(Path(saved["path"]).read_bytes(), b"%PDF-1.7 body")
        self.assertEqual(asked[0][1]["step"], "9")
        self.assertEqual(asked[1][0], "https://doc.twse.com.tw/pdf/2024_2317_20250529FE4_20261115_174824.pdf")

    def test_download_refuses_what_isnt_a_pdf(self):
        async def fetch(url, data=None, timeout=None):
            return b"<a href='/pdf/a.pdf'>a</a>" if data else b"<html>busy</html>"
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(mops_client, "fetch", fetch):
            with self.assertRaises(mops_client.MopsUnavailable):
                run(mops_client.download("2317", "2024_2317_20250529FE4.pdf", folder=folder))
            with self.assertRaises(ValueError):
                run(mops_client.download("2317", "../../etc/passwd", folder=folder))


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "g.sqlite"
        self.conn = open_graph(self.path)
        self.theme = graph.add_theme(self.conn, "t", "T")
        self.hon_hai = self.company("Hon Hai Precision Industry Co., Ltd.", ("2317", "TW"))
        self.listings = {2025: LISTING}

        async def list_documents(code, meeting_year):
            return mops_client.parse_listing(self.listings.get(meeting_year, "查無所需資料"))
        patch = mock.patch.object(mops_client, "list_documents", list_documents)
        patch.start()
        self.addCleanup(patch.stop)

    def company(self, name, *tickers):
        company_id = graph.add_company(self.conn, name)
        for value, market in tickers:
            graph.add_identifier(self.conn, company_id, "ticker", value, market)
        graph.add_to_theme(self.conn, self.theme, company_id)
        return company_id

    def test_scan_registers_the_english_report_and_queues_its_download(self):
        self.assertEqual(run(mops.scan(self.conn, self.hon_hai, today=TODAY)), {"code": "2317", "found": 1, "new": 1})
        document = self.conn.execute("SELECT * FROM documents").fetchone()
        self.assertEqual((document["source"], document["kind"], document["external_id"], document["filed_at"], document["period_end"]),
                         ("mops", "annual report", "2024_2317_20250529FE4.pdf", "2025-05-09", "2024-12-31"))
        job = self.conn.execute("SELECT kind, key, priority FROM jobs").fetchone()
        self.assertEqual(tuple(job), ("download", "mops/2024_2317_20250529FE4.pdf", 60))
        self.assertEqual(run(mops.scan(self.conn, self.hon_hai, today=TODAY)), {"code": "2317", "found": 1, "new": 0})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_old_reports_are_left_out(self):
        self.assertEqual(run(mops.scan(self.conn, self.hon_hai, today=date(2026, 9, 1)))["found"], 0)

    def test_a_company_with_a_us_listing_is_read_from_edgar_only(self):
        tsmc = self.company("Taiwan Semiconductor Manufacturing Company Limited", ("TSM", "US"), ("2330", "TW"))
        self.assertTrue(scout.uses_mops(self.conn, self.hon_hai))
        self.assertFalse(scout.uses_mops(self.conn, tsmc))

    def test_worker_scouts_downloads_and_queues_the_read(self):
        async def download(co_id, filename, folder=None):
            return {"path": "/x/report.pdf", "sha256": "cd" * 32, "size": 9}
        scout.schedule(self.conn)
        w = worker.Worker(self.path, handlers={"scout": scout.scout_job, "download": scout.download_job}, name="t")
        with mock.patch.object(mops_client, "download", download), mock.patch.object(mops, "datetime") as clock:
            clock.now.return_value.date.return_value = TODAY
            self.assertTrue(run(w.run_once()))
            self.assertTrue(run(w.run_once()))
        document = self.conn.execute("SELECT id, status, content_hash FROM documents").fetchone()
        self.assertEqual((document["status"], document["content_hash"]), ("downloaded", "cd" * 32))
        read = self.conn.execute("SELECT key, priority, payload FROM jobs WHERE kind = 'read'").fetchone()
        self.assertEqual((read["key"], read["priority"]), (str(document["id"]), reader.READ_PRIORITY["annual report"]))
        notes = [json.loads(r[0]) for r in self.conn.execute("SELECT notes FROM runs ORDER BY id")]
        self.assertEqual(notes[0], "1 MOPS annual report seen, 1 new")
        row = next(r for r in status.company_rows(self.conn) if r["company_id"] == self.hon_hai)
        self.assertEqual((row["latest_filing"], row["filings"]), ("Annual report 2024", 1))

    def test_no_english_report_is_said_in_the_notes(self):
        self.listings = {}
        scout.schedule(self.conn)
        w = worker.Worker(self.path, handlers={"scout": scout.scout_job}, name="t")
        run(w.run_once())
        self.assertIn("no English annual report", self.conn.execute("SELECT notes FROM runs").fetchone()[0])

    def test_a_missing_file_is_a_permanent_failure(self):
        run(mops.scan(self.conn, self.hon_hai, today=TODAY))

        async def gone(*args, **kwargs):
            raise mops_client.MopsNotFound("gone")
        w = worker.Worker(self.path, handlers={"download": scout.download_job}, name="t")
        with mock.patch.object(mops_client, "download", gone):
            run(w.run_once())
        self.assertEqual(self.conn.execute("SELECT status FROM jobs").fetchone()[0], "failed")
        self.assertEqual(self.conn.execute("SELECT status FROM documents").fetchone()[0], "failed")


PAGE = """Four. Operational Overview
I. Business Content
The Company designs and manufactures electronic products for its customers around the world, working closely
with partners in every region where it operates, and with its suppliers in Asia, Europe and America on high-
performance computing at the centre of its plans for the years to come, as the report sets out in detail.
This paragraph ends here.
(IV) List of customers that have accounted for more than 10% of the total purchase (sale)
Unit: NT$ Million
1 Vendor L 2,278,037 39.28% None Vendor L 2,348,108 36.99% None
- 111 -
2 Others 3,520,744 60.72% - Others 4,000,433 63.01% -"""


class PdfText(unittest.TestCase):
    def test_lines_become_paragraphs_and_table_rows(self):
        paragraphs = chunker._finish(chunker.pdf_page_blocks(PAGE))
        self.assertEqual(paragraphs[:2], ["Four. Operational Overview", "I. Business Content"])  # headings start paragraphs
        self.assertTrue(paragraphs[2].startswith("The Company designs"))
        self.assertIn("America on high-performance computing", paragraphs[2])  # the word broken at the line end is joined
        # a paragraph whose last line is full width can't be told from a wrapped line, so the next one joins it
        self.assertTrue(paragraphs[2].endswith("in detail. This paragraph ends here."))
        self.assertTrue(paragraphs[-2].endswith("(sale) Unit: NT$ Million"))
        self.assertEqual(paragraphs[-1], "1 Vendor L 2,278,037 39.28% None Vendor L 2,348,108 36.99% None\n"
                                         "2 Others 3,520,744 60.72% - Others 4,000,433 63.01% -")  # table rows stay rows
        self.assertNotIn("- 111 -", "\n".join(paragraphs))  # the page number is dropped

    def test_finish_keeps_a_tag_per_paragraph(self):
        paragraphs, pages = chunker._finish(["One", "two continues", "Three."], [1, 2, 2])
        self.assertEqual((paragraphs, pages), (["One two continues", "Three."], [1, 2]))


class Finder(unittest.TestCase):
    PARAGRAPHS = [
        "Table of Contents",
        "VII. Important contracts .................................. 129",
        "(IV) Major suppliers and customers ‑ 111",
        "Our chairman thanks the shareholders for a record year.",
        "Building on years of cooperation with major customers, Hon Hai developed AI servers.",  # prose: not the disclosure
        "We buy components from many suppliers in Asia.",
        "The weather was fine.",
        "(IV) List of customers that have accounted for more than 10% of the total purchase (sale)",
        "1 Vendor L 2,278,037 39.28% None",
        "1 Customer E 3,706,464 54.03% None",
        "VII. Important contracts",
        "Contract | Counterparty | Period",
        "Lease | Pegatron | 2024-2026",
    ]

    def test_disclosures_and_passages(self):
        with mock.patch.object(chunker, "MOPS_TABLE_CHARS", 90):
            sections = {s.name: s.paragraphs for s in chunker.mops_sections(self.PARAGRAPHS, "annual report")}
        self.assertEqual(sections["Major suppliers and customers"], [7, 8])  # stops at the budget
        self.assertEqual(sections["Material contracts"], [10, 11, 12])
        # passages with a paragraph either side; the table of contents is never read
        self.assertEqual(sections["Passages naming customers or suppliers"], [3, 4, 5, 6, 9])

    def test_the_suppliers_block_stops_where_the_contracts_start(self):
        sections = {s.name: s.paragraphs for s in chunker.mops_sections(self.PARAGRAPHS, "annual report")}
        self.assertEqual(sections["Major suppliers and customers"], [7, 8, 9])

    def test_locators_carry_the_pdf_page(self):
        pages = [chunker.page_label(1 + i // 5) for i in range(len(self.PARAGRAPHS))]
        chunks = chunker.chunk_paragraphs(self.PARAGRAPHS, "mops", "annual report", "r.pdf", headings=pages)
        table = next(c for c in chunks if c.section == "Major suppliers and customers")
        found = reader.locate(table, "1 Customer E 3,706,464 54.03% None")
        self.assertEqual(chunker.locator_for(table.section, table.numbers[found[0]], table.numbers[found[1]], table.headings[found[0]]),
                         "Major suppliers and customers, PDF page 2, paragraph 10 [chunker v1]")
        halves = reader._halves(table)  # an answer cut off is read again in halves: the pages stay with their paragraphs
        self.assertEqual([h.headings for h in halves], [["PDF page 2"], ["PDF page 2", "PDF page 2"]])

    def test_empty_text_gives_no_chunks(self):
        self.assertEqual(chunker.chunk_paragraphs([], "mops", "annual report", "scan.pdf"), [])


if __name__ == "__main__":
    unittest.main()
