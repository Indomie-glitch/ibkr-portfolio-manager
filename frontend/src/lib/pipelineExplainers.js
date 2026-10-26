import { usd } from './pipelineFormat.js'

// The ⓘ explainers on the pipeline sheet: what each tile or panel is, what yours says (from your own
// numbers) and things to consider. They describe; InfoButton shows them (footer: how, not advice).
const FOOTER = 'How the pipeline works, from your own data. Not financial advice.'

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

export const PIPELINE_EXPLAINERS = {
  coverage: {
    title: 'Coverage',
    what: 'How many of the companies on your watch list have their most recent SEC filing downloaded. The pipeline checks each company every twelve hours for new annual reports (10-K, 20-F), quarterly reports (10-Q) and news filings (8-K, 6-K).',
    yours: (p) =>
      `${p.coverage.read} of ${p.coverage.total} watched companies are up to date.` +
      (p.coverage.not_on_edgar ? ` ${plural(p.coverage.not_on_edgar, 'company')} ${p.coverage.not_on_edgar === 1 ? 'is' : 'are'} not on EDGAR (no US listing), so there is nothing to read yet.` : '') +
      (p.coverage.waiting_for_asx ? ` ${plural(p.coverage.waiting_for_asx, 'company')} ${p.coverage.waiting_for_asx === 1 ? 'is' : 'are'} listed only on the ASX and waiting for an ASX source.` : ''),
    consider: 'The SEC only holds filings of companies listed in the US. Companies listed elsewhere need their own sources, which come later. The companies you hold are read first, then the rest of the watch list.',
  },
  links: {
    title: 'Links',
    what: 'Supplier and customer links found so far. Each one points to the sentence or tagged figure in a filing it came from, so you can always see why it is there.',
    yours: (p) => `${p.links.total.toLocaleString('en-US')} links, ${p.links.week.toLocaleString('en-US')} of them found in the last 7 days, ${p.links.ended.toLocaleString('en-US')} marked as ended.`,
    consider: 'Many filings name a big customer only as “Customer A”. Those links are kept without a name rather than guessed.',
  },
  attention: {
    title: 'Needs attention',
    what: 'Filings the pipeline could not fetch or read, and links Claude could not check. Most are temporary (SEC was busy) and are retried by themselves after a wait; a few stop for good, for example a filing that no longer exists, or a link Claude declined to check twice.',
    yours: (p) =>
      p.attention.total
        ? `${plural(p.attention.retrying, 'item')} waiting to retry, ${plural(p.attention.stuck, 'item')} stopped${p.attention.unchecked ? `, ${plural(p.attention.unchecked, 'link')} unchecked` : ''}${p.attention.oversized ? `, ${plural(p.attention.oversized, 'job')} too big for your budget` : ''}. You can retry stopped ones from a company or from the log.`
        : 'Nothing is stuck right now.',
    consider: 'Retrying a stopped item gives it a fresh set of attempts. A job too big for the whole monthly budget needs a bigger budget in Settings.',
  },
  cost: {
    title: 'Cost this month',
    what: 'What the pipeline has spent on your Anthropic key this calendar month, added up from each Claude call it made (reading a report, then checking each link). Fetching filings from the SEC is free; Claude is what costs. To spread the budget over the month, it spends at most an even share of what is left each day, and the day and the month both start at midnight in your time.',
    yours: (p) =>
      `${usd(p.cost.month)} of your ${usd(p.cost.budget)} monthly budget (${p.cost.percent}%), ${usd(p.cost.budget_left)} left: ${usd(p.cost.by_stage.read)} reading and ${usd(p.cost.by_stage.verify)} checking. Today it has spent ${usd(p.cost.today)} of ${usd(p.cost.today_cap)}.` +
      (p.cost.run_now_extra ? ` Run now added ${usd(p.cost.run_now_extra)} to today.` : '') +
      (p.cost.waiting_for_tomorrow ? ` ${plural(p.cost.waiting_for_tomorrow, 'job')} put off until tomorrow's allowance.` : ''),
    consider: 'Work that does not fit today waits for tomorrow, and cheaper work goes ahead meanwhile. Run now adds one more day\'s allowance to today, never more than the month has left. When the monthly budget is used up the pipeline pauses itself and starts again next month. You can change the budget in Settings.',
  },
  companies: {
    title: 'Companies',
    what: 'The companies being watched, newest activity first: the AI hardware list and the companies you hold (marked held, and always read first). Status shows what the pipeline is doing for each: reading now, waiting in the queue, failed, or up to date. Read is when it last finished something for that company.',
    consider: 'Click a company to see its filings and open it on the Connections map. A company listed only on the ASX says waiting for ASX source: there is no source for those filings yet.',
  },
  log: {
    title: 'Live log',
    what: 'A feed of what the pipeline is doing, newest first. RUN starts a job, DONE finishes one, LINK is a new supplier or customer link, SCOUT is a check for new filings and FAIL is something that went wrong.',
    consider: 'Times are in your local time. The log updates every few seconds while this sheet is open.',
  },
}

// The text InfoButton shows for one of them, with the “yours” line filled in from the pipeline answer
export function pipelineExplainer(id, pipeline) {
  const entry = PIPELINE_EXPLAINERS[id]
  return { title: entry.title, what: entry.what, consider: entry.consider, yours: pipeline && entry.yours ? entry.yours(pipeline) : null, footer: FOOTER }
}
