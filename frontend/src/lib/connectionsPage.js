// The full Connections page (#279, Figma Connections / V2 138-1157 → 142:1157): what the inspector
// shows for the selected node, the "All connections" list, the link counts in the toolbar and the
// find-in-map search. Pure, so it's tested without a browser (connectionsPage.test.js). The map
// itself is lib/connections.js; every fact here comes from the same data (indexes, competitors,
// executives, board), never from guesses.
import { formatCompactMoney, formatPercent } from './format.js'
import { initials, parseBoardEntry, heldCompany } from './connections.js'

const ROLE_WORDS = {
  chair: 'Chair',
  deputy_chair: 'Deputy chair',
  lead_independent_director: 'Lead independent director',
  managing_director_ceo: 'Managing director and CEO',
  executive_director: 'Executive director',
  director: 'Director',
}

export const TYPE_ORDER = { INDEX: 0, COMPETITOR: 1, PERSON: 2, COMPANY: 3 }

function listWords(items) {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items.at(-1)}`
}

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

// The nodes that are links to something else (not the stock itself, nor your holdings drawn beside
// the indexes: those are shown by what they touch)
function linkNodes(map) {
  return map.nodes.filter((n) => n.kind !== 'self' && n.kind !== 'holding')
}

// Symbols of your holdings a node touches
export function ownedBy(node) {
  const info = node.info ?? {}
  if (node.kind === 'index') return info.shared ?? []
  if (node.kind === 'competitor') return info.held != null ? [node.label] : []
  if (node.kind === 'director') return (info.heldLinks ?? []).map((h) => h.symbol)
  if (node.kind === 'company') return info.company?.held ? [info.company.held.symbol] : []
  return []
}

function typeOf(node) {
  if (node.kind === 'index') return 'INDEX'
  if (node.kind === 'competitor') return 'COMPETITOR'
  if (node.kind === 'company') return 'COMPANY'
  return 'PERSON'
}

// How the person at this node is linked to the stock, in one line
function personHow(node, stock) {
  const { executive, director, heldLinks = [] } = node.info
  if (heldLinks.length) return `Sits on the ${stock.symbol} and ${listWords(heldLinks.map((h) => h.symbol))} boards`
  if (executive) return `${executive.title}${director ? ', also on the board' : ''}`
  const since = director.appointed_year ? ` since ${director.appointed_year}` : ''
  return `${ROLE_WORDS[director.role] ?? 'Director'} of ${stock.symbol}${since}${director.independent ? ', independent' : ''}`
}

function personSub(node) {
  const { executive, director } = node.info
  if (executive) return executive.title.length > 28 ? `${executive.title.slice(0, 26)}…` : executive.title
  return ROLE_WORDS[director.role] ?? 'Director'
}

function personName(node) {
  return node.info.executive?.name ?? node.info.director.name
}

/**
 * The "All connections" rows: { id, type, name, sub, how, yours: [symbols], owned: n } for each
 * link on the map, the ones touching your holdings first.
 */
export function linkRows(map, stock) {
  const rows = linkNodes(map).map((node) => {
    const yours = ownedBy(node)
    const info = node.info ?? {}
    const base = { id: node.id, type: typeOf(node), yours, owned: yours.length, node }
    if (node.kind === 'index') {
      const { index, shared } = info
      const members = shared.length ? ` ${listWords(shared)} ${shared.length === 1 ? 'is a member' : 'are members'} too` : ''
      return { ...base, name: node.label, sub: `${plural(index.count, 'stock')}`,
        how: `${stock.symbol} is #${index.rank} at ${index.weight.toFixed(1)}%.${members}`, rank: index.weight }
    }
    if (node.kind === 'competitor') {
      const { competitor: c, label, self } = info
      const size = self?.market_cap_usd && c.market_cap_usd ? Math.round((c.market_cap_usd / self.market_cap_usd) * 100) : null
      const how = [label, size != null ? `${size}% of ${stock.symbol}'s size` : null,
        c.return_1y != null ? `${formatPercent(c.return_1y, { decimals: 1 })} over 1Y` : null].filter(Boolean).join(', ')
      return { ...base, name: c.symbol, sub: c.name ?? '', how, rank: c.market_cap_usd ?? 0 }
    }
    if (node.kind === 'company') {
      const { company } = info
      return { ...base, name: company.name, sub: company.role ?? '', rank: 0,
        how: `${company.personName} ${company.role ? `is ${company.role} of` : 'also sits on the board of'} ${company.name}` }
    }
    return { ...base, name: personName(node), sub: personSub(node), how: personHow(node, stock), rank: 0 }
  })
  // Touching your holdings first (most first), then indexes, competitors by size, people, other boards
  return rows.sort((a, b) =>
    (b.owned > 0) - (a.owned > 0) || b.owned - a.owned || TYPE_ORDER[a.type] - TYPE_ORDER[b.type] || b.rank - a.rank)
}

