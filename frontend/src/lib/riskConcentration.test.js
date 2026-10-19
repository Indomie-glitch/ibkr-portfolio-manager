import { describe, expect, it } from 'vitest'
import { concentrationWarning } from './riskFormat.js'
import { concentrationYours, effectiveHoldingsYours, explainerText } from './riskExplainers.js'
import { TILE_ROWS } from './riskLayout.js'

// Shaped like GET /risk's concentration section (#99), with the Figma example numbers
const SECTION = {
  holdings: [
    { symbol: 'AAPL', weight: 0.682, risk_share: 0.916 },
    { symbol: 'CBA', weight: 0.213, risk_share: 0.061 },
    { symbol: 'BHP', weight: 0.083, risk_share: 0.02 },
    { symbol: 'APA', weight: 0.016, risk_share: 0.002 },
    { symbol: 'TLS', weight: 0.007, risk_share: 0.001 },
  ],
  count: 5,
  top3_share: 0.978,
  largest: { symbol: 'AAPL', weight: 0.682, risk_share: 0.916 },
  effective_holdings: 1.93,
  warnings: [{ kind: 'stock', name: 'AAPL', share: 0.682, threshold: 0.2 }],
}
const tile = TILE_ROWS.flat().find((t) => t.id === 'effective_holdings')

describe('concentration', () => {
  it('tile', () => {
    expect(tile.value(SECTION)).toBe('1.9 / 5')
    expect(tile.sub(SECTION)).toBe('Behaves like about 2 stocks')
    expect(tile.tone(SECTION)).toBe('amber')
    expect(tile.tone({ ...SECTION, effective_holdings: 4.2 })).toBeUndefined()
  })

  it('warnings', () => {
    expect(concentrationWarning(SECTION.warnings[0])).toBe('AAPL is 68.2% of your holdings, over the 20% level')
  })

  it('What yours means', () => {
    expect(explainerText('effective_holdings', { section: SECTION }).title).toBe('Effective holdings · 1.9 of 5')
    expect(effectiveHoldingsYours(SECTION)).toBe(
      'You own 5 stocks, but they’re uneven enough that you behave like about 2. A bad result for AAPL moves most of your portfolio.',
    )
    expect(effectiveHoldingsYours({ ...SECTION, effective_holdings: 4.6 })).toBe(
      'Your money is spread fairly evenly across your 5 stocks, so you behave like about 5.',
    )
    expect(concentrationYours(SECTION)).toBe(
      'AAPL is 68% of your money but causes 92% of the swings, because it moves more than your other holdings and they don’t offset it.',
    )
    const calmer = [{ symbol: 'CBA', weight: 0.5, risk_share: 0.3 }, { symbol: 'BHP', weight: 0.5, risk_share: 0.7 }]
    expect(concentrationYours({ holdings: calmer })).toBe(
      'CBA is 50% of your money but causes only 30% of the swings, because it moves less than your other holdings or offsets them.',
    )
  })
})

describe('exposure', () => {
  it('What yours means', async () => {
    const { exposureYours } = await import('./riskExplainers.js')
    const section = {
      currency: [{ name: 'USD', share: 0.682 }, { name: 'AUD', share: 0.318 }],
      sector: [{ name: 'Technology', share: 0.682 }, { name: 'Financials', share: 0.213 }],
    }
    expect(exposureYours(section)).toBe(
      '68% is in US dollars, so the exchange rate between the Australian and US dollar changes your returns even on days your US shares don’t move. 68% is in one industry, Technology.',
    )
    expect(exposureYours({ currency: [{ name: 'AUD', share: 1 }], sector: [{ name: 'Unknown', share: 0.5 }, { name: 'Financials', share: 0.3 }] })).toBe(
      'All of it is in Australian dollars, so exchange rates don’t change your returns. Your largest industry is Financials, at 30%.',
    )
  })
})
