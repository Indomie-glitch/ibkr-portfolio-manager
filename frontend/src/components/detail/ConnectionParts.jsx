import { formatShortDate } from '../../lib/format.js'

export function CompetitorNote({ competitors }) {
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
export function BoardNote({ board, market, onRead, onAcceptTerms, busy, error }) {
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

// The competitors' own-market / all-markets keys, drawn over the map's top right
export function ScopeKeys({ market, scope, onChange }) {
  return (
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
          onClick={() => onChange(value)}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

// The notes under the map: competitors still loading or none, the board not read, a link failing to open
export function Notes({ c, filter }) {
  return (
    <>
      {(filter === 'all' || filter === 'competitors') && <CompetitorNote competitors={c.competitors.data} />}
      {c.competitors.error && <p className="con-note">Competitors unavailable · {c.competitors.error}</p>}
      {(filter === 'all' || filter === 'people') && (
        <BoardNote
          board={c.board.data}
          market={c.market}
          busy={c.boardActions.busy}
          error={c.boardActions.error}
          onRead={c.boardActions.read}
          onAcceptTerms={c.boardActions.acceptTerms}
        />
      )}
      {c.opening && <p className="con-note">{c.opening.error ?? `Opening ${c.opening.symbol}…`}</p>}
    </>
  )
}

export function Legend({ hint = 'Click a node to open it · Scroll to zoom' }) {
  return (
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
      <span className="con-hint">{hint}</span>
    </div>
  )
}

