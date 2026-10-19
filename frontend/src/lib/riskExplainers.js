import { formatCompactMoney, formatMoney } from './format.js'
import { corr, listNames, pct, periodPhrase, ratio, shortDate, tenPercentMove } from './riskFormat.js'

const pts = (v) => Math.abs(v * 100).toFixed(1)

const money = (value) => formatMoney(value, 'AUD', { decimals: 0 })

// "rise" or "fall" with the move a 10% fall in an index would give
function betaMove(index, beta) {
  if (beta == null) return null
  if (Math.abs(beta) < 0.05) return `If the ${index} fell 10%, your holdings would barely be expected to move.`
  return `If the ${index} fell 10%, you’d expect your holdings to ${beta > 0 ? 'fall' : 'rise'} about ${tenPercentMove(beta)}.`
}

// The ⓘ explainers on the Risk page (Figma board 102:594): what each number is, what yours means
// (filled in with your own numbers), and things to consider. They describe, never advise (#191):
// lines from the board that told the reader what to do are reworded as descriptions.
//
// Each entry: title, what, consider, and optionally
//   value(data) -> text after the title ("Volatility · 19.8%")
//   yours(data) -> the "What yours means" paragraph, or null while the number isn't known
// data is whatever the tile or panel passes (usually its section of GET /risk plus meta).

