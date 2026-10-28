"""Saved name resolver lookups for the evaluation set, shared between runs (#343).

Each eval run starts from an empty temporary database, so the resolver decided every name again and asked OpenFIGI each
time (with no key OpenFIGI allows a search every 2.5 s, which made a run take about 10 minutes). The decisions themselves
can't be copied between runs: a match points at a company id in that run's database. What the resolver asked OpenFIGI can,
and with the same answers (and the same index data and alias list) it reaches the same decisions, so CachingSearch stands
in for openfigi.search and keeps every answer in backend/eval/resolver_cache.json. OpenFIGI being down is never saved.
"""
import json
from pathlib import Path

CACHE = Path(__file__).resolve().parent / "resolver_cache.json"


class CachingSearch:
    """openfigi.search(name) from the file when saved, else the real search, saved afterwards."""

    def __init__(self, search, path=CACHE):
        self.search, self.path = search, Path(path)
        self.answers = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.hits = self.misses = 0

    async def __call__(self, name):
        if name in self.answers:
            self.hits += 1
            return self.answers[name]
        self.misses += 1
        rows = await self.search(name)  # OpenFigiUnavailable goes up to the resolver, unsaved
        self.answers[name] = rows
        self.path.write_text(json.dumps(self.answers, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        return rows
