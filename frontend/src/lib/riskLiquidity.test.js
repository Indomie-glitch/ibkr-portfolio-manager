import { describe, expect, it } from 'vitest'
import { compactVolume, sellTime, sellTone } from './riskFormat.js'
import { liquidityYours } from './riskExplainers.js'
import { TILE_ROWS } from './riskLayout.js'

const tile = TILE_ROWS.flat().find((t) => t.id === 'liquidity')

describe('liquidity', () => {
  it('time to sell', () => {
    expect(sellTime({ days: 0.001, minutes: 0.39 })).toBe('< 1 min')
    expect(sellTime({ days: 0.1, minutes: 25 })).toBe('25 min')
    expect(sellTime({ days: 0.4, minutes: 130 })).toBe('2 h 10 min')
    expect(sellTime({ days: 1.5, minutes: 585 })).toBe('1.5 days')
    expect(sellTime({ days: null })).toBe('—')
    expect(sellTone({ days: 0.5 })).toBe('gain')
    expect(sellTone({ days: 3 })).toBe('amber')
    expect(sellTone({ days: 8 })).toBe('loss')
  })

  it('volumes', () => {
    expect(compactVolume(25_600_000)).toBe('25.6M')
    expect(compactVolume(2_000_000)).toBe('2M')
    expect(compactVolume(980_000)).toBe('980K')
    expect(compactVolume(null)).toBe('—')
  })

  it('tile and What yours means', () => {
    const section = { slowest: { symbol: 'TLS', days: 0.0001, minutes: 0.04 } }
    expect(tile.value(section)).toBe('< 1 min')
    expect(liquidityYours(section)).toBe(
      'Every position could be sold in under a minute: your holdings are tiny next to what trades each day.',
    )
    expect(liquidityYours({ slowest: { symbol: 'XYZ', days: 2, minutes: 720 } })).toBe(
      'XYZ would take about 2.0 days to sell without your own selling moving its price.',
    )
  })
})
