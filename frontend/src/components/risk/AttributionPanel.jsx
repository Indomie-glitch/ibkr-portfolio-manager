import { pct, points } from '../../lib/riskFormat.js'

const PARTS = [
  ['allocation', 'Allocation', 'Being in US shares instead of the ASX mix'],
  ['selection', 'Selection', 'Picking these stocks within their markets'],
  ['currency', 'Currency', 'Exchange rate on US holdings'],
]

// RSK 09 Attribution (Figma 106:1293): your return against the ASX 200's, and the difference split
// into allocation, selection and currency
export default function AttributionPanel({ section }) {
  const tone = (v) => (v > 0 ? 'gain' : v < 0 ? 'loss' : '')
  const scale = Math.max(Math.abs(section.difference ?? 0), ...PARTS.map(([key]) => Math.abs(section[key] ?? 0))) || 1
  return (
    <>
      <div className="risk-kpis plain">
        <div>
          <p className="risk-small-caps tight">Your return</p>
          <p className={`risk-kpi-big ${tone(section.portfolio_return)}`}>{pct(section.portfolio_return, { signed: true })}</p>
        </div>
        <div>
          <p className="risk-small-caps tight">ASX 200</p>
          <p className="risk-kpi-big">{pct(section.benchmark_return, { signed: true })}</p>
        </div>
        <div>
          <p className="risk-small-caps tight">Difference</p>
          <p className="risk-kpi-big amber">{points(section.difference)}</p>
        </div>
      </div>
      {PARTS.map(([key, name, description]) => (
        <div className="risk-currency-row" key={key}>
          <div className="risk-attr-line">
            <span className="risk-attr-name">{name}</span>
            <span className="risk-attr-desc">{description}</span>
            <span className="spacer" />
            <span className={`risk-currency-value ${tone(section[key])}`}>{points(section[key])}</span>
          </div>
          <span className="risk-bar full" aria-hidden="true">
            <span className={`risk-bar-fill ${tone(section[key]) || 'plain'}`} style={{ width: `${(Math.abs(section[key] ?? 0) / scale) * 100}%` }} />
          </span>
        </div>
      ))}
      <p className="risk-footnote">
        Allocation: which markets you chose. Selection: which stocks you picked within them. The three add up to the
        difference.
      </p>
    </>
  )
}