// { links, toYou } for the toolbar: "31 links · 3 to your holdings"
export function linkCounts(rows) {
  return { links: rows.length, toYou: rows.filter((r) => r.owned > 0).length }
}

export function countsText(rows) {
  const { links, toYou } = linkCounts(rows)
  return `${plural(links, 'link')} · ${toYou} to your holdings`
}

// ---------- The inspector ----------

function personRows(node, stock, holdings) {
  const { executive, director } = node.info
  const rows = [{
    chip: stock.symbol, mine: holdings.some((h) => h.con_id === stock.con_id),
    role: director ? (ROLE_WORDS[director.role] ?? 'Director') : executive.title,
    since: director?.appointed_year ?? null,
  }]
  if (director && executive) rows.push({ chip: stock.symbol, mine: false, role: executive.title, since: null, executive: true })
  for (const raw of director?.other_boards ?? []) {
    const entry = parseBoardEntry(raw)
    const held = heldCompany(entry.name, holdings)
    rows.push({ chip: held?.symbol ?? entry.name.replace(/\b(limited|ltd|inc|corporation|corp|plc)\b\.?/gi, '').trim(), mine: Boolean(held),
      role: entry.role ?? 'Director', since: null, name: entry.name, held: held?.con_id ?? null })
  }
  return rows
}

function personText(node, stock) {
  const { executive, director, heldLinks = [] } = node.info
  const parts = []
  if (director) {
    const role = ROLE_WORDS[director.role] ?? 'Director'
    parts.push(`${role} of ${stock.name}${director.appointed_year ? ` since ${director.appointed_year}` : ''}${director.independent ? ', independent' : ''}.`)
  }
  if (executive) parts.push(`${executive.title}${executive.age ? `, aged ${executive.age}` : ''}.`)
  if (director?.age && !executive?.age) parts.push(`Aged ${director.age}.`)
  const others = (director?.other_boards ?? []).map((b) => parseBoardEntry(b).name)
  if (others.length) parts.push(`Also on the boards of ${listWords(others.slice(0, 4))}${others.length > 4 ? ` and ${others.length - 4} more` : ''}.`)
  if (heldLinks.length) parts.push(`Sits on the board of ${listWords(heldLinks.map((h) => h.symbol))}, which you own.`)
  if (director?.leaving) parts.push('The document says they are retiring.')
  return parts.join(' ')
}

/**
 * What the inspector shows for a node:
 * { type, title, subtitle, initials, mine, badge, text, rows, facts, wikipedia, open }.
 * rows: the person's roles table [{ chip, mine, role, since }]. open: what Open does ({ con_id } or
 * { symbol, market } for a stock, or null).
 */
