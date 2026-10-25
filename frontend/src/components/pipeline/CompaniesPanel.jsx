import { useContext, useState } from 'react'
import { fetchPipelineFilings, retryPipeline, searchStocks } from '../../lib/api.js'
import { matchSearchResult } from '../../lib/connections.js'
import { companyKeys, filterCompanies, readTime, usd, weekChange } from '../../lib/pipelineFormat.js'
import { pipelineExplainer } from '../../lib/pipelineExplainers.js'
import { StockNavContext } from '../../lib/stockNav.js'
import { usePolled } from '../../hooks/usePolled.js'
import InfoButton from '../risk/InfoButton.jsx'

const SHOWN = 9
const STATUS_LABEL = { reading: 'reading', waiting: 'waiting', failed: 'failed', 'up to date': 'up to date', 'not on EDGAR': 'not on EDGAR' }

// One company's filings, shown under its row: what each is, where it stands, and the actions
function Filings({ company, onChanged, onClose }) {
  const { openConnections } = useContext(StockNavContext)
  const { data, error, reload } = usePolled(() => fetchPipelineFilings(company.company_id), company.company_id, 8000)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState(null)
  const searchable = (company.market === 'US' || company.market === 'ASX') && company.symbol

  async function retry() {
    setBusy(true)
    setProblem(null)
    try {
      await retryPipeline({ company_id: company.company_id })
      reload()
      onChanged()
    } catch (err) {
      setProblem(err.message)
    }
    setBusy(false)
  }

  async function openMap() {
    setBusy(true)
    setProblem(null)
    try {
      const found = matchSearchResult(await searchStocks(company.symbol), company.symbol, company.market)
      if (!found) throw new Error(`${company.symbol} wasn’t found on ${company.market === 'ASX' ? 'the ASX' : 'a US exchange'}.`)
      onClose()
      openConnections?.(found)
    } catch (err) {
      setProblem(err.message)
      setBusy(false)
    }
  }

  const filings = data?.filings ?? []
  return (
    <div className="pipeline-filings">
      {error && <p className="risk-panel-note">Unavailable: {error}</p>}
      {data && filings.length === 0 && <p className="risk-panel-note">No filings yet. {company.status === 'not on EDGAR' ? 'SEC has none for this company (no US listing).' : 'The next check will look.'}</p>}
      {filings.slice(0, 8).map((f) => (
        <div className="pipeline-filing" key={f.id}>
          <span className="pipeline-filing-label">{f.label}</span>
          <span className="pipeline-filing-date">{f.filed_at}</span>
          <span className={`pipeline-filing-state ${f.status === 'failed' || f.job_status === 'failed' || f.job_status === 'dead' ? 'failed' : ''}`} title={f.error ?? undefined}>
            {f.job_status === 'failed' || f.job_status === 'dead' ? 'failed' : f.job_status === 'queued' ? 'waiting' : f.job_status === 'running' ? 'reading' : f.status === 'downloaded' ? 'read' : f.status}
          </span>
          <a className="pipeline-filing-link" href={f.url} target="_blank" rel="noreferrer">
            Open filing ↗
          </a>
        </div>
      ))}
      <div className="pipeline-filing-actions">
        {company.status === 'failed' && (
          <button type="button" className="pipeline-button" onClick={retry} disabled={busy}>
            Retry failed
          </button>
        )}
        {searchable && openConnections && (
          <button type="button" className="pipeline-button" onClick={openMap} disabled={busy}>
            Open on Connections map
          </button>
        )}
        {problem && (
          <span className="error-text" role="alert">
            {problem}
          </span>
        )}
      </div>
    </div>
  )
}

// PIP 01: the watched companies (Figma Pipeline / V1C, node 155:1345)
export default function CompaniesPanel({ pipeline, companies, onChanged, onClose }) {
  const [key, setKey] = useState('all')
  const [all, setAll] = useState(false)
  const [selected, setSelected] = useState(null)
  const rows = filterCompanies(companies ?? [], key)
  const shown = all ? rows : rows.slice(0, SHOWN)

  return (
    <section className="risk-panel pipeline-companies" aria-labelledby="pipeline-companies-title">
      <header className="risk-panel-header">
        <span className="risk-code">PIP 01</span>
        <h2 className="risk-panel-title" id="pipeline-companies-title">
          Companies
        </h2>
        <InfoButton text={pipelineExplainer('companies', pipeline)} />
        <span className="spacer" />
        <span className="risk-panel-label">{pipeline.watched} watched · sorted by last activity</span>
      </header>
      <div className="risk-period-keys" role="group" aria-label="Show companies">
        {companyKeys(pipeline.companies).map((k) => (
          <button
            key={k.id}
            type="button"
            className={`risk-period-key ${key === k.id ? 'active' : ''}`}
            aria-pressed={key === k.id}
            onClick={() => {
              setKey(k.id)
              setSelected(null)
            }}
          >
            {k.label} {k.count}
          </button>
        ))}
      </div>
      <div className="pipeline-table" role="table" aria-label="Watched companies">
        <div className="pipeline-row pipeline-head" role="row">
          <span className="pipeline-symbol" />
          <span className="pipeline-name">COMPANY</span>
          <span className="pipeline-filing-col">LATEST FILING</span>
          <span className="pipeline-read">READ</span>
          <span className="pipeline-num">LINKS</span>
          <span className="pipeline-week">7D</span>
          <span className="spacer" />
          <span className="pipeline-status-col">STATUS</span>
          <span className="pipeline-cost">COST</span>
        </div>
        {shown.length === 0 && <p className="risk-panel-note">No companies here.</p>}
        {shown.map((c) => {
          const week = weekChange(c.links_week)
          const open = selected === c.company_id
          return (
            <div key={c.company_id}>
              <button
                type="button"
                className={`pipeline-row pipeline-company ${open ? 'open' : ''}`}
                role="row"
                aria-expanded={open}
                onClick={() => setSelected(open ? null : c.company_id)}
              >
                <span className="pipeline-symbol">{c.symbol || '—'}</span>
                <span className="pipeline-name" title={c.name}>
                  {c.name}
                </span>
                <span className="pipeline-filing-col">{c.latest_filing ?? '—'}</span>
                <span className="pipeline-read">{readTime(c.read_at)}</span>
                <span className="pipeline-num strong">{c.links}</span>
                <span className={`pipeline-week ${week.tone}`}>{week.text}</span>
                <span className="spacer" />
                <span className={`pipeline-pill ${c.status.replace(/ /g, '-')}`}>
                  <span className="pipeline-dot" />
                  {STATUS_LABEL[c.status]}
                </span>
                <span className="pipeline-cost">{usd(c.cost_usd, { dash: true })}</span>
              </button>
              {open && <Filings company={c} onChanged={onChanged} onClose={onClose} />}
            </div>
          )
        })}
      </div>
      {rows.length > SHOWN && (
        <button type="button" className="pipeline-more" onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show all ${rows.length}`}
        </button>
      )}
      <p className="risk-panel-note pipeline-footnote">
        Click a company to see the filings read, and open it on the Connections map.
      </p>
    </section>
  )
}
