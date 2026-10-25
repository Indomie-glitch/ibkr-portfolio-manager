import asyncio
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sec_client
from supply_chain import graph, sec
from supply_chain.db import open_graph

SUBMISSIONS = {"name": "Apple Inc.", "filings": {
    "recent": {"accessionNumber": ["0000320193-25-000079", "0000320193-25-000050", "0000320193-24-000100"],
               "form": ["10-K", "8-K", "10-Q"], "filingDate": ["2025-10-31", "2025-08-01", "2024-05-02"],
               "reportDate": ["2025-09-27", "", "2024-03-30"], "items": ["", "2.02,9.01", ""],
               "primaryDocument": ["aapl-10k.htm", "aapl-8k.htm", "aapl-10q.htm"], "primaryDocDescription": ["10-K", "8-K", "10-Q"],
               "size": [1, 2, 3], "isXBRL": [1, 0, 1], "isInlineXBRL": [1, 0, 1]},
    "files": [{"name": "CIK0000320193-submissions-001.json", "filingFrom": "2010-01-01", "filingTo": "2015-12-31"}]}}
OLDER = {"accessionNumber": ["0001193125-12-444068"], "form": ["10-K"], "filingDate": ["2012-10-31"], "reportDate": ["2012-09-29"],
         "items": [""], "primaryDocument": ["d411355d10k.htm"], "primaryDocDescription": ["10-K"], "size": [9], "isXBRL": [1], "isInlineXBRL": [0]}


def run(coro):
    return asyncio.run(coro)


class Fetching(unittest.TestCase):
    def setUp(self):
        sec_client._last = 0.0
        patch = mock.patch.object(sec_client.config, "sec_contact_email", lambda: "me@example.com")
        patch.start()
        self.addCleanup(patch.stop)
        sleeps = mock.patch.object(sec_client.asyncio, "sleep", mock.AsyncMock())
        self.sleeps = sleeps.start()
        self.addCleanup(sleeps.stop)

    def answers(self, *replies):
        calls = []
        queue = list(replies)

        def fake(url, request_headers, timeout, max_bytes):
            calls.append((url, request_headers))
            reply = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(reply, Exception):
                raise reply
            return reply
        return calls, mock.patch.object(sec_client, "_open", fake)

    def test_user_agent_names_the_contact(self):
        calls, patch = self.answers((200, {}, b"{}"))
        with patch:
            run(sec_client.get_bytes("https://x/y"))
        self.assertEqual(calls[0][1]["User-Agent"], "PortfolioManager me@example.com")

    def test_no_email_is_unavailable(self):
        with mock.patch.object(sec_client.config, "sec_contact_email", lambda: None):
            with self.assertRaises(sec_client.SecUnavailable):
                run(sec_client.get_bytes("https://x/y"))

    def test_busy_is_retried_with_retry_after(self):
        calls, patch = self.answers((429, {"Retry-After": "7"}, b""), (503, {}, b""), (200, {}, b"ok"))
        with patch:
            self.assertEqual(run(sec_client.get_bytes("https://x/y")), b"ok")
        self.assertEqual(len(calls), 3)
        waits = [c.args[0] for c in self.sleeps.call_args_list if c.args[0] >= 5]
        self.assertEqual(waits, [7, 20])

    def test_gives_up_after_the_retries(self):
        calls, patch = self.answers((503, {}, b""))
        with patch, self.assertRaises(sec_client.SecUnavailable):
            run(sec_client.get_bytes("https://x/y"))
        self.assertEqual(len(calls), 4)

    def test_dropped_connection_is_retried(self):
        calls, patch = self.answers(ConnectionError("reset"), (200, {}, b"ok"))
        with patch:
            self.assertEqual(run(sec_client.get_bytes("https://x/y")), b"ok")

    def test_404_is_not_retried(self):
        calls, patch = self.answers((404, {}, b""))
        with patch, self.assertRaises(sec_client.SecNotFound):
            run(sec_client.get_bytes("https://x/y"))
        self.assertEqual(len(calls), 1)

    def test_403_explains(self):
        calls, patch = self.answers((403, {}, b""))
        with patch, self.assertRaises(sec_client.SecUnavailable) as raised:
            run(sec_client.get_bytes("https://x/y"))
        self.assertIn("SEC_CONTACT_EMAIL", str(raised.exception))
        self.assertEqual(len(calls), 1)

    def test_too_large(self):
        calls, patch = self.answers((200, {}, b"x" * 11))
        with patch, self.assertRaises(sec_client.SecUnavailable):
            run(sec_client.get_bytes("https://x/y", max_bytes=10))


