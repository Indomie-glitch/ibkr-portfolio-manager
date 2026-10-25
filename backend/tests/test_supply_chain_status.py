import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import config
from fastapi import HTTPException
from routers import pipeline as routes
from supply_chain import control, db, graph, jobs, status, worker
from supply_chain.db import open_graph

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def run(coro):
    return asyncio.run(coro)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "supply_chain.sqlite"
        patch = mock.patch.object(db, "DB_PATH", self.path)
        patch.start()
        self.addCleanup(patch.stop)
        env = mock.patch.object(config, "pipeline_enabled", lambda: False)
        env.start()
        self.addCleanup(env.stop)
        control.active_workers = 0
        self.conn = open_graph(self.path)

    def company(self, name, ticker=None, theme="t"):
        company_id = graph.add_company(self.conn, name)
        if ticker:
            graph.add_identifier(self.conn, company_id, "ticker", ticker, "US")
        if theme:
            theme_id = graph.add_theme(self.conn, theme, "AI hardware")
            graph.add_to_theme(self.conn, theme_id, company_id)
        return company_id

    def document(self, company_id, kind="10-K", filed="2026-02-25", period="2026-01-25", ext="a", status="downloaded"):
        return graph.add_document(self.conn, "sec", kind, f"{ext}/x.htm", "https://x", company_id=company_id, filed_at=filed, period_end=period, status=status)

    def run_job(self, kind, key, company_id, outcome="ok", notes=None, cost=None, document_id=None, payload=None, error=None):
        job_id, _ = jobs.enqueue(self.conn, kind, key, payload, company_id=company_id, document_id=document_id, now=NOW)
        job = jobs.claim(self.conn, "w", now=NOW)
        assert job["id"] == job_id
        if outcome == "ok":
            jobs.finish(self.conn, job, notes=notes, cost_usd=cost, now=NOW)
        elif outcome == "failed":
            jobs.fail(self.conn, job, error or "boom", permanent=True, now=NOW)
        elif outcome == "retry":
            jobs.fail(self.conn, job, error or "boom", now=NOW, jitter=False)
        return job_id


class Settings(Base):
    def test_defaults_follow_the_environment_until_chosen(self):
        self.assertEqual(control.load_settings(), {"enabled": False, "paused": False, "budget_usd": 10.0})
        with mock.patch.object(config, "pipeline_enabled", lambda: True):
            self.assertTrue(control.load_settings()["enabled"])
            control.save_settings(enabled=False)  # a choice in the app wins over .env
            self.assertFalse(control.load_settings()["enabled"])

    def test_saved_and_kept_between_loads(self):
        control.save_settings(enabled=True, budget_usd=25)
        control.save_settings(paused=True)
        self.assertEqual(control.load_settings(), {"enabled": True, "paused": True, "budget_usd": 25.0})
        self.assertTrue((Path(self.tmp.name) / "pipeline_settings.json").exists())

    def test_nonsense_budgets_are_refused(self):
        for bad in (0, -5, 5000, True, "10"):
            with self.assertRaises(ValueError):
                control.save_settings(budget_usd=bad)
        self.assertEqual(control.load_settings()["budget_usd"], 10.0)

    def test_a_damaged_file_means_the_defaults(self):
        (Path(self.tmp.name) / "pipeline_settings.json").write_text("{not json")
        self.assertEqual(control.load_settings()["budget_usd"], 10.0)

    def test_should_run_needs_on_unpaused_and_budget_left(self):
        control.save_settings(enabled=True)
        self.assertTrue(control.should_run(self.conn))
        control.save_settings(paused=True)
        self.assertFalse(control.should_run(self.conn))
        control.save_settings(paused=False, budget_usd=1)
        self.run_job("scout", "1", None, cost=1.5)
        self.assertFalse(control.should_run(self.conn))
        self.assertEqual(control.status_word(self.conn), "budget")
        control.save_settings(enabled=False)
        self.assertEqual(control.status_word(self.conn), "off")

    def test_the_budget_starts_again_next_month(self):
        control.save_settings(enabled=True, budget_usd=1)
        self.run_job("scout", "1", None, cost=2)
        self.assertTrue(control.budget_used_up(self.conn, now=datetime.now(timezone.utc)))
        next_month = (datetime.now(timezone.utc).replace(day=28) + timedelta(days=10)).replace(day=2)
        self.assertFalse(control.budget_used_up(self.conn, now=next_month))

    def test_status_word_starting_then_running(self):
        control.save_settings(enabled=True)
        self.assertEqual(control.status_word(self.conn), "starting")
        control.active_workers = 2
        self.assertEqual(control.status_word(self.conn), "running")


