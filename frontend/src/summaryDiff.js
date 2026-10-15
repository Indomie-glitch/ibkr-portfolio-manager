// Matches the points of two summaries by wording, so compare mode can tag points that are new,
// no longer present, or the same point with different numbers ("Changed"). The model rewords
// every summary, so exact text matching would call almost everything new; this is a guide only.

const SIMILAR = 0.4 // share of meaningful words (and numbers) two points need in common to be the same point
const SAME_SENTENCE = 0.6 // closer still: only then can a different number mean the figure changed

// Money, percentages and plain numbers, e.g. A$4.79, −3.04%, 53.08B. A sign only counts at the
// start of a word, so "2024-25" gives 2024 and 25, not −25
const NUMBER = /(?<![\w.])[−+-]?(?:[A-Z]{1,3}\$|\$)?\d[\d,]*(?:\.\d+)?(?:%|[KMBT]\b)?/g

const STOP_WORDS = new Set(
  `the and for are was were has have had its this that with from into than then over under about
  after before since while also but not more less most very their they them which who will would
  could may might can our your you all any per one two three`.split(/\s+/),
)

// Dates and fiscal years ("on 12 Oct 2026", "FY2025") name when, not how much, so they are
// compared as words, never reported as changed numbers
const DATE = /\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?: \d{4})?|\b(?:FY ?)?(?:19|20)\d{2}\b/g
const SCALE = { thousand: 'K', million: 'M', billion: 'B', trillion: 'T' }

// "A$22.51 billion" and "A$22.51B" are the same number
function tidy(text) {
  return text.replace(/(\d) (thousand|million|billion|trillion)\b/g, (_, digit, word) => digit + SCALE[word])
}

// Figures that can change between summaries: money, percentages, decimals, 53.08B. Bare whole
// numbers are usually counts or names ("12 months", "S&P/ASX 200"), so they are left out.
function figures(text) {
  return (tidy(text).replace(DATE, ' ').match(NUMBER) ?? []).filter((n) => /[$%.KMBT]/.test(n))
}

// "A$" + "B" for A$22.51B, "%" for 4.53%: only figures with the same unit are compared
const unit = (n) => n.replace(/[−+\-\d,.]/g, '')
const value = (n) => Math.abs(parseFloat(n.replace(/[^\d.]/g, '')))
const decimals = (n) => (n.split('.')[1] ?? '').replace(/\D/g, '').length

// 1.0% and 1.04% are the same figure rounded differently
function sameFigure(a, b) {
  const places = Math.min(decimals(a), decimals(b))
  return value(a).toFixed(places) === value(b).toFixed(places)
}

// Pairs of [old, new] figures with the same unit where the new one replaced the old one. Figures
// the other summary mentions anywhere in the section don't count (points get merged and split).
function changedFigures(oldText, newText, oldSection, newSection) {
  const added = onlyIn(figures(newText), figures(oldText)).filter((n) => !oldSection.has(normalise(n)))
  const pairs = []
  for (const old of onlyIn(figures(oldText), figures(newText))) {
    if (newSection.has(normalise(old))) continue
    const i = added.findIndex((n) => unit(n) === unit(old))
    if (i === -1) continue
    const [replacement] = added.splice(i, 1)
    if (!sameFigure(old, replacement)) pairs.push([old, replacement])
  }
  return pairs
}

const stem = (w) => w.replace(/(?:ing|ed|es|s|ly)$/, '')

function tokens(text) {
  const clean = tidy(text)
  const found = clean
    .replace(NUMBER, ' ')
    .toLowerCase()
    .split(/[^a-z]+/)
    .filter((w) => w.length >= 3 && !STOP_WORDS.has(w))
    .map(stem)
  return new Set([...found, ...(clean.match(NUMBER) ?? []).map((n) => `#${normalise(n)}`)])
}

const normalise = (n) => n.replace('−', '-').replace(/,/g, '')

// Dice coefficient: 1 when both points use the same words, 0 when they share none
function similarity(a, b) {
  if (a.size === 0 || b.size === 0) return 0
  let shared = 0
  for (const w of a) if (b.has(w)) shared += 1
  return (2 * shared) / (a.size + b.size)
}


// Numbers in one list that the other doesn't have (counting repeats)
function onlyIn(list, other) {
  const left = other.map(normalise)
  return list.filter((n) => {
    const i = left.indexOf(normalise(n))
    if (i === -1) return true
    left.splice(i, 1)
    return false
  })
}

// Points that may match each other: bull only with bull, bear only with bear; news themes are
// renamed between summaries, so news points match across themes
function pointGroups(name, section) {
  if (!section) return {}
  if (name === 'bull_bear') return { bull: section.bull ?? [], bear: section.bear ?? [] }
  if (name === 'news_digest') return { all: (section.themes ?? []).flatMap((t) => t.points) }
  return { all: section.points ?? [] }
}

// Returns { older: Map(point -> mark), newer: Map(point -> mark) } for one section
export function diffSection(name, olderSection, newerSection) {
  const older = new Map()
  const newer = new Map()
  const oldGroups = pointGroups(name, olderSection)
  const newGroups = pointGroups(name, newerSection)

  for (const group of new Set([...Object.keys(oldGroups), ...Object.keys(newGroups)])) {
    const oldPoints = (oldGroups[group] ?? []).map((point) => ({ point, tokens: tokens(point.text) }))
    const newPoints = (newGroups[group] ?? []).map((point) => ({ point, tokens: tokens(point.text) }))
    const sectionFigures = (list) => new Set(list.flatMap(({ point }) => figures(point.text).map(normalise)))
    const oldFigures = sectionFigures(oldPoints)
    const newFigures = sectionFigures(newPoints)

    // Best pairs first, each point used at most once
    const pairs = []
    for (const o of oldPoints) {
      for (const n of newPoints) {
        const score = similarity(o.tokens, n.tokens)
        if (score >= SIMILAR) pairs.push({ o, n, score })
      }
    }
    pairs.sort((a, b) => b.score - a.score)
    const matched = new Set()
    for (const { o, n, score } of pairs) {
      if (matched.has(o) || matched.has(n)) continue
      matched.add(o).add(n)
      // A reworded point that only adds or drops a figure is still the same point
      const changes = score >= SAME_SENTENCE ? changedFigures(o.point.text, n.point.text, oldFigures, newFigures) : []
      if (changes.length) {
        newer.set(n.point, {
          kind: 'changed',
          from: changes.map(([old]) => old).join(', '),
          to: changes.map(([, replacement]) => replacement).join(', '),
        })
      }
    }
    for (const o of oldPoints) if (!matched.has(o)) older.set(o.point, { kind: 'removed' })
    for (const n of newPoints) if (!matched.has(n)) newer.set(n.point, { kind: 'new' })
  }
  return { older, newer }
}
