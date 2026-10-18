"""Section 10's maths: why the price moved since the previous summary (summary_facts.since_last_move).

Small hand-checkable examples. The stock's typical daily move comes from closes that alternate
+2% and −2% every day: 20 returns of ±2 have a sample standard deviation of 2 × √(20/19) = 2.052.
"""
import math
import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import summary_facts
from summary_facts import benchmark_level_at, since_last_move, trading_days_between, typical_daily_move_pct

NY = ZoneInfo("America/New_York")
TYPICAL = 2 * math.sqrt(20 / 19)  # 2.052


def zigzag_closes(days=21):
    """Closes whose daily change alternates exactly +2% and −2%."""
    closes = [100.0]
    for i in range(days - 1):
        closes.append(closes[-1] * (1.02 if i % 2 == 0 else 0.98))
    return closes


# Two US sessions: the previous summary was written after Monday's close, this one after Tuesday's
MON, TUE = date(2026, 10, 12), date(2026, 10, 13)
THEN = datetime(2026, 10, 12, 18, 0, tzinfo=NY)
NOW = datetime(2026, 10, 13, 18, 0, tzinfo=NY)
DAILY = [(date(2026, 10, 9), 99.0), (MON, 100.0), (TUE, 101.0)]  # benchmark +1% over the window


def move(price_then, price_now, beta=1.2, closes=None, daily=DAILY, now=NOW, benchmark_then=None):
    return since_last_move(
        then=THEN, now=now, price_then=price_then, price_now=price_now, benchmark_name="S&P 500",
        benchmark_then=benchmark_then, benchmark_now=daily[-1][1] if daily else None, intraday=None, daily=daily,
        exchange_zone=NY, beta=beta, stock_closes=zigzag_closes() if closes is None else closes,
    )


class TypicalMoveTests(unittest.TestCase):
    def test_standard_deviation_of_daily_changes(self):
        self.assertAlmostEqual(typical_daily_move_pct(zigzag_closes()), TYPICAL, places=9)

    def test_needs_twenty_days(self):
        self.assertIsNone(typical_daily_move_pct(zigzag_closes(20)))  # 19 returns

    def test_only_the_last_sixty_days_count(self):
        # 100 flat days, then the zigzag: only the last 60 returns are used
        closes = [100.0] * 100 + zigzag_closes(61)[1:]
        self.assertAlmostEqual(typical_daily_move_pct(closes), 2 * math.sqrt(60 / 59), places=9)


