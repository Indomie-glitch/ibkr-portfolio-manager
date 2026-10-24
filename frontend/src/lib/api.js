// In the Mac app, Rust injects the backend's address and a per-launch access token before the page
// loads (open_main_window in src-tauri/src/lib.rs); in development the backend runs on port 8000
const APP_BACKEND = window.__PORTFOLIO_BACKEND__
export const IN_APP = Boolean(APP_BACKEND)
const API_URL = APP_BACKEND?.url ?? import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const HEADERS = APP_BACKEND ? { 'X-App-Token': APP_BACKEND.token } : {}

// How long a request may take before the app gives up on it. Most answers take well under a
// second; IB price history and searches can wait in IB's queue (#203).
const TIMEOUT_MS = 30_000
const SLOW_TIMEOUT_MS = 60_000

// fetch with a time limit. For JSON the whole answer must arrive in time; a stream (stream: true)
// only has to start in time, then runs as long as it needs. signal: the caller's own cancel.
// Network failures and timeouts become plain messages (error.code 'network' or 'timeout').
async function request(path, { timeoutMs = TIMEOUT_MS, stream = false, signal, ...init } = {}) {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)
  // Passed on by hand: AbortSignal.any isn't in the Mac app's web view on older macOS
  const forward = () => controller.abort()
  signal?.addEventListener('abort', forward)
  try {
    const response = await fetch(`${API_URL}${path}`, { ...init, headers: { ...HEADERS, ...init.headers }, signal: controller.signal })
    if (stream && response.ok) return response
    const body = await response.text()
    return { ok: response.ok, status: response.status, json: () => JSON.parse(body) }
  } catch (err) {
    if (signal?.aborted) throw err
    const error = new Error(
      timedOut
        ? `No answer from the backend after ${Math.round(timeoutMs / 1000)} seconds. Try again with Refresh.`
        : IN_APP
          ? 'Couldn’t reach the app’s background service.'
          : 'Couldn’t reach the backend. Is it running?',
    )
    error.code = timedOut ? 'timeout' : 'network'
    throw error
  } finally {
    // A stream keeps its connection; only waiting for it to start was limited
    clearTimeout(timer)
    if (!stream) signal?.removeEventListener('abort', forward)
  }
}

// The error for a failed answer: FastAPI's detail when there is one, else the status
async function failure(path, response, fallback = `${path} returned ${response.status}`) {
  let detail = fallback
  try {
    const data = await response.json()
    if (typeof data.detail === 'string') detail = data.detail
    // FastAPI validation errors: a list of {msg}
    else if (Array.isArray(data.detail)) detail = data.detail.map((d) => d.msg).join(' ')
  } catch {
    // body wasn't JSON; keep the status message
  }
  const error = new Error(detail)
  error.status = response.status
  return error
}

async function getJson(path, options) {
  const response = await request(path, options)
  if (!response.ok) throw await failure(path, response)
  return response.json()
}

