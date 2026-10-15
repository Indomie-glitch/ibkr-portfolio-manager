"""The facts sheet for an AI summary: everything the app knows about one holding, with every
number calculated here in Python. The model only explains these numbers; it never computes.

Each block has an id ("D:key_stats", news "N1"...) that the model must cite.
"""
from datetime import date, datetime, timedelta

import yahoo

CURRENCY_SYMBOLS = {"AUD": "A$", "USD": "US$"}
MINUS = "−"

# Labels the frontend shows for each data id (also documents what each id means)
DATA_IDS = {
    "D:profile": "About",
    "D:key_stats": "Key statistics",
    "D:financials": "Financial statements",
    "D:valuation_history": "Past P/E",
    "D:price_moves": "Price history",
    "D:performance": "Performance",
    "D:events": "Upcoming events",
    "D:position": "Your position",
    "D:since_last": "Previous summary",
    "D:missing": "Missing data",
}


# ---------- formatting helpers (match how the app displays numbers) ----------

def money(value, currency, signed=False):
    if value is None:
        return None
    sign = MINUS if value < 0 else ("+" if signed and value > 0 else "")
    return f"{sign}{CURRENCY_SYMBOLS.get(currency, currency + ' ')}{abs(value):,.2f}"


def compact(value):
    """52855574528 -> "52.86B" (same as the frontend's formatCompactNumber)."""
    if value is None:
        return None
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= size:
            return f"{value / size:,.2f}{suffix}"
    return f"{value:,.0f}"


def pct(value, digits=2):
    return None if value is None else round(value, digits)


def change_pct(new, old):
    if new is None or not old:
        return None
    return (new / old - 1) * 100


def long_date(day):
    """date(2026, 10, 12) -> "12 Oct 2026"."""
    return f"{day.day} {day.strftime('%b %Y')}"


def fiscal_label(day):
    return f"FY{day.year}"


def as_of_text(moment):
    hour = moment.strftime("%I").lstrip("0")
    return f"{long_date(moment.date())}, {hour}:{moment.strftime('%M')}{moment.strftime('%p').lower()} {moment.tzname()}"


async def safe(load, what, missing):
    """Run one loader; on failure record what's missing and return None."""
    try:
        return await load()
    except Exception as exc:
        print(f"Summary facts: {what} unavailable ({exc.__class__.__name__}: {exc})")
        missing.append(f"{what} (Yahoo Finance unavailable)")
        return None


# ---------- the facts sheet ----------

