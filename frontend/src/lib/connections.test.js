import { describe, expect, it } from 'vitest'
import { HEIGHT, LIMITS, WIDTH, buildMap, indexLabel, initials, matchSearchResult, personKey, samePerson, visible } from './connections.js'

const STOCK = { con_id: 1, symbol: 'CBA', name: 'Commonwealth Bank of Australia', market: 'ASX' }
const HOLDINGS = [
  { con_id: 1, symbol: 'CBA', name: 'Commonwealth Bank', exchange: 'ASX', weight: 12 },
  { con_id: 2, symbol: 'BHP', name: 'BHP Group', exchange: 'ASX', weight: 10 },
  { con_id: 3, symbol: 'TLS', name: 'Telstra', exchange: 'ASX', weight: 2 },
  { con_id: 4, symbol: 'APA', name: 'APA Group', exchange: 'ASX', weight: 1 },
  { con_id: 5, symbol: 'AAPL', name: 'Apple', exchange: 'NASDAQ', weight: 30 },
]
const INDICES = [
  { id: 'asx20', name: 'S&P/ASX 20', market: 'ASX', weight: 15.31, rank: 2, count: 20 },
  { id: 'asx50', name: 'S&P/ASX 50', market: 'ASX', weight: 12.22, rank: 2, count: 50 },
  { id: 'asx200', name: 'S&P/ASX 200', market: 'ASX', weight: 9.82, rank: 2, count: 200 },
]
const MEMBERS = { asx20: ['BHP', 'CBA'], asx50: ['BHP', 'CBA', 'TLS'], asx200: ['BHP', 'CBA', 'TLS', 'APA'] }
const COMPETITORS = {
  status: 'ready', label: 'Banks - Diversified',
  companies: [
    { rank: 1, symbol: 'CBA', market: 'ASX', is_self: true, market_cap_usd: 120e9 },
    { rank: 2, symbol: 'WBC', name: 'Westpac', market: 'ASX', currency: 'AUD', market_cap: 110e9, market_cap_usd: 72e9, pe: 18, return_1y: 9, owned_con_id: null },
    { rank: 3, symbol: 'NAB', name: 'NAB', market: 'ASX', currency: 'AUD', market_cap: 100e9, market_cap_usd: 65e9, pe: 16, return_1y: 4, owned_con_id: 9 },
    { rank: 4, symbol: 'BEN', name: 'Bendigo', market: 'ASX', currency: 'AUD', market_cap: 6e9, market_cap_usd: 4e9, pe: null, return_1y: null, owned_con_id: null },
  ],
}
const EXECUTIVES = { executives: [{ name: 'Matthew Comyn', title: 'CEO, MD & Executive Director', age: 49, pay: 4331460, pay_currency: 'AUD', pay_fiscal_year: 2026 }] }
const BOARD = {
  status: 'ready',
  directors: [
    { name: 'Matt Comyn', role: 'managing_director_ceo', also_on: [] },
    { name: "Paul O'Malley", role: 'chair', independent: true, appointed_year: 2019, also_on: [] },
    { name: 'Jane McAloon', role: 'director', independent: true, other_boards: ['BlueScope Steel Limited'], also_on: [{ market: 'ASX', symbol: 'BHP', basis: 'named_in_document' }] },
  ],
}

function cba(extra = {}) {
  return buildMap({ stock: STOCK, holdings: HOLDINGS, indices: INDICES, members: MEMBERS, competitors: COMPETITORS, executives: EXECUTIVES, board: BOARD, ...extra })
}

const byId = (map, id) => map.nodes.find((n) => n.id === id)

describe('labels and names', () => {
  it('shortens index names', () => {
    expect(indexLabel('S&P/ASX 50')).toBe('ASX 50')
    expect(indexLabel('S&P 500')).toBe('S&P 500')
    expect(indexLabel('Dow Jones Industrial Average')).toBe('DOW')
    expect(indexLabel('Nasdaq 100')).toBe('NASDAQ 100')
  })

  it('makes initials without titles or degrees', () => {
    expect(initials('Mr. Matthew Comyn EMBA')).toBe('MC')
    expect(initials('Xiaoqun Clever-Steg')).toBe('XC')
    expect(initials("Paul O'Malley")).toBe('PO')
    expect(initials('Cher')).toBe('C')
    expect(initials('')).toBe('?')
  })

  it('matches Yahoo and board names for the same person', () => {
    expect(personKey('Mr. Matthew Comyn EMBA')).toBe('matthew comyn')
    expect(personKey("Paul O’Malley")).toBe(personKey("Paul O'Malley"))
    expect(personKey('Art D. Levinson')).toBe('art levinson')
    expect(personKey('Cher')).toBeNull()
    expect(samePerson('Mr. Matthew Comyn EMBA', 'Matt Comyn')).toBe(true)
    expect(samePerson('Al Gore', 'Alan Gore')).toBe(false) // too short to be sure
    expect(samePerson('Matt Comyn', 'Matt Combs')).toBe(false)
  })
})