async function postJson(path, body, options) {
  const response = await request(path, {
    ...options,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) throw await failure(path, response)
  return response.json()
}

// What an order would cost (IBKR what-if), without sending it; includes a confirmation token
// when the order may be placed
export function previewOrder(order) {
  return postJson('/orders/preview', order)
}

// Place a previewed order: order + the preview's confirmation_token
export function placeOrder(order) {
  return postJson('/orders', order)
}

// Open orders and today's filled and cancelled orders: { open, filled_today, cancelled }
export function fetchOrders() {
  return getJson('/orders')
}

export function cancelOrder(orderId) {
  return postJson(`/orders/${orderId}/cancel`, {})
}

// Change an open order's quantity or limit price: { quantity, limit_price, confirmation_token }
export function modifyOrder(orderId, change) {
  return postJson(`/orders/${orderId}/modify`, change)
}

// Follow order updates until signal aborts: onEvent('orders', [...]) first, then onEvent('order', {...})
export async function watchOrders(onEvent, signal) {
  const response = await request('/orders/stream', { stream: true, signal })
  if (!response.ok) throw await failure('/orders/stream', response)
  await readEvents(response, onEvent)
}

export function fetchHealth() {
  return getJson('/health')
}

export function fetchAccount() {
  return getJson('/account')
}

// Any ASX or US stock by symbol or company name (Markets page)
export function searchStocks(query) {
  return getJson(`/search?q=${encodeURIComponent(query)}`, { timeoutMs: SLOW_TIMEOUT_MS })
}

// Quotes for any stocks (same shape as /quotes): conIds is a comma-separated string
export function fetchPrices(conIds) {
  return getJson(`/prices?con_ids=${conIds}`)
}

// Paper or live account and whether orders are allowed (Milestone 6)
export function fetchTradingStatus() {
  return getJson('/trading/status')
}

export function fetchPositions() {
  return getJson('/positions')
}

export function fetchQuotes() {
  return getJson('/quotes')
}

export function fetchHistory(conId, range) {
  return getJson(`/history/${conId}?range=${encodeURIComponent(range)}`, { timeoutMs: SLOW_TIMEOUT_MS })
}

// A holding's purchase lots from the Flex report, with 12-month CGT dates (backend/lots.py)
export function fetchLots(conId) {
  return getJson(`/lots/${conId}`)
}

// Whether Flex purchase dates are set up
export function fetchLotsStatus() {
  return getJson('/lots/status')
}

export function fetchProfile(conId) {
  return getJson(`/profile/${conId}`)
}

export function fetchStats(conId) {
  return getJson(`/stats/${conId}`)
}

export function fetchNews(conId) {
  return getJson(`/news/${conId}`)
}

export function fetchPerformance(conId) {
  return getJson(`/performance/${conId}`)
}

export function fetchSummary(conId) {
  return getJson(`/summary/${conId}`)
}

export function fetchSummaryHistory(conId) {
  return getJson(`/summary/${conId}/history`)
}

export function fetchPastSummary(conId, summaryId) {
  return getJson(`/summary/${conId}/history/${summaryId}`)
}

// Two saved summaries (older first) and the exact changes between their data
export function fetchSummaryComparison(conId, a, b) {
  return getJson(`/summary/${conId}/compare?a=${a}&b=${b}`)
}

// Risk analysis (Milestone 8): every section for a period ('3M', '1Y', '3Y'). The first answer of
// the day downloads daily prices from Yahoo, so it may take a while
export function fetchRisk(period) {
  return getJson(`/risk?period=${encodeURIComponent(period)}`, { timeoutMs: SLOW_TIMEOUT_MS })
}

// Each holding's Altman Z score from its latest annual accounts (separate, so a Yahoo failure here only
// affects that panel)
export function fetchRiskBankruptcy() {
  return getJson('/risk/bankruptcy', { timeoutMs: SLOW_TIMEOUT_MS })
}

// Start a new AI summary and call onEvent(name, data) for each Server-Sent Event the
// backend streams: status, facts, section (one per finished section), done, error.
// (EventSource can't send POST requests, so this reads the stream with fetch.)
async function streamSummary(path, onEvent) {
  const response = await request(path, { method: 'POST', stream: true })
  if (!response.ok) throw await failure(path, response, `Summary request failed (${response.status})`)

  await readEvents(response, onEvent)
}

export function generateSummary(conId, onEvent) {
  return streamSummary(`/summary/${conId}`, onEvent)
}

// The AI portfolio summary (Overview, #22): the same calls as a stock's summary
export function fetchPortfolioSummary() {
  return getJson('/portfolio-summary')
}

export function fetchPortfolioSummaryHistory() {
  return getJson('/portfolio-summary/history')
}

export function fetchPastPortfolioSummary(summaryId) {
  return getJson(`/portfolio-summary/history/${summaryId}`)
}

export function fetchPortfolioSummaryComparison(a, b) {
  return getJson(`/portfolio-summary/compare?a=${a}&b=${b}`)
}

export function generatePortfolioSummary(onEvent) {
  return streamSummary('/portfolio-summary', onEvent)
}

// Reads a Server-Sent Events response, calling onEvent(name, data) for each event
async function readEvents(response, onEvent) {
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    // Events are separated by a blank line: "event: name\ndata: {...}\n\n"
    let end
    while ((end = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      const name = raw.match(/^event: (.*)$/m)?.[1]
      const data = raw.match(/^data: (.*)$/m)?.[1]
      if (name && data) onEvent(name, JSON.parse(data))
    }
  }
}

// Borrowing safeguard (#289): { account_id, block, change_here }
export function fetchBorrowing() {
  return getJson('/trading/borrowing')
}

// Browser version only (the Mac app uses Touch ID, desktop/appBorrowing.js): { block, confirm? }
export function changeBorrowing(change) {
  return postJson('/trading/borrowing', change)
}
