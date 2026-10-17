import { GearIcon, GridIcon, ListIcon, OrdersIcon, SearchIcon, SparklesIcon } from './icons.jsx'
import { IN_APP } from '../lib/api.js'

function connectionText(health) {
  if (health === null) return { dot: '', title: 'Checking…', detail: 'Contacting the backend' }
  if (health === 'starting') return { dot: '', title: 'Starting…', detail: 'Starting the background service' }
  if (health === 'offline') {
    return IN_APP
      ? { dot: 'bad', title: 'Not running', detail: 'Quit and reopen the app' }
      : { dot: 'bad', title: 'Backend offline', detail: 'Start uvicorn on port 8000' }
  }
  if (!health.connected) return { dot: 'bad', title: 'Disconnected', detail: 'IB Gateway is not connected' }
  return { dot: 'ok', title: 'Connected', detail: 'IB Gateway · Paper account' }
}

function Sidebar({ page, onNavigate, health }) {
  const status = connectionText(health)

  return (
    <aside className="sidebar">
      <nav className="sidebar-panel" aria-label="Main">
        <div className="sidebar-drag" data-tauri-drag-region />
        <div className="sidebar-section">Portfolio</div>
        <button
          type="button"
          className={`sidebar-item ${page === 'overview' ? 'active' : ''}`}
          aria-current={page === 'overview' ? 'page' : undefined}
          onClick={() => onNavigate('overview')}
        >
          <GridIcon /> Overview
        </button>
        <button
          type="button"
          className={`sidebar-item ${page === 'positions' ? 'active' : ''}`}
          aria-current={page === 'positions' ? 'page' : undefined}
          onClick={() => onNavigate('positions')}
        >
          <ListIcon /> Positions
        </button>
        <button
          type="button"
          className={`sidebar-item ${page === 'markets' ? 'active' : ''}`}
          aria-current={page === 'markets' ? 'page' : undefined}
          onClick={() => onNavigate('markets')}
        >
          <SearchIcon /> Markets
        </button>
        <button
          type="button"
          className={`sidebar-item ${page === 'orders' ? 'active' : ''}`}
          aria-current={page === 'orders' ? 'page' : undefined}
          onClick={() => onNavigate('orders')}
        >
          <OrdersIcon /> Orders
        </button>
        <button type="button" className="sidebar-item" disabled>
          <SparklesIcon /> AI Summaries <span className="soon-pill">Soon</span>
        </button>

        <div className="sidebar-section">App</div>
        <button
          type="button"
          className={`sidebar-item ${page === 'settings' ? 'active' : ''}`}
          aria-current={page === 'settings' ? 'page' : undefined}
          onClick={() => onNavigate('settings')}
        >
          <GearIcon /> Settings
        </button>

        <div className="connection" role="status">
          <div className="connection-row">
            <span className={`status-dot ${status.dot}`} /> {status.title}
          </div>
          <div className="connection-detail">{status.detail}</div>
        </div>
      </nav>
    </aside>
  )
}

export default Sidebar