export const EXPLAINERS = {
  volatility: {
    title: 'Volatility',
    what: 'How much your holdings typically swing in a year, up or down.',
    consider: 'Holdings that don’t move with your largest one are what usually brings this number down.',
    value: ({ section }) => pct(section.portfolio.volatility),
    yours: ({ section }) => {
      const { volatility, value_aud: value } = section.portfolio
      const asx = section.benchmarks.ASX.volatility
      const swing = `In a normal year your ${formatCompactMoney(value, 'AUD')} of holdings could end about ${money(value * volatility)} above or below its average.`
      if (asx == null) return swing
      const compared = Math.abs(volatility - asx) < 0.01 ? 'about the same as' : volatility > asx ? 'more than' : 'less than'
      return `${swing} That’s ${compared} the ASX 200, which swung about ${pct(asx, { decimals: 0 })} over the same period.`
    },
  },
  beta_asx: {
    title: 'Beta vs ASX 200',
    what: 'How much your portfolio moves when the Australian market moves.',
    consider: 'A low number means a local crash would affect you less than most Australian investors, and other markets matter more to you instead.',
    value: ({ section }) => ratio(section.portfolio.beta_asx),
    yours: ({ section }) => {
      const { beta_asx: beta, us_weight: us } = section.portfolio
      const move = betaMove('ASX 200', beta)
      if (move && beta < 0.8 && us >= 0.5) {
        return `${move} It’s low because ${pct(us, { decimals: 0 })} of your money is in US shares, which follow the US market instead.`
      }
      return move
    },
  },
  beta_us: {
    title: 'Beta vs S&P 500',
    what: 'How much your portfolio moves when the US market moves.',
    consider: 'Holdings outside the US market would lower this number.',
    value: ({ section }) => ratio(section.portfolio.beta_us),
    yours: ({ section }) => {
      const { beta_us: beta, us_weight: us } = section.portfolio
      const move = betaMove('S&P 500', beta)
      if (!move) return null
      if (us >= 0.5) return `${move} Your results mostly follow the US market, through the ${pct(us, { decimals: 0 })} of your money in US shares.`
      if (beta < 0.8) return `${move} It’s low because most of your money is in Australian shares.`
      return move
    },
  },
  effective_holdings: {
    title: 'Effective holdings',
    what: 'How many equally sized stocks your portfolio acts like.',
    consider: 'Spreading money more evenly raises this number: 5 equal holdings would score 5.',
    value: ({ section }) => `${section.effective_holdings.toFixed(1)} of ${section.count}`,
    yours: ({ section }) => effectiveHoldingsYours(section),
  },
  max_drawdown: {
    title: 'Biggest fall',
    what: 'The largest drop from a high to a low in the period.',
    consider: 'A fall this size has already happened with this mix of holdings. Less concentrated portfolios usually fall less.',
    value: ({ section }) => pct(section.max_drawdown.fall),
    yours: ({ section }) => {
      const dd = section.max_drawdown
      if (!dd.peak) return 'Your holdings never fell below an earlier high in this period.'
      return `Between ${shortDate(dd.peak)} and ${shortDate(dd.trough, true)} your holdings fell ${pct(-dd.fall)}. At today’s size that’s about ${money(-dd.loss_aud)}.`
    },
  },
  concentration: {
    title: 'Concentration',
    what: 'Each holding’s share of your money (blue) next to its share of your portfolio’s swings (amber).',
    consider:
      'When the amber bar is much longer than the blue one, that holding drives your results. Bringing the two closer usually means a smaller largest position or bigger others.',
    yours: ({ section }) => concentrationYours(section),
  },
  exposure: {
    title: 'Exposure',
    what: 'Where your money is: by currency, by country, and by industry.',
    consider: 'Holdings in other industries and in Australian dollars would make you less dependent on one area.',
    yours: ({ section }) => exposureYours(section),
  },
  correlation: {
    title: 'Correlation',
    what: 'How closely two holdings move together, from −1 (opposite) to +1 (always together).',
    consider: 'A holding with a low correlation to your largest one steadies a portfolio the most.',
    yours: ({ section }) => correlationYours(section),
  },
  volatility_beta: {
    title: 'Volatility and beta per holding',
    what: 'Each stock’s own yearly swing, and how much it moves with its market (beta above 1 means more than the market).',
    consider: 'Calm holdings steady a portfolio, but only if they’re a meaningful share of it.',
    yours: ({ section }) => volatilityBetaYours(section.holdings),
  },
  currency: {
    title: 'Currency effect',
    what: 'For a US stock, how much of your return in AUD came from the share price and how much from the exchange rate.',
    consider:
      'Currency can just as easily help next year. Some investors avoid this with currency hedged funds; most accept it as part of owning US shares.',
    value: ({ section }) => (section.holdings.length ? formatMoney(section.total_effect_aud, 'AUD', { decimals: 0, signed: true }) : null),
    yours: ({ section, meta }) => currencyYours(section, meta?.period),
  },
  factors: {
    title: 'Hidden factors',
    what: 'A few shared patterns that explain most of how your holdings move.',
    consider: 'Holdings that follow different patterns from your largest one would spread where your results come from.',
    yours: ({ section }) => factorsYours(section),
  },
  sharpe: {
    title: 'Sharpe ratio',
    what: 'How much return you got for each unit of risk you took, after subtracting what cash would have earned.',
    consider: 'A high number over one year can come from one great stock. The 3Y view and concentration put it in context.',
    value: ({ section }) => ratio(section.portfolio.sharpe),
    yours: ({ section, meta }) => sharpeYours(section, meta?.period),
  },
  tracking_asx: {
    title: 'Tracking error',
    what: 'How far your returns drift from a market index in a typical year.',
    consider: 'A big number isn’t bad by itself; it means your results won’t look like the index’s.',
    value: ({ section }) => `${pct(section.tracking_error.ASX)} vs ASX 200`,
    yours: ({ section }) => trackingYours(section),
  },
  tracking_us: {
    title: 'Tracking error',
    what: 'How far your returns drift from a market index in a typical year.',
    consider: 'A big number isn’t bad by itself; it means your results won’t look like the index’s.',
    value: ({ section }) => `${pct(section.tracking_error.US)} vs S&P 500`,
    yours: ({ section }) => trackingYours(section),
  },
  stress: {
    title: 'Stress tests',
    what: 'What would happen to what you own today if a past crash, or a made up shock, happened again.',
    consider: 'The scenarios that hurt most point to what your portfolio depends on.',
    yours: ({ section }) => stressYours(section),
  },
  var: {
    title: 'Value at Risk',
    what: 'A loss you’d expect to exceed only on rare bad days, worked out three ways.',
    consider: 'It isn’t the worst case: losses can be bigger than this. It gives a sense of what a normal bad day looks like.',
    value: ({ section }) => formatMoney(section.levels['95'].formula.day.aud, 'AUD', { decimals: 0 }),
    yours: ({ section }) => varYours(section),
  },
  attribution: {
    title: 'Attribution',
    what: 'Why your returns differed from the ASX 200, split into choosing markets, picking stocks, and currency.',
    consider: 'If most of the difference comes from one choice, your results depend on that choice continuing to work.',
    yours: ({ section }) => attributionYours(section),
  },
  mixes: {
    title: 'Optimisation and hedging',
    what: 'Example mixes of your own stocks, showing how risk and return trade off, and hedges that reduce specific risks.',
    consider: 'These use last year’s data and aren’t a plan. They show the trade off: less risk usually means giving up some return.',
    yours: ({ section, meta }) => mixesYours(section, meta?.period),
  },
  bankruptcy: {
    title: 'Bankruptcy risk · Altman Z',
    what: 'A score from a company’s accounts that estimates the risk of financial distress.',
    consider: 'A low score is a prompt to read the company’s debt and cash flow, not a prediction that it will fail.',
    yours: ({ section }) => bankruptcyYours(section),
  },
  liquidity: {
    title: 'Liquidity',
    what: 'How quickly you could sell each holding without your own selling moving the price.',
    consider: 'Liquidity matters most for small companies, thinly traded stocks and big positions.',
  },
}

