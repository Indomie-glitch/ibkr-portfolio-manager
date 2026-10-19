// The Risk page's data (Milestone 8). Every panel loads its own section with useFetch, so one failure
// only shows "unavailable" in that panel, but they all share one GET /risk request per period.
import { fetchRisk, fetchRiskBankruptcy } from './api.js'

const requests = new Map() // `${period}:${version}` -> promise of the whole answer

// The whole GET /risk answer for a period. version changes when the page wants fresh numbers.
// A failed request is forgotten, so the next call (e.g. after Refresh) asks again.
export function loadRisk(period, version = 0, fetcher = fetchRisk) {
  const key = `${period}:${version}`
  if (!requests.has(key)) {
    const promise = fetcher(period)
    requests.set(key, promise)
    promise.catch(() => {
      if (requests.get(key) === promise) requests.delete(key)
    })
  }
  return requests.get(key)
}

// One section of the answer, with the shared meta and holdings: { section, meta, holdings }.
// Throws when the backend couldn't calculate it ({ error }) or doesn't send it yet.
export async function loadSection(period, version, name, fetcher = fetchRisk) {
  const data = await loadRisk(period, version, fetcher)
  const section = data[name]
  if (section == null) throw new Error('Not calculated yet.')
  if (section.error) throw new Error(section.error)
  return { section, meta: data.meta, holdings: data.holdings }
}

// RSK 11's own answer (GET /risk/bankruptcy), shaped like a section; it doesn't depend on the period
export async function loadBankruptcy(version, fetcher = fetchRiskBankruptcy) {
  const section = await loadRisk('bankruptcy', version, fetcher)
  return { section, meta: null, holdings: null }
}

// For tests
export function clearRiskRequests() {
  requests.clear()
}
