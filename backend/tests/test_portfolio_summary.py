"""The portfolio summary with a fake Claude client: no API key, no network, no cost."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import portfolio_summary
import summary_store

IDS = ["D:portfolio", "D:allocation", "D:concentration", "D:missing", "H:1", "H:2"]
FACTS = {"as_of": "2026-10-17T10:30:00+11:00", "as_of_text": "17 Oct 2026, 10:30am AEDT", "base_currency": "AUD"}


def point(text, *sources):
    return {"text": text, "sources": list(sources)}


def section(*points, status="ok"):
    return {"status": status, "points": list(points)}


SUMMARY = {
    "portfolio_snapshot": section(point("The holdings are worth A$10,000.00.", "D:portfolio"),
                                  point("Cash is A$2,000.00.", "D:portfolio")),
    "allocation": section(point("Apple is 60.0% of the holdings.", "D:allocation", "H:2"),
                          point("US shares are 60.0%.", "D:allocation", "D:made_up")),
    "pnl_drivers": section(point("Apple lost the most.", "H:2"), point("CBA gained the most.", "H:1")),
    "concentration": section(point("You should rebalance away from Apple.", "D:concentration")),
    "upcoming_events": section(point("No events are listed.")),
    "income": section(point("No dividend data.", "D:missing"), status="unavailable"),
    "key_risks": section(point("Apple is 60.0% of the holdings.", "D:concentration"),
                         point("60.0% is in US dollars.", "D:allocation")),
    "changes_since_last": section(point("This is the first portfolio summary, because none was saved before.", "D:portfolio")),
}


class FakeStream:
    def __init__(self, text, stop_reason="end_turn"):
        self.text, self.stop_reason = text, stop_reason

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    async def text_stream(self):
        for i in range(0, len(self.text), 40):  # arrives in small chunks, like the real stream
            yield self.text[i:i + 40]

    async def get_final_message(self):
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=self.text)],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=500))


class FakeClient:
    def __init__(self, text, stop_reason="end_turn"):
        self.calls = []
        self.messages = SimpleNamespace(stream=self._stream)
        self.text, self.stop_reason = text, stop_reason

    def _stream(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self.text, self.stop_reason)


async def collect(client):
    return [event async for event in portfolio_summary.stream_sections(FACTS, IDS, client=client)]


class PortfolioSummaryTest(unittest.TestCase):
    def test_streams_every_section_in_order_with_checks(self):
        client = FakeClient(json.dumps(SUMMARY))
        events = asyncio.run(collect(client))
        names = [e[1] for e in events if e[0] == "section"]
        self.assertEqual(names, portfolio_summary.SECTIONS)
        kind, summary, warnings, usage = events[-1]
        self.assertEqual(kind, "final")
        self.assertEqual(usage["output_tokens"], 500)
        # The unknown id is removed; the uncited point and the advice are flagged
        self.assertEqual(summary["allocation"]["points"][1]["sources"], ["D:allocation"])
        self.assertTrue(summary["upcoming_events"]["points"][0]["uncited"])
        self.assertIn("advice", summary["concentration"]["points"][0]["flags"])
        # The stock summary's section 10 news checks don't apply here ("because" is fine)
        self.assertNotIn("flags", summary["changes_since_last"]["points"][0])
        self.assertTrue(any("removed unknown source ids ['D:made_up']" in w for w in warnings))

    def test_request_uses_portfolio_prompt_and_schema(self):
        client = FakeClient(json.dumps(SUMMARY))
        asyncio.run(collect(client))
        call = client.calls[0]
        self.assertIs(call["system"], portfolio_summary.SYSTEM_PROMPT)
        self.assertIn("<facts>", call["messages"][0]["content"])
        schema = call["output_config"]["format"]["schema"]
        self.assertEqual(schema["required"], portfolio_summary.SECTIONS)
        self.assertEqual(schema["$defs"]["point"]["properties"]["sources"]["items"]["enum"], IDS)

    def test_cut_off_summary_is_an_error(self):
        client = FakeClient(json.dumps(SUMMARY)[:200], stop_reason="max_tokens")
        with self.assertRaises(portfolio_summary.ai_summary.SummaryError) as caught:
            asyncio.run(collect(client))
        self.assertEqual(caught.exception.code, "incomplete")

    def test_saved_and_read_back(self):
        with tempfile.TemporaryDirectory() as folder:
            original = summary_store.DB_PATH
            summary_store.DB_PATH = Path(folder) / "summaries.sqlite"
            try:
                self.assertIsNone(summary_store.latest_portfolio())
                for i in range(summary_store.KEEP_PER_STOCK + 2):
                    summary_store.save_portfolio(f"2026-10-17T10:{i:02d}:00+11:00", "claude-haiku-4-5", FACTS, SUMMARY, [])
                latest = summary_store.latest_portfolio()
                self.assertEqual(latest["created_at"], f"2026-10-17T10:{summary_store.KEEP_PER_STOCK + 1:02d}:00+11:00")
                self.assertEqual(latest["summary"], SUMMARY)
                with summary_store._connect() as conn:
                    count = conn.execute("SELECT COUNT(*) FROM portfolio_summaries").fetchone()[0]
                self.assertEqual(count, summary_store.KEEP_PER_STOCK)
                history = summary_store.portfolio_history()
                self.assertEqual(len(history), summary_store.KEEP_PER_STOCK)
                self.assertEqual(history[0]["id"], latest["id"])
                self.assertEqual(summary_store.get_portfolio(history[-1]["id"])["facts"], FACTS)
                self.assertIsNone(summary_store.get_portfolio(9999))
            finally:
                summary_store.DB_PATH = original


if __name__ == "__main__":
    unittest.main()
