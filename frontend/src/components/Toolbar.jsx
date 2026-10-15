import { RefreshIcon } from './icons.jsx'

const APPEARANCES = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
]

function Toolbar({ title, subtitle, loading, onRefresh, appearance, onAppearanceChange }) {
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
