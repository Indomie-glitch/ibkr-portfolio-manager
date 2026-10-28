"""Out of Anthropic credits, or a key that isn't accepted (#345): the job goes back without costing an attempt, the
pipeline pauses with the reason, and resumes once a test call answers. The fake client never calls the API."""
import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import httpx2 as httpx

from supply_chain import account, control, db, jobs, status, worker
from tests.pipeline_isolation import isolate

T0 = datetime(2026, 10, 28, 9, 0, 0, tzinfo=timezone.utc)


def api_error(status_code, message, kind="invalid_request_error"):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": kind, "message": message}}
    response = httpx.Response(status_code, json=body, request=request)
    cls = {400: anthropic.BadRequestError, 401: anthropic.AuthenticationError, 403: anthropic.PermissionDeniedError,
           500: anthropic.InternalServerError}.get(status_code, anthropic.APIStatusError)
    return cls(message, response=response, body=body)


NO_CREDITS = "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."


class FakeClient:
    """messages.count_tokens answers or raises `error`."""
    def __init__(self, error=None):
        self.error, self.calls = error, 0
        self.messages = self

    async def count_tokens(self, **request):
        self.calls += 1
        if self.error:
            raise self.error
        return {"input_tokens": 5}


class AccountCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / "supply_chain.sqlite"
        self.conn = db.open_graph(self.path)
        self.addCleanup(self.conn.close)
        isolate(self, self.root)
        control.save_settings(enabled=True)


class ProblemTests(unittest.TestCase):
    def test_which_answers_are_account_problems(self):
        self.assertEqual(account.problem_of(api_error(400, NO_CREDITS)), "credits")
        self.assertEqual(account.problem_of(api_error(402, "Payment required", "billing_error")), "credits")
        self.assertEqual(account.problem_of(api_error(401, "invalid x-api-key", "authentication_error")), "api_key")
        self.assertEqual(account.problem_of(api_error(403, "not allowed", "permission_error")), "api_key")
        self.assertIsNone(account.problem_of(api_error(400, "max_tokens is too large")))
        self.assertIsNone(account.problem_of(api_error(500, "overloaded", "api_error")))
        self.assertIsNone(account.problem_of(RuntimeError("credit balance")))  # only the API's own answers count


class WorkerTests(AccountCase):
    def worker(self, handler):
        w = worker.Worker(self.path, {"read": handler})
        self.addCleanup(lambda: w.conn and w.conn.close())
        return w

    def test_out_of_credits_puts_the_job_back_and_pauses(self):
        async def read(job, conn):
            raise api_error(400, NO_CREDITS)
        jobs.enqueue(self.conn, "read", "doc-1")
        w = self.worker(read)
        self.assertTrue(asyncio.run(w.run_once()))
        job = self.conn.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual((job["status"], job["attempts"], job["last_error"]), ("queued", 0, "Anthropic credits used up"))
        self.assertLessEqual(job["run_after"], db.now())  # no back-off: it runs as soon as the account works
        self.assertFalse(control.should_run(self.conn))
        self.assertEqual(control.status_word(self.conn), "credits")
        self.assertFalse(asyncio.run(w.run_once()))  # nothing is claimed while the problem stands
        self.assertEqual(self.conn.execute("SELECT status FROM jobs").fetchone()[0], "queued")

    def test_a_refused_key_pauses_too(self):
        async def read(job, conn):
            raise api_error(401, "invalid x-api-key", "authentication_error")
        jobs.enqueue(self.conn, "read", "doc-1")
        asyncio.run(self.worker(read).run_once())
        self.assertEqual(control.status_word(self.conn), "api_key")
        self.assertEqual(self.conn.execute("SELECT attempts FROM jobs").fetchone()[0], 0)

    def test_other_errors_still_fail_and_retry(self):
        async def read(job, conn):
            raise api_error(500, "overloaded", "api_error")
        jobs.enqueue(self.conn, "read", "doc-1")
        asyncio.run(self.worker(read).run_once())
        self.assertEqual(self.conn.execute("SELECT attempts FROM jobs").fetchone()[0], 1)
        self.assertTrue(control.should_run(self.conn))

    def test_the_sheet_says_why(self):
        account.record(api_error(400, NO_CREDITS), now=T0)
        problem = status.overview(self.conn)["account_problem"]
        self.assertEqual(status.overview(self.conn)["status"], "credits")
        self.assertEqual((problem["message"], problem["since"]), ("Anthropic credits used up", "2026-10-28T09:00:00Z"))


class CheckTests(AccountCase):
    def test_it_resumes_once_the_test_call_answers(self):
        account.record(api_error(400, NO_CREDITS), now=T0)
        client = FakeClient()
        self.assertFalse(asyncio.run(account.check(client, now=T0 + timedelta(minutes=10))))  # not due yet
        self.assertEqual(client.calls, 0)
        self.assertTrue(asyncio.run(account.check(client, now=T0 + timedelta(minutes=30))))
        self.assertIsNone(account.current())
        self.assertTrue(control.should_run(self.conn))

    def test_still_out_of_credits_keeps_waiting_from_the_same_start(self):
        account.record(api_error(400, NO_CREDITS), now=T0)
        client = FakeClient(api_error(400, NO_CREDITS))
        self.assertFalse(asyncio.run(account.check(client, now=T0 + timedelta(minutes=31))))
        problem = account.current()
        self.assertEqual((problem["since"], problem["checked_at"]), ("2026-10-28T09:00:00Z", "2026-10-28T09:31:00Z"))
        self.assertFalse(asyncio.run(account.check(client, now=T0 + timedelta(minutes=40))))  # next check at 10:01
        self.assertEqual(client.calls, 1)

    def test_a_network_failure_is_not_taken_for_a_fix(self):
        account.record(api_error(400, NO_CREDITS), now=T0)
        client = FakeClient(api_error(500, "overloaded", "api_error"))
        self.assertFalse(asyncio.run(account.check(client, now=T0 + timedelta(hours=1))))
        self.assertEqual(account.current()["kind"], "credits")