// The popover's text for an explainer and its data: { title, what, yours, consider }
export function explainerText(id, data) {
  const entry = EXPLAINERS[id]
  if (!entry) return null
  const known = data != null
  const value = known && entry.value ? entry.value(data) : null
  return {
    title: value ? `${entry.title} · ${value}` : entry.title,
    what: entry.what,
    yours: known && entry.yours ? entry.yours(data) : null,
    consider: entry.consider,
  }
}

// "AAPL and BHP swing most, and move more than their markets. TLS and APA are the calmest, but
// together they're only 2.3% of your money."
export function volatilityBetaYours(holdings) {
  if (holdings.length < 2) {
    const h = holdings[0]
    return h ? `${h.symbol} swings about ${pct(h.volatility, { decimals: 0 })} a year, with a beta of ${ratio(h.beta)} against the ${h.beta_vs}.` : null
  }
  const byVol = [...holdings].sort((a, b) => b.volatility - a.volatility)
  const pairSize = holdings.length >= 4 ? 2 : 1
  const top = byVol.slice(0, pairSize)
  const calm = byVol.slice(-pairSize).reverse()
  const above = top.filter((h) => h.beta != null && h.beta > 1)
  const one = top.length === 1
  let text = `${listNames(top.map((h) => h.symbol))} ${one ? 'swings' : 'swing'} most`
  if (above.length === top.length) text += `, and ${one ? 'moves' : 'move'} more than ${one ? 'its market' : 'their markets'}`
  text += '.'
  const calmWeight = calm.reduce((sum, h) => sum + (h.weight ?? 0), 0)
  const calmOne = calm.length === 1
  const share = `${pct(calmWeight)} of your money`
  text += ` ${listNames(calm.map((h) => h.symbol))} ${calmOne ? 'is the calmest' : 'are the calmest'}`
  text += calmWeight < 0.2 ? `, but ${calmOne ? 'it’s' : 'together they’re'} only ${share}.` : `, ${calmOne ? 'at' : 'together'} ${share}.`
  return text
}

// "You own 5 stocks, but they're so uneven that you behave like about 2. …"
export function effectiveHoldingsYours({ effective_holdings: effective, count, largest }) {
  const about = Math.max(1, Math.round(effective))
  if (count === 1) return 'You own one stock, so everything depends on it.'
  if (effective >= count * 0.8) return `Your money is spread fairly evenly across your ${count} stocks, so you behave like about ${about}.`
  let text = `You own ${count} stocks, but they’re uneven enough that you behave like about ${about}.`
  if (largest.weight > 0.5) text += ` A bad result for ${largest.symbol} moves most of your portfolio.`
  return text
}

