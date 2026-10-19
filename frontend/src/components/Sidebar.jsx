import { GridIcon, ListIcon, OrdersIcon, RiskIcon, SearchIcon } from './icons.jsx'
import { IN_APP } from '../lib/api.js'
import AccountCard from './AccountCard.jsx'
import SidebarWatchlists from './SidebarWatchlists.jsx'

// The connection in words for the account card, and its dot colour
function connectionText(health, login) {
  if (IN_APP && login?.state === 'session_ended') return { dot: 'warn', text: 'Session ended' }
  if (health === null) return { dot: '', text: 'Checking…' }
  if (health === 'starting') return { dot: '', text: 'Starting…' }
  if (health === 'offline') return { dot: 'bad', text: IN_APP ? 'Not running' : 'Backend offline' }
  if (!health.connected) return { dot: 'bad', text: 'Disconnected' }
  return { dot: 'ok', text: 'Connected' }
}

function Sidebar({ page, onNavigate, watchlistId, onOpenWatchlist, onWatchlistDeleted, health, login, trading, username, savedMode, onOpenSettings, onReconnect, onSignOut }) {
  const connection = connectionText(health, login)
  // Paper or live: from the connected account (toolbar badge), else the mode last signed in with
  const kind = trading && trading.account !== 'unknown' ? trading.account : IN_APP ? savedMode : null
  const mode = kind === 'live' ? 'Live' : kind === 'paper' ? 'Paper' : null
  const signedIn = ['signed_in', 'session_ended'].includes(login?.state)
  const name = IN_APP ? (signedIn && username) || 'Not signed in' : 'IB Gateway'

  // The browser version can't control the Mac app's Gateway, so its menu only has Settings
  const items = [{ label: 'Settings…', shortcut: IN_APP ? '⌘,' : null, onSelect: onOpenSettings }]
  if (IN_APP) {
    items.push(
      {
        label: 'Reconnect',
        // The password isn't stored, so reconnecting means signing in again: offered when the session ended
        disabled: login?.state !== 'session_ended',
        disabledReason: login?.state === 'session_ended' ? undefined : 'Only needed when the IBKR session has ended',
        onSelect: onReconnect,
      },
      'separator',
      { label: 'Sign Out', disabled: !signedIn, onSelect: onSignOut },
    )
  }

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
        <button
          type="button"
          className={`sidebar-item ${page === 'risk' ? 'active' : ''}`}
          aria-current={page === 'risk' ? 'page' : undefined}
          onClick={() => onNavigate('risk')}
        >
          <RiskIcon /> Risk
        </button>

        <SidebarWatchlists
          activeId={page === 'watchlist' ? watchlistId : null}
          onOpen={onOpenWatchlist}
          onDeleted={onWatchlistDeleted}
        />

        <div className="sidebar-spacer" />
        <AccountCard
          name={name}
          status={mode ? `${mode} · ${connection.text}` : connection.text}
          dot={connection.dot}
          menuTitle={name}
          menuStatus={mode ? `${mode} account · ${connection.text}` : connection.text}
          items={items}
        />
      </nav>
    </aside>
  )
}

export default Sidebar
