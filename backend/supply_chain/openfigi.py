"""OpenFIGI client (#119): searches OpenFIGI (Bloomberg's open identifier service) for a company name.

Works without a key at a lower limit (25 searches a minute; with OPENFIGI_API_KEY 250), so requests are spaced out
and a 429 waits for Retry-After. The key is sent in a header and never logged.
"""
import asyncio
import json
import time
import urllib.error
import urllib.request

import config
from secrets_guard import mask_secrets

SEARCH_URL = "https://api.openfigi.com/v3/search"
INTERVAL_NO_KEY_S = 2.5
INTERVAL_KEY_S = 0.3
RETRY_WAITS_S = (10, 30, 60)
TIMEOUT_S = 30

_lock = asyncio.Lock()
_last = 0.0


class OpenFigiUnavailable(Exception):
    """OpenFIGI can't be reached or keeps refusing (rate limit, errors): try the name again later."""


def _post(body, headers):
    request = urllib.request.Request(SEARCH_URL, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers or {}), b""


async def search(name):
    """Equities OpenFIGI lists for a name: [{figi, name, ticker, exchCode, compositeFIGI, shareClassFIGI, securityType, securityType2}]."""
    global _last
    key = config.openfigi_api_key()
    headers = {"Content-Type": "application/json", **({"X-OPENFIGI-APIKEY": key} if key else {})}
    body = {"query": name, "marketSecDes": "Equity"}
    interval = INTERVAL_KEY_S if key else INTERVAL_NO_KEY_S
    for attempt in range(len(RETRY_WAITS_S) + 1):
        async with _lock:
            wait = interval - (time.monotonic() - _last)
            if wait > 0:
                await asyncio.sleep(wait)
            _last = time.monotonic()
        try:
            status, response_headers, content = await asyncio.to_thread(_post, body, headers)
            problem = None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            status, response_headers, content, problem = None, {}, b"", exc.__class__.__name__
        if status == 200:
            try:
                answer = json.loads(content)
            except ValueError as exc:
                raise OpenFigiUnavailable("OpenFIGI sent something that isn't JSON.") from exc
            return [row for row in answer.get("data", []) if row.get("marketSector") in (None, "Equity")]
        if status not in (None, 429, 500, 502, 503, 504):
            raise OpenFigiUnavailable(mask_secrets(f"OpenFIGI answered {status}."))
        if attempt == len(RETRY_WAITS_S):
            raise OpenFigiUnavailable(f"OpenFIGI didn't answer ({status or problem}).")
        retry_after = response_headers.get("Retry-After", "")
        await asyncio.sleep(min(float(retry_after), 120) if retry_after.isdigit() else RETRY_WAITS_S[attempt])
