import { describe, expect, it } from 'vitest'
import { severity } from './riskFormat.js'
import { stressYours } from './riskExplainers.js'

// Shaped like GET /risk's stress section (#241), with the Figma example numbers, worst first
const SECTION = {
  scenarios: [
    { kind: 'replay', id: 'gfc', name: 'GFC 2008 replay', impact_base: -34030, impact_pct: -0.47, estimated: [] },
    { kind: 'replay', id: 'covid', name: 'COVID crash replay', impact_base: -22440, impact_pct: -0.31, estimated: [] },
    { kind: 'shock', id: 'largest', name: 'Apple falls 20%', impact_base: -9870, impact_pct: -0.136 },
    { kind: 'shock', id: 'index_us', name: 'S&P 500 falls 10%', impact_base: -6440, impact_pct: -0.089 },
  ],
  value_base: 72400,
}

describe('stress tests', () => {
  it('severity', () => {
    expect(severity(-0.47)).toBe('high')
    expect(severity(-0.136)).toBe('medium')
    expect(severity(-0.05)).toBe('low')
    expect(severity(0.02)).toBeNull()
    expect(severity(null)).toBeNull()
  })

  it('What yours means, like the design', () => {
    expect(stressYours(SECTION, 'AUD')).toBe(
      'A repeat of 2008 would take about A$34,030 (47%). A 20% fall in Apple alone would cost about A$9,870, more than a 10% fall in the whole S&P 500.',
    )
  })
})
