import { describe, expect, it } from 'vitest'
import { factorsHeadline } from './riskFormat.js'
import { factorsYours } from './riskExplainers.js'

// Shaped like GET /risk's factors section (#105), with the Figma example numbers
const SECTION = {
  factors: [
    { id: 'F1', share: 0.41, name: 'Australian market' },
    { id: 'F2', share: 0.27, name: 'US tech (Apple)', top_holding: 'AAPL' },
    { id: 'F3', share: 0.15, name: 'Mostly BHP' },
    { id: 'F4', share: 0.1, name: 'Mostly APA' },
    { id: 'F5', share: 0.07, name: 'Mostly TLS' },
  ],
  loadings: [
    { symbol: 'AAPL', f1: 0.14, f2: 0.96 },
    { symbol: 'CBA', f1: 0.56, f2: 0.1 },
    { symbol: 'BHP', f1: 0.51, f2: 0.15 },
    { symbol: 'APA', f1: 0.44, f2: -0.08 },
    { symbol: 'TLS', f1: 0.46, f2: -0.12 },
  ],
  top2_share: 0.68,
  count: 5,
}

describe('hidden factors', () => {
  it('headline', () => {
    expect(factorsHeadline(SECTION)).toBe('Two factors explain 68% of how your holdings move.')
    expect(factorsHeadline({ factors: [{ share: 0.8 }, { share: 0.2 }], count: 2 })).toBe(
      'One factor explains 80% of how your holdings move.',
    )
  })

  it('What yours means', () => {
    expect(factorsYours(SECTION)).toBe(
      'Two patterns explain 68%: Australian market (CBA, BHP, TLS and APA) and US tech (Apple). The rest is each holding moving on its own.',
    )
  })
})
