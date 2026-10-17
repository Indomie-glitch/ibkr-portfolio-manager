"""Trading guardrails (Milestone 6): whether this connection may place orders, and why not.

Read only is the default. Orders are only possible when TRADING_MODE allows them, the connection
was opened without readonly, and the logged-in account matches the mode: "paper" trades only on a
paper account; "live" also needs LIVE_TRADING_CONFIRM.
"""
import config

# Labels the app shows next to the mode badge
ACCOUNT_LABELS = {"paper": "Paper account", "live": "Live account", "unknown": "Account unknown"}


def account_kind(accounts):
    """Paper account IDs start with D (DU individual, DF advisor); live ones don't.
    "unknown" when not connected or the accounts are mixed."""
    accounts = [a for a in accounts or [] if a]
    if not accounts:
        return "unknown"
    paper = [a.upper().startswith("D") for a in accounts]
    if all(paper):
        return "paper"
    if not any(paper):
        return "live"
    return "unknown"


def status(accounts, connection_read_only, mode=None, live_confirmed=None):
    """What the app shows and what the order endpoints check (the same function, so they can't disagree)."""
    mode = mode or config.trading_mode()
    live_confirmed = config.live_trading_confirmed() if live_confirmed is None else live_confirmed
    kind = account_kind(accounts)

    if mode == "off":
        reason = "Trading is off: the app is read only."
    elif kind == "unknown":
        reason = "Trading is unavailable until the account type is known (connect to IB Gateway)."
    elif mode == "paper" and kind != "paper":
        reason = "Trading is set to paper only, but this is a live account."
    elif mode == "live" and not live_confirmed:
        reason = "Live trading isn't confirmed (LIVE_TRADING_CONFIRM)."
    elif connection_read_only:
        reason = "The connection to IB Gateway is read only. Restart the backend after changing TRADING_MODE."
    else:
        reason = None

    return {
        "mode": mode,
        "account": kind,
        "account_label": ACCOUNT_LABELS[kind],
        "can_trade": reason is None,
        "reason": reason,
        "max_order_value": config.max_order_value(),
    }


# ---------- order checks (shared by preview and placement) ----------

ACTIONS = ("BUY", "SELL")
ORDER_TYPES = ("MKT", "LMT")
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
    """The ib_async order: a day order, regular trading hours only."""
    from ib_async import LimitOrder, MarketOrder
    if order["order_type"] == "LMT":
        ib_order = LimitOrder(order["action"], order["quantity"], round(order["limit_price"], 4))
    else:
        ib_order = MarketOrder(order["action"], order["quantity"])
    ib_order.tif = "DAY"
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
            round(float(order["limit_price"]), 4) if order["order_type"] == "LMT" else None)


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
