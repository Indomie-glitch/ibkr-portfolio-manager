import { GridIcon, ListIcon, SparklesIcon, TradeIcon } from './icons.jsx'
import { IN_APP } from '../api.js'

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
        <button type="button" className="sidebar-item" disabled>
          <SparklesIcon /> AI Summaries <span className="soon-pill">Soon</span>
        </button>

        <div className="sidebar-section">Trading</div>
        <button type="button" className="sidebar-item" disabled>
          <TradeIcon /> Trade <span className="soon-pill">Soon</span>
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
