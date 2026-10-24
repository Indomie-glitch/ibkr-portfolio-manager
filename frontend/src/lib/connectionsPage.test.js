import { describe, expect, it } from 'vitest'
import { buildMap, companyKey, heldCompany, parseBoardEntry, visible } from './connections.js'
import { countsText, describeNode, findNode, linkCounts, linkRows, ownedBy, pageSubtitle } from './connectionsPage.js'

const STOCK = { con_id: 1, symbol: 'CBA', name: 'Commonwealth Bank of Australia', market: 'ASX' }
const HOLDINGS = [
  { con_id: 1, symbol: 'CBA', name: 'Commonwealth Bank of Austral', exchange: 'ASX', weight: 12 },
  { con_id: 2, symbol: 'BHP', name: 'BHP Group Ltd', exchange: 'ASX', weight: 10, quantity: 100 },
  { con_id: 3, symbol: 'TLS', name: 'Telstra Group Ltd', exchange: 'ASX', weight: 2 },
  { con_id: 4, symbol: 'APA', name: 'APA Group', exchange: 'ASX', weight: 1 },
]
const INDICES = [
  { id: 'asx20', name: 'S&P/ASX 20', market: 'ASX', weight: 15.31, rank: 2, count: 20, fund: 'ILC' },
  { id: 'asx50', name: 'S&P/ASX 50', market: 'ASX', weight: 12.22, rank: 2, count: 50, fund: 'SFY' },
  { id: 'asx200', name: 'S&P/ASX 200', market: 'ASX', weight: 9.82, rank: 2, count: 200, fund: 'STW' },
]
const MEMBERS = { asx20: ['BHP', 'CBA'], asx50: ['BHP', 'CBA', 'TLS'], asx200: ['BHP', 'CBA', 'TLS', 'APA'] }
const COMPETITORS = {
  status: 'ready', label: 'Banks - Diversified',
  companies: [
    { rank: 1, symbol: 'CBA', market: 'ASX', is_self: true, market_cap_usd: 120e9 },
    { rank: 2, symbol: 'WBC', name: 'Westpac', market: 'ASX', currency: 'AUD', market_cap: 110e9, market_cap_usd: 53e9, pe: 18, return_1y: 17.8, owned_con_id: null },
    { rank: 3, symbol: 'NAB', name: 'NAB', market: 'ASX', currency: 'AUD', market_cap: 100e9, market_cap_usd: 65e9, pe: 16, return_1y: 4, owned_con_id: 9 },
  ],
}
const EXECUTIVES = { executives: [
  { name: 'Matthew Comyn', title: 'CEO, MD & Executive Director', age: 49 },
  { name: 'Alan F. Docherty', title: 'Group Executive of Financial Services & Group CFO' },
] }
const BOARD = {
  status: 'ready',
  directors: [
    { name: 'Matt Comyn', role: 'managing_director_ceo', appointed_year: 2018, other_boards: [], also_on: [] },
    { name: "Paul O'Malley", role: 'chair', independent: true, appointed_year: 2019, other_boards: [], also_on: [] },
    { name: 'Jane McAloon', role: 'director', independent: true, appointed_year: 2025, age: 62,
      other_boards: ['BlueScope Steel Limited (Chair)', 'BHP Group Limited', 'Allianz Australia Limited'],
      also_on: [{ market: 'ASX', symbol: 'BHP', basis: 'named_in_document' }], wikipedia_url: 'https://en.wikipedia.org/wiki/Jane_McAloon' },
    { name: 'Peter Harmer', role: 'director', other_boards: ['nib holdings limited', 'AUB Group Limited (Chair)'], also_on: [] },
  ],
}

function map(extra = {}) {
  return buildMap({ stock: STOCK, holdings: HOLDINGS, indices: INDICES, members: MEMBERS, competitors: COMPETITORS, executives: EXECUTIVES, board: BOARD, ...extra })
}

const node = (m, id) => m.nodes.find((n) => n.id === id)

describe('matching other boards to your holdings', () => {
  it('drops legal words and punctuation', () => {
    expect(companyKey('BHP Group Limited')).toBe('bhp group')
    expect(companyKey('Telstra Group Ltd.')).toBe('telstra group')
    expect(companyKey('Allianz Australia Limited')).toBe('allianz australia')
    expect(companyKey('Johnson & Johnson')).toBe('johnson and johnson')
  })

  it('reads "Name (Role)"', () => {
    expect(parseBoardEntry('BlueScope Steel Limited (Chair)')).toEqual({ name: 'BlueScope Steel Limited', role: 'Chair' })
    expect(parseBoardEntry('nib holdings limited')).toEqual({ name: 'nib holdings limited', role: null })
  })

  it('finds the holding for a named company, even a name IB cut short', () => {
    expect(heldCompany('BHP Group Limited', HOLDINGS).symbol).toBe('BHP')
    expect(heldCompany('Commonwealth Bank of Australia', HOLDINGS).symbol).toBe('CBA')
    expect(heldCompany('BlueScope Steel Limited', HOLDINGS)).toBeNull()
    expect(heldCompany('BH', HOLDINGS)).toBeNull() // too short to be sure
    expect(heldCompany('APA Corporation', HOLDINGS)).toBeNull() // not APA Group
  })
})

