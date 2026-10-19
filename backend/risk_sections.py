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


# Section name -> function(inputs), in the order of the page
SECTIONS = {
    "correlation": correlation_section,
}
