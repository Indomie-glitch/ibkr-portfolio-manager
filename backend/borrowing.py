"""Borrowing safeguard (#289): would a buy borrow from IBKR, and is borrowing allowed?

IBKR accounts are margin accounts, so instead of rejecting an order IBKR quietly lends the money.
Two ways that happens:
- not enough cash: the order costs more than the cash in that currency (a margin loan);
- wrong currency: buying a US stock with no USD cash. IBKR doesn't convert AUD or SGD for you; it
  leaves a negative USD balance, which is a USD loan.
Both come down to one test: the buy's cost (plus fees) against the cash in the stock's own currency
($LEDGER-CashBalance from GET /account), after taking off what open buy orders in that currency
will use when they fill (cash only drops at the fill, so without this two orders that each fit
would together borrow). IB's what-if preview doesn't report this (its answer was empty on paper),
so it is worked out here.

Blocking is on by default and saved per IBKR account. In the Mac app it can only be switched off
through the app (Touch ID or the Mac password, src-tauri/src/borrowing.rs), which sends the choice
over stdin (config.SETTINGS["allow_borrowing"]). In development it is saved in
DATA_DIR/trading_settings.json by POST /trading/borrowing after typing BORROW.
"""
import json

import config

# Fees aren't known before IB's what-if answer, so allow for them: the larger of a minimum (IBKR's
# fixed ASX minimum is A$6; US minimums are lower) and 0.1% of the order
FEE_MINIMUM = 6.0
FEE_SHARE = 0.001

SETTINGS_FILE = config.DATA_DIR / "trading_settings.json"


def fee_allowance(value):
    return max(FEE_MINIMUM, value * FEE_SHARE)


def reserved_by_open_buys(open_buys):
    """What open buy orders will use, per currency, fees included. open_buys: (currency, value)
    pairs, value = what is left to buy x price, in the stock's currency."""
    reserved = {}
    for currency, value in open_buys:
        reserved[currency] = reserved.get(currency, 0.0) + value + fee_allowance(value)
    return reserved


def borrow_needed(action, value, currency, cash_by_currency, base, reserved=None):
    """How much a buy would borrow, or None. value: the order's value in the stock's currency.
    cash_by_currency: {currency: cash balance} (a currency missing has none; a negative balance is
    already a loan, so none of it is available). reserved: {currency: what open buys will use}
    (reserved_by_open_buys). Sells are never checked: they add cash."""
    if action != "BUY" or value is None:
        return None
    reserved = reserved or {}
    cost = value + fee_allowance(value)
    held = max(cash_by_currency.get(currency, 0.0), 0.0)
    pending = reserved.get(currency, 0.0)
    available = max(held - pending, 0.0)
    if cost <= available:
        return None
    base_cash = max(cash_by_currency.get(base, 0.0), 0.0) - reserved.get(base, 0.0)
    return {
        "currency": currency,
        "amount": round(cost - available, 2),
        "cost": round(cost, 2),
        "available": round(available, 2),
        # What open buy orders in this currency will use (already taken off available)
        "reserved": round(min(pending, held), 2),
        # "currency": the account has cash, but not in this currency (convert first);
        # "cash": there isn't enough cash at all (lower the quantity)
        "reason": "currency" if currency != base and base_cash > 0 else "cash",
    }


def _money(amount, currency):
    return f"{amount:,.2f} {currency}"


def borrow_message(borrow, base, blocked):
    """The plain words the order ticket shows."""
    ccy = borrow["currency"]
    amount = _money(borrow["amount"], ccy)
    reserved = borrow.get("reserved", 0)
    if borrow["reason"] == "currency":
        if borrow["available"] <= 0 and not reserved:
            held = f"no {ccy} cash"
        elif reserved:
            held = (f"only {_money(borrow['available'], ccy)} of {ccy} cash left after "
                    f"{_money(reserved, ccy)} for your open buy orders")
        else:
            held = f"only {_money(borrow['available'], ccy)} in {ccy} cash"
        what = (f"This order would borrow about {amount} from IBKR: the account has {held}, "
                f"and IBKR doesn't convert your {base} automatically.")
        fix = f"Lower the quantity, or convert {base} to {ccy} in IBKR first."
    else:
        left = (f"{_money(borrow['available'], ccy)} left after {_money(reserved, ccy)} for your open buy orders"
                if reserved else f"{_money(borrow['available'], ccy)} in cash")
        what = (f"This order would borrow about {amount} from IBKR: it costs about "
                f"{_money(borrow['cost'], ccy)} with fees, and the account has {left}.")
        fix = ("Lower the quantity, add cash, or wait for your open orders to fill or cancel." if reserved
               else "Lower the quantity, or add cash first.")
    if blocked:
        return f"{what} {fix} (Block borrowing is on in Settings.)"
    return f"{what} IBKR charges interest on it daily until it's paid back."


def negative_balances(cash_by_currency):
    """Currencies the account already owes (a negative cash balance), for the Overview warning."""
    return [{"currency": currency, "amount": round(-cash, 2)}
            for currency, cash in sorted(cash_by_currency.items()) if cash < -0.005]


# ---------- the setting, per IBKR account ----------

def _saved():
    try:
        return json.loads(SETTINGS_FILE.read_text()).get("allow_borrowing", {})
    except (OSError, ValueError, AttributeError):
        return {}


def borrowing_allowed(account_id):
    """False (blocked) unless switched off for this account."""
    if not account_id:
        return False
    chosen = config.SETTINGS.get("allow_borrowing") if config.IN_APP else _saved()
    return bool((chosen or {}).get(account_id, False))


def save_allowed(account_id, allowed):
    """Development only: the app saves it in settings.json and sends it over stdin."""
    saved = _saved()
    saved[account_id] = bool(allowed)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps({"allow_borrowing": saved}, indent=2))
