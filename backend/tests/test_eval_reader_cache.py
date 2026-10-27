import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from eval import supply_chain_eval
from eval.reader_cache import CachingClient, request_key


def run(coro):
    return asyncio.run(coro)


class FakeAnthropic:
    def __init__(self):
        self.calls = 0
        self.messages = self

    async def create(self, **request):
        self.calls += 1
        return SimpleNamespace(stop_reason="end_turn", model=request["model"], usage=SimpleNamespace(input_tokens=1_000_000, output_tokens=0),
                               content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=f'{{"call": {self.calls}}}')])


REQUEST = {"model": "claude-haiku-5-5", "max_tokens": 100, "system": "prompt", "messages": [{"role": "user", "content": "chunk text"}],
           "output_config": {"effort": "medium"}}


class ReaderCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.api = FakeAnthropic()

    def ask(self, run_index=0, fresh=False, **changes):
        client = CachingClient(self.api, run_index, fresh, folder=self.folder)
        response = run(client.messages.create(**{**REQUEST, **changes}))
        return client, response

    def test_a_saved_answer_is_reused_and_costs_nothing_now(self):
        first, answer = self.ask()
        self.assertEqual((first.hits, first.misses, answer.usage.input_tokens), (0, 1, 1_000_000))
        again, cached = self.ask()
        self.assertEqual((again.hits, again.misses, self.api.calls), (1, 0, 1))
        self.assertEqual(cached.content[0].text, answer.content[0].text)
        self.assertEqual((cached.usage.input_tokens, cached.usage.output_tokens), (0, 0))
        self.assertGreater(again.saved_usd, 0)  # what it cost when first read

    def test_a_changed_prompt_chunk_model_or_effort_reads_again(self):
        self.ask()
        for change in ({"system": "new prompt"}, {"messages": [{"role": "user", "content": "other chunk"}]},
                       {"model": "claude-sonnet-5-5"}, {"output_config": {"effort": "low"}}):
            self.ask(**change)
        self.assertEqual(self.api.calls, 5)
        self.assertNotEqual(request_key(REQUEST), request_key({**REQUEST, "system": "new prompt"}))

    def test_each_run_number_has_its_own_answer(self):
        _, one = self.ask(run_index=0)
        _, two = self.ask(run_index=1)
        self.assertNotEqual(one.content[0].text, two.content[0].text)
        _, two_again = self.ask(run_index=1)
        self.assertEqual(two_again.content[0].text, two.content[0].text)
        self.assertEqual(self.api.calls, 2)

    def test_fresh_reads_again_and_replaces_the_saved_answer(self):
        self.ask()
        _, fresh = self.ask(fresh=True)
        self.assertEqual(self.api.calls, 2)
        _, later = self.ask()
        self.assertEqual(later.content[0].text, fresh.content[0].text)

    def test_a_failed_answer_is_not_saved(self):
        class Failing(FakeAnthropic):
            async def create(self, **request):
                self.calls += 1
                return SimpleNamespace(stop_reason="pause_turn", model=request["model"], usage=SimpleNamespace(input_tokens=1, output_tokens=1), content=[])
        self.api = Failing()
        self.ask()
        self.ask()
        self.assertEqual(self.api.calls, 2)


class RunsSummaryTests(unittest.TestCase):
    def test_mean_and_range(self):
        def metrics(found, wrong):
            return {"found": found, "headline_found": 10, "wrong_links": wrong, "wrong_numbers": 0, "trap_links": 0, "duplicate_links": 0, "truth": 89}
        def run_(reader, saved):
            return {"reader_cost": reader, "verifier_cost": 0.1, "reader_cache": {"hits": 1, "misses": 0, "saved_usd": saved}}
        results = [("a", run_(0.0, 0.1), metrics(31, 0)), ("b", run_(0.1, 0.0), metrics(42, 3)), ("c", run_(0.0, 0.1), metrics(36, 1))]
        s = supply_chain_eval.runs_summary(results)
        self.assertEqual((s["found"]["min"], s["found"]["max"], round(s["found"]["mean"], 1)), (31, 42, 36.3))
        self.assertEqual(s["wrong_links"]["runs"], [0, 3, 1])
        self.assertAlmostEqual(s["cost_usd"]["mean"], 0.2)  # cached answers count at what they cost when first read
        text = supply_chain_eval.render_runs("x", __import__("datetime").datetime(2026, 10, 27), [(st, {**r, "reader_effort": "medium", "verifier_effort": "medium"}, m) for st, r, m in results], {}, {"d": 1})
        self.assertIn("| Found (of 89) | 36.3 | 31 | 42 | 31, 42, 36 |", text)
