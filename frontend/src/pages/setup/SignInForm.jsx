import { useState } from 'react'
import { InfoIcon, SpinnerIcon, WarningIcon } from '../../components/icons.jsx'
import { AppIcon } from './parts.jsx'

const ERROR_TEXT = {
  wrong_password: 'Incorrect username or password.',
  too_many_attempts: 'Too many attempts. Wait a few minutes, then try again.',
}

// Why a second IBKR username helps (README "Using a second IBKR username" says the same)
function SecondUsernameTip() {
  const [open, setOpen] = useState(false)
  return (
    <div className="setup-tip">
      <InfoIcon size={16} />
      <div>
        <p>
          Tip: use a second IBKR username for this app, so you stay signed in to IBKR Mobile on your phone.{' '}
          <button type="button" className="setup-tip-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? 'Hide' : 'Why?'}
          </button>
        </p>
        {open && (
          <p className="setup-tip-more">
            Each IBKR username can be signed in in only one place, so using the same one here signs you out of IBKR
            Mobile. Add a second username in Client Portal under Settings › Users &amp; Access Rights. Paper accounts
            already have their own username.
          </p>
        )}
      </div>
    </div>
  )
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
      <p className="setup-text small">Your password goes straight to IB Gateway and isn’t saved.</p>

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
        <SecondUsernameTip />
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

export default SignInForm
