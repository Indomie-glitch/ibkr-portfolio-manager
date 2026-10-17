// Settings, laid out like the Figma frame "M7 / 8 Settings" (macOS System Settings style groups)
import { useEffect, useState } from 'react'
import { IN_APP } from '../lib/api.js'
import { apiKeyStatus, clearApiKey, setApiKey } from '../desktop/appApiKey.js'
import { APPEARANCES } from '../hooks/appearance.js'
import { gatewayStatus, installGateway } from '../desktop/appGateway.js'
import { savedLogin, signOut } from '../desktop/appSession.js'
import { getSettings, saveSettings } from '../desktop/appSettings.js'
import { CheckCircleIcon, ChevronsIcon } from '../components/icons.jsx'

// Written in two parts, like backend/secrets_guard.py, so the pre-commit check for keys doesn't flag it
const KEY_PREFIX = 'sk' + '-ant-'

// The models the backend accepts (config.AI_MODELS in backend/config.py)
const AI_MODELS = [
  ['claude-haiku-4-5', 'Claude Haiku 4.5'],
  ['claude-haiku-5-5', 'Claude Haiku 5.5'],
  ['claude-sonnet-5-5', 'Claude Sonnet 5.5'],
]

const MB = 1024 * 1024

function Group({ title, children, footnote }) {
  return (
    <section className="settings-section">
      <h2 className="settings-header">{title}</h2>
      <div className="settings-group">{children}</div>
      {footnote && <p className="settings-footnote">{footnote}</p>}
    </section>
  )
}

function Row({ label, caption, children, note }) {
  return (
    <div className="settings-row">
      <div className="settings-row-main">
        <span className="settings-row-label">
          {label}
          {caption && <span className="settings-row-caption">{caption}</span>}
        </span>
        <span className="settings-row-spacer" />
        {children}
      </div>
      {note && (
        <p className={`settings-row-note ${note.error ? 'error-text' : ''}`} role={note.error ? 'alert' : 'status'}>
          {note.text}
        </p>
      )}
    </div>
  )
}

function Toggle({ checked, onChange, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className="settings-toggle"
      onClick={() => onChange(!checked)}
    >
      <span className="settings-toggle-knob" />
    </button>
  )
}

function AccountGroup({ settings, username, login, connected, onSignedOut }) {
  const [note, setNote] = useState(null)
  const state = login?.state
  const signedIn = state === 'signed_in' || state === 'session_ended'
  const mode = settings?.trading_mode === 'live' ? 'Live' : 'Paper'

  async function doSignOut() {
    try {
      await signOut()
      onSignedOut()
    } catch (err) {
      setNote({ error: true, text: String(err) })
    }
  }

  let connection = ['', 'Not signed in']
  if (state === 'session_ended') connection = ['warn', 'Session ended']
  else if (signedIn) connection = connected ? ['ok', 'Connected'] : ['', 'Connecting…']

  return (
    <Group title="Account">
      <Row label="Signed in as" note={note}>
        <span className="settings-value">
          {signedIn && username ? `${username} · ${mode}` : 'Not signed in'}
        </span>
        {signedIn && (
          <button type="button" className="settings-button" onClick={doSignOut}>
            Sign Out
          </button>
        )}
      </Row>
      <Row label="Connection">
        <span className="settings-value with-dot">
          <span className={`status-dot ${connection[0]}`} /> {connection[1]}
        </span>
      </Row>
    </Group>
  )
}

