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
  },
  beta_asx: {
    title: 'Beta vs ASX 200',
    what: 'How much your portfolio moves when the Australian market moves.',
    consider: 'A low number means a local crash would affect you less than most Australian investors, and other markets matter more to you instead.',
  },
  beta_us: {
    title: 'Beta vs S&P 500',
    what: 'How much your portfolio moves when the US market moves.',
    consider: 'Holdings outside the US market would lower this number.',
  },
  effective_holdings: {
    title: 'Effective holdings',
    what: 'How many equally sized stocks your portfolio acts like.',
    consider: 'Spreading money more evenly raises this number: 5 equal holdings would score 5.',
  },
  max_drawdown: {
    title: 'Biggest fall',
    what: 'The largest drop from a high to a low in the period.',
    consider: 'A fall this size has already happened with this mix of holdings. Less concentrated portfolios usually fall less.',
  },
  concentration: {
    title: 'Concentration',
    what: 'Each holding’s share of your money (blue) next to its share of your portfolio’s swings (amber).',
    consider:
      'When the amber bar is much longer than the blue one, that holding drives your results. Bringing the two closer usually means a smaller largest position or bigger others.',
  },
  exposure: {
    title: 'Exposure',
    what: 'Where your money is: by currency, by country, and by industry.',
    consider: 'Holdings in other industries and in Australian dollars would make you less dependent on one area.',
  },
  correlation: {
    title: 'Correlation',
    what: 'How closely two holdings move together, from −1 (opposite) to +1 (always together).',
    consider: 'A holding with a low correlation to your largest one steadies a portfolio the most.',
  },
  volatility_beta: {
    title: 'Volatility and beta per holding',
    what: 'Each stock’s own yearly swing, and how much it moves with its market (beta above 1 means more than the market).',
    consider: 'Calm holdings steady a portfolio, but only if they’re a meaningful share of it.',
  },
  currency: {
    title: 'Currency effect',
    what: 'For a US stock, how much of your return in AUD came from the share price and how much from the exchange rate.',
    consider:
      'Currency can just as easily help next year. Some investors avoid this with currency hedged funds; most accept it as part of owning US shares.',
  },
  factors: {
    title: 'Hidden factors',
    what: 'A few shared patterns that explain most of how your holdings move.',
    consider: 'Holdings that follow different patterns from your largest one would spread where your results come from.',
  },
  sharpe: {
    title: 'Sharpe ratio',
    what: 'How much return you got for each unit of risk you took, after subtracting what cash would have earned.',
    consider: 'A high number over one year can come from one great stock. The 3Y view and concentration put it in context.',
  },
  tracking_error: {
    title: 'Tracking error',
    what: 'How far your returns drift from a market index in a typical year.',
    consider: 'A big number isn’t bad by itself; it means your results won’t look like the index’s.',
  },
  stress: {
    title: 'Stress tests',
    what: 'What would happen to what you own today if a past crash, or a made up shock, happened again.',
    consider: 'The scenarios that hurt most point to what your portfolio depends on.',
  },
  var: {
    title: 'Value at Risk',
    what: 'A loss you’d expect to exceed only on rare bad days, worked out three ways.',
    consider: 'It isn’t the worst case: losses can be bigger than this. It gives a sense of what a normal bad day looks like.',
  },
  attribution: {
    title: 'Attribution',
    what: 'Why your returns differed from the ASX 200, split into choosing markets, picking stocks, and currency.',
    consider: 'If most of the difference comes from one choice, your results depend on that choice continuing to work.',
  },
  mixes: {
    title: 'Optimisation and hedging',
    what: 'Example mixes of your own stocks, showing how risk and return trade off, and hedges that reduce specific risks.',
    consider: 'These use last year’s data and aren’t a plan. They show the trade off: less risk usually means giving up some return.',
  },
  bankruptcy: {
    title: 'Bankruptcy risk · Altman Z',
    what: 'A score from a company’s accounts that estimates the risk of financial distress.',
    consider: 'A low score is a prompt to read the company’s debt and cash flow, not a prediction that it will fail.',
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
