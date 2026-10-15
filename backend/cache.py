"""A small in-memory cache for slow or rate-limited lookups (Yahoo Finance).

Each entry expires after its own time-to-live. Failures are remembered briefly too,
so an outage isn't retried on every request. Everything is lost on restart, which is fine.
"""
import asyncio
import time

FAILURE_TTL = 60  # seconds to remember that a lookup failed

_entries = {}  # key -> (expires_at, value, error)
_locks = {}  # key -> asyncio.Lock


async def cached(key, ttl, fetch):
    """Return the cached value for key, or await fetch() and keep the result for ttl seconds.

    If fetch() raised recently, raise the same error again instead of calling it.
    """
    entry = _entries.get(key)
    if entry and time.monotonic() < entry[0]:
        return _result(entry)

    # One lock per key: if two requests miss at the same moment, only one calls fetch()
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        entry = _entries.get(key)
        if entry and time.monotonic() < entry[0]:
            return _result(entry)
        try:
            value = await fetch()
        except Exception as exc:
            _entries[key] = (time.monotonic() + FAILURE_TTL, None, exc)
            raise
        _entries[key] = (time.monotonic() + ttl, value, None)
        return value


def _result(entry):
    _, value, error = entry
    if error is not None:
        raise error
    return value
