// Text for the Risk page's command bar, data notes and toolbar subtitle (Figma Risk / V5A).
import { formatDate } from './format.js'

export const PERIODS = ['3M', '1Y', '3Y']
export const DEFAULT_PERIOD = '1Y'
const PERIOD_WORDS = { '3M': '3 months', '1Y': 'year', '3Y': '3 years' }

// "2026-10-18T23:04:00+11:00" -> "18 Oct 2026 23:04" (local time)
export function calculatedText(iso) {
  if (!iso) return '—'
  const at = new Date(iso)
  const day = at.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })
  const time = at.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false })
  return `${day} ${time}`
}

// Right side of the command bar
export function asOfText(meta) {
  return `As of ${calculatedText(meta.calculated_at)} · AUD · ${meta.days_used} trading days · Cash excluded`
}

// Left side of the data notes row
export function calculatedNote(meta) {
  return `Calculated ${calculatedText(meta.calculated_at)} · Daily returns in AUD · ${meta.days_used} trading days · Cash excluded`
}

// Right side of the data notes row: which holdings were left out and why
export function leftOutNote(meta) {
  const left = meta.left_out ?? []
  if (left.length === 0) {
    const all = meta.holdings_count === 1 ? 'The holding has' : `All ${meta.holdings_count} holdings have`
    return `Left out: none · ${all} a full ${PERIOD_WORDS[meta.period] ?? 'period'} of prices`
  }
  return `Left out: ${left.map((h) => `${h.symbol} (${h.reason})`).join(' · ')}`
}

// Anything else the numbers depend on: a price index used instead of a total return index, or
// prices that couldn't be updated today
export function extraNotes(meta) {
  const notes = []
  if (meta.benchmark_note) notes.push(meta.benchmark_note)
  if (meta.stale?.length) notes.push(`Couldn’t update today: ${meta.stale.join(', ')} (earlier prices used)`)
  return notes
}

// Toolbar subtitle: "5 holdings · Daily closes to 16 Oct 2026"
export function riskSubtitle(meta, holdingsCount, failed = false) {
  const holdings = `${holdingsCount} ${holdingsCount === 1 ? 'holding' : 'holdings'}`
  if (!meta) return `${holdings} · ${failed ? 'Daily closes unavailable' : 'Loading daily closes…'}`
  const n = meta.holdings_count
  return `${n} ${n === 1 ? 'holding' : 'holdings'} · Daily closes to ${formatDate(meta.last_day)}`
}

const MINUS = '−'

// 0.198 -> "19.8%"; signed: −0.163 -> "−16.3%", 0.05 -> "+5.0%"
export function pct(fraction, { decimals = 1, signed = false } = {}) {
  if (fraction == null) return '—'
  const value = fraction * 100
  const digits = Math.abs(value).toFixed(decimals)
  const zero = Number(digits) === 0 // a tiny negative number shows as 0.0%, not −0.0%
  const sign = value < 0 && !zero ? MINUS : signed && value > 0 && !zero ? '+' : ''
  return `${sign}${digits}%`
}

// 0.4712 -> "0.47"
export function ratio(value, decimals = 2) {
  if (value == null) return '—'
  return `${value < 0 ? MINUS : ''}${Math.abs(value).toFixed(decimals)}`
}

// "2026-04-02" -> "2 Apr"; with year -> "2 Apr 2026"
export function shortDate(isoDate, withYear = false) {
  if (!isoDate) return '—'
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString('en-AU', {
    day: 'numeric',
    month: 'short',
    ...(withYear ? { year: 'numeric' } : {}),
    timeZone: 'UTC',
  })
}

// "Peak 2 Apr, low 21 Apr 2026"
export function drawdownDates(drawdown) {
  if (!drawdown?.peak) return 'No fall in this period'
  return `Peak ${shortDate(drawdown.peak)}, low ${shortDate(drawdown.trough, true)}`
}

// A beta as a 10% market move: 0.47 -> "4.7%"
export function tenPercentMove(beta) {
  return `${Math.abs(beta * 10).toFixed(1)}%`
}

// ["AAPL"] -> "AAPL", ["AAPL", "BHP"] -> "AAPL and BHP", three -> "AAPL, BHP and CBA"
export function listNames(names) {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

// "AAPL is 68.2% of your holdings, over the 20% level"
export function concentrationWarning(warning) {
  return `${warning.name} is ${pct(warning.share)} of your holdings, over the ${pct(warning.threshold, { decimals: 0 })} level`
}
