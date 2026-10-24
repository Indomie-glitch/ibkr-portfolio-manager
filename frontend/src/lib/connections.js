// The Connections map (#114, Figma "Connections / V1C · Relationship map" 138:1359): turns the
// stock's indexes (#110), competitors (#111), executives (#112) and board (#113) into positioned
// nodes, lines and tooltip text. Pure, so it's tested without a browser (connections.test.js).
//
// Layout, in a 786 × 440 drawing: the stock in the middle; your holdings that share an index with it
// ("YOURS") and the indexes on the left; competitors on the right, sized by market cap; executives
// along the bottom left and the board along the bottom right. Anything linked to your holdings is
// "mine" (amber): your holdings, indexes they're in, competitors you own, and people who sit on the
// board of a company you own.
import { formatCompactMoney, formatPercent } from './format.js'

export const WIDTH = 786
export const HEIGHT = 440
const CENTER = { x: 392, y: 205 }
const SELF_R = 34
// The two rows of people along the bottom
const PEOPLE_ROWS = [338, 382]
export const LIMITS = { holdings: 5, indices: 6, competitors: 8, executives: 5, board: 8 }
export const FILTERS = ['all', 'indices', 'competitors', 'people']

// "S&P/ASX 50" -> "ASX 50", "Dow Jones Industrial Average" -> "DOW"
export function indexLabel(name) {
  if (/^dow jones/i.test(name)) return 'DOW'
  return name.replace(/^S&P\//, '').toUpperCase()
}

// ASX or US, the way the index and competitor answers name markets
export function marketOf(stock) {
  return stock.market ?? (stock.exchange === 'ASX' ? 'ASX' : 'US')
}

// "Mr. Matthew Comyn EMBA" -> "MC"; "Xiaoqun Clever-Steg" -> "XC"
export function initials(name) {
  const words = (name ?? '').replace(/\([^)]*\)/g, ' ').split(/\s+/).filter((w) => /^[A-Za-z]/.test(w))
  const named = words.filter((w) => !/^(mr|mrs|ms|dr|prof|sir)\.?$/i.test(w))
  if (named.length === 0) return '?'
  const last = [...named].reverse().find((w) => !/^[A-Z.]{2,}$/.test(w) || named.length === 1) ?? named.at(-1)
  return (named[0][0] + (named.length > 1 ? last[0] : '')).toUpperCase()
}

