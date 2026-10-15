import { formatCompactMoney, formatPercent } from '../format.js'

const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)']
const SIZE = 180
const THICKNESS = 24
const RADIUS = (SIZE - THICKNESS) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS
const GAP = 2 // px of empty ring between segments

// Show the top 5 holdings; group the rest as "Other" so colours stay distinct.
function toSlices(holdings) {
  const withWeight = holdings.filter((h) => h.weight > 0)
  const top = withWeight.slice(0, withWeight.length > 6 ? 5 : 6)
  const slices = top.map((h, i) => ({
    label: h.symbol,
    weight: h.weight,
    color: COLORS[i % COLORS.length],
  }))
  const rest = withWeight.slice(top.length)
  if (rest.length > 0) {
    slices.push({
      label: 'Other',
      weight: rest.reduce((sum, h) => sum + h.weight, 0),
      color: 'var(--text-3)',
    })
  }
  return slices
}

function AllocationCard({ holdings, totalBase, currency }) {
  const slices = toSlices(holdings)

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
    <section className="allocation-card">
      <div>
        <h2 className="card-title">Allocation</h2>
        <p className="card-caption">By market value, in {currency}</p>
      </div>

      <div className="donut">
        <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="Allocation chart">
          {/* rotate so the first slice starts at 12 o'clock */}
          <g transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}>
            <circle
              cx={SIZE / 2}
              cy={SIZE / 2}
              r={RADIUS}
              fill="none"
              stroke="var(--fill)"
              strokeWidth={THICKNESS}
            />
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
          <strong className="num">{formatCompactMoney(totalBase, currency)}</strong>
          <span>Invested</span>
        </div>
      </div>

      <ul className="legend">
        {slices.map((slice) => (
          <li key={slice.label}>
            <span className="swatch" style={{ background: slice.color }} />
            <span>{slice.label}</span>
            <span className="num">{formatPercent(slice.weight, { signed: false, decimals: 1 })}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default AllocationCard
