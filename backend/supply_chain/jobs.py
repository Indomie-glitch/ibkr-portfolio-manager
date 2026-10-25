"""The job queue (#116), on the jobs and runs tables from #115.

A job is one piece of pipeline work: a kind ("scout", "download", "read" ...) and a key (what it is about:
an accession number, a company id). At most one open (queued or running) job exists per kind and key, so
queueing the same work twice is harmless. Every attempt writes a runs row, with its outcome, tokens and cost.

Life of a job:
  queued -> running (claimed by a worker, attempts + 1) -> done
                                                        -> queued again, later (an error; retried after a back-off)
                                                        -> dead   (out of attempts)
                                                        -> failed (a permanent error: no point retrying)
  running -> queued   when the worker stopped or crashed (recover): the interrupted attempt still counts,
                      so a job that kills its worker every time ends up dead instead of looping forever
Higher priority runs first; among equals the one due longest ago. Claiming is atomic (BEGIN IMMEDIATE), so
two workers never get the same job.
"""
import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone

from supply_chain.db import transaction

BACKOFF_BASE_S = 30
BACKOFF_FACTOR = 4
BACKOFF_MAX_S = 6 * 3600
STALE_AFTER = timedelta(minutes=15)  # a running job not heard from for this long belongs to a dead worker


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now(now=None):
    return now or datetime.now(timezone.utc)


def backoff_seconds(attempts, jitter=True):
    """How long to wait before the next attempt, after `attempts` attempts: 30 s, 2 min, 8 min, 32 min ... up to 6 hours,
    with up to 20% added at random so a batch of failures doesn't all come back at the same moment."""
    wait = min(BACKOFF_MAX_S, BACKOFF_BASE_S * BACKOFF_FACTOR ** max(attempts - 1, 0))
    return wait * (1 + random.random() * 0.2) if jitter else wait


def _job(row):
    job = dict(row)
    job["payload"] = json.loads(job["payload"] or "{}")
    return job


