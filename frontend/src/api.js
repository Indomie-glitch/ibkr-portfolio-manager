const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function getJson(path) {
  const response = await fetch(`${API_URL}${path}`)
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
