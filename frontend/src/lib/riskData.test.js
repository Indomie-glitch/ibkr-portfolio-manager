import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clearRiskRequests, loadRisk, loadSection } from './riskData.js'

// api.js reads the Mac app's window settings when it loads; these tests pass their own fetcher
vi.mock('./api.js', () => ({ fetchRisk: vi.fn() }))

const ANSWER = {
  meta: { period: '1Y', days_used: 244 },
  holdings: [{ symbol: 'BHP' }],
  correlation: { average: 0.23 },
  broken: { error: 'Couldn’t calculate this section.' },
}

describe('loadRisk', () => {
  beforeEach(() => clearRiskRequests())

  it('shares one request between every panel of a period', async () => {
    const fetcher = vi.fn().mockResolvedValue(ANSWER)
    await Promise.all([loadRisk('1Y', 0, fetcher), loadSection('1Y', 0, 'correlation', fetcher), loadRisk('1Y', 0, fetcher)])
    expect(fetcher).toHaveBeenCalledTimes(1)
    await loadRisk('3M', 0, fetcher)
    await loadRisk('1Y', 1, fetcher) // a newer version asks again
    expect(fetcher).toHaveBeenCalledTimes(3)
  })

  it('asks again after a failure', async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(ANSWER)
    await expect(loadRisk('1Y', 0, fetcher)).rejects.toThrow('offline')
    await expect(loadRisk('1Y', 0, fetcher)).resolves.toBe(ANSWER)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })
})

describe('loadSection', () => {
  beforeEach(() => clearRiskRequests())

  it('returns the section with the shared meta and holdings', async () => {
    const fetcher = vi.fn().mockResolvedValue(ANSWER)
    const got = await loadSection('1Y', 0, 'correlation', fetcher)
    expect(got).toEqual({ section: { average: 0.23 }, meta: ANSWER.meta, holdings: ANSWER.holdings })
  })

  it('fails only for a section the backend couldn’t calculate or doesn’t send', async () => {
    const fetcher = vi.fn().mockResolvedValue(ANSWER)
    await expect(loadSection('1Y', 0, 'broken', fetcher)).rejects.toThrow('Couldn’t calculate this section.')
    await expect(loadSection('1Y', 0, 'liquidity', fetcher)).rejects.toThrow('Not calculated yet.')
    await expect(loadSection('1Y', 0, 'correlation', fetcher)).resolves.toBeTruthy()
  })
})
