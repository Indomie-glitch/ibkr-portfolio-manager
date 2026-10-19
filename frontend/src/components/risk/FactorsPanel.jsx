import { corr, corrColour, factorsHeadline, pct } from '../../lib/riskFormat.js'

// RSK 06 Hidden factors (Figma 106:1111): how much each factor explains, and how strongly each holding
// follows the first two (amber with the factor, blue against it).
export default function FactorsPanel({ section }) {
  const { factors, loadings } = section
  if (!factors.length) return <p className="risk-panel-note">{section.note}</p>
  // Bars are drawn against the largest share rounded up to the next 5%
  const scale = Math.ceil(Math.max(...factors.map((f) => f.share ?? 0)) * 20) / 20 || 1
  const shown = factors.slice(0, 2)
  return (
    <>
      <p className="risk-headline">{factorsHeadline(section)}</p>
      <div className="risk-factors">
        <div className="risk-factor-shares">
          <p className="risk-small-caps tight">Share of movement explained</p>
          {factors.slice(0, 5).map((f, i) => (
            <div className="risk-factor-row" key={f.id}>
              <span className={`risk-factor-id ${i < 2 ? 'amber' : ''}`}>{f.id}</span>
              <span className="risk-bar wide" aria-hidden="true">
                <span className={`risk-bar-fill ${i < 2 ? 'amber' : 'muted'}`} style={{ width: `${((f.share ?? 0) / scale) * 100}%` }} />
              </span>
              <span className="risk-factor-share">{pct(f.share, { decimals: 0 })}</span>
            </div>
          ))}
        </div>
        <div
          className="risk-loadings"
          role="table"
          aria-label="How strongly each holding follows the first two factors"
          style={{ gridTemplateColumns: `44px repeat(${shown.length}, minmax(64px, 110px))` }}
        >
          <span role="row" className="risk-heatmap-row">
            <span role="columnheader" />
            {shown.map((f) => (
              <span role="columnheader" key={f.id} className="risk-loading-head">
                <span className="risk-factor-id amber">{f.id}</span>
                <span className="risk-loading-name">{f.name}</span>
              </span>
            ))}
          </span>
          {loadings.map((row) => (
            <span role="row" className="risk-heatmap-row" key={row.symbol}>
              <span role="rowheader" className="risk-heatmap-label">
                {row.symbol}
              </span>
              {['f1', 'f2'].slice(0, shown.length).map((key) => {
                const value = row[key] ?? 0
                const strong = 0.1 + 0.85 * Math.abs(value) >= 0.75
                return (
                  <span role="cell" key={key} className={`risk-loading ${strong ? 'strong' : ''}`} style={{ background: corrColour(value) }}>
                    {corr(row[key])}
                  </span>
                )
              })}
            </span>
          ))}
        </div>
      </div>
      <p className="risk-footnote">
        Each factor is a pattern several holdings share. The numbers show how strongly each holding follows it: amber
        moves with the factor, blue moves against it.
      </p>
    </>
  )
}
