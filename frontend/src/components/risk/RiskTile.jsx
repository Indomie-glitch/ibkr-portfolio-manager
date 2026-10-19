import { useFetch } from '../../hooks/useFetch.js'
import { loadSection } from '../../lib/riskData.js'
import { explainerText } from '../../lib/riskExplainers.js'
import InfoButton from './InfoButton.jsx'

// A headline number (Figma "Risk Metric / Terminal" 95:524): amber label, value, caption and ⓘ.
// A tile whose issue isn't built yet (no value function) shows "—" and doesn't fetch.
export default function RiskTile({ tile, period, version }) {
  const built = Boolean(tile.value)
  const { data, error } = useFetch(
    () => (built ? loadSection(period, version, tile.section) : Promise.resolve(null)),
    `${tile.id}:${period}:${version}`,
  )
  const section = data?.section
  const value = section ? tile.value(section, data.meta) : '—'
  const sub = section && tile.sub ? tile.sub(section, data.meta) : error && built ? 'Unavailable' : tile.caption
  const tone = section && tile.tone ? tile.tone(section) : undefined
  return (
    <div className="risk-tile">
      <p className="risk-label">{tile.label}</p>
      <p className={`risk-tile-value ${tone ?? ''}`}>{value}</p>
      <p className="risk-tile-sub" title={error ?? undefined}>
        {sub}
      </p>
      <span className="risk-tile-info">
        <InfoButton text={explainerText(tile.explainer, section ? { section, meta: data.meta } : null)} />
      </span>
    </div>
  )
}
