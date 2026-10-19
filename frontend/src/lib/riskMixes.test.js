import { describe, expect, it } from 'vitest'
import { mixLabel, weightsCaption } from './riskFormat.js'
import { EXPLAINERS, mixesYours } from './riskExplainers.js'

const w = (pairs) => pairs.map(([symbol, weight]) => ({ symbol, weight }))
// Shaped like GET /risk's mixes section (#243), with the Figma example numbers
const SECTION = {
  mixes: [
    { id: 'current', weights: w([['AAPL', 0.68], ['CBA', 0.21], ['BHP', 0.08], ['APA', 0.02], ['TLS', 0.01]]), volatility: 0.198, annual_return: 0.262, sharpe: 1.14 },
    { id: 'capped', name: 'Apple', weights: w([['AAPL', 0.4], ['CBA', 0.39], ['BHP', 0.15]]), volatility: 0.154, annual_return: 0.196, sharpe: 1.04 },
    { id: 'equal', weights: w([['AAPL', 0.2]]), volatility: 0.136, annual_return: 0.154, sharpe: 0.87 },
    { id: 'lowest_risk', weights: w([['TLS', 0.45], ['CBA', 0.3], ['APA', 0.25]]), volatility: 0.121, annual_return: 0.13, sharpe: 0.78 },
  ],
  cash: { cash_aud: 933000, share: 0.927, account_volatility: 0.0145 },
  count: 5,
}

describe('example mixes', () => {
  it('captions', () => {
    expect(weightsCaption(SECTION.mixes[0].weights)).toBe('AAPL 68%, CBA 21%, BHP 8%…')
    expect(mixLabel(SECTION.mixes[2], 5)).toEqual({ name: 'Equal weights', caption: '20% each' })
    expect(mixLabel(SECTION.mixes[1], 5).name).toBe('Apple capped at 40%')
  })

  it('What yours means', () => {
    expect(mixesYours(SECTION, '1Y')).toBe(
      'Capping Apple at 40% would have cut volatility from 19.8% to 15.4%, but last year it would also have cut your return. Your 92.7% cash already cushions your whole account.',
    )
  })

  it('never names a best mix', () => {
    const text = `${EXPLAINERS.mixes.what} ${EXPLAINERS.mixes.consider} ${mixesYours(SECTION, '1Y')}`
    expect(text).not.toMatch(/\bbest\b|optimal|recommend(?!ation)/i)
  })
})
