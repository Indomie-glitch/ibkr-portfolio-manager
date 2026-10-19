"""The sections of GET /risk (Milestone 8): each turns the shared RiskInputs into one panel's numbers.

The maths is in risk.py; this file only picks inputs and shapes the answer. A section that raises
becomes {"error"} in the response (routers/risk.py), so one failure doesn't break the others.
"""
import numpy as np

import config
import risk
import risk_data
import yahoo
from portfolio_facts import CURRENCY_PCT, SECTOR_PCT, SINGLE_STOCK_PCT


def _symbols(inputs):
    return [h["symbol"] for h in inputs.holdings]


def correlation_section(inputs):
    """How each pair of holdings moves together (#103): correlation matrix, the most and least
    related pairs, the average, and how often each pair moved the same way."""
    symbols = _symbols(inputs)
    corr = risk.correlation(inputs.returns)
    pair_rows = []
    for i, j, value in risk.pairs(corr):
        pair_rows.append({
            "a": symbols[i], "b": symbols[j], "correlation": round(value, 3),
            "same_direction": risk.same_direction_share(inputs.returns[:, i], inputs.returns[:, j]),
            # How much b tended to move for a 1% move in a (for "when A fell 2%, B tended to fall …")
            "b_per_a": _round(risk.beta(inputs.returns[:, j], inputs.returns[:, i]), 3),
        })
    ranked = sorted(pair_rows, key=lambda p: p["correlation"])
    return {
        "symbols": symbols,
        "matrix": [[round(float(v), 3) for v in row] for row in corr],
        "pairs": pair_rows,
        "most_related": ranked[-1] if ranked else None,
        "least_related": ranked[0] if ranked else None,
        "average": round(sum(p["correlation"] for p in pair_rows) / len(pair_rows), 3) if pair_rows else None,
    }


INDEX_NAMES = {"ASX": "ASX 200", "US": "S&P 500"}
MARKET_NAMES = {"ASX": "Australia", "US": "United States"}
# Yahoo's sector names, shortened as in the design
SECTOR_NAMES = {
    "Financial Services": "Financials",
    "Basic Materials": "Materials",
    "Communication Services": "Communication",
    "Consumer Cyclical": "Consumer cyclical",
    "Consumer Defensive": "Consumer staples",
}


def sector_name(holding):
    sector = holding.get("sector")
    return SECTOR_NAMES.get(sector, sector) if sector else "Unknown"


def _round(value, places=4):
    """Rounded for the response; None for a missing or undefined number (NaN isn't valid JSON)."""
    if value is None or not np.isfinite(value):
        return None
    return round(float(value), places)


def volatility_section(inputs):
    """How much each holding and the portfolio swing, how much they move with the market, and the
    worst fall in the window (#102).

    Volatility uses AUD returns (what you experience). A holding's beta compares its own-currency
    returns with its home index, so the exchange rate doesn't blur how it moves with its market; the
    portfolio's betas compare its AUD returns with each index as quoted.
    """
    holdings = []
    vols = risk.annual_volatility(inputs.returns)
    for i, holding in enumerate(inputs.holdings):
        market = holding["market"]
        holdings.append({
            "symbol": holding["symbol"], "market": market, "weight": _round(holding["weight"]),
            "volatility": _round(vols[i]),
            "beta": _round(risk.beta(inputs.local_returns[:, i], inputs.benchmark_returns[market])),
            "beta_vs": INDEX_NAMES[market],
        })
    portfolio = risk.portfolio_returns(inputs.returns, inputs.weights)
    fall, peak, trough = risk.max_drawdown(portfolio)
    days = [inputs.base_date, *inputs.dates]
    total = sum(h["value_aud"] for h in inputs.holdings)
    return {
        "holdings": holdings,
        "portfolio": {
            "volatility": _round(risk.annual_volatility(portfolio)),
            "beta_asx": _round(risk.beta(portfolio, inputs.benchmark_returns["ASX"])),
            "beta_us": _round(risk.beta(portfolio, inputs.benchmark_returns["US"])),
            "value_aud": round(total, 2),
            "us_weight": _round(sum(h["weight"] for h in inputs.holdings if h["market"] == "US")),
        },
        "benchmarks": {market: {"name": INDEX_NAMES[market],
                                "volatility": _round(risk.annual_volatility(inputs.benchmark_returns[market]))}
                       for market in ("ASX", "US")},
        "max_drawdown": {
            "fall": _round(fall),
            "peak": days[peak].isoformat() if fall < 0 else None,
            "trough": days[trough].isoformat() if fall < 0 else None,
            # The same fall on today's holdings
            "loss_aud": round(fall * total, 2),
        },
    }


