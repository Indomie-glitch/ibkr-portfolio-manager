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

## 2. Covariance and correlation: how holdings move together

### Covariance

The *covariance* of two holdings says whether they tend to be above their own average on the same
days:

$$\text{cov}(A, B) = \frac{1}{n-1} \sum_{t=1}^{n} (a_t - \bar a)(b_t - \bar b)$$

- $a_t$, $b_t$: the two holdings' daily returns on day $t$
- $\bar a$, $\bar b$: their average daily returns over the period
- $n$: the number of days. Dividing by $n - 1$ rather than $n$ (the *sample* covariance) corrects for
  the averages themselves being estimated from the same days.

Positive means they usually move together, negative means they usually move in opposite directions.
The covariance of a holding with itself is its *variance*, the square of its daily swing.

Putting every pair in a table gives the **covariance matrix** $\Sigma$ (sigma): row $i$, column $j$ is
$\text{cov}(i, j)$, and the diagonal holds each variance. It's the base for risk contribution (who
causes the portfolio's swings), Value at Risk, the hidden factors and the example mixes, because the
portfolio's variance for weights $w$ is $w^\top \Sigma w$ (section 4 explains it).

### Correlation

Covariance depends on how much each holding swings, so it's hard to read. The *correlation* divides
that out, leaving a number from −1 to +1:

$$\rho_{AB} = \frac{\text{cov}(A, B)}{\sigma_A \, \sigma_B}$$

- $\sigma_A = \sqrt{\text{cov}(A, A)}$: holding A's daily standard deviation

**+1** means they always move together in proportion, **0** means no straight-line relationship, and
**−1** means they always move opposite. A holding whose price never moved has no correlation with
anything and shows as 0.

**Example.** Three days of returns: A = +2%, 0%, −2% and B = +1%, +1%, −2%. Both average 0%.

- var(A) = (0.02² + 0² + 0.02²) ÷ 2 = 0.0004, so $\sigma_A$ = 2.0% a day
- var(B) = (0.01² + 0.01² + 0.02²) ÷ 2 = 0.0003, so $\sigma_B$ = 1.73%
- cov(A, B) = (0.02 × 0.01 + 0 × 0.01 + (−0.02) × (−0.02)) ÷ 2 = 0.0003
- correlation = 0.0003 ÷ √(0.0004 × 0.0003) = 3 ÷ √12 = **+0.87**: they mostly move together.

### Same direction share

The hover text on the heatmap gives a plainer measure: the share of days both holdings moved the same
way (both up or both down), counting only days on which both moved. In the example, A didn't move on
day 2, so only days 1 and 3 count, and they moved the same way on both: **100%**. Two holdings with a
correlation near 0 move the same way on about half the days.

### The summary numbers

- **Most related pair** and **least related pair**: the highest and lowest correlation of all pairs.
- **Average correlation**: the mean over every pair (each pair counted once). Lower means the holdings
  offset each other more, which steadies the portfolio.

### Why ASX and US holdings look less related than they are

The ASX closes at 4 pm Sydney time, before the US market opens. News that moves both markets on a US
afternoon shows up in US prices that day but in Australian prices only the next day. Daily returns
compare the same calendar day, so part of the shared movement lands on different days and the
measured correlation between an Australian and a US holding comes out lower than the real
relationship. Weekly returns would reduce this, but they leave far fewer data points in a 3-month or
1-year window, so the app uses daily returns and notes the effect here.

## 3. Volatility, beta and the biggest fall

### Volatility

*Volatility* is how much something typically swings in a year: the standard deviation of its daily
returns, scaled to a year (section 1, "From daily to yearly"):

$$\sigma = \sqrt{\frac{1}{n-1}\sum_{t=1}^{n}(r_t - \bar r)^2} \times \sqrt{252}$$

- $r_t$: the daily return on day $t$ (in AUD for holdings and the portfolio)
- $\bar r$: the average daily return over the period

Roughly two years in three end within one volatility of the average, so a portfolio with 20%
volatility and A$50,000 in shares would typically end a year within about A$10,000 of where it would
on average.

**Example.** Daily returns of +1%, −1%, +1%, −1%. The average is 0, the squared differences add up to
4 × 0.0001 = 0.0004, divided by n − 1 = 3 gives 0.000133, and the square root is **1.15% a day**.
× √252 = × 15.87 gives **18.3% a year**.

### The portfolio's daily return

The portfolio's return on a day is each holding's return weighted by its share of the money:

$$r_{p,t} = \sum_i w_i \, r_{i,t}$$

**Example.** 75% in a stock that rose 2% and 25% in one that fell 4%: 0.75 × 2% + 0.25 × (−4%) =
1.5% − 1% = **+0.5%**.

The weights are **today's**, applied to every day in the period. So the portfolio figures answer "how
would the holdings I have now have behaved over the last year?", not "how did my account do?", which
would also depend on what was bought and sold along the way.

### Beta

*Beta* says how much something moves when a market index moves:

$$\beta = \frac{\text{cov}(r, m)}{\text{var}(m)}$$

- $r$: the daily returns of the holding (or portfolio)
- $m$: the daily returns of the index (the ASX 200 or the S&P 500, total return)

A beta of 1 means it moves in step with the index on average, 1.2 means about 12% when the index moves
10%, 0.5 about 5%, and 0 means its moves are unrelated to the index's. A beta above 1 is shown in
amber.

- **Each holding** is compared with its **home** index: Australian shares with the ASX 200, US shares
  with the S&P 500. A US share's beta uses its **US dollar** returns, so changes in the exchange rate
  (which have nothing to do with how the share follows its market) don't blur it.
- **The portfolio** is compared with both indexes, using its AUD returns and each index as quoted.

