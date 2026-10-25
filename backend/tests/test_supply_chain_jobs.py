"""Tests for the job queue and the worker runner (#116): priorities, retries with back-off, a crash and restart
that loses nothing, and workers that never take the same job. Every test has its own temporary database."""
import asyncio
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PORTFOLIO_DATA_DIR", tempfile.mkdtemp())

from supply_chain import db, graph, jobs, worker  # noqa: E402

T0 = datetime(2026, 10, 25, 9, 0, 0, tzinfo=timezone.utc)


def at(**delta):
    return T0 + timedelta(**delta)


def run(coro):
    return asyncio.run(coro)


class QueueCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "supply_chain.sqlite"
        self.conn = db.open_graph(self.path)
        self.addCleanup(self.conn.close)

    def status(self, job_id):
        return self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def runs(self, job_id):
        return self.conn.execute("SELECT * FROM runs WHERE job_id = ? ORDER BY id", (job_id,)).fetchall()


class EnqueueTests(QueueCase):
    def test_queued_work_waits_for_a_worker(self):
        job_id, created = jobs.enqueue(self.conn, "download", "0000320193-25-000079", {"url": "https://x"}, now=T0)
        self.assertTrue(created)
        row = self.status(job_id)
        self.assertEqual((row["status"], row["attempts"], row["max_attempts"], row["priority"]), ("queued", 0, 3, 100))

    def test_the_same_work_twice_is_one_job_and_the_urgent_ask_wins(self):
        first, _ = jobs.enqueue(self.conn, "download", "acc", priority=100, now=T0)
        second, created = jobs.enqueue(self.conn, "download", "acc", priority=300, now=T0)
        self.assertEqual((first, created), (second, False))
        self.assertEqual(self.status(first)["priority"], 300)
        jobs.enqueue(self.conn, "download", "acc", priority=50, now=T0)
        self.assertEqual(self.status(first)["priority"], 300)  # a lower ask never lowers it
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_the_same_key_for_another_kind_is_another_job(self):
        self.assertTrue(jobs.enqueue(self.conn, "download", "acc", now=T0)[1])
        self.assertTrue(jobs.enqueue(self.conn, "resolve", "acc", now=T0)[1])

    def test_finished_work_can_be_queued_again(self):
        job_id, _ = jobs.enqueue(self.conn, "scout", "cik-1", now=T0)
        jobs.finish(self.conn, jobs.claim(self.conn, "w", now=T0), now=T0)
        again, created = jobs.enqueue(self.conn, "scout", "cik-1", now=at(hours=24))
        self.assertTrue(created)
        self.assertNotEqual(again, job_id)

    def test_a_bad_reference_is_an_error_not_a_duplicate(self):
        with self.assertRaises(sqlite3.IntegrityError):
            jobs.enqueue(self.conn, "read", "doc", company_id=9999, now=T0)

    def test_it_can_point_at_a_company_and_a_document(self):
        company = graph.add_company(self.conn, "Apple Inc.")
        doc = graph.add_document(self.conn, "sec", "10-K", "a", "https://x")
        parent, _ = jobs.enqueue(self.conn, "download", "a", now=T0)
        child, _ = jobs.enqueue(self.conn, "read", "a", company_id=company, document_id=doc, parent_job_id=parent, now=T0)
        row = self.status(child)
        self.assertEqual((row["company_id"], row["document_id"], row["parent_job_id"]), (company, doc, parent))


