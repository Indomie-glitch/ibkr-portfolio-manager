import { formatCompactMoney } from '../../lib/format.js'
import { pct } from '../../lib/riskFormat.js'

const GROUPS = [
  ['currency', 'Currency'],
  ['market', 'Market'],
  ['sector', 'Sector'],
]

// One stacked bar with its legend; colours follow the allocation palette (--chart-1 to --chart-5)
function Split({ title, parts }) {
  const colour = (i) => `var(--chart-${(i % 5) + 1})`
  return (
    <div className="risk-split">
      <p className="risk-bar-label">{title}</p>
      <div className="risk-stacked" role="img" aria-label={`${title}: ${parts.map((p) => `${p.name} ${pct(p.share)}`).join(', ')}`}>
        {parts.map((p, i) => (
          <span key={p.name} style={{ flexGrow: p.share, background: colour(i) }} />
        ))}
      </div>
      <div className="risk-split-legend">
        {parts.map((p, i) => (
          <span key={p.name}>
            <span className="risk-swatch" style={{ background: colour(i) }} />
            <span className="risk-split-name">{p.name}</span>
            <span className="risk-split-value">{pct(p.share)}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

// RSK 02 Exposure (Figma 106:845): the holdings split by currency, market and sector
export default function ExposurePanel({ section }) {
  const holdings = formatCompactMoney(section.holdings_value_aud, 'AUD')
  const cash = section.cash_aud == null ? 'Cash' : `Cash (${formatCompactMoney(section.cash_aud, 'AUD')})`
  return (
    <>
      {GROUPS.map(([key, title]) => (
        <Split key={key} title={title} parts={section[key]} />
      ))}
      <p className="risk-footnote">
        Measured in AUD. {cash} is left out, so these split your {holdings} in holdings.
      </p>
    </>
  )
}
