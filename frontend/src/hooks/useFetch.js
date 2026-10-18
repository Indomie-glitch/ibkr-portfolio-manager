import { createContext, useContext, useEffect, useRef, useState } from 'react'

// Goes up every time the app reloads its data (the Refresh button and the minute timer). A section
// whose request failed (e.g. Yahoo was briefly down) tries again then, instead of staying
// "unavailable" until another stock is opened (#203). App.jsx provides it.
export const RefreshContext = createContext(0)

// Load data for a key (e.g. a holding's conId) and return { data, error, loading }.
// Results are tagged with their key, so switching holdings never shows the previous
// holding's data while the new one loads.
export function useFetch(fetcher, key) {
  const [result, setResult] = useState({ key: null, data: null, error: null })
  // Bumped to fetch the same key again after a failure
  const [attempt, setAttempt] = useState(0)
  const refresh = useContext(RefreshContext)

  // fetcher is a new function on every render; keep the latest one in a ref so the
  // effect below only reruns when the key changes
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  })

  // A refresh retries a failed request; a successful one stays as it is (most sections are cached
  // for minutes to a day by the backend anyway)
  const failed = result.key === key && result.error != null
  const failedRef = useRef(failed)
  useEffect(() => {
    failedRef.current = failed
  })
  const firstRefresh = useRef(refresh)
  useEffect(() => {
    if (refresh === firstRefresh.current) return
    // oxlint-disable-next-line react/set-state-in-effect
    if (failedRef.current) setAttempt((n) => n + 1)
  }, [refresh])

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
  }, [key, attempt])

  if (result.key !== key) return { data: null, error: null, loading: true }
  return { data: result.data, error: result.error, loading: false }
}
