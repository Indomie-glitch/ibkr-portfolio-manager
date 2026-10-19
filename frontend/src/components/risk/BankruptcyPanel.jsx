import { zoneLabel } from '../../lib/riskFormat.js'

const ZONE_CLASS = { safe: 'gain', grey: 'amber', distress: 'loss' }

// RSK 11 Bankruptcy risk (Figma 106:1389): each company's Altman Z score from its latest annual
// accounts, its zone, and a bar up to a score of 10
export default function BankruptcyPanel({ section }) {
  const lowByDesign = section.holdings.filter((h) => h.low_by_design)
  return (
    <>
      <div className="risk-table" role="table" aria-label="Altman Z score per holding">
        <div className="risk-z-row risk-table-head" role="row">
          <span role="columnheader">Holding</span>
          <span role="columnheader" className="num">
            Score
          </span>
          <span role="columnheader" className="num">
            Zone
          </span>
          <span role="columnheader">
            <span className="visually-hidden">Score out of 10</span>
          </span>
        </div>
        {section.holdings.map((h) => (
          <div className="risk-z-row risk-table-row roomy" role="row" key={h.symbol}>
            <span role="cell" className="risk-mix-name">
              <span className="risk-symbol">{h.symbol}</span>
              <span className="risk-mix-caption">{h.name}</span>
            </span>
            <span role="cell" className="num risk-mono">
              {h.score == null ? '—' : h.score.toFixed(1)}
            </span>
            <span role="cell" className={`num risk-zone ${ZONE_CLASS[h.zone] ?? 'muted'}`}>
              {zoneLabel(h)}
            </span>
            <span role="cell" className="risk-bar" aria-hidden="true">
              {h.score != null && (
                <span
                  className={`risk-bar-fill ${ZONE_CLASS[h.zone] === 'amber' ? 'amber' : ZONE_CLASS[h.zone]}`}
                  style={{ width: `${(Math.max(0, Math.min(10, h.score)) / 10) * 100}%` }}
                />
              )}
            </span>
          </div>
        ))}
      </div>
      <p className="risk-footnote">
        Above 3 is safe, 1.8 to 3 is a grey zone, below 1.8 is distress.
        {lowByDesign.length > 0 &&
          ` *${lowByDesign.map((h) => h.symbol).join(', ')}: utilities and property companies carry lots of debt by design, so they often score low without being in trouble.`}
      </p>
    </>
  )
}
