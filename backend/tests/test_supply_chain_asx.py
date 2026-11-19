"""ASX material contract announcements (#131): the asx.com.au client, the headline rules, the terms gate, the scout and
download jobs, and how the Reader sees an announcement. No network: the listing pages are trimmed copies of NEXTDC's
(NXT) for 2025 and 2026, the PDF is made in the test, and fetches are faked. directors.sqlite (where ASX's terms are
accepted) is a temp file."""
import asyncio
import html
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import asx_client
import directors
import directors_sources
from supply_chain import asx, chunker, graph, jobs, reader, scout, status, verifier, worker
from supply_chain.db import open_graph
from tests.pipeline_isolation import isolate

# NEXTDC's announcements as listed on asx.com.au (date, time, price sensitive, idsId, headline, pages). Only these facts
# are kept, not a copy of ASX's page (its terms allow personal use only); listing_page() renders them in ASX's markup.
LISTED = {
    2025: [
        ('15/12/2025', '8:18 am', False, '03040913', 'Change in substantial holding', 30),
        ('05/12/2025', '1:28 pm', False, '03037632', 'NEXTDC joins OpenAI for Australia as Infrastructure Partner', 3),
        ('05/12/2025', '8:24 am', True, '03037364', 'Building the Next Generation of Sovereign AI infrastructure', 2),
        ('01/12/2025', '8:30 am', True, '03034631', 'Contract Utilisation & Capex Guidance Update', 2),
        ('19/11/2025', '3:02 pm', False, '03028687', 'Annual General Meeting Results', 1),
        ('26/09/2025', '8:24 am', False, '03000572', 'NEXTDC appoints new board member - Mr Jamaludin Ibrahim', 2),
        ('10/06/2025', '8:27 am', True, '02956543', 'Contracted Utilisation & Forward Order Book Update', 2),
    ],
    2026: [
        ('13/11/2026', '8:22 am', False, '03165332', 'Change in substantial holding', 38),
        ('09/11/2026', '11:41 am', True, '03163616', 'Response to Statement by Goodman Group & Digital Realty', 5),
        ('28/10/2026', '8:20 am', True, '03158123', 'Financial Covenants - Compliance and Headroom', 6),
        ('26/10/2026', '8:28 am', True, '03156766', 'Board Renewal and AGM Voting Items', 3),
        ('21/10/2026', '8:35 am', True, '03154955', 'M3 Melbourne Power Delay & Revised FY27 Guidance', 6),
        ('19/10/2026', '9:33 am', True, '03153882', 'Trading Halt', 2),
        ('18/09/2026', '8:26 am', False, '03140856', 'Settlement of A$1.1 billion Convertible Notes Offering', 3),
        ('10/09/2026', '8:51 am', False, '03137983', 'Appendix 3B', 55),
        ('04/09/2026', '5:10 pm', True, '03136141', 'S&amp;P DJI Announces September 2026 Quarterly Rebalance', 6),
        ('27/08/2026', '5:38 pm', True, '03131689', 'FY26 Results Announcement', 7),
        ('27/08/2026', '5:37 pm', True, '03131688', 'FY26 Annual Report & Appendix 4E', 167),
        ('21/07/2026', '8:32 am', True, '03116569', 'Contracted Utilisation Update', 2),
        ('05/05/2026', '8:27 am', True, '03090318', 'A$1.8 billion of New Senior Debt Commitments Secured', 3),
        ('27/04/2026', '8:16 am', True, '03086357', 'Retail Offer Booklet & Eligibility Letters', 131),
        ('20/04/2026', '7:49 am', False, '03083979', 'Proposed issue of securities - NXT', 7),
        ('20/04/2026', '7:47 am', True, '03083977', 'Record Contracted Utilisation and A$2.2bn Capital Plan', 10),
        ('16/01/2026', '5:16 pm', False, '03050630', 'M4 Melbourne Data Centre Development Approval', 2),
    ],
}

