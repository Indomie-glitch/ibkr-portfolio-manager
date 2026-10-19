"""Regression test for #264: a day's price is only stored as a close once that market's session is over.

The bug: during the ASX's trading day, Yahoo's row for today held the latest price (or yesterday's close
repeated), and it was stored as today's close for the rest of the day.
"""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from yahoo import finished_days

SYD = ZoneInfo("Australia/Sydney")
NY = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")


def rows(zone, *days):
    return [(datetime(2026, 10, d, 0, 0, tzinfo=zone), 100.0 + d) for d in days]


class FinishedDaysTests(unittest.TestCase):
    def test_asx_today_is_left_out_while_trading(self):
        # 1:45 pm in Sydney on Monday 19 Oct: Friday's close is final, Monday's row is not
        now = datetime(2026, 10, 19, 13, 45, tzinfo=SYD)
        self.assertEqual(finished_days(rows(SYD, 16, 19), "CBA.AX", now), [(datetime(2026, 10, 16).date(), 116.0)])

    def test_asx_today_counts_after_the_close(self):
        now = datetime(2026, 10, 19, 17, 0, tzinfo=SYD)
        self.assertEqual(len(finished_days(rows(SYD, 16, 19), "CBA.AX", now)), 2)

    def test_us_session_is_judged_in_new_york_time(self):
        # 2 am Tuesday in Sydney is 11 am Monday in New York: Monday's US row is still trading
        now = datetime(2026, 10, 20, 2, 0, tzinfo=SYD)
        self.assertEqual([d.day for d, _ in finished_days(rows(NY, 16, 19), "AAPL", now)], [16])
        # 9 am Tuesday in Sydney is 6 pm Monday in New York: Monday has closed
        later = datetime(2026, 10, 20, 9, 0, tzinfo=SYD)
        self.assertEqual([d.day for d, _ in finished_days(rows(NY, 16, 19), "AAPL", later)], [16, 19])

    def test_currency_today_is_always_left_out(self):
        # AUDUSD trades around the clock: today's row is a running quote even in the evening
        now = datetime(2026, 10, 19, 20, 0, tzinfo=LONDON)
        self.assertEqual([d.day for d, _ in finished_days(rows(LONDON, 16, 19), "AUDUSD=X", now)], [16])


if __name__ == "__main__":
    unittest.main()
