import { useEffect, useRef, useState } from 'react'
import { formatMoney } from '../format.js'

const HEIGHT = 230
const PAD_Y = 10
const LABEL_COUNT = 5

// Track an element's width so the SVG can be drawn in real pixels (no stretching).
// ResizeObserver calls us whenever the element changes size, e.g. when the list is resized.
function useWidth() {
  const ref = useRef(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}

function formatTick(time, range) {
  const d = new Date(time)
  if (range === '1D') return d.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false })
  if (range === '1Y' || range === 'All') return d.toLocaleDateString('en-AU', { month: 'short', year: '2-digit' })
  return d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
}

function formatTooltipTime(time, range) {
  const d = new Date(time)
  const date = d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
  if (range === '1D' || range === '1W') {
    return `${date} ${d.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false })}`
  }
  return date
}

function PriceChart({ bars, range, avgCost, currency, loading, error }) {
  const [ref, width] = useWidth()
  const [hover, setHover] = useState(null)

  let body
  if (error) {
    body = <div className="chart-message">Could not load price history.<br />{error}</div>
  } else if (loading && !bars) {
    body = <div className="chart-message">Loading price history…</div>
  } else if (!bars || bars.length < 2) {
    body = <div className="chart-message">Not enough price history for this range.</div>
  } else if (width > 0) {
    const closes = bars.map((b) => b.close)
    // Include the average cost in the scale so its dashed line is always visible
    const values = avgCost ? [...closes, avgCost] : closes
    const min = Math.min(...values)
    const max = Math.max(...values)
    const span = max - min || 1

    const x = (i) => (i / (bars.length - 1)) * width
    const y = (v) => PAD_Y + (1 - (v - min) / span) * (HEIGHT - PAD_Y * 2)

    const line = bars.map((b, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(b.close).toFixed(1)}`).join(' ')
    const area = `${line} L${width} ${HEIGHT} L0 ${HEIGHT} Z`
    const color = closes.at(-1) >= closes[0] ? 'var(--pill-gain)' : 'var(--pill-loss)'
    const last = bars.length - 1
    const point = hover ?? last

    function handleMove(e) {
      const box = e.currentTarget.getBoundingClientRect()
      const ratio = (e.clientX - box.left) / box.width
      setHover(Math.min(last, Math.max(0, Math.round(ratio * last))))
    }

    body = (
      <>
        <svg
          width={width}
          height={HEIGHT}
          onPointerMove={handleMove}
          onPointerLeave={() => setHover(null)}
          role="img"
          aria-label={`Price chart, ${range}`}
        >
          {[0.25, 0.5, 0.75].map((f) => (
            <line key={f} x1="0" x2={width} y1={HEIGHT * f} y2={HEIGHT * f} stroke="var(--chart-grid)" />
          ))}
          <path d={area} fill={color} fillOpacity="0.12" />
          {avgCost && (
            <line
              x1="0"
              x2={width}
              y1={y(avgCost)}
              y2={y(avgCost)}
              stroke="var(--text-3)"
              strokeDasharray="4 4"
            />
          )}
          <path d={line} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          {hover != null && (
            <line x1={x(hover)} x2={x(hover)} y1="0" y2={HEIGHT} stroke="var(--text-3)" strokeOpacity="0.5" />
          )}
          <circle cx={x(point)} cy={y(bars[point].close)} r="4" fill={color} stroke="var(--bg)" strokeWidth="2" />
        </svg>
        {hover != null && (
          <div
            className="chart-tooltip"
            style={{ left: Math.min(width - 60, Math.max(60, x(hover))) }}
          >
            <strong className="num">{formatMoney(bars[hover].close, currency)}</strong>{' '}
            <span>{formatTooltipTime(bars[hover].time, range)}</span>
          </div>
        )}
      </>
    )
  }

  const hasChart = bars && bars.length >= 2 && !error
  // Evenly spaced bars for the x-axis labels
  const ticks = hasChart
    ? Array.from({ length: LABEL_COUNT }, (_, i) => bars[Math.round((i / (LABEL_COUNT - 1)) * (bars.length - 1))])
    : []

  return (
    <div className="chart-card">
      <div className="chart" ref={ref}>
        {body}
      </div>
      {hasChart && (
        <>
          <div className="x-axis">
            {ticks.map((b, i) => (
              <span key={i}>{formatTick(b.time, range)}</span>
            ))}
          </div>
          {avgCost && (
            <div className="chart-legend">
              <span className="chart-legend-dash" /> Your average cost ({formatMoney(avgCost, currency)})
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default PriceChart
