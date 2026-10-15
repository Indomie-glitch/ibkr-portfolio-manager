import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchAccount, fetchHealth, fetchPositions, fetchQuotes } from './api.js'
import { formatTime } from './format.js'
import { buildHoldings } from './holdings.js'
import { useAppearance } from './appearance.js'
import ConnectionMessage from './components/ConnectionMessage.jsx'
import Sidebar from './components/Sidebar.jsx'
import Toolbar from './components/Toolbar.jsx'
import Overview from './pages/Overview.jsx'
import Positions from './pages/Positions.jsx'

const AUTO_REFRESH_MS = 60_000
// /health is a cheap local request, so check it often to notice drops and recoveries quickly
const HEALTH_CHECK_MS = 5_000

// 'checking' before the first answer, 'offline' if the backend is unreachable,
// 'disconnected' if the backend is up but IB Gateway isn't, otherwise 'connected'
function connectionState(health) {
  if (health === null) return 'checking'
  if (health === 'offline') return 'offline'
  return health.connected ? 'connected' : 'disconnected'
}

function App() {
  const [page, setPage] = useState('overview')
  const [selectedId, setSelectedId] = useState(null)
  const [account, setAccount] = useState(null)
  const [positions, setPositions] = useState([])
  const [quotes, setQuotes] = useState([])
  // null = not checked yet, 'offline' = backend unreachable, otherwise the /health response
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  // true only while a Refresh-button load runs (it shows the spinner)
  const [loading, setLoading] = useState(false)
  const [updatedAt, setUpdatedAt] = useState(null)
  // Goes up after every successful load so child components (the chart) can refetch too
  const [dataVersion, setDataVersion] = useState(0)
  // Only the newest request may update state, in case an older one finishes later
  const latestRequest = useRef(0)
  const [appearance, setAppearance] = useAppearance()

  // Checks the connection, then fetches everything and swaps in the new numbers.
  // Used by the first load, the timers below, and the Refresh button (which also shows a spinner).
  const load = useCallback(async () => {
    const requestId = ++latestRequest.current
    const isLatest = () => requestId === latestRequest.current

    try {
      // Ask about the connection first; there's no point asking for data IB can't give
      let healthData
      try {
        healthData = await fetchHealth()
      } catch {
        healthData = 'offline'
      }
      if (!isLatest()) return
      setHealth(healthData)
      if (connectionState(healthData) !== 'connected') return

      const [accountData, positionsData, quotesData] = await Promise.all([
        fetchAccount(),
        fetchPositions(),
        fetchQuotes(),
      ])
      if (!isLatest()) return
      setAccount(accountData)
      setPositions(positionsData)
      setQuotes(quotesData)
      setError(null)
      setUpdatedAt(new Date())
      setDataVersion((v) => v + 1)
    } catch (err) {
      if (!isLatest()) return
      // 503 = Gateway dropped between the health check and the data request
      if (err.status === 503) setHealth({ connected: false })
      else setError(err.message)
    } finally {
      if (isLatest()) setLoading(false)
    }
  }, [])

  const checkHealth = useCallback(async () => {
    let healthData
    try {
      healthData = await fetchHealth()
    } catch {
      healthData = 'offline'
    }
    // Keep the old value if nothing changed, so React can skip re-rendering
    setHealth((old) => (connectionState(old) === connectionState(healthData) ? old : healthData))
  }, [])

  const connection = connectionState(health)
  const connected = connection === 'connected'

  // Watch the connection every few seconds while the tab is visible
  useEffect(() => {
    // These calls only set state after a fetch resolves, so they aren't synchronous setStates
    // oxlint-disable-next-line react/set-state-in-effect
    checkHealth()
    const timer = setInterval(() => {
      if (!document.hidden) checkHealth()
    }, HEALTH_CHECK_MS)
    return () => clearInterval(timer)
  }, [checkHealth])

  // Load data as soon as we're connected (at start and after every reconnect), then every minute.
  // When the connection drops, the cleanup stops the timer until it comes back.
  useEffect(() => {
    if (!connected) return
    // oxlint-disable-next-line react/set-state-in-effect
    load()
    const timer = setInterval(() => {
      if (!document.hidden) load()
    }, AUTO_REFRESH_MS)
    return () => clearInterval(timer)
  }, [connected, load])

  function openHolding(conId) {
    setSelectedId(conId)
    setPage('positions')
  }

  const { holdings } = buildHoldings(positions, quotes, account)
  const updated = updatedAt ? `Updated ${formatTime(updatedAt)}` : 'Loading…'
  let subtitle =
    page === 'overview' ? `${updated} · Prices delayed 15 min` : `${holdings.length} holdings · ${updated}`
  if (connection === 'disconnected') subtitle = 'Waiting for IB Gateway…'
  if (connection === 'offline') subtitle = 'Waiting for the backend…'
  // Only show the cards when the data is current; never stale numbers while disconnected
  const showData = connected && account

  return (
    <div className="app">
      <Sidebar page={page} onNavigate={setPage} health={health} />

      <main className="content">
        <Toolbar
          title={page === 'overview' ? 'Overview' : 'Positions'}
          subtitle={subtitle}
          loading={loading}
          onRefresh={() => {
            setLoading(true)
            load()
          }}
          appearance={appearance}
          onAppearanceChange={setAppearance}
        />

        {(connection === 'offline' || connection === 'disconnected') && (
          <ConnectionMessage state={connection} lastUpdated={updatedAt} />
        )}

        {connected && error && (
          <div className="page-message">
            <div className="error" role="alert">
              <strong>Could not load data.</strong> Make sure the backend is running on port 8000 and IB
              Gateway is logged in.
              <div className="error-detail">{error}</div>
            </div>
          </div>
        )}

        {showData && page === 'overview' && (
          <div className="page-body">
            <Overview account={account} holdings={holdings} onOpenHolding={openHolding} />
          </div>
        )}

        {showData && page === 'positions' && (
          <Positions
            holdings={holdings}
            selectedId={selectedId}
            onSelect={setSelectedId}
            refreshKey={dataVersion}
          />
        )}
      </main>
    </div>
  )
}

export default App
