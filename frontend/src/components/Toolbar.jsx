import { APPEARANCES } from '../appearance.js'
import { RefreshIcon } from './icons.jsx'

// The account badge's tooltip: whether orders are possible and the order limit
function tradingTitle(trading) {
  if (!trading.can_trade) return trading.reason
  const limit = trading.max_order_value.toLocaleString(undefined, { maximumFractionDigits: 0 })
  return `Trading is on (${trading.mode}). Orders up to ${limit} in the account's currency.`
}

function Toolbar({ title, subtitle, loading, onRefresh, appearance, onAppearanceChange, trading }) {
  return (
    <header className="toolbar" data-tauri-drag-region>
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
      <div className="segmented appearance-control" role="group" aria-label="Appearance">
        {APPEARANCES.map((a) => (
          <button
            key={a.value}
            type="button"
            aria-pressed={appearance === a.value}
            onClick={() => onAppearanceChange(a.value)}
          >
            {a.label}
          </button>
        ))}
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
