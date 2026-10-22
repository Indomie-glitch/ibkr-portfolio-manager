"""Exchange rates for the account (#270): units of the account's base currency per 1 unit of
another currency, e.g. 1.35 for USD on an SGD account.

IB's account ledger only has a rate for currencies the account holds cash in, so an SGD account
with no USD balance has none for USD. This finds one anyway, in this order:
  1. the ledger rate, if the caller has it
  2. an IB forex quote for the pair
  3. Yahoo Finance (e.g. USDSGD=X)
and keeps a looked-up rate for a few minutes. None means no source had a rate.

The sources are plain functions (ib_rate, yahoo_rate), and pair_symbol() is the Yahoo naming, so a
later daily rate series (#271) can reuse them.
"""
import asyncio
import math

from ib_async import Forex

import yahoo
from cache import cached
from ib_core import ib

TTL = 5 * 60  # seconds a looked-up rate is reused
IB_TIMEOUT = 4  # seconds to wait for IB's forex quote


class FxUnavailable(Exception):
    pass


def pair_symbol(currency, base):
    """Yahoo's symbol for 'base currency per 1 currency': USDSGD=X is SGD per US dollar."""
    return f"{currency}{base}=X"


def _price(ticker):
    """A usable rate from an IB forex ticker (midpoint of bid and ask, else last or close), or None."""
    if ticker is None:
        return None
    value = ticker.marketPrice()
    return value if isinstance(value, (int, float)) and math.isfinite(value) and value > 0 else None


async def ib_rate(currency, base):
    """IB's forex quote. IB lists each pair one way round (USD.SGD, but AUD.USD), so the other
    way round is tried too and turned upside down."""
    for pair, invert in ((currency + base, False), (base + currency, True)):
        contract = Forex(pair)
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified or qualified[0] is None:
            continue
        [ticker] = await asyncio.wait_for(ib.reqTickersAsync(contract), timeout=IB_TIMEOUT)
        price = _price(ticker)
        if price is not None:
            return 1 / price if invert else price
    return None


async def yahoo_rate(currency, base):
    return await yahoo.fetch_fx_rate(pair_symbol(currency, base))


async def _look_up(currency, base):
    for source in (ib_rate, yahoo_rate):
        try:
            rate = await source(currency, base)
        except Exception:
            continue  # this source failed; the next one may still have it
        if rate is not None and math.isfinite(rate) and rate > 0:
            return rate
    raise FxUnavailable(f"No exchange rate for {currency} to {base}")


async def rate_to_base(currency, base, ledger_rates=None):
    """Base currency per 1 unit of currency, or None when no source has it.
    ledger_rates: the {currency: rate} from IB's account ledger (GET /account's fx_rates)."""
    if currency == base:
        return 1.0
    ledger = (ledger_rates or {}).get(currency)
    if ledger:
        return ledger
    try:
        return await cached(("fx", currency, base), TTL, lambda: _look_up(currency, base))
    except FxUnavailable:
        return None


async def fill_missing(ledger_rates, currencies, base):
    """ledger_rates plus a rate for each of these currencies it lacks (when one can be found)."""
    rates = dict(ledger_rates)
    for currency in sorted({c for c in currencies if c}):
        if currency != base and not rates.get(currency):
            rate = await rate_to_base(currency, base)
            if rate is not None:
                rates[currency] = rate
    return rates
