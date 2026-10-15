import { useRef, useState } from 'react'
import { companyName, formatNumber, formatPercent, trendClass } from '../format.js'
import { SearchIcon } from './icons.jsx'

const MIN_WIDTH = 220
const MAX_WIDTH = 480
const DEFAULT_WIDTH = 300
const STORAGE_KEY = 'holdingsListWidth'
const MARKETS = ['All', 'ASX', 'US']

function clampWidth(width) {
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width))
}

function loadWidth() {
  try {
    const saved = Number(localStorage.getItem(STORAGE_KEY))
    return saved ? clampWidth(saved) : DEFAULT_WIDTH
  } catch {
    return DEFAULT_WIDTH
  }
}

function saveWidth(width) {
  try {
    localStorage.setItem(STORAGE_KEY, String(width))
  } catch {
    // storage blocked (e.g. private window); the width just won't be remembered
  }
}

function HoldingsList({ holdings, selectedId, onSelect }) {
  const [query, setQuery] = useState('')
  const [market, setMarket] = useState('All')
  const [width, setWidth] = useState(loadWidth)
  const drag = useRef(null)

  const q = query.trim().toLowerCase()
  const visible = holdings.filter(
    (h) =>
      (market === 'All' || h.market === market) &&
      (!q || h.symbol.toLowerCase().includes(q) || h.name.toLowerCase().includes(q)),
  )

  // Dragging: remember where the pointer started, then grow/shrink by how far it moved.
  // setPointerCapture keeps sending move events to the handle even if the pointer leaves it.
  function startDrag(e) {
    drag.current = { startX: e.clientX, startWidth: width }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  function moveDrag(e) {
    if (!drag.current) return
    setWidth(clampWidth(drag.current.startWidth + e.clientX - drag.current.startX))
  }

  function endDrag() {
    if (!drag.current) return
    drag.current = null
    saveWidth(width)
  }

  function handleKey(e) {
    const step = e.key === 'ArrowRight' ? 16 : e.key === 'ArrowLeft' ? -16 : 0
    if (!step) return
    e.preventDefault()
    const next = clampWidth(width + step)
    setWidth(next)
    saveWidth(next)
  }

  return (
    <aside className="holdings-pane" style={{ width }}>
      <div className="holdings-list">
        <label className="search-field">
          <SearchIcon />
          <input
            type="search"
            placeholder="Search holdings"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>

        <div className="list-filter">
          <div className="segmented" role="group" aria-label="Market">
            {MARKETS.map((m) => (
              <button key={m} type="button" aria-pressed={market === m} onClick={() => setMarket(m)}>
                {m}
              </button>
            ))}
          </div>
        </div>

        <div className="list-meta">
          <span>{visible.length} holdings</span>
          <span>Day change</span>
        </div>

        {visible.map((h) => {
          const pct = h.quote?.day_change_pct
          return (
            <button
              key={h.con_id}
              type="button"
              className={`holding-item ${h.con_id === selectedId ? 'selected' : ''}`}
              aria-current={h.con_id === selectedId ? 'true' : undefined}
              onClick={() => onSelect(h.con_id)}
            >
              <div className="holding-names">
                <div className="holding-symbol">{h.symbol}</div>
                <div className="company" title={h.name_truncated ? 'Name shortened by IB' : undefined}>
                  {companyName(h)}
                </div>
              </div>
              <div className="holding-price num">
                {formatNumber(h.last)}
                <span className={`change-pill ${trendClass(pct)}`}>{formatPercent(pct)}</span>
              </div>
            </button>
          )
        })}

        {visible.length === 0 && <p className="empty">No matching holdings.</p>}
      </div>

      <div
        className="resize-handle"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize holdings list"
        aria-valuemin={MIN_WIDTH}
        aria-valuemax={MAX_WIDTH}
        aria-valuenow={width}
        tabIndex={0}
        onPointerDown={startDrag}
        onPointerMove={moveDrag}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onKeyDown={handleKey}
      />
    </aside>
  )
}

export default HoldingsList
