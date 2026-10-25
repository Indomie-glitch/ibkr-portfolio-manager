"""Theme seeds (#121): the companies each theme starts with, from seed/themes.json.

A theme is a named group of companies the pipeline watches (the SEC scout, #118, files each member's new filings).
seed_themes is safe to run again: companies are found by ticker (market + ticker), so a second run adds only what's new
and refreshes a company's segment. The list is a starting point; edit seed/themes.json to add companies.
"""
import json
from pathlib import Path

from supply_chain import graph

SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "themes.json"
SEED_SOURCE = "theme seed"


def load_seed(path=None):
    path = Path(path or SEED_PATH)
    return json.loads(path.read_text(encoding="utf-8"))["themes"]


def validate(themes):
    """Problems in a seed (blank names, a ticker used twice in a market, a company in a theme twice); [] when fine."""
    problems = []
    for theme in themes:
        seen = set()
        for company in theme.get("companies", []):
            name, ticker, market = (company.get(k) or "" for k in ("name", "ticker", "market"))
            if not name.strip() or not ticker.strip() or not market.strip():
                problems.append(f"{theme['slug']}: needs name, ticker and market: {company}")
            key = (market, ticker)
            if key in seen:
                problems.append(f"{theme['slug']}: {ticker} ({market}) twice")
            seen.add(key)
    return problems


def seed_themes(conn, themes=None):
    """Writes the themes and their companies; returns {slug: {"added": n, "already": n}}."""
    themes = load_seed() if themes is None else themes
    problems = validate(themes)
    if problems:
        raise ValueError("; ".join(problems))
    result = {}
    for theme in themes:
        theme_id = graph.add_theme(conn, theme["slug"], theme["name"], theme.get("description"))
        counts = {"added": 0, "already": 0}
        for company in theme["companies"]:
            company_id = graph.find_company(conn, "ticker", company["ticker"], company["market"])
            if company_id is None:
                company_id = graph.add_company(conn, company["name"], country=company.get("country"))
                graph.add_identifier(conn, company_id, "ticker", company["ticker"], company["market"], source=SEED_SOURCE)
                counts["added"] += 1
            else:
                counts["already"] += 1
            graph.add_to_theme(conn, theme_id, company_id, company.get("segment"))
        result[theme["slug"]] = counts
    return result


def members(conn, slug):
    """A theme's companies: [{company_id, name, ticker, market, segment}], by segment then name."""
    rows = conn.execute(
        """SELECT c.id AS company_id, c.name, i.value AS ticker, i.market, tc.segment
           FROM themes t JOIN theme_companies tc ON tc.theme_id = t.id JOIN companies c ON c.id = tc.company_id
           LEFT JOIN identifiers i ON i.company_id = c.id AND i.scheme = 'ticker'
           WHERE t.slug = ? ORDER BY tc.segment, c.name""", (slug,)).fetchall()
    return [dict(row) for row in rows]
