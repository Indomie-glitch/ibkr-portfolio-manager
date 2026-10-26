import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

import anthropic

import usage_store
from supply_chain import control, graph, jobs, orchestrator, reader, scout, status, verifier, worker
from supply_chain.db import open_graph
from tests.pipeline_isolation import isolate

SYDNEY = ZoneInfo("Australia/Sydney")


def at(year, month, day, hour=12, minute=0, tz=SYDNEY):
    return datetime(year, month, day, hour, minute, tzinfo=tz).astimezone(timezone.utc)


def run(coro):
    return asyncio.run(coro)


class OrchestratorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.conn = open_graph(self.root / "g.sqlite")
        self.addCleanup(self.conn.close)
        patch = mock.patch.object(usage_store, "DB_PATH", self.root / "usage.sqlite")
        patch.start()
        self.addCleanup(patch.stop)
        isolate(self, self.root)
        control.clock_zone = SYDNEY  # undone by isolate's patch of clock_zone
        control.save_settings(budget_usd=10.0)

    def spend(self, usd, when):
        """A finished run that cost `usd` and started at `when`."""
        job_id, _ = jobs.enqueue(self.conn, "read", f"spend{when.isoformat()}{usd}")
        self.conn.execute("UPDATE jobs SET status = 'done' WHERE id = ?", (job_id,))
        stamp = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.conn.execute("INSERT INTO runs (job_id, started_at, outcome, cost_usd) VALUES (?, ?, 'ok', ?)", (job_id, stamp, usd))

    def company(self, name, ticker, market="US", theme=True, held=False):
        company_id = graph.add_company(self.conn, name)
        graph.add_identifier(self.conn, company_id, "ticker", ticker, market)
        if theme:
            theme_id = self.conn.execute("SELECT id FROM themes LIMIT 1").fetchone()
            theme_id = theme_id["id"] if theme_id else graph.add_theme(self.conn, "ai", "AI")
            graph.add_to_theme(self.conn, theme_id, company_id)
        if held:
            self.conn.execute("UPDATE companies SET held = 1 WHERE id = ?", (company_id,))
        return company_id


