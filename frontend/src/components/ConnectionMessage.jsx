import { formatTime } from '../format.js'

const MESSAGES = {
  disconnected: {
    title: 'IB Gateway is not connected',
    body: 'Start IB Gateway and log in to your paper account. The app reconnects on its own, so there is no need to reload.',
  },
  offline: {
    title: 'Can’t reach the backend',
    body: 'Start the API server, then this page will pick it up automatically:',
    command: 'cd backend && source venv/bin/activate && uvicorn main:app --reload',
  },
  // The Mac app runs its own backend
  starting: {
    title: 'Starting Portfolio Manager…',
    body: 'This takes a few seconds, a little longer the first time after installing.',
    neutral: true,
  },
  stopped: {
    title: 'Portfolio Manager’s background service isn’t running',
    body: 'Quit and reopen the app. If this keeps happening, the log is in ~/Library/Logs/com.indomieglitch.portfoliomanager/backend.log',
  },
}

function ConnectionMessage({ state, lastUpdated }) {
  const message = MESSAGES[state]
  return (
    <div className="connection-message" role="alert">
      <div className="connection-card">
        <span className={`status-dot ${message.neutral ? '' : 'bad'}`} />
        <h2>{message.title}</h2>
        <p>{message.body}</p>
        {message.command && <code>{message.command}</code>}
        <p className="connection-retry">
          <span className="pulse" /> {message.neutral ? 'Waiting for it to answer' : 'Checking again every few seconds'}
          {lastUpdated && ` · last data from ${formatTime(lastUpdated)}`}
        </p>
      </div>
    </div>
  )
}

export default ConnectionMessage
