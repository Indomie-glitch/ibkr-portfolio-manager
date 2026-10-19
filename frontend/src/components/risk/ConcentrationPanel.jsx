import { concentrationWarning, pct } from '../../lib/riskFormat.js'

// A bar's width; tiny shares still show a sliver (Figma: 2 px)
const width = (share) => `max(2px, ${Math.max(0, Math.min(1, share ?? 0)) * 100}%)`

// RSK 01 Concentration (Figma 106:754): each holding's share of the money (blue) next to its share of
// the portfolio's swings (amber), the top 3, largest and effective holdings, and warnings.
export default function ConcentrationPanel({ section }) {
  const { holdings, largest, warnings } = section
  return (
    <>
      <div className="risk-table" role="table" aria-label="Share of money and of risk">
        <div className="risk-conc-row risk-table-head" role="row">
          <span role="columnheader">#</span>
          <span role="columnheader">Holding</span>
          <span role="columnheader">Share of money and of risk</span>
          <span role="columnheader" className="num">
            Money
          </span>
          <span role="columnheader" className="num">
            Risk
          </span>
        </div>
        {holdings.map((h, i) => (
          <div className="risk-conc-row risk-conc-item" role="row" key={h.symbol}>
            <span role="cell" className="risk-mono-2 faint">
              {i + 1}
            </span>
            <span role="cell" className="risk-symbol">
              {h.symbol}
            </span>
            <span role="cell" className="risk-pair-bars" aria-hidden="true">
              <span className="risk-bar thin">
                <span className="risk-bar-fill money" style={{ width: width(h.weight) }} />
              </span>
              <span className="risk-bar thin">
                <span className="risk-bar-fill amber" style={{ width: width(h.risk_share) }} />
              </span>
            </span>
            <span role="cell" className="num risk-mono">
              {pct(h.weight)}
            </span>
            <span role="cell" className="num risk-mono amber">
              {pct(h.risk_share)}
            </span>
          </div>
        ))}
      </div>
      <div className="risk-legend">
        <span>
          <span className="risk-legend-key money" /> Share of money
        </span>
        <span>
          <span className="risk-legend-key amber" /> Share of risk: how much of the swings it causes
        </span>
      </div>
      <div className="risk-kpis">
        <div>
          <p className="risk-small-caps">Top 3 share</p>
          <p className="risk-kpi-value">{pct(section.top3_share)}</p>
        </div>
        <div>
          <p className="risk-small-caps">Largest</p>
          <p className="risk-kpi-value">
            {largest.symbol} {pct(largest.weight)}
          </p>
        </div>
        <div>
          <p className="risk-small-caps">Effective holdings</p>
          <p className="risk-kpi-value">
            {section.effective_holdings.toFixed(1)} of {section.count}
          </p>
        </div>
      </div>
      {warnings.length > 0 && (
        <ul className="risk-warnings">
          {warnings.map((w) => (
            <li key={`${w.kind}-${w.name}`}>
              <span className="risk-warning-mark" aria-hidden="true">
                ▲
              </span>
              {concentrationWarning(w)}
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
