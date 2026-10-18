import { useState } from 'react'
import { formatCompactMoney, formatMoney, formatNumber, formatPercent, trendClass } from '../lib/format.js'
import { UpDownIcon } from './icons.jsx'

const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)']
const SIZE = 180
const THICKNESS = 24
const RADIUS = (SIZE - THICKNESS) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS
const GAP = 2 // px of empty ring between segments

// What the card can measure. Money metrics use the AUD copies so holdings can be added up.
const METRICS = {
  market_value: {
    label: 'Market value',
    caption: (c) => `What each holding is worth now, in ${c}`,
    centre: 'Market value',
    value: (h) => h.market_value_base,
  },
  cost_basis: {
    label: 'Cost basis',
    caption: (c) => `What you paid for each holding, in ${c}`,
    centre: 'Invested',
    value: (h) => h.cost_basis_base,
  },
  quantity: {
    label: 'Quantity',
    caption: () => 'Number of shares held',
    centre: 'Shares',
    value: (h) => h.quantity,
    isCount: true,
  },
  unrealized_pnl: {
    label: 'Unrealised P&L',
    caption: (c) => `Gain or loss per holding, in ${c}`,
    value: (h) => h.unrealized_pnl_base,
    diverging: true,
  },
}

// Show the top 5 holdings; group the rest as "Other" so colours stay distinct.
// Colours follow the holding (biggest by market value = first colour), not the metric,
// so AAPL keeps the same colour when you switch metrics.
function toSlices(holdings, metric) {
  const coloured = holdings.map((h, i) => ({ h, color: COLORS[i % COLORS.length] }))
  const items = coloured
    .map(({ h, color }) => ({ label: h.symbol, value: metric.value(h), color }))
    .filter((s) => s.value > 0)
    .sort((a, b) => b.value - a.value)
  const total = items.reduce((sum, s) => sum + s.value, 0)

  const top = items.slice(0, items.length > 6 ? 5 : 6)
  const rest = items.slice(top.length)
  if (rest.length > 0) {
    top.push({ label: 'Other', value: rest.reduce((sum, s) => sum + s.value, 0), color: 'var(--text-3)' })
  }
  return { total, slices: top.map((s) => ({ ...s, weight: total ? (s.value / total) * 100 : 0 })) }
}

function Donut({ slices, centreValue, centreLabel }) {
  // Each slice is the same circle, drawn as a dash that covers only its share of the ring.
  // strokeDashoffset moves the dash so it starts where the previous slices ended.
  const arcs = slices.map((slice, i) => {
    const before = slices.slice(0, i).reduce((sum, s) => sum + s.weight, 0)
    const length = (slice.weight / 100) * CIRCUMFERENCE
    return {
      ...slice,
      dash: Math.max(length - (slices.length > 1 ? GAP : 0), 0),
      offset: -(before / 100) * CIRCUMFERENCE,
    }
  })

  return (
    <div className="donut">
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="Allocation chart">
        {/* rotate so the first slice starts at 12 o'clock */}
        <g transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}>
          <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none" stroke="var(--fill)" strokeWidth={THICKNESS} />
          {arcs.map((arc) => (
            <circle
              key={arc.label}
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke={arc.color}
              strokeWidth={THICKNESS}
              strokeDasharray={`${arc.dash} ${CIRCUMFERENCE}`}
              strokeDashoffset={arc.offset}
            />
          ))}
        </g>
      </svg>
      <div className="donut-label">
        <strong className="num">{centreValue}</strong>
        <span>{centreLabel}</span>
      </div>
    </div>
  )
}

// Gains grow right from a centre zero line, losses grow left. A donut can't show
// negative values, so P&L uses these bars instead.
function DivergingBars({ holdings, currency }) {
  const rows = holdings
    .filter((h) => h.unrealized_pnl_base != null)
    .map((h) => ({ label: h.symbol, value: h.unrealized_pnl_base }))
    .sort((a, b) => b.value - a.value)
  const total = rows.reduce((sum, r) => sum + r.value, 0)
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.value)), 0)

  return (
    <>
      <div>
        <p className={`pnl-total num ${trendClass(total)}`}>{formatMoney(total, currency, { signed: true })}</p>
        <p className="card-caption">Total unrealised P&amp;L</p>
      </div>

      {/* One grid for all rows, so every track is the same width and the zero lines line up.
          The amount column sizes to its widest value, so amounts are never clipped. */}
      <div className="bars">
        {rows.map((r) => {
          // Half the track per side; keep tiny non-zero values visible as a 2px sliver
          const share = maxAbs ? Math.abs(r.value) / maxAbs : 0
          const width = r.value === 0 ? '0px' : `max(2px, calc(${share} * (50% - 1px)))`
          return (
            <div className="bar-row" key={r.label}>
              <span className="bar-label">{r.label}</span>
              <span className="bar-track">
                <span
                  className={`bar ${r.value >= 0 ? 'gain' : 'loss'}`}
                  style={r.value >= 0 ? { left: 'calc(50% + 1px)', width } : { right: 'calc(50% + 1px)', width }}
                />
              </span>
              <span className={`bar-amount num ${trendClass(r.value)}`}>
                {formatMoney(r.value, currency, { signed: true })}
              </span>
            </div>
          )
        })}
        <div className="bar-row bar-axis">
          <span />
          <span>
            <span>← loss</span>
            <span>gain →</span>
          </span>
          <span />
        </div>
      </div>
    </>
  )
}

function AllocationCard({ holdings, currency }) {
  const [metricKey, setMetricKey] = useState('market_value')
  const metric = METRICS[metricKey]
  const { total, slices } = metric.diverging ? { total: 0, slices: [] } : toSlices(holdings, metric)
  const formatValue = (v) => (metric.isCount ? `${formatNumber(v, 0)} sh` : formatMoney(v, currency, { decimals: 0 }))

  return (
    <section className="allocation-card" id="allocation-card">
      <div className="allocation-header">
        <div className="allocation-titles">
          <h2 className="card-title">Allocation</h2>
          <p className="card-caption">{metric.caption(currency)}</p>
        </div>
        <label className="metric-select">
          <span className="visually-hidden">Measure allocation by</span>
          <select value={metricKey} onChange={(e) => setMetricKey(e.target.value)}>
            {Object.entries(METRICS).map(([key, m]) => (
              <option key={key} value={key}>
                {m.label}
              </option>
            ))}
          </select>
          <UpDownIcon />
        </label>
      </div>

      {metric.diverging ? (
        <DivergingBars holdings={holdings} currency={currency} />
      ) : (
        <>
          <Donut
            slices={slices}
            centreValue={metric.isCount ? formatNumber(total, 0) : formatCompactMoney(total, currency)}
            centreLabel={metric.centre}
          />
          <ul className="legend">
            {slices.map((slice) => (
              <li key={slice.label}>
                <span className="swatch" style={{ background: slice.color }} />
                <span>{slice.label}</span>
                <span className="legend-value num">{formatValue(slice.value)}</span>
                <span className="legend-pct num">
                  {formatPercent(slice.weight, { signed: false, decimals: 1 })}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

export default AllocationCard
