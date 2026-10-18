"""News sentiment (#170) with a fake Claude client: no API calls."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import news_sentiment
import usage_store


def headline(n, title):
    return {"title": title, "publisher": "Reuters", "url": f"https://example.com/{n}",
            "published": "2026-10-17T01:00:00+00:00"}


ITEMS = [
    headline(1, "Acme beats profit forecasts and lifts dividend"),
    headline(2, "Regulator sues Acme over misleading fees"),
    headline(3, "Acme to present at investor conference"),
]


class FakeMessages:
    def __init__(self, answer, stop_reason="end_turn", error=None):
        self.answer = answer
        self.stop_reason = stop_reason
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=json.dumps(self.answer))],
            usage=SimpleNamespace(input_tokens=500, output_tokens=120),
        )


class FakeClient:
    def __init__(self, answer, **kwargs):
        self.messages = FakeMessages(answer, **kwargs)


ANSWER = {"items": [
    {"id": "N1", "direction": "positive", "strength": 2, "reason": "Profit beat and a higher dividend."},
    {"id": "N2", "direction": "negative", "strength": 3, "reason": "Possible fines and refunds."},
    {"id": "N3", "direction": "neutral", "strength": 1, "reason": "Routine event."},
]}


def run(coro):
    return asyncio.run(coro)


class NewsSentimentTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.original = news_sentiment.DB_PATH
        news_sentiment.DB_PATH = Path(self.folder.name) / "news_sentiment.sqlite"
        # Never log test calls in the real usage file
        self.original_usage = usage_store.DB_PATH
        usage_store.DB_PATH = Path(self.folder.name) / "usage.sqlite"
        news_sentiment._failed_at.clear()

    def tearDown(self):
        news_sentiment.DB_PATH = self.original
        usage_store.DB_PATH = self.original_usage
        self.folder.cleanup()

    def test_positive_negative_and_neutral(self):
        client = FakeClient(ANSWER)
        items = run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", ITEMS, client=client))
        self.assertEqual(items[0]["sentiment"], {"direction": "positive", "strength": 2,
                                                 "reason": "Profit beat and a higher dividend."})
        self.assertEqual(items[1]["sentiment"]["direction"], "negative")
        self.assertEqual(items[1]["sentiment"]["strength"], 3)
        # Neutral items have no strength (no arrows)
        self.assertEqual(items[2]["sentiment"], {"direction": "neutral", "strength": None, "reason": "Routine event."})
        # The originals are untouched and everything else is kept
        self.assertNotIn("sentiment", ITEMS[0])
        self.assertEqual(items[0]["title"], ITEMS[0]["title"])

    def test_one_batched_call_judged_for_the_company(self):
        client = FakeClient(ANSWER)
        run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", ITEMS, client=client))
        self.assertEqual(len(client.messages.calls), 1)
        call = client.messages.calls[0]
        message = call["messages"][0]["content"]
        self.assertIn("Company: Acme Corp (ticker ACME)", message)
        self.assertIn("N2. Regulator sues Acme over misleading fees (Reuters, 2026-10-17)", message)
        schema = call["output_config"]["format"]["schema"]
        self.assertEqual(schema["properties"]["items"]["items"]["properties"]["id"]["enum"], ["N1", "N2", "N3"])

    def test_each_article_is_judged_once(self):
        run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", ITEMS, client=FakeClient(ANSWER)))
        newer = [headline(4, "Acme wins large defence contract")] + ITEMS
        client = FakeClient({"items": [{"id": "N1", "direction": "positive", "strength": 2, "reason": "New contract."}]})
        items = run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", newer, client=client))
        # Only the new headline is sent, and the saved answers are reused
        self.assertIn("N1. Acme wins large defence contract", client.messages.calls[0]["messages"][0]["content"])
        self.assertNotIn("Regulator", client.messages.calls[0]["messages"][0]["content"])
        self.assertEqual([i["sentiment"]["direction"] for i in items], ["positive", "positive", "negative", "neutral"])
        # Nothing new: no call at all
        client = FakeClient(ANSWER)
        run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", newer, client=client))
        self.assertEqual(client.messages.calls, [])

    def test_same_article_is_judged_separately_per_stock(self):
        run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", ITEMS, client=FakeClient(ANSWER)))
        client = FakeClient(ANSWER)
        run(news_sentiment.with_sentiment(2, "Rival Inc", "RVL", ITEMS, client=client))
        self.assertEqual(len(client.messages.calls), 1)

    def test_no_api_key_returns_news_without_sentiment(self):
        with mock.patch.object(news_sentiment.config, "anthropic_api_key", return_value=None):
            items = run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", ITEMS))
        self.assertEqual([i["sentiment"] for i in items], [None, None, None])
        self.assertEqual([i["title"] for i in items], [i["title"] for i in ITEMS])

    def test_failed_call_returns_news_and_waits_before_retrying(self):
        client = FakeClient(ANSWER, error=RuntimeError("boom"))
        items = run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", ITEMS, client=client))
        self.assertEqual([i["sentiment"] for i in items], [None, None, None])
        again = FakeClient(ANSWER)
        run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", ITEMS, client=again))
        self.assertEqual(again.messages.calls, [])

    def test_cut_off_answer_is_a_failure(self):
        client = FakeClient(ANSWER, stop_reason="max_tokens")
        items = run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", ITEMS, client=client))
        self.assertEqual([i["sentiment"] for i in items], [None, None, None])

    def test_unknown_ids_bad_values_and_repeats_are_dropped(self):
        answer = {"items": [
            {"id": "N9", "direction": "positive", "strength": 1, "reason": "x"},
            {"id": "N1", "direction": "great", "strength": 1, "reason": "x"},
            {"id": "N2", "direction": "negative", "strength": 1, "reason": "first"},
            {"id": "N2", "direction": "positive", "strength": 3, "reason": "second"},
        ]}
        items = run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", ITEMS, client=FakeClient(answer)))
        self.assertEqual([i["sentiment"] and i["sentiment"]["reason"] for i in items], [None, "first", None])

    def test_usage_is_logged_per_call(self):
        run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", ITEMS, client=FakeClient(ANSWER)))
        month = usage_store.monthly()
        self.assertEqual(month["by_feature"]["news_sentiment"],
                         {"calls": 1, "input_tokens": 500, "output_tokens": 120, "cost_usd": 0.0011})

    def test_a_cut_off_answer_is_still_logged(self):
        run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", ITEMS, client=FakeClient(ANSWER, stop_reason="max_tokens")))
        self.assertEqual(usage_store.monthly()["calls"], 1)

    def test_old_usage_rows_move_to_the_usage_store(self):
        import sqlite3
        conn = sqlite3.connect(news_sentiment.DB_PATH)
        conn.execute("CREATE TABLE ai_usage (id INTEGER PRIMARY KEY, created_at TEXT, feature TEXT, model TEXT, "
                     "con_id INTEGER, items INTEGER, input_tokens INTEGER, output_tokens INTEGER)")
        conn.execute("INSERT INTO ai_usage VALUES (1, '2026-10-18T10:00:00+11:00', 'news_sentiment', "
                     "'claude-haiku-4-5', 7, 3, 1000, 200)")
        conn.commit()
        conn.close()
        news_sentiment.saved_sentiments(7, ["x"])  # any use of the file moves them
        news_sentiment.saved_sentiments(7, ["x"])  # and only once
        self.assertEqual(usage_store.monthly("2026-10")["by_feature"]["news_sentiment"]["calls"], 1)
        self.assertAlmostEqual(usage_store.monthly("2026-10")["cost_usd"], 0.002)

    def test_no_news_makes_no_call(self):
        client = FakeClient(ANSWER)
        self.assertEqual(run(news_sentiment.with_sentiment(1, "Acme Corp", "ACME", [], client=client)), [])
        self.assertEqual(client.messages.calls, [])


if __name__ == "__main__":
    unittest.main()
