// The full Connections page (#279, Figma Connections / V2 142:1157), opened from "Open full map" in a
// stock's Connections section. Same map as the section (ConnectionMap, buildMap), larger, with an
// inspector for the selected node and the list of every connection under it.
import { useEffect, useMemo, useState } from 'react'
import ConnectionMap from '../components/detail/ConnectionMap.jsx'
import { Legend, Notes, ScopeKeys } from '../components/detail/ConnectionParts.jsx'
import { SectionLoading } from '../components/detail/DisclosureSection.jsx'
import InfoButton from '../components/risk/InfoButton.jsx'
import { useConnections } from '../hooks/useConnections.js'
import { FILTERS, visible } from '../lib/connections.js'
import { DEPTH_EXPLAINER, FILTER_LABELS, INSPECTOR_EXPLAINER, LIST_EXPLAINER, MAP_EXPLAINER } from '../lib/connectionTexts.js'
import { countsText, describeNode, findNode, linkRows } from '../lib/connectionsPage.js'

const LIST_SHORT = 5

function Keys({ label, labelId, options, value, onChange }) {
  return (
    <>
      <span className="risk-bar-label" id={labelId}>
        {label}
      </span>
      <div className="risk-period-keys" role="group" aria-labelledby={labelId}>
        {options.map(([key, text]) => (
          <button key={key} type="button" className={`risk-period-key ${key === value ? 'active' : ''}`} aria-pressed={key === value}
            onClick={() => onChange(key)}>
            {text}
          </button>
        ))}
      </div>
    </>
  )
}

function Chip({ children, mine }) {
  return <span className={`con-chip ${mine ? 'mine' : ''}`}>{children}</span>
}

