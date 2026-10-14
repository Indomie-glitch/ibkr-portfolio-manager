import { useEffect, useState } from 'react'
import { fetchAccount, fetchPositions } from './api.js'
import AccountSummary from './components/AccountSummary.jsx'
import PositionsTable from './components/PositionsTable.jsx'

function App() {
  const [account, setAccount] = useState(null)
  const [positions, setPositions] = useState([])
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  // Bumping this number re-runs the effect below, which refetches the data
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    let ignore = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [accountData, positionsData] = await Promise.all([
          fetchAccount(),
          fetchPositions(),
        ])
        if (!ignore) {
          setAccount(accountData)
          setPositions(positionsData)
        }
      } catch (err) {
        if (!ignore) setError(err.message)
      } finally {
        if (!ignore) setLoading(false)
      }
    }

    load()
    return () => {
      ignore = true
    }
  }, [refreshKey])

  return (
    <main className="page">
      <header className="header">
        <h1>Portfolio</h1>
        <button
          type="button"
          onClick={() => setRefreshKey((k) => k + 1)}
          disabled={loading}
        >
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </header>

      {error && (
        <div className="error" role="alert">
          <strong>Could not load data.</strong> Make sure the backend is
          running on port 8000 and IB Gateway is logged in.
          <div className="error-detail">{error}</div>
        </div>
      )}

      {account && (
        <>
          <AccountSummary account={account} />
          <h2>Positions</h2>
          <PositionsTable positions={positions} />
        </>
      )}
    </main>
  )
}

export default App