def enqueue(conn, kind, key, payload=None, priority=100, run_after=None, company_id=None, document_id=None, parent_job_id=None,
            max_attempts=3, now=None):
    """Queues work. Returns (job id, created). If the same kind and key is already open, nothing is added; the
    existing job is returned (created False) and takes the higher of the two priorities, so asking for something
    urgently moves it up the queue."""
    moment = _now(now)
    stamp = _iso(moment)
    try:
        job_id = conn.execute(
            """INSERT INTO jobs (kind, key, payload, priority, max_attempts, run_after, company_id, document_id, parent_job_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (kind, key, json.dumps(payload or {}), priority, max_attempts, _iso(run_after or moment), company_id, document_id,
             parent_job_id, stamp, stamp)).lastrowid
        return job_id, True
    except sqlite3.IntegrityError:
        row = conn.execute("SELECT id FROM jobs WHERE kind = ? AND key = ? AND status IN ('queued', 'running')", (kind, key)).fetchone()
        if row is None:
            raise  # some other constraint (an unknown company id ...): not a duplicate
        conn.execute("UPDATE jobs SET priority = MAX(priority, ?), updated_at = ? WHERE id = ?", (priority, stamp, row["id"]))
        return row["id"], False


def claim(conn, worker, kinds=None, now=None):
    """The next job to run, marked running for this worker, with a new runs row; None when nothing is due.
    Returns the job (payload decoded) plus run_id. kinds limits it to the kinds this worker can handle."""
    moment = _now(now)
    stamp = _iso(moment)
    where, params = "status = 'queued' AND run_after <= ?", [stamp]
    if kinds is not None:
        if not kinds:
            return None
        where += f" AND kind IN ({', '.join('?' * len(kinds))})"
        params += list(kinds)
    with transaction(conn):
        row = conn.execute(f"SELECT * FROM jobs WHERE {where} ORDER BY priority DESC, run_after, id LIMIT 1", params).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE jobs SET status = 'running', attempts = attempts + 1, locked_by = ?, locked_at = ?, updated_at = ? WHERE id = ?",
                     (worker, stamp, stamp, row["id"]))
        run_id = conn.execute("INSERT INTO runs (job_id, started_at, worker) VALUES (?, ?, ?)", (row["id"], stamp, worker)).lastrowid
    job = _job(conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone())
    job["run_id"] = run_id
    return job


def heartbeat(conn, job_id, now=None):
    """Says the worker is still on this job, so it isn't taken for a dead worker's."""
    conn.execute("UPDATE jobs SET locked_at = ? WHERE id = ? AND status = 'running'", (_iso(_now(now)), job_id))


def finish(conn, job, notes=None, model=None, input_tokens=None, output_tokens=None, cost_usd=None, now=None):
    """The job is done; its run records the outcome, tokens and cost."""
    stamp = _iso(_now(now))
    with transaction(conn):
        conn.execute("UPDATE jobs SET status = 'done', locked_by = NULL, locked_at = NULL, last_error = NULL, finished_at = ?, updated_at = ? WHERE id = ?",
                     (stamp, stamp, job["id"]))
        conn.execute("""UPDATE runs SET outcome = 'ok', finished_at = ?, model = ?, input_tokens = ?, output_tokens = ?, cost_usd = ?, notes = ? WHERE id = ?""",
                     (stamp, model, input_tokens, output_tokens, cost_usd, json.dumps(notes) if notes is not None else None, job["run_id"]))


def fail(conn, job, error, permanent=False, now=None, jitter=True):
    """The attempt failed. A temporary error queues the job again after a back-off, until it is out of attempts (dead);
    a permanent error (the input itself is wrong) marks it failed at once. Returns the job's new status."""
    moment = _now(now)
    stamp = _iso(moment)
    current = conn.execute("SELECT attempts, max_attempts FROM jobs WHERE id = ?", (job["id"],)).fetchone()
    message = str(error)[:2000]
    if permanent:
        status, outcome, run_after = "failed", "error", None
    elif current["attempts"] >= current["max_attempts"]:
        status, outcome, run_after = "dead", "error", None
    else:
        status, outcome = "queued", "retry"
        run_after = _iso(moment + timedelta(seconds=backoff_seconds(current["attempts"], jitter)))
    with transaction(conn):
        conn.execute("""UPDATE jobs SET status = ?, last_error = ?, locked_by = NULL, locked_at = NULL, updated_at = ?,
                        run_after = COALESCE(?, run_after), finished_at = ? WHERE id = ?""",
                     (status, message, stamp, run_after, stamp if status != "queued" else None, job["id"]))
        conn.execute("UPDATE runs SET outcome = ?, finished_at = ?, error = ? WHERE id = ?", (outcome, stamp, message, job["run_id"]))
    return status


def release(conn, job, reason="stopped before it finished", count_attempt=False, now=None):
    """Puts a running job back in the queue because its worker is stopping (an orderly shutdown), without
    holding the interruption against it unless count_attempt."""
    stamp = _iso(_now(now))
    with transaction(conn):
        conn.execute("""UPDATE jobs SET status = 'queued', attempts = attempts - ?, locked_by = NULL, locked_at = NULL, last_error = ?, updated_at = ?
                        WHERE id = ? AND status = 'running'""", (0 if count_attempt else 1, reason, stamp, job["id"]))
        conn.execute("UPDATE runs SET outcome = 'abandoned', finished_at = ?, error = ? WHERE id = ?", (stamp, reason, job["run_id"]))


def recover(conn, stale_after=STALE_AFTER, now=None):
    """Takes back running jobs whose worker is gone: those not heard from for stale_after (pass timedelta(0) at the start
    of the only worker, when every running job is a leftover from before the restart). The interrupted attempt counts, so
    a job that kills its worker every time runs out of attempts and goes dead instead of looping. Returns the ids."""
    moment = _now(now)
    stamp = _iso(moment)
    cutoff = _iso(moment - stale_after)
    recovered = []
    with transaction(conn):
        rows = conn.execute("SELECT id, attempts, max_attempts FROM jobs WHERE status = 'running' AND locked_at <= ?", (cutoff,)).fetchall()
        for row in rows:
            dead = row["attempts"] >= row["max_attempts"]
            conn.execute("""UPDATE jobs SET status = ?, locked_by = NULL, locked_at = NULL, last_error = 'interrupted: the worker stopped or crashed',
                            run_after = ?, updated_at = ?, finished_at = ? WHERE id = ?""",
                         ("dead" if dead else "queued", stamp, stamp, stamp if dead else None, row["id"]))
            conn.execute("""UPDATE runs SET outcome = 'abandoned', finished_at = ?, error = 'interrupted' WHERE job_id = ? AND outcome = 'running'""",
                         (stamp, row["id"]))
            recovered.append(row["id"])
    return recovered


def requeue(conn, job_id, now=None):
    """Gives a dead or failed job another go: its attempts start again."""
    stamp = _iso(_now(now))
    changed = conn.execute("""UPDATE jobs SET status = 'queued', attempts = 0, run_after = ?, last_error = NULL, finished_at = NULL, updated_at = ?
                              WHERE id = ? AND status IN ('dead', 'failed', 'cancelled')""", (stamp, stamp, job_id)).rowcount
    return bool(changed)


def cancel(conn, job_id, now=None):
    """Stops a queued job from running. A running job can't be cancelled (it finishes or fails)."""
    stamp = _iso(_now(now))
    return bool(conn.execute("UPDATE jobs SET status = 'cancelled', finished_at = ?, updated_at = ? WHERE id = ? AND status = 'queued'",
                             (stamp, stamp, job_id)).rowcount)


def counts(conn):
    """{status: how many}, for the pipeline status page (#122)."""
    return {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")}


def counts_by_kind(conn):
    return {(r["kind"], r["status"]): r["n"] for r in conn.execute("SELECT kind, status, COUNT(*) AS n FROM jobs GROUP BY kind, status")}


def spent_since(conn, since):
    """US$ spent by runs that started at or after `since` (a datetime): the orchestrator's daily budget (#126)."""
    return conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM runs WHERE started_at >= ?", (_iso(since),)).fetchone()[0]
