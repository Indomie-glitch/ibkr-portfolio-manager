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

// "this year", "over the last 3 months", "over the last 3 years"
export function periodPhrase(period) {
  return { '3M': 'over the last 3 months', '1Y': 'this year', '3Y': 'over the last 3 years' }[period] ?? 'over this period'
}

// The one-line explanation under the total currency effect
export function currencySentence(section, period) {
  const fx = section.fx_return
  const gains = section.holdings.reduce((sum, h) => sum + h.value_aud * (h.price_return ?? 0), 0) >= 0
  const when = periodPhrase(period)
  if (fx == null || Math.abs(fx) < 0.0005) return `The exchange rate barely moved ${when}, so it made little difference.`
  if (fx < 0) {
    return gains
      ? `A stronger Australian dollar shrank your US gains ${when}.`
      : `A stronger Australian dollar added to your US losses ${when}.`
  }
  return gains
    ? `A weaker Australian dollar added to your US gains ${when}.`
    : `A weaker Australian dollar softened your US losses ${when}.`
}

// +0.48, −0.10, 1.00 for the diagonal
export function corr(value, { signed = true } = {}) {
  if (value == null) return '—'
  const text = Math.abs(value).toFixed(2)
  if (Number(text) === 0) return '0.00'
  return `${value < 0 ? MINUS : signed ? '+' : ''}${text}`
}

// A heatmap cell's colour: amber for moving together, blue for opposite, stronger further from 0
export function corrColour(value) {
  // Opacity 10% at 0 up to 95% at ±1 (Figma RSK 03); color-mix works in older macOS web views too
  const share = Math.round((0.1 + 0.85 * Math.min(1, Math.abs(value))) * 100)
  return `color-mix(in srgb, var(${value < 0 ? '--accent' : '--risk-key-on'}) ${share}%, transparent)`
}

// How related a pair is, in words
export function describePair(value) {
  if (value <= -0.3) return 'Usually move in opposite directions'
  if (value <= -0.1) return 'Tend to move in opposite directions'
  if (value < 0.1) return 'Move almost independently'
  if (value < 0.3) return 'Sometimes rise and fall together'
  if (value < 0.6) return 'Often rise and fall on the same days'
  return 'Usually rise and fall on the same days'
}

export function describeAverage(value) {
  if (value < 0.3) return 'Your holdings mostly move independently'
  if (value < 0.6) return 'Your holdings often move together'
  return 'Your holdings mostly move together'
}

// The heatmap's hover text for a pair: "Moved the same way on 66% of days in the last year. When CBA
// fell 2%, BHP tended to fall about 1%."
export function pairTooltip(pair, period) {
  const when = { '3M': 'in the last 3 months', '1Y': 'in the last year', '3Y': 'in the last 3 years' }[period] ?? ''
  const parts = []
  if (pair.same_direction != null) parts.push(`Moved the same way on ${pct(pair.same_direction, { decimals: 0 })} of days ${when}.`.replace(' .', '.'))
  if (pair.b_per_a != null) {
    const move = pair.b_per_a * 2
    if (Math.abs(move) < 0.1) parts.push(`When ${pair.a} fell 2%, ${pair.b} barely moved.`)
    else parts.push(`When ${pair.a} fell 2%, ${pair.b} tended to ${move > 0 ? 'fall' : 'rise'} about ${Math.abs(move).toFixed(Math.abs(move) < 1 ? 1 : 0)}%.`)
  }
  return parts.join(' ')
}

const COUNT_WORDS = ['No', 'One', 'Two', 'Three', 'Four', 'Five']

// "Two factors explain 68% of how your holdings move." (one factor when there are only two holdings,
// since two factors would always explain all of it)
export function factorsHeadline({ factors, count }) {
  const used = count <= 2 ? 1 : 2
  const share = factors.slice(0, used).reduce((sum, f) => sum + (f.share ?? 0), 0)
  return `${COUNT_WORDS[used]} ${used === 1 ? 'factor explains' : 'factors explain'} ${pct(share, { decimals: 0 })} of how your holdings move.`
}