def concentration_section(inputs):
    """How much of the money sits in each stock next to how much of the swings it causes, the top 3,
    the effective number of holdings, and warnings over the AI portfolio summary's thresholds (#99)."""
    weights = inputs.weights
    contributions = risk.risk_contributions(weights, risk.covariance(inputs.returns))
    rows = sorted(
        ({"symbol": h["symbol"], "weight": _round(w), "risk_share": _round(c) if c == c else None}  # c == c drops NaN
         for h, w, c in zip(inputs.holdings, weights, contributions)),
        key=lambda r: -r["weight"],
    )
    warnings = []

    def warn(kind, name, share, threshold):
        if share * 100 > threshold:
            warnings.append({"kind": kind, "name": name, "share": _round(share), "threshold": threshold / 100})

    for row in rows:
        warn("stock", row["symbol"], row["weight"], SINGLE_STOCK_PCT)
    for sector, share in risk.shares_by(weights, [sector_name(h) for h in inputs.holdings]):
        if sector != "Unknown":
            warn("sector", sector, share, SECTOR_PCT)
    for currency, share in risk.shares_by(weights, [h["currency"] for h in inputs.holdings]):
        warn("currency", currency, share, CURRENCY_PCT)
    return {
        "holdings": rows,
        "count": len(rows),
        "top3_share": _round(sum(r["weight"] for r in rows[:3])),
        "largest": rows[0],
        "effective_holdings": _round(risk.effective_holdings(weights), 2),
        "warnings": warnings,
        "thresholds": {"stock": SINGLE_STOCK_PCT / 100, "sector": SECTOR_PCT / 100, "currency": CURRENCY_PCT / 100},
    }


def exposure_section(inputs):
    """How the holdings split by currency, market and sector, as shares of their AUD value (#100).
    Cash isn't a holding; it's reported separately for the footnote."""
    weights = inputs.weights

    def split(labels):
        return [{"name": name, "share": _round(share)} for name, share in risk.shares_by(weights, labels)]

    return {
        "currency": split([h["currency"] for h in inputs.holdings]),
        "market": split([MARKET_NAMES.get(h["market"], h["market"]) for h in inputs.holdings]),
        "sector": split([sector_name(h) for h in inputs.holdings]),
        "holdings_value_aud": round(sum(h["value_aud"] for h in inputs.holdings), 2),
        "cash_aud": None if inputs.cash_aud is None else round(inputs.cash_aud, 2),
    }


def currency_section(inputs):
    """For each US holding over the window: its price return in USD, the AUD/USD effect and the return
    in AUD, where 1 + AUD return = (1 + USD return)(1 + FX return); and the portfolio's total currency
    effect in A$ (#101)."""
    fx = float(risk.compound(inputs.fx_returns))
    rows = []
    for i, holding in enumerate(inputs.holdings):
        if holding["currency"] != "USD":
            continue
        price = float(risk.compound(inputs.local_returns[:, i]))
        rows.append({
            "symbol": holding["symbol"], "name": holding["name"], "value_aud": round(holding["value_aud"], 2),
            "price_return": _round(price), "fx_return": _round(fx), "aud_return": _round((1 + price) * (1 + fx) - 1),
            "effect_aud": round(risk.currency_effect_aud(holding["value_aud"], fx), 2),
        })
    rows.sort(key=lambda r: -r["value_aud"])
    return {
        "holdings": rows,
        "fx_return": _round(fx),
        "total_effect_aud": round(sum(r["effect_aud"] for r in rows), 2),
    }


# Short sector words for factor names: "US tech (Apple)"
SECTOR_WORDS = {"Technology": "tech", "Financial Services": "financials", "Basic Materials": "materials",
                "Communication Services": "communication", "Healthcare": "healthcare", "Energy": "energy"}
