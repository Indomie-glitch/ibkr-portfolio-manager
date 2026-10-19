"""Risk maths (Milestone 8): pure functions on prices and returns, no network and no IB.

Each metric is explained with a small worked example in docs/risk-maths.md. Conventions:
- returns are simple daily returns (today / yesterday − 1) of each holding's value in AUD
- a returns matrix has one row per day and one column per holding
- yearly figures use 252 trading days (volatility scales with √252)
"""
from datetime import date, timedelta

import numpy as np

TRADING_DAYS = 252
PERIODS = ("3M", "1Y", "3Y")
PERIOD_MONTHS = {"3M": 3, "1Y": 12, "3Y": 36}
# A holding counts as having the whole window if its first price is at most this many days after
# the window starts (long weekends and holidays at the start of the window)
START_SLACK_DAYS = 7


def months_before(day, months):
    """The same day of the month, `months` earlier (the 31st becomes the month's last day)."""
    year, month = divmod(day.month - 1 - months, 12)
    year, month = day.year + year, month + 1
    for d in (day.day, 30, 29, 28):
        try:
            return date(year, month, d)
        except ValueError:
            continue


def window_start(period, today):
    """First calendar day of the 3M / 1Y / 3Y window ending today."""
    return months_before(today, PERIOD_MONTHS[period])


def covers_window(first_date, start):
    """True when a series starts close enough to the window's start to be used."""
    return first_date <= start + timedelta(days=START_SLACK_DAYS)


def to_aud(closes, audusd):
    """A US dollar price series in Australian dollars: price ÷ that day's AUDUSD rate.

    closes and audusd are {date: value}; days without a rate are dropped.
    """
    return {day: price / audusd[day] for day, price in closes.items() if day in audusd}


def align(series):
    """Keep only the dates on which every series has a value.

    series: {name: {date: value}}. Returns (dates, matrix) with the dates sorted and one column
    per series, in the order of `series`.
    """
    names = list(series)
    if not names:
        return [], np.empty((0, 0))
    common = set(series[names[0]])
    for name in names[1:]:
        common &= set(series[name])
    dates = sorted(common)
    matrix = np.array([[series[name][day] for name in names] for day in dates], dtype=float)
    return dates, matrix.reshape(len(dates), len(names))


def simple_returns(prices):
    """Daily simple returns from a prices matrix (rows = days): one row fewer than the prices."""
    prices = np.asarray(prices, dtype=float)
    return prices[1:] / prices[:-1] - 1


def fx_returns(audusd):
    """Daily return of one US dollar measured in Australian dollars.

    A US dollar is worth 1 / AUDUSD Australian dollars, so its return is
    AUDUSD(yesterday) / AUDUSD(today) − 1: when the Australian dollar rises, a US dollar buys
    fewer of them and the return is negative.
    """
    audusd = np.asarray(audusd, dtype=float)
    return audusd[:-1] / audusd[1:] - 1


def weights(values):
    """Each holding's share of the total value (they add up to 1)."""
    values = np.asarray(values, dtype=float)
    total = values.sum()
    if total <= 0:
        raise ValueError("Holdings have no value")
    return values / total
