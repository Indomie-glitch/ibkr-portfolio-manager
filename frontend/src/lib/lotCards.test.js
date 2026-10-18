// The Purchase date and 12-month CGT date cards (#17): every case in the issue.
// Run with: npm test
import assert from 'node:assert/strict'
import { test } from 'vitest'
import { FLEX_GUIDE_URL, lotCards } from './lotCards.js'

const lot = (opened, cgt, days, quantity = 100) => ({ quantity, opened, cgt_discount_from: cgt, days_until_discount: days })
const cases = [
  ['one purchase, waiting', lotCards({ lots: [lot('2026-09-09', '2027-09-10', 328)], unknown_quantity: 0 }, true),
    { purchase: ['9 Sep 2026', null], cgt: ['10 Sep 2027', '328 days left', 'warning'] }],
  ['one purchase, eligible', lotCards({ lots: [lot('2024-03-01', '2025-03-02', 0)], unknown_quantity: 0 }, true),
    { purchase: ['1 Mar 2024', null], cgt: ['2 Mar 2025', null] }],
  ['one day split into two lots', lotCards({ lots: [lot('2026-09-17', '2027-09-18', 336, 61), lot('2026-09-17', '2027-09-18', 336, 39)], unknown_quantity: 0 }, true),
    { purchase: ['17 Sep 2026', '2 purchases'], cgt: ['18 Sep 2027', '336 days left', 'warning'] }],
  // #192: one day, several purchases, some shares undated: still one date, never a same-day range
  ['one day, two purchases, some undated', lotCards({ lots: [lot('2026-09-17', '2027-09-18', 336, 61), lot('2026-09-17', '2027-09-18', 336, 39)], unknown_quantity: 20 }, true),
    { purchase: ['17 Sep 2026', '2 purchases · 20 shares: date unknown'], cgt: ['18 Sep 2027', '336 days left', 'warning'] }],
  ['two days, one with two purchases', lotCards({ lots: [lot('2026-02-04', '2027-02-05', 111, 10), lot('2026-02-04', '2027-02-05', 111, 5), lot('2026-09-09', '2027-09-10', 328, 15)], unknown_quantity: 0 }, true),
    { purchase: ['3 purchases', '4 Feb 2026 to 9 Sep 2026'], cgt: ['5 Feb 2027', 'Next: 15 shares, 111 days left', 'warning'] }],
  ['three purchases, one waiting soonest', lotCards({ lots: [lot('2025-03-12', '2026-03-13', 0, 50), lot('2026-02-04', '2027-02-05', 111, 35), lot('2026-09-09', '2027-09-10', 328, 15)], unknown_quantity: 0 }, true),
    { purchase: ['3 purchases', '12 Mar 2025 to 9 Sep 2026'], cgt: ['5 Feb 2027', 'Next: 35 shares, 111 days left', 'warning'] }],
  ['several, all eligible', lotCards({ lots: [lot('2023-01-02', '2024-01-03', 0), lot('2024-05-06', '2025-05-07', 0)], unknown_quantity: 0 }, true),
    { purchase: ['2 purchases', '2 Jan 2023 to 6 May 2024'], cgt: ['7 May 2025', null] }],
  ['no Flex report', lotCards({ lots: [], unknown_quantity: 100 }, false),
    { purchase: ['Unknown', 'Set up an IBKR Flex Query'], cgt: ['Unknown', null] }],
  // #199: the Mac app has no Flex settings yet, so it doesn't send people looking for them
  ['no Flex report, Mac app', lotCards({ lots: [], unknown_quantity: 100 }, false, { inApp: true }),
    { purchase: ['Unknown', 'Not available in the app yet'], cgt: ['Unknown', null] }],
  ['Flex set up, shares not covered', lotCards({ lots: [], unknown_quantity: 100 }, true),
    { purchase: ['Unknown', null], cgt: ['Unknown', null] }],
  ['request failed', lotCards(null, undefined), { purchase: ['Unknown', null], cgt: ['Unknown', null] }],
  ['1 day left', lotCards({ lots: [lot('2025-10-17', '2026-10-18', 1)], unknown_quantity: 0 }, true),
    { purchase: ['17 Oct 2025', null], cgt: ['18 Oct 2026', '1 day left', 'warning'] }],
]
for (const [name, got, want] of cases) {
  test(name, () => {
  assert.deepEqual([got.purchase.value, got.purchase.note ?? null], want.purchase, name)
  assert.deepEqual([got.cgt.value, got.cgt.note ?? null, ...(want.cgt[2] ? [got.cgt.noteTone] : [])], want.cgt, name)
  })
}

test('the browser hint links to the Flex setup guide; the app one has no link', () => {
  assert.equal(lotCards(null, false).purchase.noteHref, FLEX_GUIDE_URL)
  assert.equal(lotCards(null, false, { inApp: true }).purchase.noteHref, undefined)
  assert.equal(lotCards(null, true).purchase.noteHref, undefined)
})
