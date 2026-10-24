import { useEffect, useRef, useState } from 'react'
import { stockDetail } from '../lib/holdings.js'
import { usePrices } from '../hooks/usePrices.js'
import { useResizableWidth } from '../hooks/useResizableWidth.js'
import { useStockSearch } from '../hooks/useStockSearch.js'
import { MARKETS_LIST } from '../lib/listPanes.js'
import HoldingDetail from '../components/HoldingDetail.jsx'
import MarketFilter from '../components/MarketFilter.jsx'
import StockRow from '../components/StockRow.jsx'
import { SearchIcon } from '../components/icons.jsx'

const RECENT_KEY = 'recentStocks'
const RECENT_LIMIT = 5

function loadRecent() {
  try {
    const saved = JSON.parse(localStorage.getItem(RECENT_KEY))
    return Array.isArray(saved) ? saved : []
  } catch {
    return []
  }
}

function saveRecent(items) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(items))
  } catch {
    // storage blocked; the list just won't be remembered
  }
}

function Markets({ holdings, refreshKey, trading, onTrade, openRequest }) {
  const [query, setQuery] = useState('')
  const [market, setMarket] = useState('All')
  const [recent, setRecent] = useState(loadRecent)
  const [selected, setSelected] = useState(null)
  const { paneProps, handleProps } = useResizableWidth(MARKETS_LIST, 'Resize search list')

  const q = query.trim()
  const search = useStockSearch(q)
  const searching = search.searching
  const results = search.items.filter((s) => market === 'All' || s.market === market)

  // Prices for the rows on screen (refreshed with the rest of the app)
  const prices = usePrices([...results, ...recent].map((s) => s.con_id), refreshKey)

  function select(stock) {
    setSelected(stock)
    const entry = { con_id: stock.con_id, symbol: stock.symbol, name: stock.name, exchange: stock.exchange,
      currency: stock.currency, market: stock.market }
    const next = [entry, ...recent.filter((r) => r.con_id !== stock.con_id)].slice(0, RECENT_LIMIT)
    setRecent(next)
    saveRecent(next)
  }

  // A stock opened from another page (Connections, #114) becomes the selection and joins Recent
  const handled = useRef(null)
  useEffect(() => {
    if (!openRequest || handled.current === openRequest.nonce) return
    handled.current = openRequest.nonce
    // oxlint-disable-next-line react/set-state-in-effect
    select(openRequest.stock)
  })

  function clearRecent() {
    setRecent([])
    saveRecent([])
  }

  const owned = new Map(holdings.map((h) => [h.con_id, h]))
  const withOwned = (stock) => ({ ...stock, owned: owned.has(stock.con_id) })
  // A holding shows its full detail; any other stock shows the same detail without a position
  const detail = stockDetail(selected, owned, prices)

  return (
    <div className="positions-page">
      <aside {...paneProps}>
        <div className="holdings-list">
          <label className="search-field">
            <SearchIcon />
            <input
              type="search"
              placeholder="Search by symbol or company"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search stocks"
            />
          </label>

          <MarketFilter market={market} onChange={setMarket} />

          {q && (
            <>
              <div className="list-meta">
                <span>{searching ? 'Searching…' : `${results.length} ${results.length === 1 ? 'result' : 'results'}`}</span>
                <span>Day change</span>
              </div>
              {results.map((s) => (
                <StockRow key={s.con_id} stock={withOwned(s)} quote={prices[s.con_id]}
                  selected={s.con_id === selected?.con_id} onSelect={select} />
              ))}
              {!searching && search.error && <p className="empty">{search.error}</p>}
              {!searching && !search.error && results.length === 0 && <p className="empty">No ASX or US stocks found.</p>}
            </>
          )}

          {recent.length > 0 && (
            <>
              <div className="list-meta recent-header">
                <span>Recently viewed</span>
                <button type="button" className="link-button" onClick={clearRecent}>
                  Clear
                </button>
              </div>
              {recent.map((s) => (
                <StockRow key={s.con_id} stock={withOwned(s)} quote={prices[s.con_id]}
                  selected={!q && s.con_id === selected?.con_id} onSelect={select} />
              ))}
            </>
          )}
        </div>
      </aside>
      {/* Outside the pane, so it stays at the detail's edge (and can be dragged) when the list is hidden */}
      <div className="resize-divider">
        <div {...handleProps} />
      </div>

      {detail ? (
        <HoldingDetail key={detail.con_id} holding={detail} refreshKey={refreshKey} trading={trading} onTrade={onTrade} />
      ) : (
        <p className="empty markets-empty">Search for any stock on the ASX or US exchanges.</p>
      )}
    </div>
  )
}

export default Markets
