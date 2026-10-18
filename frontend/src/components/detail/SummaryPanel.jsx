// An AI summary's panel: Summarise / Regenerate, History (past summaries and compare), and the
// summary itself as it streams in. Shared by a stock's summary (AiSummarySection) and the portfolio
// summary on Overview (PortfolioSummaryCard, #22), so both look and behave the same.
import { useState } from 'react'
import { formatGeneratedTime, formatSummaryDate } from '../../lib/format.js'
import { useFetch } from '../../hooks/useFetch.js'
import { SparklesIcon } from '../icons.jsx'
import DisclosureSection, { SectionLoading } from './DisclosureSection.jsx'
import SummaryCompare from './SummaryCompare.jsx'
import SummaryHistoryMenu from './SummaryHistoryMenu.jsx'
import { AiSummaryBody } from './SummaryView.jsx'
import { STOCK_SUMMARY, SummaryKind } from './summaryKinds.js'

function BackBanner({ children, onBack }) {
  return (
    <p className="ai-banner info">
      {children}{' '}
      <button type="button" className="link-button" onClick={onBack}>
        Back to latest
      </button>
    </p>
  )
}

// A saved summary from the history, read only, drawn exactly like the latest one
function PastSummary({ source, summaryId, name, onBack }) {
  const past = useFetch(() => source.past(summaryId), `${source.key}:${summaryId}`)
  if (past.loading) return <SectionLoading />
  if (past.error) return <BackBanner onBack={onBack}>Couldn’t load that summary · {past.error}.</BackBanner>
  return (
    <>
      <BackBanner onBack={onBack}>Viewing summary from {formatSummaryDate(past.data.created_at)}.</BackBanner>
      <AiSummaryBody view={past.data} generating={false} configured name={name} />
    </>
  )
}

function ComparedSummaries({ source, ids, onBack }) {
  const [a, b] = ids
  const comparison = useFetch(() => source.compare(a, b), `${source.key}:${a}:${b}`)
  if (comparison.loading) return <SectionLoading lines={5} />
  if (comparison.error) return <BackBanner onBack={onBack}>Couldn’t compare those summaries · {comparison.error}.</BackBanner>
  const { older, newer } = comparison.data
  return (
    <>
      <BackBanner onBack={onBack}>
        Comparing summaries from {formatSummaryDate(older.created_at)} and {formatSummaryDate(newer.created_at)}.
      </BackBanner>
      <SummaryCompare comparison={comparison.data} />
    </>
  )
}

// source: what the panel summarises. { key (a stock's conId, or 'portfolio'), latest(), history(),
// past(id), compare(a, b), generate(onEvent), historyItem?(item) }
// kind: STOCK_SUMMARY or portfolioSummary(…) from summaryKinds.js
export function SummaryPanel({ source, kind = STOCK_SUMMARY, sectionId, title, firstLabel, name, owned = true }) {
  const key = source.key
  const saved = useFetch(() => source.latest(), key)
  // The generation in progress (or just finished/failed). Tagged with what it summarises, so
  // switching stocks mid-generation never shows one stock's summary under another; the backend
  // still finishes and saves it.
  const [run, setRun] = useState(null)
  // What the panel shows instead of the latest summary: { key, pastId } or { key, compare: [a, b] }
  const [mode, setMode] = useState(null)

  const runForThis = run?.key === key ? run : null
  const generating = runForThis?.status === 'running'
  const configured = saved.data?.ai_configured ?? false
  const missingKeyMessage = saved.data?.missing_key_message
  const latest = saved.data?.latest
  // While writing, show the new sections; otherwise the newest finished summary
  const view = runForThis?.view ?? latest
  const modeForThis = mode?.key === key ? mode : null
  const backToLatest = () => setMode(null)

  // Reloads whenever a newer summary is saved
  const newestId = runForThis?.status === 'done' ? runForThis.view.id : latest?.id
  const history = useFetch(() => source.history(), `${key}:${newestId ?? ''}`)
  // The History menu labels each summary with a figure: the stock's price or the portfolio's value
  const historyItems = Array.isArray(history.data) ? history.data.map(source.historyItem ?? ((item) => item)) : []

  async function start() {
    setMode(null)
    const update = (change) => setRun((r) => (r && r.key === key ? change(r) : r))
    setRun({ key, status: 'running', view: { summary: {}, links: {}, warnings: [] }, error: null })
    try {
      await source.generate((event, data) => {
        if (event === 'facts') {
          update((r) => ({ ...r, view: { ...r.view, as_of_text: data.as_of_text, links: data.links, missing: data.missing, facts: data.facts } }))
        } else if (event === 'section') {
          update((r) => ({
            ...r,
            view: { ...r.view, summary: { ...r.view.summary, [data.name]: data.section }, warnings: [...r.view.warnings, ...data.warnings] },
          }))
        } else if (event === 'done') {
          update((r) => ({ ...r, status: 'done', view: data }))
        } else if (event === 'error') {
          update((r) => ({ ...r, status: 'error', error: data.message }))
        }
      })
      // The stream ended without "done" or "error" (connection dropped)
      update((r) => (r.status === 'running' ? { ...r, status: 'error', error: 'The connection closed before the summary finished.' } : r))
    } catch (err) {
      update((r) => ({ ...r, status: 'error', error: err.message }))
    }
  }

  const generatedAt = view?.created_at ? `Generated ${formatGeneratedTime(view.created_at)}` : null
  const note = generating ? 'Writing…' : modeForThis ? null : generatedAt
  const actions = (
    <>
      {note && <span className="disclosure-note">{note}</span>}
      {historyItems.length > 0 && (
        <SummaryHistoryMenu
          items={historyItems}
          shownId={modeForThis?.pastId ?? (modeForThis ? null : historyItems[0].id)}
          disabled={generating}
          onView={(pastId) => setMode(pastId ? { key, pastId } : null)}
          onCompare={(ids) => setMode({ key, compare: ids })}
        />
      )}
      <button
        type="button"
        className="button-primary compact"
        onClick={start}
        disabled={!configured || generating || saved.loading}
        title={configured ? undefined : missingKeyMessage}
      >
        <SparklesIcon size={13} /> {view || latest ? 'Regenerate' : firstLabel}
      </button>
    </>
  )

  return (
    <SummaryKind.Provider value={kind}>
      <DisclosureSection id={sectionId} title={title} accent actions={actions}>
        <div className="ai-summary-card">
          {runForThis?.status === 'error' && (
            <p className="ai-banner error" role="alert">
              {runForThis.error}
              {Object.keys(runForThis.view?.summary ?? {}).length > 0 && ' The sections below are incomplete and weren’t saved.'}
            </p>
          )}
          {modeForThis?.pastId ? (
            <PastSummary source={source} summaryId={modeForThis.pastId} name={name} onBack={backToLatest} />
          ) : modeForThis?.compare ? (
            <ComparedSummaries source={source} ids={modeForThis.compare} onBack={backToLatest} />
          ) : saved.error && !view ? (
            <p className="section-unavailable">Couldn’t load the saved summary · {saved.error}</p>
          ) : (
            <AiSummaryBody
              view={view}
              generating={generating}
              configured={configured}
              missingKeyMessage={missingKeyMessage}
              name={name}
              owned={owned}
            />
          )}
        </div>
      </DisclosureSection>
    </SummaryKind.Provider>
  )
}

