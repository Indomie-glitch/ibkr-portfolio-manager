import { useContext, useState } from 'react'
import { FILTERS, visible } from '../../lib/connections.js'
import { formatShortDate } from '../../lib/format.js'
import { StockNavContext } from '../../lib/stockNav.js'
import { useConnections } from '../../hooks/useConnections.js'
import { FILTER_LABELS, MAP_EXPLAINER } from '../../lib/connectionTexts.js'
import InfoButton from '../risk/InfoButton.jsx'
import { Legend, Notes, ScopeKeys } from './ConnectionParts.jsx'
import ConnectionMap from './ConnectionMap.jsx'
import { SectionUnavailable } from './DisclosureSection.jsx'

function ConnectionsSection({ holding, name }) {
  const { openConnections } = useContext(StockNavContext)
  const [filter, setFilter] = useState('all')
  const [onlyMine, setOnlyMine] = useState(false)
  const c = useConnections(holding, name)
  const shown = visible(c.map, filter, onlyMine)

  if (c.indices.error && c.competitors.error && c.board.error) {
    return <SectionUnavailable what="Connections" reason={c.indices.error} />
  }
  const asOf = c.indices.data?.indices?.[0]?.as_of
  const boardDoc = c.board.data?.status === 'ready' ? c.board.data.document : null

  return (
    <div className="connections">
      <div className="risk-panel con-panel">
        <div className="con-header">
          <span className="risk-code">CON MAP</span>
          <div className="risk-period-keys" role="group" aria-label="Show">
            {FILTERS.map((f) => (
              <button
                key={f}
                type="button"
                className={`risk-period-key ${f === filter ? 'active' : ''}`}
                aria-pressed={f === filter}
                onClick={() => setFilter(f)}
              >
                {FILTER_LABELS[f]}
              </button>
            ))}
          </div>
          <InfoButton text={MAP_EXPLAINER} />
          <div className="spacer" />
          {openConnections && (
            <button type="button" className="con-open-full" onClick={() => openConnections({ ...holding, name: name ?? holding.name })}>
              Open full map ↗
            </button>
          )}
          <button
            type="button"
            className={`con-mine-key ${onlyMine ? 'active' : ''}`}
            aria-pressed={onlyMine}
            onClick={() => setOnlyMine(!onlyMine)}
          >
            ● ONLY MINE
          </button>
        </div>

        {c.loading ? (
          <div className="con-map con-map-loading" aria-label="Loading connections">
            <span className="skeleton-line" />
          </div>
        ) : (
          <ConnectionMap shown={shown} onOpen={c.open}>
            {(filter === 'all' || filter === 'competitors') && c.competitors.data?.status !== 'unsupported' && (
              <ScopeKeys market={c.market} scope={c.scope} onChange={c.setScope} />
            )}
          </ConnectionMap>
        )}

        {!c.loading && (
          <Notes c={c} filter={filter} />
        )}

        <Legend />
      </div>
      <div className="con-data-notes">
        <span>Index lists and roles refreshed weekly{asOf ? ` · as of ${formatShortDate(asOf)}` : ''}</span>
        <div className="spacer" />
        {boardDoc && (
          <a href={boardDoc.pdf_url ?? boardDoc.url} target="_blank" rel="noreferrer">
            Board from {boardDoc.title}
          </a>
        )}
      </div>
    </div>
  )
}

export default ConnectionsSection
