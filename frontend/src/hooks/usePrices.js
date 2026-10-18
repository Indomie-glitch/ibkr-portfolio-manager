import { useEffect, useState } from 'react'
import { fetchPrices } from '../lib/api.js'

// Prices (GET /prices, same shape as /quotes) for stocks that aren't holdings, by conId: fetched for
// the ids that don't have one yet, and again for all of them after every app refresh (refreshKey).
// Used by Markets and watchlists (#206); a failed request leaves those rows without a price.
export function usePrices(conIds, refreshKey) {
  const [prices, setPrices] = useState({})

  const missingIds = [...new Set(conIds)].filter((id) => !(id in prices)).join(',')
  useEffect(() => {
    if (!missingIds) return
    let ignore = false
    fetchPrices(missingIds)
      .then((quotes) => {
        if (ignore) return
        setPrices((old) => ({ ...old, ...Object.fromEntries(quotes.map((p) => [p.con_id, p])) }))
      })
      .catch(() => {}) // rows just show no price
    return () => {
      ignore = true
    }
  }, [missingIds])

  useEffect(() => {
    // New figures on Refresh: fetch the prices again
    // oxlint-disable-next-line react/set-state-in-effect
    setPrices({})
  }, [refreshKey])

  return prices
}
