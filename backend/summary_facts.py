"""The facts sheet for an AI summary: everything the app knows about one holding, with every
number calculated here in Python. The model only explains these numbers; it never computes.

Each block has an id ("D:key_stats", news "N1"...) that the model must cite.
"""
import math
import re
import statistics
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import yahoo
from secrets_guard import mask_secrets

CURRENCY_SYMBOLS = {"AUD": "A$", "USD": "US$"}
MINUS = "−"


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
        print(f"Summary facts: {what} unavailable ({exc.__class__.__name__}: {mask_secrets(exc)})")
        missing.append(f"{what} (Yahoo Finance unavailable)")
        return None


# ---------- the facts sheet ----------

def position_lots(holding_lots):
    """Purchase lots and 12-month CGT discount dates for D:position, from lots.lots_for() (the
    Flex report), all as stated facts. Without a report, says the purchase date is unknown."""
    if not holding_lots or not holding_lots["lots"]:
        return {
            "purchase_date": None,
            "cgt_12_month_date": None,
            "cgt_note": "Purchase date unknown: Interactive Brokers' trading connection doesn't provide it, "
                        "and no IBKR Flex report with purchase dates is set up",
        }
    report_day = date.fromisoformat(holding_lots["report_date"]) if holding_lots.get("report_date") else None
    lots = []
    for lot in holding_lots["lots"]:
        opened = date.fromisoformat(lot["opened"])
        discount_from = date.fromisoformat(lot["cgt_discount_from"])
        lots.append({
            "quantity": lot["quantity"],
            "purchase_date": long_date(opened),
            "cgt_discount_from": long_date(discount_from),
            "days_until_discount": lot["days_until_discount"],
            "discount_applies_now": lot["days_until_discount"] == 0,
        })
    first, last = lots[0], lots[-1]
    waiting = [lot for lot in lots if not lot["discount_applies_now"]]
    # Lots bought on one day share their dates: say that date once, never a same-day range (#192)
    one_day = first["purchase_date"] == last["purchase_date"]
    if len(lots) == 1:
        purchase_date = first["purchase_date"]
    elif one_day:
        purchase_date = f"{first['purchase_date']} ({len(lots)} purchases)"
    else:
        purchase_date = f"{len(lots)} lots, bought {first['purchase_date']} to {last['purchase_date']}"
    if not waiting:
        cgt_date = (f"All lots qualify (since {last['cgt_discount_from']})" if one_day
                    else f"All lots qualify (the last since {last['cgt_discount_from']})")
    elif len({lot["cgt_discount_from"] for lot in waiting}) == 1 and len(waiting) == len(lots):
        cgt_date = f"{waiting[0]['cgt_discount_from']} for all shares"
    else:
        cgt_date = f"Next lot qualifies on {waiting[0]['cgt_discount_from']}"
    unknown = holding_lots.get("unknown_quantity") or 0
    source = ("IBKR's own lots in the Flex report" if holding_lots["source"] == "flex_lots"
              else "trades in the Flex report, oldest sold first")
    return {
        "purchase_date": purchase_date,
        "cgt_12_month_date": cgt_date,
        "lots": lots,
        "shares_with_unknown_purchase_date": unknown or None,
        "cgt_note": (
            f"Purchase dates from {source}"
            + (f" as of {long_date(report_day)}" if report_day else "")
            + ". The CGT discount applies to a sale from the day after the 12-month anniversary of purchase"
            + (f"; {unknown:g} shares were bought outside the report's period, so their dates are unknown" if unknown else "")
        ),
    }


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
    # Only needed to compare with the previous summary
    index_intraday = await safe(loaders["index_intraday"], "Intraday benchmark prices", missing) if previous else None
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

    # News ids and local dates first: price moves list the news dated near each move
    news_dates = []
    for i, item in enumerate(news or [], start=1):
        published = datetime.fromisoformat(item["published"]).astimezone().date() if item.get("published") else None
        news_dates.append((f"N{i}", published))

    def news_near(day):
        """News dated on the move's day or up to 3 days before (calculated here, not by the model)."""
        return [news_id for news_id, published in news_dates if published and timedelta(0) <= day - published <= timedelta(days=3)]

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
                    "news_on_or_up_to_3_days_before": news_near(day),
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
        **position_lots(inputs.get("lots")),
    }

    # --- news with ids, and D:since_last ---
    links, news_facts = {}, []
    for i, item in enumerate(news or [], start=1):
        news_id = f"N{i}"
        published = datetime.fromisoformat(item["published"]).astimezone() if item.get("published") else None
        links[news_id] = {"url": item["url"], "title": item["title"], "publisher": item["publisher"], "published": item.get("published")}
        entry = {"id": news_id, "date": long_date(published.date()) if published else None,
                 "publisher": item["publisher"], "title": item["title"]}
        if previous and published and datetime.fromisoformat(previous["created_at"]) < published <= now:
            entry["published_between_summaries"] = True
        news_facts.append(entry)
    facts["news"] = news_facts

    benchmark_now = intraday_or_daily_now(index_intraday, index_closes)
    if previous:
        then = datetime.fromisoformat(previous["created_at"]).astimezone()  # local zone name (AEDT)
        previous_price = previous["facts"].get("last_price_value")
        facts["D:since_last"] = {
            "previous_summary": as_of_text(then),
            **prices_then_and_now(previous_price, last, currency),
            **since_last_move(
                then=then, now=now, price_then=previous_price, price_now=last,
                benchmark_name="S&P/ASX 200" if is_asx else "S&P 500",
                benchmark_then=saved_benchmark_level(previous, inputs.get("index_symbol")),
                benchmark_now=benchmark_now, intraday=index_intraday, daily=index_closes,
                exchange_zone=ZoneInfo("Australia/Sydney" if is_asx else "America/New_York"),
                beta=(info or {}).get("beta"), stock_closes=[b.close for b in inputs["bars"]][:-1] + [last],
            ),
            "news_between_summaries": [n["id"] for n in news_facts if n.get("published_between_summaries")],
        }
    else:
        facts["D:since_last"] = {"previous_summary": None, "note": "This is the first summary of this stock"}

    facts["D:missing"] = missing
    # Kept with the saved summary (not needed by the model): the raw price and benchmark level
    # for the next summary's comparison
    facts["last_price_value"] = last
    if benchmark_now is not None:
        facts["benchmark_level"] = {"symbol": inputs.get("index_symbol"), "value": benchmark_now, "time": now.isoformat()}
    return {"facts": facts, "links": links}


