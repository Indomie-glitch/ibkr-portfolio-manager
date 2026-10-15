import { useState } from 'react'
import { fetchSummary, generateSummary } from '../../api.js'
import { formatGeneratedTime } from '../../format.js'
import { useFetch } from '../../useFetch.js'
import { SparklesIcon } from '../icons.jsx'
import DisclosureSection from './DisclosureSection.jsx'

// The 10 sections, always in this order, in four groups
const GROUPS = [
  {
    title: 'About the company',
    sections: [
      ['business_snapshot', 'Business snapshot'],
      ['financial_health', 'Financial health'],
      ['valuation', 'Valuation in context'],
    ],
  },
  {
    title: 'What’s happening now',
    sections: [
      ['news_digest', 'News digest'],
      ['price_moves', 'Why the price moved'],
      ['upcoming_events', 'Upcoming events'],
    ],
  },
  {
    title: 'Looking ahead',
    sections: [
      ['bull_bear', 'Bull and bear case'],
      ['key_risks', 'Key risks'],
    ],
  },
  {
    title: 'What it means for you',
    sections: [
      ['your_position', 'Your position'],
      ['changes_since_last', 'What changed since you last looked'],
    ],
  },
]

// Data ids the model cites -> label and the part of the page that shows that data
const DATA_SOURCES = {
  'D:profile': { label: 'About', target: 'section-about' },
  'D:key_stats': { label: 'Key statistics', target: 'section-keyStats' },
  'D:financials': { label: 'Financial statements' },
  'D:valuation_history': { label: 'Past P/E' },
  'D:price_moves': { label: 'Price chart', target: 'price-chart' },
  'D:performance': { label: 'Performance', target: 'section-performance' },
  'D:events': { label: 'Upcoming events' },
  'D:position': { label: 'Your position', target: 'your-position' },
  'D:since_last': { label: 'Previous summary' },
  'D:missing': { label: 'Missing data' },
}