// "AAPL is 68% of your money but causes 92% of the swings, because …"
export function concentrationYours({ holdings }) {
  const top = holdings[0]
  if (!top || top.risk_share == null) return null
  const money = pct(top.weight, { decimals: 0 })
  const swings = pct(top.risk_share, { decimals: 0 })
  if (holdings.length === 1) return `${top.symbol} is all of your money, so it causes all of the swings.`
  if (top.risk_share > top.weight + 0.02) {
    return `${top.symbol} is ${money} of your money but causes ${swings} of the swings, because it moves more than your other holdings and they don’t offset it.`
  }
  if (top.risk_share < top.weight - 0.02) {
    return `${top.symbol} is ${money} of your money but causes only ${swings} of the swings, because it moves less than your other holdings or offsets them.`
  }
  return `${top.symbol} is ${money} of your money and causes about the same share of the swings (${swings}).`
}

// "68% is in US dollars, so … 68% is also in one industry, Technology."
export function exposureYours({ currency, sector }) {
  const usd = currency.find((c) => c.name === 'USD')?.share ?? 0
  const parts = []
  if (usd > 0) {
    parts.push(
      `${pct(usd, { decimals: 0 })} is in US dollars, so the exchange rate between the Australian and US dollar changes your returns even on days your US shares don’t move.`,
    )
  } else {
    parts.push('All of it is in Australian dollars, so exchange rates don’t change your returns.')
  }
  const top = sector.find((s) => s.name !== 'Unknown')
  if (top) {
    parts.push(
      top.share >= 0.4
        ? `${pct(top.share, { decimals: 0 })} is in one industry, ${top.name}.`
        : `Your largest industry is ${top.name}, at ${pct(top.share, { decimals: 0 })}.`,
    )
  }
  return parts.join(' ')
}

// "Apple rose 39.3% in US dollars, but the Australian dollar strengthened, so in AUD you got 31.8%. …"
export function currencyYours(section, period) {
  const top = section.holdings[0]
  if (!top) return 'You have no US holdings, so exchange rates don’t change your returns.'
  const moved = top.price_return >= 0 ? `rose ${pct(top.price_return)}` : `fell ${pct(-top.price_return)}`
  const aud = section.fx_return < 0 ? 'strengthened' : 'weakened'
  const but = (top.price_return >= 0) === (section.fx_return < 0) ? 'but' : 'and'
  const got = top.aud_return >= 0 ? `you got ${pct(top.aud_return)}` : `it fell ${pct(-top.aud_return)}`
  const effect = section.total_effect_aud
  const cost = effect < 0 ? `cost you about ${money(-effect)}` : `added about ${money(effect)}`
  return `${top.name} ${moved} in US dollars, ${but} the Australian dollar ${aud}, so in AUD ${got}. The exchange rate ${cost} ${periodPhrase(period)}.`
}

// "Your average is +0.23: your holdings mostly move independently, which helps, … CBA and BHP move
// together most (+0.48)."
export function correlationYours({ average, most_related: most }) {
  if (average == null || !most) return null
  let text = `Your average is ${corr(average)}: `
  if (average < 0.3) text += 'your holdings mostly move independently, which helps, because when one falls the others often don’t.'
  else if (average < 0.6) text += 'your holdings often move together, so a fall in one is often matched by falls in others.'
  else text += 'your holdings mostly move together, so they tend to fall at the same time.'
  return `${text} ${most.a} and ${most.b} move together most (${corr(most.correlation)}).`
}