class Lookups(unittest.TestCase):
    def setUp(self):
        sec_client._last = 0.0
        sec_client._tickers.update(at=0.0, map=None)
        sec_client._submissions.clear()
        for target, value in (("sec_contact_email", lambda: "me@example.com"),):
            patch = mock.patch.object(sec_client.config, target, value)
            patch.start()
            self.addCleanup(patch.stop)

    def fake_json(self, pages):
        calls = []

        async def fake(url):
            calls.append(url)
            for suffix, page in pages.items():
                if url.endswith(suffix):
                    return page
            raise sec_client.SecNotFound(url)
        return calls, mock.patch.object(sec_client, "get_json", fake)

    def test_ticker_to_cik(self):
        calls, patch = self.fake_json({"company_tickers.json": {"0": {"cik_str": 1067983, "ticker": "BRK-B"}, "1": {"cik_str": 320193, "ticker": "AAPL"}}})
        with patch:
            self.assertEqual(run(sec_client.cik_for_ticker("BRK B")), 1067983)
            self.assertEqual(run(sec_client.cik_for_ticker("aapl")), 320193)
            self.assertIsNone(run(sec_client.cik_for_ticker("NOPE")))
        self.assertEqual(len(calls), 1)

    def test_filings_filtered_by_form(self):
        calls, patch = self.fake_json({"CIK0000320193.json": SUBMISSIONS})
        with patch:
            found = run(sec_client.list_filings(320193, forms=("10-K", "10-Q"), since="2024-01-01"))
        self.assertEqual([f["form"] for f in found], ["10-K", "10-Q"])
        self.assertEqual(found[0]["url"], "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-10k.htm")
        self.assertEqual(found[0]["period"], "2025-09-27")
        self.assertEqual(len(calls), 1)  # reaches back only to 2024: no older page

    def test_older_pages_only_when_asked_for(self):
        calls, patch = self.fake_json({"CIK0000320193.json": SUBMISSIONS, "submissions-001.json": OLDER})
        with patch:
            everything = run(sec_client.list_filings(320193, forms=("10-K",)))
            self.assertEqual([f["filed"] for f in everything], ["2025-10-31", "2012-10-31"])
            sec_client._submissions.clear()
            calls.clear()
            run(sec_client.list_filings(320193, since="2020-01-01"))
        self.assertEqual(len(calls), 1)

    def test_items_and_missing_period(self):
        calls, patch = self.fake_json({"CIK0000320193.json": SUBMISSIONS, "submissions-001.json": OLDER})
        with patch:
            eight_k = run(sec_client.list_filings(320193, forms=("8-K",)))[0]
        self.assertEqual(eight_k["items"], ["2.02", "9.01"])
        self.assertIsNone(eight_k["period"])

    def test_index_lookup(self):
        index = {"directory": {"item": [{"name": "aapl-10k.htm", "type": "10-K", "size": "1234"}, {"name": "ex21.htm", "type": "EX-21", "size": ""}]}}
        calls, patch = self.fake_json({"/000032019325000079/index.json": index})
        with patch:
            files = run(sec_client.filing_files(320193, "0000320193-25-000079"))
        self.assertEqual([f["name"] for f in files], ["aapl-10k.htm", "ex21.htm"])
        self.assertEqual(files[0]["size"], 1234)
        self.assertIsNone(files[1]["size"])
        self.assertTrue(files[1]["url"].endswith("/000032019325000079/ex21.htm"))


class Downloading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_safe_name(self):
        self.assertEqual(sec_client.safe_name("../../etc/passwd"), "passwd")
        self.assertEqual(sec_client.safe_name(".hidden"), "hidden")
        self.assertEqual(sec_client.safe_name(""), "document")
        self.assertEqual(sec_client.safe_name("a b?.htm"), "a_b_.htm")

    def test_download_hashes_and_writes(self):
        body = b"<html>filing</html>"

        async def fake(url, max_bytes=0):
            return body
        with mock.patch.object(sec_client, "get_bytes", fake):
            saved = run(sec_client.download(320193, "0000320193-25-000079", "aapl-10k.htm", folder=self.tmp.name))
        self.assertEqual(saved["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(Path(saved["path"]).read_bytes(), body)
        self.assertEqual(sec_client.file_sha256(saved["path"]), saved["sha256"])
        self.assertFalse(list(Path(self.tmp.name).glob("*.part")))

    def test_register_and_fetch_into_store(self):
        conn = open_graph(Path(self.tmp.name) / "g.sqlite")
        company = graph.add_company(conn, "Apple Inc.")
        filing = {"accession": "0000320193-25-000079", "form": "10-K", "filed": "2025-10-31", "period": "2025-09-27",
                  "primary_document": "aapl-10k.htm", "url": "https://www.sec.gov/x"}
        first = sec.register_filing(conn, company, 320193, filing)
        self.assertEqual(sec.register_filing(conn, company, 320193, filing), first)
        self.assertIsNone(sec.register_filing(conn, company, 320193, {**filing, "primary_document": None}))
        calls = []

        async def fake(cik, accession, filename):
            calls.append(filename)
            return {"sha256": "abc", "size": 5, "path": "/tmp/x"}
        with mock.patch.object(sec_client, "download", fake):
            self.assertEqual(run(sec.fetch_document(conn, first, 320193, filing["accession"], "aapl-10k.htm")), "abc")
            run(sec.fetch_document(conn, first, 320193, filing["accession"], "aapl-10k.htm"))
        self.assertEqual(calls, ["aapl-10k.htm"])
        row = conn.execute("SELECT status, content_hash, size_bytes FROM documents WHERE id = ?", (first,)).fetchone()
        self.assertEqual((row["status"], row["content_hash"], row["size_bytes"]), ("downloaded", "abc", 5))


if __name__ == "__main__":
    unittest.main()
