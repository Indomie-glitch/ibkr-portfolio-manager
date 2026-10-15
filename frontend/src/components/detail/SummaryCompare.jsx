import { formatSummaryTime } from '../../format.js'
import { diffSection } from '../../summaryDiff.js'
import { GROUPS } from '../../summarySections.js'
import { SectionBody } from './SummaryView.jsx'

function heading(view) {
  const price = view.facts?.['D:key_stats']?.last_price
  return price ? `${formatSummaryTime(view.created_at)} · ${price}` : formatSummaryTime(view.created_at)
}

// Exact changes between the two facts sheets, calculated by the backend
function DataChanges({ rows }) {
  return (
    <div className="compare-data">
      <p className="ai-group-title">What changed in the data</p>
      <dl className="compare-data-grid">
        {rows.map((row) => (
          <div key={row.label} title={row.note} className={row.minor ? 'minor' : undefined}>
            <dt>{row.label}</dt>
            <dd className="num">
              {row.old != null ? `${row.old} → ${row.new ?? '–'}` : (row.new ?? '–')}
            </dd>
            {row.change && <dd className={`compare-change ${row.tone ?? ''}`}>{row.change}</dd>}
          </div>
        ))}
      </dl>
    </div>
  )
}

function Column({ side, view, name, marks }) {
  const section = view.summary[name]
  return (
    <div className="compare-column">
      <p className="compare-side">{side}</p>
      {section ? (
        <SectionBody name={name} section={section} links={view.links ?? {}} facts={view.facts} marks={marks} />
      ) : (
        <p className="section-unavailable">Not in this summary</p>
      )}
    </div>
  )
}

// Two saved summaries side by side, section by section
function SummaryCompare({ comparison }) {
  const { older, newer, data_changes: dataChanges } = comparison
  return (
    <div className="ai-summary compare">
      <DataChanges rows={dataChanges} />
      <p className="section-footnote">
        Below, points are matched by wording, so treat the tags as a guide: <span className="ai-mark new">New</span>{' '}
        <span className="ai-mark changed">Changed</span> (same point, different figures) and{' '}
        <span className="ai-mark removed">No longer present</span>.
      </p>
      <div className="compare-row compare-headings">
        <p className="compare-heading num">Older · {heading(older)}</p>
        <p className="compare-heading num">Newer · {heading(newer)}</p>
      </div>
      {GROUPS.map((group) => (
        <div className="ai-group" key={group.title}>
          <p className="ai-group-title">{group.title}</p>
          {group.sections.map(([key, title]) => {
            const marks = diffSection(key, older.summary[key], newer.summary[key])
            return (
              <div className="ai-section" key={key}>
                <p className="ai-section-title">{title}</p>
                <div className="compare-row">
                  <Column side={`Older · ${heading(older)}`} view={older} name={key} marks={marks.older} />
                  <Column side={`Newer · ${heading(newer)}`} view={newer} name={key} marks={marks.newer} />
                </div>
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}

export default SummaryCompare
