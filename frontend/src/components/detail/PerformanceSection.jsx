import { fetchPerformance } from '../../lib/api.js'
import { formatPercent, trendClass } from '../../lib/format.js'
import { useFetch } from '../../hooks/useFetch.js'
import { SectionLoading, SectionUnavailable } from './DisclosureSection.jsx'

const PERIOD_LABELS = { ytd: 'Year to date', '1y': '1 year', '3y': '3 years', '5y': '5 years' }

function ReturnRow({ label, value, maxAbs, barClass }) {
  // Bars share one scale across all tiles, so lengths can be compared anywhere in the section
  const width = value == null || !maxAbs ? 0 : Math.max((Math.abs(value) / maxAbs) * 100, 3)
  return (
    <div className="return-row">
      <div className="return-top">
        <span>{label}</span>
        <span className={`num ${trendClass(value)}`}>{value == null ? '—' : formatPercent(value)}</span>
      </div>
      <div className="return-track">
        <span className={`return-bar ${barClass}`} style={{ width: `${width}%` }} />
      </div>
    </div>
  )
}

function PerformanceSection({ holding }) {
  const { data: performance, error, loading } = useFetch(() => fetchPerformance(holding.con_id), holding.con_id)

  if (loading) return <SectionLoading lines={3} />
  if (error) return <SectionUnavailable what="Performance" reason={error} />

  const { periods, benchmark } = performance
  const values = periods.flatMap((p) => [p.stock, p.benchmark]).filter((v) => v != null)
  const maxAbs = Math.max(...values.map(Math.abs), 0)

  return (
    <div className="return-tiles">
      {periods.map((p) => (
        <div className="return-tile" key={p.period}>
          <p className="return-title">{PERIOD_LABELS[p.period] ?? p.period}</p>
          <ReturnRow
            label={holding.symbol}
            value={p.stock}
            maxAbs={maxAbs}
            barClass={p.stock != null && p.stock < 0 ? 'loss' : 'gain'}
          />
          <ReturnRow label={benchmark.short} value={p.benchmark} maxAbs={maxAbs} barClass="benchmark" />
        </div>
      ))}
    </div>
  )
}

export default PerformanceSection
