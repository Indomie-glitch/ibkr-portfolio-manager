"""The Anthropic account behind the pipeline (#345): out of credits, or a key that isn't accepted.

Such an answer isn't the job's fault and retrying it can't help, so the worker doesn't fail the job: it puts it back
without counting the attempt (jobs.release), records the problem here, and the pipeline pauses (control.should_run).
The sheet and the Settings line say why ("Anthropic credits used up"). The supervisor checks every CHECK_EVERY_S whether
the API answers again and then clears the problem, so the pipeline resumes by itself.

The check uses messages.count_tokens, which is free. It may answer even while the credit balance is still too low;
then the next real call records the problem again (still without costing the job an attempt), so a wrong "fixed" costs
one refused call every 30 minutes and nothing else.

The problem is kept in pipeline_settings.json (control.save_settings) so it survives a restart and the status
endpoint can show it.
"""
from datetime import datetime, timedelta, timezone

import anthropic

import config
from secrets_guard import mask_secrets

CHECK_EVERY_S = 30 * 60

MESSAGES = {
    "credits": "Anthropic credits used up",
    "api_key": "Anthropic API key not accepted",
}


def problem_of(exc):
    """"credits" for a credit balance or billing answer, "api_key" for an authentication or permission one, else None."""
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return "api_key"
    if isinstance(exc, anthropic.APIStatusError):
        body = getattr(exc, "body", None)
        error = body.get("error") if isinstance(body, dict) else None
        kind = error.get("type") if isinstance(error, dict) else None
        text = str(exc).lower()
        if exc.status_code == 402 or kind == "billing_error" or "credit balance" in text or "billing" in text:
            return "credits"
    return None


def _now(now=None):
    return now or datetime.now(timezone.utc)


def _iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def record(exc, now=None):
    """Saves the problem (keeping when it started) and returns it."""
    from supply_chain import control
    kind = problem_of(exc)
    current = control.load_settings()["account_problem"] or {}
    stamp = _iso(_now(now))
    problem = {"kind": kind, "message": MESSAGES[kind], "detail": mask_secrets(str(exc))[:300],
               "since": current.get("since") if current.get("kind") == kind else stamp, "checked_at": stamp}
    control.save_settings(account_problem=problem)
    return problem


def current():
    from supply_chain import control
    return control.load_settings()["account_problem"]


def due(problem, now=None, every_s=CHECK_EVERY_S):
    checked = datetime.strptime(problem["checked_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return _now(now) - checked >= timedelta(seconds=every_s)


async def test_call(client=None):
    """A free call that needs the key: count_tokens. Raises what the API raises."""
    client = client or anthropic.AsyncAnthropic(api_key=config.anthropic_api_key(), timeout=30)
    await client.messages.count_tokens(model=config.READER_MODEL, messages=[{"role": "user", "content": "ping"}])


async def check(client=None, now=None, every_s=CHECK_EVERY_S):
    """If there is a problem and its check is due, tries the API: clears the problem when it answers (True), else keeps
    it with a new checked_at. Returns True when the problem was cleared, False otherwise (also when nothing was due)."""
    from supply_chain import control
    problem = current()
    if not problem or not due(problem, now, every_s):
        return False
    try:
        await test_call(client)
    except Exception as exc:
        if problem_of(exc):
            record(exc, now)
        else:  # the network or the API is down: that's not the account; look again next time
            control.save_settings(account_problem={**problem, "checked_at": _iso(_now(now))})
        return False
    control.save_settings(account_problem={})
    print("Supply chain: the Anthropic API answers again; the pipeline resumes")
    return True
