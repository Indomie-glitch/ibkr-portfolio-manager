import { useCallback, useEffect, useState } from 'react'
import { IN_APP } from '../lib/api.js'
import { loginState } from '../desktop/appSession.js'

// Steps where something is happening: check often so the screen follows along
const BUSY = ['starting', 'signing_in', 'awaiting_approval']

// The IBKR sign-in state from the Mac app, kept up to date (once a second while signing in,
// every five seconds otherwise). Always null outside the app.
export function useLogin() {
  const [login, setLogin] = useState(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!IN_APP) return
    let timer
    let stopped = false
    async function check() {
      try {
        const next = await loginState()
        if (stopped) return
        setLogin((old) => (JSON.stringify(old) === JSON.stringify(next) ? old : next))
        timer = setTimeout(check, BUSY.includes(next.state) ? 1000 : 5000)
      } catch {
        if (!stopped) timer = setTimeout(check, 2000)
      }
    }
    check()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [tick])

  // Call after starting or cancelling a sign-in, to follow it straight away
  const refresh = useCallback(() => setTick((n) => n + 1), [])
  return [login, refresh]
}
