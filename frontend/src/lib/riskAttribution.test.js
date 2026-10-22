import { describe, expect, it } from 'vitest'
import { points } from './riskFormat.js'
import { attributionYours } from './riskExplainers.js'

// What GET /risk's attribution section says about the account (#271): the ASX 200 and the two markets
const AUD_ACCOUNT = {
  benchmark: 'ASX 200',
  segments: [
    { market: 'ASX', weight: 0.32, home: true },
    { market: 'US', weight: 0.68, home: false },
  ],
}

describe('attribution', () => {
  it('points', () => {
    expect(points(0.139)).toBe('+13.9 pts')
    expect(points(-0.018)).toBe('−1.8 pts')
  })

  it('What yours means, like the design', () => {
    expect(attributionYours({ ...AUD_ACCOUNT, difference: 0.167, allocation: 0.139, selection: 0.046, currency: -0.018 })).toBe(
      'You beat the ASX 200 by 16.7 points. 13.9 came from being in US shares rather than the local market, 4.6 from the stocks you picked and the exchange rate cost 1.8.',
    )
    expect(attributionYours({ ...AUD_ACCOUNT, difference: -0.05, allocation: 0, selection: -0.05, currency: 0 })).toBe(
      'You trailed the ASX 200 by 5.0 points. The stocks you picked cost 5.0.',
    )
  })
})
