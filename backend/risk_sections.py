"""The sections of GET /risk (Milestone 8): each turns the shared RiskInputs into one panel's numbers.

The maths is in risk.py; this file only picks inputs and shapes the answer. A section that raises
becomes {"error"} in the response (routers/risk.py), so one failure doesn't break the others.
"""
import risk


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


# Section name -> function(inputs), in the order of the page
SECTIONS = {
    "correlation": correlation_section,
    "volatility": volatility_section,
}
