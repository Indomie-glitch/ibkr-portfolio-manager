import { WarningIcon } from '../../components/icons.jsx'
import { IconCircle } from './parts.jsx'

function LoginNotApproved({ onBack, onTryAgain }) {
  return (
    <div className="setup approve">
      <IconCircle tone="warning">
        <WarningIcon size={36} />
      </IconCircle>
      <h1 className="setup-title">Login wasn’t approved</h1>
      <p className="setup-text">The request in IBKR Mobile was declined, or it timed out after 3 minutes.</p>
      <p className="setup-text faint">Tap Try Again, then approve the new request on your phone within 3 minutes.</p>
      <div className="setup-spacer" />
      <div className="setup-footer">
        <button type="button" className="setup-button" onClick={onBack}>
          Back
        </button>
        <div className="setup-spacer" />
        <button type="button" className="setup-button primary" onClick={onTryAgain}>
          Try Again
        </button>
      </div>
    </div>
  )
}

export default LoginNotApproved
