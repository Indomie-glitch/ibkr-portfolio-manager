import { describe, expect, it } from 'vitest'
import {
  budgetText,
  companyKeys,
  costSummary,
  filterCompanies,
  isEmptyState,
  nextMonthStart,
  parseBudget,
  readTime,
  settingsLine,
  statusPill,
  tiles,
  usd,
  weekChange,
} from './pipelineFormat.js'

const pipeline = (over = {}) => ({
  status: 'running',
  enabled: true,
  started: true,
  workers: 2,
  coverage: { read: 46, total: 52, not_on_edgar: 0 },
  links: { total: 3912, week: 214, ended: 18 },
  attention: { stuck: 0, retrying: 3, total: 3 },
  cost: { month: 4.12, week: 1.86, per_filing: 0.03, budget: 10, budget_left: 5.88, percent: 41 },
  companies: { all: 52, reading: 2, waiting: 29, failed: 3, up_to_date: 18, not_on_edgar: 0 },
  ...over,
})

describe('usd', () => {
  it('formats money, with a floor for tiny amounts', () => {
    expect(usd(4.12)).toBe('US$4.12')
    expect(usd(10)).toBe('US$10.00')
    expect(usd(1234.5)).toBe('US$1,234.50')
    expect(usd(0)).toBe('US$0.00')
    expect(usd(0.001)).toBe('<US$0.01')
    expect(usd(0, { dash: true })).toBe('—')
    expect(usd(null)).toBe('—')
  })
})

describe('budget field', () => {
  it('parses what people type', () => {
    expect(parseBudget('10')).toBe(10)
    expect(parseBudget('US$12.50')).toBe(12.5)
    expect(parseBudget(' $1,000 ')).toBe(1000)
    for (const bad of ['', '0', '-5', 'abc', '1e3', '12.345', '1001', '10 dollars']) expect(parseBudget(bad)).toBeNull()
  })
  it('shows whole amounts without decimals', () => {
    expect(budgetText(10)).toBe('10')
    expect(budgetText(12.5)).toBe('12.5')
  })
})

describe('settingsLine', () => {
  it('describes each state in plain words', () => {
    expect(settingsLine(pipeline())).toBe('Running · 2 workers · US$4.12 of US$10.00 spent this month. 3 reports need attention, 3 retrying.')
    expect(settingsLine(pipeline({ attention: { stuck: 0, retrying: 0, total: 0 }, workers: 1 }))).toBe('Running · 1 worker · US$4.12 of US$10.00 spent this month.')
    expect(settingsLine(pipeline({ status: 'off' }))).toMatch(/^Off\./)
    expect(settingsLine(pipeline({ status: 'paused' }))).toMatch(/^Paused\. Press Run now/)
    expect(settingsLine(pipeline({ status: 'budget' }), new Date(2026, 9, 25))).toContain('starts again on 1 November')
    expect(settingsLine(null)).toBe('Checking…')
  })
  it('knows when next month starts', () => {
    expect(nextMonthStart(new Date(2026, 11, 31)).getMonth()).toBe(0)
    expect(nextMonthStart(new Date(2026, 11, 31)).getFullYear()).toBe(2027)
  })
})

describe('statusPill', () => {
  it('has a tone and label per status', () => {
    expect(statusPill(pipeline())).toEqual({ tone: 'ok', label: 'Running · 2 workers' })
    expect(statusPill(pipeline({ status: 'paused' })).tone).toBe('warn')
    expect(statusPill(pipeline({ status: 'budget' })).label).toBe('Paused · budget used')
    expect(statusPill(pipeline({ status: 'off' }))).toEqual({ tone: 'off', label: 'Off' })
    expect(statusPill(null).label).toBe('Off')
  })
})

describe('tiles', () => {
  it('builds the four tiles from the answer', () => {
    const [coverage, links, attention, cost] = tiles(pipeline())
    expect(coverage.value).toBe('46 / 52')
    expect(links).toMatchObject({ value: '3,912', sub: '+214 this week, 18 ended' })
    expect(attention).toMatchObject({ value: '3', tone: 'loss', sub: '3 retrying' })
    expect(cost).toMatchObject({ value: 'US$4.12', sub: '41% of your US$10.00 budget' })
  })
  it('says so when nothing needs attention, and when companies are not on EDGAR', () => {
    const t = tiles(pipeline({ attention: { stuck: 0, retrying: 0, total: 0 }, coverage: { read: 40, total: 59, not_on_edgar: 7 } }))
    expect(t[2]).toMatchObject({ value: '0', sub: 'Nothing needs attention' })
    expect(t[2].tone).toBeUndefined()
    expect(t[0].sub).toContain('7 not on EDGAR')
  })
  it('lists stopped ones too', () => {
    expect(tiles(pipeline({ attention: { stuck: 2, retrying: 1, total: 3 } }))[2].sub).toBe('1 retrying, 2 stopped')
  })
})

describe('companies', () => {
  const rows = [{ status: 'failed' }, { status: 'waiting' }, { status: 'failed' }, { status: 'up to date' }]
  it('filters by status', () => {
    expect(filterCompanies(rows, 'all')).toHaveLength(4)
    expect(filterCompanies(rows, 'failed')).toHaveLength(2)
    expect(filterCompanies(rows, 'reading')).toHaveLength(0)
  })
  it('counts the keys', () => {
    expect(companyKeys(pipeline().companies).map((k) => `${k.label} ${k.count}`)).toEqual(['ALL 52', 'RUNNING 2', 'WAITING 29', 'FAILED 3', 'UP TO DATE 18'])
  })
})

describe('readTime', () => {
  const now = new Date(2026, 9, 25, 12, 0, 0)
  it('is short and relative', () => {
    expect(readTime(null, now)).toBe('—')
    expect(readTime(new Date(2026, 9, 25, 11, 59, 30).toISOString(), now)).toBe('now')
    expect(readTime(new Date(2026, 9, 25, 9, 5).toISOString(), now)).toBe('09:05')
    expect(readTime(new Date(2026, 9, 22, 9, 5).toISOString(), now)).toMatch(/^[A-Z][a-z]{2}$/)
    expect(readTime(new Date(2026, 8, 3, 9, 5).toISOString(), now)).toMatch(/3 Sep/)
  })
})

describe('small things', () => {
  it('shows the 7 day change', () => {
    expect(weekChange(9)).toEqual({ text: '+9', tone: 'gain' })
    expect(weekChange(0)).toEqual({ text: '0', tone: 'faint' })
  })
  it('summarises cost', () => {
    expect(costSummary(pipeline().cost).map((c) => c.value)).toEqual(['US$1.86', 'US$0.03', 'US$5.88'])
    expect(costSummary({ week: 0, per_filing: null, budget_left: 0 }).map((c) => c.value)).toEqual(['US$0.00', '—', 'US$0.00'])
    expect(costSummary({ week: 0, per_filing: null, budget_left: 0 })[2].tone).toBe('loss')
  })
  it('shows the empty state only when off and never used', () => {
    expect(isEmptyState(pipeline({ enabled: false, started: false }))).toBe(true)
    expect(isEmptyState(pipeline({ enabled: false, started: true }))).toBe(false)
    expect(isEmptyState(pipeline({ enabled: true, started: false }))).toBe(false)
  })
})
