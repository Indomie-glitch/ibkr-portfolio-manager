import { formatShortDate } from './format.js'

const daysLeft = (days) => `${days} ${days === 1 ? 'day' : 'days'} left`
const shares = (quantity) => `${quantity % 1 ? quantity : Math.round(quantity)} ${quantity === 1 ? 'share' : 'shares'}`

// What the Purchase date and 12-month CGT date cards in Your position show (#17), from
// GET /lots/{con_id}. Each card: { value, note, noteTone: 'warning' | 'muted' }.
// flexConfigured: from GET /lots/status (false adds the "Set up Flex" hint).
export function lotCards(lots, flexConfigured) {
  // IBKR can split one day's buying into several lots (one per execution); they count as one
  // purchase, since they share a purchase date and so a CGT date
  const byDay = new Map()
  for (const lot of lots?.lots ?? []) {
    const day = byDay.get(lot.opened)
    if (day) day.quantity += lot.quantity
    else byDay.set(lot.opened, { ...lot })
  }
  const known = [...byDay.values()]
  if (!known.length) {
    return {
      purchase: { value: 'Unknown', note: flexConfigured === false ? 'Set up Flex in Settings' : null, noteTone: 'muted' },
      cgt: { value: 'Unknown', note: null },
    }
  }

  // Shares the report doesn't date (bought before its period, or since it was made)
  const unknownNote = lots.unknown_quantity > 0 ? `${shares(lots.unknown_quantity)}: date unknown` : null

  if (known.length === 1) {
    const [lot] = known
    return {
      purchase: { value: formatShortDate(lot.opened), note: unknownNote, noteTone: 'muted' },
      cgt: {
        value: formatShortDate(lot.cgt_discount_from),
        note: lot.days_until_discount > 0 ? daysLeft(lot.days_until_discount) : null,
        noteTone: 'warning',
      },
    }
  }

  const byDate = [...known].sort((a, b) => a.opened.localeCompare(b.opened))
  const range = `${formatShortDate(byDate[0].opened)} to ${formatShortDate(byDate.at(-1).opened)}`
  const waiting = known.filter((lot) => lot.days_until_discount > 0).sort((a, b) => a.days_until_discount - b.days_until_discount)
  let cgt
  if (waiting.length) {
    // The next purchase to become eligible
    const next = waiting[0]
    cgt = { value: formatShortDate(next.cgt_discount_from), note: `Next: ${shares(next.quantity)}, ${daysLeft(next.days_until_discount)}`, noteTone: 'warning' }
  } else {
    // Every lot already qualifies: the latest date
    const latest = known.reduce((a, b) => (a.cgt_discount_from > b.cgt_discount_from ? a : b))
    cgt = { value: formatShortDate(latest.cgt_discount_from), note: null }
  }
  return {
    purchase: { value: `${known.length} purchases`, note: unknownNote ? `${range} · ${unknownNote}` : range, noteTone: 'muted' },
    cgt,
  }
}
