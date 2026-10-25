import { useEffect, useRef, useState } from 'react'
import { fetchPipelineLog, retryPipeline } from '../../lib/api.js'
import { costSummary, logTime } from '../../lib/pipelineFormat.js'
import { pipelineExplainer } from '../../lib/pipelineExplainers.js'
import { usePolled } from '../../hooks/usePolled.js'
import InfoButton from '../risk/InfoButton.jsx'

const KEYS = [
  ['all', 'ALL'],
  ['links', 'LINKS'],
  ['failed', 'FAILED'],
]

// PIP 02: the live log (Figma Pipeline / V1C, node 155:1416)
export default function LogPanel({ pipeline, onChanged }) {
  const [kind, setKind] = useState('all')
  const { data, error } = usePolled(() => fetchPipelineLog(kind), kind, 4000)
  const [problem, setProblem] = useState(null)
  const box = useRef(null)
  const events = data?.events ?? []
  const newest = events[0]?.at
  const following = pipeline.status === 'running' || pipeline.status === 'starting'

  // Newest on top: keep the view at the top when new lines arrive
  useEffect(() => {
    if (box.current) box.current.scrollTop = 0
  }, [newest, kind])

  async function retry(jobId) {
    setProblem(null)
    try {
      await retryPipeline({ job_id: jobId })
      onChanged()
    } catch (err) {
      setProblem(err.message)
    }
  }

  return (
    <section className="risk-panel pipeline-log-panel" aria-labelledby="pipeline-log-title">
      <header className="risk-panel-header">
        <span className="risk-code">PIP 02</span>
        <h2 className="risk-panel-title" id="pipeline-log-title">
          Live log
        </h2>
        <InfoButton text={pipelineExplainer('log', pipeline)} />
        <span className="spacer" />
        <span className="risk-panel-label">{following ? 'Following' : 'Not running'}</span>
      </header>
      <div className="risk-period-keys" role="group" aria-label="Show log lines">
        {KEYS.map(([id, label]) => (
          <button key={id} type="button" className={`risk-period-key ${kind === id ? 'active' : ''}`} aria-pressed={kind === id} onClick={() => setKind(id)}>
            {label}
          </button>
        ))}
      </div>
      <div className="pipeline-log" ref={box} role="log" aria-live="off" tabIndex={0} aria-label="Pipeline log">
        {error && !data && <p className="pipeline-log-empty">Unavailable: {error}</p>}
        {data && events.length === 0 && (
          <p className="pipeline-log-empty">{kind === 'all' ? 'Nothing has run yet.' : kind === 'links' ? 'No links found yet.' : 'Nothing has failed.'}</p>
        )}
        {events.map((e, i) => (
          <div className="pipeline-log-line" key={`${e.at}-${e.tag}-${i}`}>
            <span className="pipeline-log-time">{logTime(e.at)}</span>
            <span className={`pipeline-log-tag ${e.tag.toLowerCase()}`}>{e.tag}</span>
            <span className="pipeline-log-text">
              {e.text}
              {e.job_id != null && (
                <button type="button" className="pipeline-log-retry" onClick={() => retry(e.job_id)}>
                  Retry
                </button>
              )}
            </span>
          </div>
        ))}
      </div>
      {problem && (
        <p className="error-text" role="alert">
          {problem}
        </p>
      )}
      <div className="pipeline-costs">
        {costSummary(pipeline.cost).map((c) => (
          <div key={c.label}>
            <p className="pipeline-cost-label">{c.label}</p>
            <p className={`pipeline-cost-value ${c.tone ?? ''}`}>{c.value}</p>
          </div>
        ))}
      </div>
      <p className="risk-panel-note pipeline-footnote">
        LINK lines are new supplier or customer links as they’re found. The pipeline pauses itself when the monthly budget runs out.
      </p>
    </section>
  )
}