// "Two patterns explain 68%: Australian market (CBA, BHP, TLS and APA) and US tech (Apple) (AAPL)."
export function factorsYours({ factors, loadings, count }) {
  if (!factors?.length) return null
  const followers = (key) =>
    loadings
      .filter((l) => (l[key] ?? 0) >= 0.4)
      .sort((a, b) => b[key] - a[key])
      .map((l) => l.symbol)
  // A factor that's one holding on its own is already named after it
  const describe = (factor, key) => {
    const who = followers(key)
    const alone = who.length === 0 || (who.length === 1 && who[0] === factor.top_holding)
    return alone ? factor.name : `${factor.name} (${listNames(who)})`
  }
  if (count <= 2) return `One pattern explains ${pct(factors[0].share, { decimals: 0 })}: ${describe(factors[0], 'f1')}.`
  const share = pct(factors[0].share + factors[1].share, { decimals: 0 })
  return `Two patterns explain ${share}: ${describe(factors[0], 'f1')} and ${describe(factors[1], 'f2')}. The rest is each holding moving on its own.`
}

// "Your holdings returned 26.2% with 19.8% volatility. After the 4.6% you'd have earned in cash, …"
export function sharpeYours({ portfolio, benchmarks, risk_free_rate: rf }, period) {
  if (portfolio.sharpe == null) return null
  const returned = period === '1Y' ? `returned ${pct(portfolio.annual_return)}` : `returned the equivalent of ${pct(portfolio.annual_return)} a year`
  let text = `Your holdings ${returned} with ${pct(portfolio.volatility)} volatility. After the ${pct(rf)} you’d have earned in cash, that’s ${ratio(portfolio.sharpe)} units of return per unit of risk.`
  if (benchmarks.ASX.sharpe != null) text += ` The ASX 200 managed ${ratio(benchmarks.ASX.sharpe)}.`
  return text
}

// "Your results can easily end up 21% above or below the ASX 200 in a year, … Against the S&P 500 it's only 9.8%."
export function trackingYours({ tracking_error: te }) {
  if (te.ASX == null || te.US == null) return null
  const asx = pct(te.ASX, { decimals: 0 })
  let text = `Your results can easily end up ${asx} above or below the ASX 200 in a year, because you hold different things from it.`
  if (te.US < te.ASX * 0.8) text += ` Against the S&P 500 it’s only ${pct(te.US)}, because more of your results follow the US market.`
  else if (te.US > te.ASX * 1.25) text += ` Against the S&P 500 it’s ${pct(te.US)}, because more of your results follow the Australian market.`
  else text += ` Against the S&P 500 it’s ${pct(te.US)}.`
  return text
}

// "On about 1 trading day in 20 you could lose more than A$1,485, and on 1 day in 100 more than A$2,100. …"
export function varYours({ levels }) {
  const day95 = levels['95'].formula.day.aud
  const day99 = levels['99'].formula.day.aud
  const month95 = levels['95'].formula.month.aud
  return `On about 1 trading day in 20 you could lose more than ${money(-day95)}, and on 1 day in 100 more than ${money(-day99)}. Over a month, the 1 in 20 figure is about ${money(-month95)}.`
}

// "A repeat of 2008 would take about A$34,030 (47%). A 20% fall in Apple alone would cost about A$9,870, …"
export function stressYours({ scenarios }) {
  const byId = Object.fromEntries(scenarios.map((s) => [s.id, s]))
  const worstReplay = scenarios.find((s) => s.kind === 'replay' && s.impact_aud != null)
  const parts = []
  if (worstReplay) {
    const what = { gfc: 'A repeat of 2008', covid: 'A repeat of the 2020 COVID crash', tech2022: 'A repeat of 2022' }[worstReplay.id]
    parts.push(`${what} would take about ${money(-worstReplay.impact_aud)} (${pct(-worstReplay.impact_pct, { decimals: 0 })}).`)
  }
  const largest = byId.largest
  const sp = byId.index_us
  if (largest) {
    let text = `A 20% fall in ${largest.name.replace(/ falls 20%$/, '')} alone would cost about ${money(-largest.impact_aud)}`
    if (sp && largest.impact_aud < sp.impact_aud) text += ', more than a 10% fall in the whole S&P 500'
    parts.push(`${text}.`)
  }
  return parts.join(' ') || null
}