def listing_page(rows):
    """An announcements page in asx.com.au's markup: a header row, then one row per announcement."""
    body = []
    for day, at, sensitive, ids_id, headline, pages in rows:
        mark = '<img src="/asx/v2/markets/image/icon-price-sensitive.svg" class="pricesens" title="price sensitive">' if sensitive else ""
        size = f'<span class="page">{pages} pages</span>' if pages else ""
        body.append(f'<tr><td>{day}<br><span class="dates-time">{at}</span></td><td class="pricesens">{mark}</td>'
                    f'<td><a href="/asx/v2/statistics/displayAnnouncement.do?display=pdf&amp;idsId={ids_id}">{html.escape(headline)}<br>'
                    f'<img src="/asx/v2/markets/image/pdf_icon.png">{size}</a></td></tr>')
    return ('<html><body><table><thead><tr><th>Date</th><th>Price sens.</th><th>Headline</th></tr></thead><tbody>'
            + "".join(body) + "</tbody></table></body></html>")


PAGES = {year: listing_page(rows) for year, rows in LISTED.items()}
TODAY = date(2026, 11, 15)
TERMS_PAGE = '<form><input name="pdfURL" value="https://announcements.asx.com.au/asxpdf/20251205/pdf/06sz8h5wyv4fwj.pdf" type="hidden"></form>'


def run(coro):
    return asyncio.run(coro)


