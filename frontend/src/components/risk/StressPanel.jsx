import { formatMoney } from '../../lib/format.js'
import { listNames, pct, severity } from '../../lib/riskFormat.js'

// RSK 07 Stress tests (Figma 106:1207): what today's holdings would lose in past crashes and simple
// shocks, worst first, with a small severity marker
export default function StressPanel({ section }) {
  const estimated = [...new Set(section.scenarios.flatMap((s) => s.estimated ?? []))]
  return (
    <>
      <div className="risk-table" role="table" aria-label="Stress tests">
        <div className="risk-stress-row risk-table-head" role="row">
          <span role="columnheader">Scenario</span>
          <span role="columnheader">Shock</span>
          <span role="columnheader" className="num">
            Impact
          </span>
          <span role="columnheader" className="num">
            <span className="visually-hidden">Share of holdings</span>
          </span>
        </div>
        {section.scenarios.map((s) => {
          const level = severity(s.impact_pct)
          return (
            <div className="risk-stress-row risk-table-row roomy" role="row" key={s.id}>
              <span role="cell" className="risk-var-label">
                {s.name}
                {s.estimated?.length > 0 && <span className="risk-estimated" title="Partly estimated from the market">*</span>}
              </span>
              <span role="cell" className="risk-mono-2 small">
                {s.label}
              </span>
              <span role="cell" className={`num risk-mono ${s.impact_aud < 0 ? 'loss' : ''}`}>
                {s.impact_aud == null ? 'Unavailable' : formatMoney(s.impact_aud, 'AUD', { decimals: 0 })}
              </span>
              <span role="cell" className="num risk-stress-pct">
                {level && <span className={`risk-severity ${level}`} aria-label={`${level} impact`} />}
                {pct(s.impact_pct)}
              </span>
            </div>
          )
        })}
      </div>
      <p className="risk-footnote">
        Replays apply what each holding (or its market) did in that period to what you own today.
        {estimated.length > 0 &&
          ` * ${listNames(estimated)} had no prices then, so ${estimated.length === 1 ? 'its' : 'their'} market × beta is used.`}
      </p>
    </>
  )
}