// First and last name, lower case, without titles, initials, degrees or apostrophes: for matching the
// same person in Yahoo's executives and the board (the backend's people.match_key, simplified)
export function personKey(name) {
  const words = (name ?? '')
    .replace(/\([^)]*\)/g, ' ')
    .replace(/['‘’`]/g, '')
    .split(/[\s,]+/)
    .filter((w) => w && !/^(mr|mrs|ms|dr|prof|sir)\.?$/i.test(w) && !/\./.test(w) && !/^[A-Z]{2,}$/.test(w))
  if (words.length < 2) return null
  return `${words[0]} ${words.at(-1)}`.toLowerCase()
}

// The same person in two lists from one company ("Matthew Comyn" in Yahoo, "Matt Comyn" on the
// board): same last name, and first names equal or one starting the other. Only used within one
// company, where two different people with those names are very unlikely.
export function samePerson(a, b) {
  const ka = personKey(a)
  const kb = personKey(b)
  if (!ka || !kb) return false
  const [fa, la] = ka.split(' ')
  const [fb, lb] = kb.split(' ')
  if (la !== lb) return false
  const shorter = fa.length <= fb.length ? fa : fb
  return fa === fb || (shorter.length >= 3 && (fa.startsWith(fb) || fb.startsWith(fa)))
}

const LEGAL_WORDS = /\b(limited|ltd|inc|incorporated|corp|corporation|plc|company|co|holdings|nv|sa|ag|se|llc)\b/g

// "BHP Group Limited" -> "bhp group": for matching a company named in a document to a holding's name
export function companyKey(name) {
  return (name ?? '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9 ]/g, ' ')
    .replace(LEGAL_WORDS, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
}

// "BlueScope Steel Limited (Chair)" -> { name: "BlueScope Steel Limited", role: "Chair" }
export function parseBoardEntry(text) {
  const match = /^(.*?)\s*\(([^)]*)\)\s*$/.exec(text ?? '')
  return match ? { name: match[1].trim(), role: match[2].trim() } : { name: (text ?? '').trim(), role: null }
}

// "Coles Group Limited (October 2020–October 2023)": a board they have left, not one they sit on
export function isFormerBoard(entry) {
  return Boolean(entry.role && /\b(19|20)\d\d\b/.test(entry.role))
}

// The holding a named company is, or null: the same name once legal words are dropped, or one
// starting the other (IB cuts long names: "Commonwealth Bank of Austral")
export function heldCompany(name, holdings) {
  const key = companyKey(name)
  if (key.length < 3) return null
  return holdings.find((h) => {
    const held = companyKey(h.name)
    return held.length >= 3 && (held === key || (Math.min(held.length, key.length) >= 8 && (held.startsWith(key) || key.startsWith(held))))
  }) ?? null
}

function ordinal(n) {
  const s = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return `${n}${s[(v - 20) % 10] || s[v] || s[0]}`
}

function listWords(items) {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items.at(-1)}`
}

const ROLE_WORDS = {
  chair: 'Chair',
  deputy_chair: 'Deputy chair',
  lead_independent_director: 'Lead independent director',
  managing_director_ceo: 'Managing director and CEO',
  executive_director: 'Executive director',
  director: 'Director',
}

// Spreads n items between a and b (both included; one item sits in the middle)
function spread(n, a, b) {
  if (n === 1) return [(a + b) / 2]
  return Array.from({ length: n }, (_, i) => a + ((b - a) * i) / (n - 1))
}

function around(angleDeg, rx, ry) {
  const a = (angleDeg * Math.PI) / 180
  return { x: CENTER.x + Math.cos(a) * rx, y: CENTER.y + Math.sin(a) * ry }
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v))
}

// Room a circle needs: a label drawn outside it (small competitors) needs about its width more
function room(c) {
  return c.r + (c.labelOutside ? c.label.length * 3.5 + 6 : 0)
}

// Pushes overlapping circles apart (a few rounds is enough for a handful), keeping them in the box
function separate(circles, left, right, top, bottom, gap = 6) {
  for (let round = 0; round < 40; round++) {
    let moved = false
    for (let i = 0; i < circles.length; i++) {
      for (let j = i + 1; j < circles.length; j++) {
        const a = circles[i]
        const b = circles[j]
        const dx = b.x - a.x || 0.01
        const dy = b.y - a.y || 0.01
        const distance = Math.hypot(dx, dy)
        const need = room(a) + room(b) + gap
        if (distance >= need) continue
        const push = (need - distance) / 2
        a.x -= (dx / distance) * push
        a.y -= (dy / distance) * push
        b.x += (dx / distance) * push
        b.y += (dy / distance) * push
        moved = true
      }
    }
    for (const c of circles) {
      c.x = clamp(c.x, left + c.r, right - c.r)
      c.y = clamp(c.y, top + c.r, bottom - c.r)
    }
    if (!moved) break
  }
}

/**
 * Builds the map.
 * stock: { con_id, symbol, name, market }
 * holdings: your holdings [{ con_id, symbol, name, exchange|market }]
 * indices: GET /indices/{id} .indices; members: { index id: [symbols] } of those indexes
 * competitors: GET /competitors/{id} (ready or loading) or null
 * executives: GET /executives/{id} or null; board: GET /directors/{id} or null
 * Returns { nodes, edges, labels }.
 */
export function buildMap({ stock, holdings = [], indices = [], members = {}, competitors = null, executives = null, board = null, depth = 1 }) {
  const nodes = []
  const edges = []
  const labels = []
  const others = holdings.filter((h) => h.con_id !== stock.con_id)
  const heldBySymbol = new Map(others.map((h) => [`${marketOf(h)}:${h.symbol}`, h]))
  const heldCount = others.length

  nodes.push({
    id: 'self', kind: 'self', ...CENTER, r: SELF_R, label: stock.symbol, sublabel: stock.name, group: 'self',
    tooltip: { title: `${stock.symbol} · THIS STOCK`, body: stock.name },
    info: { stock },
  })

  // ---------- Indexes, and your holdings in them ----------
  const shownIndices = indices.slice(0, LIMITS.indices)
  const memberSets = Object.fromEntries(shownIndices.map((i) => [i.id, new Set(members[i.id] ?? [])]))
  const holdingIndices = new Map() // holding con_id -> [index ids]
  for (const index of shownIndices) {
    for (const h of others) {
      if (marketOf(h) === index.market && memberSets[index.id].has(h.symbol)) {
        holdingIndices.set(h.con_id, [...(holdingIndices.get(h.con_id) ?? []), index.id])
      }
    }
  }
  const yours = others
    .filter((h) => holdingIndices.has(h.con_id))
    .sort((a, b) => holdingIndices.get(b.con_id).length - holdingIndices.get(a.con_id).length || (b.weight ?? 0) - (a.weight ?? 0))
    .slice(0, LIMITS.holdings)

  const indexYs = spread(shownIndices.length, shownIndices.length > 3 ? 70 : 85, shownIndices.length > 3 ? 270 : 225)
  shownIndices.forEach((index, i) => {
    const inIt = others.filter((h) => (holdingIndices.get(h.con_id) ?? []).includes(index.id)).map((h) => h.symbol)
    const label = indexLabel(index.name)
    nodes.push({
      id: `index:${index.id}`, kind: 'index', x: 159, y: indexYs[i], w: Math.max(64, label.length * 7 + 18), h: 24, label, group: 'indices', mine: inIt.length > 0,
      info: { index, shared: inIt },
      tooltip: {
        title: `${label} · ${stock.symbol} #${index.rank} · ${index.weight.toFixed(1)}%`,
        body: `${stock.symbol} is the ${index.rank === 1 ? '' : `${ordinal(index.rank)} `}largest of the ${index.count} stocks in the ${index.name}.`,
        forYou: inIt.length
          ? `You also own ${listWords(inIt)} in this index (${inIt.length} of your ${heldCount} other holdings).`
          : 'None of your other holdings are in this index.',
      },
    })
    edges.push({ from: `index:${index.id}`, to: 'self', group: 'indices' })
  })
  if (shownIndices.length) labels.push({ text: 'INDICES', x: 127, y: indexYs[0] - 28, kind: 'index' })
  else {
    // Say so, rather than leave the left side empty (a small cap or a stock on another market)
    const covered = stock.market === 'ASX' ? 'THE ASX 20, 50 OR 200' : 'THE S&P 500, NASDAQ 100 OR DOW'
    labels.push({ text: `NOT IN ${covered}`, x: 40, y: 150, kind: 'self', group: 'indices', note: true })
  }

  const yoursYs = spread(yours.length, 40, 250)
  yours.forEach((h, i) => {
    const shared = holdingIndices.get(h.con_id).map((id) => indexLabel(shownIndices.find((x) => x.id === id).name))
    nodes.push({
      id: `holding:${h.con_id}`, kind: 'holding', x: 50, y: yoursYs[i], w: 48, h: 22, label: h.symbol, group: 'indices', mine: true,
      open: { con_id: h.con_id }, info: { holding: h, shared },
      tooltip: { title: `${h.symbol} · YOU OWN IT`, body: `${h.name ?? h.symbol} is in the ${listWords(shared)} with ${stock.symbol}.` },
    })
    for (const id of holdingIndices.get(h.con_id)) edges.push({ from: `holding:${h.con_id}`, to: `index:${id}`, mine: true, group: 'indices' })
  })
  if (yours.length) labels.push({ text: 'YOURS', x: 29, y: yoursYs[0] - 26, mine: true, kind: 'holding', group: 'indices' })

  // ---------- Competitors, sized by market cap ----------
  const peers = (competitors?.companies ?? []).filter((c) => !c.is_self).slice(0, LIMITS.competitors)
  const biggest = Math.max(1, ...peers.map((c) => c.market_cap_usd ?? 0))
  const peerAngles = spread(peers.length, -62, 18)
  peers.forEach((c, i) => {
    const r = 8 + 14 * Math.sqrt((c.market_cap_usd ?? 0) / biggest)
    const p = around(peerAngles[i], 250 + (i % 2) * 70, 175)
    const held = c.owned_con_id ?? heldBySymbol.get(`${c.market}:${c.symbol}`)?.con_id ?? null
    nodes.push({
      id: `peer:${c.market}:${c.symbol}`, kind: 'competitor', x: clamp(p.x, 330, WIDTH - r - 30), y: clamp(p.y, 72, 300), r,
      label: c.symbol, group: 'competitors', mine: held != null, labelOutside: r < 14,
      open: held != null ? { con_id: held } : { symbol: c.symbol, market: c.market },
      info: { competitor: c, label: competitors.label, self: (competitors.companies ?? []).find((x) => x.is_self) ?? null, held },
      tooltip: {
        title: `${c.symbol} · #${c.rank} · ${competitors.label}`.toUpperCase(),
        body: [
          c.name,
          c.market_cap != null ? `Market cap ${formatCompactMoney(c.market_cap, c.currency)}` : null,
          c.pe != null ? `P/E ${c.pe.toFixed(1)}` : null,
          c.return_1y != null ? `1 year ${formatPercent(c.return_1y, { decimals: 1 })}` : null,
        ].filter(Boolean).join(' · '),
        forYou: held != null ? 'You own it.' : null,
      },
    })
    edges.push({ from: `peer:${c.market}:${c.symbol}`, to: 'self', mine: held != null, group: 'competitors' })
  })
  separate(nodes.filter((n) => n.kind === 'competitor'), 330, WIDTH - 30, 72, 300)
  if (peers.length) labels.push({ text: 'COMPETITORS · SIZE = MARKET CAP', x: 559, y: 52, kind: 'competitor' })

  // ---------- People: executives (Yahoo) and the board (the company's document) ----------
  const execs = (executives?.executives ?? []).slice(0, LIMITS.executives)
  const directors = board?.status === 'ready' ? board.directors ?? [] : []
  const boardOnly = directors.filter((d) => !execs.some((e) => samePerson(e.name, d.name))).slice(0, LIMITS.board)

  // Two staggered rows along the bottom: executives on the left, the board on the right
  const execXs = spread(execs.length, execs.length > 1 ? 70 : 200, 330)
  execs.forEach((e, i) => {
    const p = { x: execXs[i], y: i % 2 ? PEOPLE_ROWS[1] : PEOPLE_ROWS[0] }
    const onBoard = directors.find((d) => samePerson(e.name, d.name))
    nodes.push({
      id: `exec:${i}`, kind: 'executive', x: p.x, y: p.y, r: 16, label: initials(e.name), group: 'people',
      link: onBoard?.wikipedia_url ?? e.wikipedia_url ?? null,
      info: { executive: e, director: onBoard ?? null },
      tooltip: {
        title: e.name.toUpperCase(),
        body: [e.title, e.age ? `Age ${e.age}` : null, e.pay ? `Pay ${formatCompactMoney(e.pay, e.pay_currency)} (${e.pay_fiscal_year})` : null]
          .filter(Boolean).join(' · '),
      },
    })
    edges.push({ from: `exec:${i}`, to: 'self', group: 'people' })
  })
  if (execs.length) labels.push({ text: 'EXECUTIVES', x: execXs[0] - 16, y: PEOPLE_ROWS[0] - 30, kind: 'executive' })

  const boardXs = spread(boardOnly.length, 450, boardOnly.length > 1 ? 690 : 450)
  boardOnly.forEach((d, i) => {
    const p = { x: boardXs[i], y: i % 2 ? PEOPLE_ROWS[1] : PEOPLE_ROWS[0] }
    const heldLinks = (d.also_on ?? []).map((a) => heldBySymbol.get(`${a.market}:${a.symbol}`)).filter(Boolean)
    const id = `board:${i}`
    const node = {
      id, kind: 'director', x: p.x, y: p.y, r: 16, label: initials(d.name), group: 'people',
      mine: heldLinks.length > 0, link: d.wikipedia_url ?? null,
      info: { director: d, heldLinks },
      tooltip: {
        title: d.name.toUpperCase(),
        body: [
          [ROLE_WORDS[d.role] ?? 'Director', d.independent ? 'independent' : null, d.appointed_year ? `since ${d.appointed_year}` : null]
            .filter(Boolean).join(', '),
          d.other_boards?.length ? `Also: ${d.other_boards.slice(0, 3).join('; ')}` : null,
        ].filter(Boolean).join('. '),
        forYou: heldLinks.length ? `Also on the board of ${listWords(heldLinks.map((h) => h.symbol))}, which you own.` : null,
      },
    }
    nodes.push(node)
    edges.push({ from: id, to: 'self', group: 'people' })
    heldLinks.slice(0, 1).forEach((h) => {
      const linkId = `linked:${i}:${h.con_id}`
      nodes.push({
        id: linkId, kind: 'holding', x: WIDTH - 36, y: node.y + (i % 2 ? 0 : -26), w: 48, h: 22, label: h.symbol, group: 'people',
        mine: true, open: { con_id: h.con_id }, info: { holding: h, linkedVia: d },
        tooltip: { title: `${h.symbol} · YOU OWN IT`, body: `${d.name} is on its board and on ${stock.symbol}'s.` },
      })
      edges.push({ from: id, to: linkId, mine: true, group: 'people' })
    })
  })
  if (boardOnly.length) labels.push({ text: 'BOARD', x: boardXs[0] - 16, y: PEOPLE_ROWS[0] - 30, kind: 'director' })

  // ---------- Depth 2: the other boards the directors sit on (from the document) ----------
  if (depth >= 2) addOtherBoards(nodes, edges, directors, others)

  return { nodes, edges, labels }
}

