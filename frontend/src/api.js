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
    throw new Error(detail)
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
