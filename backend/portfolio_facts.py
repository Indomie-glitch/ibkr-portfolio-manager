"""The facts sheet for the AI portfolio summary (docs/portfolio-summary-spec.md): every number
calculated here in Python. The model only explains them and cites the blocks' ids: D:* for the
portfolio and H:<con_id> for each holding.
"""
from datetime import timedelta

from summary_facts import as_of_text, change_pct, long_date, money, parse_money, pct

# Concentration flags (stated in the facts, so the model can quote them)
SINGLE_STOCK_PCT = 20
SECTOR_PCT = 40
CURRENCY_PCT = 80
EVENTS_DAYS = 60
MONTH_SESSIONS = 21
# Weight changes since the last summary smaller than this (percentage points) aren't listed
WEIGHT_CHANGE_POINTS = 1


def holding_id(con_id):
    return f"H:{con_id}"


def market_of(position):
    return "ASX" if position.get("exchange") == "ASX" else "US"


def _shares(groups, total):
    """{name: value} -> {name: % of total}, largest first."""
    if not total:
        return {}
    return {name: pct(value / total * 100, 1) for name, value in sorted(groups.items(), key=lambda kv: -kv[1])}


def month_move(closes, index_closes, beta):
    """The holding's move over the last month vs its benchmark, and the part beta says the market
    explains. closes / index_closes: [(date, close)], oldest first."""
    if not closes or len(closes) <= MONTH_SESSIONS:
        return None
    start_day, start = closes[-1 - MONTH_SESSIONS]
    end_day, end = closes[-1]
    stock = change_pct(end, start)

    def index_on(day):
        before = [value for d, value in index_closes or [] if d <= day]
        return before[-1] if before else None

    benchmark = change_pct(index_on(end_day), index_on(start_day))
    move = {"from": long_date(start_day), "to": long_date(end_day), "stock_pct": pct(stock), "benchmark_pct": pct(benchmark)}
    if benchmark is not None and beta is not None and stock is not None:
        explained = beta * benchmark
        move.update(beta=pct(beta), explained_by_market_pct=pct(explained), rest_pct=pct(stock - explained))
    return move