FACTOR_INDEX_MIN = 0.5  # a factor is named after an index only if their returns correlate at least this much


def factor_name(index_corr, top_holding):
    """"Australian market", "US tech (Apple)" or "Mostly Apple"."""
    market, strength = max(index_corr.items(), key=lambda item: abs(item[1] or 0))
    name = top_holding["name"] or top_holding["symbol"]
    if strength is not None and abs(strength) >= FACTOR_INDEX_MIN:
        if market == "ASX":
            return "Australian market"
        word = SECTOR_WORDS.get(top_holding.get("sector"), "market")
        return f"US {word} ({name})"
    return f"Mostly {name}"


def factors_section(inputs):
    """The few shared patterns behind how the holdings move (#105): principal components of the
    correlation matrix, each factor's share of the variance, the holdings' loadings on the first two,
    and a name for each factor."""
    n = len(inputs.holdings)
    if n < 2:
        return {"factors": [], "loadings": [], "top2_share": None, "count": n,
                "note": "Hidden factors need at least two holdings."}
    shares, loadings, factor_returns = risk.pca(inputs.returns)
    factors = []
    for k in range(n):
        index_corr = {market: _round(np.corrcoef(factor_returns[:, k], inputs.benchmark_returns[market])[0, 1], 3)
                      for market in ("ASX", "US")}
        top = inputs.holdings[int(np.argmax(np.abs(loadings[:, k])))]
        factors.append({"id": f"F{k + 1}", "share": _round(shares[k]), "name": factor_name(index_corr, top),
                        "top_holding": top["symbol"], "index_correlation": index_corr})
    return {
        "factors": factors,
        "loadings": [{"symbol": h["symbol"], "f1": _round(loadings[i, 0], 3), "f2": _round(loadings[i, 1], 3)}
                     for i, h in enumerate(inputs.holdings)],
        "top2_share": _round(shares[:2].sum()),
        "count": n,
    }


def performance_section(inputs):
    """Return per unit of risk for the portfolio and the ASX 200 (Sharpe ratio), and how far the
    portfolio drifts from each index (tracking error) (#239). Indexes are total return, as quoted."""
    rf = config.risk_free_rate()
    portfolio = risk.portfolio_returns(inputs.returns, inputs.weights)

    def summary(returns):
        return {"annual_return": _round(risk.annual_return(returns)),
                "volatility": _round(risk.annual_volatility(returns)),
                "sharpe": _round(risk.sharpe_ratio(returns, rf), 3)}

    return {
        "portfolio": summary(portfolio),
        "benchmarks": {"ASX": summary(inputs.benchmark_returns["ASX"])},
        "tracking_error": {market: _round(risk.tracking_error(portfolio, inputs.benchmark_returns[market]))
                           for market in ("ASX", "US")},
        "risk_free_rate": rf,
    }


def var_section(inputs):
    """Value at Risk (#240): the loss on today's holdings that only the worst 1 day in 20 (95%) or 1 in
    100 (99%) should exceed, for 1 day and 1 month (21 trading days), worked out three ways."""
    value = sum(h["value_aud"] for h in inputs.holdings)
    cov = risk.covariance(inputs.returns)
    portfolio = risk.portfolio_returns(inputs.returns, inputs.weights)

    def entry(ret):
        return None if ret is None else {"return": _round(ret, 5), "aud": round(float(ret * value), 2)}

    levels = {}
    for confidence in (0.95, 0.99):
        levels[f"{round(confidence * 100)}"] = {
            "formula": {"day": entry(risk.parametric_var(inputs.weights, cov, confidence)),
                        "month": entry(risk.parametric_var(inputs.weights, cov, confidence, risk.MONTH_DAYS))},
            "history": {"day": entry(risk.historical_var(portfolio, confidence)),
                        "month": entry(risk.historical_var(portfolio, confidence, risk.MONTH_DAYS))},
            "simulated": {"day": entry(risk.simulated_var(inputs.weights, cov, confidence)),
                          "month": entry(risk.simulated_var(inputs.weights, cov, confidence, risk.MONTH_DAYS))},
        }
    return {"value_aud": round(value, 2), "levels": levels, "runs": risk.SIMULATION_RUNS,
            "month_days": risk.MONTH_DAYS}


