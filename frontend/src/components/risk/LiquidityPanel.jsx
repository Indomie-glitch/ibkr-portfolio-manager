import { formatNumber } from '../../lib/format.js'
import { compactVolume, sellTime, sellTone } from '../../lib/riskFormat.js'

// RSK 12 Liquidity (Figma 106:1447): how long each holding would take to sell without moving its
// price, trading at most 10% of a normal day's volume
export default function LiquidityPanel({ section }) {
  const slowest = section.slowest
  const allQuick = slowest && slowest.days < 1
  return (
    <>
      <div className="risk-table" role="table" aria-label="Time to sell each holding">
        <div className="risk-liq-row risk-table-head" role="row">
          <span role="columnheader">Holding</span>
          <span role="columnheader" className="num">
            Your shares
          </span>
          <span role="columnheader" className="num">
            Avg daily volume
          </span>
          <span role="columnheader" className="num">
            Time to sell
          </span>
        </div>
        {section.holdings.map((h) => (
          <div className="risk-liq-row risk-table-row roomy" role="row" key={h.symbol}>
            <span role="cell" className="risk-symbol">
              {h.symbol}
            </span>
            <span role="cell" className="num risk-mono">
              {h.quantity == null ? '—' : formatNumber(h.quantity, 0)}
            </span>
            <span role="cell" className="num risk-mono dim">
              {compactVolume(h.avg_volume)}
            </span>
            <span role="cell" className={`num risk-mono ${sellTone(h)}`}>
              {sellTime(h)}
            </span>
          </div>
        ))}
      </div>
      <p className="risk-footnote">
        Time to sell assumes you trade no more than 10% of a normal day’s volume, so your own selling doesn’t move the
        price.{' '}
        {allQuick
          ? 'All your positions are small next to daily volume.'
          : slowest
            ? `${slowest.symbol} would take the longest: ${sellTime(slowest)}.`
            : ''}
      </p>
    </>
  )
}