// "You beat the ASX 200 by 16.7 points. Most of it (13.9) came from being in US shares rather than the
// local market, 4.6 from the stocks you picked, and the exchange rate cost 1.8."
export function attributionYours({ difference, allocation, selection, currency }) {
  if (difference == null) return null
  const verdict = difference >= 0 ? `You beat the ASX 200 by ${pts(difference)} points.` : `You trailed the ASX 200 by ${pts(difference)} points.`
  const phrases = {
    allocation: (v) => (v >= 0 ? `${pts(v)} came from being in US shares rather than the local market` : `being in US shares rather than the local market cost ${pts(v)}`),
    selection: (v) => (v >= 0 ? `${pts(v)} from the stocks you picked` : `the stocks you picked cost ${pts(v)}`),
    currency: (v) => (v >= 0 ? `the exchange rate added ${pts(v)}` : `the exchange rate cost ${pts(v)}`),
  }
  const parts = [['allocation', allocation], ['selection', selection], ['currency', currency]]
    .filter(([, v]) => v != null && Math.abs(v) >= 0.0005)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
  if (!parts.length) return verdict
  const text = parts.map(([key, v]) => phrases[key](v))
  return `${verdict} ${text[0][0].toUpperCase()}${text[0].slice(1)}${text.length > 1 ? `, ${listNames(text.slice(1))}` : ''}.`
}

// "Capping Apple at 40% would have cut volatility from 19.8% to 15.4%, but last year it would also have
// cut your return. Your 92.7% cash already cushions your whole account."
export function mixesYours({ mixes, cash }, period) {
  const current = mixes[0]
  const capped = mixes.find((m) => m.id === 'capped')
  const when = { '3M': 'over the last 3 months', '1Y': 'last year', '3Y': 'over the last 3 years' }[period] ?? 'over this period'
  const parts = []
  if (capped) {
    const vol = capped.volatility < current.volatility ? 'cut' : 'raised'
    const ret = capped.annual_return < current.annual_return ? 'cut' : 'raised'
    const link = vol === 'cut' && ret === 'cut' ? 'but' : 'and'
    parts.push(
      `Capping ${capped.name} at 40% would have ${vol} volatility from ${pct(current.volatility)} to ${pct(capped.volatility)}, ${link} ${when} it would also have ${ret} your return.`,
    )
  } else {
    const lowest = mixes.find((m) => m.id === 'lowest_risk')
    if (lowest) parts.push(`The lowest risk mix of your stocks would have swung ${pct(lowest.volatility)} a year, against ${pct(current.volatility)} for your current mix.`)
  }
  if (cash && cash.share >= 0.05) parts.push(`Your ${pct(cash.share)} cash already cushions your whole account.`)
  return parts.join(' ') || null
}

// "AAPL (9.8) and BHP (4.6) are comfortably safe. TLS is in the grey zone, and APA scores low mainly
// because utilities carry a lot of debt by design. The score doesn't work for banks like CBA."
export function bankruptcyYours({ holdings }) {
  const scored = (zone) => holdings.filter((h) => h.zone === zone)
  const parts = []
  const safe = scored('safe')
  if (safe.length) {
    const names = listNames(safe.map((h) => `${h.symbol} (${h.score.toFixed(1)})`))
    parts.push(`${names} ${safe.length === 1 ? 'is' : 'are'} comfortably safe.`)
  }
  const grey = scored('grey')
  if (grey.length) parts.push(`${listNames(grey.map((h) => h.symbol))} ${grey.length === 1 ? 'is' : 'are'} in the grey zone.`)
  const distress = scored('distress')
  const byDesign = distress.filter((h) => h.low_by_design)
  const other = distress.filter((h) => !h.low_by_design)
  if (byDesign.length) {
    parts.push(`${listNames(byDesign.map((h) => h.symbol))} ${byDesign.length === 1 ? 'scores' : 'score'} low mainly because utilities and property companies carry a lot of debt by design.`)
  }
  if (other.length) parts.push(`${listNames(other.map((h) => h.symbol))} ${other.length === 1 ? 'is' : 'are'} in the distress zone.`)
  const banks = scored('bank')
  if (banks.length) parts.push(`The score doesn’t work for banks like ${listNames(banks.map((h) => h.symbol))}.`)
  return parts.join(' ') || null
}
