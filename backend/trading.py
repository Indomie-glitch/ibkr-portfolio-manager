"""Trading guardrails (Milestone 6): whether orders can be placed, and the checks every order passes.

Trading is on for any connected account, paper or live; the toolbar badge shows which one. Every
order is previewed (IBKR what-if) and placed with a single-use confirmation token, and the server
checks whole shares, no short selling and MAX_ORDER_VALUE before sending it.
"""
import config

# Labels for the toolbar badge
ACCOUNT_LABELS = {"paper": "Paper account", "live": "Live account", "unknown": "Account unknown"}


def account_kind(accounts):
    """Paper account IDs start with D (DU individual, DF advisor); live ones don't. Any live
    account among several makes it "live". "unknown" when not connected."""
    accounts = [a for a in accounts or [] if a]
    if not accounts:
        return "unknown"
    return "paper" if all(a.upper().startswith("D") for a in accounts) else "live"


def status(accounts):
    """What the app shows and what the order endpoints check (the same function, so they can't disagree)."""
    kind = account_kind(accounts)
    reason = "Trading is unavailable until IB Gateway is connected." if kind == "unknown" else None

    return {
        "account": kind,
        "account_label": ACCOUNT_LABELS[kind],
        "can_trade": reason is None,
        "reason": reason,
        "max_order_value": config.max_order_value(),
    }


# ---------- order checks (shared by preview and placement) ----------

ACTIONS = ("BUY", "SELL")
ORDER_TYPES = ("MKT", "LMT")
# Time in force: good for the day, or good till cancelled
TIFS = ("DAY", "GTC")
# IB's "no value" for doubles
UNSET = 1.7976931348623157e308


def check_order(order, price, fx_rate, held_quantity, trading_status):
    """Problems that stop an order, in plain words (empty when it may go ahead), and its estimated
    value. order: {action, quantity, order_type, limit_price}. price: the limit price, or the last
    price for a market order (None if unknown). fx_rate: order currency -> base currency."""
    problems = []
    if not trading_status["can_trade"]:
        problems.append(trading_status["reason"])
    if order["action"] not in ACTIONS:
        problems.append("Choose Buy or Sell.")
    if order.get("tif", "DAY") not in TIFS:
        problems.append("Choose Day or Good till cancelled.")
    if order["order_type"] not in ORDER_TYPES:
        problems.append("Choose a market or limit order.")
    quantity = order["quantity"]
    if not quantity or quantity <= 0 or quantity != int(quantity):
        problems.append("Enter a whole number of shares.")
    if order["order_type"] == "LMT" and not (order.get("limit_price") or 0) > 0:
        problems.append("Enter a limit price above zero.")
    if order["action"] == "SELL" and quantity and quantity > (held_quantity or 0):
        # No short selling: only shares you hold can be sold
        problems.append(f"You can sell at most {held_quantity or 0:g} shares (the number you hold).")

    value = price * quantity if price is not None and quantity and quantity > 0 else None
    value_base = value * fx_rate if value is not None and fx_rate is not None else None
    limit = trading_status["max_order_value"]
    if value is None:
        problems.append("The order's value can't be worked out without a current price.")
    elif value_base is None:
        problems.append("The order's value can't be checked against the limit without an exchange rate.")
    elif value_base > limit:
        problems.append(f"The order is worth about {value_base:,.2f} in the account's currency, above the "
                        f"{limit:,.0f} limit (MAX_ORDER_VALUE).")
    return problems, value, value_base


def build_order(order):
    """The ib_async order: Day (default) or GTC, regular trading hours only."""
    from ib_async import LimitOrder, MarketOrder
    if order["order_type"] == "LMT":
        ib_order = LimitOrder(order["action"], order["quantity"], round(order["limit_price"], 4))
    else:
        ib_order = MarketOrder(order["action"], order["quantity"])
    ib_order.tif = order.get("tif") or "DAY"
    ib_order.outsideRth = False
    return ib_order


def _number(value):
    """OrderState numbers arrive as strings or IB's 'unset' double."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number >= UNSET or number != number else number


def what_if_summary(state):
    """The parts of IB's what-if answer the confirmation sheet shows."""
    return {
        "commission": _number(state.commission),
        "min_commission": _number(state.minCommission),
        "max_commission": _number(state.maxCommission),
        "commission_currency": state.commissionCurrency or None,
        "init_margin_change": _number(state.initMarginChange),
        "maint_margin_change": _number(state.maintMarginChange),
        "equity_with_loan_change": _number(state.equityWithLoanChange),
        "warning": state.warningText or None,
    }


# ---------- confirmation tokens: an order is only placed after its preview was shown ----------

TOKEN_LIFETIME_S = 120


def _order_key(con_id, order):
    """The parts of an order the confirmation covers: any change needs a new preview."""
    return (con_id, order["action"], float(order["quantity"]), order["order_type"],
            round(float(order["limit_price"]), 4) if order["order_type"] == "LMT" else None,
            order.get("tif") or "DAY")


