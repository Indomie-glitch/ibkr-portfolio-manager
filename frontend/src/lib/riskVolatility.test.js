import { describe, expect, it } from 'vitest'
import { drawdownDates, pct, ratio } from './riskFormat.js'
import { explainerText, volatilityBetaYours } from './riskExplainers.js'
import { TILE_ROWS } from './riskLayout.js'

// Shaped like GET /risk's volatility section (#102)
const SECTION = {
  holdings: [
    { symbol: 'AAPL', market: 'US', weight: 0.68, volatility: 0.274, beta: 1.21, beta_vs: 'S&P 500' },
    { symbol: 'CBA', market: 'ASX', weight: 0.2, volatility: 0.189, beta: 0.92, beta_vs: 'ASX 200' },
    { symbol: 'BHP', market: 'ASX', weight: 0.097, volatility: 0.246, beta: 1.18, beta_vs: 'ASX 200' },
    { symbol: 'APA', market: 'ASX', weight: 0.013, volatility: 0.162, beta: 0.54, beta_vs: 'ASX 200' },
    { symbol: 'TLS', market: 'ASX', weight: 0.01, volatility: 0.148, beta: 0.48, beta_vs: 'ASX 200' },
  ],
  portfolio: { volatility: 0.198, beta_asx: 0.47, beta_us: 0.89, value_aud: 72400, us_weight: 0.68 },
  benchmarks: { ASX: { name: 'ASX 200', volatility: 0.13 }, US: { name: 'S&P 500', volatility: 0.16 } },
  max_drawdown: { fall: -0.163, peak: '2026-04-02', trough: '2026-04-21', loss_aud: -11801 },
}
const tile = (id) => TILE_ROWS.flat().find((t) => t.id === id)

describe('number formats', () => {
  it('percentages and ratios', () => {
    expect(pct(0.198)).toBe('19.8%')
    expect(pct(-0.163)).toBe('−16.3%')
    expect(pct(0.05, { signed: true })).toBe('+5.0%')
    expect(pct(-0.0001)).toBe('0.0%') // no "−0.0%"
    expect(pct(null)).toBe('—')
    expect(ratio(0.4712)).toBe('0.47')
    expect(ratio(-0.2)).toBe('−0.20')
  })

  it('drawdown dates', () => {
    expect(drawdownDates(SECTION.max_drawdown)).toBe('Peak 2 Apr, low 21 Apr 2026')
    expect(drawdownDates({ fall: 0, peak: null })).toBe('No fall in this period')
  })
})

describe('volatility tiles (Figma values)', () => {
  it('match the design', () => {
    expect(tile('volatility').value(SECTION)).toBe('19.8%')
    expect(tile('beta_asx').value(SECTION)).toBe('0.47')
    expect(tile('beta_asx').sub(SECTION)).toBe('Moves 4.7% when the ASX moves 10%')
    expect(tile('beta_us').sub(SECTION)).toBe('Moves 8.9% when the S&P moves 10%')
    expect(tile('max_drawdown').value(SECTION)).toBe('−16.3%')
    expect(tile('max_drawdown').tone(SECTION)).toBe('loss')
  })
})

describe('What yours means', () => {
  const yours = (id) => explainerText(id, { section: SECTION, meta: {} })

  it('volatility in dollars and against the ASX 200', () => {
    expect(yours('volatility').title).toBe('Volatility · 19.8%')
    expect(yours('volatility').yours).toBe(
      'In a normal year your A$72.4k of holdings could end about A$14,335 above or below its average. That’s more than the ASX 200, which swung about 13% over the same period.',
    )
  })

  it('betas', () => {
    expect(yours('beta_asx').yours).toBe(
      'If the ASX 200 fell 10%, you’d expect your holdings to fall about 4.7%. It’s low because 68% of your money is in US shares, which follow the US market instead.',
    )
    expect(yours('beta_us').yours).toBe(
      'If the S&P 500 fell 10%, you’d expect your holdings to fall about 8.9%. Your results mostly follow the US market, through the 68% of your money in US shares.',
    )
  })

  it('biggest fall', () => {
    expect(yours('max_drawdown').title).toBe('Biggest fall · −16.3%')
    expect(yours('max_drawdown').yours).toBe(
      'Between 2 Apr and 21 Apr 2026 your holdings fell 16.3%. At today’s size that’s about A$11,801.',
    )
  })

  it('per holding, like the design', () => {
    expect(volatilityBetaYours(SECTION.holdings)).toBe(
      'AAPL and BHP swing most, and move more than their markets. TLS and APA are the calmest, but together they’re only 2.3% of your money.',
    )
  })
})
