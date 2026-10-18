import { useEffect, useState } from 'react'
import { searchStocks } from '../lib/api.js'

// Wait for a pause in typing before asking IB (it allows about one search a second)
const SEARCH_DELAY_MS = 350

// Search any ASX or US stock (GET /search) for the text typed (already trimmed; '' searches
// nothing). Returns { searching, items, error } for exactly that text: old results never show under
// new text. Used by Markets and the watchlist's add-a-stock field (#206).
export function useStockSearch(query) {
  // The results belong to search.query
  const [search, setSearch] = useState({ query: '', items: [], error: null })

  useEffect(() => {
    if (!query) return
    let ignore = false
    const timer = setTimeout(() => {
      searchStocks(query)
        .then((items) => !ignore && setSearch({ query, items, error: null }))
        .catch((err) => !ignore && setSearch({ query, items: [], error: err.message }))
    }, SEARCH_DELAY_MS)
    return () => {
      ignore = true
      clearTimeout(timer)
    }
  }, [query])

  const searching = query !== '' && search.query !== query
  const current = query !== '' && !searching
  return { searching, items: current ? search.items : [], error: current ? search.error : null }
}
