import asyncio
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import sec_client
from supply_chain import graph, jobs, scout, sec, worker
from supply_chain.db import open_graph

TODAY = date(2026, 10, 25)


def filing(accession, form, filed, doc="main.htm"):
    return {"accession": accession, "form": form, "filed": filed, "period": None, "items": [], "primary_document": doc,
            "url": f"https://www.sec.gov/{accession}/{doc}"}


def run(coro):
    return asyncio.run(coro)


class Scout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "g.sqlite"
        self.conn = open_graph(self.path)
        self.nvda = graph.add_company(self.conn, "NVIDIA Corporation")
        graph.add_identifier(self.conn, self.nvda, "ticker", "NVDA", "US")
        self.theme = graph.add_theme(self.conn, "t", "T")
        graph.add_to_theme(self.conn, self.theme, self.nvda)
        self.filings = []
        self.listed = []

        async def cik_for_ticker(symbol):
            return {"NVDA": 1045810}.get(symbol)

        async def list_filings(cik, forms=None, since=None, until=None):
            self.listed.append((cik, forms, since))
            return self.filings
        for name, fake in (("cik_for_ticker", cik_for_ticker), ("list_filings", list_filings)):
            patch = mock.patch.object(sec_client, name, fake)
            patch.start()
            self.addCleanup(patch.stop)

    def scan(self):
        return run(scout.scan(self.conn, self.nvda, today=TODAY))

    def open_jobs(self, kind="download"):
        return self.conn.execute("SELECT key, priority FROM jobs WHERE kind = ? ORDER BY id", (kind,)).fetchall()

    def test_new_filings_are_registered_and_queued(self):
        self.filings = [filing("0001-26-1", "10-K", "2026-02-20"), filing("0001-26-2", "8-K", "2026-10-01")]
        self.assertEqual(self.scan(), {"cik": 1045810, "found": 2, "new": 2})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM documents WHERE company_id = ?", (self.nvda,)).fetchone()[0], 2)
        self.assertEqual([(r["key"], r["priority"]) for r in self.open_jobs()], [("0001-26-1/main.htm", 60), ("0001-26-2/main.htm", 30)])

    def test_second_scan_finds_nothing_new(self):
        self.filings = [filing("0001-26-1", "10-Q", "2026-08-05")]
        self.scan()
        self.assertEqual(self.scan(), {"cik": 1045810, "found": 1, "new": 0})
        self.assertEqual(len(self.open_jobs()), 1)

    def test_cik_is_stored_and_reused(self):
        self.scan()
        self.assertEqual(scout.cik_of(self.conn, self.nvda), 1045810)
        with mock.patch.object(sec_client, "cik_for_ticker", side_effect=AssertionError("asked again")):
            self.scan()

    def test_old_8k_is_skipped_but_old_10k_is_kept(self):
        self.filings = [filing("a", "8-K", "2026-06-01"), filing("b", "10-K", "2025-10-01")]
        self.assertEqual(self.scan()["new"], 1)
        self.assertEqual([r["key"] for r in self.open_jobs()], ["b/main.htm"])

    def test_filing_without_document_is_ignored(self):
        self.filings = [filing("a", "10-K", "2026-02-20", doc=None)]
        self.assertEqual(self.scan(), {"cik": 1045810, "found": 0, "new": 0})

    def test_foreign_company_without_us_ticker_is_skipped(self):
        other = graph.add_company(self.conn, "Samsung")
        graph.add_identifier(self.conn, other, "ticker", "005930", "KR")
        self.assertEqual(run(scout.scan(self.conn, other, today=TODAY))["cik"], None)
        self.assertEqual(self.listed, [])

    def test_unknown_to_sec(self):
        other = graph.add_company(self.conn, "Nobody")
        graph.add_identifier(self.conn, other, "ticker", "ZZZZ", "US")
        self.assertIsNone(run(scout.scan(self.conn, other, today=TODAY))["cik"])

    def test_cik_owned_by_another_company_is_not_guessed(self):
        twin = graph.add_company(self.conn, "NVIDIA twin")
        graph.add_identifier(self.conn, twin, "cik", "1045810")
        self.assertIsNone(run(scout.resolve_cik(self.conn, self.nvda)))

    def test_discovered_document_without_job_is_picked_up_again(self):
        self.filings = [filing("a", "10-K", "2026-02-20")]
        sec.register_filing(self.conn, self.nvda, 1045810, self.filings[0])
        self.assertEqual(self.scan()["new"], 0)
        self.assertEqual(len(self.open_jobs()), 1)


