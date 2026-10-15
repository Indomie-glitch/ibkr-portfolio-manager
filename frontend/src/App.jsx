import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchAccount, fetchHealth, fetchPositions, fetchQuotes } from './api.js'
import { formatTime } from './format.js'
import { buildHoldings } from './holdings.js'
import Sidebar from './components/Sidebar.jsx'
import Toolbar from './components/Toolbar.jsx'
import Overview from './pages/Overview.jsx'
import Positions from './pages/Positions.jsx'

const AUTO_REFRESH_MS = 60_000

function App() {
  const [page, setPage] = useState('overview')
  const [selectedId, setSelectedId] = useState(null)
  const [account, setAccount] = useState(null)
  const [positions, setPositions] = useState([])
  const [quotes, setQuotes] = useState([])
  // null = not checked yet, 'offline' = backend unreachable, otherwise the /health response
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [updatedAt, setUpdatedAt] = useState(null)
  // Goes up after every successful load so child components (the chart) can refetch too
  const [dataVersion, setDataVersion] = useState(0)
  // Only the newest request may update state, in case an older one finishes later
  const latestRequest = useRef(0)

  // Fetches everything and swaps in the new numbers. Used by the first load, the
  // 60-second auto refresh, and the Refresh button (which also shows a spinner).
  const load = useCallback(async () => {
    const requestId = ++latestRequest.current

    fetchHealth()
      .then((h) => requestId === latestRequest.current && setHealth(h))
      .catch(() => requestId === latestRequest.current && setHealth('offline'))

    try {
      const [accountData, positionsData, quotesData] = await Promise.all([
        fetchAccount(),
        fetchPositions(),
        fetchQuotes(),
      ])
      if (requestId !== latestRequest.current) return
      setAccount(accountData)
      setPositions(positionsData)
      setQuotes(quotesData)
      setError(null)
      setUpdatedAt(new Date())
      setDataVersion((v) => v + 1)
    } catch (err) {
      if (requestId === latestRequest.current) setError(err.message)
    } finally {
      if (requestId === latestRequest.current) setLoading(false)
    }
  }, [])

  // First load, then refresh every minute while the tab is visible
  useEffect(() => {
    // load() only sets state after its fetches resolve, so this is not a synchronous setState
    // oxlint-disable-next-line react/set-state-in-effect
    load()
    const timer = setInterval(() => {
      if (!document.hidden) load()
    }, AUTO_REFRESH_MS)
    return () => clearInterval(timer)
  }, [load])

  function openHolding(conId) {
    setSelectedId(conId)
    setPage('positions')
  }

  const { holdings } = buildHoldings(positions, quotes, account)
  const updated = updatedAt ? `Updated ${formatTime(updatedAt)}` : 'Loading…'
  const subtitle =
    page === 'overview' ? `${updated} · Prices delayed 15 min` : `${holdings.length} holdings · ${updated}`

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
        />

        {error && (
          <div className="page-message">
            <div className="error" role="alert">
              <strong>Could not load data.</strong> Make sure the backend is running on port 8000 and IB
              Gateway is logged in.
              <div className="error-detail">{error}</div>
            </div>
          </div>
        )}

        {account && page === 'overview' && (
          <div className="page-body">
            <Overview account={account} holdings={holdings} onOpenHolding={openHolding} />
          </div>
        )}

        {account && page === 'positions' && (
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
