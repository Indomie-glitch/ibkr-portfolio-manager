import { formatNumber, formatPercent, trendClass } from '../lib/format.js'

// One stock in a list (Markets, watchlists): the Positions list's row style, with "Owned" after the
// exchange for holdings. onContextMenu is for right-click menus (e.g. Remove from a watchlist).
function StockRow({ stock, quote, selected, onSelect, onContextMenu }) {
  const pct = quote?.day_change_pct
  return (
    <button
      type="button"
      className={`holding-item ${selected ? 'selected' : ''}`}
      aria-current={selected ? 'true' : undefined}
      onClick={() => onSelect(stock)}
      onContextMenu={onContextMenu}
    >
      <div className="holding-names">
        <div className="holding-symbol">{stock.symbol}</div>
        <div className="company">
          {stock.name} · {stock.exchange}
          {stock.owned ? ' · Owned' : ''}
        </div>
      </div>
      <div className="holding-price num">
        {formatNumber(quote?.last)}
        <span className={`change-pill ${trendClass(pct)}`}>{formatPercent(pct)}</span>
      </div>
    </button>
  )
}

export default StockRow
