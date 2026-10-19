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


# ---------- How holdings move together (#103) ----------

def covariance(returns):
    """Sample covariance matrix Σ of daily returns (columns = holdings), dividing by n − 1."""
    returns = np.asarray(returns, dtype=float)
    return np.atleast_2d(np.cov(returns, rowvar=False, ddof=1))


def correlation(returns):
    """Correlation matrix: covariance scaled so every value is between −1 and +1.

    A holding whose price never moved has no correlation with anything; it shows as 0 (1 with itself).
    """
    cov = covariance(returns)
    sd = np.sqrt(np.diag(cov))
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = cov / np.outer(sd, sd)
    corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
    np.fill_diagonal(corr, 1.0)
    return np.clip(corr, -1.0, 1.0)


def same_direction_share(a, b):
    """Share of days both moved the same way (both up or both down), out of the days both moved."""
    a, b = np.sign(np.asarray(a, dtype=float)), np.sign(np.asarray(b, dtype=float))
    moved = (a != 0) & (b != 0)
    if not moved.any():
        return None
    return float((a[moved] == b[moved]).mean())


def pairs(matrix):
    """Every pair (i, j) with i < j and its value, from a square matrix."""
    n = len(matrix)
    return [(i, j, float(matrix[i][j])) for i in range(n) for j in range(i + 1, n)]


# ---------- Volatility, beta and max drawdown (#102) ----------

def annual_volatility(returns):
    """Yearly volatility: the sample standard deviation of daily returns × √252.

    Works on one series or column by column on a matrix (rows = days).
    """
    returns = np.asarray(returns, dtype=float)
    return np.std(returns, axis=0, ddof=1) * np.sqrt(TRADING_DAYS)


def portfolio_returns(returns, weights):
    """The portfolio's daily return with fixed weights: Σ wᵢ rᵢ for each day."""
    return np.asarray(returns, dtype=float) @ np.asarray(weights, dtype=float)


def beta(returns, index_returns):
    """How much a series moves with an index: cov(r, index) / var(index). None if the index never moved."""
    returns = np.asarray(returns, dtype=float)
    index_returns = np.asarray(index_returns, dtype=float)
    variance = np.var(index_returns, ddof=1)
    if variance == 0:
        return None
    return float(np.cov(returns, index_returns, ddof=1)[0, 1] / variance)


def max_drawdown(returns):
    """The largest fall from a high to a later low of the value grown by these daily returns.

    Returns (fall, peak, trough): fall is negative (−0.2 = −20%), peak and trough are positions in the
    value series, where 0 is the value before the first return and k is the value after return k.
    (0, 0, 0) when the value never fell.
    """
    values = np.concatenate([[1.0], np.cumprod(1 + np.asarray(returns, dtype=float))])
    peaks = np.maximum.accumulate(values)
    falls = values / peaks - 1
    trough = int(np.argmin(falls))
    if falls[trough] >= 0:
        return 0.0, 0, 0
    peak = int(np.argmax(values[: trough + 1]))
    return float(falls[trough]), peak, trough
