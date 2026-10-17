import { formatTime } from '../lib/format.js'
import { WarningIcon } from './icons.jsx'

const REASONS = {
  logged_in_elsewhere: 'You signed in to IBKR somewhere else, so this app was signed out.',
  sign_in_again: 'IBKR asks you to sign in again once a week.',
  gateway_stopped: 'IB Gateway stopped.',
}

// Shown above the dashboard (Figma "Session ended") when the IBKR session ends; the figures
// below stay, dimmed, until it reconnects
function SessionBanner({ reason, lastUpdated, onReconnect }) {
  const figures = lastUpdated ? ` The figures below are from ${formatTime(lastUpdated)}.` : ''
  return (
    <div className="page-message">
      <div className="session-banner" role="alert">
        <WarningIcon size={20} />
        <div className="session-banner-text">
          <p className="session-banner-title">Your IBKR session ended</p>
          <p className="session-banner-detail">
            {REASONS[reason] ?? REASONS.gateway_stopped}
            {figures}
          </p>
        </div>
        <button type="button" className="setup-button primary" onClick={onReconnect}>
          Reconnect
        </button>
      </div>
    </div>
  )
}

export default SessionBanner
