import { RefreshIcon } from './icons.jsx'

function Toolbar({ title, subtitle, loading, onRefresh }) {
  return (
    <header className="toolbar">
      <div>
        <h1 className="toolbar-title">{title}</h1>
        <p className="toolbar-subtitle">{subtitle}</p>
      </div>
      <div className="spacer" />
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
