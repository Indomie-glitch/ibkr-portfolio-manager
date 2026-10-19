import { beforeEach, describe, expect, it, vi } from 'vitest'
import { zoneLabel } from './riskFormat.js'
import { bankruptcyYours } from './riskExplainers.js'
import { clearRiskRequests, loadBankruptcy } from './riskData.js'

vi.mock('./api.js', () => ({ fetchRisk: vi.fn(), fetchRiskBankruptcy: vi.fn() }))

// Shaped like GET /risk/bankruptcy (#244), with the Figma example numbers
const ANSWER = {
  holdings: [
    { symbol: 'AAPL', name: 'Apple', zone: 'safe', score: 9.8 },
    { symbol: 'BHP', name: 'BHP Group', zone: 'safe', score: 4.6 },
    { symbol: 'TLS', name: 'Telstra', zone: 'grey', score: 1.9 },
    { symbol: 'APA', name: 'APA Group', zone: 'distress', score: 1.1, low_by_design: true },
    { symbol: 'CBA', name: 'Commonwealth Bank', zone: 'bank', score: null },
  ],
}

describe('bankruptcy risk', () => {
  beforeEach(() => clearRiskRequests())

  it('zones', () => {
    expect(ANSWER.holdings.map(zoneLabel)).toEqual(['Safe', 'Safe', 'Grey', 'Distress*', 'Not used for banks'])
  })

  it('What yours means, like the design', () => {
    expect(bankruptcyYours(ANSWER)).toBe(
      'AAPL (9.8) and BHP (4.6) are comfortably safe. TLS is in the grey zone. APA scores low mainly because utilities and property companies carry a lot of debt by design. The score doesn’t work for banks like CBA.',
    )
  })

  it('loads from its own endpoint, once per version', async () => {
    const fetcher = vi.fn().mockResolvedValue(ANSWER)
    const [a, b] = await Promise.all([loadBankruptcy(0, fetcher), loadBankruptcy(0, fetcher)])
    expect(a.section).toBe(ANSWER)
    expect(b.section).toBe(ANSWER)
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})
