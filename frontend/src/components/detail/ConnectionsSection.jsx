import { useContext, useMemo, useState } from 'react'
import {
  acceptAsxTerms,
  fetchBoard,
  fetchCompetitors,
  fetchExecutives,
  fetchIndexMembers,
  fetchStockIndices,
  readBoard,
  searchStocks,
} from '../../lib/api.js'
import { FILTERS, buildMap, marketOf, matchSearchResult, visible } from '../../lib/connections.js'
import { formatShortDate } from '../../lib/format.js'
import { StockNavContext } from '../../lib/stockNav.js'
import { useFetch } from '../../hooks/useFetch.js'
import InfoButton from '../risk/InfoButton.jsx'
import ConnectionMap from './ConnectionMap.jsx'
import { SectionUnavailable } from './DisclosureSection.jsx'

const EXPLAINER = {
  title: 'Connections',
  what: 'How this stock is linked to others: the indexes it’s in, the largest companies in its industry, the people who run it, and its board of directors. Lines in amber lead to stocks you own.',
  consider: 'A link shows a shared index, industry or person, not how the prices move together. Board members come from the company’s latest proxy statement or annual report; index lists and competitors are refreshed weekly.',
}

const FILTER_LABELS = { all: 'ALL', indices: 'INDICES', competitors: 'COMPETITORS', people: 'PEOPLE' }

// The indexes the stock is in, and which symbols each holds (to find your holdings among them)
async function loadIndices(conId) {
  const answer = await fetchStockIndices(conId)
  const lists = await Promise.all(
    answer.indices.map((index) =>
      fetchIndexMembers(index.id)
        .then((m) => [index.id, m.members.map((member) => member.symbol)])
        .catch(() => [index.id, []])),
  )
  return { indices: answer.indices, members: Object.fromEntries(lists) }
}

function CompetitorNote({ competitors }) {
  if (!competitors) return null
  if (competitors.status === 'loading') {
    const { done, total } = competitors.progress ?? {}
    return <p className="con-note">Finding competitors · {done} of {total} companies looked up so far</p>
  }
  if (competitors.status === 'no_industry') {
    return <p className="con-note">No industry on Yahoo (an ETF or fund), so there are no competitors to show.</p>
  }
  if (competitors.status === 'unsupported') {
    return <p className="con-note">Competitors cover ASX and US stocks only.</p>
  }
  if (competitors.companies?.filter((c) => !c.is_self).length === 0) {
    return <p className="con-note">No other company in its industry among the index members.</p>
  }
  return null
}

// The board's state when it isn't on the map: not read yet (with what's needed), no document, a
// newer document, or reading it now
function BoardNote({ board, market, onRead, onAcceptTerms, busy, error }) {
  if (!board) return null
  const kind = market === 'ASX' ? 'annual report' : 'proxy statement'
  const needs = board.needs?.map((n) => n.id) ?? []
  const actionError = error && <p className="con-note error-text">{error}</p>

  if (busy) {
    return <p className="con-note">Reading the board from the latest {kind}… this can take up to a minute.</p>
  }
  if (board.status === 'ready' && board.newer_document) {
    return (
      <div className="con-board-note">
        <p className="con-note">
          A newer {kind} is out ({formatShortDate(board.newer_document.filed)}). The board shown is from the previous one.
        </p>
        {board.can_read && (
          <button type="button" className="settings-button" onClick={onRead}>
            Update board
          </button>
        )}
        {actionError}
      </div>
    )
  }
  if (board.status === 'ready') return actionError || null

  const notFound = board.status === 'no_document' || board.status === 'unreadable'
  return (
    <div className="con-board-note">
      <p className="con-note">
        {notFound
          ? `No board list found: ${board.error}`
          : `The board hasn’t been read yet. Reading it downloads the latest ${kind} and asks Claude to list the directors (about half a US cent on your API key).`}
        {notFound && board.document?.url && (
          <>
            {' '}
            <a href={board.document.pdf_url ?? board.document.url} target="_blank" rel="noreferrer">
              Open the document
            </a>
          </>
        )}
      </p>
      {needs.includes('asx_terms') && (
        <p className="con-note">
          ASX boards come from company announcements on asx.com.au, which ASX allows for private and personal use only.{' '}
          <button type="button" className="settings-button" onClick={onAcceptTerms}>
            I accept, for my personal use
          </button>
        </p>
      )}
      {needs
        .filter((n) => n !== 'asx_terms')
        .map((n) => (
          <p key={n} className="con-note">
            {board.needs.find((x) => x.id === n).message}
          </p>
        ))}
      {board.can_read && !notFound && (
        <button type="button" className="settings-button primary" onClick={onRead}>
          Read board
        </button>
      )}
      {actionError}
    </div>
  )
}