# ---------- Why the price moved since the previous summary ----------

VOLATILITY_DAYS = 60  # daily returns used for the stock's typical move
RESIDUAL_LIMIT = 1.5  # company specific when the unexplained move is more than this many typical moves
FALLBACK_POINTS = 1  # without beta or volatility: in line with the market within this many percentage points
BAR = timedelta(minutes=5)

RULE = (f"expected_move_pct = beta_5y × benchmark_change_since_pct; residual_pct = price_change_since_pct − "
        f"expected_move_pct; typical_daily_move_pct = the standard deviation of the stock's daily % changes over "
        f"the last {VOLATILITY_DAYS} trading days; typical_move_this_window_pct = typical_daily_move_pct × "
        f"√(trading_days_between). Company specific if the residual is larger than {RESIDUAL_LIMIT} × "
        f"typical_move_this_window_pct, otherwise in line with the market. small_move: the stock moved less than "
        f"typical_move_this_window_pct.")
FALLBACK_RULE = (f"Beta or volatility not available: in line with the market if the stock moved within "
                 f"{FALLBACK_POINTS} percentage point of the benchmark, otherwise company specific. small_move: "
                 f"the stock moved less than 1%.")


def prices_then_and_now(then, now, currency):
    """Both prices, with a third decimal when two different prices round to the same cents
    (A$4.786 and A$4.790 would both show as A$4.79 next to a 0.08% change)."""
    then_text, now_text = money(then, currency), money(now, currency)
    if then is not None and now is not None and then_text == now_text and round(then, 3) != round(now, 3):
        symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
        then_text, now_text = f"{symbol}{then:,.3f}", f"{symbol}{now:,.3f}"
    return {"price_then": then_text, "price_now": now_text}


def intraday_or_daily_now(intraday, daily):
    """The latest benchmark level: the last 5-minute bar, else the last daily close."""
    if intraday:
        return intraday[-1][1]
    return daily[-1][1] if daily else None