**Example.** An index moves +1%, −1%, +1%, −1% and a stock moves exactly twice as much: +2%, −2%, +2%,
−2%. Its covariance with the index is twice the index's variance, so its beta is **2**. A stock that
moved +1%, +1%, −1%, −1% on those days rose and fell independently of the index: covariance 0, beta
**0**.

### Maximum drawdown

The *maximum drawdown* is the largest fall from a high to a later low. Grow A$1 by the daily returns,
keep track of the highest value so far, and find the deepest fall below it:

$$V_t = \prod_{s \le t}(1 + r_{p,s}), \qquad \text{drawdown}_t = \frac{V_t}{\max_{s \le t} V_s} - 1$$

The maximum drawdown is the most negative drawdown, with the date of the high before it (*peak*) and
of the low (*trough*). The A$ figure is that fall applied to today's value of the holdings.

**Example.** Daily returns +10%, −20%, +5%, −10%, +30%. The value goes 1 → 1.10 → 0.88 → 0.924 →
0.832 → 1.081. The high is 1.10 after day 1 and the lowest point after it is 0.832 after day 4:
0.832 ÷ 1.10 − 1 = **−24.4%**. The value later recovers above 1.10, but the drawdown still counts,
because it's the worst fall you'd have sat through.

## 4. Concentration: share of money vs share of risk

### Share of money

Each holding's weight $w_i$ (section 1). **Top 3 share** adds the three largest weights, and
**largest** is the biggest single weight.

### Share of risk (risk contribution)

The portfolio's variance (its squared daily swing) can be written with the covariance matrix
$\Sigma$ from section 2:

$$\sigma_p^2 = w^\top \Sigma w = \sum_i w_i (\Sigma w)_i$$

- $(\Sigma w)_i = \sum_j \Sigma_{ij} w_j$: how holding $i$ moves together with the whole portfolio,
  including with itself

Each term $w_i (\Sigma w)_i$ is the part of the variance that comes from holding $i$, so its share is:

$$\text{RC}_i = \frac{w_i (\Sigma w)_i}{w^\top \Sigma w}, \qquad \sum_i \text{RC}_i = 100\%$$

A holding's share of risk is bigger than its share of money when it swings more than the others, or
moves with them so they don't offset it. It's smaller when it's calm, or moves against the rest. It
can even be negative: a holding that tends to rise when the others fall steadies the portfolio.

**Example.** Two unrelated holdings, one swinging 20% a year and one 10%, so (in yearly terms)
$\Sigma$ = [[0.04, 0], [0, 0.01]], with half the money in each.

- $\Sigma w$ = (0.04 × 0.5, 0.01 × 0.5) = (0.02, 0.005)
- $w^\top \Sigma w$ = 0.5 × 0.02 + 0.5 × 0.005 = 0.0125 (a portfolio volatility of √0.0125 = 11.2%)
- shares of risk: 0.5 × 0.02 ÷ 0.0125 = **80%** and 0.5 × 0.005 ÷ 0.0125 = **20%**

Half the money, but four fifths of the swings come from the more volatile holding. (The app uses daily
covariances; scaling $\Sigma$ to a year multiplies the top and bottom by the same 252, so the shares
are the same.)

### Effective holdings

How many equally sized holdings the portfolio behaves like:

$$N_{\text{eff}} = \frac{1}{\sum_i w_i^2}$$

$\sum w_i^2$ is the *Herfindahl index*, a standard measure of concentration. With $n$ equal holdings
each $w_i = 1/n$, so $\sum w_i^2 = 1/n$ and $N_{\text{eff}} = n$. One big holding dominates the sum of
squares, which pulls the number down.

**Example.** Weights 68.2%, 21.3%, 8.3%, 1.6% and 0.7%: the squares add up to 0.465 + 0.045 + 0.007 +
0.0003 + 0.00005 = 0.518, so $N_{\text{eff}}$ = 1 ÷ 0.518 = **1.9**. Five stocks that behave like
about two.

### Warnings

A warning shows when one stock is over **20%** of the holdings, one sector over **40%**, or one
currency over **80%**. These are the same levels the AI portfolio summary uses (`portfolio_facts.py`),
so the two always flag the same things. Sectors come from each company's Yahoo profile; holdings
without one aren't counted towards any sector.

## 5. Currency effect on US holdings

A US share earns you two things at once in Australian dollars: its price change in US dollars, and the
change in what a US dollar is worth in AUD (section 1). Over a whole period each compounds day by day:

$$r^{USD} = \prod_t (1 + r^{USD}_t) - 1, \qquad r^{FX} = \prod_t (1 + r^{FX}_t) - 1$$

and they combine the same way as on a single day:

$$1 + r^{AUD} = (1 + r^{USD})(1 + r^{FX})$$

*Compounding* means each day's return applies to the value after the day before: +10% then −10% is
1.1 × 0.9 − 1 = **−1%**, not 0%.

### In dollars

The currency effect in A$ answers: how much more (or less) are my US holdings worth today than they
would be if the exchange rate hadn't moved over the period? At the old rate, today's value $V$ would be
$V / (1 + r^{FX})$, so:

$$\text{effect} = V - \frac{V}{1 + r^{FX}} = V \times \frac{r^{FX}}{1 + r^{FX}}$$

The panel's total adds this up over every US holding. Like the other figures, it uses today's
holdings over the whole period.

**Example.** A US share rose **+20%** in US dollars over the year, while a US dollar lost 5% against
the Australian dollar twice in a row: $r^{FX}$ = 0.95 × 0.95 − 1 = **−9.75%**. In AUD the share
returned 1.20 × 0.9025 − 1 = **+8.3%**. If it's worth A$10,830 today, at the old exchange rate it would
be worth 10,830 ÷ 0.9025 = A$12,000, so the stronger Australian dollar cost **A$1,170**.