function ConnectionsSection({ holding, name }) {
  const { holdings, openStock } = useContext(StockNavContext)
  const market = marketOf(holding)
  const [filter, setFilter] = useState('all')
  const [onlyMine, setOnlyMine] = useState(false)
  // Competitors from the stock's own market by default; "All" adds the other market (CBA's peers start with JPM)
  const [scope, setScope] = useState('same_market')
  const [boardVersion, setBoardVersion] = useState(0)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState(null)
  const [opening, setOpening] = useState(null)

  const conId = holding.con_id
  const indices = useFetch(() => loadIndices(conId), conId)
  const competitors = useFetch(() => fetchCompetitors(conId, scope), `${conId}:${scope}`)
  const executives = useFetch(() => fetchExecutives(conId), conId)
  const board = useFetch(() => fetchBoard(conId), `${conId}:${boardVersion}`)

  const stock = { con_id: conId, symbol: holding.symbol, name: name ?? holding.name ?? holding.symbol, market }
  const map = useMemo(
    () =>
      buildMap({
        stock,
        holdings,
        indices: indices.data?.indices ?? [],
        members: indices.data?.members ?? {},
        competitors: competitors.data,
        executives: executives.data,
        board: board.data,
      }),
    // stock is rebuilt each render from these
    // oxlint-disable-next-line react-hooks/exhaustive-deps
    [conId, holding.symbol, holding.name, name, market, holdings, indices.data, competitors.data, executives.data, board.data],
  )
  const shown = visible(map, filter, onlyMine)

  async function run(action) {
    setBusy(true)
    setActionError(null)
    try {
      await action()
      setBoardVersion((v) => v + 1)
    } catch (err) {
      setActionError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function open(node) {
    if (node.link && !node.open) {
      window.open(node.link, '_blank', 'noopener,noreferrer')
      return
    }
    if (!openStock) return
    if (node.open.con_id) {
      openStock({ con_id: node.open.con_id, symbol: node.label })
      return
    }
    // Competitors have no con_id: find it the way the Markets search does
    setOpening({ symbol: node.open.symbol, error: null })
    try {
      const found = matchSearchResult(await searchStocks(node.open.symbol), node.open.symbol, node.open.market)
      if (!found) throw new Error(`${node.open.symbol} wasn’t found on ${node.open.market === 'ASX' ? 'the ASX' : 'a US exchange'}.`)
      setOpening(null)
      openStock(found)
    } catch (err) {
      setOpening({ symbol: node.open.symbol, error: err.message })
    }
  }

  const loading = indices.loading || competitors.loading || executives.loading || board.loading
  if (indices.error && competitors.error && board.error) {
    return <SectionUnavailable what="Connections" reason={indices.error} />
  }
  const asOf = indices.data?.indices?.[0]?.as_of
  const boardDoc = board.data?.status === 'ready' ? board.data.document : null

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
          <InfoButton text={EXPLAINER} />
          <div className="spacer" />
          <button
            type="button"
            className={`con-mine-key ${onlyMine ? 'active' : ''}`}
            aria-pressed={onlyMine}
            onClick={() => setOnlyMine(!onlyMine)}
          >
            ● ONLY MINE
          </button>
        </div>

        {loading ? (
          <div className="con-map con-map-loading" aria-label="Loading connections">
            <span className="skeleton-line" />
          </div>
        ) : (
          <ConnectionMap shown={shown} onOpen={open}>
            {(filter === 'all' || filter === 'competitors') && competitors.data?.status !== 'unsupported' && (
              <div className="con-scope risk-period-keys" role="group" aria-label="Competitors from">
                {[
                  ['same_market', market === 'ASX' ? 'ASX' : 'US'],
                  ['all', 'ALL'],
                ].map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    className={`risk-period-key ${scope === value ? 'active' : ''}`}
                    aria-pressed={scope === value}
                    onClick={() => setScope(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </ConnectionMap>
        )}

        {!loading && (
          <>
            {(filter === 'all' || filter === 'competitors') && <CompetitorNote competitors={competitors.data} />}
            {competitors.error && <p className="con-note">Competitors unavailable · {competitors.error}</p>}
            {(filter === 'all' || filter === 'people') && (
              <BoardNote
                board={board.data}
                market={market}
                busy={busy}
                error={actionError}
                onRead={() => run(() => readBoard(conId))}
                onAcceptTerms={() => run(() => acceptAsxTerms(true))}
              />
            )}
            {opening && <p className="con-note">{opening.error ?? `Opening ${opening.symbol}…`}</p>}
          </>
        )}

        <div className="con-legend">
          <span>
            <i className="con-swatch mine" /> You own it
          </span>
          <span>
            <i className="con-swatch self" /> This stock
          </span>
          <span>
            <i className="con-swatch line" /> Link to your holdings
          </span>
          <div className="spacer" />
          <span className="con-hint">Click a node to open it · Scroll to zoom</span>
        </div>
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
