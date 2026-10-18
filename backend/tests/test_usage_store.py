"""Claude API usage and cost (#86)."""
import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import ai_summary
import usage_store

AEDT = timezone(timedelta(hours=11))


class UsageStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original = usage_store.DB_PATH
        usage_store.DB_PATH = Path(self.folder.name) / "usage.sqlite"

    def tearDown(self):
        usage_store.DB_PATH = self.original
        self.folder.cleanup()

    def test_prices(self):
        self.assertAlmostEqual(usage_store.cost_usd("claude-haiku-4-5", 10_000, 2_000), 0.02)
        self.assertAlmostEqual(usage_store.cost_usd("claude-sonnet-5-5", 10_000, 2_000), 0.04)
        self.assertAlmostEqual(usage_store.cost_usd("claude-haiku-5-5", 10_000, 2_000), 0.002)
        # Claude Haiku 5.5's higher rate for prompts over 100K tokens
        self.assertAlmostEqual(usage_store.cost_usd("claude-haiku-5-5", 200_000, 2_000), 0.105)
        self.assertIsNone(usage_store.cost_usd("some-future-model", 1, 1))

    def test_monthly_totals_per_feature(self):
        oct_ = datetime(2026, 10, 18, 9, tzinfo=AEDT)
        usage_store.record("stock_summary", "claude-haiku-4-5", {"input_tokens": 12_000, "output_tokens": 3_000}, 1, now=oct_)
        usage_store.record("stock_summary", "claude-haiku-4-5", {"input_tokens": 12_000, "output_tokens": 6_000}, 1,
                           outcome="incomplete", now=oct_)
        usage_store.record("portfolio_summary", "claude-sonnet-5-5", {"input_tokens": 20_000, "output_tokens": 4_000}, now=oct_)
        usage_store.record("news_sentiment", "some-future-model", {"input_tokens": 900, "output_tokens": 100}, 2, now=oct_)
        # Another month: not counted; 1 Nov 00:30 in Sydney is still 31 Oct in UTC, and counts as November
        usage_store.record("stock_summary", "claude-haiku-4-5", {"input_tokens": 1, "output_tokens": 1}, 1,
                           now=datetime(2026, 11, 1, 0, 30, tzinfo=AEDT))

        month = usage_store.monthly("2026-10")
        self.assertEqual(month["calls"], 4)
        self.assertEqual(month["input_tokens"], 44_900)
        self.assertEqual(month["output_tokens"], 13_100)
        self.assertAlmostEqual(month["cost_usd"], 0.027 + 0.042 + 0.08)
        self.assertEqual(month["unpriced_calls"], 1)
        self.assertEqual(month["by_feature"]["stock_summary"]["calls"], 2)
        self.assertEqual(month["by_feature"]["news_sentiment"]["cost_usd"], 0)
        self.assertEqual(usage_store.monthly("2026-11")["calls"], 1)
        # A month with nothing yet: zeros for every feature
        empty = usage_store.monthly("2026-09")
        self.assertEqual((empty["calls"], empty["cost_usd"]), (0, 0))
        self.assertEqual(set(empty["by_feature"]), set(usage_store.FEATURES))

    def test_a_broken_record_never_raises(self):
        usage_store.record("stock_summary", "claude-haiku-4-5", {"input_tokens": None})  # prints, doesn't raise
        self.assertEqual(usage_store.monthly()["calls"], 0)


class FakeStream:
    def __init__(self, stop_reason):
        self.final = SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=json.dumps({}))],
                                     usage=SimpleNamespace(input_tokens=11_000, output_tokens=32_000))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    async def text_stream(self):
        yield "{"

    async def get_final_message(self):
        return self.final


class CutOffSummaryTests(unittest.TestCase):
    def test_a_cut_off_summary_reports_the_tokens_it_used(self):
        client = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kwargs: FakeStream("max_tokens")))

        async def run():
            async for _ in ai_summary.stream_sections({"company": {"name": "A", "symbol": "A", "exchange": "ASX"},
                                                       "as_of_text": "now"}, ["D:key_stats"], client=client):
                pass

        with self.assertRaises(ai_summary.SummaryError) as caught:
            asyncio.run(run())
        self.assertEqual(caught.exception.code, "incomplete")
        self.assertEqual(caught.exception.usage, {"input_tokens": 11_000, "output_tokens": 32_000})


if __name__ == "__main__":
    unittest.main()
