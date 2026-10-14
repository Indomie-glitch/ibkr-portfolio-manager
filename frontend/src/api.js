const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

async function getJson(path) {
  const response = await fetch(`${API_URL}${path}`)
  if (!response.ok) {
    throw new Error(`${path} returned ${response.status}`)
  }
  return response.json()
}

export function fetchAccount() {
  return getJson('/account')
}

export function fetchPositions() {
  return getJson('/positions')
}