def make_pdf(pages):
    """A small real PDF with one text line per entry of each page (Helvetica), so pypdf reads it as ASX's PDFs."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        text = "BT /F1 11 Tf 14 TL 50 780 Td " + " ".join(f"({line.replace('(', '[').replace(')', ']')}) Tj T*" for line in lines) + " ET"
        objects.append(f"<< /Length {len(text)} >>\nstream\n{text}\nendstream")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objects)} 0 R >>")
        kids.append(f"{len(objects)} 0 R")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    body, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    body += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return body


ANNOUNCEMENT = [
    ["ASX Release", "5 December 2025", "Building the Next Generation of Sovereign AI infrastructure in Australia",
     "NEXTDC Limited (ASX: NXT) is pleased to announce that today it agreed a Memorandum of Understanding with OpenAI.",
     "Authorised for release by the Managing Director and Chief Executive Officer of NEXTDC Limited. ENDS"],
    ["About NEXTDC", "NEXTDC is an ASX 100-listed technology company and data centre provider.", "For personal use only"],
]


class Client(unittest.TestCase):
    def test_listing_rows_with_the_price_sensitive_mark(self):
        rows = asx_client.parse_announcements(PAGES[2026])
        self.assertEqual(len(rows), 17)
        self.assertEqual(rows[0], {"date": "2026-11-13", "headline": "Change in substantial holding", "ids_id": "03165332", "pages": 38,
                                   "price_sensitive": False})
        utilisation = next(r for r in rows if r["ids_id"] == "03116569")
        self.assertEqual((utilisation["headline"], utilisation["date"], utilisation["pages"], utilisation["price_sensitive"]),
                         ("Contracted Utilisation Update", "2026-07-21", 2, True))
        self.assertEqual(next(r for r in rows if r["ids_id"] == "03163616")["headline"], "Response to Statement by Goodman Group & Digital Realty")

    def test_codes_and_ids_are_checked_before_they_go_into_an_address(self):
        self.assertIn("asxCode=NXT&timeframe=Y&year=2026", asx_client.listing_url("NXT", 2026))
        self.assertEqual(asx_client.display_url("03037364"),
                         "https://www.asx.com.au/asx/v2/statistics/displayAnnouncement.do?display=pdf&idsId=03037364")
        for bad in ("NXT&x=1", "", "nx"):
            with self.assertRaises(ValueError):
                asx_client.listing_url(bad, 2026)
        with self.assertRaises(ValueError):
            asx_client.display_url("../1")

    def test_download_follows_the_terms_page_to_asxs_own_pdf(self):
        asked = []

        async def fetch(url, retries=None, max_bytes=None):
            asked.append(url)
            return TERMS_PAGE.encode() if "displayAnnouncement" in url else b"%PDF-1.4 body"
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(asx_client, "fetch", fetch):
            saved = run(asx_client.download("03037364", "NXT", folder=folder))
            self.assertEqual(Path(saved["path"]).read_bytes(), b"%PDF-1.4 body")
            self.assertEqual(Path(saved["path"]).name, "03037364.pdf")
        self.assertEqual(asked[1], "https://announcements.asx.com.au/asxpdf/20251205/pdf/06sz8h5wyv4fwj.pdf")
        self.assertEqual(saved["pdf_url"], asked[1])

    def test_download_refuses_another_host_and_what_isnt_a_pdf(self):
        async def elsewhere(url, retries=None, max_bytes=None):
            return b'<input name="pdfURL" value="https://evil.example/a.pdf">'

        async def html(url, retries=None, max_bytes=None):
            return TERMS_PAGE.encode() if "displayAnnouncement" in url else b"<html>busy</html>"
        with tempfile.TemporaryDirectory() as folder:
            for fake in (elsewhere, html):
                with mock.patch.object(asx_client, "fetch", fake), self.assertRaises(asx_client.AsxUnavailable):
                    run(asx_client.download("03037364", "NXT", folder=folder))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_busy_answers_are_retried_and_a_missing_page_is_not(self):
        answers = [(503, b""), (200, b"page")]
        with mock.patch.object(asx_client, "_open", lambda url, max_bytes: answers.pop(0)), \
                mock.patch.object(asx_client, "MIN_INTERVAL_S", 0):
            self.assertEqual(run(asx_client.fetch("https://www.asx.com.au/x", retries=(0,))), b"page")
        with mock.patch.object(asx_client, "_open", lambda url, max_bytes: (404, b"")), mock.patch.object(asx_client, "MIN_INTERVAL_S", 0):
            with self.assertRaises(asx_client.AsxNotFound):
                run(asx_client.fetch("https://www.asx.com.au/x", retries=(0, 0)))

    def test_boards_of_directors_still_find_the_annual_report(self):
        # directors_sources reads the same listing through asx_client, with one try and its own errors
        async def fetch(url, retries=None, max_bytes=None):
            self.assertEqual(retries, ())
            return PAGES[int(url.rsplit("year=", 1)[1])].encode()
        with mock.patch.object(asx_client, "fetch", fetch):
            report = run(directors_sources.latest_asx_report("nxt", now=datetime(2026, 11, 15)))
        self.assertEqual((report["ids_id"], report["filed"], report["title"]),
                         ("03131688", "2026-08-27", "NXT FY26 Annual Report & Appendix 4E (2026-08-27)"))

        async def down(url, retries=None, max_bytes=None):
            raise asx_client.AsxUnavailable("Couldn't download from www.asx.com.au (503).")
        with mock.patch.object(asx_client, "fetch", down), self.assertRaises(directors_sources.SourceUnavailable):
            run(directors_sources.latest_asx_report("NXT"))


def row(headline, pages=2, price_sensitive=False):
    return {"headline": headline, "pages": pages, "price_sensitive": price_sensitive}


class Headlines(unittest.TestCase):
    """Real headlines from NEXTDC (NXT), Lynas (LYC) and Pilbara Minerals (PLS), 2025-26."""

    READ = [
        row("NEXTDC joins OpenAI for Australia as Infrastructure Partner", 3),
        row("Contracted Utilisation Update", 2, True),
        row("Contract Utilisation & Capex Guidance Update", 2, True),
        row("Contracted Utilisation & Forward Order Book Update", 2, True),
        row("Record Contracted Utilisation and A$2.2bn Capital Plan", 10, True),
        row("Lynas and JS Link Partnership for Malaysian Magnet Factory", 2, True),
        row("Lynas to Develop Metal Making Partnership with LS Eco Energy", 2),
        row("Lynas and US DoW sign Letter of Intent for rare earth supply", 2, True),
        row("LYNAS & JARE SIGN MINERAL EXPLORATION & DEVELOPMENT MOU", 2),
        row("Enhanced JARE Agreement for Japanese Industry", 2, True),
        row("PLS signs long term power agreement", 4, True),
        row("PLS executes offtake agreement with Canmax", 2, True),
        row("PLS and Calix agree revised Mid-Stream project structure", 3),
    ]
    PRICE_SENSITIVE = [  # no deal word, but material news of a few pages
        row("Building the Next Generation of Sovereign AI infrastructure", 2, True),  # NEXTDC's MoU with OpenAI
        row("M3 Melbourne Power Delay & Revised FY27 Guidance", 6, True),
        row("Enhancing infrastructure to strengthen Pilgangoora operation", 4, True),
    ]
    SKIPPED = [
        row("A$1.8 billion of New Senior Debt Commitments Secured", 3, True),  # "secured", but debt
        row("Successful pricing of A$1.1 billion Convertible Notes", 7, True),
        row("A$1.0 billion Hybrid Securities Offer & La Caisse Commitment", 4, True),
        row("Retail Entitlement Offer Opens", 5, True),
        row("Senior Debt Facilities Upsized to A$2.3 Billion", 2, True),
        row("PLS prices US$700M Senior Unsecured Notes Offering", 1, True),
        row("Financial Covenants - Compliance and Headroom", 6, True),
        row("Appendix 3B", 55),
        row("Cleansing Notice", 2),
        row("Notification regarding unquoted securities - NXT", 6),
        row("Application for quotation of securities - NXT", 7),
        row("Change in substantial holding", 38),
        row("Becoming a substantial holder from GMG", 127),
        row("Change of Director's Interest Notice", 2),
        row("NEXTDC appoints new board member - Deborah Page AM", 2),
        row("Board Renewal and AGM Voting Items", 3, True),
        row("Retirement of Chief Executive Officer", 1, True),
        row("FY26 Results Announcement", 7, True),
        row("Half Year Reports & Accounts", 21, True),
        row("FY26 Annual Report & Appendix 4E", 167, True),
        row("September 2026 Quarterly Activities Report", 9, True),
        row("Investor Presentation", 59, True),
        row("AGM - CEO's Address", 5, True),
        row("Notice of AGM, Proxy Sample & Online Meeting Guide", 29),
        row("FY26 Corporate Governance Statement", 33),
        row("Introduction of Growth Incentive Plan", 3, True),
        row("Trading Halt", 2, True),
        row("Response to Statement by Goodman Group & Digital Realty", 5, True),
        row("Response to Share Raid by Goodman Group & Digital Realty", 2, True),
        row("Response to ASX Compliance Letter", 5),
        row("S&P DJI Announces September 2026 Quarterly Rebalance", 6, True),
        row("Lynas Rare Earths to Acquire Meteoric Resources", 147, True),
        row("Pilgangoora Ore Reserve increases 31% in contained lithium", 71, True),
        row("M4 Melbourne Data Centre Development Approval", 2),  # not price sensitive, no deal word
        row("PLS approves P2000 FID to lift production to circa 2Mtpa", 12, True),  # price sensitive but long
        row("Major supply contract: scheme booklet", 45),  # a deal word, but far too long and a scheme
        row("Supply agreement (full document)", 60),
    ]

    def test_deals_are_read(self):
        self.assertEqual([r["headline"] for r in self.READ if asx.worth_reading(r) != "deal"], [])

    def test_short_price_sensitive_news_is_read(self):
        self.assertEqual([asx.worth_reading(r) for r in self.PRICE_SENSITIVE], ["price sensitive"] * len(self.PRICE_SENSITIVE))

    def test_shares_meetings_results_and_admin_are_skipped(self):
        self.assertEqual([r["headline"] for r in self.SKIPPED if asx.worth_reading(r)], [])

    def test_unknown_page_counts(self):
        self.assertEqual(asx.worth_reading(row("Supply agreement signed", None)), "deal")
        self.assertIsNone(asx.worth_reading(row("Building something", None, True)))


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        isolate(self, root)  # also points directors.sqlite (ASX's terms) at the temp folder
        self.path = root / "g.sqlite"
        self.conn = open_graph(self.path)
        self.addCleanup(self.conn.close)
        self.theme = graph.add_theme(self.conn, "t", "T")
        self.nextdc = self.company("NEXTDC Limited", ("NXT", "ASX"))
        self.listed = []

        async def announcements(code, year, retries=None):
            self.listed.append((code, year))
            return asx_client.parse_announcements(PAGES.get(year, "<table></table>"))
        for patcher in (mock.patch.object(asx_client, "announcements", announcements), mock.patch.object(asx, "datetime")):
            clock = patcher.start()
            self.addCleanup(patcher.stop)
        clock.now.return_value.date.return_value = TODAY  # what scan() takes for today when the worker calls it

    def company(self, name, *tickers):
        company_id = graph.add_company(self.conn, name)
        for value, market in tickers:
            graph.add_identifier(self.conn, company_id, "ticker", value, market)
        graph.add_to_theme(self.conn, self.theme, company_id)
        return company_id

    def worker(self, *kinds):
        handlers = {"scout": scout.scout_job, "download": scout.download_job}
        return worker.Worker(self.path, handlers={k: handlers[k] for k in kinds}, name="t")

    def documents(self):
        return {r["external_id"]: r for r in self.conn.execute("SELECT * FROM documents WHERE source = 'asx'")}

    def test_nothing_is_fetched_before_the_terms_are_accepted(self):
        self.assertEqual(scout.due_companies(self.conn), [])
        row = next(r for r in status.company_rows(self.conn) if r["company_id"] == self.nextdc)
        self.assertEqual(row["status"], "waiting for ASX terms")
        self.assertEqual(status.overview(self.conn)["coverage"]["waiting_for_asx"], 1)
        self.assertEqual(status.run_now(self.conn)["queued"], 0)  # Run now doesn't queue them either
        graph_jobs = self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        self.assertEqual(graph_jobs, 0)
        # a scout job queued some other way says why and fetches nothing
        jobs.enqueue(self.conn, "scout", str(self.nextdc), company_id=self.nextdc)
        self.assertTrue(run(self.worker("scout").run_once()))
        self.assertIn("waiting for ASX terms", json.loads(self.conn.execute("SELECT notes FROM runs").fetchone()[0]))
        self.assertEqual((self.listed, self.documents()), ([], {}))

    def test_scan_registers_the_deals_from_the_last_400_days(self):
        directors.accept_asx_terms(True)
        self.assertEqual(run(asx.scan(self.conn, self.nextdc, today=TODAY)), {"code": "NXT", "listed": 22, "found": 6, "new": 6})
        self.assertEqual(self.listed, [("NXT", 2026), ("NXT", 2025)])
        documents = self.documents()
        self.assertEqual(sorted((d["filed_at"], d["title"]) for d in documents.values()), [
            ("2025-12-01", "Contract Utilisation & Capex Guidance Update"),
            ("2025-12-05", "Building the Next Generation of Sovereign AI infrastructure"),
            ("2025-12-05", "NEXTDC joins OpenAI for Australia as Infrastructure Partner"),
            ("2026-04-20", "Record Contracted Utilisation and A$2.2bn Capital Plan"),
            ("2026-07-21", "Contracted Utilisation Update"),
            ("2026-10-21", "M3 Melbourne Power Delay & Revised FY27 Guidance"),
        ])  # the board appointment of 26 Sep 2025 and the order book update of June 2025 are older than 400 days
        openai = documents["03037632"]
        self.assertEqual((openai["kind"], openai["url"], openai["status"], openai["language"], openai["company_id"]),
                         ("ASX announcement", asx_client.display_url("03037632"), "discovered", "en", self.nextdc))
        queued = {r["key"]: (r["priority"], json.loads(r["payload"])) for r in self.conn.execute("SELECT key, priority, payload FROM jobs")}
        self.assertEqual(queued["asx/03037632"], (30, {"source": "asx", "document_id": openai["id"], "ids_id": "03037632", "code": "NXT",
                                                       "form": "ASX announcement", "why": "deal"}))
        self.assertEqual(queued["asx/03037364"][0], 35)  # price sensitive: fetched first
        self.assertEqual(queued["asx/03037364"][1]["why"], "price sensitive")
        self.assertEqual(run(asx.scan(self.conn, self.nextdc, today=TODAY))["new"], 0)  # seen before: nothing again
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 6)

    def test_january_reaches_back_two_years(self):
        directors.accept_asx_terms(True)
        run(asx.scan(self.conn, self.nextdc, today=date(2027, 1, 10)))
        self.assertEqual(self.listed, [("NXT", 2027), ("NXT", 2026), ("NXT", 2025)])

    def test_worker_scouts_downloads_and_queues_the_reads(self):
        directors.accept_asx_terms(True)
        saved = []

        async def download(ids_id, code, folder=None):
            saved.append((ids_id, code))
            return {"path": f"/x/{ids_id}.pdf", "sha256": ids_id.rjust(64, "0"), "size": 9, "pdf_url": "https://announcements.asx.com.au/a.pdf"}
        self.assertEqual(scout.schedule(self.conn), 1)
        w = self.worker("scout", "download")
        with mock.patch.object(asx_client, "download", download):
            while run(w.run_once()):
                pass
        self.assertEqual(saved[0], ("03154955", "NXT"))  # price sensitive ones first, the newest of them first
        self.assertEqual(len(saved), 6)
        self.assertEqual({d["status"] for d in self.documents().values()}, {"downloaded"})
        reads = self.conn.execute("SELECT priority FROM jobs WHERE kind = 'read'").fetchall()
        self.assertEqual([r["priority"] for r in reads], [reader.READ_PRIORITY["ASX announcement"]] * 6)
        notes = [json.loads(r[0]) for r in self.conn.execute("SELECT notes FROM runs ORDER BY id")]
        self.assertEqual(notes[0], "6 ASX announcements worth reading (of 22), 6 new")
        row = next(r for r in status.company_rows(self.conn) if r["company_id"] == self.nextdc)
        self.assertEqual((row["status"], row["latest_filing"], row["filings"]), ("waiting", "ASX announcement 21 Oct", 6))  # the reads are queued
        filings = status.company_filings(self.conn, self.nextdc)
        self.assertEqual((filings[0]["label"], filings[0]["url"]), ("ASX announcement 21 Oct", asx_client.display_url("03154955")))

    def test_no_deals_is_said_in_the_notes(self):
        directors.accept_asx_terms(True)
        before = dict(PAGES)
        self.addCleanup(lambda: PAGES.update(before))
        PAGES.clear()
        scout.schedule(self.conn)
        run(self.worker("scout").run_once())
        self.assertEqual(json.loads(self.conn.execute("SELECT notes FROM runs").fetchone()[0]),
                         "no contract announcements on the ASX in the last 400 days (0 announcements)")
        self.assertEqual(next(r for r in status.company_rows(self.conn) if r["company_id"] == self.nextdc)["status"], "up to date")

    def test_a_missing_announcement_is_a_permanent_failure(self):
        directors.accept_asx_terms(True)
        run(asx.scan(self.conn, self.nextdc, today=TODAY))

        async def gone(*args, **kwargs):
            raise asx_client.AsxNotFound("www.asx.com.au has nothing at that address.")
        self.conn.execute("DELETE FROM jobs WHERE key != 'asx/03037632'")
        with mock.patch.object(asx_client, "download", gone):
            run(self.worker("download").run_once())
        self.assertEqual(self.conn.execute("SELECT status FROM jobs").fetchone()[0], "failed")
        self.assertEqual(self.documents()["03037632"]["status"], "failed")

    def test_withdrawn_terms_stop_the_downloads(self):
        directors.accept_asx_terms(True)
        run(asx.scan(self.conn, self.nextdc, today=TODAY))
        directors.accept_asx_terms(False)
        with mock.patch.object(asx_client, "download", mock.AsyncMock()) as download:
            run(self.worker("download").run_once())
        download.assert_not_called()
        self.assertEqual(self.conn.execute("SELECT status FROM jobs WHERE status != 'queued'").fetchone()[0], "failed")
        self.assertEqual(next(r for r in status.company_rows(self.conn) if r["company_id"] == self.nextdc)["status"], "waiting for ASX terms")
        # accepted again: the next scout queues the announcement whose download failed
        directors.accept_asx_terms(True)
        failed = self.conn.execute("SELECT key FROM jobs WHERE status = 'failed'").fetchone()["key"]
        run(asx.scan(self.conn, self.nextdc, today=TODAY))
        self.assertEqual(self.conn.execute("SELECT status FROM jobs WHERE key = ? ORDER BY id DESC", (failed,)).fetchone()["status"], "queued")

    def test_a_company_with_a_us_listing_is_read_from_edgar_only(self):
        dual = self.company("Dual Listed Ltd", ("DUAL", "US"), ("DUL", "ASX"))
        self.assertTrue(scout.uses_asx(self.conn, self.nextdc))
        self.assertFalse(scout.uses_asx(self.conn, dual))
        self.assertNotIn(dual, status.asx_only_ids(self.conn))


class Reading(unittest.TestCase):
    def test_the_whole_announcement_is_read_with_its_pdf_pages(self):
        self.assertIsNone(chunker.FINDERS["asx"](["a"], "ASX announcement"))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "03037364.pdf"
            path.write_bytes(make_pdf(ANNOUNCEMENT))
            chunks = chunker.chunk_file(path, "asx", "ASX announcement")
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertEqual(chunk.section, "Full text")
        self.assertIn("Memorandum of Understanding with OpenAI", chunk.text)
        self.assertIn("About NEXTDC", chunk.text)  # the company profile is kept: it can name customers
        self.assertEqual(chunk.headings[0], "PDF page 1")
        self.assertEqual(chunk.headings[-1], "PDF page 2")
        found = reader.locate(chunk, "today it agreed a Memorandum of Understanding with OpenAI")
        self.assertEqual(chunker.locator_for(chunk.section, chunk.numbers[found[0]], chunk.numbers[found[1]], chunk.headings[found[0]]),
                         "Full text, PDF page 1, paragraph 2 [chunker v1]")

    def test_the_reader_and_verifier_name_the_announcement(self):
        with tempfile.TemporaryDirectory() as folder:
            conn = open_graph(Path(folder) / "g.sqlite")
            try:
                company = graph.add_company(conn, "NEXTDC Limited")
                document = graph.add_document(conn, "asx", asx.KIND, "03037364", asx_client.display_url("03037364"), company_id=company,
                                              title="Building the Next Generation of Sovereign AI infrastructure", filed_at="2025-12-05")
                row = conn.execute("SELECT * FROM documents WHERE id = ?", (document,)).fetchone()
                chunk = chunker.chunk_paragraphs(["NEXTDC agreed an MoU with OpenAI."], "asx", asx.KIND, "03037364.pdf")[0]
                message = reader.user_message({"name": "NEXTDC Limited", "ticker": "NXT"}, dict(row), chunk)
                self.assertIn("Form: ASX announcement, filed 2025-12-05\n", message)
                label = verifier.placeholder_label(conn, {"document_id": document, "customer_name": "Customer A"}, "customer")
                self.assertEqual(label, "Customer A in the ASX announcement filed 2025-12-05")
                self.assertEqual(status.filing_label(row), "ASX announcement 5 Dec")
                self.assertTrue(reader.should_read(asx.KIND))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
