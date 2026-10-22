import { describe, expect, it } from 'vitest'
import { currencySentence } from './riskFormat.js'
import { currencyYours, explainerText } from './riskExplainers.js'

// Shaped like GET /risk's currency section (#101), with the Figma example numbers
const SECTION = {
  holdings: [
    { symbol: 'AAPL', name: 'Apple', currency: 'USD', value_base: 49400, price_return: 0.393, fx_return: -0.054, base_return: 0.318, effect_base: -1862 },
  ],
  fx_currency: 'USD',
  fx_return: -0.054,
  currencies: [{ currency: 'USD', pair: 'AUD/USD', fx_return: -0.054 }],
  total_effect_base: -1862,
}

describe('currency effect', () => {
  it('one-line explanation', () => {
    expect(currencySentence(SECTION, '1Y', 'AUD')).toBe('A stronger Australian dollar shrank your US gains this year.')
    const weaker = { ...SECTION, fx_return: 0.03, holdings: [{ ...SECTION.holdings[0], price_return: -0.1 }] }
    expect(currencySentence(weaker, '3M', 'AUD')).toBe('A weaker Australian dollar softened your US losses over the last 3 months.')
  })

  it('What yours means', () => {
    expect(explainerText('currency', { section: SECTION, meta: { period: '1Y', currency: 'AUD' } }).title).toBe('Currency effect · −A$1,862')
    expect(currencyYours(SECTION, '1Y', 'AUD')).toBe(
      'Apple rose 39.3% in US dollars, but the Australian dollar strengthened, so in AUD you got 31.8%. The exchange rate cost you about A$1,862 this year.',
    )
    expect(currencyYours({ holdings: [], total_effect_base: 0, currencies: [{ currency: 'USD' }] }, '1Y', 'AUD')).toBe(
      'You have no US holdings, so exchange rates don’t change your returns.',
    )
  })
})