def saved_benchmark_level(previous, index_symbol):
    level = previous["facts"].get("benchmark_level")
    return level["value"] if level and level.get("symbol") == index_symbol else None


def closed_by(day, moment, exchange_zone):
    """Whether that day's session had closed at the moment (both exchanges close at 4pm, plus
    time for the closing auction)."""
    local = moment.astimezone(exchange_zone)
    return day < local.date() or (day == local.date() and local.time() >= time(16, 30))


def benchmark_level_at(moment, intraday, daily, exchange_zone):
    """(level, basis) of the benchmark at a past moment, or (None, None)."""
    if intraday:
        ended = [v for start, v in intraday if start + BAR <= moment]
        if ended and intraday[0][0] <= moment:
            return ended[-1], "5-minute index prices"
    if daily:
        closed = [v for day, v in daily if closed_by(day, moment, exchange_zone)]
        if closed:
            return closed[-1], "daily closes (approximate)"
    return None, None


def trading_days_between(then, now, intraday, daily, exchange_zone):
    """Trading time between two moments in sessions: 5-minute bars in the window divided by the
    bars in a full session, so windows shorter than a session give a fraction of a day."""
    if intraday and intraday[0][0] <= then:
        per_day = {}
        for start, _ in intraday:
            day = start.astimezone(exchange_zone).date()
            per_day[day] = per_day.get(day, 0) + 1
        full_session = statistics.median(per_day.values())
        # From the bar the "then" level was taken from (benchmark_level_at) up to now
        in_window = sum(1 for start, _ in intraday if start + BAR > then and start < now)
        return in_window / full_session
    if daily:
        # Sessions after the close the "then" level came from, up to now
        now_day = now.astimezone(exchange_zone).date()
        return float(sum(1 for day, _ in daily if not closed_by(day, then, exchange_zone) and day <= now_day))
    return None


def typical_daily_move_pct(closes):
    """Standard deviation of the stock's daily % changes over the last VOLATILITY_DAYS days."""
    returns = [change_pct(b, a) for a, b in zip(closes, closes[1:]) if a][-VOLATILITY_DAYS:]
    return statistics.stdev(returns) if len(returns) >= 20 else None


def since_last_move(*, then, now, price_then, price_now, benchmark_name, benchmark_then, benchmark_now,
                    intraday, daily, exchange_zone, beta, stock_closes):
    """How much the stock moved since the previous summary, compared with the benchmark, and
    whether the move looks market-wide or company specific. Every number is calculated here."""
    stock = change_pct(price_now, price_then)
    basis = "saved with the previous summary" if benchmark_then is not None else None
    if benchmark_then is None:
        benchmark_then, basis = benchmark_level_at(then, intraday, daily, exchange_zone)
    benchmark = change_pct(benchmark_now, benchmark_then)
    days = trading_days_between(then, now, intraday, daily, exchange_zone)
    result = {
        "price_change_since_pct": pct(stock),
        "benchmark": benchmark_name,
        "benchmark_change_since_pct": pct(benchmark),
        "benchmark_basis": basis,
        "trading_between_summaries": None if days is None else days > 0,
        "trading_days_between": None if days is None else round(days, 2),
    }
    if stock is None:
        return result
    if days == 0:
        result.update(classification=None, small_move=abs(stock) < 1,
                      note="The benchmark didn't trade between the two summaries; any price difference comes "
                           "from trading outside regular market hours")
        return result

    volatility = typical_daily_move_pct(stock_closes)
    if beta is not None and volatility is not None and benchmark is not None and days:
        expected = beta * benchmark
        residual = stock - expected
        typical = volatility * math.sqrt(days)
        result.update(
            beta_5y=pct(beta), typical_daily_move_pct=pct(volatility),
            expected_move_pct=pct(expected), residual_pct=pct(residual), typical_move_this_window_pct=pct(typical),
            classification="company specific" if abs(residual) > RESIDUAL_LIMIT * typical else "in line with the market",
            small_move=abs(stock) < typical, rule=RULE,
        )
    elif benchmark is not None:
        result.update(
            relative_to_benchmark_pct_points=pct(stock - benchmark),
            classification="company specific" if abs(stock - benchmark) > FALLBACK_POINTS else "in line with the market",
            small_move=abs(stock) < 1, rule=FALLBACK_RULE,
        )
    else:
        result.update(classification=None, small_move=abs(stock) < 1,
                      note="Benchmark prices not available, so the move can't be compared with the market")
    return result