function scrollTo(target) {
  document.getElementById(target)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function Sources({ ids, links }) {
  // News ids become numbered links to the article; data ids become chips that scroll to that data
  const newsNumbers = Object.keys(links)
  return (
    <span className="ai-sources">
      {ids.map((id) => {
        if (links[id]) {
          const link = links[id]
          return (
            <a
              key={id}
              className="ai-source news"
              href={link.url}
              target="_blank"
              rel="noopener noreferrer"
              title={`${link.publisher}: ${link.title}`}
            >
              {newsNumbers.indexOf(id) + 1}
            </a>
          )
        }
        const source = DATA_SOURCES[id] ?? { label: id }
        return source.target ? (
          <button key={id} type="button" className="ai-source" onClick={() => scrollTo(source.target)}>
            {source.label}
          </button>
        ) : (
          <span key={id} className="ai-source">
            {source.label}
          </span>
        )
      })}
    </span>
  )
}

function Points({ points, links }) {
  return (
    <ul className="ai-points">
      {points.map((point, i) => (
        <li key={i}>
          {point.text}{' '}
          {point.flags && (
            <span className="ai-flag" title={`Automatic check: possible ${point.flags.join(', ')}. Read this point critically.`}>
              check
            </span>
          )}{' '}
          {point.uncited ? (
            <span className="ai-uncited" title="The model didn't cite a source for this point">
              no source
            </span>
          ) : (
            <Sources ids={point.sources} links={links} />
          )}
        </li>
      ))}
    </ul>
  )
}

// Numbers calculated by the backend, shown next to the model's explanation
function FactsTable({ rows }) {
  const shown = rows.filter(([, value]) => value != null)
  if (shown.length === 0) return null
  return (
    <dl className="ai-facts">
      {shown.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className="num">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function SectionBody({ name, section, links, facts }) {
  let extra = null
  if (name === 'upcoming_events' && facts?.['D:events']) {
    extra = <FactsTable rows={facts['D:events'].upcoming.map((e) => [e.event, e.date])} />
  }
  if (name === 'your_position' && facts?.['D:position']) {
    const p = facts['D:position']
    extra = (
      <FactsTable
        rows={[
          ['Gain or loss', p.unrealised_gain_or_loss && `${p.unrealised_gain_or_loss} (${p.unrealised_gain_or_loss_pct}%)`],
          ['Portfolio weight', p.portfolio_weight_pct != null ? `${p.portfolio_weight_pct}%` : null],
          ['Expected yearly dividends', p.expected_yearly_dividends],
          ['Purchase date', p.purchase_date ?? 'Unknown'],
          ['12-month CGT date', p.cgt_12_month_date ?? 'Unknown'],
        ]}
      />
    )
  }

  if (name === 'news_digest') {
    return section.themes.map((theme) => (
      <div className="ai-theme" key={theme.theme}>
        <p className="ai-theme-title">{theme.theme}</p>
        <Points points={theme.points} links={links} />
      </div>
    ))
  }
  if (name === 'bull_bear') {
    return (
      <div className="ai-bull-bear">
        <div>
          <p className="ai-theme-title gain">Bull case</p>
          <Points points={section.bull} links={links} />
        </div>
        <div>
          <p className="ai-theme-title loss">Bear case</p>
          <Points points={section.bear} links={links} />
        </div>
      </div>
    )
  }
  return (
    <>
      {extra}
      <Points points={section.points} links={links} />
    </>
  )
}

function SkeletonLines() {
  return (
    <div className="ai-skeleton">
      {[100, 88, 60].map((width) => (
        <span key={width} className="skeleton-line accent" style={{ width: `${width}%` }} />
      ))}
    </div>
  )
}

// Yahoo outages are worth flagging; permanent gaps (no peer data) are explained in the sections
function yahooGaps(missing) {
  return (missing ?? []).filter((m) => m.includes('Yahoo Finance unavailable')).map((m) => m.replace(/ \(.*\)$/, ''))
}

function AiSummaryBody({ view, generating, configured, name }) {
  if (!view) {
    if (!configured) {
      return <p className="section-unavailable">Add ANTHROPIC_API_KEY to .env and restart the backend to turn on AI summaries.</p>
    }
    if (!generating) {
      return (
        <p className="ai-empty">
          No summary yet. Summarise writes a briefing on {name} from the data on this page: the business, its finances
          and valuation, recent news and price moves, upcoming events, the case for and against, risks, and what it
          means for your position.
        </p>
      )
    }
  }

  const sections = view?.summary ?? {}
  const gaps = yahooGaps(view?.missing)
  return (
    <div className="ai-summary">
      {gaps.length > 0 && <p className="ai-banner">Generated without: {gaps.join(', ')} (Yahoo Finance unavailable).</p>}
      {GROUPS.map((group) => (
        <div className="ai-group" key={group.title}>
          <p className="ai-group-title">{group.title}</p>
          {group.sections.map(([key, title]) => {
            const section = sections[key]
            return (
              <div className="ai-section" key={key}>
                <p className="ai-section-title">
                  {title}
                  {section && section.status !== 'ok' && (
                    <span className="ai-status">{section.status === 'limited' ? 'Limited data' : 'Not available'}</span>
                  )}
                </p>
                {section ? (
                  <SectionBody name={key} section={section} links={view.links ?? {}} facts={view.facts} />
                ) : (
                  <SkeletonLines />
                )}
              </div>
            )
          })}
        </div>
      ))}
      {view?.warnings?.length > 0 && (
        <details className="ai-checks">
          <summary>
            {view.warnings.length} automatic check{view.warnings.length === 1 ? '' : 's'} flagged; points marked “check”
            may break the summary rules, so read them critically
          </summary>
          <ul>
            {view.warnings.map((warning, i) => (
              <li key={i}>{warning}</li>
            ))}
          </ul>
        </details>
      )}
      <p className="section-footnote">
        Not financial advice. Generated {view?.as_of_text ? `from data as of ${view.as_of_text}` : 'from the data on this page'}
        {view?.model ? ` by ${view.model}` : ''}; it only uses the company profile, key statistics, financial
        statements, recent news, price history and your position shown in this app.
      </p>
    </div>
  )
}

function AiSummarySection({ holding, name }) {
  const saved = useFetch(() => fetchSummary(holding.con_id), holding.con_id)
  // The generation in progress (or just finished/failed). Tagged with its holding, so switching
  // stocks mid-generation never shows one stock's summary under another; the backend still
  // finishes and saves it.
  const [run, setRun] = useState(null)

  const runForThis = run?.conId === holding.con_id ? run : null
  const generating = runForThis?.status === 'running'
  const configured = saved.data?.ai_configured ?? false
  const latest = saved.data?.latest
  // While writing, show the new sections; otherwise the newest finished summary
  const view = runForThis?.view ?? latest

  async function start() {
    const conId = holding.con_id
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
  const note = generating ? 'Writing…' : generatedAt
  const actions = (
    <>
      {note && <span className="disclosure-note">{note}</span>}
      <button
        type="button"
        className="button-primary compact"
        onClick={start}
        disabled={!configured || generating || saved.loading}
        title={configured ? undefined : 'Add ANTHROPIC_API_KEY to .env to turn on AI summaries'}
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
        {saved.error && !view ? (
          <p className="section-unavailable">Couldn’t load the saved summary · {saved.error}</p>
        ) : (
          <AiSummaryBody view={view} generating={generating} configured={configured} name={name} />
        )}
      </div>
    </DisclosureSection>
  )
}

export default AiSummarySection
