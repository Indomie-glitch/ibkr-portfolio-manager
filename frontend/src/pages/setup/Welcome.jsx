import { AppIcon } from './parts.jsx'

const WELCOME_STEPS = [
  ['Install IB Gateway', 'IBKR’s official connection software. You only install it once.'],
  ['Sign in with your IBKR account', 'You’ll approve the login on your phone in IBKR Mobile.'],
  ['Add an AI key (optional)', 'Turn on AI summaries any time in Settings.'],
]

function Welcome({ onStart }) {
  return (
    <div className="setup welcome">
      <AppIcon size={80} />
      <h1 className="setup-title">Welcome to Portfolio Manager</h1>
      <p className="setup-text wide">
        A clearer view of your Interactive Brokers portfolio, with AI summaries. Setup takes about five minutes.
      </p>
      <ol className="setup-steps">
        {WELCOME_STEPS.map(([title, caption], i) => (
          <li key={title}>
            <span className="setup-step-number">{i + 1}</span>
            <span>
              <span className="setup-step-title">{title}</span>
              <span className="setup-step-caption">{caption}</span>
            </span>
          </li>
        ))}
      </ol>
      <div className="setup-spacer" />
      <div className="setup-footer">
        <div className="setup-spacer" />
        <button type="button" className="setup-button primary" onClick={onStart}>
          Get Started
        </button>
      </div>
    </div>
  )
}

export default Welcome