def model_facts(facts):
    """The part of the facts sheet the model sees (drops bookkeeping fields)."""
    return {k: v for k, v in facts.items() if k not in ("last_price_value", "benchmark_level", "links")}


def source_ids(facts):
    """Every id the model may cite for this facts sheet."""
    return [k for k in facts if k.startswith("D:")] + [n["id"] for n in facts.get("news", [])]


def parse_money(text):
    """"−A$15.00" -> -15.0 (saved facts keep money as display strings)."""
    match = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    if not match:
        return None
    value = float(match.group().replace(",", ""))
    return -value if text.lstrip().startswith((MINUS, "-")) else value


# Changes smaller than this share of the old value are shown but marked minor (same rule as the
# "Changed" tags in frontend/src/lib/summaryDiff.js)
MINOR_CHANGE_PCT = 1


def compare_data(older, newer):
    """Exact changes between two saved facts sheets, for the top of compare mode.

    Each row is {label, old, new, change, tone, minor}; a value is None when that sheet lacks it.
    """
    currency = newer.get("company", {}).get("currency")
    old_stats, new_stats = older.get("D:key_stats", {}), newer.get("D:key_stats", {})
    old_pos, new_pos = older.get("D:position", {}), newer.get("D:position", {})
    rows = []

    def add(label, old, new, values, text=lambda c: f"{c:+.2f}".replace("-", MINUS), tone=False, change=None):
        """values: the raw (old, new) numbers; change defaults to new - old."""
        old_value, new_value = values
        if change is None and old_value is not None and new_value is not None:
            change = new_value - old_value
        if change is not None:
            change = round(change, 2)
        relative = change_pct(new_value, old_value)
        minor = bool(change) and relative is not None and abs(relative) < MINOR_CHANGE_PCT
        if change is None:
            change_text = None
        elif change == 0:
            change_text = "No change"
        else:
            change_text = text(change) + (f" (under {MINOR_CHANGE_PCT}%)" if minor else "")
        rows.append({
            "label": label, "old": old, "new": new, "change": change_text, "minor": minor,
            "tone": None if minor or not tone or not change else "gain" if change > 0 else "loss",
        })

    def as_money(change):
        return money(change, currency, signed=True)

    def shown(value, suffix=""):
        return None if value is None else f"{value}{suffix}"

    prices = (older.get("last_price_value"), newer.get("last_price_value"))
    add("Price", old_stats.get("last_price"), new_stats.get("last_price"), prices,
        text=lambda c: f"{c:+.2f}%".replace("-", MINUS), tone=True, change=change_pct(prices[1], prices[0]))
    add("P/E (trailing)", shown(old_stats.get("pe_ttm")), shown(new_stats.get("pe_ttm")),
        (old_stats.get("pe_ttm"), new_stats.get("pe_ttm")))
    add("Analyst target", old_stats.get("analyst_target_price"), new_stats.get("analyst_target_price"),
        (parse_money(old_stats.get("analyst_target_price")), parse_money(new_stats.get("analyst_target_price"))),
        text=as_money)
    add("Dividend yield", shown(old_stats.get("dividend_yield_pct"), "%"), shown(new_stats.get("dividend_yield_pct"), "%"),
        (old_stats.get("dividend_yield_pct"), new_stats.get("dividend_yield_pct")),
        text=lambda c: f"{c:+.2f} pts".replace("-", MINUS))
    add("Unrealised P&L", old_pos.get("unrealised_gain_or_loss"), new_pos.get("unrealised_gain_or_loss"),
        (parse_money(old_pos.get("unrealised_gain_or_loss")), parse_money(new_pos.get("unrealised_gain_or_loss"))),
        text=as_money, tone=True)

    old_urls = {link["url"] for link in older.get("links", {}).values()}
    new_news = [news_id for news_id, link in newer.get("links", {}).items() if link["url"] not in old_urls]
    rows.append({"label": "New news items", "old": None, "new": str(len(new_news)), "change": None, "tone": None, "minor": False,
                 "note": "Headlines in the newer summary that the older one didn't have"})
    return rows
