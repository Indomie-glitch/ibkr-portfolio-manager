import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchPrices, searchStocks } from '../lib/api.js'
import { addToWatchlist, removeFromWatchlist, useNamingWatchlist } from '../lib/watchlists.js'
import { useResizableWidth } from '../hooks/useResizableWidth.js'
import { WATCHLIST_LIST } from '../lib/listPanes.js'
import HoldingDetail from '../components/HoldingDetail.jsx'
import PopupMenu from '../components/PopupMenu.jsx'
import StockRow from '../components/StockRow.jsx'
import { PlusIcon, SearchIcon, StarIcon } from '../components/icons.jsx'

const MARKETS = ['All', 'ASX', 'US']
// Wait for a pause in typing before asking IB (it allows about one search a second)
const SEARCH_DELAY_MS = 350

// Search results under the field, each with an Add button (Figma M6 / 10 node 42:1357)
function AddStockPopover({ query, list, onAdded }) {
  const [search, setSearch] = useState({ query: '', items: [], error: null })

  useEffect(() => {
    let ignore = false
    const timer = setTimeout(() => {
      searchStocks(query)
        .then((items) => !ignore && setSearch({ query, items, error: null }))
        .catch((err) => !ignore && setSearch({ query, items: [], error: err.message }))
    }, SEARCH_DELAY_MS)
    return () => {
      ignore = true
      clearTimeout(timer)
    }
  }, [query])

  const inList = new Set(list.stocks.map((s) => s.con_id))
  let body
  if (search.query !== query) body = <p className="add-stock-note">Searching…</p>
  else if (search.error) body = <p className="add-stock-note">{search.error}</p>
  else if (search.items.length === 0) body = <p className="add-stock-note">No ASX or US stocks found.</p>
  else {
    body = search.items.map((s) => (
      <div key={s.con_id} className="add-stock-result">
        <div className="add-stock-text">
          <span className="add-stock-symbol">{s.symbol}</span>
          <span className="add-stock-name">
            {s.name} · {s.exchange}
          </span>
        </div>
        {inList.has(s.con_id) ? (
          <span className="add-stock-added">Added</span>
        ) : (
          <button type="button" className="add-stock-button" aria-label={`Add ${s.symbol}`} onClick={() => onAdded(s)}>
            <PlusIcon size={12} strokeWidth={1.6} /> Add
          </button>
        )}
      </div>
    ))
  }
  return (
    <div className="add-stock-popover" role="region" aria-label="Search results" aria-live="polite">
      {body}
    </div>
  )
}

// A watchlist's page (#88, Figma M6 / 6 node 36:754): its stocks with price and day change, and the
// selected stock's detail, or the empty state (M6 / 8 node 42:857)
function Watchlist({ list, holdings, refreshKey, trading, onTrade }) {
  const [query, setQuery] = useState('')
  const [market, setMarket] = useState('All')
  const [prices, setPrices] = useState({})
  const [selectedId, setSelectedId] = useState(null)
  // Right-click menu on a row: { stock, x, y } or null
  const [menu, setMenu] = useState(null)
  const closeMenu = useCallback(() => setMenu(null), [])
  const searchRef = useRef(null)
  const { paneProps, handleProps } = useResizableWidth(WATCHLIST_LIST, 'Resize watchlist')

  const empty = list.stocks.length === 0
  // An empty watchlist starts in the search field, ready to add stocks, once it has been named in
  // the sidebar (taking the focus earlier would end the naming)
  const naming = useNamingWatchlist() === list.id
  useEffect(() => {
    if (empty && !naming) searchRef.current?.focus()
  }, [empty, naming, list.id])

  // Prices for the stocks that don't have one yet (refreshed with the rest of the app)
  const missingIds = list.stocks.map((s) => s.con_id).filter((id) => !(id in prices)).join(',')
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

  const owned = new Map(holdings.map((h) => [h.con_id, h]))
  const visible = list.stocks.filter((s) => market === 'All' || s.market === market)
  // The selected stock, or the first one, so the detail is never blank while the list has stocks
  const selected = visible.find((s) => s.con_id === selectedId) ?? visible[0] ?? null
  let detail = null
  if (selected) {
    const quote = prices[selected.con_id] ?? null
    detail = owned.get(selected.con_id) ?? { ...selected, quote, last: quote?.last, not_owned: true }
  }

  function add(stock) {
    addToWatchlist(list.id, stock)
    setSelectedId(stock.con_id)
  }

  const q = query.trim()
  const count = `${list.stocks.length} ${list.stocks.length === 1 ? 'stock' : 'stocks'}`

  return (
    <div className="positions-page">
      <aside {...paneProps}>
        <div className="holdings-list">
          <div className="add-stock">
            <label className="search-field">
              <SearchIcon />
              <input
                ref={searchRef}
                type="search"
                placeholder="Add a stock to this watchlist"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Escape' && setQuery('')}
                aria-label="Add a stock to this watchlist"
              />
            </label>
            {q && <AddStockPopover query={q} list={list} onAdded={add} />}
          </div>

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
            <span>{market === 'All' ? count : `${visible.length} of ${count}`}</span>
            <span>Day change</span>
          </div>

          {visible.map((s) => (
            <StockRow
              key={s.con_id}
              stock={{ ...s, owned: owned.has(s.con_id) }}
              quote={owned.get(s.con_id)?.quote ?? prices[s.con_id]}
              selected={s.con_id === selected?.con_id}
              onSelect={() => setSelectedId(s.con_id)}
              onContextMenu={(e) => {
                e.preventDefault()
                setMenu({ stock: s, x: e.clientX, y: e.clientY })
              }}
            />
          ))}
          {!empty && visible.length === 0 && <p className="empty">No {market} stocks in this watchlist.</p>}
        </div>
      </aside>
      {/* Outside the pane, so it stays at the detail's edge (and can be dragged) when the list is hidden */}
      <div className="resize-divider">
        <div {...handleProps} />
      </div>

      {menu && (
        <PopupMenu
          label={`${menu.stock.symbol} options`}
          items={[{ label: `Remove from ${list.name}`, onSelect: () => removeFromWatchlist(list.id, menu.stock.con_id) }]}
          onClose={closeMenu}
          className="context-menu"
          style={{ left: menu.x, top: menu.y }}
        />
      )}

      {detail ? (
        <HoldingDetail key={detail.con_id} holding={detail} refreshKey={refreshKey} trading={trading} onTrade={onTrade} />
      ) : (
        <div className="watchlist-empty">
          <span className="watchlist-empty-icon">
            <StarIcon size={32} />
          </span>
          <h2>{empty ? `${list.name} is empty` : `No ${market} stocks`}</h2>
          <p>
            {empty
              ? 'Use the search field to add stocks, or drag them here from Positions, Markets or another watchlist.'
              : `Choose All to see every stock in ${list.name}.`}
          </p>
        </div>
      )}
    </div>
  )
}

export default Watchlist