def build_portfolio_facts(account, holdings, now, missing=None, previous=None):
    """account: GET /account. holdings: one dict per position with position (GET /positions item),
    quote (GET /quotes item or None), sector, beta, closes, index_closes, benchmark (name),
    events [(date, label)] and dividends_12m (per share, position currency); missing data as None.
    now: an aware datetime (the summary's time). previous: the last saved portfolio facts, or None."""
    today = now.date()
    base = account["currency"]
    rates = account.get("fx_rates") or {}
    missing = list(missing or [])

    def to_base(amount, currency):
        if amount is None:
            return None
        rate = 1 if currency == base else rates.get(currency)
        return amount * rate if rate is not None else None

    rows = []
    for h in holdings:
        p = h["position"]
        value = to_base(p["market_value"], p["currency"])
        if value is None:
            missing.append(f"{p['symbol']}: no exchange rate for {p['currency']}")
            continue
        quote = h.get("quote") or {}
        day_pct = quote.get("day_change_pct")
        rows.append({
            "h": h, "p": p, "value": value,
            "pnl": to_base(p.get("unrealized_pnl"), p["currency"]),
            # Yesterday's value is value / (1 + change), so today's change in money is the difference
            "day_change": value - value / (1 + day_pct / 100) if day_pct is not None else None,
            "dividends": to_base(h["dividends_12m"] * p["quantity"], p["currency"]) if h.get("dividends_12m") is not None else None,
        })
    invested = sum(r["value"] for r in rows)
    weight = {r["p"]["con_id"]: (r["value"] / invested * 100 if invested else None) for r in rows}

    facts = {"as_of": now.isoformat(timespec="seconds"), "as_of_text": as_of_text(now), "base_currency": base}

    # --- one block per holding ---
    for r in rows:
        p, h = r["p"], r["h"]
        upcoming = sorted((day, label) for day, label in h.get("events") or [] if today <= day <= today + timedelta(days=EVENTS_DAYS))
        facts[holding_id(p["con_id"])] = {
            "symbol": p["symbol"],
            "name": p.get("name"),
            "market": market_of(p),
            "currency": p["currency"],
            "sector": h.get("sector"),
            "weight_pct": pct(weight[p["con_id"]], 1),
            "value": money(r["value"], base),
            "unrealised_gain_or_loss": money(r["pnl"], base, signed=True),
            "unrealised_gain_or_loss_pct": pct(p.get("unrealized_pnl_pct")),
            "day_change_pct": pct((h.get("quote") or {}).get("day_change_pct")),
            "last_month_vs_market": month_move(h.get("closes"), h.get("index_closes"), h.get("beta")),
            "benchmark": h.get("benchmark"),
            "next_event": {"date": long_date(upcoming[0][0]), "event": upcoming[0][1]} if upcoming else None,
            "expected_yearly_dividends": money(r["dividends"], base),
        }

    # --- D:portfolio ---
    pnl_total = sum(r["pnl"] for r in rows if r["pnl"] is not None)
    day_total = sum(r["day_change"] for r in rows if r["day_change"] is not None)
    facts["D:portfolio"] = {
        "net_liquidation": money(account.get("net_liquidation"), base),
        "cash": money(account.get("cash"), base),
        "holdings_value": money(invested, base),
        "number_of_holdings": len(rows),
        "unrealised_gain_or_loss": money(pnl_total, base, signed=True),
        "unrealised_gain_or_loss_pct": pct(pnl_total / (invested - pnl_total) * 100) if invested - pnl_total else None,
        "change_today": money(day_total, base, signed=True),
        "change_today_pct": pct(day_total / (invested - day_total) * 100) if invested - day_total else None,
    }

    # --- D:allocation ---
    def group(key):
        groups = {}
        for r in rows:
            name = key(r) or "Unknown"
            groups[name] = groups.get(name, 0) + r["value"]
        return groups

    by_currency = group(lambda r: r["p"]["currency"])
    by_sector = group(lambda r: r["h"].get("sector"))
    facts["D:allocation"] = {
        "basis": f"% of the holdings' value ({money(invested, base)}), in {base}",
        "by_holding": {r["p"]["symbol"]: pct(weight[r["p"]["con_id"]], 1) for r in sorted(rows, key=lambda r: -r["value"])},
        "by_market": _shares(group(lambda r: market_of(r["p"])), invested),
        "by_currency": _shares(by_currency, invested),
        "by_sector": _shares(by_sector, invested),
        "cash_pct_of_net_liquidation": pct(account["cash"] / account["net_liquidation"] * 100, 1)
        if account.get("cash") is not None and account.get("net_liquidation") else None,
    }

    # --- D:pnl: biggest contributors to the gain or loss since purchase, and today ---
    with_pnl = [r for r in rows if r["pnl"] is not None]
    facts["D:pnl"] = {
        "since_purchase_biggest_gains": [{"holding": holding_id(r["p"]["con_id"]), "amount": money(r["pnl"], base, signed=True)}
                                         for r in sorted(with_pnl, key=lambda r: -r["pnl"]) if r["pnl"] > 0][:3],
        "since_purchase_biggest_losses": [{"holding": holding_id(r["p"]["con_id"]), "amount": money(r["pnl"], base, signed=True)}
                                          for r in sorted(with_pnl, key=lambda r: r["pnl"]) if r["pnl"] < 0][:3],
        "today_biggest_moves": [{"holding": holding_id(r["p"]["con_id"]), "amount": money(r["day_change"], base, signed=True)}
                                for r in sorted((r for r in rows if r["day_change"] is not None), key=lambda r: -abs(r["day_change"]))][:3],
    }

    # --- D:market_moves ---
    facts["D:market_moves"] = {
        "period": "the last month (21 trading sessions)",
        "method": "explained_by_market_pct = beta × benchmark_pct; rest_pct = stock_pct − explained_by_market_pct",
        "holdings": [{"holding": holding_id(r["p"]["con_id"]), **move}
                     for r in rows if (move := facts[holding_id(r["p"]["con_id"])]["last_month_vs_market"])],
    }

    # --- D:concentration ---
    ranked = sorted(rows, key=lambda r: -r["value"])
    flags = []
    for r in ranked:
        if weight[r["p"]["con_id"]] and weight[r["p"]["con_id"]] > SINGLE_STOCK_PCT:
            flags.append(f"{r['p']['symbol']} is {pct(weight[r['p']['con_id']], 1)}% of the holdings (above {SINGLE_STOCK_PCT}%)")
    for name, share in _shares(by_sector, invested).items():
        if name != "Unknown" and share > SECTOR_PCT:
            flags.append(f"{name} is {share}% of the holdings (above {SECTOR_PCT}%)")
    for name, share in _shares(by_currency, invested).items():
        if share > CURRENCY_PCT:
            flags.append(f"{name} is {share}% of the holdings (above {CURRENCY_PCT}%)")
    facts["D:concentration"] = {
        "largest": [{"holding": holding_id(r["p"]["con_id"]), "weight_pct": pct(weight[r["p"]["con_id"]], 1)} for r in ranked[:5]],
        "top_3_share_pct": pct(sum(weight[r["p"]["con_id"]] for r in ranked[:3]), 1) if rows else None,
        "flags": flags,
        "thresholds": f"single stock above {SINGLE_STOCK_PCT}%, sector above {SECTOR_PCT}%, currency above {CURRENCY_PCT}%",
    }

    # --- D:events ---
    events = sorted(
        ((day, r, label) for r in rows for day, label in (r["h"].get("events") or [])
         if today <= day <= today + timedelta(days=EVENTS_DAYS)),
        key=lambda e: (e[0], e[1]["p"]["symbol"], e[2]),  # same-day events: by symbol
    )
    facts["D:events"] = {
        "window": f"{long_date(today)} to {long_date(today + timedelta(days=EVENTS_DAYS))}",
        "upcoming": [{"date": long_date(day), "holding": holding_id(r["p"]["con_id"]), "event": label} for day, r, label in events],
    }

    # --- D:income ---
    paying = [r for r in rows if r["dividends"]]
    income_total = sum(r["dividends"] for r in paying)
    facts["D:income"] = {
        "basis": "Dividends per share with ex-dates in the last 12 months × shares held now; future dividends may differ",
        "expected_yearly_total": money(income_total, base),
        "yield_on_holdings_value_pct": pct(income_total / invested * 100) if invested else None,
        "by_holding": [{"holding": holding_id(r["p"]["con_id"]), "amount": money(r["dividends"], base)}
                       for r in sorted(paying, key=lambda r: -r["dividends"])],
    }

    facts["D:since_last"] = since_last(previous, facts)
    facts["D:missing"] = missing
    return facts