class Scheduling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conn = open_graph(Path(self.tmp.name) / "g.sqlite")
        theme = graph.add_theme(self.conn, "t", "T")
        self.ids = [graph.add_company(self.conn, n) for n in ("A", "B")]
        for i in self.ids:
            graph.add_to_theme(self.conn, theme, i)
        graph.add_company(self.conn, "Not in a theme")
        self.now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

    def test_queues_each_theme_company_once(self):
        self.assertEqual(scout.schedule(self.conn, self.now), 2)
        self.assertEqual(scout.schedule(self.conn, self.now), 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs WHERE kind = 'scout'").fetchone()[0], 2)

    def test_due_again_after_the_interval(self):
        scout.schedule(self.conn, self.now)
        self.conn.execute("UPDATE jobs SET status = 'done'")
        self.assertEqual(scout.schedule(self.conn, self.now + timedelta(hours=1)), 0)
        self.assertEqual(scout.schedule(self.conn, self.now + timedelta(hours=13)), 2)

    def test_open_job_blocks_even_when_old(self):
        scout.schedule(self.conn, self.now)
        self.assertEqual(scout.schedule(self.conn, self.now + timedelta(days=3)), 0)


class Handlers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "g.sqlite"
        self.conn = open_graph(self.path)
        self.company = graph.add_company(self.conn, "A")
        graph.add_identifier(self.conn, self.company, "ticker", "A", "US")
        theme = graph.add_theme(self.conn, "t", "T")
        graph.add_to_theme(self.conn, theme, self.company)

    def test_worker_scouts_then_downloads(self):
        async def cik_for_ticker(symbol):
            return 5

        async def list_filings(cik, forms=None, since=None, until=None):
            return [filing("0005-26-1", "10-K", date.today().isoformat())]

        async def download(cik, accession, filename):
            return {"sha256": "ab" * 32, "size": 3, "path": "/x"}
        scout.schedule(self.conn)
        w = worker.Worker(self.path, handlers={"scout": scout.scout_job, "download": scout.download_job}, name="t")
        with mock.patch.object(sec_client, "cik_for_ticker", cik_for_ticker), mock.patch.object(sec_client, "list_filings", list_filings), \
                mock.patch.object(sec_client, "download", download):
            self.assertTrue(run(w.run_once()))
            self.assertTrue(run(w.run_once()))
            self.assertFalse(run(w.run_once()))
        row = self.conn.execute("SELECT status, content_hash FROM documents").fetchone()
        self.assertEqual((row["status"], row["content_hash"]), ("downloaded", "ab" * 32))
        self.assertEqual(self.conn.execute("SELECT status FROM jobs WHERE kind = 'download'").fetchone()[0], "done")

    def test_missing_filing_is_a_permanent_failure(self):
        document = sec.register_filing(self.conn, self.company, 5, filing("0005-26-1", "10-K", "2026-02-01"))
        jobs.enqueue(self.conn, "download", "0005-26-1/main.htm",
                     {"document_id": document, "cik": 5, "accession": "0005-26-1", "filename": "main.htm"}, document_id=document)

        async def gone(*args):
            raise sec_client.SecNotFound("gone")
        w = worker.Worker(self.path, handlers={"download": scout.download_job}, name="t")
        with mock.patch.object(sec_client, "download", gone):
            run(w.run_once())
        self.assertEqual(self.conn.execute("SELECT status FROM jobs").fetchone()[0], "failed")
        self.assertEqual(self.conn.execute("SELECT status FROM documents").fetchone()[0], "failed")


if __name__ == "__main__":
    unittest.main()