SHOCK = -0.10  # index falls and the AUD rise
SINGLE_STOCK_SHOCK = -0.20


def home_betas(inputs):
    """Each holding's beta against its home index (own-currency returns); 1 when it can't be measured."""
    betas = []
    for i, holding in enumerate(inputs.holdings):
        b = risk.beta(inputs.local_returns[:, i], inputs.benchmark_returns[holding["market"]])
        betas.append(1.0 if b is None or not np.isfinite(b) else b)
    return betas


def _index_return(scenarios, market, scenario):
    """A market's return over a past crash: its total return index, else its price index."""
    choice = yahoo.RISK_BENCHMARKS[market]
    for symbol in (choice["symbol"], choice["fallback"]):
        ret = scenarios.get(symbol, {}).get(scenario)
        if ret is not None:
            return ret
    return None


def replay(inputs, betas, scenario):
    """What today's holdings would have done over a past crash, in AUD: each holding's own return
    then, or its home index × its beta if it had no prices then. (None, estimated) if not possible."""
    scenarios = inputs.scenarios
    audusd = scenarios.get(yahoo.AUDUSD, {}).get(scenario)
    fx = None if audusd is None else risk.usd_in_aud_return(audusd)
    impact, estimated = 0.0, []
    for holding, b in zip(inputs.holdings, betas):
        ret = scenarios.get(holding["yahoo"], {}).get(scenario)
        if ret is None:
            market_ret = _index_return(scenarios, holding["market"], scenario)
            if market_ret is None:
                return None, []
            ret = b * market_ret
            estimated.append(holding["symbol"])
        if holding["currency"] == "USD":
            if fx is None:
                return None, []
            ret = (1 + ret) * (1 + fx) - 1
        impact += holding["value_aud"] * ret
    return impact, estimated


def stress_section(inputs):
    """What today's holdings would lose in past crashes and simple shocks, worst first (#241)."""
    total = sum(h["value_aud"] for h in inputs.holdings)
    betas = home_betas(inputs)
    rows = []

    def row(kind, key, name, label, impact, **extra):
        rows.append({"kind": kind, "id": key, "name": name, "label": label,
                     "impact_aud": None if impact is None else round(impact, 2),
                     "impact_pct": None if impact is None or not total else _round(impact / total), **extra})

    for key, scenario in risk_data.SCENARIOS.items():
        impact, estimated = replay(inputs, betas, key)
        row("replay", key, scenario["name"], scenario["label"], impact, estimated=estimated)

    largest = max(inputs.holdings, key=lambda h: h["value_aud"])
    row("shock", "largest", f"{largest['name'] or largest['symbol']} falls 20%", "Custom",
        SINGLE_STOCK_SHOCK * largest["value_aud"], symbol=largest["symbol"])
    for market, name in (("US", "S&P 500"), ("ASX", "ASX 200")):
        impact = sum(h["value_aud"] * b * SHOCK for h, b in zip(inputs.holdings, betas) if h["market"] == market)
        # The beta of the whole portfolio this works out to, for the "Using your beta" label
        implied = impact / (SHOCK * total) if total else None
        row("shock", f"index_{market.lower()}", f"{name} falls 10%", f"Using your beta {implied:.2f}", impact,
            implied_beta=_round(implied, 3))
    usd = sum(h["value_aud"] for h in inputs.holdings if h["currency"] == "USD")
    row("shock", "aud", "AUD rises 10% vs USD", "Currency", usd * (1 / 1.1 - 1))

    known = sorted((r for r in rows if r["impact_aud"] is not None), key=lambda r: r["impact_aud"])
    return {"scenarios": known + [r for r in rows if r["impact_aud"] is None], "value_aud": round(total, 2)}


