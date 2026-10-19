import { pct, ratio } from '../../lib/riskFormat.js'

const MARKET_CODES = { ASX: 'AU', US: 'US' }

// RSK 04 Volatility and beta (Figma 106:1008): each holding's yearly swing as a bar, its beta against
// its home index (amber above 1), and the portfolio's figures.
export default function VolatilityPanel({ section }) {
  const { holdings, portfolio } = section
  // Bars are drawn against the largest volatility rounded up to the next 10%
  const scale = Math.max(0.1, Math.ceil(Math.max(...holdings.map((h) => h.volatility ?? 0)) * 10) / 10)
  return (
    <>
      <div className="risk-table" role="table" aria-label="Volatility and beta per holding">
        <div className="risk-vol-row risk-table-head" role="row">
          <span role="columnheader">Holding</span>
          <span role="columnheader">Mkt</span>
          <span role="columnheader">Volatility</span>
          <span role="columnheader" className="num">
            <span className="visually-hidden">Volatility per year</span>
          </span>
          <span role="columnheader" className="num">
            Beta
          </span>
          <span role="columnheader" className="num">
            Vs
          </span>
        </div>
        {holdings.map((h) => (
          <div className="risk-vol-row risk-table-row" role="row" key={h.symbol}>
            <span role="cell" className="risk-symbol">
              {h.symbol}
            </span>
            <span role="cell" className="risk-mono-2">
              {MARKET_CODES[h.market] ?? h.market}
            </span>
            <span role="cell" className="risk-bar" aria-hidden="true">
              <span className="risk-bar-fill vol" style={{ width: `${Math.min(100, ((h.volatility ?? 0) / scale) * 100)}%` }} />
            </span>
            <span role="cell" className="num risk-mono">
              {pct(h.volatility)}
            </span>
            <span role="cell" className={`num risk-mono ${h.beta > 1 ? 'amber' : ''}`}>
              {ratio(h.beta)}
            </span>
            <span role="cell" className="num risk-mono-2">
              {h.beta_vs}
            </span>
          </div>
        ))}
      </div>
      <div className="risk-portfolio-row">
        <span className="risk-portfolio-name">Portfolio</span>
        <span className="risk-mono">{pct(portfolio.volatility)}</span>
        <span className="spacer" />
        <span className="risk-portfolio-betas">
          β {ratio(portfolio.beta_asx)} ASX 200 · β {ratio(portfolio.beta_us)} S&amp;P 500
        </span>
      </div>
      <p className="risk-footnote">
        Volatility: how much a stock typically swings in a year. Beta above 1 means it moves more than its market
        (amber).
      </p>
    </>
  )
}
