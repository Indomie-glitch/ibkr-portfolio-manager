import { useCallback, useEffect, useState } from 'react'
import appIcon from '../assets/app-icon.png'
import { checkForUpdate, downloadUpdate, installUpdate, onCheckForUpdatesMenu, openReleasePage, restartApp } from '../appUpdater.js'
import { SpinnerIcon } from './icons.jsx'

const MB = 1024 * 1024
// Wait a moment after launch, so the check doesn't compete with starting up
const LAUNCH_CHECK_DELAY_MS = 3000

// Once per session, even if this component is shown again
let checkedAtLaunch = false

// The update dialog: offered at launch and from the app menu, never installed without a click.
// `ready` is false while the startup screen shows (the window is too small for a dialog then).
function UpdatePrompt({ ready }) {
  // hidden | checking | available | up_to_date | check_failed | downloading | download_failed
  // | installing | install_failed
  const [phase, setPhase] = useState('hidden')
  const [update, setUpdate] = useState(null)
  const [progress, setProgress] = useState({ received: 0, total: null })
  const [error, setError] = useState(null)

  // manual: from the menu, so "you're up to date" and check errors are shown; at launch they aren't
  const check = useCallback(async (manual) => {
    if (manual) setPhase('checking')
    try {
      const found = await checkForUpdate()
      setUpdate(found)
      if (found) setPhase('available')
      else setPhase(manual ? 'up_to_date' : 'hidden')
    } catch (err) {
      console.warn('Update check failed', err)
      setError(String(err))
      setPhase(manual ? 'check_failed' : 'hidden')
    }
  }, [])

  useEffect(() => {
    if (!ready || checkedAtLaunch) return
    checkedAtLaunch = true
    const timer = setTimeout(() => check(false), LAUNCH_CHECK_DELAY_MS)
    return () => clearTimeout(timer)
  }, [ready, check])

  useEffect(() => {
    const stop = onCheckForUpdatesMenu(() => check(true))
    return () => {
      stop.then((unlisten) => unlisten())
    }
  }, [check])

  async function updateNow() {
    setPhase('downloading')
    setProgress({ received: 0, total: null })
    try {
      await downloadUpdate((event) => {
        if (event.event === 'progress') setProgress({ received: event.received, total: event.total })
      })
    } catch (err) {
      setError(String(err))
      setPhase('download_failed')
      return
    }
    setPhase('installing')
    try {
      await installUpdate() // relaunches on success
    } catch (err) {
      setError(String(err))
      setPhase('install_failed')
    }
  }

  if (phase === 'hidden') return null
  const close = () => setPhase('hidden')

  let title
  let body
  let buttons
  if (phase === 'checking') {
    title = 'Checking for updates…'
    body = (
      <p className="update-status">
        <SpinnerIcon size={14} /> Contacting GitHub
      </p>
    )
  } else if (phase === 'up_to_date') {
    title = 'You’re up to date'
    body = <p className="update-text">Portfolio Manager {update?.current_version ?? ''} is the newest version.</p>
    buttons = (
      <button type="button" className="setup-button primary" onClick={close}>
        OK
      </button>
    )
  } else if (phase === 'check_failed') {
    title = 'Couldn’t check for updates'
    body = <p className="update-text">Check your internet connection and try again from the Portfolio Manager menu.</p>
    buttons = (
      <button type="button" className="setup-button primary" onClick={close}>
        OK
      </button>
    )
  } else if (phase === 'available') {
    title = 'A new version of Portfolio Manager is available'
    body = (
      <>
        <p className="update-text">
          Version {update.version} is out; you have {update.current_version}.
        </p>
        {update.notes && <div className="update-notes">{update.notes}</div>}
      </>
    )
    buttons = (
      <>
        <button type="button" className="setup-button" onClick={close}>
          Later
        </button>
        <button type="button" className="setup-button primary" onClick={updateNow}>
          Update Now
        </button>
      </>
    )
  } else if (phase === 'downloading') {
    const { received, total } = progress
    title = `Downloading version ${update.version}…`
    body = (
      <div className="update-progress">
        <progress className="setup-progress-track" max={total || 1} value={total ? received : 0} />
        <p className="update-status">
          {total ? `${Math.floor(received / MB)} of ${Math.floor(total / MB)} MB` : `${Math.floor(received / MB)} MB`}
        </p>
      </div>
    )
  } else if (phase === 'installing') {
    title = 'Installing and restarting…'
    body = (
      <p className="update-status">
        <SpinnerIcon size={14} /> Signing out of IBKR and replacing the app
      </p>
    )
  } else if (phase === 'download_failed') {
    title = 'The update couldn’t be downloaded'
    body = <p className="update-text">Nothing was changed. Try again later from the Portfolio Manager menu.</p>
    buttons = (
      <button type="button" className="setup-button primary" onClick={close}>
        OK
      </button>
    )
  } else if (phase === 'install_failed') {
    title = 'The update couldn’t be installed'
    body = (
      <p className="update-text">
        macOS didn’t let Portfolio Manager replace itself. Download version {update.version} from the release page,
        open the DMG and drag the app into Applications, replacing the old one.
      </p>
    )
    buttons = (
      <>
        <button type="button" className="setup-button" onClick={() => restartApp()}>
          Restart Portfolio Manager
        </button>
        <button type="button" className="setup-button primary" onClick={() => openReleasePage(update.version)}>
          Open Release Page
        </button>
      </>
    )
  }

  return (
    <div className="update-backdrop">
      <div className="update-dialog" role="dialog" aria-modal="true" aria-labelledby="update-title">
        <img className="update-icon" src={appIcon} width="80" height="80" alt="" />
        <h2 className="update-title" id="update-title">
          {title}
        </h2>
        {body}
        {(phase === 'download_failed' || phase === 'install_failed') && error && (
          <p className="update-error" title={error}>
            {error}
          </p>
        )}
        {buttons && <div className="update-buttons">{buttons}</div>}
      </div>
    </div>
  )
}

export default UpdatePrompt
