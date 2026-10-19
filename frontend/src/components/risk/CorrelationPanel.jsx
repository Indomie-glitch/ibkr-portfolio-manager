import { useRef, useState } from 'react'
import { corr, corrColour, describeAverage, describePair, pairTooltip } from '../../lib/riskFormat.js'

// The pair for row i, column j (pairs are listed once, with i < j)
function pairAt(pairs, symbols, i, j) {
  const [a, b] = i < j ? [symbols[i], symbols[j]] : [symbols[j], symbols[i]]
  const pair = pairs.find((p) => p.a === a && p.b === b)
  if (!pair || i < j) return pair
  // Seen from the other side: the move per 1% of the other holding
  // cov / var(b) = correlation² / (cov / var(a))
  const reverse = pair.b_per_a ? pair.correlation ** 2 / pair.b_per_a : null
  return { ...pair, a: pair.b, b: pair.a, b_per_a: reverse }
}

// RSK 03 Correlation (Figma 106:912): an n × n grid from −1 (blue) through 0 to +1 (amber), with the
// diagonal greyed, a scale, three callouts and a hover explanation per pair.
export default function CorrelationPanel({ section, period }) {
  const { symbols, matrix, pairs } = section
  const [hover, setHover] = useState(null) // { i, j, left, top }
  const gridRef = useRef(null)

  function show(event, i, j) {
    const cell = event.currentTarget
    const grid = gridRef.current
    const right = cell.offsetLeft + cell.offsetWidth + 8
    // To the right of the cell, or to its left when there's no room
    const left = right + 240 > grid.offsetWidth ? Math.max(0, cell.offsetLeft - 248) : right
    setHover({ i, j, left, top: cell.offsetTop })
  }

  const hovered = hover && pairAt(pairs, symbols, hover.i, hover.j)
  const most = section.most_related
  const least = section.least_related
  return (
    <>
      <div
        className="risk-heatmap"
        ref={gridRef}
        role="table"
        aria-label="Correlation of daily returns between each pair of holdings"
        style={{ gridTemplateColumns: `44px repeat(${symbols.length}, minmax(0, 72px))` }}
        onMouseLeave={() => setHover(null)}
      >
        <span role="row" className="risk-heatmap-row">
          <span role="columnheader" />
          {symbols.map((s) => (
            <span role="columnheader" key={s} className="risk-heatmap-head">
              {s}
            </span>
          ))}
        </span>
        {symbols.map((rowSymbol, i) => (
          <span role="row" className="risk-heatmap-row" key={rowSymbol}>
            <span role="rowheader" className="risk-heatmap-label">
              {rowSymbol}
            </span>
            {symbols.map((colSymbol, j) => {
              const value = matrix[i][j]
              if (i === j) {
                return (
                  <span role="cell" key={colSymbol} className="risk-heatmap-cell self">
                    1.00
                  </span>
                )
              }
              const pair = pairAt(pairs, symbols, i, j)
              const active = hover?.i === i && hover?.j === j
              return (
                <span
                  role="cell"
                  key={colSymbol}
                  className={`risk-heatmap-cell ${active ? 'active' : ''}`}
                  style={{ background: corrColour(value) }}
                  aria-label={`${rowSymbol} and ${colSymbol} ${corr(value)}. ${pair ? pairTooltip(pair, period) : ''}`}
                  onMouseEnter={(e) => show(e, i, j)}
                >
                  {corr(value)}
                </span>
              )
            })}
          </span>
        ))}
        {hovered && (
          <div className="risk-heatmap-tooltip" style={{ left: hover.left, top: hover.top }} aria-hidden="true">
            <p className="risk-heatmap-tooltip-title">
              {`${hovered.a} and ${hovered.b}  ${corr(hovered.correlation)}`}
            </p>
            <p>{pairTooltip(hovered, period)}</p>
          </div>
        )}
      </div>
      <div className="risk-scale">
        <span>−1 opposite</span>
        <span className="risk-scale-bar" aria-hidden="true" />
        <span>+1 together</span>
      </div>
      {most && (
        <div className="risk-callouts">
          <div>
            <p className="risk-small-caps tight">Most related</p>
            <p className="risk-callout-value amber">
              {`${most.a} · ${most.b}  ${corr(most.correlation)}`}
            </p>
            <p className="risk-callout-note">{describePair(most.correlation)}</p>
          </div>
          <div>
            <p className="risk-small-caps tight">Least related</p>
            <p className="risk-callout-value">
              {`${least.a} · ${least.b}  ${corr(least.correlation)}`}
            </p>
            <p className="risk-callout-note">{describePair(least.correlation)}</p>
          </div>
          <div>
            <p className="risk-small-caps tight">Average</p>
            <p className="risk-callout-value">{corr(section.average)}</p>
            <p className="risk-callout-note">{describeAverage(section.average)}</p>
          </div>
        </div>
      )}
    </>
  )
}
