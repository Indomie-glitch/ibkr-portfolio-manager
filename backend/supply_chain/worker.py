"""The worker runner (#116): takes jobs from the queue (jobs.py) and runs their handlers.

A handler is `async def handle(job, conn)` registered for a kind with @handler("scout"). It returns None or a
dict with any of notes, model, input_tokens, output_tokens, cost_usd (recorded on the run), and raises
Permanent for an error that retrying can't fix; any other exception means "try again later".

Surviving restarts: the queue lives in the database. When the runner starts it takes back every job a previous
process left running and carries on, and on an orderly stop (the app quitting) the job in hand goes back in the
queue without costing an attempt. A crash costs the interrupted attempt, so a job that crashes the process
every time ends up dead. Only one runner process should use a database; further worker coroutines inside it
are fine (each has its own connection and claims atomically).
"""
import asyncio
import os
import socket
from datetime import timedelta

import config
from secrets_guard import mask_secrets
from supply_chain import db, jobs

HANDLERS = {}
HANDLER_TIMEOUT_S = 15 * 60
HEARTBEAT_S = 60
POLL_S = 5


class Permanent(Exception):
    """The job can't succeed however often it is retried (the input is wrong): it is marked failed at once."""


def handler(kind):
    """Registers the function that does the work for a kind of job."""
    def register(func):
        HANDLERS[kind] = func
        return func
    return register


class Worker:
    def __init__(self, path=None, handlers=None, name=None, poll_s=POLL_S, timeout_s=HANDLER_TIMEOUT_S, heartbeat_s=HEARTBEAT_S):
        self.path = path
        self.handlers = HANDLERS if handlers is None else handlers
        self.name = name or f"{socket.gethostname()}-{os.getpid()}"
        self.poll_s, self.timeout_s, self.heartbeat_s = poll_s, timeout_s, heartbeat_s
        self.stopping = asyncio.Event()
        self.conn = None

    def connection(self):
        if self.conn is None:
            self.conn = db.open_graph(self.path)
        return self.conn

    def stop(self):
        """Finish the job in hand, then return from run_forever."""
        self.stopping.set()

    def start(self, exclusive=True):
        """Takes back what a previous process left running. exclusive: this is the only runner, so every running
        job is a leftover (the normal case at app start); otherwise only jobs not heard from for a while."""
        return jobs.recover(self.connection(), stale_after=timedelta(0) if exclusive else jobs.STALE_AFTER)

    async def run_once(self):
        """Claims and runs one job. Returns True if there was one (whatever its outcome), False if the queue had nothing for us."""
        conn = self.connection()
        job = jobs.claim(conn, self.name, kinds=list(self.handlers))
        if job is None:
            return False
        beat = asyncio.create_task(self._heartbeat(job["id"]))
        try:
            result = await asyncio.wait_for(self.handlers[job["kind"]](job, conn), self.timeout_s)
        except asyncio.CancelledError:
            jobs.release(conn, job)  # the app is quitting: the job goes back, and this isn't held against it
            raise
        except Permanent as exc:
            jobs.fail(conn, job, exc, permanent=True)
        except asyncio.TimeoutError:
            jobs.fail(conn, job, f"took longer than {self.timeout_s} seconds")
        except Exception as exc:
            print(f"Supply chain job {job['id']} ({job['kind']} {job['key']}) failed: {exc.__class__.__name__}: {mask_secrets(exc)}")
            jobs.fail(conn, job, f"{exc.__class__.__name__}: {mask_secrets(exc)}")
        else:
            jobs.finish(conn, job, **{k: v for k, v in (result or {}).items() if k in ("notes", "model", "input_tokens", "output_tokens", "cost_usd")})
        finally:
            beat.cancel()
        return True

    async def _heartbeat(self, job_id):
        conn = db.connect(self.path)
        try:
            while True:
                await asyncio.sleep(self.heartbeat_s)
                jobs.heartbeat(conn, job_id)
        finally:
            conn.close()

    async def run_forever(self, exclusive=True):
        """Recovers, then works through the queue until stop() (or the task is cancelled), sleeping when it is empty."""
        recovered = self.start(exclusive)
        if recovered:
            print(f"Supply chain: took back {len(recovered)} unfinished job(s)")
        try:
            while not self.stopping.is_set():
                if await self.run_once():
                    continue
                try:
                    await asyncio.wait_for(self.stopping.wait(), self.poll_s)
                except asyncio.TimeoutError:
                    pass
        finally:
            if self.conn is not None:
                self.conn.close()
                self.conn = None


async def keep_running(path=None, count=None):
    """Background task for the app's lifespan: runs the workers while config.pipeline_enabled() (off by default: the
    pipeline spends AI budget). Several workers run side by side when PIPELINE_WORKERS says so."""
    while not config.pipeline_enabled():
        await asyncio.sleep(60)  # noticed when it is switched on
    from supply_chain import scout, xbrl  # noqa: F401  registers the scout, download and xbrl handlers
    count = count or config.pipeline_workers()
    workers = [Worker(path, name=f"{socket.gethostname()}-{os.getpid()}-{i}") for i in range(count)]
    workers[0].start(exclusive=True)  # one process: whatever was running before is a leftover
    try:
        await asyncio.gather(scout.keep_scheduling(path), *(w.run_forever(exclusive=False) for w in workers))
    finally:
        for w in workers:
            w.stop()
