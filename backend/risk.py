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


# ---------- Concentration: share of money vs share of risk (#99) ----------

def risk_contributions(weights, cov):
    """Each holding's share of the portfolio's variance: wᵢ (Σw)ᵢ / (wᵀΣw). They add up to 1.

    A share can be negative when a holding moves against the rest and steadies the portfolio.
    """
    w = np.asarray(weights, dtype=float)
    cov = np.asarray(cov, dtype=float)
    marginal = cov @ w
    total = float(w @ marginal)
    if total <= 0:
        return np.full(len(w), np.nan)
    return w * marginal / total


def effective_holdings(weights):
    """How many equal holdings the weights behave like: 1 / Σ wᵢ² (the inverse Herfindahl index)."""
    w = np.asarray(weights, dtype=float)
    return float(1 / np.sum(w ** 2))


def shares_by(weights, labels):
    """Total weight per label, largest first: [(label, share)]."""
    totals = {}
    for weight, label in zip(weights, labels):
        totals[label] = totals.get(label, 0.0) + float(weight)
    return sorted(totals.items(), key=lambda item: -item[1])


# ---------- Currency effect on foreign holdings (#101) ----------

def compound(returns):
    """The total return over all the days: Π(1 + rₜ) − 1 (column by column on a matrix)."""
    return np.prod(1 + np.asarray(returns, dtype=float), axis=0) - 1


def currency_effect_aud(value_aud, fx_return):
    """How many A$ the exchange rate added to (or took from) a US holding worth value_aud today.

    Had the rate not moved, today's value would be value_aud / (1 + r_fx); the difference is the
    currency effect: value_aud × r_fx / (1 + r_fx).
    """
    return value_aud * fx_return / (1 + fx_return)


# ---------- Hidden factors: principal component analysis (#105) ----------

def pca(returns):
    """Principal components of the correlation matrix of daily returns.

    Returns (shares, loadings, factor_returns):
    - shares: each factor's share of the total variance, largest first (they add up to 1)
    - loadings: rows = holdings, columns = factors: each holding's correlation with each factor
      (eigenvector × √eigenvalue)
    - factor_returns: rows = days, columns = factors: the standardised returns combined by each
      eigenvector

    Each factor's sign is chosen so its loadings add up to a positive number (an eigenvector and its
    negative describe the same pattern).
    """
    returns = np.asarray(returns, dtype=float)
    sd = returns.std(axis=0, ddof=1)
    sd[sd == 0] = 1.0  # a holding that never moved stays at 0
    z = (returns - returns.mean(axis=0)) / sd
    values, vectors = np.linalg.eigh(correlation(returns))
    order = np.argsort(values)[::-1]
    values = np.clip(values[order], 0, None)
    vectors = vectors[:, order]
    signs = np.where(vectors.sum(axis=0) < 0, -1.0, 1.0)
    vectors = vectors * signs
    total = values.sum()
    shares = values / total if total > 0 else values
    loadings = vectors * np.sqrt(values)
    return shares, loadings, z @ vectors


# ---------- Sharpe ratio and tracking error (#239) ----------

def annual_return(returns):
    """The yearly rate that compounds to the period's total return: (Π(1 + rₜ))^(252 / n) − 1."""
    returns = np.asarray(returns, dtype=float)
    growth = np.prod(1 + returns)
    return float(growth ** (TRADING_DAYS / len(returns)) - 1)


def sharpe_ratio(returns, risk_free_rate):
    """(yearly return − risk-free rate) / yearly volatility. None when the series never moved."""
    volatility = float(annual_volatility(returns))
    if volatility == 0:
        return None
    return (annual_return(returns) - risk_free_rate) / volatility


def tracking_error(returns, index_returns):
    """How far returns drift from an index in a typical year: sd(r − index) × √252."""
    difference = np.asarray(returns, dtype=float) - np.asarray(index_returns, dtype=float)
    return float(annual_volatility(difference))


# ---------- Value at Risk (#240) ----------

Z_SCORES = {0.95: 1.645, 0.99: 2.326}  # one-sided normal quantiles
MONTH_DAYS = 21
SIMULATION_RUNS = 10_000
SIMULATION_SEED = 2026  # fixed, so the simulated figures don't change between refreshes


def parametric_var(weights, cov, confidence, days=1):
    """Formula VaR as a return: −z × σₚ × √days, with σₚ = √(wᵀΣw) the daily portfolio volatility."""
    w = np.asarray(weights, dtype=float)
    sigma = float(np.sqrt(w @ np.asarray(cov, dtype=float) @ w))
    return -Z_SCORES[confidence] * sigma * np.sqrt(days)


def historical_var(portfolio_returns, confidence, days=1):
    """VaR from what actually happened: the (1 − confidence) percentile of daily returns, or of every
    overlapping run of `days` compounded returns."""
    r = np.asarray(portfolio_returns, dtype=float)
    if days > 1:
        growth = np.cumprod(np.concatenate([[1.0], 1 + r]))
        r = growth[days:] / growth[:-days] - 1
    if len(r) == 0:
        return None
    return float(np.percentile(r, (1 - confidence) * 100))


def simulated_var(weights, cov, confidence, days=1, runs=SIMULATION_RUNS, seed=SIMULATION_SEED):
    """Monte Carlo VaR: `runs` random paths of `days` daily returns drawn from a multivariate normal
    with covariance Σ (mean 0), compounded, and the (1 − confidence) percentile of the results."""
    w = np.asarray(weights, dtype=float)
    rng = np.random.default_rng(seed)
    daily = rng.multivariate_normal(np.zeros(len(w)), np.asarray(cov, dtype=float), size=(runs, days)) @ w
    totals = np.prod(1 + daily, axis=1) - 1
    return float(np.percentile(totals, (1 - confidence) * 100))