class SinceLastMoveTests(unittest.TestCase):
    def test_in_line_with_the_market(self):
        # Stock +1.5%. Expected 1.2 × 1% = 1.2%, residual 0.3, within 1.5 × 2.052 (one trading day)
        result = move(10.00, 10.15)
        self.assertEqual(result["price_change_since_pct"], 1.5)
        self.assertEqual(result["benchmark_change_since_pct"], 1.0)
        self.assertEqual(result["benchmark_basis"], "daily closes (approximate)")
        self.assertEqual(result["trading_days_between"], 1.0)
        self.assertEqual(result["expected_move_pct"], 1.2)
        self.assertEqual(result["residual_pct"], 0.3)
        self.assertEqual(result["typical_move_this_window_pct"], 2.05)
        self.assertEqual(result["classification"], "in line with the market")
        self.assertTrue(result["small_move"])  # 1.5 < 2.052

    def test_company_specific(self):
        # Stock +8%: residual 8 − 1.2 = 6.8, more than 1.5 × 2.052 = 3.08
        result = move(10.00, 10.80)
        self.assertEqual(result["residual_pct"], 6.8)
        self.assertEqual(result["classification"], "company specific")
        self.assertFalse(result["small_move"])

    def test_negative_residual_counts_too(self):
        # Stock −3% while the market rose 1%: residual −4.2, beyond 3.08 in size
        result = move(10.00, 9.70)
        self.assertEqual(result["residual_pct"], -4.2)
        self.assertEqual(result["classification"], "company specific")

    def test_typical_move_grows_with_the_square_root_of_the_days(self):
        # Four sessions later: typical = 2.052 × √4 = 4.10, so +8% (residual 6.8) is still more than
        # 1.5 × 4.10 = 6.16, but +7% (residual 5.8) is not
        daily = DAILY + [(date(2026, 10, 14), 101.0), (date(2026, 10, 15), 101.0), (date(2026, 10, 16), 101.0)]
        later = datetime(2026, 10, 16, 18, 0, tzinfo=NY)
        result = move(10.00, 10.80, daily=daily, now=later)
        self.assertEqual(result["trading_days_between"], 4.0)
        self.assertEqual(result["typical_move_this_window_pct"], 4.1)
        self.assertEqual(result["classification"], "company specific")
        self.assertEqual(move(10.00, 10.70, daily=daily, now=later)["classification"], "in line with the market")

    def test_without_beta_the_one_point_rule_applies(self):
        # Within 1 percentage point of the benchmark (+1%): in line; more: company specific
        result = move(10.00, 10.15, beta=None)
        self.assertEqual(result["relative_to_benchmark_pct_points"], 0.5)
        self.assertEqual(result["classification"], "in line with the market")
        self.assertEqual(move(10.00, 10.30, beta=None)["classification"], "company specific")
        self.assertIn("percentage point", result["rule"])

    def test_without_enough_history_the_one_point_rule_applies(self):
        self.assertIn("relative_to_benchmark_pct_points", move(10.00, 10.15, closes=zigzag_closes(10)))

    def test_no_trading_between_the_summaries(self):
        # Both summaries after the same close: no session in between
        same_evening = datetime(2026, 10, 12, 20, 0, tzinfo=NY)
        result = move(10.00, 10.02, daily=DAILY[:2], now=same_evening)
        self.assertFalse(result["trading_between_summaries"])
        self.assertIsNone(result["classification"])
        self.assertIn("didn't trade", result["note"])

    def test_without_benchmark_prices(self):
        result = move(10.00, 10.15, daily=None)
        self.assertIsNone(result["benchmark_change_since_pct"])
        self.assertIsNone(result["classification"])
        self.assertIn("not available", result["note"])

    def test_the_saved_benchmark_level_is_used_first(self):
        # The previous summary saved the index at 99.0, so the benchmark moved 101/99 − 1 = +2.02%
        result = move(10.00, 10.15, benchmark_then=99.0)
        self.assertEqual(result["benchmark_basis"], "saved with the previous summary")
        self.assertEqual(result["benchmark_change_since_pct"], 2.02)


class FiveMinuteBarTests(unittest.TestCase):
    """78 bars of 5 minutes make one session (9:30 to 16:00 New York time)."""

    def setUp(self):
        self.bars = []
        for day in (MON, TUE):
            start = datetime(day.year, day.month, day.day, 9, 30, tzinfo=NY)
            for i in range(78):
                self.bars.append((start + timedelta(minutes=5 * i), 100.0 + i / 10 + (10 if day == TUE else 0)))

    def test_half_a_session_plus_a_full_one(self):
        # From 12:45 on Monday (bar 39 of 78) to after Tuesday's close: 39 + 78 bars = 1.5 sessions
        then = datetime(2026, 10, 12, 12, 45, tzinfo=NY)
        self.assertEqual(trading_days_between(then, NOW, self.bars, None, NY), 1.5)

    def test_the_level_then_is_the_last_finished_bar(self):
        # At 12:45 the 12:40 bar (index 38) has just finished
        then = datetime(2026, 10, 12, 12, 45, tzinfo=NY)
        self.assertEqual(benchmark_level_at(then, self.bars, None, NY), (100.0 + 38 / 10, "5-minute index prices"))

    def test_before_the_bars_start_daily_closes_are_used(self):
        before = datetime(2026, 10, 9, 18, 0, tzinfo=NY)
        self.assertEqual(benchmark_level_at(before, self.bars, DAILY, NY), (99.0, "daily closes (approximate)"))


class PricesThenAndNowTests(unittest.TestCase):
    def test_a_third_decimal_when_both_round_to_the_same_cents(self):
        self.assertEqual(summary_facts.prices_then_and_now(4.786, 4.790, "AUD"), {"price_then": "A$4.786", "price_now": "A$4.790"})
        self.assertEqual(summary_facts.prices_then_and_now(4.78, 4.80, "AUD"), {"price_then": "A$4.78", "price_now": "A$4.80"})


if __name__ == "__main__":
    unittest.main()
