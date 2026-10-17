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
