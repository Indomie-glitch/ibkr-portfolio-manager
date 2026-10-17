import { useState } from 'react'
import { companyName, formatNumber, formatPercent, trendClass } from '../lib/format.js'
import { SearchIcon } from './icons.jsx'
import { useResizableWidth } from '../hooks/useResizableWidth.js'

const MARKETS = ['All', 'ASX', 'US']

function HoldingsList({ holdings, selectedId, onSelect }) {
  const [query, setQuery] = useState('')
  const [market, setMarket] = useState('All')
  const [width, handleProps] = useResizableWidth('holdingsListWidth', 'Resize holdings list')

  const q = query.trim().toLowerCase()
  const visible = holdings.filter(
    (h) =>
      (market === 'All' || h.market === market) &&
      (!q || h.symbol.toLowerCase().includes(q) || h.name.toLowerCase().includes(q)),
  )

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

      <div {...handleProps} />
    </aside>
  )
}

export default HoldingsList
