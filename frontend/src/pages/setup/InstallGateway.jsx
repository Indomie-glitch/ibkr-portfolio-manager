import { useEffect, useState } from 'react'
import { gatewayStatus, installGateway } from '../../desktop/appGateway.js'
import { CheckCircleIcon, DownloadIcon, SpinnerIcon, WarningIcon } from '../../components/icons.jsx'
import { IconCircle } from './parts.jsx'

const MB = 1024 * 1024

function InstallGateway({ onBack, onContinue }) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  const [watching, setWatching] = useState(0)

  useEffect(() => {
    let timer
    async function check() {
      try {
        const next = await gatewayStatus()
        setStatus(next)
        if (!next.installed && ['downloading', 'checking', 'installer_open'].includes(next.setup.step)) {
          timer = setTimeout(check, 1000)
        }
      } catch (err) {
        setError(String(err))
      }
    }
    check()
    return () => clearTimeout(timer)
  }, [watching])

  async function install() {
    setError(null)
    try {
      await installGateway()
      setWatching((n) => n + 1)
    } catch (err) {
      setError(String(err))
    }
  }

  const installed = status?.installed
  const setup = status?.setup
  const failed = error || setup?.error
  let progress = null
  if (installed) {
    progress = (
      <div className="setup-progress-labels">
        <span className="setup-installed">
          <CheckCircleIcon size={14} /> IB Gateway {installed.version} is installed
        </span>
      </div>
    )
  } else if (setup?.step === 'downloading' || setup?.step === 'checking') {
    const checking = setup.step === 'checking'
    progress = (
      <>
        <div className="setup-progress-labels">
          <span>{checking ? 'Checking the installer is genuine' : 'Downloading IB Gateway'}</span>
          <span className="setup-progress-amount">
            {setup.total ? `${Math.floor(setup.received / MB)} MB of ${Math.floor(setup.total / MB)} MB` : ''}
          </span>
        </div>
        <progress className="setup-progress-track" max={setup.total || 1} value={setup.received} />
      </>
    )
  } else if (setup?.step === 'installer_open') {
    progress = (
      <div className="setup-progress-labels">
        <span>IBKR’s installer is open</span>
        <SpinnerIcon size={14} />
      </div>
    )
  }

  return (
    <div className="setup install">
      <p className="setup-step-of">Step 1 of 2</p>
      <IconCircle>
        <DownloadIcon size={36} />
      </IconCircle>
      <h1 className="setup-title">Install IB Gateway</h1>
      <p className="setup-text wide">
        Portfolio Manager connects to your account through IB Gateway, IBKR’s official software. It runs quietly in the
        background, so you won’t need to open it yourself.
      </p>
      <div className="setup-box">
        {progress}
        {!installed && (!setup || setup.step === 'idle' || setup.step === 'failed') && status && (
          <button type="button" className="setup-button primary small" onClick={install}>
            {setup?.step === 'failed' ? 'Try Again' : 'Download IB Gateway (about 300 MB)'}
          </button>
        )}
        {failed && (
          <p className="setup-error" role="alert">
            <WarningIcon size={14} /> {failed}
          </p>
        )}
        <p className="setup-box-note">
          When IBKR’s installer opens, click Continue through each step, then come back here.
        </p>
      </div>
      <div className="setup-spacer" />
      <div className="setup-footer">
        <button type="button" className="setup-button" onClick={onBack}>
          Back
        </button>
        <div className="setup-spacer" />
        <button type="button" className="setup-button primary" disabled={!installed} onClick={onContinue}>
          Continue
        </button>
      </div>
    </div>
  )
}

export default InstallGateway