def attribution_section(inputs):
    """Why the holdings beat or trailed the ASX 200 over the window (#242): which market they're in
    (allocation), which stocks within each market (selection), and the exchange rate (currency).

    Each holding's return is compounded over the window and the segments use today's weights (a
    single period), so the parts add up exactly to the difference."""
    local = risk.compound(inputs.local_returns)
    weights = inputs.weights

    def segment(market):
        idx = [i for i, h in enumerate(inputs.holdings) if h["market"] == market]
        w = float(sum(weights[i] for i in idx))
        r = float(sum(weights[i] * local[i] for i in idx) / w) if w else 0.0
        return w, r

    w_au, r_au = segment("ASX")
    w_us, r_us = segment("US")
    benchmark = float(risk.compound(inputs.benchmark_returns["ASX"]))
    us_index = float(risk.compound(inputs.benchmark_returns["US"]))
    fx = float(risk.compound(inputs.fx_returns))
    portfolio, allocation, selection, currency, cross = risk.attribution(w_au, r_au, w_us, r_us, benchmark, us_index, fx)
    return {
        "portfolio_return": _round(portfolio),
        "benchmark_return": _round(benchmark),
        "difference": _round(portfolio - benchmark),
        # The currency part includes the small cross term, so the three add up to the difference
        "allocation": _round(allocation),
        "selection": _round(selection),
        "currency": _round(currency + cross),
        "cross": _round(cross),
        "us_weight": _round(w_us),
        "us_index_return": _round(us_index),
        "fx_return": _round(fx),
    }


CAP = 0.40


def mixes_section(inputs):
    """Other ways the same stocks could have been weighted, as examples from the window's data, not
    advice (#243): the current mix, the largest holding capped at 40%, equal weights and the lowest
    risk mix; and two hedges (the currency on US holdings, and the account's cash)."""
    rf = config.risk_free_rate()
    symbols = _symbols(inputs)
    n = len(symbols)

    def figures(key, weights, **extra):
        daily = risk.portfolio_returns(inputs.returns, weights)
        return {"id": key, "weights": [{"symbol": s, "weight": _round(w)} for s, w in zip(symbols, weights)],
                "volatility": _round(risk.annual_volatility(daily)), "annual_return": _round(risk.annual_return(daily)),
                "sharpe": _round(risk.sharpe_ratio(daily, rf), 3), **extra}

    mixes = [figures("current", inputs.weights)]
    largest = int(np.argmax(inputs.weights))
    largest_holding = inputs.holdings[largest]
    if inputs.weights[largest] > CAP:
        capped = risk.cap_weights(inputs.weights, CAP)
        if capped is not None:
            mixes.append(figures("capped", capped, name=largest_holding["name"] or largest_holding["symbol"]))
    if n > 1:
        mixes.append(figures("equal", np.full(n, 1 / n)))
        mixes.append(figures("lowest_risk", risk.min_variance_weights(risk.covariance(inputs.returns))))

    # Hedges. Currency: US holdings' own-currency returns in place of their AUD returns
    us = [i for i, h in enumerate(inputs.holdings) if h["currency"] == "USD"]
    hedge = None
    if us:
        hedged = inputs.returns.copy()
        hedged[:, us] = inputs.local_returns[:, us]
        daily = risk.portfolio_returns(hedged, inputs.weights)
        fx = float(risk.compound(inputs.fx_returns))
        effect = sum(risk.currency_effect_aud(inputs.holdings[i]["value_aud"], fx) for i in us)
        hedge = {"volatility": _round(risk.annual_volatility(daily)), "annual_return": _round(risk.annual_return(daily)),
                 # What hedging would have changed in A$: the opposite of the currency's effect
                 "result_aud": round(-effect, 2)}
    total = sum(h["value_aud"] for h in inputs.holdings)
    cash = None
    if inputs.cash_aud is not None and inputs.cash_aud + total > 0:
        share = max(0.0, inputs.cash_aud) / (max(0.0, inputs.cash_aud) + total)
        cash = {"cash_aud": round(inputs.cash_aud, 2), "share": _round(share),
                # The whole account swings less: cash doesn't move
                "account_volatility": _round(mixes[0]["volatility"] * (1 - share))}
    return {"mixes": mixes, "cap": CAP, "currency_hedge": hedge, "cash": cash, "count": n}


# Section name -> function(inputs), in the order of the page
SECTIONS = {
    "concentration": concentration_section,
    "exposure": exposure_section,
    "correlation": correlation_section,
    "volatility": volatility_section,
    "currency": currency_section,
    "factors": factors_section,
    "performance": performance_section,
    "var": var_section,
    "stress": stress_section,
    "attribution": attribution_section,
    "mixes": mixes_section,
}
