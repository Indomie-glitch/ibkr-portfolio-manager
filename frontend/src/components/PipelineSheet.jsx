import { useEffect, useRef, useState } from 'react'
import { fetchPipeline, fetchPipelineCompanies, runPipelineNow, savePipelineSettings } from '../lib/api.js'
import { isEmptyState, runNowNote, statusPill, tiles } from '../lib/pipelineFormat.js'
import { pipelineExplainer } from '../lib/pipelineExplainers.js'
import { usePolled } from '../hooks/usePolled.js'
import CompaniesPanel from './pipeline/CompaniesPanel.jsx'
import LogPanel from './pipeline/LogPanel.jsx'
import InfoButton from './risk/InfoButton.jsx'

// What it is, shown while the pipeline is off and has never run
function EmptyState({ pipeline, onOpenSettings }) {
  return (
    <div className="pipeline-empty">
      <h3>The supply chain pipeline is off</h3>
      <p>
        It reads the annual and quarterly reports that companies file with the SEC, for the {pipeline.themes[0] ?? 'AI hardware'} companies on its watch list ({pipeline.watched || 59} of them),
        and picks out who sells to whom: the customers and suppliers they name, and the share of sales a big customer makes up. Every link keeps the sentence or figure it came from.
      </p>
      <p>
        This version collects the filings and the customer figures that companies tag in their reports. The supplier map built from them comes in a later version.
      </p>
      <h4>How to turn it on</h4>
      <ol>
        <li>Open Settings and find Supply chain pipeline.</li>
        <li>Turn on Run pipeline. It uses your own Anthropic key (Settings › AI summaries) when it reads reports with Claude.</li>
        <li>Set a monthly budget. It starts at US$10, and the pipeline pauses itself when it is used up.</li>
      </ol>
      {!pipeline.settings.sec_contact_email && (
        <p className="pipeline-empty-warn">
          Downloading filings needs a contact address for the SEC. In development, set SEC_CONTACT_EMAIL in .env.
        </p>
      )}
      <button type="button" className="pipeline-button primary" onClick={onOpenSettings}>
        Open Settings
      </button>
    </div>
  )
}

// The pipeline as a floating sheet (Figma Pipeline / V1C, node 157:1496), opened from Settings. Closes with Done,
// Escape or a click outside, like the Settings sheet.
export default function PipelineSheet({ onClose, onOpenSettings }) {
  const doneRef = useRef(null)
  const { data: pipeline, error, reload } = usePolled(fetchPipeline, 'pipeline', 4000)
  const { data: companies, reload: reloadCompanies } = usePolled(fetchPipelineCompanies, 'companies', 6000)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const [added, setAdded] = useState(null)

  useEffect(() => {
    const previous = document.activeElement
    doneRef.current?.focus()
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      previous?.focus?.()
    }
  }, [onClose])

  const changed = () => {
    reload()
    reloadCompanies()
  }

  async function act(work) {
    setBusy(true)
    setProblem(null)
    try {
      const result = await work()
      if (result && typeof result.added_usd === 'number') setAdded(runNowNote(result.added_usd))
      changed()
    } catch (err) {
      setProblem(err.message)
    }
    setBusy(false)
  }

  const empty = pipeline && isEmptyState(pipeline)
  const pill = statusPill(pipeline)
  const off = !pipeline?.enabled

  return (
    <div className="settings-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="pipeline-sheet" role="dialog" aria-modal="true" aria-labelledby="pipeline-title">
        <div className="pipeline-toolbar">
          <div className="pipeline-title-stack">
            <h2 id="pipeline-title">Pipeline</h2>
            <p>
              Settings › Supply chain pipeline
              {pipeline ? ` · ${pipeline.themes.join(', ') || 'No'} theme · ${pipeline.watched} companies watched` : ''}
            </p>
          </div>
          <div className="spacer" />
          <span className={`pipeline-status-pill ${pill.tone}`}>
            <span className="pipeline-dot" />
            {pill.label}
          </span>
          <button
            type="button"
            className="pipeline-button"
            disabled={busy || off || !pipeline}
            onClick={() => act(() => savePipelineSettings({ paused: pipeline.status !== 'paused' }))}
          >
            {pipeline?.status === 'paused' ? 'Resume' : 'Pause'}
          </button>
          <button type="button" className="pipeline-button" disabled={busy || off || !pipeline} onClick={() => act(runPipelineNow)}>
            Run now
          </button>
          <button ref={doneRef} type="button" className="pipeline-button primary" onClick={onClose}>
            Done
          </button>
        </div>
        <div className="pipeline-body">
          {problem && (
            <p className="error-text" role="alert">
              {problem}
            </p>
          )}
          {added && (
            <p className="risk-panel-note" role="status">
              {added}
            </p>
          )}
          {!pipeline && !error && <p className="risk-panel-note">Loading…</p>}
          {error && !pipeline && <p className="risk-panel-note" role="status">Unavailable: {error}</p>}
          {empty && <EmptyState pipeline={pipeline} onOpenSettings={onOpenSettings} />}
          {pipeline && !empty && (
            <>
              <div className="pipeline-tiles">
                {tiles(pipeline).map((tile) => (
                  <div className="risk-tile" key={tile.id}>
                    <p className="risk-label">{tile.label}</p>
                    <p className={`risk-tile-value ${tile.tone ?? ''}`}>{tile.value}</p>
                    <p className="risk-tile-sub">{tile.sub}</p>
                    <span className="risk-tile-info">
                      <InfoButton text={pipelineExplainer(tile.id, pipeline)} />
                    </span>
                  </div>
                ))}
              </div>
              <div className="pipeline-columns">
                <CompaniesPanel pipeline={pipeline} companies={companies?.companies} onChanged={changed} onClose={onClose} />
                <LogPanel pipeline={pipeline} onChanged={changed} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
