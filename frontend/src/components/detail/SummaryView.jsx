// How a summary is drawn; shared by the latest, past and compare views
import { GROUPS } from '../../summarySections.js'

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

// Compare mode tags a point as new, changed (different numbers) or no longer present
const MARK_LABELS = { new: 'New', removed: 'No longer present', changed: 'Changed' }

function Points({ points, links, marks }) {
  return (
    <ul className="ai-points">
      {points.map((point, i) => {
        const mark = marks?.get(point)
        return (
        <li key={i} className={mark ? `ai-point-${mark.kind}` : undefined}>
          {mark && (
            <span className={`ai-mark ${mark.kind}`}>
              {MARK_LABELS[mark.kind]}
              {mark.kind === 'changed' && <span className="num">: {mark.from || '–'} → {mark.to || '–'}</span>}
            </span>
          )}{' '}
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
        )
      })}
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

export function SectionBody({ name, section, links, facts, marks }) {
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
        <Points points={theme.points} links={links} marks={marks} />
      </div>
    ))
  }
  if (name === 'bull_bear') {
    return (
      <div className="ai-bull-bear">
        <div>
          <p className="ai-theme-title gain">Bull case</p>
          <Points points={section.bull} links={links} marks={marks} />
        </div>
        <div>
          <p className="ai-theme-title loss">Bear case</p>
          <Points points={section.bear} links={links} marks={marks} />
        </div>
      </div>
    )
  }
  return (
    <>
      {extra}
      <Points points={section.points} links={links} marks={marks} />
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

export function AiSummaryBody({ view, generating, configured, name }) {
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
