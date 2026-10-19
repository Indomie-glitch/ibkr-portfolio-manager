import { describe, expect, it } from 'vitest'
import { varPlainWords } from './riskFormat.js'
import { explainerText, varYours } from './riskExplainers.js'
import { TILE_ROWS } from './riskLayout.js'

const entry = (aud) => ({ return: aud / 72400, aud })
// Shaped like GET /risk's var section (#240), with the Figma example numbers
const SECTION = {
  value_aud: 72400,
  levels: {
    95: { formula: { day: entry(-1485), month: entry(-6810) }, history: { day: entry(-1620), month: entry(-7350) }, simulated: { day: entry(-1530), month: entry(-7010) } },
    99: { formula: { day: entry(-2100), month: entry(-9620) }, history: { day: entry(-2500), month: entry(-9900) }, simulated: { day: entry(-2150), month: entry(-9700) } },
  },
  runs: 10000,
  month_days: 21,
}
const tile = TILE_ROWS.flat().find((t) => t.id === 'var_1d')

describe('Value at Risk', () => {
  it('tile', () => {
    expect(tile.value(SECTION)).toBe('−A$1,485')
    expect(tile.tone(SECTION)).toBe('loss')
  })

  it('plain words', () => {
    expect(varPlainWords(SECTION, '1Y')).toBe(
      'On about 1 trading day in 20, expect to lose more than A$1,485. The history based figure is higher because real markets have more extreme days than the formula assumes.',
    )
    const calm = { ...SECTION, levels: { ...SECTION.levels, 95: { ...SECTION.levels[95], history: { day: entry(-1200) } } } }
    expect(varPlainWords(calm, '3M')).toContain('The history based figure is lower: the past 3 months had fewer extreme days')
  })

  it('What yours means', () => {
    expect(explainerText('var', { section: SECTION }).title).toBe('Value at Risk · −A$1,485')
    expect(varYours(SECTION)).toBe(
      'On about 1 trading day in 20 you could lose more than A$1,485, and on 1 day in 100 more than A$2,100. Over a month, the 1 in 20 figure is about A$6,810.',
    )
  })
})
