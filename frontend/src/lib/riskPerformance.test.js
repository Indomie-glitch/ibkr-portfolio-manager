import { describe, expect, it } from 'vitest'
import { explainerText, sharpeYours, trackingYours } from './riskExplainers.js'
import { TILE_ROWS } from './riskLayout.js'

// Shaped like GET /risk's performance section (#239), with the Figma example numbers
const SECTION = {
  portfolio: { annual_return: 0.262, volatility: 0.198, sharpe: 1.14 },
  benchmarks: { ASX: { annual_return: 0.1, volatility: 0.13, sharpe: 0.45 } },
  tracking_error: { ASX: 0.214, US: 0.098 },
  risk_free_rate: 0.046,
}
const tile = (id) => TILE_ROWS.flat().find((t) => t.id === id)

describe('Sharpe ratio and tracking error', () => {
  it('tiles', () => {
    expect(tile('sharpe').value(SECTION)).toBe('1.14')
    expect(tile('sharpe').sub(SECTION)).toBe('Return per unit of risk. ASX 200: 0.45')
    expect(tile('tracking_asx').value(SECTION)).toBe('21.4%')
    expect(tile('tracking_us').value(SECTION)).toBe('9.8%')
  })

  it('What yours means', () => {
    expect(explainerText('tracking_asx', { section: SECTION }).title).toBe('Tracking error · 21.4% vs ASX 200')
    expect(sharpeYours(SECTION, '1Y')).toBe(
      'Your holdings returned 26.2% with 19.8% volatility. After the 4.6% you’d have earned in cash, that’s 1.14 units of return per unit of risk. The ASX 200 managed 0.45.',
    )
    expect(sharpeYours(SECTION, '3M')).toContain('returned the equivalent of 26.2% a year')
    expect(trackingYours(SECTION.tracking_error ? SECTION : null)).toBe(
      'Your results can easily end up 21% above or below the ASX 200 in a year, because you hold different things from it. Against the S&P 500 it’s only 9.8%, because more of your results follow the US market.',
    )
  })
})