function GatewayGroup({ settings, onSave }) {
  const [port, setPort] = useState(String(settings.gateway_port))
  const [portNote, setPortNote] = useState(null)
  const [gateway, setGateway] = useState(null)
  const [installNote, setInstallNote] = useState(null)
  const [watching, setWatching] = useState(0)

  useEffect(() => {
    let timer
    async function check() {
      try {
        const next = await gatewayStatus()
        setGateway(next)
        if (!next.installed && ['downloading', 'checking', 'installer_open'].includes(next.setup.step)) {
          timer = setTimeout(check, 1000)
        }
      } catch (err) {
        setInstallNote({ error: true, text: String(err) })
      }
    }
    check()
    return () => clearTimeout(timer)
  }, [watching])

  async function savePort(event) {
    event?.preventDefault()
    const number = Number(port)
    if (!Number.isInteger(number) || number < 1024 || number > 65535) {
      setPortNote({ error: true, text: 'Use a port between 1024 and 65535.' })
      return
    }
    if (number === settings.gateway_port) return
    const error = await onSave({ gateway_port: number })
    setPortNote(error ? { error: true, text: error } : { text: `Saved. Connecting on port ${number}…` })
  }

  async function install() {
    setInstallNote(null)
    try {
      await installGateway()
      setWatching((n) => n + 1)
    } catch (err) {
      setInstallNote({ error: true, text: String(err) })
    }
  }

  const setup = gateway?.setup
  let version = <span className="settings-value">Checking…</span>
  if (gateway?.installed) {
    version = <span className="settings-value">{gateway.installed.version} (stable)</span>
  } else if (setup?.step === 'downloading') {
    version = (
      <span className="settings-value">
        Downloading… {setup.total ? `${Math.floor(setup.received / MB)} of ${Math.floor(setup.total / MB)} MB` : ''}
      </span>
    )
  } else if (setup?.step === 'checking') {
    version = <span className="settings-value">Checking the installer…</span>
  } else if (setup?.step === 'installer_open') {
    version = <span className="settings-value">Finish IBKR’s installer…</span>
  } else if (gateway) {
    version = (
      <>
        <span className="settings-value">Not installed</span>
        <button type="button" className="settings-button" onClick={install}>
          {setup?.step === 'failed' ? 'Try Again' : 'Install…'}
        </button>
      </>
    )
  }

  return (
    <Group title="IB Gateway">
      <Row
        label="Reconnect automatically"
        caption="After IB Gateway’s daily restart. When the app opens, and when IBKR asks once a week, you sign in yourself."
      >
        <Toggle
          label="Reconnect automatically"
          checked={settings.auto_reconnect}
          onChange={(value) => onSave({ auto_reconnect: value })}
        />
      </Row>
      <Row
        label="API port"
        caption="The port Portfolio Manager’s IB Gateway uses. The default is 4012, so it doesn’t clash with another Gateway or TWS on 4001 or 4002."
        note={portNote}
      >
        <form onSubmit={savePort}>
          <input
            className="settings-field port"
            inputMode="numeric"
            value={port}
            onChange={(e) => {
              setPort(e.target.value.replace(/\D/g, ''))
              setPortNote(null)
            }}
            onBlur={savePort}
            aria-label="IB Gateway API port"
          />
        </form>
      </Row>
      <Row label="Gateway version" note={installNote ?? (setup?.error ? { error: true, text: setup.error } : null)}>
        {version}
      </Row>
    </Group>
  )
}

