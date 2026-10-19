import { useFetch } from '../../hooks/useFetch.js'
import { loadSection } from '../../lib/riskData.js'
import { explainerText } from '../../lib/riskExplainers.js'
import InfoButton from './InfoButton.jsx'

// The frame every Risk panel shares (Figma Risk / V5A): RSK tag, title, ⓘ, a label on the right,
// then the body. Each panel loads its own section, so a failure only says "unavailable" here.
// Body: the panel's component ({ section, meta, holdings, period }), or none yet (empty frame).
// label(section, period): the right-hand label; the period by default.
export default function RiskPanel({ panel, Body, label, period, version }) {
  const { data, error, loading } = useFetch(
    () => (Body ? loadSection(period, version, panel.section) : Promise.resolve(null)),
    `${panel.id}:${period}:${version}`,
  )
  const section = data?.section
  let content
  if (!Body) content = <p className="risk-panel-note">Coming in a later update.</p>
  else if (loading) content = <p className="risk-panel-note">Loading…</p>
  else if (error) content = <p className="risk-panel-note" role="status">Unavailable: {error}</p>
  else content = <Body section={section} meta={data.meta} holdings={data.holdings} period={period} />

  return (
    <section className="risk-panel" style={{ order: panel.order }} aria-labelledby={`risk-${panel.id}`}>
      <header className="risk-panel-header">
        <span className="risk-code">{panel.code}</span>
        <h2 className="risk-panel-title" id={`risk-${panel.id}`}>
          {panel.title}
        </h2>
        <InfoButton text={explainerText(panel.explainer, section ? { section, meta: data.meta } : null)} />
        <span className="spacer" />
        <span className="risk-panel-label">{section && label ? label(section, period) : period}</span>
      </header>
      {content}
    </section>
  )
}
