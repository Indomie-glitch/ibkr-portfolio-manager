import { useEffect, useRef, useState } from 'react'

// Load data for a key (e.g. a holding's conId) and return { data, error, loading }.
// Results are tagged with their key, so switching holdings never shows the previous
// holding's data while the new one loads.
export function useFetch(fetcher, key) {
  const [result, setResult] = useState({ key: null, data: null, error: null })

  // fetcher is a new function on every render; keep the latest one in a ref so the
  // effect below only reruns when the key changes
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  })

  useEffect(() => {
    let ignore = false
    fetcherRef
      .current()
      .then((data) => {
        if (!ignore) setResult({ key, data, error: null })
      })
      .catch((err) => {
        if (!ignore) setResult({ key, data: null, error: err.message })
      })
    return () => {
      ignore = true
    }
  }, [key])

  if (result.key !== key) return { data: null, error: null, loading: true }
  return { data: result.data, error: result.error, loading: false }
}
