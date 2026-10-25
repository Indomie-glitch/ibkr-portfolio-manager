// Wording and small calculations for the pipeline sheet and its Settings group (#122). Pure, so they
// are tested (pipelineFormat.test.js).

// "US$4.12"; a cost under a cent is "<US$0.01" rather than a misleading US$0.00, and none is "—"
export function usd(value, { dash = false } = {}) {
  if (value == null || (dash && value === 0)) return '—'
  if (value > 0 && value < 0.005) return '<US$0.01'
  return `US$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

// The budget as shown in the field: "10", "12.5"
export function budgetText(value) {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)))
}

// What was typed in the budget field -> a number, or null when it isn't a sensible amount
export function parseBudget(text, max = 1000) {
  const cleaned = String(text).trim().replace(/^(?:US)?\$/i, '').replace(/,/g, '')
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null
  const value = Number(cleaned)
  return value > 0 && value <= max ? value : null
}

// The first day of next month, for "starts again on 1 November"
export function nextMonthStart(now = new Date()) {
  return new Date(now.getFullYear(), now.getMonth() + 1, 1)
}

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

// The Settings row's one line: "Running · 2 workers · US$4.12 of US$10 spent this month. 3 reports failed and are retrying."
export function settingsLine(pipeline, now = new Date()) {
  if (!pipeline) return 'Checking…'
  const { status, workers, cost, attention } = pipeline
  const spent = `${usd(cost.month)} of ${usd(cost.budget)} spent this month`
  const trouble = attention.total
    ? ` ${plural(attention.total, 'report')} ${attention.total === 1 ? 'needs' : 'need'} attention${attention.retrying ? `, ${attention.retrying} retrying` : ''}.`
    : ''
  if (status === 'off') return 'Off. Turn on Run pipeline to start reading company reports.'
  if (status === 'paused') return `Paused. Press Run now in the pipeline to continue. ${spent}.${trouble}`
  if (status === 'budget') {
    const month = nextMonthStart(now).toLocaleDateString('en-AU', { day: 'numeric', month: 'long' })
    return `Paused: this month’s budget is used up (${spent}). It starts again on ${month}.${trouble}`
  }
  if (status === 'starting') return `Starting… ${spent}.${trouble}`
  return `Running · ${plural(workers, 'worker')} · ${spent}.${trouble}`
}

// The status pill in the sheet's toolbar: { tone: ok | warn | off, label }
export function statusPill(pipeline) {
  switch (pipeline?.status) {
    case 'running':
      return { tone: 'ok', label: `Running · ${plural(pipeline.workers, 'worker')}` }
    case 'starting':
      return { tone: 'ok', label: 'Starting…' }
    case 'paused':
      return { tone: 'warn', label: 'Paused' }
    case 'budget':
      return { tone: 'warn', label: 'Paused · budget used' }
    default:
      return { tone: 'off', label: 'Off' }
  }
}

// The four tiles, from GET /pipeline
export function tiles(pipeline) {
  const { coverage, links, attention, cost } = pipeline
  const edgar = coverage.not_on_edgar ? ` · ${coverage.not_on_edgar} not on EDGAR` : ''
  return [
    { id: 'coverage', label: 'COVERAGE', value: `${coverage.read} / ${coverage.total}`, sub: `Watched companies with their latest filing read${edgar}` },
    {
      id: 'links',
      label: 'LINKS',
      value: links.total.toLocaleString('en-US'),
      sub: `+${links.week.toLocaleString('en-US')} this week, ${links.ended.toLocaleString('en-US')} ended`,
    },
    {
      id: 'attention',
      label: 'NEEDS ATTENTION',
      value: String(attention.total),
      tone: attention.total ? 'loss' : undefined,
      sub: attention.total
        ? [attention.retrying && `${attention.retrying} retrying`, attention.stuck && `${attention.stuck} stopped`].filter(Boolean).join(', ')
        : 'Nothing needs attention',
    },
    { id: 'cost', label: 'COST · MONTH', value: usd(cost.month), tone: 'amber', sub: `${cost.percent}% of your ${usd(cost.budget)} budget` },
  ]
}

// The filter keys over the companies, with their counts: [{ id, label, count }]
export function companyKeys(counts) {
  return [
    { id: 'all', label: 'ALL', count: counts.all },
    { id: 'reading', label: 'RUNNING', count: counts.reading },
    { id: 'waiting', label: 'WAITING', count: counts.waiting },
    { id: 'failed', label: 'FAILED', count: counts.failed },
    { id: 'up to date', label: 'UP TO DATE', count: counts.up_to_date },
  ]
}

export function filterCompanies(companies, key) {
  return key === 'all' ? companies : companies.filter((c) => c.status === key)
}

// "now", "20:28" (today), "Tue" (this week), "3 Oct", or "—": when a company's last job finished
export function readTime(iso, now = new Date()) {
  if (!iso) return '—'
  const at = new Date(iso)
  const ago = now - at
  if (ago < 60_000) return 'now'
  if (at.toDateString() === now.toDateString()) return at.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  if (ago < 6 * 86_400_000) return at.toLocaleDateString('en-AU', { weekday: 'short' })
  return at.toLocaleDateString('en-AU', { day: 'numeric', month: 'short' })
}

// 20:31:42 in the viewer's time
export function logTime(iso) {
  return new Date(iso).toLocaleTimeString('en-GB')
}

// "+9" in green, "0" faint
export function weekChange(n) {
  return { text: n > 0 ? `+${n}` : '0', tone: n > 0 ? 'gain' : 'faint' }
}

// The cost row under the log
export function costSummary(cost) {
  return [
    { label: 'THIS WEEK', value: usd(cost.week), tone: 'amber' },
    { label: 'PER FILING', value: cost.per_filing == null ? '—' : usd(cost.per_filing) },
    { label: 'BUDGET LEFT', value: usd(cost.budget_left), tone: cost.budget_left > 0 ? 'gain' : 'loss' },
  ]
}

// Whether the pipeline has never been used and isn't switched on: the sheet shows its explanation instead
export function isEmptyState(pipeline) {
  return !pipeline.enabled && !pipeline.started
}
