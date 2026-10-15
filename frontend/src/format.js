// Symbols used in the design: A$ for AUD, US$ for USD. Other currencies use their code.
const CURRENCY_PREFIX = { AUD: 'A$', USD: 'US$' }
const MINUS = '−' // a proper minus sign; lines up better than a hyphen

function prefixFor(currency) {
  return CURRENCY_PREFIX[currency] ?? `${currency} `
}

export function formatNumber(value, decimals = 2) {
  if (value == null) return '—'
  return new Intl.NumberFormat('en-AU', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value)
}

// formatMoney(1234.5, 'AUD') -> "A$1,234.50"
// formatMoney(-12.6, 'AUD', { signed: true }) -> "−A$12.60"
// formatMoney(52285.4, 'AUD', { decimals: 0 }) -> "A$52,285"
export function formatMoney(value, currency, { signed = false, decimals = 2 } = {}) {
  if (value == null) return '—'
  const sign = value < 0 ? MINUS : signed && value > 0 ? '+' : ''
  return `${sign}${prefixFor(currency)}${formatNumber(Math.abs(value), decimals)}`
}

// formatCompactMoney(75552, 'AUD') -> "A$75.6k"
export function formatCompactMoney(value, currency) {
  if (value == null) return '—'
  const compact = new Intl.NumberFormat('en-AU', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value)
  return `${prefixFor(currency)}${compact.toLowerCase()}`
}

// formatPercent(2.164) -> "+2.16%"
export function formatPercent(value, { signed = true, decimals = 2 } = {}) {
  if (value == null) return '—'
  const sign = value < 0 ? MINUS : signed && value > 0 ? '+' : ''
  return `${sign}${formatNumber(Math.abs(value), decimals)}%`
}

export function formatTime(date) {
  return date.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false })
}

// IB cuts company names off at 28 characters; mark those with an ellipsis
export function companyName(holding) {
  return holding.name_truncated ? `${holding.name}…` : holding.name
}

// CSS class for a gain or loss number
export function trendClass(value) {
  if (value == null || value === 0) return ''
  return value > 0 ? 'gain' : 'loss'
}
