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

## 6. Hidden factors (principal component analysis)

Five holdings give ten pairwise correlations, which is a lot to take in. *Principal component analysis*
(PCA) looks for a few shared patterns, called *factors*, that explain most of how the holdings move.
If two factors explain 70%, the portfolio behaves mostly like two things, whatever the number of
stocks.

### How it's done

1. **Standardise** each holding's daily returns: subtract its average and divide by its standard
   deviation, so a calm stock and a wild one count equally. The covariance matrix of standardised
   returns is the **correlation matrix** $R$ from section 2.
2. **Eigen decomposition** of $R$: find the directions $v_k$ (*eigenvectors*) and numbers
   $\lambda_k$ (*eigenvalues*) with
   $$R \, v_k = \lambda_k v_k$$
   Each eigenvector is a recipe mixing the holdings into one factor, and its eigenvalue is how much of
   the total variation that factor captures. The eigenvalues of a correlation matrix add up to the
   number of holdings $n$.
3. **Explained share:** factor $k$ explains $\lambda_k / n$ of how the holdings move. The factors are
   sorted from largest to smallest (F1, F2, …).
4. **Loadings:** $v_k \sqrt{\lambda_k}$, each holding's correlation with factor $k$. A loading near 1
   means the holding moves almost exactly with that factor; near 0, not at all; negative, against it.
5. **Names:** each factor's daily returns (the standardised returns mixed by its eigenvector) are
   compared with the ASX 200 and the S&P 500. If one of them correlates at least 0.5 with the
   factor, the factor is named after it: "Australian market", or for the US the main holding's
   industry and name, such as "US tech (Apple)". Otherwise it's named after the holding that loads on
   it most: "Mostly Apple".

An eigenvector and its negative describe the same pattern, so each factor's sign is chosen to make its
loadings add up to a positive number.

### Example

Two holdings with correlation $\rho$ have $R$ = [[1, ρ], [ρ, 1]]. Its eigenvectors are
(1, 1)/√2 (both moving together) and (1, −1)/√2 (one up, the other down), with eigenvalues
$1 + \rho$ and $1 - \rho$.

