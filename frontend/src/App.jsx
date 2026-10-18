import { useCallback, useEffect, useRef, useState } from 'react'
import { IN_APP, fetchAccount, fetchHealth, fetchPositions, fetchQuotes, fetchTradingStatus } from './lib/api.js'
import { formatTime } from './lib/format.js'
import { buildHoldings } from './lib/holdings.js'
import { useAppearance } from './hooks/appearance.js'
import { sizeWindowFor } from './desktop/appWindow.js'
import ConnectionMessage from './components/ConnectionMessage.jsx'
import SessionBanner from './components/SessionBanner.jsx'
import UpdatePrompt from './components/UpdatePrompt.jsx'
import Sidebar from './components/Sidebar.jsx'
import Toolbar from './components/Toolbar.jsx'
import Overview from './pages/Overview.jsx'
import OrderConfirm from './components/OrderConfirm.jsx'
import OrderTicket from './components/OrderTicket.jsx'
import Markets from './pages/Markets.jsx'
import Orders from './pages/Orders.jsx'
import Positions from './pages/Positions.jsx'
import Watchlist from './pages/Watchlist.jsx'
import { useWatchlists } from './lib/watchlists.js'
import SettingsSheet from './components/SettingsSheet.jsx'
import { onOpenSettingsMenu } from './desktop/appMenu.js'
import { toggleList } from './hooks/useResizableWidth.js'
import { LIST_FOR_PAGE } from './lib/listPanes.js'
import { savedLogin, signOut } from './desktop/appSession.js'
import Setup, { Startup } from './pages/Setup.jsx'
import { useLogin } from './hooks/useLogin.js'

const AUTO_REFRESH_MS = 60_000
const PAGE_TITLES = { overview: 'Overview', positions: 'Positions', markets: 'Markets', orders: 'Orders' }
// /health is a cheap local request, so check it often to notice drops and recoveries quickly
const HEALTH_CHECK_MS = 5_000

// The Mac app starts its own backend, which takes a few seconds (longer the first time after
// installing, while macOS checks the new files); until then "unreachable" means "still starting"
const APP_STARTUP_MS = 30_000
const STARTED_AT = Date.now()

// The /health response, or 'starting' / 'offline' when the backend can't be reached
async function readHealth() {
  try {
    return await fetchHealth()
  } catch {
    return IN_APP && Date.now() - STARTED_AT < APP_STARTUP_MS ? 'starting' : 'offline'
  }
}

// 'checking' before the first answer; 'starting' while the app's backend starts; 'offline' if the
// backend is unreachable ('stopped' in the app, where it should always be running); 'disconnected'
// if the backend is up but IB Gateway isn't; otherwise 'connected'
function connectionState(health) {
  if (health === null) return IN_APP ? 'starting' : 'checking'
  if (health === 'starting') return 'starting'
  if (health === 'offline') return IN_APP ? 'stopped' : 'offline'
  return health.connected ? 'connected' : 'disconnected'
}

