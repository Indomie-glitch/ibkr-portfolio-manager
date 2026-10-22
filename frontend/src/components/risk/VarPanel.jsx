import { formatMoney } from '../../lib/format.js'
import { varPlainWords } from '../../lib/riskFormat.js'

const money = (entry, currency) => (entry ? formatMoney(entry.base, currency, { decimals: 0 }) : '—')
const PAST = { '3M': 'Past 3 months', '1Y': 'Past year', '3Y': 'Past 3 years' }

// RSK 08 Value at Risk (Figma 106:1256): the loss only the worst 1 day in 20 (or 100) should exceed,
// for a day and a month, by formula, from history and simulated; then the same in plain words.
export default function VarPanel({ section, meta, period }) {
  const { levels } = section
  const rows = [
    { label: '95% (1 in 20)', figures: levels['95'].formula, method: 'Formula' },
    { label: '99% (1 in 100)', figures: levels['99'].formula, method: 'Formula' },
    { label: '95% from history', figures: levels['95'].history, method: PAST[period] ?? 'History' },
    { label: '95% simulated', figures: levels['95'].simulated, method: `${section.runs.toLocaleString('en-AU')} runs` },
  ]
  return (
    <>
      <div className="risk-table" role="table" aria-label="Value at Risk">
        <div className="risk-var-row risk-table-head" role="row">
          <span role="columnheader">
            <span className="visually-hidden">Confidence</span>
          </span>
          <span role="columnheader" className="num">
            1 day
          </span>
          <span role="columnheader" className="num">
            1 month
          </span>
          <span role="columnheader" className="num">
            Method
          </span>
        </div>
        {rows.map((r) => (
          <div className="risk-var-row risk-table-row roomy" role="row" key={r.label}>
            <span role="cell" className="risk-var-label">
              {r.label}
            </span>
            <span role="cell" className="num risk-mono loss">
              {money(r.figures.day, meta.currency)}
            </span>
            <span role="cell" className="num risk-mono loss">
              {money(r.figures.month, meta.currency)}
            </span>
            <span role="cell" className="num risk-mono-2 small">
              {r.method}
            </span>
          </div>
        ))}
      </div>
      <div className="risk-plain">
        <p className="risk-small-caps tight">In plain words</p>
        <p>{varPlainWords(section, period, meta.currency)}</p>
      </div>
    </>
  )
}
