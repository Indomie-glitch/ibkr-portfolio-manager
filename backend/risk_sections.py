"""The sections of GET /risk (Milestone 8): each turns the shared RiskInputs into one panel's numbers.

The maths is in risk.py; this file only picks inputs and shapes the answer. A section that raises
becomes {"error"} in the response (routers/risk.py), so one failure doesn't break the others.
"""
import risk
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
    return None if value is None else round(float(value), places)


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


# Section name -> function(inputs), in the order of the page
SECTIONS = {
    "concentration": concentration_section,
    "exposure": exposure_section,
    "correlation": correlation_section,
    "volatility": volatility_section,
}
