"""Borrowing safeguard (#289): would a buy borrow from IBKR, and is borrowing allowed?

IBKR accounts are margin accounts, so instead of rejecting an order IBKR quietly lends the money.
Two ways that happens:
- not enough cash: the order costs more than the cash in that currency (a margin loan);
- wrong currency: buying a US stock with no USD cash. IBKR doesn't convert AUD or SGD for you; it
  leaves a negative USD balance, which is a USD loan.
Both come down to one test: the buy's cost (plus fees) against the cash in the stock's own currency
($LEDGER-CashBalance from GET /account). IB's what-if preview doesn't report this (its answer was
empty on paper), so it is worked out here.

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


def borrow_needed(action, value, currency, cash_by_currency, base):
    """How much a buy would borrow, or None. value: the order's value in the stock's currency.
    cash_by_currency: {currency: cash balance} (a currency missing has none; a negative balance is
    already a loan, so none of it is available). Sells are never checked: they add cash."""
    if action != "BUY" or value is None:
        return None
    cost = value + fee_allowance(value)
    available = max(cash_by_currency.get(currency, 0.0), 0.0)
    if cost <= available:
        return None
    base_cash = max(cash_by_currency.get(base, 0.0), 0.0)
    return {
        "currency": currency,
        "amount": round(cost - available, 2),
        "cost": round(cost, 2),
        "available": round(available, 2),
        # "currency": the account has cash, but not in this currency (convert first);
        # "cash": there isn't enough cash at all (lower the quantity)
        "reason": "currency" if currency != base and available < cost and base_cash > 0 else "cash",
    }


def _money(amount, currency):
    return f"{amount:,.2f} {currency}"


def borrow_message(borrow, base, blocked):
    """The plain words the order ticket shows."""
    amount = _money(borrow["amount"], borrow["currency"])
    if borrow["reason"] == "currency":
        held = "no" if borrow["available"] <= 0 else f"only {_money(borrow['available'], borrow['currency'])} in"
        what = (f"This order would borrow about {amount} from IBKR: the account has {held} "
                f"{borrow['currency']} cash, and IBKR doesn't convert your {base} automatically.")
        fix = f"Lower the quantity, or convert {base} to {borrow['currency']} in IBKR first."
    else:
        what = (f"This order would borrow about {amount} from IBKR: it costs about "
                f"{_money(borrow['cost'], borrow['currency'])} with fees, and the account has "
                f"{_money(borrow['available'], borrow['currency'])} cash in {borrow['currency']}.")
        fix = "Lower the quantity, or add cash first."
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
