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

// formatCompactNumber(5283000) -> "5.28M", formatCompactNumber(52520000000) -> "52.52B"
export function formatCompactNumber(value) {
  if (value == null) return '—'
  const units = [
    [1e12, 'T'],
    [1e9, 'B'],
    [1e6, 'M'],
    [1e3, 'K'],
  ]
  for (const [size, suffix] of units) {
    if (Math.abs(value) >= size) return `${formatNumber(value / size)}${suffix}`
  }
  return formatNumber(value, 0)
}

// "2026-08-12" -> "12 Aug 2026". Dates without a time are read as UTC so they don't shift a day.
export function formatDate(isoDate) {
  if (!isoDate) return '—'
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString('en-AU', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

// "2026-06-30" -> "30 June"
export function formatDayMonth(isoDate) {
  if (!isoDate) return '—'
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString('en-AU', {
    day: 'numeric',
    month: 'long',
    timeZone: 'UTC',
  })
}

// How long ago something happened: "5m ago", "3h ago", "2d ago", "2mo ago", "1y ago"
export function formatAge(isoDateTime, now = Date.now()) {
  if (!isoDateTime) return ''
  const minutes = Math.max(0, Math.round((now - new Date(isoDateTime).getTime()) / 60000))
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.round(days / 30)
  if (months < 12) return `${months}mo ago`
  return `${Math.round(days / 365)}y ago`
}

// "2:14pm", or "15 Oct, 2:14pm" when it isn't today
// "2:14pm"
function clockTime(moment) {
  return moment
    .toLocaleTimeString('en-AU', { hour: 'numeric', minute: '2-digit', hour12: true })
    .replace(/\s/g, '')
    .toLowerCase()
}

// "15 Oct, 2:14pm" (with the year when it isn't this year), for the summary history
export function formatSummaryTime(isoDateTime, now = new Date()) {
  const moment = new Date(isoDateTime)
  const options = { day: 'numeric', month: 'short' }
  if (moment.getFullYear() !== now.getFullYear()) options.year = 'numeric'
  return `${moment.toLocaleDateString('en-AU', options)}, ${clockTime(moment)}`
}

// "15 Oct 2026, 2:14pm"
export function formatSummaryDate(isoDateTime) {
  const moment = new Date(isoDateTime)
  return `${moment.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })}, ${clockTime(moment)}`
}

export function formatGeneratedTime(isoDateTime, now = new Date()) {
  if (!isoDateTime) return ''
  const moment = new Date(isoDateTime)
  const time = clockTime(moment)
  if (moment.toDateString() === now.toDateString()) return time
  return `${moment.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })}, ${time}`
}
