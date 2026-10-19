import { describe, expect, it } from 'vitest'
import { corr, corrColour, describeAverage, describePair, pairTooltip } from './riskFormat.js'
import { correlationYours } from './riskExplainers.js'

describe('correlation heatmap', () => {
  it('numbers and colours', () => {
    expect(corr(0.48)).toBe('+0.48')
    expect(corr(-0.1)).toBe('−0.10')
    expect(corr(-0.001)).toBe('0.00')
    // Opacity 0.1 + 0.85 × |c|, as in the design (+0.48 → 51%)
    expect(corrColour(0.48)).toBe('color-mix(in srgb, var(--risk-key-on) 51%, transparent)')
    expect(corrColour(-0.2)).toBe('color-mix(in srgb, var(--accent) 27%, transparent)')
  })

  it('words', () => {
    expect(describePair(0.48)).toBe('Often rise and fall on the same days')
    expect(describePair(0.03)).toBe('Move almost independently')
    expect(describePair(-0.4)).toBe('Usually move in opposite directions')
    expect(describeAverage(0.23)).toBe('Your holdings mostly move independently')
  })

  it('hover text, as in the design', () => {
    const pair = { a: 'CBA', b: 'BHP', correlation: 0.48, same_direction: 0.66, b_per_a: 0.5 }
    expect(pairTooltip(pair, '1Y')).toBe(
      'Moved the same way on 66% of days in the last year. When CBA fell 2%, BHP tended to fall about 1%.',
    )
    expect(pairTooltip({ ...pair, b_per_a: -0.6 }, '3M')).toBe(
      'Moved the same way on 66% of days in the last 3 months. When CBA fell 2%, BHP tended to rise about 1%.',
    )
  })

  it('What yours means', () => {
    expect(correlationYours({ average: 0.23, most_related: { a: 'CBA', b: 'BHP', correlation: 0.48 } })).toBe(
      'Your average is +0.23: your holdings mostly move independently, which helps, because when one falls the others often don’t. CBA and BHP move together most (+0.48).',
    )
  })
})