describe('the map', () => {
  it('puts the stock in the middle and every node inside the drawing', () => {
    const map = cba()
    expect(byId(map, 'self')).toMatchObject({ label: 'CBA', x: 392 })
    for (const n of map.nodes) {
      const half = n.r ?? n.w / 2
      expect(n.x - half).toBeGreaterThanOrEqual(0)
      expect(n.x + half).toBeLessThanOrEqual(WIDTH)
      expect(n.y).toBeGreaterThan(0)
      expect(n.y).toBeLessThan(HEIGHT)
    }
  })

  it('links your holdings to the indexes they share with the stock', () => {
    const map = cba()
    const yours = map.nodes.filter((n) => n.id.startsWith('holding:')).map((n) => n.label)
    expect(yours).toEqual(['BHP', 'TLS', 'APA']) // AAPL isn't in an ASX index; CBA is the stock itself
    const bhpLinks = map.edges.filter((e) => e.from === 'holding:2').map((e) => e.to)
    expect(bhpLinks).toEqual(['index:asx20', 'index:asx50', 'index:asx200'])
    expect(map.edges.filter((e) => e.from.startsWith('holding:')).every((e) => e.mine)).toBe(true)
  })

  it('writes the index tooltip from facts only', () => {
    const asx50 = byId(cba(), 'index:asx50')
    expect(asx50.tooltip.title).toBe('ASX 50 · CBA #2 · 12.2%')
    expect(asx50.tooltip.body).toBe('CBA is the 2nd largest of the 50 stocks in the S&P/ASX 50.')
    expect(asx50.tooltip.forYou).toBe('You also own BHP and TLS in this index (2 of your 4 other holdings).')
    expect(asx50.mine).toBe(true)
  })

  it('sizes competitors by market cap and opens them by con_id or symbol', () => {
    const map = cba()
    const wbc = byId(map, 'peer:ASX:WBC')
    const ben = byId(map, 'peer:ASX:BEN')
    expect(wbc.r).toBeGreaterThan(ben.r)
    expect(ben.labelOutside).toBe(true)
    expect(wbc.open).toEqual({ symbol: 'WBC', market: 'ASX' })
    expect(byId(map, 'peer:ASX:NAB')).toMatchObject({ mine: true, open: { con_id: 9 } })
    expect(map.nodes.some((n) => n.id === 'peer:ASX:CBA')).toBe(false)
    expect(wbc.tooltip.title).toBe('WBC · #2 · BANKS - DIVERSIFIED')
  })

  it('shows a person once: an executive on the board stays with the executives', () => {
    const map = cba()
    expect(map.nodes.filter((n) => n.kind === 'executive').map((n) => n.label)).toEqual(['MC'])
    expect(map.nodes.filter((n) => n.kind === 'director').map((n) => n.label)).toEqual(['PO', 'JM'])
  })

  it('draws a director on the board of one of your holdings in amber, linked to it', () => {
    const map = cba()
    const jane = map.nodes.find((n) => n.kind === 'director' && n.label === 'JM')
    expect(jane.mine).toBe(true)
    expect(jane.tooltip.forYou).toBe('Also on the board of BHP, which you own.')
    const link = map.edges.find((e) => e.from === jane.id && e.to.startsWith('linked:'))
    expect(link.mine).toBe(true)
    expect(byId(map, link.to)).toMatchObject({ label: 'BHP', open: { con_id: 2 } })
  })

  it('never draws two circles on top of each other, even at the limits', () => {
    const peers = Array.from({ length: 12 }, (_, i) => ({ rank: i + 2, symbol: `P${i}`, market: 'ASX', market_cap_usd: 1e9 * (12 - i) }))
    const people = Array.from({ length: 10 }, (_, i) => ({ name: `Person Number${i}`, role: 'director', also_on: [] }))
    const execs = Array.from({ length: 7 }, (_, i) => ({ name: `Exec Officer${i}`, title: 'Chief' }))
    const map = cba({ competitors: { status: 'ready', label: 'X', companies: [COMPETITORS.companies[0], ...peers] },
      board: { status: 'ready', directors: people }, executives: { executives: execs } })
    const circles = map.nodes.filter((n) => n.r && n.kind !== 'self')
    // Small competitors' labels sit outside the circle: they need clear space too
    const labelRoom = (n) => (n.labelOutside ? n.label.length * 3.5 + 6 : 0)
    for (let i = 0; i < circles.length; i++) {
      for (let j = i + 1; j < circles.length; j++) {
        const a = circles[i]
        const b = circles[j]
        expect(Math.hypot(a.x - b.x, a.y - b.y), `${a.id} / ${b.id}`).toBeGreaterThanOrEqual(a.r + b.r + Math.min(labelRoom(a), labelRoom(b)))
      }
    }
  })

  it('keeps to the limits', () => {
    const many = { status: 'ready', label: 'X', companies: Array.from({ length: 20 }, (_, i) => ({ rank: i + 1, symbol: `P${i}`, market: 'ASX', market_cap_usd: 1e9 * (20 - i) })) }
    const map = cba({ competitors: many })
    expect(map.nodes.filter((n) => n.kind === 'competitor')).toHaveLength(LIMITS.competitors)
  })

  it('works with nothing but the stock, and says it is in none of the indexes', () => {
    const map = buildMap({ stock: { ...STOCK, symbol: 'GOLD', market: 'US' } })
    expect(map.nodes).toHaveLength(1)
    expect(map.labels.map((l) => l.text)).toEqual(['NOT IN THE S&P 500, NASDAQ 100 OR DOW'])
    expect(visible(map, 'indices').labels).toHaveLength(1)
    expect(visible(map, 'competitors').labels).toHaveLength(0)
  })

  it('fits long index names in their box', () => {
    const map = cba({ indices: [{ id: 'nasdaq100', name: 'Nasdaq 100', market: 'US', weight: 9, rank: 1, count: 101 }] })
    expect(byId(map, 'index:nasdaq100').w).toBeGreaterThanOrEqual('NASDAQ 100'.length * 7)
  })

  it('leaves the board out until it has been read', () => {
    const map = cba({ board: { status: 'not_read', directors: [] } })
    expect(map.nodes.some((n) => n.kind === 'director')).toBe(false)
  })
})