// RSK 08's "In plain words": the 1-day 95% figure, and how the history based one compares
export function varPlainWords({ levels }, period) {
  const formula = levels['95'].formula.day
  const history = levels['95'].history.day
  const loss = formatCompactLoss(formula.aud)
  let text = `On about 1 trading day in 20, expect to lose more than ${loss}.`
  if (history) {
    const past = { '3M': 'the past 3 months', '1Y': 'the past year', '3Y': 'the past 3 years' }[period] ?? 'this period'
    if (history.aud < formula.aud * 1.05) {
      text += ' The history based figure is higher because real markets have more extreme days than the formula assumes.'
    } else if (history.aud > formula.aud * 0.95) {
      text += ` The history based figure is lower: ${past} had fewer extreme days than the formula assumes.`
    } else {
      text += ' The three methods roughly agree.'
    }
  }
  return text
}

// −1485.3 -> "A$1,485" (the size of a loss)
function formatCompactLoss(aud) {
  return `A$${Math.round(Math.abs(aud)).toLocaleString('en-AU')}`
}

// A stress test's severity marker: high at a 20% loss or more, medium from 10%, low below
export function severity(impactPct) {
  if (impactPct == null || impactPct >= 0) return null
  if (impactPct <= -0.2) return 'high'
  if (impactPct <= -0.1) return 'medium'
  return 'low'
}

// Percentage points: 0.139 -> "+13.9 pts"
export function points(fraction, { signed = true } = {}) {
  if (fraction == null) return '—'
  return pct(fraction, { signed }).replace('%', ' pts')
}

// "AAPL 68%, CBA 21%, BHP 8%…": the largest weights of a mix
export function weightsCaption(weights, shown = 3) {
  const sorted = [...weights].sort((a, b) => b.weight - a.weight).filter((w) => w.weight >= 0.005)
  const text = sorted.slice(0, shown).map((w) => `${w.symbol} ${pct(w.weight, { decimals: 0 })}`).join(', ')
  return sorted.length > shown ? `${text}…` : text
}

// Name and caption for each example mix in RSK 10
export function mixLabel(mix, count) {
  switch (mix.id) {
    case 'current':
      return { name: 'Your current mix', caption: weightsCaption(mix.weights) }
    case 'capped':
      return { name: `${mix.name} capped at 40%`, caption: `Rest spread in proportion: ${weightsCaption(mix.weights, 2)}` }
    case 'equal':
      return { name: 'Equal weights', caption: `${pct(1 / count, { decimals: 0 })} each` }
    default:
      return { name: 'Lowest risk mix', caption: weightsCaption(mix.weights) }
  }
}

// RSK 11's zone text: "Safe", "Grey", "Distress*" for a utility, "Not used for banks"
export function zoneLabel(row) {
  switch (row.zone) {
    case 'safe':
      return 'Safe'
    case 'grey':
      return `Grey${row.low_by_design ? '*' : ''}`
    case 'distress':
      return `Distress${row.low_by_design ? '*' : ''}`
    case 'bank':
      return 'Not used for banks'
    default:
      return 'Unavailable'
  }
}

// Time to sell: "< 1 min", "25 min", "2 h 10 min", "1.5 days"
export function sellTime(row) {
  if (row?.days == null) return '—'
  if (row.days >= 1) return `${row.days < 10 ? row.days.toFixed(1) : Math.round(row.days)} ${row.days < 1.05 ? 'day' : 'days'}`
  const minutes = row.minutes
  if (minutes < 1) return '< 1 min'
  if (minutes < 60) return `${Math.round(minutes)} min`
  const hours = Math.floor(minutes / 60)
  const rest = Math.round(minutes - hours * 60)
  return rest ? `${hours} h ${rest} min` : `${hours} h`
}

// Green under a day, amber up to 5 trading days, red beyond
export function sellTone(row) {
  if (row?.days == null) return ''
  if (row.days < 1) return 'gain'
  return row.days <= 5 ? 'amber' : 'loss'
}

// 25_600_000 -> "25.6M", 980_000 -> "980K"
export function compactVolume(value) {
  if (value == null) return '—'
  for (const [size, suffix] of [[1e9, 'B'], [1e6, 'M'], [1e3, 'K']]) {
    if (value >= size) return `${(value / size).toFixed(value / size < 100 ? 1 : 0).replace(/\.0$/, '')}${suffix}`
  }
  return String(Math.round(value))
}
