"""AI summary of a stock the investor doesn't own (#95): same briefing without your_position."""
import asyncio
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PORTFOLIO_DATA_DIR", tempfile.mkdtemp())
import ai_summary  # noqa: E402
import summary_facts  # noqa: E402
import summary_store  # noqa: E402
from routers import summaries  # noqa: E402

NOW = datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)
CONTRACT = SimpleNamespace(conId=4815747, symbol="NVDA", primaryExchange="NASDAQ", exchange="SMART", currency="USD", secType="STK")


async def unavailable():
    raise RuntimeError("offline")


def inputs(position):
    bars = [SimpleNamespace(date=date(2026, 7, 1) + timedelta(days=i), close=180 + i * 0.1) for i in range(60)]
    return {
        "position": position, "quote": {"last": 188.4, "prev_close": 186.3}, "bars": bars,
        "base_currency": "AUD", "fx_rate": 1.52, "total_market_value_base": 50000, "is_asx": False,
        "index_symbol": "^GSPC", "lots": None,
    }


LOADERS = {name: unavailable for name in ("info", "financials", "dividends", "performance", "index_closes", "index_intraday", "news")}


class NotOwnedFactsTests(unittest.TestCase):
    def test_facts_have_no_position(self):
        position = summaries.not_owned_position(CONTRACT, "NVIDIA Corp", {"last": 188.4})
        facts = asyncio.run(summary_facts.build_facts(inputs(position), LOADERS, now=NOW))["facts"]
        self.assertNotIn("D:position", facts)
        self.assertNotIn("D:position", summary_facts.source_ids(facts))
        self.assertEqual(facts["company"], {"name": "NVIDIA Corp", "symbol": "NVDA", "exchange": "NASDAQ",
                                            "currency": "USD", "owned_by_investor": False})
        self.assertEqual(facts["last_price_value"], 188.4)

    def test_holdings_still_get_their_position(self):
        position = {"con_id": 1, "symbol": "NVDA", "name": "NVIDIA Corp", "exchange": "NASDAQ", "currency": "USD",
                    "quantity": 10, "avg_cost": 150, "market_price": 188.4, "market_value": 1884,
                    "unrealized_pnl": 384, "unrealized_pnl_pct": 25.6}
        facts = asyncio.run(summary_facts.build_facts(inputs(position), LOADERS, now=NOW))["facts"]
        self.assertTrue(facts["company"]["owned_by_investor"])
        self.assertEqual(facts["D:position"]["quantity"], 10)


class NotOwnedBriefingTests(unittest.TestCase):
    def test_nine_sections_and_a_prompt_without_the_position(self):
        sections, system = ai_summary.briefing_for(False)
        self.assertEqual(len(sections), 9)
        self.assertNotIn("your_position", sections)
        self.assertNotIn("explain the figures in D:position", system)
        self.assertIn("doesn't own this stock", system)
        schema = ai_summary.build_schema(["D:key_stats"], sections)
        self.assertNotIn("your_position", schema["properties"])
        self.assertEqual(schema["required"], sections)
        self.assertEqual(ai_summary.briefing_for(True), (ai_summary.SECTIONS, ai_summary.SYSTEM_PROMPT))

    def test_saved_summary_without_your_position_reads_back(self):
        with tempfile.TemporaryDirectory() as folder:
            original = summary_store.DB_PATH
            summary_store.DB_PATH = Path(folder) / "summaries.sqlite"
            try:
                facts = {"company": {"symbol": "NVDA", "owned_by_investor": False}, "as_of_text": "18 Oct 2026",
                         "D:key_stats": {}, "D:missing": [], "news": []}
                point = {"text": "Makes chips.", "sources": ["D:key_stats"]}
                summary = {name: {"status": "ok", "points": [point]} for name in ai_summary.NOT_OWNED_SECTIONS}
                summary["news_digest"] = {"status": "unavailable", "themes": []}
                summary["bull_bear"] = {"status": "ok", "bull": [point], "bear": [point]}
                summary_store.save(4815747, "NVDA", NOW.isoformat(), "claude-haiku-4-5", facts, summary, [])
                response = summaries.saved_summary_response(summary_store.latest(4815747))
                self.assertFalse(response["owned"])
                self.assertNotIn("your_position", response["summary"])
                self.assertEqual(len(response["summary"]), 9)
            finally:
                summary_store.DB_PATH = original


if __name__ == "__main__":
    unittest.main()