export function describeNode(node, { stock, holdings = [] }) {
  const info = node.info ?? {}
  if (node.kind === 'self') {
    return { type: 'STOCK', title: stock.symbol, subtitle: `${stock.name} · this stock`, mine: holdings.some((h) => h.con_id === stock.con_id),
      text: `The stock this map is about. Everything on it is linked to ${stock.symbol}.`, rows: [], facts: [], open: null }
  }
  if (node.kind === 'index') {
    const { index, shared } = info
    return {
      type: 'INDEX', title: node.label, subtitle: index.name, mine: shared.length > 0,
      badge: shared.length ? `YOU OWN ${shared.length} OF ITS STOCKS` : null,
      text: `${stock.symbol} is #${index.rank} of the ${index.count} stocks in the ${index.name}, at ${index.weight.toFixed(1)}% of the index.${shared.length ? ` You also own ${listWords(shared)}.` : ''}`,
      rows: [], facts: [['Rank', `#${index.rank} of ${index.count}`], ['Weight', `${index.weight.toFixed(1)}%`], ['Holdings file', index.fund ?? '—']], open: null,
    }
  }
  if (node.kind === 'holding') {
    const { holding, shared = [], linkedVia } = info
    return {
      type: 'STOCK', title: holding.symbol, subtitle: holding.name ?? holding.symbol, mine: true, badge: 'YOU OWN IT',
      text: linkedVia ? `${linkedVia.name} sits on its board and on ${stock.symbol}'s.` : `In the ${listWords(shared)} with ${stock.symbol}.`,
      rows: [], facts: [['You hold', holding.quantity != null ? String(holding.quantity) : '—'], ['Portfolio weight', holding.weight != null ? formatPercent(holding.weight, { signed: false, decimals: 1 }) : '—']],
      open: { con_id: holding.con_id },
    }
  }
  if (node.kind === 'competitor') {
    const { competitor: c, label, held } = info
    return {
      type: 'STOCK', title: c.symbol, subtitle: `${c.name ?? c.symbol} · ${c.market}`, mine: held != null, badge: held != null ? 'YOU OWN IT' : null,
      text: `#${c.rank} of its group by market cap (${label}).`,
      rows: [], open: node.open,
      facts: [
        ['Market cap', c.market_cap != null ? formatCompactMoney(c.market_cap, c.currency) : '—'],
        ['P/E', c.pe != null ? c.pe.toFixed(1) : '—'],
        ['1 year', c.return_1y != null ? formatPercent(c.return_1y, { decimals: 1 }) : '—'],
      ],
    }
  }
  if (node.kind === 'company') {
    const { company } = info
    return {
      type: 'STOCK', title: company.name, subtitle: company.role ?? 'Board seat', mine: Boolean(company.held),
      badge: company.held ? 'YOU OWN IT' : null,
      text: `${company.personName} ${company.role ? `is ${company.role} of` : 'also sits on the board of'} ${company.name}.`,
      rows: [], facts: [], open: node.open,
    }
  }
  // Executives and directors
  const { executive, director, heldLinks = [] } = info
  const name = executive?.name ?? director.name
  return {
    type: 'PERSON', title: name, subtitle: executive?.title ?? ROLE_WORDS[director.role] ?? 'Director', initials: initials(name),
    mine: heldLinks.length > 0 || Boolean(node.mine),
    badge: heldLinks.length ? `ON ${heldLinks.length === 1 ? '1 OF' : `${heldLinks.length} OF`} YOUR HOLDINGS' BOARDS` : null,
    text: personText(node, stock), rows: personRows(node, stock, holdings), facts: [],
    wikipedia: node.link ?? null, open: null,
  }
}

// ---------- Find in map ----------

// The node a search text points at: a symbol, a person's name, an index or a company, best match first
export function findNode(map, query) {
  const q = (query ?? '').trim().toLowerCase()
  if (!q) return null
  const names = (n) => [n.label, n.info?.executive?.name, n.info?.director?.name, n.info?.competitor?.name, n.info?.index?.name,
    n.info?.holding?.name, n.info?.company?.name].filter(Boolean).map((s) => s.toLowerCase())
  const nodes = map.nodes
  return nodes.find((n) => names(n).some((s) => s === q))
    ?? nodes.find((n) => names(n).some((s) => s.startsWith(q)))
    ?? nodes.find((n) => names(n).some((s) => s.split(/\s+/).some((w) => w.startsWith(q))))
    ?? nodes.find((n) => q.length >= 3 && names(n).some((s) => s.includes(q)))
    ?? null
}

// ---------- Toolbar text ----------

// summary: countsText(rows), or null while the map is loading
export function pageSubtitle(stock, summary) {
  return `${stock.name} · ${stock.market} · ${summary ?? 'Loading…'}`
}