def since_last(previous, facts):
    """What changed since the previous portfolio summary, from its saved facts (money is saved as
    display strings, so it's parsed back)."""
    if not previous:
        return {"previous_summary": None, "note": "This is the first portfolio summary"}
    base = facts["base_currency"]
    then_portfolio, now_portfolio = previous.get("D:portfolio", {}), facts["D:portfolio"]

    def compare(key):
        old, new = parse_money(then_portfolio.get(key)), parse_money(now_portfolio.get(key))
        if old is None or new is None:
            return None
        return {"then": then_portfolio[key], "now": now_portfolio[key], "change": money(new - old, base, signed=True),
                "change_pct": pct(change_pct(new, old)) if old else None}

    held_then = {k: v["symbol"] for k, v in previous.items() if k.startswith("H:")}
    held_now = {k: v["symbol"] for k, v in facts.items() if k.startswith("H:")}
    weights_then = previous.get("D:allocation", {}).get("by_holding", {})
    weights_now = facts["D:allocation"]["by_holding"]
    weight_changes = []
    for key in held_now.keys() & held_then.keys():
        old, new = weights_then.get(held_then[key]), weights_now.get(held_now[key])
        if old is not None and new is not None and abs(new - old) >= WEIGHT_CHANGE_POINTS:
            weight_changes.append({"holding": key, "weight_then_pct": old, "weight_now_pct": new,
                                   "change_points": pct(new - old, 1)})
    weight_changes.sort(key=lambda c: -abs(c["change_points"]))
    same_currency = previous.get("base_currency") == base
    return {
        "previous_summary": previous.get("as_of_text"),
        "net_liquidation": compare("net_liquidation") if same_currency else None,
        "holdings_value": compare("holdings_value") if same_currency else None,
        "unrealised_gain_or_loss": compare("unrealised_gain_or_loss") if same_currency else None,
        "number_of_holdings": {"then": then_portfolio.get("number_of_holdings"), "now": now_portfolio["number_of_holdings"]},
        "holdings_added": [{"holding": key, "symbol": held_now[key]} for key in held_now if key not in held_then],
        # Sold holdings have no H: id in these facts any more, so they're named by symbol
        "holdings_sold": sorted(held_then[key] for key in held_then if key not in held_now),
        "weight_changes": weight_changes,
        "weight_change_threshold": f"changes of {WEIGHT_CHANGE_POINTS} percentage point or more",
        "note": None if same_currency else f"The base currency changed from {previous.get('base_currency')} to {base}; money isn't compared",
    }


def source_ids(facts):
    """Every id the model may cite."""
    return [key for key in facts if key.startswith(("D:", "H:"))]