class PriorityTests(OrchestratorCase):
    def test_held_companies_come_first_whatever_the_kind(self):
        theme = self.company("Theme Co", "THM")
        held = self.company("Held Co", "HLD", held=True)
        jobs.enqueue(self.conn, "download", "theme-download", priority=60, company_id=theme)   # the most urgent kind
        jobs.enqueue(self.conn, "read", "held-read", priority=45, company_id=held)
        jobs.enqueue(self.conn, "merge", "no-company", priority=99)                              # no company: no boost
        order = []
        while (job := jobs.claim(self.conn, "w")):
            order.append(job["key"])
            jobs.finish(self.conn, job)
        self.assertEqual(order, ["held-read", "no-company", "theme-download"])

    def test_within_a_group_the_kind_priorities_still_apply(self):
        held = self.company("Held Co", "HLD", held=True)
        jobs.enqueue(self.conn, "read", "read", priority=45, company_id=held)
        jobs.enqueue(self.conn, "verify", "verify", priority=46, company_id=held)
        jobs.enqueue(self.conn, "xbrl", "xbrl", priority=55, company_id=held)
        order = []
        while (job := jobs.claim(self.conn, "w")):
            order.append(job["key"])
            jobs.finish(self.conn, job)
        self.assertEqual(order, ["xbrl", "verify", "read"])

    def item(self, symbol, exchange, position=10, sec_type="STK", long_name=None):
        contract = SimpleNamespace(symbol=symbol, primaryExchange=exchange, exchange="SMART", secType=sec_type, longName=long_name)
        return SimpleNamespace(contract=contract, position=position)

    def test_holdings_are_matched_by_ticker_and_market(self):
        amd = self.company("Advanced Micro Devices, Inc.", "AMD")
        cba = self.company("Commonwealth Bank", "CBA", market="ASX", theme=False)
        other = self.company("Other Co", "OTH")
        result = orchestrator.refresh_holdings(self.conn, [self.item("AMD", "NASDAQ"), self.item("CBA", "ASX")])
        self.assertEqual(result, {"held": 2, "added": 0})
        held = {r["id"] for r in self.conn.execute("SELECT id FROM companies WHERE held = 1")}
        self.assertEqual(held, {amd, cba})
        self.assertNotIn(other, held)

    def test_a_holding_follows_a_merged_company(self):
        retired = self.company("Customer A (unnamed customer of X)", "OLD", theme=False)
        named = self.company("Named Co", "NMD")
        self.conn.execute("UPDATE companies SET merged_into = ? WHERE id = ?", (named, retired))
        orchestrator.refresh_holdings(self.conn, [self.item("OLD", "NYSE")])
        self.assertEqual([r["id"] for r in self.conn.execute("SELECT id FROM companies WHERE held = 1")], [named])

    def test_holdings_not_in_the_graph_are_added_and_unknown_ones_skipped(self):
        result = orchestrator.refresh_holdings(self.conn, [self.item("AAPL", "NASDAQ", long_name="Apple Inc."), self.item("7203", "TSEJ"),
                                                          self.item("SOLD", "NYSE", position=0), self.item("OPT", "SMART", sec_type="OPT")])
        self.assertEqual(result, {"held": 1, "added": 1})
        row = self.conn.execute("SELECT name FROM companies WHERE held = 1").fetchone()
        self.assertEqual(row["name"], "Apple Inc.")
        self.assertEqual(graph.find_company(self.conn, "ticker", "AAPL", "US"), self.conn.execute("SELECT id FROM companies WHERE held = 1").fetchone()["id"])

    def test_selling_everything_clears_the_marks(self):
        self.company("Held Co", "HLD", held=True)
        orchestrator.refresh_holdings(self.conn, [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM companies WHERE held = 1").fetchone()[0], 0)

    def test_held_companies_outside_the_theme_are_scouted_and_asx_ones_wait(self):
        theme = self.company("Theme Co", "THM")
        us_held = self.company("Held US", "HUS", theme=False, held=True)
        asx_held = self.company("Held ASX", "HAX", market="ASX", theme=False, held=True)
        asx_theme = self.company("ASX Theme", "NXT", market="ASX")
        plain = self.company("Not watched", "NOP", theme=False)
        self.assertEqual(scout.due_companies(self.conn), [theme, us_held])
        self.assertEqual(sorted(status.watched_ids(self.conn)), sorted([theme, us_held, asx_held, asx_theme]))
        self.assertNotIn(plain, status.watched_ids(self.conn))

    def test_asx_companies_show_as_waiting_for_an_asx_source(self):
        asx = self.company("Held ASX", "HAX", market="ASX", theme=False, held=True)
        nxt = self.company("ASX Theme", "NXT", market="ASX")
        kr = self.company("Samsung", "005930", market="KR")
        rows = {r["company_id"]: r for r in status.company_rows(self.conn)}
        self.assertEqual((rows[asx]["status"], rows[nxt]["status"], rows[asx]["held"]), ("waiting for ASX source", "waiting for ASX source", True))
        self.assertEqual(rows[kr]["status"], "waiting")
        self.assertEqual(status.overview(self.conn)["coverage"]["waiting_for_asx"], 2)


class PaceTests(OrchestratorCase):
    def cap(self, now, **settings):
        control.save_settings(**settings) if settings else None
        return orchestrator.pace(self.conn, now)

    def test_an_even_share_of_what_is_left(self):
        p = orchestrator.pace(self.conn, at(2026, 10, 1))  # 31 days left, US$10
        self.assertAlmostEqual(p["cap"], 10 / 31)
        self.assertAlmostEqual(orchestrator.pace(self.conn, at(2026, 10, 27))["cap"], 10 / 5)

    def test_the_last_day_gets_everything_left(self):
        self.spend(7.0, at(2026, 10, 10))
        p = orchestrator.pace(self.conn, at(2026, 10, 31))
        self.assertAlmostEqual(p["cap"], 3.0)
        self.assertEqual(p["days_left"], 1)

    def test_unspent_days_roll_forward(self):
        before = orchestrator.pace(self.conn, at(2026, 10, 2))["cap"]
        self.spend(0.5, at(2026, 10, 1))  # a day that spent less than its 0.32 share would leave more; this one spent more
        after = orchestrator.pace(self.conn, at(2026, 10, 2))["cap"]
        self.assertLess(after, before)
        self.assertAlmostEqual(after, 9.5 / 30)
        # nothing spent for a week: the days left share the whole budget
        self.assertAlmostEqual(orchestrator.pace(self.conn, at(2026, 10, 8), None)["cap"], (10 - 0.5) / 24)

    def test_the_floor_keeps_some_progress_after_a_heavy_day(self):
        self.spend(7.0, at(2026, 10, 3, 12))  # US$3.00 left with 28 days to go: an even share is 0.107
        p = orchestrator.pace(self.conn, at(2026, 10, 4))
        self.assertAlmostEqual(p["cap"], 10 / 60)  # lifted to the floor, half an even share of the whole budget
        # the floor is never more than what is left
        self.spend(2.95, at(2026, 10, 5, 12))
        self.assertAlmostEqual(orchestrator.pace(self.conn, at(2026, 10, 6))["cap"], 0.05)

    def test_todays_spending_comes_off_todays_allowance_not_off_the_cap(self):
        self.spend(0.1, at(2026, 10, 27, 9))
        p = orchestrator.pace(self.conn, at(2026, 10, 27, 15))
        self.assertAlmostEqual(p["cap"], 2.0)  # computed from what was left at the start of the day
        self.assertAlmostEqual(p["allowance"], 1.9)
        self.assertAlmostEqual(p["spent_today"], 0.1)

    def test_the_monthly_budget_is_the_hard_limit(self):
        self.spend(9.95, at(2026, 10, 10))
        p = orchestrator.pace(self.conn, at(2026, 10, 31))
        self.assertAlmostEqual(p["allowance"], 0.05)
        self.assertAlmostEqual(orchestrator.pace(self.conn, at(2026, 10, 31, 20))["month_left"], 0.05)

    def test_running_jobs_reserve_against_the_allowance(self):
        now = at(2026, 10, 27)
        first = orchestrator.reserve(self.conn, 1.5, now)
        self.assertTrue(first.ok)
        self.assertAlmostEqual(orchestrator.pace(self.conn, now)["allowance"], 0.5)
        self.assertFalse(orchestrator.reserve(self.conn, 0.6, now).ok)  # two workers can't both spend what only one could
        first.release()
        self.assertTrue(orchestrator.reserve(self.conn, 0.6, now).ok)

    def test_run_now_adds_one_days_cap_each_press_and_never_past_the_month(self):
        now = at(2026, 10, 27)
        self.assertAlmostEqual(orchestrator.add_run_now(self.conn, now), 2.0)
        self.assertAlmostEqual(orchestrator.pace(self.conn, now)["allowance"], 4.0)
        self.assertAlmostEqual(orchestrator.add_run_now(self.conn, now), 2.0)
        self.assertAlmostEqual(orchestrator.pace(self.conn, now)["allowance"], 6.0)
        self.assertAlmostEqual(orchestrator.pace(self.conn, now)["extra"], 4.0)

    def test_one_click_early_in_the_month_cannot_spend_the_month(self):
        early = at(2026, 10, 1)
        self.assertAlmostEqual(orchestrator.add_run_now(self.conn, early), 10 / 31, places=5)  # a day's worth, not the month
        self.assertAlmostEqual(orchestrator.pace(self.conn, early)["allowance"], 20 / 31, places=5)

    def test_run_now_stops_adding_when_the_month_has_no_more_to_give(self):
        self.spend(9.0, at(2026, 10, 20))  # US$1.00 left, 5 days to go: a day's cap is 0.20
        now = at(2026, 10, 27)
        added = [round(orchestrator.add_run_now(self.conn, now), 6) for _ in range(6)]
        self.assertEqual(added, [0.2, 0.2, 0.2, 0.2, 0.0, 0.0])
        self.assertAlmostEqual(orchestrator.pace(self.conn, now)["allowance"], 1.0)  # the monthly budget is still the limit

    def test_run_now_extra_is_for_today_only(self):
        orchestrator.add_run_now(self.conn, at(2026, 10, 27))
        self.assertEqual(orchestrator.pace(self.conn, at(2026, 10, 28))["extra"], 0.0)
        self.assertGreater(orchestrator.pace(self.conn, at(2026, 10, 27, 23, 30))["extra"], 0)

    def test_no_run_now_when_the_month_is_used_up(self):
        self.spend(10.0, at(2026, 10, 5))
        self.assertEqual(orchestrator.add_run_now(self.conn, at(2026, 10, 27)), 0.0)


class ClockTests(OrchestratorCase):
    """The day and the month turn over at the same moment: local midnight, not UTC."""
    def test_the_day_starts_at_local_midnight(self):
        before, after = at(2026, 10, 27, 23, 59), at(2026, 10, 28, 0, 1)
        self.assertEqual(control.today(before).isoformat(), "2026-10-27")
        self.assertEqual(control.today(after).isoformat(), "2026-10-28")
        self.assertEqual(control.day_start(before), datetime(2026, 10, 27, tzinfo=SYDNEY))
        self.assertEqual(control.next_day_start(before), datetime(2026, 10, 28, tzinfo=SYDNEY))

    def test_11am_sydney_is_not_a_boundary(self):
        # midnight UTC is 11:00 in Sydney (daylight time): today's spending must not reset then
        self.spend(0.4, at(2026, 10, 27, 9))
        just_before = datetime(2026, 10, 27, 23, 59, tzinfo=timezone.utc)  # 10:59 on the 28th, Sydney
        just_after = datetime(2026, 10, 28, 0, 1, tzinfo=timezone.utc)     # 11:01 on the 28th, Sydney
        self.spend(0.3, at(2026, 10, 28, 8))
        for moment in (just_before, just_after):
            self.assertAlmostEqual(orchestrator.pace(self.conn, moment)["spent_today"], 0.3)
            self.assertEqual(control.today(moment).isoformat(), "2026-10-28")

    def test_the_month_turns_over_with_the_day(self):
        self.spend(9.0, at(2026, 10, 31, 20))
        last_night, first_morning = at(2026, 10, 31, 23, 59), at(2026, 11, 1, 0, 1)
        self.assertAlmostEqual(orchestrator.pace(self.conn, last_night)["month_left"], 1.0)
        fresh = orchestrator.pace(self.conn, first_morning)
        self.assertAlmostEqual(fresh["month_left"], 10.0)
        self.assertEqual((fresh["spent_today"], fresh["days_left"]), (0.0, 30))
        self.assertEqual(control.month_start(first_morning), datetime(2026, 11, 1, tzinfo=SYDNEY))
        self.assertEqual(control.next_month_start(last_night), datetime(2026, 11, 1, tzinfo=SYDNEY))
        self.assertEqual(control.next_month_start(at(2026, 12, 15)), datetime(2027, 1, 1, tzinfo=SYDNEY))

    def test_the_budget_check_uses_the_same_month(self):
        control.save_settings(budget_usd=1.0)
        self.spend(1.0, at(2026, 10, 31, 20))
        self.assertTrue(control.budget_used_up(self.conn, now=at(2026, 10, 31, 23, 59)))
        self.assertFalse(control.budget_used_up(self.conn, now=at(2026, 11, 1, 0, 1)))

    def test_deferred_work_waits_until_the_local_morning(self):
        self.spend(1.99, at(2026, 10, 27, 9))
        denied = orchestrator.reserve(self.conn, 0.5, at(2026, 10, 27, 15))
        self.assertFalse(denied.ok)
        self.assertEqual(denied.until, datetime(2026, 10, 28, 0, 5, tzinfo=SYDNEY))


class ReservationTests(OrchestratorCase):
    def test_a_call_that_fits_goes_ahead(self):
        self.assertTrue(orchestrator.reserve(self.conn, 0.05, at(2026, 10, 27)).ok)

    def test_a_call_that_would_break_todays_cap_waits_for_tomorrow(self):
        self.spend(1.98, at(2026, 10, 27, 9))
        denied = orchestrator.reserve(self.conn, 0.05, at(2026, 10, 27, 15))
        self.assertFalse(denied.ok)
        self.assertIn("tomorrow", denied.reason)

    def test_a_job_bigger_than_a_whole_days_cap_runs_on_a_day_with_nothing_spent(self):
        now = at(2026, 10, 27)  # the cap is 2.00
        big = orchestrator.reserve(self.conn, 3.5, now)
        self.assertTrue(big.ok)
        self.assertFalse(orchestrator.reserve(self.conn, 0.01, now).ok)  # while it runs nothing else is started
        big.release()
        self.spend(0.01, now)
        self.assertFalse(orchestrator.reserve(self.conn, 3.5, now).ok)  # not once the day has spent something
        self.assertTrue(orchestrator.reserve(self.conn, 3.5, at(2026, 10, 28)).ok)  # but the next fresh day it does

    def test_a_job_bigger_than_the_rest_of_the_month_waits_for_next_month(self):
        self.spend(9.8, at(2026, 10, 5))
        denied = orchestrator.reserve(self.conn, 0.5, at(2026, 10, 27))
        self.assertFalse(denied.ok)
        self.assertEqual(denied.until, datetime(2026, 11, 1, 0, 5, tzinfo=SYDNEY))
        self.assertIn("next month", denied.reason)

    def test_a_job_bigger_than_the_whole_monthly_budget_says_so(self):
        denied = orchestrator.reserve(self.conn, 12.0, at(2026, 10, 27))
        self.assertFalse(denied.ok)
        self.assertIn("too big for the budget", denied.reason)

    def test_ai_kinds_are_not_claimed_when_nothing_is_left_to_spend(self):
        kinds = ["scout", "download", "read", "verify", "merge"]
        now = at(2026, 10, 27)
        self.assertEqual(orchestrator.claimable_kinds(self.conn, kinds, now), kinds)
        self.spend(1.999, now)
        self.assertEqual(orchestrator.claimable_kinds(self.conn, kinds, now), ["scout", "download", "merge"])
        self.assertEqual(orchestrator.claimable_kinds(self.conn, ["scout", "download"], now), ["scout", "download"])

    def test_a_run_has_its_own_hard_cap_and_no_pacing(self):
        now = at(2026, 10, 27)
        self.spend(0.2, at(2026, 10, 27, 1))  # spent before the run started
        with mock.patch.object(orchestrator.limits, "pacing", False), mock.patch.object(orchestrator.limits, "run_cap_usd", 0.5), \
                mock.patch.object(orchestrator.limits, "run_since", at(2026, 10, 27, 10)):
            self.assertAlmostEqual(orchestrator.pace(self.conn, now)["allowance"], 0.5)  # not the 2.00 cap, not the month's 9.8
            self.spend(0.3, at(2026, 10, 27, 11))
            self.assertAlmostEqual(orchestrator.pace(self.conn, now)["allowance"], 0.2)
            self.assertTrue(orchestrator.reserve(self.conn, 0.15, now).ok)
            self.assertFalse(orchestrator.reserve(self.conn, 0.1, now).ok)


class EstimateTests(OrchestratorCase):
    def test_a_chunk_read_is_priced_from_its_tokens(self):
        # 40,000 estimated tokens + 1,000 prompt in, 5% out, at Haiku's US$0.10 / US$0.50 per million
        inp = 41_000
        expected = (inp * 0.10 + inp * 0.05 * 0.50) / 1_000_000
        self.assertAlmostEqual(orchestrator.read_estimate(self.conn, 40_000), expected)

    def test_a_tiny_chunk_still_expects_some_output(self):
        self.assertAlmostEqual(orchestrator.read_estimate(self.conn, 100), (1_100 * 0.10 + 500 * 0.50) / 1_000_000)

    def test_the_estimate_is_above_what_the_real_amd_call_cost(self):
        # 45,583 estimated tokens became 38,864 in and 2,022 out: US$0.0049 (reader smoke test)
        self.assertGreater(orchestrator.read_estimate(self.conn, 45_583), 0.0049)

    def test_the_output_ratio_comes_from_chunk_reads_once_there_are_enough(self):
        document = graph.add_document(self.conn, "sec", "10-K", "x", "u")
        for n in range(orchestrator.RATIO_MIN_ROWS):
            self.conn.execute("""INSERT INTO chunk_reads (document_id, chunker_version, chunk_number, locator, text_hash, input_tokens, output_tokens, found, read_at)
                                 VALUES (?, 1, ?, 'l', 'h', 10000, 1000, 0, '2026-10-27T00:00:00Z')""", (document, n))
        self.assertAlmostEqual(orchestrator.output_ratio(self.conn), 0.12)  # 10%, with 20% headroom
        self.assertGreater(orchestrator.read_estimate(self.conn, 40_000), (41_000 * 0.10 + 41_000 * 0.05 * 0.50) / 1_000_000)

    def test_a_verify_batch_is_priced_for_sonnet(self):
        expected = ((6_000 + 700) * 2.00 + (120 * 8 + 100) * 10.00) / 1_000_000
        self.assertAlmostEqual(orchestrator.verify_estimate(6_000, 8), expected)

    def test_calls_are_charged_to_the_run_as_they_are_made(self):
        job_id, _ = jobs.enqueue(self.conn, "read", "k")
        job = jobs.claim(self.conn, "w")
        orchestrator.charge(self.conn, job["run_id"], [{"model": "claude-haiku-5-5", "input_tokens": 10_000, "output_tokens": 500}])
        orchestrator.charge(self.conn, job["run_id"], [{"model": "claude-haiku-5-5", "input_tokens": 20_000, "output_tokens": 0},
                                                       {"model": "claude-sonnet-5", "input_tokens": 1_000, "output_tokens": 100}])
        run = self.conn.execute("SELECT * FROM runs WHERE id = ?", (job["run_id"],)).fetchone()
        self.assertEqual((run["input_tokens"], run["output_tokens"], run["model"]), (31_000, 600, "claude-haiku-5-5, claude-sonnet-5"))
        self.assertAlmostEqual(run["cost_usd"], (30_000 * 0.10 + 500 * 0.50) / 1_000_000 + (1_000 * 2.0 + 100 * 10.0) / 1_000_000)
        jobs.fail(self.conn, job, "the lookup went down", jitter=False)  # the job fails afterwards: the money is still counted
        self.assertAlmostEqual(jobs.spent_since(self.conn, at(2026, 1, 1)), run["cost_usd"])

    def test_finishing_does_not_count_the_cost_twice(self):
        jobs.enqueue(self.conn, "read", "k")
        job = jobs.claim(self.conn, "w")
        orchestrator.charge(self.conn, job["run_id"], [{"model": "claude-haiku-5-5", "input_tokens": 10_000, "output_tokens": 0}])
        jobs.finish(self.conn, job, model="claude-haiku-5-5", input_tokens=10_000, output_tokens=0, cost_usd=0.001)  # what the handler totals
        self.assertAlmostEqual(jobs.spent_since(self.conn, at(2026, 1, 1)), 0.001)


class DeferralTests(OrchestratorCase):
    """Reader and Verifier jobs stop when the allowance can't take the next call and are queued again for the next day."""
    def setUp(self):
        super().setUp()
        import shutil
        folder = self.root / "filings" / "1" / "0001"
        folder.mkdir(parents=True)
        shutil.copy(Path(__file__).parent / "fixtures" / "filings" / "tenk.htm", folder / "tenk.htm")
        self.acme = graph.add_company(self.conn, "Acme Semiconductor Inc.")
        graph.add_identifier(self.conn, self.acme, "ticker", "ACME", "US")
        self.document = graph.add_document(self.conn, "sec", "10-K", "0001/tenk", "https://www.sec.gov/x", company_id=self.acme,
                                           filed_at="2026-02-25", period_end="2026-01-25", status="downloaded")
        self.conn.execute("UPDATE documents SET local_path = ? WHERE id = ?", (str(folder / "tenk.htm"), self.document))

    def leave_allowance(self, usd):
        """Spend today's cap down to `usd` (the spend is stamped just after this morning's midnight)."""
        cap = orchestrator.pace(self.conn)["cap"]
        self.spend(cap - usd, control.day_start() + timedelta(seconds=1))

    def move_spending_to_yesterday(self):
        yesterday = (control.day_start() - timedelta(hours=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.conn.execute("UPDATE runs SET started_at = ?", (yesterday,))

    def client(self, calls):
        async def create(**request):  # each call really costs 10,000 in and 200 out: US$0.0011 at Haiku's price
            calls.append(request)
            return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=10_000, output_tokens=200),
                                   content=[SimpleNamespace(type="text", text='{"relationships": []}')])
        return SimpleNamespace(messages=SimpleNamespace(create=create))

    async def resolve(self, conn, name):
        return {"status": "skipped", "reason": "no_match", "detail": ""}

    def read(self, calls, run_id=None):
        return run(reader.read_document(self.conn, self.document, client=self.client(calls), resolve=self.resolve, run_id=run_id))

    def test_a_read_stops_when_a_chunk_does_not_fit_and_keeps_what_it_read(self):
        self.leave_allowance(0.0008)  # a chunk is estimated at US$0.0004 and really costs 0.0011
        calls = []
        job_id, _ = jobs.enqueue(self.conn, "read", str(self.document), company_id=self.acme)
        job = jobs.claim(self.conn, "w")
        totals = self.read(calls, run_id=job["run_id"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(totals["chunks"], 4)
        self.assertIn("tomorrow", totals["deferred"].reason)
        self.assertEqual(self.conn.execute("SELECT status FROM documents WHERE id = ?", (self.document,)).fetchone()[0], "downloaded")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM chunk_reads").fetchone()[0], 1)
        self.assertAlmostEqual(self.conn.execute("SELECT cost_usd FROM runs WHERE id = ?", (job["run_id"],)).fetchone()[0], 0.0011)

    def test_the_worker_queues_the_rest_for_the_next_day_and_the_next_day_finishes_it(self):
        self.leave_allowance(0.003)  # chunks are estimated at 0.0004 but really cost 0.0011 here: three go ahead; under 0.002 AI jobs aren't claimed
        calls = []
        jobs.enqueue(self.conn, "read", str(self.document), {}, priority=45, company_id=self.acme, document_id=self.document)

        async def handler(job, conn):
            return await reader.read_job(job, conn)

        with mock.patch.object(reader.resolver, "resolve", self.resolve), mock.patch.object(reader.anthropic, "AsyncAnthropic", return_value=self.client(calls)), \
                mock.patch.object(reader.config, "anthropic_api_key", return_value="sk-test"):
            w = worker.Worker(self.root / "g.sqlite", handlers={"read": handler}, name="w1")
            self.assertTrue(run(w.run_once()))
            w.stop()
        self.assertEqual(len(calls), 3)
        done, again = self.conn.execute("SELECT * FROM jobs WHERE kind = 'read' AND key = ? ORDER BY id", (str(self.document),)).fetchall()
        self.assertEqual((done["status"], again["status"]), ("done", "queued"))
        self.assertEqual(again["run_after"], jobs._iso(control.next_day_start() + orchestrator.DEFER_AFTER))
        self.assertIn("waiting for tomorrow", again["last_error"])
        self.assertEqual(status.overview(self.conn)["cost"]["waiting_for_tomorrow"], 1)
        # the same worker finds nothing it may do today: the queued read isn't due yet
        self.assertEqual(orchestrator.claimable_kinds(self.conn, ["read", "scout"]), ["scout"])
        # the next day the allowance is back: the chunks already read aren't paid for again
        self.move_spending_to_yesterday()
        totals = self.read(calls)
        self.assertIsNone(totals["deferred"])
        self.assertEqual((totals["skipped"], len(calls)), (3, 4))
        self.assertEqual(self.conn.execute("SELECT status FROM documents WHERE id = ?", (self.document,)).fetchone()[0], "processed")

    def test_a_cheap_job_still_runs_when_a_dearer_one_does_not_fit(self):
        self.leave_allowance(0.01)  # a Haiku chunk is about US$0.0009, a Sonnet batch of eight claims about US$0.024
        now = datetime.now(timezone.utc)
        batch = orchestrator.verify_estimate(6_000, 8)
        chunk = orchestrator.read_estimate(self.conn, 5_000)
        self.assertGreater(batch, 0.01)
        self.assertLess(chunk, 0.01)
        self.assertFalse(orchestrator.reserve(self.conn, batch, now).ok)
        self.assertTrue(orchestrator.reserve(self.conn, chunk, now).ok)

    def test_candidates_put_off_by_the_budget_do_not_use_up_an_attempt(self):
        read_id = self.conn.execute("""INSERT INTO chunk_reads (document_id, chunker_version, chunk_number, locator, text_hash, found, read_at)
                                       VALUES (?, 1, 1, 'l', 'h', 1, '2026-10-27T00:00:00Z')""", (self.document,)).lastrowid
        self.conn.execute(
            """INSERT INTO candidates (document_id, chunk_read_id, kind, counterparty_role, supplier_name, customer_name, supplier_is_filer, customer_is_filer,
               supplier_id, customer_id, quote, locator, context, candidate_hash, created_at, updated_at)
               VALUES (?, ?, 'supplies', 'supplier', 'Gamma', 'Acme', 0, 1, ?, ?, 'q', 'l', 'c', 'h', '2026-10-27T00:00:00Z', '2026-10-27T00:00:00Z')""",
            (self.document, read_id, self.acme, self.acme))
        self.leave_allowance(0.001)  # a batch of one claim is estimated at about US$0.004
        totals = run(verifier.verify_document(self.conn, self.document, client=SimpleNamespace()))
        self.assertIn("tomorrow", totals["deferred"].reason)
        self.assertEqual(tuple(self.conn.execute("SELECT verify_attempts, status FROM candidates").fetchone()), (0, "pending"))


class GateTests(unittest.TestCase):
    def rate_limited(self, retry_after=None):
        headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
        import httpx2
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx2.Response(429, request=request, headers=headers)
        return anthropic.RateLimitError("rate limited", response=response, body=None)

    def make_gate(self, **kwargs):
        self.now = 0.0
        self.slept = []

        async def sleep(seconds):
            self.slept.append(round(seconds, 3))
            self.now += seconds
            await asyncio.sleep(0)  # a real wait lets the other workers run

        return orchestrator.Gate(clock=lambda: self.now, sleep=sleep, **kwargs)

    def test_calls_start_at_least_a_second_apart(self):
        async def go():
            gate = self.make_gate(concurrent=2, gap_s=1.0)

            async def ok():
                return "done"

            return [await gate.call(ok) for _ in range(3)]
        self.assertEqual(run(go()), ["done"] * 3)
        self.assertEqual(self.slept, [1.0, 1.0])

    def test_a_429_makes_every_worker_wait_for_retry_after(self):
        attempts = []

        async def go():
            gate = self.make_gate(concurrent=2, gap_s=0.0)

            async def limited():
                attempts.append(self.now)
                if len(attempts) == 1:
                    raise self.rate_limited(retry_after=42)
                return "ok"

            async def other():
                attempts.append(("other", self.now))
                return "other"

            first = asyncio.create_task(gate.call(limited))
            await asyncio.sleep(0)
            second = await gate.call(other)  # a second worker, while the first is told to wait
            return await first, second, gate

        first, second, gate = run(go())
        self.assertEqual((first, second), ("ok", "other"))
        self.assertEqual(attempts[0], 0.0)
        self.assertIn(("other", 42.0), attempts)  # the other worker waited too: it didn't go on while the first was told to wait
        self.assertIn(42.0, attempts)
        self.assertIn(42.0, self.slept)

    def test_without_retry_after_the_wait_grows(self):
        async def go():
            gate = self.make_gate(gap_s=0.0)
            calls = []

            async def limited():
                calls.append(1)
                if len(calls) < 3:
                    raise self.rate_limited()
                return "ok"

            return await gate.call(limited)
        self.assertEqual(run(go()), "ok")
        self.assertEqual([s for s in self.slept if s], [30.0, 60.0])

    def test_gives_up_after_three_tries_and_the_wait_is_capped(self):
        async def go():
            gate = self.make_gate(gap_s=0.0)

            async def limited():
                raise self.rate_limited(retry_after=9999)

            with self.assertRaises(anthropic.RateLimitError):
                await gate.call(limited)
        run(go())
        self.assertEqual([s for s in self.slept if s], [300.0, 300.0])

    def test_other_errors_are_not_retried(self):
        async def go():
            gate = self.make_gate(gap_s=0.0)
            calls = []

            async def broken():
                calls.append(1)
                raise ValueError("boom")

            with self.assertRaises(ValueError):
                await gate.call(broken)
            return calls
        self.assertEqual(run(go()), [1])

    def test_at_most_two_calls_run_at_once(self):
        async def go():
            gate = orchestrator.Gate(concurrent=2, gap_s=0.0)
            running, peak = 0, 0

            async def work():
                nonlocal running, peak
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(0.01)
                running -= 1

            await asyncio.gather(*(gate.call(work) for _ in range(6)))
            return peak
        self.assertEqual(run(go()), 2)

    def test_retry_after_header(self):
        self.assertEqual(orchestrator.retry_after(self.rate_limited(retry_after=7), 1), 7.0)
        self.assertEqual(orchestrator.retry_after(self.rate_limited(), 2), 60)


class CostRollupTests(OrchestratorCase):
    def test_reader_and_verifier_costs_roll_up_per_company_and_in_the_cost_tile(self):
        amd = self.company("AMD", "AMD")
        nvda = self.company("NVIDIA", "NVDA")
        now = datetime.now(timezone.utc)
        for company, kind, cost in ((amd, "read", 0.010), (amd, "verify", 0.030), (nvda, "read", 0.004)):
            job_id, _ = jobs.enqueue(self.conn, kind, f"{company}{kind}", company_id=company)
            job = jobs.claim(self.conn, "w")
            jobs.add_usage(self.conn, job["run_id"], "claude-haiku-5-5", 1000, 100, cost)
            jobs.finish(self.conn, job)
        rows = {r["company_id"]: r for r in status.company_rows(self.conn)}
        self.assertAlmostEqual(rows[amd]["cost_usd"], 0.04, places=4)
        self.assertAlmostEqual(rows[nvda]["cost_usd"], 0.004, places=4)
        cost = status.overview(self.conn)["cost"]
        self.assertAlmostEqual(cost["month"], 0.044, places=4)
        self.assertAlmostEqual(cost["today"], 0.044, places=4)
        self.assertEqual(cost["by_stage"], {"read": 0.014, "verify": 0.03})
        self.assertAlmostEqual(cost["today_cap"], orchestrator.pace(self.conn, now)["cap"], places=4)

    def test_run_now_is_shown_in_the_cost(self):
        self.company("AMD", "AMD")
        control.save_settings(enabled=True)
        result = status.run_now(self.conn)
        self.assertGreater(result["added_usd"], 0)
        cost = status.overview(self.conn)["cost"]
        self.assertAlmostEqual(cost["run_now_extra"], result["added_usd"], places=4)
        self.assertAlmostEqual(cost["today_cap"], orchestrator.pace(self.conn)["cap"] + result["added_usd"], places=4)

    def test_a_job_no_month_can_take_needs_attention(self):
        job_id, _ = jobs.enqueue(self.conn, "read", "huge", run_after=datetime.now(timezone.utc) + timedelta(days=30))
        self.conn.execute("UPDATE jobs SET last_error = 'too big for the budget (needs about US$12.00, the monthly budget is US$10.00)' WHERE id = ?", (job_id,))
        attention = status.overview(self.conn)["attention"]
        self.assertEqual((attention["oversized"], attention["total"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