describe('depth 2: directors other boards', () => {
  it('adds nothing at depth 1', () => {
    expect(map().nodes.some((n) => n.kind === 'company')).toBe(false)
  })

  it('adds a dot for each other board of the people on the map, yours first and in amber', () => {
    const m = map({ depth: 2 })
    const dots = m.nodes.filter((n) => n.kind === 'company')
    expect(dots.map((d) => d.label)).toEqual(['BHP Group Limited', 'BlueScope Steel Limited', 'Allianz Australia Limited', 'nib holdings limited', 'AUB Group Limited'])
    expect(dots[0]).toMatchObject({ mine: true, open: { con_id: 2 }, depth: 2 })
    expect(dots[1]).toMatchObject({ mine: false, open: null })
    expect(dots[1].tooltip.body).toBe('Jane McAloon: Chair.')
    expect(dots[0].tooltip.forYou).toBe('You own BHP.')
    // every dot is joined to its person, and sits inside the drawing
    for (const dot of dots) {
      expect(m.edges.some((e) => e.to === dot.id && e.depth === 2)).toBe(true)
      expect(dot.x).toBeGreaterThan(0)
      expect(dot.x).toBeLessThan(786)
      expect(dot.y).toBeLessThan(440)
    }
  })

  it('keeps to three boards per person', () => {
    const board = { status: 'ready', directors: [{ name: 'Busy Person', role: 'director', other_boards: ['A Co', 'B Co', 'C Co', 'D Co', 'E Co'] }] }
    expect(map({ depth: 2, board }).nodes.filter((n) => n.kind === 'company')).toHaveLength(3)
  })
})

describe('the link list', () => {
  const rows = linkRows(map(), STOCK)

  it('lists every link once, the ones touching your holdings first', () => {
    // Most holdings touched first (ASX 200: 3, ASX 50: 2), then one each: index, competitor, person; then the rest
    expect(rows.map((r) => r.name)).toEqual(['ASX 200', 'ASX 50', 'ASX 20', 'NAB', 'Jane McAloon', 'WBC',
      'Matthew Comyn', 'Alan F. Docherty', "Paul O'Malley", 'Peter Harmer'])
  })

  it('counts the links and those touching your holdings', () => {
    expect(linkCounts(rows)).toEqual({ links: 10, toYou: 5 })
    expect(countsText(rows)).toBe('10 links · 5 to your holdings')
    expect(pageSubtitle(STOCK, countsText(rows))).toBe('Commonwealth Bank of Australia · ASX · 10 links · 5 to your holdings')
    expect(pageSubtitle(STOCK, null)).toBe('Commonwealth Bank of Australia · ASX · Loading…')
  })

  it('says how each is connected, in facts', () => {
    const by = (name) => rows.find((r) => r.name === name)
    expect(by('ASX 50').how).toBe('CBA is #2 at 12.2%. BHP and TLS are members too')
    expect(by('ASX 50').sub).toBe('50 stocks')
    expect(by('WBC').how).toBe("Banks - Diversified, 44% of CBA's size, +17.8% over 1Y")
    expect(by('Jane McAloon').how).toBe('Sits on the CBA and BHP boards')
    expect(by("Paul O'Malley").how).toBe('Chair of CBA since 2019, independent')
    expect(by('Matthew Comyn').how).toBe('CEO, MD & Executive Director, also on the board')
    expect(by('Alan F. Docherty').how).toBe('Group Executive of Financial Services & Group CFO')
    expect(by('Alan F. Docherty').sub).toBe('Group Executive of Financi…')
  })

  it('names the holdings each touches', () => {
    expect(rows.find((r) => r.name === 'ASX 50').yours).toEqual(['BHP', 'TLS'])
    expect(rows.find((r) => r.name === 'WBC').yours).toEqual([])
    expect(rows.find((r) => r.name === 'NAB').yours).toEqual(['NAB'])
  })

  it('puts other boards (depth 2) last', () => {
    const deep = linkRows(map({ depth: 2 }), STOCK)
    expect(deep.at(-1).type).toBe('COMPANY')
    expect(deep.find((r) => r.name === 'BHP Group Limited').how).toBe('Jane McAloon also sits on the board of BHP Group Limited')
    expect(deep.find((r) => r.name === 'BlueScope Steel Limited').how).toBe('Jane McAloon is Chair of BlueScope Steel Limited')
    expect(deep.findIndex((r) => r.name === 'BHP Group Limited')).toBeLessThan(deep.findIndex((r) => r.name === 'Paul O\'Malley'))
  })

  it('follows the filters', () => {
    const shown = visible(map(), 'competitors')
    expect(linkRows(shown, STOCK).map((r) => r.type)).toEqual(['COMPETITOR', 'COMPETITOR'])
  })
})

