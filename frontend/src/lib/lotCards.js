import { formatShortDate } from './format.js'

const daysLeft = (days) => `${days} ${days === 1 ? 'day' : 'days'} left`
const shares = (quantity) => `${quantity % 1 ? quantity : Math.round(quantity)} ${quantity === 1 ? 'share' : 'shares'}`

// What the Purchase date and 12-month CGT date cards in Your position show (#17), from
// GET /lots/{con_id}. Each card: { value, note, noteTone: 'warning' | 'muted', noteHref? }.
// flexConfigured: from GET /lots/status (false adds a hint on how to get purchase dates).
// inApp: the Mac app can't take a Flex token yet (its Settings rows are #89), so the hint says so
// instead of pointing to the setup guide, which is for the browser version (#199).
export const FLEX_GUIDE_URL = 'https://github.com/Indomie-glitch/ibkr-portfolio-manager/blob/main/docs/flex-query.md'

function flexHint(inApp) {
  return inApp
    ? { note: 'Not available in the app yet', noteTone: 'muted' }
    : { note: 'Set up an IBKR Flex Query', noteTone: 'muted', noteHref: FLEX_GUIDE_URL }
}

export function lotCards(lots, flexConfigured, { inApp = false } = {}) {
  // Lots bought on the same day share a purchase date and so a CGT date: the dates and CGT
  // countdown are per day, while the purchase count is IBKR's lots (#192)
  const purchases = lots?.lots?.length ?? 0
  const byDay = new Map()
  for (const lot of lots?.lots ?? []) {
    const day = byDay.get(lot.opened)
    if (day) day.quantity += lot.quantity
    else byDay.set(lot.opened, { ...lot })
  }
  const known = [...byDay.values()]
  if (!known.length) {
    return {
      purchase: { value: 'Unknown', ...(flexConfigured === false ? flexHint(inApp) : { note: null, noteTone: 'muted' }) },
      cgt: { value: 'Unknown', note: null },
    }
  }

  // Shares the report doesn't date (bought before its period, or since it was made)
  const unknownNote = lots.unknown_quantity > 0 ? `${shares(lots.unknown_quantity)}: date unknown` : null

  if (known.length === 1) {
    // One day: that date, not a same-day range, with how many purchases it was (#192)
    const [lot] = known
    const count = purchases > 1 ? `${purchases} purchases` : null
    return {
      purchase: { value: formatShortDate(lot.opened), note: [count, unknownNote].filter(Boolean).join(' · ') || null, noteTone: 'muted' },
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
    purchase: { value: `${purchases} purchases`, note: unknownNote ? `${range} · ${unknownNote}` : range, noteTone: 'muted' },
    cgt,
  }
}