class ConfirmationTokens:
    """Single-use tokens issued with a preview that can submit. Placing an order needs the token
    for exactly that order, within TOKEN_LIFETIME_S; a token works once (so a double click can't
    place two orders). Held in memory only."""

    def __init__(self, lifetime_s=TOKEN_LIFETIME_S):
        self.lifetime_s = lifetime_s
        self._tokens = {}

    def issue(self, con_id, order, now):
        import secrets
        self._drop_expired(now)
        token = secrets.token_urlsafe(24)
        self._tokens[token] = (_order_key(con_id, order), now + self.lifetime_s)
        return token

    def redeem(self, token, con_id, order, now):
        """Uses up the token. Returns None if it's valid for this order, otherwise the problem."""
        self._drop_expired(now)
        entry = self._tokens.pop(token or "", None)
        if entry is None:
            return "This confirmation has expired or was already used. Review the order again."
        key, _ = entry
        if key != _order_key(con_id, order):
            return "The order changed after it was reviewed. Review it again."
        return None

    def _drop_expired(self, now):
        for token in [t for t, (_, expires) in self._tokens.items() if expires <= now]:
            del self._tokens[token]


# ---------- open orders and today's history (GET /orders) ----------

DONE_STATUSES = ("Filled", "Cancelled", "ApiCancelled", "Inactive")


def _number_or_none(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number >= UNSET or number != number else number


def order_row(trade, names, fills=()):
    """One row of the Orders page. fills: this order's executions (for the average price, the
    commission and the time when the order itself doesn't have them)."""
    order, contract, status = trade.order, trade.contract, trade.orderStatus
    shares = sum(f.execution.shares for f in fills)
    avg = (sum(f.execution.shares * f.execution.price for f in fills) / shares) if shares else _number_or_none(status.avgFillPrice)
    commissions = [_number_or_none(f.commissionReport.commission) for f in fills if f.commissionReport]
    commissions = [c for c in commissions if c is not None]
    # IBKR's order lists have no placement time. ib_async starts the log of an order it placed itself
    # with a PendingSubmit entry at that moment; an order learned from IBKR (TWS, mobile, an earlier
    # session) starts with whenever the app first heard of it, so its time isn't shown (#157)
    first = trade.log[0] if trade.log else None
    placed = first.time if first and first.status == "PendingSubmit" else None
    return {
        "order_id": order.orderId or None, "perm_id": order.permId or None,
        "con_id": contract.conId, "symbol": contract.symbol, "name": names.get(contract.conId),
        "currency": contract.currency, "action": order.action, "quantity": _number_or_none(order.totalQuantity),
        "filled": shares or _number_or_none(status.filled) or 0, "order_type": order.orderType,
        "tif": order.tif or "DAY", "limit_price": _number_or_none(order.lmtPrice) if order.orderType == "LMT" else None,
        "avg_fill_price": avg, "commission": sum(commissions) if commissions else None,
        "status": status.status, "placed": placed.isoformat() if placed else None,
    }


def orders_overview(open_trades, completed, fills, names):
    """{open, filled_today, cancelled} for the Orders page.
    open_trades: reqAllOpenOrders; completed: reqCompletedOrders (IB keeps them for the current
    day; ib_async gives no completion time); fills: reqExecutions (today's executions)."""
    from ib_async import Order, OrderStatus, Trade

    fills_by_perm = {}
    for fill in fills:
        fills_by_perm.setdefault(fill.execution.permId, []).append(fill)
    known = {t.order.permId: t for t in [*completed, *open_trades] if t.order.permId}

    open_rows = [order_row(t, names, fills_by_perm.get(t.order.permId, ()))
                 for t in open_trades if t.orderStatus.status not in DONE_STATUSES]

    filled_today = []
    open_perms = {t.order.permId for t in open_trades if t.orderStatus.status not in DONE_STATUSES}
    for perm_id, order_fills in fills_by_perm.items():
        if perm_id in open_perms:
            continue  # partly filled: still listed as open
        trade = known.get(perm_id)
        if trade is None:
            # An order IB no longer lists: rebuild what the executions say
            first = order_fills[0]
            trade = Trade(contract=first.contract,
                          order=Order(orderId=first.execution.orderId, permId=perm_id,
                                      action="BUY" if first.execution.side == "BOT" else "SELL",
                                      totalQuantity=sum(f.execution.shares for f in order_fills), orderType=""),
                          orderStatus=OrderStatus(status="Filled"))
        row = order_row(trade, names, order_fills)
        row["status"] = "Filled"
        filled_today.append(row)

    cancelled = [order_row(t, names, fills_by_perm.get(t.order.permId, ()))
                 for t in completed if t.orderStatus.status in ("Cancelled", "ApiCancelled")]
    newest_first = lambda rows: sorted(rows, key=lambda r: r["placed"] or "", reverse=True)  # noqa: E731
    return {"open": newest_first(open_rows), "filled_today": newest_first(filled_today), "cancelled": newest_first(cancelled)}
