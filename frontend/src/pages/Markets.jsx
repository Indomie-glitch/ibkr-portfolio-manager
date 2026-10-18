import { useEffect, useState } from 'react'
import { fetchPrices, searchStocks } from '../lib/api.js'
import { useResizableWidth } from '../hooks/useResizableWidth.js'
import { MARKETS_LIST } from '../lib/listPanes.js'
import HoldingDetail from '../components/HoldingDetail.jsx'
import StockRow from '../components/StockRow.jsx'
import { SearchIcon } from '../components/icons.jsx'

const MARKETS = ['All', 'ASX', 'US']
const RECENT_KEY = 'recentStocks'
const RECENT_LIMIT = 5
// Wait for a pause in typing before asking IB (it allows about one search a second)
const SEARCH_DELAY_MS = 350

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

function Markets({ holdings, refreshKey, trading, onTrade }) {
  const [query, setQuery] = useState('')
  const [market, setMarket] = useState('All')
  // The results belong to search.query, so old results never show under new text
  const [search, setSearch] = useState({ query: '', items: [], error: null })
  const [prices, setPrices] = useState({})
  const [recent, setRecent] = useState(loadRecent)
  const [selected, setSelected] = useState(null)
  const { paneProps, handleProps } = useResizableWidth(MARKETS_LIST, 'Resize search list')

  const q = query.trim()
  useEffect(() => {
    if (!q) return
    let ignore = false
    const timer = setTimeout(() => {
      searchStocks(q)
        .then((items) => !ignore && setSearch({ query: q, items, error: null }))
        .catch((err) => !ignore && setSearch({ query: q, items: [], error: err.message }))
    }, SEARCH_DELAY_MS)
    return () => {
      ignore = true
      clearTimeout(timer)
    }
  }, [q])

  const searching = q !== '' && search.query !== q
  const results = q && !searching ? search.items.filter((s) => market === 'All' || s.market === market) : []

  // Prices for the rows on screen that don't have one yet (refreshed with the rest of the app)
  const shown = [...results, ...recent]
  const missingIds = [...new Set(shown.map((s) => s.con_id))].filter((id) => !(id in prices)).join(',')
  useEffect(() => {
    if (!missingIds) return
    let ignore = false
    fetchPrices(missingIds)
      .then((quotes) => {
        if (ignore) return
        setPrices((old) => ({ ...old, ...Object.fromEntries(quotes.map((p) => [p.con_id, p])) }))
      })
      .catch(() => {}) // rows just show no price
    return () => {
      ignore = true
    }
  }, [missingIds])

  useEffect(() => {
    // New figures on Refresh: fetch the prices again
    // oxlint-disable-next-line react/set-state-in-effect
    setPrices({})
  }, [refreshKey])

  function select(stock) {
    setSelected(stock)
    const entry = { con_id: stock.con_id, symbol: stock.symbol, name: stock.name, exchange: stock.exchange,
      currency: stock.currency, market: stock.market }
    const next = [entry, ...recent.filter((r) => r.con_id !== stock.con_id)].slice(0, RECENT_LIMIT)
    setRecent(next)
    saveRecent(next)
  }

  function clearRecent() {
    setRecent([])
    saveRecent([])
  }

  const owned = new Map(holdings.map((h) => [h.con_id, h]))
  const withOwned = (stock) => ({ ...stock, owned: owned.has(stock.con_id) })
  // A holding shows its full detail; any other stock shows the same detail without a position
  let detail = null
  if (selected) {
    const quote = prices[selected.con_id] ?? null
    detail = owned.get(selected.con_id) ?? { ...selected, quote, last: quote?.last, not_owned: true }
  }

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

          <div className="list-filter">
            <div className="segmented" role="group" aria-label="Market">
              {MARKETS.map((m) => (
                <button key={m} type="button" aria-pressed={market === m} onClick={() => setMarket(m)}>
                  {m}
                </button>
              ))}
            </div>
          </div>

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
