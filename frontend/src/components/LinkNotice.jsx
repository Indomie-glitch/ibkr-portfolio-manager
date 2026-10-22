import { useEffect, useState } from 'react'
import { isTauri } from '@tauri-apps/api/core'
import { onLinkOpenFailed } from '../desktop/appLinks.js'

// Long enough to read two short lines
const HIDE_AFTER_MS = 5000

// Mac app only (renders nothing in the browser): a small notice when a link out (news, company website, citation) couldn't be
// opened in the browser (#276). Hides itself after a few seconds, or on ×.
function LinkNotice() {
  const [reason, setReason] = useState(null)
  // Bumped on every failure, so a second one restarts the timer
  const [shownAt, setShownAt] = useState(0)

  // isTauri, not IN_APP: `npm run tauri dev` has no bundled backend but opens links the same way
  useEffect(() => {
    if (!isTauri()) return
    return onLinkOpenFailed((text) => {
      setReason(text)
      setShownAt(Date.now())
    })
  }, [])

  useEffect(() => {
    if (!reason) return
    const timer = setTimeout(() => setReason(null), HIDE_AFTER_MS)
    return () => clearTimeout(timer)
  }, [reason, shownAt])

  if (!reason) return null
  return (
    <div className="link-notice" role="status">
      <div className="link-notice-text">
        <span className="link-notice-title">Couldn&apos;t open the link</span>
        <span>{reason}</span>
      </div>
      <button type="button" className="link-notice-close" aria-label="Dismiss" onClick={() => setReason(null)}>
        ×
      </button>
    </div>
  )
}

export default LinkNotice