function App() {
  const [page, setPage] = useState('overview')
  // Settings opens as a sheet over the current page (from the account menu, or ⌘, in the Mac app)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const openSettings = useCallback(() => setSettingsOpen(true), [])
  const closeSettings = useCallback(() => setSettingsOpen(false), [])
  // The IBKR username and mode last signed in with, for the account card (Mac app only)
  const [savedAccount, setSavedAccount] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  // The open watchlist when page is 'watchlist' (#88)
  const [watchlistId, setWatchlistId] = useState(null)
  const watchlists = useWatchlists()
  const watchlist = watchlists.find((l) => l.id === watchlistId) ?? null
  const [account, setAccount] = useState(null)
  const [positions, setPositions] = useState([])
  const [quotes, setQuotes] = useState([])
  // null = not checked yet, 'starting' / 'offline' = backend unreachable (see readHealth), otherwise the /health response
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  // true only while a Refresh-button load runs (it shows the spinner)
  const [loading, setLoading] = useState(false)
  const [updatedAt, setUpdatedAt] = useState(null)
  // Goes up after every successful load so child components (the chart) can refetch too
  const [dataVersion, setDataVersion] = useState(0)
  // Paper or live account, for the toolbar badge (null until known)
  const [trading, setTrading] = useState(null)
  // The open order ticket: { stock, side, review (the preview being confirmed), nonce } or null
  const [ticket, setTicket] = useState(null)
  // Only the newest request may update state, in case an older one finishes later
  const latestRequest = useRef(0)
  const [appearance, setAppearance] = useAppearance()
  // The Mac app's IBKR sign-in (null outside the app)
  const [login, refreshLogin] = useLogin()
  // Set by Reconnect on the "session ended" banner: show the sign-in form
  const [needSignIn, setNeedSignIn] = useState(false)

  // Checks the connection, then fetches everything and swaps in the new numbers.
  // Used by the first load, the timers below, and the Refresh button (which also shows a spinner).
  const load = useCallback(async () => {
    const requestId = ++latestRequest.current
    const isLatest = () => requestId === latestRequest.current

    try {
      // Ask about the connection first; there's no point asking for data IB can't give
      const healthData = await readHealth()
      if (!isLatest()) return
      setHealth(healthData)
      if (connectionState(healthData) !== 'connected') return

      const [accountData, positionsData, quotesData, tradingData] = await Promise.all([
        fetchAccount(),
        fetchPositions(),
        fetchQuotes(),
        // Only for the badge: a failure here shouldn't hide the portfolio
        fetchTradingStatus().catch(() => null),
      ])
      if (!isLatest()) return
      setTrading(tradingData)
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
    const healthData = await readHealth()
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

  const closeTicket = useCallback(() => setTicket(null), [])

  function openWatchlist(id) {
    setWatchlistId(id)
    setPage('watchlist')
  }

  // A deleted watchlist that was open: back to Overview
  function watchlistDeleted(id) {
    if (id === watchlistId && page === 'watchlist') setPage('overview')
  }

  function openHolding(conId) {
    setSelectedId(conId)
    setPage('positions')
  }

  // In the Mac app: the startup screen while the backend starts, the setup flow until signed in to
  // IBKR, then the dashboard (with a banner and the last figures if the session ends)
  const signedIn = login?.state === 'signed_in'
  const sessionEnded = login?.state === 'session_ended'
  let appScreen = 'dashboard'
  if (IN_APP) {
    if (connection === 'starting' || login === null) appScreen = 'startup'
    else if (!signedIn && (!sessionEnded || needSignIn)) appScreen = 'setup'
  }

  useEffect(() => {
    if (appScreen === 'dashboard') sizeWindowFor('dashboard')
  }, [appScreen])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    if (signedIn) setNeedSignIn(false)
  }, [signedIn])

  // The password isn't stored, so reconnecting means signing in again
  function reconnectSession() {
    setNeedSignIn(true)
  }

  useEffect(() => {
    if (!IN_APP || !signedIn) return
    savedLogin()
      .then(setSavedAccount)
      .catch(() => {}) // the card then says "Not signed in" only until the next sign-in
  }, [signedIn])

  // ⌘⌥S shows or hides the list on Positions and Markets, like macOS's "Hide Sidebar" (#91).
  // e.code, because ⌥ changes the character (⌥S types ß)
  const listKey = account && connected ? LIST_FOR_PAGE[page] : undefined
  useEffect(() => {
    if (!listKey) return
    const onKey = (e) => {
      if (e.metaKey && e.altKey && !e.shiftKey && !e.ctrlKey && e.code === 'KeyS') {
        e.preventDefault()
        toggleList(listKey)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [listKey])

  // ⌘, (the app menu's Settings… item) opens the sheet
  useEffect(() => (IN_APP ? onOpenSettingsMenu(openSettings) : undefined), [openSettings])

  async function signOutFromMenu() {
    try {
      await signOut()
    } finally {
      refreshLogin()
    }
  }

  const { holdings } = buildHoldings(positions, quotes, account)
  const updated = updatedAt ? `Updated ${formatTime(updatedAt)}` : 'Loading…'
  let subtitle =
    page === 'overview' ? `${updated} · Prices delayed 15 min` : `${holdings.length} holdings · ${updated}`
  if (connection === 'disconnected') subtitle = 'Waiting for IB Gateway…'
  if (connection === 'offline') subtitle = 'Waiting for the backend…'
  if (connection === 'starting') subtitle = 'Starting…'
  if (connection === 'stopped') subtitle = 'Not running'
  if (page === 'orders' && connected) subtitle = updated
  if (page === 'markets' && connected) subtitle = 'Search stocks on the ASX and US exchanges'
  if (page === 'watchlist' && watchlist && connected) {
    subtitle = `Watchlist · ${watchlist.stocks.length} ${watchlist.stocks.length === 1 ? 'stock' : 'stocks'}`
  }
  // Only show the cards when the data is current; never stale numbers while disconnected, except
  // dimmed under the "session ended" banner, which says how old they are
  const showData = account && (connected || sessionEnded)

  // No title bar in the app: this strip is where the window can be dragged from
  const dragStrip = <div className="drag-strip" data-tauri-drag-region />
  // First in every screen below, so it stays mounted (and keeps a download going) when the screen changes
  const updates = IN_APP ? <UpdatePrompt ready={appScreen !== 'startup'} /> : null
  if (appScreen === 'startup') {
    return (
      <>
        {updates}
        {dragStrip}
        <Startup />
      </>
    )
  }
  if (appScreen === 'setup') {
    return (
      <>
        {updates}
        {dragStrip}
        <Setup login={login} onChange={refreshLogin} />
      </>
    )
  }

  return (
    <>
      {updates}
      <div className="app">
        <Sidebar
          page={page}
          onNavigate={setPage}
          watchlistId={watchlistId}
          onOpenWatchlist={openWatchlist}
          onWatchlistDeleted={watchlistDeleted}
          health={health}
          login={login}
          trading={connected ? trading : null}
          username={savedAccount?.username}
          savedMode={savedAccount?.mode}
          onOpenSettings={openSettings}
          onReconnect={reconnectSession}
          onSignOut={signOutFromMenu}
        />

        <main className="content">
          <Toolbar
            title={page === 'watchlist' ? watchlist?.name : PAGE_TITLES[page]}
            subtitle={subtitle}
            loading={loading}
            onRefresh={() => {
              setLoading(true)
              load()
            }}
            trading={connected ? trading : null}
            listKey={listKey}
          />

          {/* Settings works without a connection: it's where you'd fix one */}
          {settingsOpen && (
            <SettingsSheet
              onClose={closeSettings}
              appearance={appearance}
              onAppearanceChange={setAppearance}
              login={login}
              connected={connected}
              onSignedOut={() => {
                closeSettings()
                refreshLogin()
              }}
            />
          )}

          {sessionEnded && (
            <SessionBanner reason={login.reason} lastUpdated={updatedAt} onReconnect={reconnectSession} />
          )}

          {!sessionEnded && ['starting', 'offline', 'stopped', 'disconnected'].includes(connection) && (
            <ConnectionMessage state={connection} health={health} lastUpdated={updatedAt} />
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
            <div className={`page-body ${sessionEnded ? 'stale' : ''}`}>
              <Overview account={account} holdings={holdings} onOpenHolding={openHolding} />
            </div>
          )}

          {showData && page === 'positions' && (
            <Positions
              stale={sessionEnded}
              holdings={holdings}
              selectedId={selectedId}
              onSelect={setSelectedId}
              refreshKey={dataVersion}
              trading={connected ? trading : null}
              onTrade={(stock, side) => setTicket({ stock, side })}
            />
          )}

          {/* Searching needs IB, so no stale view here */}
          {showData && connected && page === 'markets' && (
            <Markets
              holdings={holdings}
              refreshKey={dataVersion}
              trading={trading}
              onTrade={(stock, side) => setTicket({ stock, side })}
            />
          )}

          {/* Prices come from IB, so no stale view here either */}
          {showData && connected && page === 'watchlist' && watchlist && (
            <Watchlist
              key={watchlist.id}
              list={watchlist}
              holdings={holdings}
              refreshKey={dataVersion}
              trading={trading}
              onTrade={(stock, side) => setTicket({ stock, side })}
            />
          )}

          {showData && connected && page === 'orders' && (
            <Orders
              refreshKey={dataVersion}
              trading={trading}
              onModify={(order) =>
                setTicket({
                  stock: { con_id: order.con_id, symbol: order.symbol, currency: order.currency, last: null },
                  side: order.action,
                  existing: order,
                })
              }
            />
          )}

          {ticket && connected && (
            <>
              {/* Stays mounted under the review sheet, so Edit returns to the same numbers */}
              <OrderTicket
                key={`${ticket.stock.con_id}-${ticket.side}-${ticket.existing?.order_id ?? 'new'}`}
                stock={ticket.stock}
                side={ticket.side}
                existing={ticket.existing}
                trading={trading}
                account={account}
                onClose={closeTicket}
                onReview={(review) => setTicket((t) => ({ ...t, review }))}
                hidden={Boolean(ticket.review)}
                previewNonce={ticket.nonce ?? 0}
              />
              {ticket.review && (
                <OrderConfirm
                  preview={ticket.review}
                  trading={trading}
                  onEdit={() => setTicket((t) => ({ ...t, review: null, nonce: (t.nonce ?? 0) + 1 }))}
                  onDone={() => {
                    closeTicket()
                    load()
                  }}
                  onViewOrders={() => {
                    closeTicket()
                    setPage('orders')
                    load()
                  }}
                />
              )}
            </>
          )}
        </main>
      </div>
    </>
  )
}

export default App
