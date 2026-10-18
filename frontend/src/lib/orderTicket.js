// The order ticket's maths (#201), kept out of the component so it can be tested
// (orderTicket.test.js). The backend checks every order again (whole shares, the value limit, not
// selling more than you hold), but only this file knows what the user typed and meant.
import { formatMoney } from './format.js'

// A whole number of shares: digits only (no "1e3", "0x10", "-5", "1.5" or blanks)
const WHOLE = /^\d+$/
// Money: digits with an optional decimal part ("500", "500.5", ".5"); commas and spaces are
// allowed as thousands separators and ignored
const DECIMAL = /^(\d+(\.\d*)?|\.\d+)$/

// Quantity text -> { value, problem }. value is a whole number above 0, or null with a reason
// (null problem too when the field is just empty)
export function parseShares(text) {
  const raw = String(text ?? '').trim()
  if (raw === '') return { value: null, problem: null }
  if (WHOLE.test(raw)) {
    const value = Number(raw)
    return value > 0 ? { value, problem: null } : { value: null, problem: 'Enter at least 1 share.' }
  }
  if (/^\d*\.\d+$/.test(raw)) return { value: null, problem: 'Orders are for whole shares only.' }
  return { value: null, problem: 'Enter the number of shares as digits only.' }
}

// Amount or limit price text -> { value, problem } (value above 0, or null)
export function parseMoney(text, what = 'amount') {
  const raw = String(text ?? '').trim().replace(/[,\s]/g, '')
  if (raw === '') return { value: null, problem: null }
  if (!DECIMAL.test(raw)) return { value: null, problem: `Enter the ${what} as a number, e.g. 1500.50.` }
  const value = Number(raw)
  return value > 0 ? { value, problem: null } : { value: null, problem: `The ${what} must be more than zero.` }
}

// The price an amount is divided by: the limit price, or for a market order the latest price
export function amountPrice(last, form) {
  const price = form.orderType === 'LMT' ? parseMoney(form.limitPrice).value : last
  return price > 0 ? price : null
}

// Ordering by amount: the whole number of shares it buys or sells (orders are whole shares only,
// so it rounds down); null until there's an amount and a price (#161)
export function sharesForAmount(amount, price) {
  if (!(amount > 0) || !(price > 0)) return null
  // IBKR's prices carry more decimals than are shown (342.76000975), so allow for rounding noise:
  // a millionth of a share, far less than a cent
  return Math.floor(amount / price + 1e-6)
}

// The order the form describes, in the shape POST /orders/preview takes, and any problems with what
// was typed. order is null while the form is incomplete or has a problem.
export function orderFrom(stock, form) {
  const problems = []
  let quantity = null
  if (form.by === 'amount') {
    const amount = parseMoney(form.amount)
    if (amount.problem) problems.push(amount.problem)
    quantity = sharesForAmount(amount.value, amountPrice(stock.last, form))
  } else {
    const shares = parseShares(form.quantity)
    if (shares.problem) problems.push(shares.problem)
    quantity = shares.value
  }
  let limitPrice = null
  if (form.orderType === 'LMT') {
    const limit = parseMoney(form.limitPrice, 'limit price')
    if (limit.problem) problems.push(limit.problem)
    limitPrice = limit.value
  }
  const complete = quantity > 0 && (form.orderType !== 'LMT' || limitPrice > 0)
  if (!complete || problems.length) return { order: null, problems }
  return {
    order: {
      con_id: stock.con_id,
      action: form.side,
      quantity,
      order_type: form.orderType,
      limit_price: limitPrice,
      tif: form.tif,
    },
    problems,
  }
}

// The stepper: one share more or less, never below 1 (unreadable text starts from 0)
export function stepShares(text, by) {
  const shares = parseShares(text).value ?? 0
  return String(Math.max(1, shares + by))
}

// Switching between Shares and Amount keeps the order about the same size: shares × price becomes
// the amount (rounded up to the cent, so switching back gives the same shares), and back
export function switchOrderBy(form, by, last) {
  if (form.by === by) return form
  const price = amountPrice(last, form)
  if (by === 'amount') {
    const shares = parseShares(form.quantity).value
    const amount = price && shares ? (Math.ceil(shares * price * 100) / 100).toFixed(2) : ''
    return { ...form, by, amount }
  }
  const shares = sharesForAmount(parseMoney(form.amount).value, price)
  return { ...form, by, quantity: shares > 0 ? String(shares) : form.quantity }
}

// Commission from the preview: the exact figure, or IBKR's min–max range
export function commissionText(whatIf) {
  if (!whatIf) return '—'
  const currency = whatIf.commission_currency
  if (whatIf.commission != null) return formatMoney(whatIf.commission, currency)
  if (whatIf.min_commission != null && whatIf.max_commission != null) {
    return `${formatMoney(whatIf.min_commission, currency)}–${formatMoney(whatIf.max_commission, currency)}`
  }
  return '—'
}

// The estimate lines under the form, from the preview (all null until there is one).
// total: the value plus commission for a buy or minus it for a sell, when the commission is in the
// stock's currency (otherwise the value alone). buyingPowerAfter: buying power moved by the order's
// value in the account's currency (an estimate: before commission).
export function estimates(preview, { side, currency, buyingPower }) {
  const buying = side === 'BUY'
  const value = preview?.estimated_value ?? null
  const commission = preview?.what_if?.commission
  const sameCurrency = preview?.what_if?.commission_currency === currency
  const total = value != null && commission != null && sameCurrency ? value + (buying ? commission : -commission) : value
  const base = preview?.estimated_value_base
  const buyingPowerAfter = buyingPower != null && base != null ? buyingPower + (buying ? -base : base) : null
  return { value, total, buyingPowerAfter }
}