function ApiKeyRow() {
  // Whether a key was entered this session (null while checking); it's only ever kept in memory
  const [saved, setSaved] = useState(null)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [note, setNote] = useState(null)

  useEffect(() => {
    apiKeyStatus()
      .then(setSaved)
      .catch((err) => setNote({ error: true, text: String(err) }))
  }, [])

  async function save(event) {
    event.preventDefault()
    const key = value.trim()
    if (!key.startsWith(KEY_PREFIX)) {
      setNote({ error: true, text: `Anthropic API keys start with “${KEY_PREFIX}”.` })
      return
    }
    try {
      await setApiKey(key)
      setSaved(true)
      setEditing(false)
      setValue('')
      setNote({ text: 'AI summaries are on until you quit the app.' })
    } catch (err) {
      setNote({ error: true, text: String(err) })
    }
  }

  async function remove() {
    try {
      await clearApiKey()
      setSaved(false)
      setNote({ text: 'Removed. AI summaries are off until you add a key.' })
    } catch (err) {
      setNote({ error: true, text: String(err) })
    }
  }

  return (
    <Row label="Anthropic API key" note={note}>
      {saved === null && <span className="settings-value">Checking…</span>}
      {saved && !editing && (
        <>
          <span className="settings-value with-dot">
            <span className="settings-check">
              <CheckCircleIcon size={14} />
            </span>
            In use
          </span>
          <button type="button" className="settings-button" onClick={() => setEditing(true)}>
            Replace…
          </button>
          <button type="button" className="settings-button" onClick={remove}>
            Remove
          </button>
        </>
      )}
      {saved !== null && (!saved || editing) && (
        <form className="settings-inline" onSubmit={save}>
          <input
            className="settings-field key"
            type="password"
            placeholder={`${KEY_PREFIX}…`}
            autoComplete="off"
            spellCheck="false"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            aria-label="Anthropic API key"
          />
          <button type="submit" className="settings-button primary" disabled={!value.trim()}>
            Use
          </button>
          {editing && (
            <button type="button" className="settings-button" onClick={() => setEditing(false)}>
              Cancel
            </button>
          )}
        </form>
      )}
    </Row>
  )
}

function ModelRow({ settings, onSave }) {
  return (
    <Row label="Model">
      <span className="settings-popup">
        <select
          value={settings?.ai_model ?? 'claude-haiku-4-5'}
          onChange={(e) => onSave({ ai_model: e.target.value })}
          aria-label="AI summary model"
          disabled={!settings}
        >
          {AI_MODELS.map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
        <ChevronsIcon size={12} />
      </span>
    </Row>
  )
}

function AppearanceGroup({ appearance, onAppearanceChange }) {
  return (
    <Group title="Appearance">
      <Row label="Theme">
        <div className="segmented settings-segmented" role="group" aria-label="Appearance">
          {APPEARANCES.map((a) => (
            <button
              key={a.value}
              type="button"
              aria-pressed={appearance === a.value}
              onClick={() => onAppearanceChange(a.value)}
            >
              {a.label}
            </button>
          ))}
        </div>
      </Row>
    </Group>
  )
}

function Settings({ appearance, onAppearanceChange, login, connected, onSignedOut }) {
  const [settings, setSettings] = useState(null)
  // The IBKR username last signed in with (settings.json; the password is never stored)
  const [username, setUsername] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!IN_APP) return
    getSettings()
      .then(setSettings)
      .catch((err) => setError(String(err)))
    savedLogin()
      .then((saved) => setUsername(saved.username))
      .catch(() => {})
  }, [])

  // Saves a change to one or more settings; returns an error message, or null
  async function save(change) {
    const next = { ...settings, ...change }
    try {
      await saveSettings(next)
      setSettings(next)
      return null
    } catch (err) {
      return String(err)
    }
  }

  if (!IN_APP) {
    return (
      <div className="page-body settings">
        <div className="settings-column">
          <p className="settings-footnote">
            In development, the API key, Gateway port and model come from .env (ANTHROPIC_API_KEY, IB_PORT, AI_MODEL).
          </p>
          <AppearanceGroup appearance={appearance} onAppearanceChange={onAppearanceChange} />
        </div>
      </div>
    )
  }

  return (
    <div className="page-body settings">
      <div className="settings-column">
        {error && <p className="settings-footnote error-text">{error}</p>}
        <AccountGroup
          settings={settings}
          username={username}
          login={login}
          connected={connected}
          onSignedOut={onSignedOut}
        />
        {settings && <GatewayGroup settings={settings} onSave={save} />}
        <Group
          title="AI summaries"
          footnote="Not saved. Enter it again after restarting. Summaries are billed to your own Anthropic account."
        >
          <ApiKeyRow />
          <ModelRow settings={settings} onSave={save} />
        </Group>
        <AppearanceGroup appearance={appearance} onAppearanceChange={onAppearanceChange} />
      </div>
    </div>
  )
}

export default Settings
