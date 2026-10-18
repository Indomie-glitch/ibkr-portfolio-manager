// How a summary is drawn; shared by the latest, past and compare views, and by stock and portfolio
// summaries (what differs is in summaryKinds.js)
import { useContext } from 'react'
import { SummaryKind } from './summaryKinds.js'

function scrollTo(target) {
  document.getElementById(target)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function Sources({ ids, links, facts }) {
  // News ids become numbered links to the article; data ids become chips that scroll to that data
  // (a portfolio summary's holding chip opens that holding)
  const kind = useContext(SummaryKind)
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
        const source = kind.source(id, facts)
        const onClick = source.onClick ?? (source.target ? () => scrollTo(source.target) : null)
        return onClick ? (
          <button key={id} type="button" className="ai-source" title={source.title} onClick={onClick}>
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

function Points({ points, links, facts, marks }) {
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
            <Sources ids={point.sources} links={links} facts={facts} />
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
  const kind = useContext(SummaryKind)
  let extra = null
  // The stock summary's tables of calculated figures
  if (kind.name === 'stock' && name === 'upcoming_events' && facts?.['D:events']) {
    extra = <FactsTable rows={facts['D:events'].upcoming.map((e) => [e.event, e.date])} />
  }
  if (kind.name === 'stock' && name === 'your_position' && facts?.['D:position']) {
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
        <Points facts={facts} points={theme.points} links={links} marks={marks} />
      </div>
    ))
  }
  if (name === 'bull_bear') {
    return (
      <div className="ai-bull-bear">
        <div>
          <p className="ai-theme-title gain">Bull case</p>
          <Points facts={facts} points={section.bull} links={links} marks={marks} />
        </div>
        <div>
          <p className="ai-theme-title loss">Bear case</p>
          <Points facts={facts} points={section.bear} links={links} marks={marks} />
        </div>
      </div>
    )
  }
  return (
    <>
      {extra}
      <Points facts={facts} points={section.points} links={links} marks={marks} />
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

// owned: false for a stock found on Markets (#95), which gets the briefing without Your position
export function AiSummaryBody({ view, generating, configured, missingKeyMessage, name, owned = true }) {
  const kind = useContext(SummaryKind)
  // A saved stock summary knows whether the stock was owned when it was written
  const withPosition = view?.owned ?? owned
  if (!view) {
    if (!configured) {
      return <p className="section-unavailable">{missingKeyMessage ?? 'AI summaries are turned off.'}</p>
    }
    if (!generating) {
      return (
        <p className="ai-empty">{kind.intro(name, withPosition)}</p>
      )
    }
  }

  const sections = view?.summary ?? {}
  const gaps = yahooGaps(view?.missing)
  return (
    <div className="ai-summary">
      {gaps.length > 0 && <p className="ai-banner">Generated without: {gaps.join(', ')} (Yahoo Finance unavailable).</p>}
      {kind.groups(withPosition).map((group) => (
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
        {view?.model ? ` by ${view.model}` : ''}; it only uses {kind.basis(withPosition)}.
      </p>
    </div>
  )
}