describe('filters', () => {
  it('shows one group at a time', () => {
    const map = cba()
    const kinds = (filter) => [...new Set(visible(map, filter).nodes.map((n) => n.kind))].sort()
    expect(kinds('indices')).toEqual(['holding', 'index', 'self'])
    expect(kinds('competitors')).toEqual(['competitor', 'self'])
    expect(kinds('people')).toEqual(['director', 'executive', 'holding', 'self'])
    expect(visible(map, 'competitors').labels.map((l) => l.text)).toEqual(['COMPETITORS · SIZE = MARKET CAP'])
  })

  it('only mine keeps what links to your holdings', () => {
    const shown = visible(cba(), 'all', true)
    expect(shown.nodes.map((n) => n.label).sort()).toEqual(['APA', 'ASX 20', 'ASX 200', 'ASX 50', 'BHP', 'BHP', 'CBA', 'JM', 'NAB', 'TLS'])
    expect(shown.edges.every((e) => shown.nodes.some((n) => n.id === e.from) && shown.nodes.some((n) => n.id === e.to))).toBe(true)
    expect(shown.labels.map((l) => l.text)).not.toContain('EXECUTIVES')
  })
})

describe('opening a competitor', () => {
  it('finds the same symbol on the same market', () => {
    const results = [
      { con_id: 10, symbol: 'BHP', market: 'US' },
      { con_id: 11, symbol: 'BHP', market: 'ASX' },
    ]
    expect(matchSearchResult(results, 'BHP', 'ASX').con_id).toBe(11)
    expect(matchSearchResult(results, 'WBC', 'ASX')).toBeNull()
  })
})