class Companies(Base):
    def test_status_for_each_situation(self):
        failed, reading, waiting, fresh, empty, unseen = (self.company(n, n[:4].upper()) for n in
                                                          ("Failed Co", "Reading Co", "Waiting Co", "Fresh Co", "Empty Co", "Unseen Co"))
        self.run_job("download", "f", failed, outcome="failed", document_id=self.document(failed, ext="f"))
        self.run_job("scout", str(fresh), fresh, notes="1 filings seen, 1 new")
        self.document(fresh, ext="fresh")
        self.run_job("scout", str(empty), empty, notes='no SEC listing (no US ticker, or SEC doesn\'t know it)')
        jobs.enqueue(self.conn, "download", "r", company_id=reading, now=NOW)
        jobs.claim(self.conn, "w", now=NOW)  # reading
        jobs.enqueue(self.conn, "download", "w", company_id=waiting, now=NOW)
        got = {r["name"]: r for r in status.company_rows(self.conn, NOW)}
        self.assertEqual({n: r["status"] for n, r in got.items()},
                         {"Failed Co": "failed", "Reading Co": "reading", "Waiting Co": "waiting", "Fresh Co": "up to date",
                          "Empty Co": "not on EDGAR", "Unseen Co": "waiting"})

    def test_filing_label_links_and_cost(self):
        nvda = self.company("NVIDIA Corporation", "NVDA")
        other = self.company("Apple Inc.", "AAPL", theme=None)
        self.document(nvda, kind="10-K", filed="2026-02-25", period="2026-01-25", ext="k")
        self.document(nvda, kind="8-K", filed="2025-10-21", period=None, ext="e")
        self.run_job("xbrl", "k", nvda, notes="3 linked", cost=0.04)
        evidence = {"document_id": self.document(nvda, ext="k2"), "quote": "q", "tier": 1, "extractor": "xbrl"}
        stamp = (datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        graph.add_relationship(self.conn, nvda, other, evidence, supplier_revenue_share=22)
        self.conn.execute("UPDATE relationships SET first_seen = ?", (stamp,))
        row = status.company_rows(self.conn, datetime.now(timezone.utc))[0]
        self.assertEqual((row["symbol"], row["latest_filing"], row["links"], row["links_week"]), ("NVDA", "10-K 2026", 1, 1))
        self.assertEqual(row["cost_usd"], 0.04)

    def test_filing_labels(self):
        label = lambda **k: status.filing_label({"kind": k["kind"], "filed_at": k.get("filed"), "period_end": k.get("period")})
        self.assertEqual(label(kind="10-K", period="2026-01-25"), "10-K 2026")
        self.assertEqual(label(kind="20-F", period="2025-12-31"), "20-F 2025")
        self.assertEqual(label(kind="10-Q", period="2026-06-27"), "10-Q Jun 2026")
        self.assertEqual(label(kind="8-K", filed="2026-10-21"), "8-K 21 Oct")
        self.assertEqual(label(kind="6-K"), "6-K")

    def test_company_filings_with_their_download_state(self):
        company = self.company("A Co", "AAAA")
        document = self.document(company, ext="one", status="failed")
        self.run_job("download", "one", company, outcome="failed", document_id=document, error="SEC answered 500")
        filings = status.company_filings(self.conn, company)
        self.assertEqual((filings[0]["label"], filings[0]["job_status"], filings[0]["error"]), ("10-K 2026", "failed", "SEC answered 500"))

    def test_only_theme_companies_are_listed(self):
        self.company("Watched", "WWWW")
        self.company("Not watched", "NNNN", theme=None)
        self.assertEqual([r["name"] for r in status.company_rows(self.conn, NOW)], ["Watched"])


class Overview(Base):
    def test_tiles(self):
        a, b = self.company("A Co", "AAAA"), self.company("B Co", "BBBB")
        self.document(a, ext="a")
        self.run_job("scout", str(a), a, notes="1 filings seen, 1 new", cost=0.5)
        self.run_job("download", "z", b, outcome="failed")
        self.run_job("download", "y", b, outcome="retry")
        control.save_settings(enabled=True, budget_usd=2)
        overview = status.overview(self.conn, NOW)
        self.assertEqual(overview["watched"], 2)
        self.assertEqual(overview["coverage"], {"read": 1, "total": 2, "not_on_edgar": 0})
        self.assertEqual(overview["attention"], {"stuck": 1, "retrying": 1, "total": 2})
        self.assertEqual((overview["cost"]["month"], overview["cost"]["percent"], overview["cost"]["budget_left"]), (0.5, 25, 1.5))
        self.assertEqual(overview["themes"], ["AI hardware"])
        self.assertTrue(overview["started"])

    def test_empty_database(self):
        overview = status.overview(self.conn, NOW)
        self.assertEqual((overview["status"], overview["watched"], overview["started"], overview["links"]["total"]), ("off", 0, False, 0))


class Log(Base):
    def test_events_newest_first_with_tags(self):
        nvda = self.company("NVIDIA Corporation", "NVDA")
        self.run_job("scout", str(nvda), nvda, notes="5 filings seen, 5 new")
        self.run_job("xbrl", "k", nvda, notes="8 linked, 2 unresolved", cost=0.04, payload={"filing": {"form": "10-K"}})
        self.run_job("download", "x", nvda, outcome="failed", error="SEC no response", payload={"form": "8-K"})
        events = status.log_events(self.conn)
        self.assertEqual({e["tag"] for e in events}, {"SCOUT", "DONE", "FAIL"})
        fail = next(e for e in events if e["tag"] == "FAIL")
        self.assertIn("fetch NVDA 8-K", fail["text"])
        self.assertIn("SEC no response", fail["text"])
        self.assertIsNotNone(fail["job_id"])
        done = next(e for e in events if e["tag"] == "DONE")
        self.assertIn("read NVDA 10-K", done["text"])
        self.assertIn("US$0.04", done["text"])

    def test_link_lines(self):
        supplier = self.company("Micron", "MU")
        apple = self.company("Apple Inc.", "AAPL", theme=None)
        placeholder = graph.add_company(self.conn, "Customer A (unnamed customer of Micron, year to 2025-08-28)", placeholder_for=supplier)
        document = self.document(supplier)
        evidence = lambda q: {"document_id": document, "quote": q, "tier": 1, "extractor": "xbrl"}
        graph.add_relationship(self.conn, supplier, apple, evidence("a"), supplier_revenue_share=12)
        graph.add_relationship(self.conn, supplier, placeholder, evidence("b"), supplier_revenue_share=17)
        texts = {e["text"] for e in status.log_events(self.conn, kind="links")}
        self.assertEqual(texts, {"MU → AAPL · 12% of revenue", "MU → Customer A (Micron, FY2025) · 17% of revenue"})

    def test_filters(self):
        a = self.company("A Co", "AAAA")
        self.run_job("scout", str(a), a, notes="n")
        self.run_job("download", "d", a, outcome="failed")
        self.assertEqual({e["tag"] for e in status.log_events(self.conn, kind="failed")}, {"FAIL"})
        self.assertEqual(status.log_events(self.conn, kind="links"), [])

    def test_a_running_job_is_a_run_line_and_a_retried_one_says_when(self):
        a = self.company("A Co", "AAAA")
        jobs.enqueue(self.conn, "download", "r", {"form": "10-K"}, company_id=a, now=NOW)
        jobs.claim(self.conn, "w", now=NOW)
        self.assertEqual(status.log_events(self.conn)[0]["tag"], "RUN")
        self.run_job("download", "q", a, outcome="retry", error="SEC no response")
        self.assertIn("retry", next(e for e in status.log_events(self.conn) if e["tag"] == "FAIL")["text"])


class Actions(Base):
    def test_retry_one_job_or_all_of_a_company(self):
        a = self.company("A Co", "AAAA")
        first = self.run_job("download", "1", a, outcome="failed")
        self.run_job("download", "2", a, outcome="failed")
        self.assertEqual(status.retry(self.conn, job_id=first), 1)
        self.assertEqual(status.retry(self.conn, company_id=a), 1)  # only the one still failed
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued'").fetchone()[0], 2)
        with self.assertRaises(ValueError):
            status.retry(self.conn)

    def test_run_now_queues_every_company_and_resumes(self):
        for n in ("A", "B", "C"):
            self.company(n + " Co", n * 4)
        control.save_settings(enabled=True, paused=True)
        self.assertEqual(status.run_now(self.conn), 3)
        self.assertEqual(status.run_now(self.conn), 0)  # already queued
        self.assertFalse(control.load_settings()["paused"])


class Routes(Base):
    def request(self, origin=None):
        return mock.Mock(headers={"origin": origin} if origin else {})

    def test_overview_and_settings(self):
        self.company("A Co", "AAAA")
        answer = routes.pipeline_overview()
        self.assertEqual(answer["settings"]["budget_default"], 10.0)
        self.assertEqual(answer["status"], "off")

    def test_change_settings_checks_origin_and_budget(self):
        change = routes.SettingsChange(enabled=True, budget_usd=12)
        self.assertTrue(routes.change_settings(change, self.request())["enabled"])
        with self.assertRaises(HTTPException) as raised:
            routes.change_settings(change, self.request("https://evil.example"))
        self.assertEqual(raised.exception.status_code, 403)
        with self.assertRaises(HTTPException) as raised:
            routes.change_settings(routes.SettingsChange(budget_usd=-1), self.request())
        self.assertEqual(raised.exception.status_code, 400)

    def test_run_now_needs_the_pipeline_on(self):
        with self.assertRaises(HTTPException) as raised:
            routes.run_now(self.request())
        self.assertEqual(raised.exception.status_code, 409)
        control.save_settings(enabled=True)
        self.company("A Co", "AAAA")
        self.assertEqual(routes.run_now(self.request())["queued"], 1)

    def test_log_filter_and_retry(self):
        a = self.company("A Co", "AAAA")
        job = self.run_job("download", "d", a, outcome="failed")
        self.assertEqual(len(routes.pipeline_log("failed")["events"]), 1)
        self.assertEqual(routes.retry(routes.Retry(job_id=job), self.request())["requeued"], 1)
        with self.assertRaises(HTTPException):
            routes.retry(routes.Retry(), self.request())

    def test_companies_and_filings(self):
        a = self.company("A Co", "AAAA")
        self.document(a)
        self.assertEqual(routes.pipeline_companies()["companies"][0]["symbol"], "AAAA")
        self.assertEqual(len(routes.pipeline_company_filings(a)["filings"]), 1)


class Supervisor(Base):
    def test_workers_start_stop_and_restart_with_the_switches(self):
        started = []

        async def fake_run_workers(path, count):
            started.append(count)
            control.active_workers = count
            try:
                await asyncio.sleep(3600)
            finally:
                control.active_workers = 0

        async def scenario():
            with mock.patch.object(worker, "run_workers", fake_run_workers):
                task = asyncio.create_task(worker.keep_running(self.path, count=2, every_s=0.01))
                await asyncio.sleep(0.05)
                self.assertEqual(started, [])  # off
                control.save_settings(enabled=True)
                await asyncio.sleep(0.05)
                self.assertEqual((started, control.active_workers), ([2], 2))
                control.save_settings(paused=True)
                await asyncio.sleep(0.05)
                self.assertEqual(control.active_workers, 0)
                control.save_settings(paused=False)
                await asyncio.sleep(0.05)
                self.assertEqual((started, control.active_workers), ([2, 2], 2))
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                await asyncio.sleep(0.02)
                self.assertEqual(control.active_workers, 0)
        run(scenario())

    def test_the_watch_list_is_loaded_even_while_off(self):
        async def scenario():
            task = asyncio.create_task(worker.keep_running(self.path, count=1, every_s=0.01))
            await asyncio.sleep(0.1)
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        run(scenario())
        self.assertGreater(len(status.watched_ids(self.conn)), 40)
        self.assertEqual(status.overview(self.conn)["status"], "off")

    def test_budget_used_up_stops_the_workers(self):
        async def fake_run_workers(path, count):
            control.active_workers = count
            try:
                await asyncio.sleep(3600)
            finally:
                control.active_workers = 0

        async def scenario():
            control.save_settings(enabled=True, budget_usd=1)
            with mock.patch.object(worker, "run_workers", fake_run_workers):
                task = asyncio.create_task(worker.keep_running(self.path, count=1, every_s=0.01))
                await asyncio.sleep(0.05)
                self.assertEqual(control.active_workers, 1)
                self.run_job("scout", "1", None, cost=2)
                await asyncio.sleep(0.05)
                self.assertEqual(control.active_workers, 0)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        run(scenario())


if __name__ == "__main__":
    unittest.main()
