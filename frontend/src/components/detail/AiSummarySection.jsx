import { useState } from 'react'
import { fetchPastSummary, fetchSummary, fetchSummaryComparison, fetchSummaryHistory, generateSummary } from '../../lib/api.js'
import { formatGeneratedTime, formatSummaryDate } from '../../lib/format.js'
import { useFetch } from '../../hooks/useFetch.js'
import { SparklesIcon } from '../icons.jsx'
import DisclosureSection, { SectionLoading } from './DisclosureSection.jsx'
import SummaryCompare from './SummaryCompare.jsx'
import SummaryHistoryMenu from './SummaryHistoryMenu.jsx'
import { AiSummaryBody } from './SummaryView.jsx'

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
function PastSummary({ conId, summaryId, name, onBack }) {
  const past = useFetch(() => fetchPastSummary(conId, summaryId), `${conId}:${summaryId}`)
  if (past.loading) return <SectionLoading />
  if (past.error) return <BackBanner onBack={onBack}>Couldn’t load that summary · {past.error}.</BackBanner>
  return (
    <>
      <BackBanner onBack={onBack}>Viewing summary from {formatSummaryDate(past.data.created_at)}.</BackBanner>
      <AiSummaryBody view={past.data} generating={false} configured name={name} />
    </>
  )
}

function ComparedSummaries({ conId, ids, onBack }) {
  const [a, b] = ids
  const comparison = useFetch(() => fetchSummaryComparison(conId, a, b), `${conId}:${a}:${b}`)
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

function AiSummarySection({ holding, name }) {
  const saved = useFetch(() => fetchSummary(holding.con_id), holding.con_id)
  // The generation in progress (or just finished/failed). Tagged with its holding, so switching
  // stocks mid-generation never shows one stock's summary under another; the backend still
  // finishes and saves it.
  const [run, setRun] = useState(null)
  // What the section shows instead of the latest summary: { conId, pastId } or { conId, compare: [a, b] }
  const [mode, setMode] = useState(null)

  const runForThis = run?.conId === holding.con_id ? run : null
  const generating = runForThis?.status === 'running'
  const configured = saved.data?.ai_configured ?? false
  const missingKeyMessage = saved.data?.missing_key_message
  const latest = saved.data?.latest
  // While writing, show the new sections; otherwise the newest finished summary
  const view = runForThis?.view ?? latest
  const modeForThis = mode?.conId === holding.con_id ? mode : null
  const backToLatest = () => setMode(null)

  // Reloads whenever a newer summary is saved
  const newestId = runForThis?.status === 'done' ? runForThis.view.id : latest?.id
  const history = useFetch(() => fetchSummaryHistory(holding.con_id), `${holding.con_id}:${newestId ?? ''}`)

  async function start() {
    const conId = holding.con_id
    setMode(null)
    const update = (change) => setRun((r) => (r && r.conId === conId ? change(r) : r))
    setRun({ conId, status: 'running', view: { summary: {}, links: {}, warnings: [] }, error: null })
    try {
      await generateSummary(conId, (event, data) => {
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
      {history.data?.length > 0 && (
        <SummaryHistoryMenu
          items={history.data}
          shownId={modeForThis?.pastId ?? (modeForThis ? null : history.data[0].id)}
          disabled={generating}
          onView={(pastId) => setMode(pastId ? { conId: holding.con_id, pastId } : null)}
          onCompare={(ids) => setMode({ conId: holding.con_id, compare: ids })}
        />
      )}
      <button
        type="button"
        className="button-primary compact"
        onClick={start}
        disabled={!configured || generating || saved.loading}
        title={configured ? undefined : missingKeyMessage}
      >
        <SparklesIcon size={13} /> {view || latest ? 'Regenerate' : 'Summarise'}
      </button>
    </>
  )

  return (
    <DisclosureSection id="aiSummary" title="AI summary" accent actions={actions}>
      <div className="ai-summary-card">
        {runForThis?.status === 'error' && (
          <p className="ai-banner error" role="alert">
            {runForThis.error}
            {Object.keys(runForThis.view?.summary ?? {}).length > 0 && ' The sections below are incomplete and weren’t saved.'}
          </p>
        )}
        {modeForThis?.pastId ? (
          <PastSummary conId={holding.con_id} summaryId={modeForThis.pastId} name={name} onBack={backToLatest} />
        ) : modeForThis?.compare ? (
          <ComparedSummaries conId={holding.con_id} ids={modeForThis.compare} onBack={backToLatest} />
        ) : saved.error && !view ? (
          <p className="section-unavailable">Couldn’t load the saved summary · {saved.error}</p>
        ) : (
          <AiSummaryBody
            view={view}
            generating={generating}
            configured={configured}
            missingKeyMessage={missingKeyMessage}
            name={name}
          />
        )}
      </div>
    </DisclosureSection>
  )
}

export default AiSummarySection