async def build_facts(inputs, loaders, previous=None, now=None):
    """inputs: IB data gathered by main.py (contract, position, quote, bars, fx, totals).
    loaders: zero-argument async functions for each Yahoo source (cached in main.py).
    previous: the last saved summary for this stock (for "what changed since last time").

    Returns {"facts": ..., "links": ...}: facts go to the model, links (news urls) to the frontend.
    """
    now = now or datetime.now().astimezone()
    today = now.date()
    position = inputs["position"]
    quote = inputs["quote"] or {}
    currency = position["currency"]
    base = inputs["base_currency"]
    fx = inputs["fx_rate"]
    is_asx = inputs["is_asx"]
    missing = []

    info = await safe(loaders["info"], "Company profile and key statistics", missing)
    financials = await safe(loaders["financials"], "Financial statements", missing)
    dividends = await safe(loaders["dividends"], "Dividend history", missing)
    performance = await safe(loaders["performance"], "Long-term performance", missing)
    index_closes = await safe(loaders["index_closes"], "Benchmark prices", missing)
    news = await safe(loaders["news"], "News", missing)

    last = quote.get("last") or position["market_price"]
    name = (info or {}).get("longName") or position["name"]
    facts = {
        "as_of": now.isoformat(timespec="seconds"),
        "as_of_text": as_of_text(now),
        "company": {"name": name, "symbol": position["symbol"], "exchange": position["exchange"], "currency": currency},
    }

    # --- D:profile ---
    if info:
        facts["D:profile"] = {
            "name": name,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "employees": info.get("fullTimeEmployees"),
            "description": info.get("longBusinessSummary"),
        }

    # --- D:key_stats (market fields from IB, slower fields from Yahoo; same as the Key statistics section) ---
    stats = {
        "last_price": money(last, currency),
        "previous_close": money(quote.get("prev_close"), currency),
        "day_change_pct": pct(quote.get("day_change_pct")),
        "day_range": [money(quote.get("day_low"), currency), money(quote.get("day_high"), currency)],
        "volume": compact(quote.get("volume")),
        "average_volume_3m": compact(quote.get("avg_volume")),
    }
    if info:
        target = info.get("targetMeanPrice")
        low52, high52 = info.get("fiftyTwoWeekLow"), info.get("fiftyTwoWeekHigh")
        stats.update({
            "market_cap": compact(info.get("marketCap")),
            "pe_ttm": pct(info.get("trailingPE")),
            "forward_pe": pct(info.get("forwardPE")),
            "eps_ttm": money(info.get("trailingEps"), currency),
            "dividend_yield_pct": pct(info.get("dividendYield")),
            "beta_5y": pct(info.get("beta")),
            "analyst_target_price": money(target, currency),
            "analyst_target_vs_last_price_pct": pct(change_pct(target, last)),
            "range_52_weeks": [money(low52, currency), money(high52, currency)],
            "position_in_52_week_range_pct": pct((last - low52) / (high52 - low52) * 100, 1)
            if low52 is not None and high52 and high52 > low52 else None,
        })
    facts["D:key_stats"] = stats

    # --- D:financials and D:valuation_history ---
    if financials:
        years = sorted(financials["revenue"], reverse=True)  # newest first
        revenue = financials["revenue"]
        latest = years[0] if years else None

        def margin(row, year):
            value = financials[row].get(year)
            return pct(value / revenue[year] * 100, 1) if value is not None and revenue.get(year) else None

        debt, cash, equity = financials["total_debt"], financials["cash"], financials["stockholders_equity"]
        earnings = financials["last_earnings"]
        facts["D:financials"] = {
            "revenue_by_fiscal_year": {fiscal_label(y): compact(revenue[y]) for y in years},
            "revenue_change_latest_year_pct": pct(change_pct(revenue[years[0]], revenue[years[1]]), 1) if len(years) > 1 else None,
            "revenue_change_over_period_pct": pct(change_pct(revenue[years[0]], revenue[years[-1]]), 1) if len(years) > 1 else None,
            "net_margin_pct_by_fiscal_year": {fiscal_label(y): margin("net_income", y) for y in years},
            "operating_margin_pct_latest_year": margin("operating_income", latest) if latest else None,
            "balance_sheet_date": long_date(financials["balance_date"]) if financials["balance_date"] else None,
            "total_debt": compact(debt),
            "cash": compact(cash),
            "net_debt": compact(debt - cash) if debt is not None and cash is not None else None,
            "debt_to_equity_pct": pct(debt / equity * 100, 1) if debt is not None and equity else None,
            "last_earnings_vs_estimate": None,
        }
        if earnings and earnings.get("eps_actual") is not None and earnings.get("eps_estimate") is not None:
            surprise = earnings.get("surprise_pct")
            facts["D:financials"]["last_earnings_vs_estimate"] = {
                "quarter_ending": long_date(date.fromisoformat(earnings["period_end"])),
                "eps_actual": money(earnings["eps_actual"], currency),
                "eps_estimate": money(earnings["eps_estimate"], currency),
                "surprise_pct": pct(surprise),
                "result": "beat" if surprise and surprise > 0.5 else "missed" if surprise and surprise < -0.5 else "in line",
            }
        else:
            missing.append("Last earnings result versus analyst estimates (not available from Yahoo for this company)")

        pe_history = {}
        for year, eps in sorted(financials["diluted_eps"].items(), reverse=True):
            price = financials["price_at_year_end"].get(year)
            if price and eps and eps > 0:
                pe_history[fiscal_label(year)] = round(price / eps, 1)
        facts["D:valuation_history"] = {
            "pe_at_fiscal_year_end": pe_history,
            "average_past_pe": round(sum(pe_history.values()) / len(pe_history), 1) if pe_history else None,
            "note": "Share price at each fiscal year end divided by that year's diluted EPS",
        }
    missing.append("Comparison with similar companies (not available)")

    # --- D:price_moves (IB daily bars vs the benchmark price index on the same dates) ---
    bars = inputs["bars"]
    benchmark_name = "S&P/ASX 200" if is_asx else "S&P 500"
    if len(bars) > 5:
        closes = [(b.date if isinstance(b.date, date) else b.date.date(), b.close) for b in bars]
        # The latest bar is the current (or most recent) session; use the same latest price the
        # rest of the app shows, so today's move here matches the key statistics
        closes[-1] = (closes[-1][0], last)
        index = index_closes or []

        def index_on(day):
            before = [v for d, v in index if d <= day]
            return before[-1] if before else None

        last_day, last_close = closes[-1]
        returns = {}
        for label, sessions in (("1 week", 5), ("1 month", 21), ("3 months", len(closes) - 1)):
            if sessions < len(closes):
                start_day, start_close = closes[-1 - sessions]
                returns[label] = {
                    "from": long_date(start_day),
                    "stock_pct": pct(change_pct(last_close, start_close)),
                    "benchmark_pct": pct(change_pct(index_on(last_day), index_on(start_day))) if index else None,
                }
        daily = [
            (closes[i][0], change_pct(closes[i][1], closes[i - 1][1]), closes[i - 1][0])
            for i in range(max(1, len(closes) - 30), len(closes))
        ]
        biggest = sorted(daily, key=lambda d: abs(d[1] or 0), reverse=True)[:3]
        facts["D:price_moves"] = {
            "benchmark": benchmark_name,
            "to": long_date(last_day),
            "returns": returns,
            "largest_daily_moves_last_30_sessions": [
                {
                    "date": long_date(day),
                    "stock_pct": pct(move),
                    "benchmark_pct": pct(change_pct(index_on(day), index_on(prev_day))) if index else None,
                }
                for day, move, prev_day in sorted(biggest, key=lambda d: d[0])
            ],
            "sector_move": "not available",
            "note": "Price changes only (dividends not included)",
        }
    missing.append("Sector performance (not available)")

    # --- D:performance (total return, dividends reinvested) ---
    if performance:
        labels = {"ytd": "year to date", "1y": "1 year", "3y": "3 years", "5y": "5 years"}
        facts["D:performance"] = {
            "benchmark": f"{performance['benchmark']['name']} (total return index)",
            "total_return_pct": {
                labels[p["period"]]: {"stock": pct(p["stock"]), "benchmark": pct(p["benchmark"])}
                for p in performance["periods"]
            },
        }

    # --- D:events (only future dates) ---
    events = []
    if info:
        # Same date rules as the Key statistics section (earnings in the exchange's time zone)
        dated = yahoo.stats_from_info(info)
        for key, label in (("earnings_date", "Earnings result"), ("ex_dividend_date", "Ex-dividend date")):
            if dated[key] and date.fromisoformat(dated[key]) >= today:
                events.append({"date": long_date(date.fromisoformat(dated[key])), "event": label})
    facts["D:events"] = {
        "upcoming": events,
        "note": None if events else "No upcoming dated events in the data (only past dates are known)",
    }

    # --- D:position (all calculated here) ---
    quantity = position["quantity"]
    market_value = position["market_value"]
    dividends_12m = None
    if dividends is not None:
        cutoff = today - timedelta(days=365)
        dividends_12m = sum(amount for day, amount in dividends if cutoff < day <= today)
    expected = dividends_12m * quantity if dividends_12m is not None else None
    facts["D:position"] = {
        "quantity": quantity,
        "average_cost": money(position["avg_cost"], currency),
        "cost_basis": money(position["avg_cost"] * quantity, currency),
        "market_value": money(market_value, currency),
        "market_value_in_base_currency": money(market_value * fx, base) if currency != base and market_value is not None else None,
        "unrealised_gain_or_loss": money(position["unrealized_pnl"], currency, signed=True),
        "unrealised_gain_or_loss_pct": pct(position["unrealized_pnl_pct"]),
        "portfolio_weight_pct": pct(market_value * fx / inputs["total_market_value_base"] * 100, 1)
        if market_value is not None and inputs["total_market_value_base"] else None,
        "dividends_per_share_last_12_months": money(dividends_12m, currency),
        "expected_yearly_dividends": money(expected, currency),
        "expected_yearly_dividends_in_base_currency": money(expected * fx, base) if expected is not None and currency != base else None,
        "dividend_basis": f"Dividends with ex-dividend dates in the 12 months to {long_date(today)}; future dividends may differ",
        "purchase_date": None,
        "cgt_12_month_date": None,
        "cgt_note": "Purchase date unknown: Interactive Brokers doesn't provide it through this connection",
    }

    # --- news with ids, and D:since_last ---
    previous_urls = set()
    if previous:
        previous_urls = {link["url"] for link in previous["facts"].get("links", {}).values()}
    links, news_facts = {}, []
    for i, item in enumerate(news or [], start=1):
        news_id = f"N{i}"
        published = datetime.fromisoformat(item["published"]).astimezone() if item.get("published") else None
        links[news_id] = {"url": item["url"], "title": item["title"], "publisher": item["publisher"], "published": item.get("published")}
        entry = {"id": news_id, "date": long_date(published.date()) if published else None,
                 "publisher": item["publisher"], "title": item["title"]}
        if previous:
            entry["new_since_last"] = item["url"] not in previous_urls
        news_facts.append(entry)
    facts["news"] = news_facts

    if previous:
        then = datetime.fromisoformat(previous["created_at"])
        previous_price = previous["facts"].get("last_price_value")
        facts["D:since_last"] = {
            "previous_summary": as_of_text(then),
            "price_then": money(previous_price, currency),
            "price_now": money(last, currency),
            "price_change_since_pct": pct(change_pct(last, previous_price)),
            "new_news_ids": [n["id"] for n in news_facts if n.get("new_since_last")],
        }
    else:
        facts["D:since_last"] = {"previous_summary": None, "note": "This is the first summary of this stock"}

    facts["D:missing"] = missing
    # Kept with the saved summary (not needed by the model): the raw price for the next comparison
    facts["last_price_value"] = last
    return {"facts": facts, "links": links}


def model_facts(facts):
    """The part of the facts sheet the model sees (drops bookkeeping fields)."""
    return {k: v for k, v in facts.items() if k not in ("last_price_value", "links")}


def source_ids(facts):
    """Every id the model may cite for this facts sheet."""
    return [k for k in facts if k.startswith("D:")] + [n["id"] for n in facts.get("news", [])]
