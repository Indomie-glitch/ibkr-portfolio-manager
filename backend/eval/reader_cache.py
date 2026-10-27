"""Saved Reader answers for the evaluation set, so a run can measure a change that doesn't touch the Reader.

The Reader alone varies a lot between runs at the same settings (31 to 42 of 89 found), so a single run can't show what a
Verifier, merge or confidence change did. CachingClient stands in for anthropic.AsyncAnthropic in the Reader: an answer is
kept under the hash of the whole request (model, effort, system prompt, schema and the user message, which holds the chunk
text), so any change to the prompt, the model, the effort or the chunk reads afresh. Several answers can be kept per
request, one per run of --runs N (answers {"0": ..., "1": ...}), so a three-run baseline can be scored again later without new calls.

Only the Reader is cached: the Verifier, merge and confidence always run.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import usage_store

CACHE = Path(__file__).resolve().parent / "reader_cache"


def request_key(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _stored(response):
    return {"stop_reason": response.stop_reason, "model": getattr(response, "model", None),
            "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
            "content": [{"type": b.type, "text": b.text} for b in response.content if b.type == "text"]}


def _response(stored, cached):
    # a cached answer costs nothing now: its tokens are reported as 0 (CachingClient.saved_usd keeps what it cost)
    tokens = (0, 0) if cached else (stored["usage"]["input_tokens"], stored["usage"]["output_tokens"])
    return SimpleNamespace(stop_reason=stored["stop_reason"], model=stored["model"],
                           usage=SimpleNamespace(input_tokens=tokens[0], output_tokens=tokens[1]),
                           content=[SimpleNamespace(type=b["type"], text=b["text"]) for b in stored["content"]])


class CachingClient:
    """client.messages.create for the Reader: answer number run_index from the cache, else a real call that is then
    saved there. fresh=True ignores what is saved and replaces it."""

    def __init__(self, client, run_index=0, fresh=False, folder=CACHE):
        self.client, self.run_index, self.fresh, self.folder = client, run_index, fresh, Path(folder)
        self.messages = self
        self.hits = self.misses = 0
        self.saved_usd = 0.0

    def _path(self, key):
        return self.folder / key[:2] / f"{key}.json"

    async def create(self, **request):
        path = self._path(request_key(request))
        entry = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"model": request.get("model"), "answers": {}}
        slot = str(self.run_index)
        if not self.fresh and slot in entry["answers"]:
            self.hits += 1
            stored = entry["answers"][slot]
            cost = usage_store.cost_usd(request["model"], stored["usage"]["input_tokens"], stored["usage"]["output_tokens"])
            self.saved_usd += cost or 0.0
            return _response(stored, cached=True)
        self.misses += 1
        response = await self.client.messages.create(**request)
        stored = _stored(response)
        if response.stop_reason in ("end_turn", "max_tokens", "refusal"):  # an answer the Reader can use; anything else isn't kept
            entry["answers"][slot] = stored
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
        return _response(stored, cached=False)
