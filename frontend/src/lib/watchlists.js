// Watchlists (#88): lists of any stocks, kept in this browser / the Mac app's web view (localStorage),
// never on the backend. The sidebar, the Watchlist page and the Watch menu on a stock all read and
// change the same small store, so they always agree.
import { useSyncExternalStore } from 'react'

const STORAGE_KEY = 'watchlists'
export const NEW_NAME = 'New Watchlist'
export const MAX_NAME = 40

// ---------- pure helpers (tested in watchlists.test.js) ----------

// What a watchlist keeps about a stock: enough to show its row before prices arrive
export function stockEntry(stock) {
  const { con_id, symbol, name, exchange, currency, market } = stock
  return { con_id, symbol, name: name ?? symbol, exchange, currency, market }
}

// A trimmed name that no other watchlist has: "New Watchlist", "New Watchlist 2", …
export function uniqueName(name, lists, exceptId = null) {
  const base = name.trim().replace(/\s+/g, ' ').slice(0, MAX_NAME) || NEW_NAME
  const taken = new Set(lists.filter((l) => l.id !== exceptId).map((l) => l.name.toLowerCase()))
  if (!taken.has(base.toLowerCase())) return base
  for (let n = 2; ; n++) {
    const candidate = `${base} ${n}`
    if (!taken.has(candidate.toLowerCase())) return candidate
  }
}

export function addList(lists, id, name) {
  return [...lists, { id, name: uniqueName(name, lists), stocks: [] }]
}

export function renameList(lists, id, name) {
  return lists.map((l) => (l.id === id ? { ...l, name: uniqueName(name, lists, id) } : l))
}

export function removeList(lists, id) {
  return lists.filter((l) => l.id !== id)
}

// Newest first; a stock already in the list stays where it is
export function addStockTo(lists, id, stock) {
  return lists.map((l) =>
    l.id === id && !l.stocks.some((s) => s.con_id === stock.con_id) ? { ...l, stocks: [stockEntry(stock), ...l.stocks] } : l,
  )
}

export function removeStockFrom(lists, id, conId) {
  return lists.map((l) => (l.id === id ? { ...l, stocks: l.stocks.filter((s) => s.con_id !== conId) } : l))
}

// Saved data can be anything (an older version, hand edits): keep only well-formed lists
export function parseSaved(raw) {
  try {
    const data = JSON.parse(raw)
    if (!Array.isArray(data)) return []
    return data
      .filter((l) => l && typeof l.id === 'string' && typeof l.name === 'string' && Array.isArray(l.stocks))
      .map((l) => ({ id: l.id, name: l.name, stocks: l.stocks.filter((s) => Number.isInteger(s?.con_id) && s.symbol) }))
  } catch {
    return []
  }
}

// ---------- the shared store ----------

let lists = null
// The watchlist whose name is being typed in the sidebar (just created), or null
let naming = null
const listeners = new Set()

function current() {
  if (lists === null) {
    try {
      lists = parseSaved(localStorage.getItem(STORAGE_KEY))
    } catch {
      lists = [] // storage blocked: watchlists work until the page closes
    }
  }
  return lists
}

function commit(next) {
  lists = next
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  } catch {
    // see current()
  }
  listeners.forEach((listener) => listener())
}

function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useWatchlists() {
  return useSyncExternalStore(subscribe, current)
}

export function useNamingWatchlist() {
  return useSyncExternalStore(subscribe, () => naming)
}

// Creates "New Watchlist" (optionally with a first stock) and starts naming it in the sidebar
export function createWatchlist(firstStock = null) {
  const id = `wl-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`
  let next = addList(current(), id, NEW_NAME)
  if (firstStock) next = addStockTo(next, id, firstStock)
  naming = id
  commit(next)
  return id
}

export function finishNaming(id, name) {
  naming = null
  commit(renameList(current(), id, name))
}

export function startNaming(id) {
  naming = id
  listeners.forEach((listener) => listener())
}

export function deleteWatchlist(id) {
  if (naming === id) naming = null
  commit(removeList(current(), id))
}

export function addToWatchlist(id, stock) {
  commit(addStockTo(current(), id, stock))
}

export function removeFromWatchlist(id, conId) {
  commit(removeStockFrom(current(), id, conId))
}