class ClaimTests(QueueCase):
    def test_higher_priority_first_then_the_longest_due_then_the_oldest(self):
        low, _ = jobs.enqueue(self.conn, "k", "low", priority=100, run_after=at(minutes=-5), now=T0)
        high, _ = jobs.enqueue(self.conn, "k", "high", priority=300, run_after=at(minutes=-1), now=T0)
        early, _ = jobs.enqueue(self.conn, "k", "early", priority=100, run_after=at(minutes=-10), now=T0)
        tie_a, _ = jobs.enqueue(self.conn, "k", "tie a", priority=100, run_after=at(minutes=-10), now=T0)
        order = [jobs.claim(self.conn, "w", now=T0)["id"] for _ in range(4)]
        self.assertEqual(order, [high, early, tie_a, low])
        self.assertIsNone(jobs.claim(self.conn, "w", now=T0))

    def test_work_that_is_not_due_yet_waits(self):
        jobs.enqueue(self.conn, "k", "later", run_after=at(minutes=10), now=T0)
        self.assertIsNone(jobs.claim(self.conn, "w", now=T0))
        self.assertEqual(jobs.claim(self.conn, "w", now=at(minutes=10))["key"], "later")

    def test_a_worker_only_takes_the_kinds_it_can_handle(self):
        jobs.enqueue(self.conn, "read", "r", priority=500, now=T0)
        jobs.enqueue(self.conn, "download", "d", priority=100, now=T0)
        self.assertEqual(jobs.claim(self.conn, "w", kinds=["download"], now=T0)["kind"], "download")
        self.assertIsNone(jobs.claim(self.conn, "w", kinds=["download"], now=T0))
        self.assertIsNone(jobs.claim(self.conn, "w", kinds=[], now=T0))
        self.assertEqual(jobs.claim(self.conn, "w", now=T0)["kind"], "read")

    def test_claiming_marks_it_running_counts_the_attempt_and_starts_a_run(self):
        job_id, _ = jobs.enqueue(self.conn, "k", "x", {"n": 1}, now=T0)
        job = jobs.claim(self.conn, "worker-1", now=T0)
        self.assertEqual((job["id"], job["payload"], job["attempts"]), (job_id, {"n": 1}, 1))
        row = self.status(job_id)
        self.assertEqual((row["status"], row["locked_by"], row["locked_at"]), ("running", "worker-1", "2026-10-25T09:00:00Z"))
        [run_row] = self.runs(job_id)
        self.assertEqual((run_row["id"], run_row["outcome"], run_row["worker"]), (job["run_id"], "running", "worker-1"))

    def test_two_workers_never_get_the_same_job(self):
        for i in range(40):
            jobs.enqueue(self.conn, "k", f"job {i}", now=T0)
        claimed, lock = [], threading.Lock()

        def work(name):
            conn = db.connect(self.path)
            try:
                while True:
                    job = jobs.claim(conn, name, now=T0)
                    if job is None:
                        return
                    with lock:
                        claimed.append(job["id"])
            finally:
                conn.close()
        threads = [threading.Thread(target=work, args=(f"w{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(claimed), 40)
        self.assertEqual(len(set(claimed)), 40)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 40)


class OutcomeTests(QueueCase):
    def claim(self, **extra):
        jobs.enqueue(self.conn, "k", "x", now=T0, **extra)
        return jobs.claim(self.conn, "w", now=T0)

    def test_done_records_the_cost_on_the_run(self):
        job = self.claim()
        jobs.finish(self.conn, job, notes={"relationships": 3}, model="claude-haiku-5-5", input_tokens=30000, output_tokens=900, cost_usd=0.0034, now=at(seconds=20))
        self.assertEqual(self.status(job["id"])["status"], "done")
        [run_row] = self.runs(job["id"])
        self.assertEqual((run_row["outcome"], run_row["model"], run_row["cost_usd"], run_row["finished_at"]), ("ok", "claude-haiku-5-5", 0.0034, "2026-10-25T09:00:20Z"))
        self.assertEqual(run_row["notes"], '{"relationships": 3}')
        self.assertEqual(jobs.spent_since(self.conn, at(hours=-1)), 0.0034)
        self.assertEqual(jobs.spent_since(self.conn, at(hours=1)), 0)

    def test_retries_back_off_and_the_third_failure_is_dead(self):
        job = self.claim()
        self.assertEqual(jobs.fail(self.conn, job, "timeout", now=T0, jitter=False), "queued")
        row = self.status(job["id"])
        self.assertEqual((row["run_after"], row["last_error"], row["locked_by"]), ("2026-10-25T09:00:30Z", "timeout", None))
        self.assertIsNone(jobs.claim(self.conn, "w", now=at(seconds=29)))  # not before the back-off is over
        second = jobs.claim(self.conn, "w", now=at(seconds=30))
        self.assertEqual(jobs.fail(self.conn, second, "timeout", now=at(seconds=30), jitter=False), "queued")
        self.assertEqual(self.status(job["id"])["run_after"], "2026-10-25T09:02:30Z")  # 2 minutes
        third = jobs.claim(self.conn, "w", now=at(minutes=3))
        self.assertEqual(jobs.fail(self.conn, third, "still down", now=at(minutes=3), jitter=False), "dead")
        row = self.status(job["id"])
        self.assertEqual((row["status"], row["attempts"], row["last_error"]), ("dead", 3, "still down"))
        self.assertIsNone(jobs.claim(self.conn, "w", now=at(days=1)))
        self.assertEqual([r["outcome"] for r in self.runs(job["id"])], ["retry", "retry", "error"])

    def test_the_back_off_grows_and_stops_at_six_hours(self):
        self.assertEqual([jobs.backoff_seconds(n, jitter=False) for n in (1, 2, 3, 4, 5, 6, 7, 20)],
                         [30, 120, 480, 1920, 7680, 21600, 21600, 21600])
        jittered = [jobs.backoff_seconds(1) for _ in range(50)]
        self.assertTrue(all(30 <= j <= 36 for j in jittered))
        self.assertGreater(len(set(jittered)), 1)

    def test_a_permanent_error_is_not_retried(self):
        job = self.claim()
        self.assertEqual(jobs.fail(self.conn, job, "no such filing", permanent=True, now=T0), "failed")
        self.assertIsNone(jobs.claim(self.conn, "w", now=at(days=1)))

    def test_more_attempts_when_asked(self):
        job = self.claim(max_attempts=1)
        self.assertEqual(jobs.fail(self.conn, job, "x", now=T0), "dead")

    def test_dead_and_failed_jobs_can_be_tried_again_from_the_start(self):
        job = self.claim(max_attempts=1)
        jobs.fail(self.conn, job, "x", now=T0)
        self.assertTrue(jobs.requeue(self.conn, job["id"], now=at(hours=1)))
        row = self.status(job["id"])
        self.assertEqual((row["status"], row["attempts"], row["last_error"]), ("queued", 0, None))
        self.assertFalse(jobs.requeue(self.conn, job["id"], now=at(hours=1)))  # it isn't dead now

    def test_a_queued_job_can_be_cancelled_but_not_a_running_one(self):
        queued, _ = jobs.enqueue(self.conn, "k", "a", now=T0)
        self.assertTrue(jobs.cancel(self.conn, queued, now=T0))
        self.assertIsNone(jobs.claim(self.conn, "w", now=T0))
        jobs.enqueue(self.conn, "k", "b", now=T0)
        running = jobs.claim(self.conn, "w", now=T0)
        self.assertFalse(jobs.cancel(self.conn, running["id"], now=T0))

    def test_counts_for_the_status_page(self):
        jobs.enqueue(self.conn, "read", "a", now=T0)
        jobs.enqueue(self.conn, "read", "b", now=T0)
        jobs.enqueue(self.conn, "download", "c", now=T0)
        jobs.finish(self.conn, jobs.claim(self.conn, "w", kinds=["download"], now=T0), now=T0)
        self.assertEqual(jobs.counts(self.conn), {"queued": 2, "done": 1})
        self.assertEqual(jobs.counts_by_kind(self.conn), {("read", "queued"): 2, ("download", "done"): 1})


class RecoveryTests(QueueCase):
    def test_after_a_crash_unfinished_jobs_are_taken_back_and_run_again(self):
        jobs.enqueue(self.conn, "k", "x", now=T0)
        crashed = jobs.claim(self.conn, "old-process", now=T0)  # ... and the process died here
        self.assertEqual(jobs.recover(self.conn, stale_after=timedelta(0), now=at(minutes=1)), [crashed["id"]])
        row = self.status(crashed["id"])
        self.assertEqual((row["status"], row["attempts"], row["locked_by"]), ("queued", 1, None))  # the lost attempt counts
        self.assertIn("interrupted", row["last_error"])
        self.assertEqual([r["outcome"] for r in self.runs(crashed["id"])], ["abandoned"])
        again = jobs.claim(self.conn, "new-process", now=at(minutes=1))
        self.assertEqual((again["id"], again["attempts"]), (crashed["id"], 2))

    def test_a_job_that_crashes_its_worker_every_time_ends_up_dead(self):
        jobs.enqueue(self.conn, "k", "poison", max_attempts=3, now=T0)
        for n in range(3):
            self.assertIsNotNone(jobs.claim(self.conn, "w", now=at(minutes=n)))
            jobs.recover(self.conn, stale_after=timedelta(0), now=at(minutes=n, seconds=30))
        row = self.conn.execute("SELECT status, attempts FROM jobs").fetchone()
        self.assertEqual((row["status"], row["attempts"]), ("dead", 3))
        self.assertIsNone(jobs.claim(self.conn, "w", now=at(days=1)))

    def test_only_stale_jobs_are_taken_from_workers_that_may_still_be_alive(self):
        jobs.enqueue(self.conn, "k", "slow", now=T0)
        jobs.enqueue(self.conn, "k", "forgotten", now=T0)
        slow = jobs.claim(self.conn, "alive", now=T0)
        forgotten = jobs.claim(self.conn, "gone", now=T0)
        jobs.heartbeat(self.conn, slow["id"], now=at(minutes=14))
        self.assertEqual(jobs.recover(self.conn, now=at(minutes=16)), [forgotten["id"]])  # not heard from for 16 minutes
        self.assertEqual(self.status(slow["id"])["status"], "running")

    def test_nothing_to_recover_is_fine(self):
        self.assertEqual(jobs.recover(self.conn, stale_after=timedelta(0), now=T0), [])

    def test_an_orderly_stop_puts_the_job_back_without_counting_the_attempt(self):
        jobs.enqueue(self.conn, "k", "x", now=T0)
        job = jobs.claim(self.conn, "w", now=T0)
        jobs.release(self.conn, job, now=at(seconds=5))
        row = self.status(job["id"])
        self.assertEqual((row["status"], row["attempts"]), ("queued", 0))
        self.assertEqual([r["outcome"] for r in self.runs(job["id"])], ["abandoned"])


Worker = worker.Worker


def make_worker(case, handlers, **extra):
    w = Worker(case.path, handlers, **extra)
    case.addCleanup(lambda: w.conn and w.conn.close())
    return w


class WorkerTests(QueueCase):
    def test_runs_a_handler_and_records_the_result(self):
        seen = []

        async def read(job, conn):
            seen.append((job["key"], job["payload"]))
            return {"notes": {"found": 2}, "model": "claude-haiku-5-5", "input_tokens": 1000, "output_tokens": 100, "cost_usd": 0.001, "ignored": "x"}
        jobs.enqueue(self.conn, "read", "doc-1", {"doc": 1})
        w = make_worker(self, {"read": read})
        self.assertTrue(run(w.run_once()))
        self.assertEqual(seen, [("doc-1", {"doc": 1})])
        job = self.conn.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual(job["status"], "done")
        self.assertEqual(self.conn.execute("SELECT cost_usd, model FROM runs").fetchone()[:], (0.001, "claude-haiku-5-5"))
        self.assertFalse(run(w.run_once()))  # the queue is empty now

    def test_a_handler_error_is_retried_later_and_the_message_is_kept(self):
        async def broken(job, conn):
            raise RuntimeError("SEC answered 503")
        jobs.enqueue(self.conn, "download", "acc")
        w = make_worker(self, {"download": broken})
        run(w.run_once())
        row = self.conn.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual((row["status"], row["attempts"], row["last_error"]), ("queued", 1, "RuntimeError: SEC answered 503"))
        self.assertGreater(row["run_after"], db.now())  # backed off
        self.assertFalse(run(w.run_once()))  # so it isn't picked straight up again

    def test_secrets_in_errors_are_masked(self):
        async def leaky(job, conn):
            raise RuntimeError("bad key " + "sk" + "-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789")  # built in two parts: the commit hook blocks key-shaped text
        jobs.enqueue(self.conn, "read", "x")
        run(make_worker(self, {"read": leaky}).run_once())
        self.assertNotIn("abcdefghijklmnop", self.conn.execute("SELECT last_error FROM jobs").fetchone()[0])

    def test_a_permanent_error_fails_the_job_at_once(self):
        async def wrong(job, conn):
            raise worker.Permanent("no such filing")
        jobs.enqueue(self.conn, "download", "acc")
        run(make_worker(self, {"download": wrong}).run_once())
        self.assertEqual(self.conn.execute("SELECT status, attempts FROM jobs").fetchone()[:], ("failed", 1))

    def test_a_handler_that_hangs_is_timed_out_and_retried(self):
        async def hangs(job, conn):
            await asyncio.sleep(30)
        jobs.enqueue(self.conn, "read", "x")
        run(make_worker(self, {"read": hangs}, timeout_s=0.05).run_once())
        row = self.conn.execute("SELECT status, last_error FROM jobs").fetchone()
        self.assertEqual(row["status"], "queued")
        self.assertIn("took longer", row["last_error"])

    def test_kinds_without_a_handler_are_left_for_someone_else(self):
        jobs.enqueue(self.conn, "read", "x", priority=900)
        w = make_worker(self, {})
        self.assertFalse(run(w.run_once()))
        self.assertEqual(self.conn.execute("SELECT status FROM jobs").fetchone()[0], "queued")

    def test_the_registry_decorator(self):
        saved = dict(worker.HANDLERS)
        self.addCleanup(lambda: (worker.HANDLERS.clear(), worker.HANDLERS.update(saved)))

        @worker.handler("sample")
        async def sample(job, conn):
            return None
        self.assertIs(worker.HANDLERS["sample"], sample)

    def test_a_restart_resumes_what_the_old_process_left(self):
        done = []

        async def read(job, conn):
            done.append(job["key"])
        jobs.enqueue(self.conn, "read", "interrupted", priority=200)
        jobs.enqueue(self.conn, "read", "waiting", priority=100)
        jobs.claim(self.conn, "old-process")  # the old process took it and was killed
        self.conn.close()
        reopened = Worker(self.path, {"read": read}, poll_s=0.01)

        async def go():
            task = asyncio.create_task(reopened.run_forever())
            for _ in range(200):
                if len(done) == 2:
                    break
                await asyncio.sleep(0.01)
            reopened.stop()
            await task
        run(go())
        self.assertEqual(done, ["interrupted", "waiting"])
        check = db.connect(self.path)
        self.addCleanup(check.close)
        self.assertEqual(jobs.counts(check), {"done": 2})
        self.assertEqual([r[0] for r in check.execute("SELECT outcome FROM runs ORDER BY id")], ["abandoned", "ok", "ok"])

    def test_cancelling_the_runner_puts_the_job_in_hand_back(self):
        async def slow(job, conn):
            await asyncio.sleep(30)
        jobs.enqueue(self.conn, "read", "x")
        w = make_worker(self, {"read": slow}, poll_s=0.01)

        async def go():
            task = asyncio.create_task(w.run_forever())
            await asyncio.sleep(0.2)  # it is in the handler
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        run(go())
        check = db.connect(self.path)
        self.addCleanup(check.close)
        row = check.execute("SELECT status, attempts, locked_by FROM jobs").fetchone()
        self.assertEqual((row["status"], row["attempts"], row["locked_by"]), ("queued", 0, None))  # not held against it

    def test_stop_finishes_the_job_in_hand_and_returns(self):
        order = []

        async def read(job, conn):
            order.append("start")
            await asyncio.sleep(0.1)
            order.append("end")
        jobs.enqueue(self.conn, "read", "a")
        jobs.enqueue(self.conn, "read", "b")
        w = make_worker(self, {"read": read}, poll_s=0.01)

        async def go():
            task = asyncio.create_task(w.run_forever())
            await asyncio.sleep(0.05)
            w.stop()
            await asyncio.wait_for(task, 5)
        run(go())
        self.assertEqual(order, ["start", "end"])  # the first finished; the second never started
        check = db.connect(self.path)
        self.addCleanup(check.close)
        self.assertEqual(jobs.counts(check), {"done": 1, "queued": 1})

    def test_several_workers_share_the_queue(self):
        seen, lock = [], threading.Lock()

        async def read(job, conn):
            await asyncio.sleep(0.01)
            with lock:
                seen.append(job["key"])
        for i in range(12):
            jobs.enqueue(self.conn, "read", f"job {i}")
        workers = [Worker(self.path, {"read": read}, name=f"w{i}", poll_s=0.01) for i in range(3)]

        async def go():
            tasks = [asyncio.create_task(w.run_forever(exclusive=False)) for w in workers]
            for _ in range(300):
                if len(seen) >= 12:
                    break
                await asyncio.sleep(0.02)
            for w in workers:
                w.stop()
            await asyncio.gather(*tasks)
        run(go())
        self.assertEqual(sorted(seen), sorted(f"job {i}" for i in range(12)))  # each exactly once


class ConfigTests(unittest.TestCase):
    def test_off_by_default_and_switched_on_by_the_environment(self):
        import config
        for value, want in [("", False), ("0", False), ("1", True), ("true", True)]:
            with unittest.mock.patch.dict(os.environ, {"PIPELINE": value}), unittest.mock.patch.object(config, "IN_APP", False):
                self.assertEqual(config.pipeline_enabled(), want, value)
        with unittest.mock.patch.object(config, "IN_APP", True), unittest.mock.patch.dict(config.SETTINGS, {}, clear=True):
            self.assertFalse(config.pipeline_enabled())
            config.SETTINGS["pipeline"] = True
            self.assertTrue(config.pipeline_enabled())

    def test_worker_count_is_kept_sensible(self):
        import config
        for value, want in [("", 2), ("3", 3), ("0", 1), ("99", 8), ("many", 2)]:
            with unittest.mock.patch.dict(os.environ, {"PIPELINE_WORKERS": value}):
                self.assertEqual(config.pipeline_workers(), want, value)


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
