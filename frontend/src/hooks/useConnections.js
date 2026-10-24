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
} from '../lib/api.js'
import { buildMap, marketOf, matchSearchResult } from '../lib/connections.js'
import { StockNavContext } from '../lib/stockNav.js'
import { useFetch } from './useFetch.js'

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

/**
 * Everything the Connections section and the full page show for one stock (#114, #279): the data
 * from the indexes, competitors, executives and board endpoints, the map built from it, reading the
 * board, and opening a node. depth 2 adds the directors' other boards.
 */
export function useConnections(holding, name, { depth = 1 } = {}) {
  const { holdings, openStock } = useContext(StockNavContext)
  const market = marketOf(holding)
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

  const stock = useMemo(
    () => ({ con_id: conId, symbol: holding.symbol, name: name ?? holding.name ?? holding.symbol, market }),
    [conId, holding.symbol, holding.name, name, market],
  )
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
        depth,
      }),
    [stock, holdings, indices.data, competitors.data, executives.data, board.data, depth],
  )

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

  // Opens what a node points at: a stock (found by symbol first when it has no con_id: a competitor)
  // or a person's Wikipedia page
  async function open(node) {
    if (node.link && !node.open) {
      window.open(node.link, '_blank', 'noopener,noreferrer')
      return
    }
    if (!openStock || !node.open) return
    if (node.open.con_id) {
      openStock({ con_id: node.open.con_id, symbol: node.label })
      return
    }
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

  return {
    stock, market, holdings, map, scope, setScope, opening, open,
    indices, competitors, executives, board,
    loading: indices.loading || competitors.loading || executives.loading || board.loading,
    boardActions: { busy, error: actionError, read: () => run(() => readBoard(conId)), acceptTerms: () => run(() => acceptAsxTerms(true)) },
  }
}
