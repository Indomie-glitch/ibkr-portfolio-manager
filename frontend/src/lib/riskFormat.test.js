import { describe, expect, it } from 'vitest'
import { extraNotes, leftOutNote, riskSubtitle } from './riskFormat.js'
import { EXPLAINERS, explainerText } from './riskExplainers.js'
import { PANELS, TILE_ROWS } from './riskLayout.js'

const META = { period: '1Y', holdings_count: 5, last_day: '2026-10-16', left_out: [], days_used: 244, stale: [] }

describe('Risk page text', () => {
  it('subtitle names the last daily close', () => {
    expect(riskSubtitle(META, 5)).toBe('5 holdings · Daily closes to 16 Oct 2026')
    expect(riskSubtitle({ ...META, holdings_count: 1 }, 1)).toBe('1 holding · Daily closes to 16 Oct 2026')
    expect(riskSubtitle(null, 3)).toBe('3 holdings · Loading daily closes…')
    expect(riskSubtitle(null, 3, true)).toBe('3 holdings · Daily closes unavailable')
  })

  it('says which holdings were left out and why', () => {
    expect(leftOutNote(META)).toBe('Left out: none · All 5 holdings have a full year of prices')
    expect(leftOutNote({ ...META, period: '3M' })).toBe('Left out: none · All 5 holdings have a full 3 months of prices')
    const left = [{ symbol: 'NEW', reason: 'Prices only from 2 Oct 2026' }, { symbol: 'SAP', reason: 'Only AUD and USD holdings are included (EUR)' }]
    expect(leftOutNote({ ...META, left_out: left })).toBe(
      'Left out: NEW (Prices only from 2 Oct 2026) · SAP (Only AUD and USD holdings are included (EUR))',
    )
  })

  it('mentions a price index fallback and prices that couldn’t be updated', () => {
    expect(extraNotes(META)).toEqual([])
    expect(extraNotes({ ...META, benchmark_note: 'No total return series', stale: ['AAPL'] })).toEqual([
      'No total return series',
      'Couldn’t update today: AAPL (earlier prices used)',
    ])
  })
})

describe('Risk explainers', () => {
  it('every tile and panel has one', () => {
    const ids = [...TILE_ROWS.flat().map((t) => t.explainer), ...PANELS.map((p) => p.explainer)]
    for (const id of ids) expect(EXPLAINERS[id], id).toBeTruthy()
  })

  it('never tells the reader what to do', () => {
    const advice = /\byou should\b|\bshould you\b|\bconsider (buying|selling)\b|\b(buy|sell) more\b|\bcheck it\b|\bask (whether|which)\b/i
    for (const [id, entry] of Object.entries(EXPLAINERS)) {
      expect(`${entry.what} ${entry.consider}`, id).not.toMatch(advice)
    }
  })

  it('leaves out What yours means until the number is known', () => {
    const text = explainerText('volatility', null)
    expect(text.title).toBe('Volatility')
    expect(text.yours).toBeNull()
    expect(explainerText('nope', null)).toBeNull()
  })
})

describe('Risk layout', () => {
  it('has twelve panels numbered in order, six per column', () => {
    expect(PANELS.map((p) => p.order)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
    expect(PANELS.filter((p) => p.column === 'left')).toHaveLength(6)
    expect(TILE_ROWS.map((r) => r.length)).toEqual([5, 5])
  })
})