describe('the inspector', () => {
  const m = map({ depth: 2 })
  const ctx = { stock: STOCK, holdings: HOLDINGS }
  const jane = m.nodes.find((n) => n.info?.director?.name === 'Jane McAloon')

  it('describes a person: role, holdings, roles table and Wikipedia', () => {
    const d = describeNode(jane, ctx)
    expect(d).toMatchObject({ type: 'PERSON', title: 'Jane McAloon', subtitle: 'Director', initials: 'JM', mine: true,
      badge: "ON 1 OF YOUR HOLDINGS' BOARDS", wikipedia: 'https://en.wikipedia.org/wiki/Jane_McAloon' })
    expect(d.text).toBe('Director of Commonwealth Bank of Australia since 2025, independent. Aged 62. Also on the boards of BlueScope Steel Limited, BHP Group Limited and Allianz Australia Limited. Sits on the board of BHP, which you own.')
    expect(d.rows[0]).toEqual({ chip: 'CBA', mine: true, role: 'Director', since: 2025 })
    expect(d.rows.find((r) => r.chip === 'BHP')).toMatchObject({ mine: true, role: 'Director', held: 2 })
    expect(d.rows.find((r) => r.name === 'BlueScope Steel Limited')).toMatchObject({ chip: 'BlueScope Steel', mine: false, role: 'Chair' })
  })

  it('a person with no Wikipedia page just has none', () => {
    const paul = m.nodes.find((n) => n.info?.director?.name === "Paul O'Malley")
    expect(describeNode(paul, ctx)).toMatchObject({ wikipedia: null, badge: null, mine: false })
  })

  it('an executive who is also a director shows both roles', () => {
    const comyn = m.nodes.find((n) => n.info?.executive?.name === 'Matthew Comyn')
    const d = describeNode(comyn, ctx)
    expect(d.subtitle).toBe('CEO, MD & Executive Director')
    expect(d.rows.map((r) => r.role)).toEqual(['Managing director and CEO', 'CEO, MD & Executive Director'])
    expect(d.text).toContain('Managing director and CEO of Commonwealth Bank of Australia since 2018')
  })

  it('describes an index with your holdings in it', () => {
    const d = describeNode(node(m, 'index:asx50'), ctx)
    expect(d).toMatchObject({ type: 'INDEX', title: 'ASX 50', mine: true, badge: 'YOU OWN 2 OF ITS STOCKS' })
    expect(d.facts).toEqual([['Rank', '#2 of 50'], ['Weight', '12.2%'], ['Holdings file', 'SFY']])
    expect(d.text).toBe('CBA is #2 of the 50 stocks in the S&P/ASX 50, at 12.2% of the index. You also own BHP and TLS.')
  })

  it('describes a competitor you do not own, and one you do', () => {
    const wbc = describeNode(node(m, 'peer:ASX:WBC'), ctx)
    expect(wbc).toMatchObject({ type: 'STOCK', title: 'WBC', badge: null, open: { symbol: 'WBC', market: 'ASX' } })
    expect(wbc.facts).toEqual([['Market cap', 'A$110b'], ['P/E', '18.0'], ['1 year', '+17.8%']])
    expect(describeNode(node(m, 'peer:ASX:NAB'), ctx)).toMatchObject({ badge: 'YOU OWN IT', open: { con_id: 9 } })
  })

  it('describes a holding and another board', () => {
    expect(describeNode(node(m, 'holding:2'), ctx)).toMatchObject({ title: 'BHP', badge: 'YOU OWN IT', open: { con_id: 2 } })
    const company = m.nodes.find((n) => n.kind === 'company' && n.label === 'BlueScope Steel Limited')
    expect(describeNode(company, ctx)).toMatchObject({ title: 'BlueScope Steel Limited', subtitle: 'Chair', badge: null, open: null })
  })

  it('describes the stock itself', () => {
    expect(describeNode(node(m, 'self'), ctx)).toMatchObject({ type: 'STOCK', title: 'CBA', mine: true })
  })

  it('knows what a node touches', () => {
    expect(ownedBy(node(m, 'index:asx200'))).toEqual(['BHP', 'TLS', 'APA'])
    expect(ownedBy(node(m, 'peer:ASX:WBC'))).toEqual([])
    expect(ownedBy(jane)).toEqual(['BHP'])
  })
})

describe('find in map', () => {
  const m = map()
  const label = (q) => findNode(m, q)?.id

  it('finds symbols, names and indexes', () => {
    expect(label('wbc')).toBe('peer:ASX:WBC')
    expect(label('Westpac')).toBe('peer:ASX:WBC')
    expect(label('asx 50')).toBe('index:asx50')
    expect(label('mcaloon')).toBe(m.nodes.find((n) => n.info?.director?.name === 'Jane McAloon').id)
    expect(label('Jane')).toBe(m.nodes.find((n) => n.info?.director?.name === 'Jane McAloon').id)
  })

  it('prefers an exact match, then a prefix', () => {
    expect(label('CBA')).toBe('self')
    expect(label('bh')).toBe('holding:2')
  })

  it('finds nothing for nothing', () => {
    expect(findNode(m, '')).toBeNull()
    expect(findNode(m, '   ')).toBeNull()
    expect(findNode(m, 'zzz')).toBeNull()
    expect(findNode(m, 'ab')).toBeNull() // too short for a match in the middle of a word
  })
})
