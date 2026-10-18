// The order ticket's maths (#201). Run with: npm test
import { describe, expect, test } from 'vitest'
import {
  amountPrice,
  commissionText,
  estimates,
  orderFrom,
  outcomeUnknown,
  parseMoney,
  parseShares,
  sharesForAmount,
  stepShares,
  switchOrderBy,
} from './orderTicket.js'

const stock = { con_id: 265598, last: 342.76000975, currency: 'USD' }
const form = (change) => ({ side: 'BUY', orderType: 'LMT', by: 'shares', quantity: '1', amount: '', limitPrice: '342.76', tif: 'DAY', ...change })

describe('typed numbers', () => {
  test('shares: whole numbers only, anything else is refused, never changed', () => {
    expect(parseShares('25')).toEqual({ value: 25, problem: null })
    expect(parseShares(' 25 ')).toEqual({ value: 25, problem: null })
    expect(parseShares('')).toEqual({ value: null, problem: null })
    for (const odd of ['1e3', '0x10', '-5', 'abc', '1,000', '+3', 'Infinity']) {
      const { value, problem } = parseShares(odd)
      expect(value, odd).toBeNull()
      expect(problem, odd).toMatch(/digits only/)
    }
    expect(parseShares('1.5').problem).toBe('Orders are for whole shares only.')
    expect(parseShares('0').problem).toBe('Enter at least 1 share.')
  })

  test('money: decimals and thousands separators, nothing else', () => {
    expect(parseMoney('1500.50').value).toBe(1500.5)
    expect(parseMoney('1,500').value).toBe(1500)
    expect(parseMoney('.5').value).toBe(0.5)
    expect(parseMoney('12.').value).toBe(12)
    expect(parseMoney('')).toEqual({ value: null, problem: null })
    for (const odd of ['1e3', '0x10', '-5', '1.2.3', 'abc']) expect(parseMoney(odd).value, odd).toBeNull()
    expect(parseMoney('0', 'limit price').problem).toBe('The limit price must be more than zero.')
    expect(parseMoney('-5', 'limit price').problem).toBe('Enter the limit price as a number, e.g. 1500.50.')
  })
})

describe('ordering by amount', () => {
  test('a market order uses the latest price, a limit order the limit price', () => {
    expect(amountPrice(342.76000975, form({ orderType: 'MKT' }))).toBe(342.76000975)
    expect(amountPrice(342.76000975, form({ limitPrice: '300' }))).toBe(300)
    expect(amountPrice(null, form({ orderType: 'MKT' }))).toBeNull()
    expect(amountPrice(342.76, form({ limitPrice: '' }))).toBeNull()
  })

  test('rounds down to whole shares', () => {
    // 1000 / 342.76000975 = 2.917…
    expect(sharesForAmount(1000, 342.76000975)).toBe(2)
    expect(sharesForAmount(100, 342.76)).toBe(0)
    expect(sharesForAmount(null, 342.76)).toBeNull()
    expect(sharesForAmount(1000, null)).toBeNull()
  })

  test('an amount that buys exactly whole shares is not lost to floating-point noise', () => {
    // 0.7 / 0.1 is 6.9999999… in floating point
    expect(sharesForAmount(0.7, 0.1)).toBe(7)
    expect(sharesForAmount(1028.28, 342.76)).toBe(3)
  })

  test('the order uses the share count, and a limit order its limit price', () => {
    const { order, problems } = orderFrom(stock, form({ by: 'amount', amount: '1,000', limitPrice: '300' }))
    expect(problems).toEqual([])
    expect(order).toEqual({ con_id: 265598, action: 'BUY', quantity: 3, order_type: 'LMT', limit_price: 300, tif: 'DAY' })
  })
})

