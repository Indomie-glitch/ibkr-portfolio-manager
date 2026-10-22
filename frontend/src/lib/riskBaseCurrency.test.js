import { describe, expect, it } from 'vitest'
import { currencyName, formatMoney } from './format.js'
import { asOfText, benchmarkNames, calculatedNote, currencySentence, homeIndexName, varPlainWords } from './riskFormat.js'
import { attributionYours, currencyYours, explainerText, exposureYours, stressYours } from './riskExplainers.js'

// GET /risk's meta for a Singapore dollar account holding Australian and US shares (#271)
const META = {
  currency: 'SGD',
  home_market: 'SG',
  calculated_at: '2026-10-22T21:00:00+08:00',
  days_used: 244,
  period: '1Y',
  benchmarks: {
    ASX: { symbol: '^AXJT', short: 'ASX 200', total_return: true },
    US: { symbol: '^SP500TR', short: 'S&P 500', total_return: true },
    SG: { symbol: '^STI', short: 'STI', total_return: false },
  },
  fx_pairs: [
    { currency: 'AUD', pair: 'AUD/SGD', symbol: 'AUDSGD=X' },
    { currency: 'USD', pair: 'USD/SGD', symbol: 'USDSGD=X' },
  ],
}

const CURRENCY = {
  holdings: [
    { symbol: 'AAPL', name: 'Apple', currency: 'USD', value_base: 60000, price_return: 0.2, fx_return: -0.03, base_return: 0.164, effect_base: -1856 },
    { symbol: 'BHP', name: 'BHP Group', currency: 'AUD', value_base: 9000, price_return: 0.05, fx_return: 0.01, base_return: 0.0605, effect_base: 89 },
  ],
  fx_currency: 'USD',
  fx_return: -0.03,
  currencies: [
    { currency: 'AUD', pair: 'AUD/SGD', fx_return: 0.01 },
    { currency: 'USD', pair: 'USD/SGD', fx_return: -0.03 },
  ],
  total_effect_base: -1767,
}

describe('an SGD account', () => {
  it('money and currency names', () => {
    expect(formatMoney(-1767, 'SGD', { decimals: 0 })).toBe('−S$1,767')
    expect(currencyName('SGD')).toBe('Singapore dollar')
    expect(currencyName('EUR')).toBe('EUR')
  })

  it('command bar and notes', () => {
    expect(benchmarkNames(META)).toBe('ASX 200 · S&P 500 · STI')
    expect(homeIndexName(META)).toBe('STI')
    expect(asOfText(META)).toContain('· SGD · 244 trading days')
    expect(calculatedNote(META)).toContain('Daily returns in SGD')
  })

  it('currency effect', () => {
    expect(currencySentence(CURRENCY, '1Y', 'SGD')).toBe('A stronger Singapore dollar shrank your US gains this year.')
    expect(currencyYours(CURRENCY, '1Y', 'SGD')).toBe(
      'Apple rose 20.0% in US dollars, but the Singapore dollar strengthened, so in SGD you got 16.4%. The exchange rate cost you about S$1,767 this year.',
    )
    const text = explainerText('currency', { section: CURRENCY, meta: META })
    expect(text.title).toBe('Currency effect · −S$1,767')
    expect(text.what).toBe(
      'For an Australian or US stock, how much of your return in SGD came from the share price and how much from the exchange rate.',
    )
    expect(text.consider).toContain('owning Australian and US shares.')
  })

  it('exposure', () => {
    const section = { currency: [{ name: 'USD', share: 0.6 }, { name: 'AUD', share: 0.3 }, { name: 'SGD', share: 0.1 }], sector: [] }
    expect(exposureYours(section, 'SGD')).toBe(
      '90% is in US dollars and Australian dollars, so the exchange rates between the Singapore dollar and the US and Australian dollars change your returns even on days your US and Australian shares don’t move.',
    )
    expect(exposureYours({ currency: [{ name: 'SGD', share: 1 }], sector: [] }, 'SGD')).toBe(
      'All of it is in Singapore dollars, so exchange rates don’t change your returns.',
    )
    expect(explainerText('exposure', { section, meta: META }).consider).toContain('in Singapore dollars would make you')
  })

  it('attribution against the STI', () => {
    const section = {
      benchmark: 'STI',
      difference: 0.08,
      allocation: 0.06,
      selection: 0.03,
      currency: -0.01,
      segments: [
        { market: 'ASX', weight: 0.2, home: false },
        { market: 'US', weight: 0.8, home: false },
      ],
    }
    expect(attributionYours(section)).toBe(
      'You beat the STI by 8.0 points. 6.0 came from being in Australian and US shares rather than the local market, 3.0 from the stocks you picked and the exchange rate cost 1.0.',
    )
    expect(explainerText('attribution', { section, meta: META }).what).toContain('differed from the STI,')
  })

  it('stress tests and Value at Risk in S$', () => {
    const scenarios = [{ kind: 'replay', id: 'gfc', name: 'GFC 2008 replay', impact_base: -20000, impact_pct: -0.3 }]
    expect(stressYours({ scenarios }, 'SGD')).toBe('A repeat of 2008 would take about S$20,000 (30%).')
    const entry = (base) => ({ return: base / 69000, base })
    const levels = { 95: { formula: { day: entry(-1500) }, history: { day: entry(-1500) } } }
    expect(varPlainWords({ levels }, '1Y', 'SGD')).toContain('expect to lose more than S$1,500.')
  })

  it('explainers before the numbers arrive', () => {
    expect(explainerText('currency', null).what).toBe(
      'For a stock in another currency, how much of your return came from the share price and how much from the exchange rate.',
    )
    expect(explainerText('attribution', null).what).toContain('differed from the home market’s index,')
  })
})
