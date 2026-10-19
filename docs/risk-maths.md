# Risk maths

How every number on the Risk page is worked out. Each section has the formula, what each symbol means,
why it's done that way, and a worked example with small numbers you can check by hand. The code is in
`backend/risk.py` (pure maths) and `backend/risk_data.py` (getting the prices); the tests in
`backend/tests/test_risk_*.py` use the same small examples.

Everything here describes your holdings. None of it says what to buy or sell.

## 1. Daily returns in Australian dollars

Every other section starts from one table: for each trading day in the period, how much each holding's
value changed that day, measured in Australian dollars.

### Prices

- **Stocks:** daily closing prices from Yahoo Finance, *dividend-adjusted*. When a company pays a
  dividend its share price drops by about the dividend, even though the owner didn't lose anything.
  Yahoo adjusts the earlier prices down so that drop doesn't look like a loss, which means returns
  include dividends (a *total return*).
- **Markets:** the S&P/ASX 200 and the S&P 500 as *total return indexes* (`^AXJT`, `^SP500TR`): the
  index with dividends reinvested, so both sides of every comparison include dividends. If Yahoo has no
  total return series, the price index (`^AXJO`, `^GSPC`) is used instead and the page says so.
- **Exchange rate:** `AUDUSD=X`, the number of US dollars one Australian dollar buys (for example 0.65).

Prices are kept in `risk_prices.sqlite`. Yahoo is asked at most once a day per symbol, and only for the
days not stored yet, plus the last two weeks again: after each dividend Yahoo rewrites a stock's past
adjusted prices, and if the stored ones no longer match, the whole history is fetched again.

### US prices in Australian dollars

A US share's price in AUD is its US price divided by that day's rate:

$$P^{AUD}_t = \frac{P^{USD}_t}{x_t}$$

- $P^{USD}_t$: the share's US dollar close on day $t$
- $x_t$: the AUDUSD rate on day $t$ (US dollars per Australian dollar)

**Example.** A share is US$100 and the rate is 0.65, so it's worth 100 ÷ 0.65 = **A$153.85**. The next
day it's US$102 and the rate is 0.66: 102 ÷ 0.66 = **A$154.55**.

### Daily return

The *simple daily return* is how much the value changed, as a share of yesterday's value:

$$r_t = \frac{P_t}{P_{t-1}} - 1$$

**Example (continued).** In US dollars the share rose 102 ÷ 100 − 1 = **+2.00%**. In Australian dollars
it rose only 154.55 ÷ 153.85 − 1 = **+0.45%**, because the Australian dollar got stronger.

### The two parts: price and currency

The AUD return is the US price return combined with the change in what a US dollar is worth in AUD:

$$1 + r^{AUD} = (1 + r^{USD})(1 + r^{FX}), \qquad r^{FX}_t = \frac{x_{t-1}}{x_t} - 1$$

- $r^{USD}$: the share's return in US dollars
- $r^{FX}$: the return of holding one US dollar, measured in AUD. A US dollar is worth $1/x$ Australian
  dollars, so when $x$ goes up (a stronger Australian dollar) a US dollar is worth less and $r^{FX}$ is
  negative.

**Example (continued).** $r^{FX}$ = 0.65 ÷ 0.66 − 1 = **−1.52%**, and (1 + 0.02) × (1 − 0.0152) − 1 =
**+0.45%**, the same answer as above. The Currency effect panel splits returns into these two parts.

### Lining up the days

The ASX and the US markets have different holidays (Australia Day, Thanksgiving…). A day only counts
if **every** series has a close that day: each holding, both indexes and the exchange rate. Days where
anything is missing are dropped, and the page says how many days were used. A year has about 252
trading days on each market, but only about 244 that both share.

Why drop them rather than fill them in: filling a missing close with the day before's would show a 0%
day followed by a two-day move, which makes a holding look calmer and less related to the others than
it is.

### Periods and holdings left out

The period buttons choose the window: **3M** (3 months), **1Y** (1 year, the default) or **3Y**
(3 years), ending at the latest close.

A holding whose prices start more than a week after the window starts (it was listed or bought into a
new company recently) is **left out** of every calculation and listed in the Data notes row, rather
than shortening the window for everything else. Holdings in currencies other than AUD and USD are left
out too.

### Weights

A holding's *weight* is its share of the AUD market value of the stocks included:

$$w_i = \frac{V_i}{\sum_j V_j}$$

- $V_i$: today's market value of holding $i$ in AUD (US holdings converted at the latest rate)

Cash isn't a stock and doesn't move with the market, so it's left out of the weights (the Exposure and
Optimisation panels show it separately).

**Example.** BHP worth A$3,000 and Apple worth US$650 at a rate of 0.66 (A$984.85): BHP's weight is
3,000 ÷ 3,984.85 = **75.3%**, Apple's **24.7%**.

### From daily to yearly

Yearly figures assume **252 trading days** a year. Returns add up over days, but swings (standard
deviations) grow with the *square root* of time, because up and down days partly cancel out:

$$\sigma_{year} = \sigma_{day} \times \sqrt{252} \approx \sigma_{day} \times 15.87$$

**Example.** A holding that typically moves 1% a day typically moves about 1% × 15.87 = **15.9%** in a
year, not 252%.

### Risk-free rate

What cash would have earned, used by the Sharpe ratio and the example mixes: `RISK_FREE_RATE` in
`.env`, by default **4.60%** a year, the Reserve Bank of Australia's cash rate target since
29 September 2026.
