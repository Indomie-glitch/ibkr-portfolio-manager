import { useCallback, useEffect, useRef, useState } from 'react'

// Loads data now and again every `ms` while the component is mounted (the pipeline sheet follows a live
// queue). `key` restarts it for another question (e.g. the log's filter). reload() fetches at once, e.g.
// after pressing Retry. A failed refresh keeps the last data and reports the error.
export function usePolled(fetcher, key, ms = 5000) {
  const [state, setState] = useState({ key: null, data: null, error: null })
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  })
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let ignore = false
    const load = () =>
      fetcherRef
        .current()
        .then((data) => !ignore && setState({ key, data, error: null }))
        .catch((err) => !ignore && setState((old) => ({ key, data: old.key === key ? old.data : null, error: err.message })))
    load()
    const timer = setInterval(load, ms)
    return () => {
      ignore = true
      clearInterval(timer)
    }
  }, [key, ms, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  const current = state.key === key
  return { data: current ? state.data : null, error: current ? state.error : null, loading: !current, reload }
}