// Small dots along the bottom edge, one per other company board of a person already on the map
// (up to 3 each, 18 in all, boards of companies you own first). Amber and clickable when you own
// the company; otherwise they only have a tooltip, since the document names no ticker.
function addOtherBoards(nodes, edges, directors, others) {
  const entries = []
  for (const person of nodes.filter((n) => n.kind === 'director' || n.kind === 'executive')) {
    const name = person.info.director?.name ?? person.info.executive?.name
    const record = directors.find((d) => samePerson(d.name, name))
    for (const raw of (record?.other_boards ?? []).slice(0, 3)) {
      const entry = parseBoardEntry(raw)
      if (!entry.name || isFormerBoard(entry)) continue
      entries.push({ person, personName: record.name, ...entry, held: heldCompany(entry.name, others) })
    }
  }
  const picked = [...entries.filter((e) => e.held), ...entries.filter((e) => !e.held)].slice(0, 18)
  // Left of the middle for people on the left, right of it for the rest, in the order of their people
  for (const [side, left, right] of [['left', 30, 350], ['right', 430, WIDTH - 70]]) {
    const group = picked.filter((e) => (e.person.x < CENTER.x) === (side === 'left')).sort((a, b) => a.person.x - b.person.x)
    const xs = spread(group.length, left, right)
    group.forEach((e, i) => {
      const id = `other:${e.person.id}:${i}:${side}`
      nodes.push({
        id, kind: 'company', depth: 2, x: group.length === 1 ? (left + right) / 2 : xs[i], y: 420, r: 6, label: e.name, group: 'people',
        mine: Boolean(e.held), open: e.held ? { con_id: e.held.con_id } : null, info: { company: e, person: e.person },
        tooltip: {
          title: e.name.toUpperCase(),
          body: `${e.personName}${e.role ? `: ${e.role}` : ' also sits on this board'}.`,
          forYou: e.held ? `You own ${e.held.symbol}.` : null,
        },
      })
      edges.push({ from: e.person.id, to: id, mine: Boolean(e.held), group: 'people', depth: 2 })
      if (e.held) e.person.mine = true
    })
  }
}

// Which nodes, lines and group labels to draw for a filter key and "only mine"
export function visible(map, filter = 'all', onlyMine = false) {
  const keepGroup = (group) => group === 'self' || filter === 'all' || group === filter
  const nodes = map.nodes.filter((n) => keepGroup(n.group) && (!onlyMine || n.kind === 'self' || n.mine))
  const ids = new Set(nodes.map((n) => n.id))
  const edges = map.edges.filter((e) => ids.has(e.from) && ids.has(e.to))
  // A group's label shows while any of its nodes do (YOURS: the holdings next to the indexes)
  const labels = map.labels.filter((l) =>
    l.note ? keepGroup(l.group) && !onlyMine : nodes.some((n) => n.kind === l.kind && (!l.group || n.group === l.group)))
  return { nodes, edges, labels }
}

// The stock to open for a competitor: the search result with the same symbol on the same market
export function matchSearchResult(results, symbol, market) {
  return results.find((r) => r.symbol === symbol && r.market === market) ?? null
}