// The panel on the right: what the selected node is, with its facts and roles
function Inspector({ node, ctx, onOpen }) {
  const d = describeNode(node, ctx)
  const person = d.type === 'PERSON'
  return (
    <div className="risk-panel con-inspector">
      <div className="con-header">
        <span className="risk-code">SELECTED</span>
        <span className="con-type">{d.type}</span>
        <InfoButton text={INSPECTOR_EXPLAINER} />
      </div>
      <div className="con-identity">
        <div className={`con-photo ${d.mine ? 'mine' : ''} ${person ? '' : 'square'}`} aria-hidden="true">
          {person ? d.initials : d.title.slice(0, 4)}
        </div>
        <div className="con-identity-text">
          <p className="con-name">{d.title}</p>
          <p className="con-role">{d.subtitle}</p>
          {d.badge && <p className="con-badge">{d.badge}</p>}
        </div>
      </div>
      <p className="con-text">{d.text}</p>

      {d.facts.length > 0 && (
        <dl className="con-facts">
          {d.facts.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      )}

      {d.rows.length > 0 && (
        <div className="con-roles" role="table" aria-label="Roles">
          <div className="con-role-row head" role="row">
            <span>COMPANY</span>
            <span>ROLE</span>
            <span className="grow" />
            <span>SINCE</span>
          </div>
          {d.rows.map((r, i) => (
            <div key={i} className={`con-role-row ${r.mine ? 'mine' : ''}`} role="row" title={r.name}>
              <span className="company">
                <Chip mine={r.mine}>{r.chip}</Chip>
              </span>
              <span className="role">{r.role}</span>
              <span className="grow" />
              <span className="since">{r.since ?? ''}</span>
            </div>
          ))}
        </div>
      )}

      <div className="con-actions">
        {d.open && (
          <button type="button" className="con-primary" onClick={() => onOpen(node)}>
            Open stock
          </button>
        )}
        {person && d.wikipedia && (
          <button type="button" className="con-primary" onClick={() => onOpen(node)}>
            Wikipedia ↗
          </button>
        )}
      </div>
      {person && !d.wikipedia && <p className="con-hint">No Wikipedia page is known for this person.</p>}
      <p className="con-hint">
        Click any node to inspect it here. Double click opens its page: a stock opens its stock detail, a person opens their Wikipedia page.
      </p>
    </div>
  )
}

function ConnectionList({ rows, selectedId, onSelect, onOpen }) {
  const [all, setAll] = useState(false)
  const shown = all ? rows : rows.slice(0, LIST_SHORT)
  return (
    <div className="risk-panel con-list">
      <div className="con-header">
        <span className="risk-code">CON LIST</span>
        <span className="con-type">ALL CONNECTIONS</span>
        <InfoButton text={LIST_EXPLAINER} />
        <div className="spacer" />
        <span className="con-count">{rows.length} · SORTED BY RELEVANCE TO YOU</span>
      </div>
      <div className="con-list-row head" role="row">
        <span className="c-type">TYPE</span>
        <span className="c-name">NAME</span>
        <span className="c-how">HOW IT’S CONNECTED</span>
        <span className="grow" />
        <span className="c-yours">YOURS</span>
      </div>
      {shown.map((r) => (
        <div
          key={r.id}
          role="row"
          tabIndex={0}
          className={`con-list-row ${r.owned ? 'mine' : ''} ${selectedId === r.id ? 'selected' : ''}`}
          onClick={() => onSelect(r.node)}
          onDoubleClick={() => onOpen(r.node)}
          onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect(r.node))}
        >
          <span className="c-type">{r.type}</span>
          <span className="c-name">
            <b>{r.name}</b>
            <i>{r.sub}</i>
          </span>
          <span className="c-how">{r.how}</span>
          <span className="grow" />
          <span className="c-yours">
            {r.owned === 0 ? <em>—</em> : r.owned === 1 ? <Chip mine>{r.yours[0]}</Chip> : <Chip mine>{r.owned} OWNED</Chip>}
          </span>
        </div>
      ))}
      {rows.length > LIST_SHORT && (
        <button type="button" className="con-show-all" onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show all ${rows.length}`}
        </button>
      )}
    </div>
  )
}

function ConnectionsPage({ holding, name, onSummary }) {
  const [filter, setFilter] = useState('all')
  const [depth, setDepth] = useState(1)
  const [onlyMine, setOnlyMine] = useState(false)
  const [query, setQuery] = useState('')
  const [selectedId, setSelectedId] = useState('self')
  const c = useConnections(holding, name, { depth })

  const shown = useMemo(() => visible(c.map, filter, onlyMine), [c.map, filter, onlyMine])
  const rows = useMemo(() => linkRows(shown, c.stock), [shown, c.stock])
  // The toolbar's counts ("31 links · 3 to your holdings") are for everything on the map, whatever is
  // filtered; null while loading. Only the text goes up, so an unchanged map doesn't re-render App.
  const summary = useMemo(() => (c.loading ? null : countsText(linkRows(c.map, c.stock))), [c.loading, c.map, c.stock])
  useEffect(() => {
    onSummary?.(summary)
  }, [summary, onSummary])

  // What's selected must still be showing: a filter can hide it
  const selected = shown.nodes.find((n) => n.id === selectedId) ?? shown.nodes.find((n) => n.id === 'self')
  const ctx = { stock: c.stock, holdings: c.holdings }

  function find(text) {
    setQuery(text)
    const found = findNode(shown, text)
    if (found) setSelectedId(found.id)
  }

  const noMatch = query.trim() && !findNode(shown, query)
  return (
    <div className="page-body risk-page connections-page">
      <div className="risk-command-bar">
        <Keys label="Show" labelId="con-show-label" value={filter} onChange={setFilter}
          options={FILTERS.map((f) => [f, FILTER_LABELS[f]])} />
        <Keys label="Depth" labelId="con-depth-label" value={depth} onChange={setDepth} options={[[1, '1'], [2, '2']]} />
        <InfoButton text={DEPTH_EXPLAINER} />
        <div className="spacer" />
        <button type="button" className={`con-mine-key ${onlyMine ? 'active' : ''}`} aria-pressed={onlyMine} onClick={() => setOnlyMine(!onlyMine)}>
          ● ONLY MINE
        </button>
        <label className={`con-find ${noMatch ? 'none' : ''}`}>
          <span aria-hidden="true">⌕</span>
          <input type="search" placeholder="Find in map" value={query} onChange={(e) => find(e.target.value)} aria-label="Find in map"
            title={noMatch ? 'Nothing on the map matches' : undefined} />
        </label>
      </div>

      <div className="con-main">
        <div className="risk-panel con-map-panel">
          <div className="con-header">
            <span className="risk-code">CON MAP</span>
            <InfoButton text={MAP_EXPLAINER} />
          </div>
          {c.loading ? (
            <div className="con-map con-map-loading" aria-label="Loading connections">
              <SectionLoading lines={1} />
            </div>
          ) : (
            <ConnectionMap shown={shown} selectedId={selected?.id} onSelect={(n) => setSelectedId(n.id)} onOpen={c.open} zoomButtons>
              {(filter === 'all' || filter === 'competitors') && c.competitors.data?.status !== 'unsupported' && (
                <ScopeKeys market={c.market} scope={c.scope} onChange={c.setScope} />
              )}
            </ConnectionMap>
          )}
          {!c.loading && <Notes c={c} filter={filter} />}
          <Legend hint="Click a node to inspect it · Double click opens it · Scroll to zoom" />
        </div>
        {selected && !c.loading ? <Inspector node={selected} ctx={ctx} onOpen={c.open} /> : <div className="risk-panel con-inspector" />}
      </div>

      {!c.loading && <ConnectionList rows={rows} selectedId={selected?.id} onSelect={(n) => setSelectedId(n.id)} onOpen={c.open} />}
    </div>
  )
}

export default ConnectionsPage
