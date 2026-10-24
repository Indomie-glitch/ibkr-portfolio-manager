import { useListCollapsed, toggleList } from '../hooks/useResizableWidth.js'
import { RefreshIcon, SidebarIcon } from './icons.jsx'

// The account badge's tooltip: whether orders are possible and the order limit
function tradingTitle(trading) {
  if (!trading.can_trade) return trading.reason
  const limit = trading.max_order_value.toLocaleString(undefined, { maximumFractionDigits: 0 })
  const real = trading.account === 'live' ? ' Orders use real money.' : ''
  return `Connected to your ${trading.account_label.toLowerCase()}.${real} Orders up to ${limit} in the account's currency.`
}

// Shows or hides the page's list (Positions, Markets); ⌘⌥S does the same (#91)
function ListToggle({ listKey }) {
  const collapsed = useListCollapsed(listKey)
  const label = collapsed ? 'Show list' : 'Hide list'
  return (
    <button
      type="button"
      className="button icon-only"
      aria-label={label}
      aria-pressed={!collapsed}
      title={`${label} (⌘⌥S)`}
      onClick={() => toggleList(listKey)}
    >
      <SidebarIcon />
    </button>
  )
}

// The theme is set in Settings → Appearance only (as in Figma, the toolbar has no theme control)
function Toolbar({ title, subtitle, loading, onRefresh, trading, listKey, back }) {
  return (
    <header className="toolbar" data-tauri-drag-region>
      {listKey && <ListToggle listKey={listKey} />}
      {back && (
        <button type="button" className="toolbar-back" onClick={back.onClick} aria-label={`Back to ${back.label}`}>
          <span aria-hidden="true">‹</span> {back.label}
        </button>
      )}
      <div>
        <h1 className="toolbar-title">{title}</h1>
        <p className="toolbar-subtitle">{subtitle}</p>
      </div>
      <div className="spacer" />
      {trading && trading.account !== 'unknown' && (
        <div className={`badge badge-account ${trading.account}`} title={tradingTitle(trading)}>
          <span className="badge-dot" /> {trading.account_label}
        </div>
      )}
      <div className="badge" title="IB prices are delayed about 15 minutes without a market data subscription">
        <span className="badge-dot" /> Delayed data
      </div>
      <button
        type="button"
        className={`button ${loading ? 'loading' : ''}`}
        onClick={onRefresh}
        disabled={loading}
      >
        <RefreshIcon /> {loading ? 'Refreshing…' : 'Refresh'}
      </button>
    </header>
  )
}

export default Toolbar