describe('the order sent for a preview', () => {
  test('shares, market order, good till cancelled', () => {
    const { order } = orderFrom(stock, form({ side: 'SELL', orderType: 'MKT', quantity: '7', tif: 'GTC' }))
    expect(order).toEqual({ con_id: 265598, action: 'SELL', quantity: 7, order_type: 'MKT', limit_price: null, tif: 'GTC' })
  })

  test('no order while incomplete, and a reason when something typed is wrong', () => {
    expect(orderFrom(stock, form({ quantity: '' }))).toEqual({ order: null, problems: [] })
    expect(orderFrom(stock, form({ limitPrice: '' }))).toEqual({ order: null, problems: [] })
    expect(orderFrom(stock, form({ quantity: '1e3' })).order).toBeNull()
    expect(orderFrom(stock, form({ quantity: '1.5' })).problems).toEqual(['Orders are for whole shares only.'])
    expect(orderFrom(stock, form({ quantity: '-5' })).problems).toEqual(['Enter the number of shares as digits only.'])
    expect(orderFrom(stock, form({ limitPrice: 'abc' })).problems).toEqual(['Enter the limit price as a number, e.g. 1500.50.'])
    // An amount below one share: no order, and the note under the field explains it
    expect(orderFrom(stock, form({ by: 'amount', amount: '100' }))).toEqual({ order: null, problems: [] })
  })
})

describe('switching between shares and amount', () => {
  test('shares -> amount -> shares gives the same number back', () => {
    const shares = form({ orderType: 'MKT', quantity: '3' })
    const amount = switchOrderBy(shares, 'amount', 342.76000975)
    // 3 × 342.76000975 = 1028.28002925, rounded up to the cent
    expect(amount.amount).toBe('1028.29')
    expect(switchOrderBy(amount, 'shares', 342.76000975).quantity).toBe('3')
  })

  test('without a price or shares the amount stays empty; an unusable amount keeps the old shares', () => {
    expect(switchOrderBy(form({ limitPrice: '' }), 'amount', 342.76).amount).toBe('')
    expect(switchOrderBy(form({ quantity: 'abc' }), 'amount', 342.76).amount).toBe('')
    expect(switchOrderBy(form({ by: 'amount', amount: '10', quantity: '4' }), 'shares', 342.76).quantity).toBe('4')
    const same = form()
    expect(switchOrderBy(same, 'shares', 342.76)).toBe(same)
  })
})

test('the stepper never goes below 1 share', () => {
  expect(stepShares('5', 1)).toBe('6')
  expect(stepShares('1', -1)).toBe('1')
  expect(stepShares('', 1)).toBe('1')
  expect(stepShares('1e3', 1)).toBe('1')
})

describe('estimates', () => {
  const preview = { estimated_value: 1000, estimated_value_base: 1520, what_if: { commission: 1.5, commission_currency: 'USD' } }

  test('a buy adds the commission, a sell subtracts it', () => {
    expect(estimates(preview, { side: 'BUY', currency: 'USD', buyingPower: 10000 })).toEqual({ value: 1000, total: 1001.5, buyingPowerAfter: 8480 })
    expect(estimates(preview, { side: 'SELL', currency: 'USD', buyingPower: 10000 })).toEqual({ value: 1000, total: 998.5, buyingPowerAfter: 11520 })
  })

  test('a commission in another currency is left out of the total', () => {
    const aud = { ...preview, what_if: { commission: 6, commission_currency: 'AUD' } }
    expect(estimates(aud, { side: 'BUY', currency: 'USD', buyingPower: 10000 }).total).toBe(1000)
  })

  test('nothing to show before a preview or without buying power', () => {
    expect(estimates(null, { side: 'BUY', currency: 'USD', buyingPower: 10000 })).toEqual({ value: null, total: null, buyingPowerAfter: null })
    expect(estimates(preview, { side: 'BUY', currency: 'USD', buyingPower: null }).buyingPowerAfter).toBeNull()
  })

  test('commission text: exact, a range, or a dash', () => {
    expect(commissionText({ commission: 1.5, commission_currency: 'USD' })).toBe('US$1.50')
    expect(commissionText({ min_commission: 1, max_commission: 2.5, commission_currency: 'USD' })).toBe('US$1.00–US$2.50')
    expect(commissionText({ commission_currency: 'USD' })).toBe('—')
    expect(commissionText(null)).toBe('—')
  })
})

test('after a failed Place, only a refusal before sending means the order surely wasn\'t placed', () => {
  // The backend refused: expired confirmation, a guardrail, bad input
  for (const status of [400, 404, 409, 422]) expect(outcomeUnknown({ status }), status).toBe(false)
  // No answer (network, timeout) or a server error: IBKR may have it
  expect(outcomeUnknown({ code: 'timeout' })).toBe(true)
  expect(outcomeUnknown({ code: 'network' })).toBe(true)
  expect(outcomeUnknown({ status: 500 })).toBe(true)
  expect(outcomeUnknown({ status: 503 })).toBe(true)
})
