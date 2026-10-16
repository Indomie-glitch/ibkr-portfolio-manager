import { IN_APP } from '../api.js'
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
  // The Mac app after signing in, while the backend connects to Gateway
  connecting: {
    title: 'Connecting to Interactive Brokers…',
    body: 'Signed in. Your account appears in a few seconds.',
    neutral: true,
  },
  stopped: {
    title: 'Portfolio Manager’s background service isn’t running',
    body: 'Quit and reopen the app. If this keeps happening, the log is in ~/Library/Logs/com.indomieglitch.portfoliomanager/backend.log',
  },
}

// In the app, after this long "Connecting…" turns into an explanation of what's wrong
const EXPLAIN_AFTER_S = 20
const LOG = '~/Library/Logs/com.indomieglitch.portfoliomanager/backend.log'

// Why the app's backend can't reach IB Gateway (the problem /health reports, see ib_connection.py)
function problemMessage({ problem, port, client_id: clientId }) {
  switch (problem) {
    case 'client_id_in_use':
      return {
        title: 'Another program is using IB Gateway’s connection',
        body: `Something else on this Mac is connected to IB Gateway with the same client ID. Portfolio Manager is trying other IDs (now ${clientId}). If this doesn’t clear, quit the other program or reopen Portfolio Manager.`,
      }
    case 'refused':
      return {
        title: 'IB Gateway isn’t accepting connections',
        body: `Nothing answered on port ${port}. Check the API port in Settings, or sign out and sign in again.`,
      }
    case 'timeout':
      return {
        title: 'IB Gateway isn’t answering',
        body: `Port ${port} answered, but IB Gateway didn’t respond. If it’s still starting it will connect by itself; otherwise quit and reopen Portfolio Manager.`,
      }
    default:
      return {
        title: 'Couldn’t connect to IB Gateway',
        body: `Quit and reopen Portfolio Manager. If it keeps happening, the log is in ${LOG}`,
      }
  }
}

function ConnectionMessage({ state, health, lastUpdated }) {
  let message = MESSAGES[IN_APP && state === 'disconnected' ? 'connecting' : state]
  if (IN_APP && state === 'disconnected' && health?.problem && health.problem_for_s >= EXPLAIN_AFTER_S) {
    message = problemMessage(health)
  }
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
