// The Mac app's setup and sign-in screens (Figma page "Desktop app (M7)"): Startup, Welcome,
// Install IB Gateway, Sign in (and its error state), Approve on phone, Login not approved.
import { useEffect, useState } from 'react'
import { gatewayStatus, installGateway } from '../appGateway.js'
import { cancelSignIn, savedLogin, signIn } from '../appSession.js'
import { sizeWindowFor } from '../appWindow.js'
import {
  AppGlyph,
  CheckCircleIcon,
  DownloadIcon,
  InfoIcon,
  PhoneIcon,
  SpinnerIcon,
  WarningIcon,
} from '../components/icons.jsx'

const MB = 1024 * 1024
const APPROVAL_SECONDS = 180 // IBKR's limit for approving in IBKR Mobile

function AppIcon({ size }) {
  return (
    <div className={`app-icon size-${size}`}>
      <AppGlyph size={size} />
    </div>
  )
}

function IconCircle({ tone = 'accent', children }) {
  return <div className={`icon-circle ${tone}`}>{children}</div>
}

// "Starting up…" while the app's backend starts, or "Signing in…" when the app signs in by itself
export function Startup({ label = 'Starting up…' }) {
  useEffect(() => {
    sizeWindowFor('startup')
  }, [])
  return (
    <div className="setup startup">
      <AppIcon size={72} />
      <p className="startup-name">Portfolio Manager</p>
      <p className="startup-status">
        <SpinnerIcon size={16} /> {label}
      </p>
    </div>
  )
}

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

const ERROR_TEXT = {
  wrong_password: 'Incorrect username or password.',
  too_many_attempts: 'Too many attempts. Wait a few minutes, then try again.',
}

function SignInForm({ form, setForm, busy, login, onSubmit }) {
  let error = null
  if (login?.state === 'wrong_password') {
    error = login.too_many_attempts ? ERROR_TEXT.too_many_attempts : ERROR_TEXT.wrong_password
  } else if (login?.state === 'error') {
    error = login.message
  } else if (form.error) {
    error = form.error
  }
  const passwordWrong = login?.state === 'wrong_password'
  const update = (change) => setForm((f) => ({ ...f, ...change, error: null }))

  return (
    <form
      className="setup signin"
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
      }}
    >
      <p className="setup-step-of">Step 2 of 2</p>
      <AppIcon size={56} />
      <h1 className="setup-title small">Sign in to Interactive Brokers</h1>
      <p className="setup-text small">Your password is saved in your Mac’s Keychain and never leaves this Mac.</p>

      <div className="setup-form">
        <div className="setup-field">
          <span className="setup-label" id="account-label">
            Account
          </span>
          <div className="segmented setup-segmented" role="group" aria-labelledby="account-label">
            {[
              ['live', 'Live'],
              ['paper', 'Paper'],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={form.mode === value}
                onClick={() => update({ mode: value })}
                disabled={busy}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <label className="setup-field">
          <span className="setup-label">Username</span>
          <input
            className="setup-input"
            value={form.username}
            onChange={(e) => update({ username: e.target.value })}
            autoComplete="username"
            spellCheck="false"
            autoCapitalize="off"
            disabled={busy}
            autoFocus={!form.username}
          />
        </label>
        <label className="setup-field">
          <span className="setup-label">Password</span>
          <input
            className={`setup-input ${passwordWrong ? 'invalid' : ''}`}
            type="password"
            value={form.password}
            onChange={(e) => update({ password: e.target.value })}
            autoComplete="current-password"
            disabled={busy}
            autoFocus={Boolean(form.username)}
            aria-invalid={passwordWrong}
          />
        </label>
        {error && (
          <p className="setup-error" role="alert">
            <WarningIcon size={14} /> {error}
          </p>
        )}
        <label className="setup-checkbox">
          <input
            type="checkbox"
            checked={form.remember}
            onChange={(e) => update({ remember: e.target.checked })}
            disabled={busy}
          />
          Remember password in Keychain
        </label>
        <div className="setup-tip">
          <InfoIcon size={16} />
          <p>Tip: use a second IBKR username for this app, so you stay signed in to IBKR Mobile on your phone.</p>
        </div>
      </div>

      <div className="setup-spacer" />
      <button type="submit" className="setup-button primary full" disabled={busy}>
        {busy ? (
          <>
            <SpinnerIcon size={14} /> Signing In…
          </>
        ) : (
          'Sign In'
        )}
      </button>
    </form>
  )
}

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

// The setup flow, shown until the app is signed in to IBKR. `login` is the state from useLogin;
// `onChange` asks it to check again right away.
function Setup({ login, onChange }) {
  // null while loading; then 'welcome' (first run), 'install' or 'signin'
  const [step, setStep] = useState(null)
  const [form, setForm] = useState({ mode: 'paper', username: '', password: '', remember: true, error: null })
  // True once this screen started a sign-in, so its progress shows on the form (an automatic
  // sign-in at launch shows the startup screen instead)
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    Promise.all([savedLogin(), gatewayStatus()])
      .then(([saved, gateway]) => {
        setForm((f) => ({ ...f, username: saved.username ?? '', mode: saved.mode ?? 'paper' }))
        if (!saved.username) setStep('welcome')
        else setStep(gateway.installed ? 'signin' : 'install')
      })
      .catch(() => setStep('signin'))
  }, [])

  const state = login?.state
  const busy = submitted && (state === 'starting' || state === 'signing_in')

  let screen = step
  if (state === 'awaiting_approval') screen = 'approve'
  else if (state === 'not_approved') screen = 'not_approved'
  else if (!submitted && (state === 'starting' || state === 'signing_in')) screen = 'auto'

  useEffect(() => {
    if (screen === 'welcome' || screen === 'install') sizeWindowFor(screen)
    else if (screen && screen !== 'auto') sizeWindowFor('signin')
  }, [screen])

  async function submit() {
    if (!form.username.trim() || !form.password) {
      setForm((f) => ({ ...f, error: 'Enter your IBKR username and password.' }))
      return
    }
    setSubmitted(true)
    try {
      await signIn(form)
      onChange()
    } catch (err) {
      setForm((f) => ({ ...f, error: String(err) }))
    }
  }

  async function backToForm() {
    await cancelSignIn()
    setSubmitted(false)
    setStep('signin')
    onChange()
  }

  if (screen === null) return <Startup />
  if (screen === 'auto') return <Startup label="Signing in to IBKR…" />
  if (screen === 'welcome') return <Welcome onStart={() => setStep('install')} />
  if (screen === 'install') return <InstallGateway onBack={() => setStep('welcome')} onContinue={() => setStep('signin')} />
  if (screen === 'approve') return <ApproveOnPhone username={form.username} onCancel={backToForm} />
  if (screen === 'not_approved') return <LoginNotApproved onBack={backToForm} onTryAgain={submit} />
  return <SignInForm form={form} setForm={setForm} busy={busy} login={login} onSubmit={submit} />
}

export default Setup
