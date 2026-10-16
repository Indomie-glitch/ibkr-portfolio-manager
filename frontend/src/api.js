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

export function fetchHealth() {
  return getJson('/health')
}

export function fetchAccount() {
  return getJson('/account')
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