With $\rho$ = 0.87 (section 2's example), the first factor explains (1 + 0.87) ÷ 2 = **93%** of how the
pair moves, and each loads √(1.87 ÷ 2) = **0.97** on it. The second factor, their differences, explains
the remaining **7%**.

With three holdings, two of which move identically and a third that moves on its own, $R$ =
[[1, 1, 0], [1, 1, 0], [0, 0, 1]] has eigenvalues 2, 1 and 0. **Two factors explain 100%**: F1 (2/3)
is the pair, with loadings 1, 1, 0, and F2 (1/3) is the third holding, with loadings 0, 0, 1.

## 7. Sharpe ratio and tracking error

### Yearly return

The period's daily returns compound to a total growth $G = \prod_t (1 + r_t)$. The yearly rate that
grows to the same amount over $n$ trading days is:

$$r_{year} = G^{252/n} - 1$$

For the 1Y window ($n$ ≈ 252) that's simply the year's return. For 3M it's the 3-month return scaled
up to a year, which is jumpy: a good quarter looks like a spectacular year.

**Example.** 63 days (a quarter) that add up to +5%: at that pace a year would be
1.05^(252/63) − 1 = 1.05⁴ − 1 = **+21.6%**.

### Sharpe ratio

$$\text{Sharpe} = \frac{r_{year} - r_f}{\sigma}$$

- $r_f$: the *risk-free rate*, what cash would have earned (`RISK_FREE_RATE`, 4.60%)
- $\sigma$: the yearly volatility (section 3)

It's the extra return you got for each unit of swing you sat through. Cash has a Sharpe ratio of 0 by
definition. As a rough guide, the share market as a whole often lands somewhere around 0.3 to 0.6 over
long periods; a single year can be far higher or below zero. It's shown for the ASX 200 (total return)
over the same days for comparison.

**Example.** A return of 26.2% with 19.8% volatility: (26.2% − 4.6%) ÷ 19.8% = **1.09**.

### Tracking error

How far your returns drift from an index in a typical year: the volatility of the *difference*
between your daily return and the index's.

$$\text{TE} = \text{sd}(r_{p,t} - m_t) \times \sqrt{252}$$

A portfolio that copied the index exactly would have 0. Being steadily ahead or behind by the same
amount every day is also 0 — only the *variation* of the gap counts. A large tracking error isn't good
or bad by itself: it says your results won't look like the index's, in either direction.

The portfolio's AUD returns are compared with each index as quoted (the S&P 500 in US dollars), the
same choice as for the portfolio's betas (section 3).

**Example.** Daily gaps of +1%, −1%, +1%, −1%: their standard deviation is 1.15% a day, so the tracking
error is 1.15% × √252 = **18.3%** a year.

## 8. Value at Risk

*Value at Risk* (VaR) is a loss you'd expect to be exceeded only on rare bad days: at **95%**, on about
1 trading day in 20; at **99%**, on about 1 in 100. It's in A$ on today's holdings value, for one day
and for one month (21 trading days). It isn't the worst case: on those rare days the loss can be much
bigger.

### 1. Formula (parametric)

If daily portfolio returns follow a normal distribution with average 0 and standard deviation
$\sigma_p$, then 5% of days fall below $-1.645\,\sigma_p$ and 1% below $-2.326\,\sigma_p$:

$$\text{VaR} = -z \times \sigma_p \times \sqrt{\text{days}} \times V, \qquad \sigma_p = \sqrt{w^\top \Sigma w}$$

- $z$: 1.645 (95%) or 2.326 (99%), from the normal distribution's table
- $\sigma_p$: the portfolio's daily volatility from the covariance matrix (section 4)
- $\sqrt{\text{days}}$: a month of 21 days swings √21 ≈ 4.6 times as much as one day
- $V$: today's value of the holdings in AUD

**Example.** A$10,000 in two unrelated holdings, half each, swinging 2% and 1% a day:
$\sigma_p^2$ = 0.25 × 0.0004 + 0.25 × 0.0001 = 0.000125, so $\sigma_p$ = **1.12%** a day. 95% VaR =
1.645 × 1.12% × A$10,000 = **A$184** for a day, and × √21 = **A$843** for a month.

### 2. From history

No assumption about the shape of returns: take the actual daily portfolio returns in the period and
find the one that only 5% of days were worse than (the *5th percentile*). For a month, take every
overlapping run of 21 days (days 1–21, 2–22, …), compound each, and find their 5th percentile.

Real markets have more extreme days than a normal distribution allows (*fat tails*), so this figure is
often bigger than the formula's. With only a year of data it rests on the worst dozen or so days, so it
also jumps around more.

**Example.** Twenty days with returns −10%, −9%, …, +9%: the 5th percentile, interpolating between the
two worst days, is −10% + 0.95 × 1% = **−9.05%**.

### 3. Simulated (Monte Carlo)

Make up 10,000 possible days (or 21-day months) by drawing each holding's returns at random from a
normal distribution with the same covariance $\Sigma$ as the real ones, so holdings that moved together
still do. Combine them with the weights, compound the months, and take the 5th percentile of the
10,000 results. The random numbers start from a fixed *seed*, so the figure doesn't change every time
the page refreshes.

For one day it lands close to the formula (both assume normal returns); for a month, compounding
21 days makes it slightly different.

## 9. Stress tests

A stress test asks: what would happen to the holdings I have **today** if a past crash, or a simple
made-up shock, happened again? The impact is in A$ on today's holdings value, and the list is sorted
worst first.

### Replays of past crashes

| Scenario | From the close on or before | To the close on or before |
|---|---|---|
| GFC 2008 | 31 Aug 2008 | 9 Mar 2009 (the US market's low) |
| COVID crash | 19 Feb 2020 (the high) | 23 Mar 2020 (the low) |
| 2022 tech sell-off | 31 Dec 2021 | 30 Dec 2022 |

For each holding:

1. **Its own return over the period** (dividend-adjusted), if it had prices then.
2. Otherwise **its home index's return × its beta** (section 3), marked with * on the panel. A company
   listed in 2015 can't have fallen in 2008, but a stock like it would have moved with its market.
3. For US holdings, the AUD return adds the exchange rate over the same dates:
   $(1 + r^{USD})(1 + r^{FX}) - 1$, with $r^{FX} = 1 / (1 + r_{AUDUSD}) - 1$.

Then impact $= \sum_i V_i \times r_i$ with today's values $V_i$.

In a crash the Australian dollar usually falls, which softens the loss on US shares for an Australian
investor: in the GFC the AUDUSD rate fell about 26%, so a US dollar gained about 35% in AUD.

**Example.** A$6,000 of BHP fell 50%: −A$3,000. A$4,000 of a US stock with no prices then, beta 1,
while the S&P 500 fell 40%: −40% in US dollars. AUDUSD fell 25%, so a US dollar rose 1 ÷ 0.75 − 1 =
+33.3% in AUD, and the AUD return is 0.6 × 1.333 − 1 = −20%: −A$800. Total **−A$3,800**, 38% of
A$10,000.

The past returns are fetched once and kept: a dividend paid later lowers every earlier adjusted price
by the same factor, so a return between two past dates never changes.

### Shocks

- **Largest holding falls 20%**: −20% × its value.
- **S&P 500 falls 10%** / **ASX 200 falls 10%**: each holding in that market moves its beta × −10%;
  holdings in the other market don't move. The label shows the beta this works out to for the whole
  portfolio: impact ÷ (−10% × total).
- **AUD rises 10% against the USD**: each US dollar is then worth 1 ÷ 1.1 of what it was in AUD, so US
  holdings lose 1 − 1/1.1 = **9.09%** in AUD.

**Example.** A$6,000 of BHP (beta 2) and A$4,000 of a US stock (beta 1). ASX 200 −10%: 6,000 × 2 ×
−10% = **−A$1,200** (a whole-portfolio beta of 1.2). S&P 500 −10%: 4,000 × 1 × −10% = **−A$400**
(0.4). AUD +10%: 4,000 × −9.09% = **−A$364**.

The marker next to each percentage shows how big the hit is: red at 20% or more of the holdings, amber
from 10%, grey below.

## 10. Performance attribution vs the ASX 200

*Attribution* splits the difference between your return and the ASX 200's into the choices that
caused it. The holdings are grouped into two *segments*, Australia and the United States; the ASX 200
is the *benchmark*, which is 100% Australia.

### The symbols

- $w_{AU}$, $w_{US}$: the share of the holdings in each market (today's weights, adding up to 1)
- $r_{AU}$, $r_{US}$: those holdings' combined return over the period in their own currency
- $B$: the ASX 200's return (total return); $M$: the S&P 500's return in US dollars
- $F$: the return of one US dollar in AUD (section 1)

Each holding's return is compounded over the whole period (section 5), and the segment's return is the
weighted average of its holdings'.

### Your return and the three parts

$$R = w_{AU}\, r_{AU} + w_{US}\,[(1 + r_{US})(1 + F) - 1]$$

$$\underbrace{w_{US}(M - B)}_{\text{allocation}} + \underbrace{w_{AU}(r_{AU} - B) + w_{US}(r_{US} - M)}_{\text{selection}} + \underbrace{w_{US} F + w_{US}\, r_{US} F}_{\text{currency}} = R - B$$

- **Allocation**: what being in the US market instead of the Australian one did, if you'd simply held
  each market's index.
- **Selection**: how your stocks did against their own market's index.
- **Currency**: the exchange rate's effect on the money in US shares. The second term,
  $w_{US}\, r_{US} F$, is a small *cross term*: the currency move applied to the US gains themselves.
  It's included in Currency so the three parts add up exactly to the difference.

The parts are in *percentage points* (pts): the difference between two percentages, so 26.2% vs 9.5%
is 16.7 points, not 176%.

Because the weights are today's, held for the whole period, "your return" here is what today's mix
would have done, not your account's actual history.

### Example

40% in Australian shares that rose 12%, 60% in US shares that rose 30% in US dollars. The ASX 200 rose
10%, the S&P 500 20%, and a US dollar lost 5% in AUD.

- Your return: 0.4 × 12% + 0.6 × (1.30 × 0.95 − 1) = 4.8% + 0.6 × 23.5% = **18.9%**; difference
  **+8.9 pts**
- Allocation: 0.6 × (20% − 10%) = **+6.0 pts**
- Selection: 0.4 × (12% − 10%) + 0.6 × (30% − 20%) = 0.8 + 6.0 = **+6.8 pts**
- Currency: 0.6 × (−5%) + 0.6 × 30% × (−5%) = −3.0 − 0.9 = **−3.9 pts**
- Check: 6.0 + 6.8 − 3.9 = **8.9 pts** ✓

## 11. Example mixes and hedges

These show the trade-off between risk and return using **the same stocks** weighted differently over
the same period. They're examples worked out from past data, not a recommendation: none is labelled
best, and past results don't predict future ones.

For every mix, the daily return series is the holdings' returns combined with that mix's weights, and
volatility, yearly return and Sharpe ratio are worked out as in sections 3 and 7. So the "current mix"
row matches the tiles exactly.

### Largest holding capped at 40%

The largest holding is set to 40% and the excess is shared among the others **in proportion to their
weights**. If that pushes another one over 40%, it's capped too, and so on. With two holdings a 40% cap
is impossible (2 × 40% < 100%), so the row isn't shown, nor when nothing is over 40%.

**Example.** 60%, 30%, 10%: the 20% excess goes 3 : 1 to the other two, giving 45% and 15%. 45% is now
over, so its 5% excess goes to the last one: **40%, 40%, 20%**.

### Equal weights

$1/n$ in each.

### Lowest risk mix (minimum variance)

The weights $w$ that make the portfolio's variance $w^\top \Sigma w$ as small as possible, with every
weight between 0 and 1 (no borrowing or short selling) and the weights adding up to 1.

There's no simple formula once weights can't go negative, so it's found step by step by *projected
gradient descent*:

1. Start with equal weights.
2. Take a small step downhill: $w \leftarrow w - \eta \cdot 2\Sigma w$ ($2\Sigma w$ is the *gradient*, the
   direction in which the variance grows fastest; $\eta = 1 / (2\lambda_{max})$ with $\lambda_{max}$ the
   largest eigenvalue of $\Sigma$, small enough never to overshoot).
3. *Project* back to the nearest allowed weights: shift all weights by the same amount and set any
   negatives to 0, so they add up to 1 again.
4. Repeat until the weights stop changing.

**Example.** Two unrelated holdings with variances 0.04 and 0.01. Without the 0-to-1 rule, the answer
is known: weight each by 1 / its variance, so 25 : 100, giving **20%** and **80%**. Here both are already
between 0 and 1, so projected gradient descent lands on the same answer. When one holding only adds
risk, the rule stops its weight at 0 instead of going negative.

### Hedges

- **Currency hedge on US holdings**: the current mix with each US holding's US-dollar return in place
  of its AUD return, as if the exchange rate had been fixed. The A$ figure is the opposite of section
  5's currency effect: what hedging would have added (or cost) over the period. It leaves out the cost
  of hedging itself.
- **Cash or bonds**: cash doesn't move with the share market, so with a cash share $c$ of the whole
  account, the account swings about $(1 - c)$ times as much as the holdings. With 75% in cash, a 20%
  volatility in the shares is only about 5% for the whole account.

## 12. Bankruptcy risk: the Altman Z score

A quick financial-distress score from a company's latest **annual accounts**, published by Edward
Altman in 1968 for manufacturing companies:

$$Z = 1.2A + 1.4B + 3.3C + 0.6D + 1.0E$$

| Ratio | Formula | What it says |
|---|---|---|
| $A$ | working capital ÷ total assets | short-term cushion: current assets left after paying current debts |
| $B$ | retained earnings ÷ total assets | how much of the company was built from profits it kept |
| $C$ | EBIT ÷ total assets | how much the assets earn before interest and tax |
| $D$ | market value of the shares ÷ total liabilities | how far the share value could fall before debts exceed it |
| $E$ | revenue ÷ total assets | how hard the assets work to make sales |

The weights (1.2, 1.4, …) are the ones Altman fitted to tell companies that later failed from ones
that didn't. **Zones:** above 3 is *safe*, 1.8 to 3 a *grey zone*, below 1.8 *distress*. The bar on the
panel goes up to 10.

**Where it doesn't fit:**

- **Banks and other financial companies** (Yahoo sector Financial Services): borrowing and lending is
  their business, so their balance sheets look nothing like a manufacturer's. The panel says "Not used
  for banks".
- **Utilities and property companies** carry a lot of long-term debt by design, backed by steady
  income, so they often score low without being in trouble. They're marked with *.

The market value $D$ uses the share price today but the accounts are from the latest annual report.
When a company's shares and accounts are in different currencies (BHP is listed in AUD but reports in
USD), the market value is converted with the latest AUD/USD rate first.

**Example.** Total assets 100, working capital 20, retained earnings 30, EBIT 10, revenue 80, total
liabilities 50 and a market value of 150:

- A = 0.2, B = 0.3, C = 0.1, D = 150 ÷ 50 = 3, E = 0.8
- Z = 1.2 × 0.2 + 1.4 × 0.3 + 3.3 × 0.1 + 0.6 × 3 + 1.0 × 0.8 = 0.24 + 0.42 + 0.33 + 1.8 + 0.8 = **3.59**: safe.

A low score is a prompt to look at the company's debt and cash flow, not a prediction that it will fail.

## 13. Liquidity

How long each holding would take to sell **without your own selling moving the price**. A common rule
of thumb is to trade no more than about 10% of a stock's normal daily volume: more than that and you
start pushing the price down as you sell.

$$\text{days to sell} = \frac{\text{shares held}}{10\% \times \text{average daily volume}}$$

- **Average daily volume**: the number of shares traded on a normal day, from IB's daily bars over the
  last 3 months (the same figure as on the stock detail's Key statistics; IB's volume runs a bit below
  the consolidated volume Yahoo shows)
- Under one trading day, it's shown in minutes of the trading session: the US market trades 390
  minutes a day (9:30 am to 4 pm New York time) and the ASX 360 (10 am to 4 pm Sydney time)

The time to sell **everything** (the Liquidity tile) is the slowest holding's, because the holdings can
be sold at the same time.

Green means under a day, amber up to 5 trading days, red longer.

**Example.** 100 shares of a stock that trades 1,000,000 a day: 10% of a day is 100,000 shares, so 100
shares take 100 ÷ 100,000 = **0.001 days**, about 0.4 minutes of a US session: "< 1 min". 50,000 shares of
a small company trading 100,000 a day would take 50,000 ÷ 10,000 = **5 trading days**.
