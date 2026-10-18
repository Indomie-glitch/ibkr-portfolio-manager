import { useEffect, useState } from 'react'
import { PhoneIcon, SpinnerIcon } from '../../components/icons.jsx'
import { IconCircle } from './parts.jsx'

const APPROVAL_SECONDS = 180 // IBKR's limit for approving in IBKR Mobile

function useCountdown(seconds) {
  const [started] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const left = Math.max(0, seconds - Math.floor((now - started) / 1000))
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`
}

function ApproveOnPhone({ username, onCancel }) {
  const left = useCountdown(APPROVAL_SECONDS)
  return (
    <div className="setup approve">
      <IconCircle>
        <PhoneIcon size={36} />
      </IconCircle>
      <h1 className="setup-title">Approve on your phone</h1>
      <p className="setup-text">Open IBKR Mobile and approve the login request for {username}.</p>
      <p className="setup-waiting" role="status">
        <SpinnerIcon size={14} /> Waiting for approval · {left}
      </p>
      <p className="setup-text faint">Didn’t get a notification? Open IBKR Mobile and check that IB Key is turned on.</p>
      <div className="setup-spacer" />
      <div className="setup-footer">
        <div className="setup-spacer" />
        <button type="button" className="setup-button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  )
}

export default ApproveOnPhone
