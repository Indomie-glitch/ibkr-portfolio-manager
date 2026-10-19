"""The two summary streaming routes (POST /summary/{con_id}, POST /portfolio-summary): which events
they send for every outcome, what they save and what usage they log. Claude and the facts are faked."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

import ai_summary
import portfolio_summary
import summary_store
import usage_store
from routers import summaries

POINT = {"text": "Makes chips.", "sources": ["D:key_stats"]}


def section(name):
    if name == "news_digest":
        return {"status": "ok", "themes": [{"theme": "T", "points": [POINT]}]}
    if name == "bull_bear":
        return {"status": "ok", "bull": [POINT], "bear": [POINT]}
    return {"status": "ok", "points": [POINT]}


STOCK_FACTS = {"as_of": "2026-10-18T09:00:00+11:00", "as_of_text": "18 Oct 2026, 9:00am AEDT",
               "company": {"symbol": "NVDA", "owned_by_investor": False}, "D:key_stats": {}, "D:missing": [], "news": []}
PORTFOLIO_FACTS = {"as_of": "2026-10-18T09:00:00+11:00", "as_of_text": "18 Oct 2026, 9:00am AEDT",
                   "D:portfolio": {"number_of_holdings": 5}, "D:key_stats": {}, "D:missing": []}
USAGE = {"input_tokens": 1000, "output_tokens": 200}


def fake_stream(sections, *, fail=None, calls=None):
    """Stands in for stream_sections: each section, then the final summary, or fail part way."""
    async def stream(*args, **kwargs):
        if calls is not None:
            calls.append(kwargs)
        for i, name in enumerate(sections):
            if fail and i == 2:
                raise fail
            yield ("section", name, section(name), [])
        yield ("final", {name: section(name) for name in sections}, [], USAGE)
    return stream


def request(origin="http://localhost:5173"):
    return SimpleNamespace(headers={"origin": origin} if origin else {})


async def events(response):
    """[(event, data)] from a streamed response."""
    text = "".join([chunk async for chunk in response.body_iterator])
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


class RouteTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        for store, name in ((summary_store, "summaries.sqlite"), (usage_store, "usage.sqlite")):
            patcher = mock.patch.object(store, "DB_PATH", Path(self.folder.name) / name)
            patcher.start()
            self.addCleanup(patcher.stop)
        key = mock.patch.object(ai_summary, "api_key_configured", return_value=True)
        key.start()
        self.addCleanup(key.stop)
        self.addCleanup(self.folder.cleanup)

    def usage(self):
        return [(r["feature"], r["outcome"], r["input_tokens"]) for r in self.rows()]

    def rows(self):
        with usage_store._connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM ai_usage ORDER BY id")]


class StockSummaryRouteTests(RouteTestCase):
    def run_route(self, stream, facts=STOCK_FACTS, facts_error=None, origin="http://localhost:5173"):
        async def build(con_id):
            if facts_error:
                raise facts_error
            return {"facts": json.loads(json.dumps(facts)), "links": {}}

        async def go():
            with mock.patch.object(summaries, "summary_facts_for", build), \
                 mock.patch.object(ai_summary, "stream_sections", stream):
                return await events(await summaries.generate_summary(4815747, request(origin)))
        return asyncio.run(go())

    def test_success_streams_sections_saves_and_logs_usage(self):
        calls = []
        got = self.run_route(fake_stream(ai_summary.NOT_OWNED_SECTIONS, calls=calls))
        names = [e for e, _ in got]
        self.assertEqual(names[:2], ["status", "facts"])
        self.assertEqual(names[2:-1], ["section"] * 9)
        self.assertEqual(names[-1], "done")
        done = got[-1][1]
        self.assertEqual(len(done["summary"]), 9)
        self.assertFalse(done["owned"])
        # Not owned: the 9-section briefing was asked for
        self.assertEqual(calls[0]["sections"], ai_summary.NOT_OWNED_SECTIONS)
        self.assertEqual(calls[0]["system"], ai_summary.NOT_OWNED_PROMPT)
        self.assertIsNotNone(summary_store.latest(4815747))
        self.assertEqual(self.usage(), [("stock_summary", "ok", 1000)])

    def test_facts_failure(self):
        got = self.run_route(fake_stream([]), facts_error=RuntimeError("Yahoo down"))
        self.assertEqual(got, [("status", {"message": "Gathering data"}),
                               ("error", {"code": "facts_failed", "message": "Couldn't gather the data for this holding."})])
        self.assertEqual(self.usage(), [])

    def test_a_cut_off_summary_is_an_error_and_its_tokens_are_logged(self):
        fail = ai_summary.SummaryError("incomplete", "The summary was cut off before it finished.", USAGE)
        got = self.run_route(fake_stream(ai_summary.SECTIONS, fail=fail))
        self.assertEqual([e for e, _ in got], ["status", "facts", "section", "section", "error"])
        self.assertEqual(got[-1][1], {"code": "incomplete", "message": "The summary was cut off before it finished."})
        self.assertIsNone(summary_store.latest(4815747))
        self.assertEqual(self.usage(), [("stock_summary", "incomplete", 1000)])

    def test_an_error_before_claude_answered_logs_nothing(self):
        fail = ai_summary.SummaryError("network", "Couldn't reach the Anthropic API.")
        got = self.run_route(fake_stream(ai_summary.SECTIONS, fail=fail))
        self.assertEqual(got[-1], ("error", {"code": "network", "message": "Couldn't reach the Anthropic API."}))
        self.assertEqual(self.usage(), [])

    def test_unexpected_errors_get_a_plain_message(self):
        got = self.run_route(fake_stream(ai_summary.SECTIONS, fail=ValueError("boom")))
        self.assertEqual(got[-1], ("error", {"code": "unexpected", "message": "Something went wrong while writing the summary."}))

    def test_one_at_a_time_per_stock(self):
        lock = summaries.summary_locks.setdefault(4815747, asyncio.Lock())

        async def go():
            await lock.acquire()
            try:
                await summaries.generate_summary(4815747, request())
            finally:
                lock.release()
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(go())
        self.assertEqual(caught.exception.status_code, 409)
        summaries.summary_locks.pop(4815747)

    def test_other_websites_are_refused(self):
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(summaries.generate_summary(4815747, request("https://evil.example")))
        self.assertEqual(caught.exception.status_code, 403)


class PortfolioSummaryRouteTests(RouteTestCase):
    def run_route(self, stream, facts=PORTFOLIO_FACTS, facts_error=None):
        async def build():
            if facts_error:
                raise facts_error
            return json.loads(json.dumps(facts))

        async def go():
            with mock.patch.object(summaries, "portfolio_facts_for", build), \
                 mock.patch.object(portfolio_summary, "stream_sections", stream):
                return await events(await summaries.generate_portfolio_summary(request()))
        return asyncio.run(go())

    def test_success_streams_sections_saves_and_logs_usage(self):
        got = self.run_route(fake_stream(portfolio_summary.SECTIONS))
        self.assertEqual([e for e, _ in got], ["status", "facts"] + ["section"] * 8 + ["done"])
        self.assertEqual(len(got[-1][1]["summary"]), 8)
        self.assertIsNotNone(summary_store.latest_portfolio())
        self.assertEqual(self.usage(), [("portfolio_summary", "ok", 1000)])

    def test_risk_findings_can_be_cited(self):
        # D:risk (#108) is offered to the model as a source, and a key risk citing it is kept
        seen = []
        risk_point = {"text": "Volatility is 19.8% a year.", "sources": ["D:risk"]}

        async def stream(facts, source_ids, client=None):
            seen.extend(source_ids)
            sections = {name: section(name) for name in portfolio_summary.SECTIONS}
            sections["key_risks"] = {"status": "ok", "points": [risk_point, risk_point]}
            for name in portfolio_summary.SECTIONS:
                yield ("section", name, sections[name], [])
            yield ("final", sections, [], USAGE)

        facts = {**PORTFOLIO_FACTS, "D:risk": {"available": True, "volatility_pct": 19.8}}
        got = self.run_route(stream, facts=facts)
        self.assertIn("D:risk", seen)
        self.assertEqual(got[-1][0], "done")
        self.assertEqual(got[-1][1]["summary"]["key_risks"]["points"][0]["sources"], ["D:risk"])

    def test_no_holdings(self):
        facts = {**PORTFOLIO_FACTS, "D:portfolio": {"number_of_holdings": 0}}
        got = self.run_route(fake_stream(portfolio_summary.SECTIONS), facts=facts)
        self.assertEqual(got[-1], ("error", {"code": "no_holdings", "message": "There are no share holdings to summarise."}))
        self.assertEqual(self.usage(), [])

    def test_facts_failure(self):
        got = self.run_route(fake_stream([]), facts_error=RuntimeError("IB down"))
        self.assertEqual(got[-1], ("error", {"code": "facts_failed", "message": "Couldn't gather the data for the portfolio."}))

    def test_a_refused_summary_logs_its_tokens(self):
        fail = ai_summary.SummaryError("refused", "The model declined to write this summary.", USAGE)
        got = self.run_route(fake_stream(portfolio_summary.SECTIONS, fail=fail))
        self.assertEqual(got[-1], ("error", {"code": "refused", "message": "The model declined to write this summary."}))
        self.assertIsNone(summary_store.latest_portfolio())
        self.assertEqual(self.usage(), [("portfolio_summary", "refused", 1000)])

    def test_unexpected_errors_get_a_plain_message(self):
        got = self.run_route(fake_stream(portfolio_summary.SECTIONS, fail=KeyError("x")))
        self.assertEqual(got[-1], ("error", {"code": "unexpected", "message": "Something went wrong while writing the summary."}))

    def test_one_at_a_time(self):
        async def go():
            await summaries.portfolio_summary_lock.acquire()
            try:
                await summaries.generate_portfolio_summary(request())
            finally:
                summaries.portfolio_summary_lock.release()
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(go())
        self.assertEqual(caught.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
