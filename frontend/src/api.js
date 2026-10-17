// In the Mac app, Rust injects the backend's address and a per-launch access token before the page
// loads (open_main_window in src-tauri/src/lib.rs); in development the backend runs on port 8000
const APP_BACKEND = window.__PORTFOLIO_BACKEND__
export const IN_APP = Boolean(APP_BACKEND)
const API_URL = APP_BACKEND?.url ?? import.meta.env.VITE_API_URL ?? 'http://localhost:8000'
const HEADERS = APP_BACKEND ? { 'X-App-Token': APP_BACKEND.token } : {}

async function getJson(path) {
  const response = await fetch(`${API_URL}${path}`, { headers: HEADERS })
  if (!response.ok) {
    let detail = `${path} returned ${response.status}`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // body wasn't JSON; keep the status message
    }
    const error = new Error(detail)
    error.status = response.status
    throw error
  }
  return response.json()
}

async function postJson(path, body) {
  const response = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { ...HEADERS, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    let detail = `${path} returned ${response.status}`
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
    throw error
  }
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
  const response = await fetch(`${API_URL}/orders/stream`, { headers: HEADERS, signal })
  if (!response.ok) throw new Error(`/orders/stream returned ${response.status}`)
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
  return getJson(`/search?q=${encodeURIComponent(query)}`)
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
  return getJson(`/history/${conId}?range=${encodeURIComponent(range)}`)
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

// Start a new AI summary and call onEvent(name, data) for each Server-Sent Event the
// backend streams: status, facts, section (one per finished section), done, error.
// (EventSource can't send POST requests, so this reads the stream with fetch.)
export async function generateSummary(conId, onEvent) {
  const response = await fetch(`${API_URL}/summary/${conId}`, { method: 'POST', headers: HEADERS })
  if (!response.ok) {
    let detail = `Summary request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // not JSON; keep the status message
    }
    const error = new Error(detail)
    error.status = response.status
    throw error
  }

  await readEvents(response, onEvent)
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
