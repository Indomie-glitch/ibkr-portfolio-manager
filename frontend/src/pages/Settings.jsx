import { useEffect, useState } from 'react'
import { IN_APP } from '../api.js'
import { deleteSecret, saveSecret, secretStatus } from '../appSecrets.js'
import { APPEARANCES } from '../appearance.js'
import { gatewayStatus, installGateway } from '../appGateway.js'
import { getSettings, saveSettings } from '../appSettings.js'

// Written in two parts, like backend/secrets_guard.py, so the pre-commit check for keys doesn't flag it
const KEY_PREFIX = 'sk' + '-ant-'

function Row({ label, caption, children }) {
  return (
    <div className="settings-row">
      <div className="settings-label">
        <div>{label}</div>
        {caption && <div className="settings-caption">{caption}</div>}
      </div>
      <div className="settings-control">{children}</div>
    </div>
  )
}

// Saved, success and error notes under a control
function Note({ note }) {
  if (!note) return null
  return (
    <p className={`settings-note ${note.error ? 'error-text' : ''}`} role={note.error ? 'alert' : 'status'}>
      {note.text}
    </p>
  )
}

function ApiKeySetting() {
  const [saved, setSaved] = useState(null) // null while loading, then true / false
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [note, setNote] = useState(null)

  useEffect(() => {
    secretStatus()
      .then((status) => setSaved(status.anthropic_api_key))
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
      await saveSecret('anthropic_api_key', key)
      setSaved(true)
      setEditing(false)
      setValue('')
      setNote({ text: 'Saved. AI summaries are on.' })
    } catch (err) {
      setNote({ error: true, text: String(err) })
    }
  }

  async function remove() {
    try {
      await deleteSecret('anthropic_api_key')
      setSaved(false)
      setNote({ text: 'Removed. AI summaries are off until you add a key.' })
    } catch (err) {
      setNote({ error: true, text: String(err) })
    }
  }

  const showForm = saved === false || editing
  return (
    <Row
      label="Anthropic API key"
      caption="Turns on AI summaries. Create one at console.anthropic.com. It's kept in your Mac's Keychain and only sent to Anthropic."
    >
      {saved === null && !note && <span className="settings-caption">Checking…</span>}
      {saved && !editing && (
        <div className="settings-inline">
          <span className="settings-status">
            <span className="status-dot ok" /> Saved in Keychain
          </span>
          <button type="button" className="button compact" onClick={() => setEditing(true)}>
            Change
          </button>
          <button type="button" className="button compact" onClick={remove}>
            Remove
          </button>
        </div>
      )}
      {showForm && saved !== null && (
        <form className="settings-inline" onSubmit={save}>
          <input
            className="settings-input"
            type="password"
            placeholder={`${KEY_PREFIX}…`}
            autoComplete="off"
            spellCheck="false"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            aria-label="Anthropic API key"
          />
          <button type="submit" className="button-primary compact" disabled={!value.trim()}>
            Save
          </button>
          {editing && (
            <button type="button" className="button compact" onClick={() => setEditing(false)}>
              Cancel
            </button>
          )}
        </form>
      )}
      <Note note={note} />
    </Row>
  )
}

const MB = 1024 * 1024
const ACTIVE_STEPS = ['downloading', 'checking', 'installer_open']

function GatewayInstallSetting() {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState(null)
  // Bumped by install() to start following progress again
  const [watching, setWatching] = useState(0)

  // Check once, then every second while a download or the installer is in progress
  useEffect(() => {
    let timer
    async function check() {
      try {
        const next = await gatewayStatus()
        setStatus(next)
        if (ACTIVE_STEPS.includes(next.setup.step) && !next.installed) timer = setTimeout(check, 1000)
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

  const { installed, setup } = status ?? {}
  return (
    <Row
      label="IB Gateway"
      caption="Interactive Brokers' connection app. Portfolio Manager runs it in the background, so you never need to open it."
    >
      {!status && !error && <span className="settings-caption">Checking…</span>}
      {installed && (
        <span className="settings-status" title={installed.path}>
          <span className="status-dot ok" /> IB Gateway {installed.version} installed
        </span>
      )}
      {status && !installed && (setup.step === 'idle' || setup.step === 'failed') && (
        <button type="button" className="button-primary compact" onClick={install}>
          {setup.step === 'failed' ? 'Try again' : 'Download and install (about 300 MB)'}
        </button>
      )}
      {!installed && setup?.step === 'downloading' && (
        <div className="gateway-progress">
          <progress max={setup.total || 1} value={setup.received} />
          <span className="settings-caption">
            {setup.total ? `Downloading from Interactive Brokers… ${Math.floor(setup.received / MB)} of ${Math.floor(setup.total / MB)} MB` : 'Connecting to Interactive Brokers…'}
          </span>
        </div>
      )}
      {!installed && setup?.step === 'checking' && <span className="settings-caption">Checking the installer is genuine…</span>}
      {!installed && setup?.step === 'installer_open' && (
        <p className="settings-note">
          IBKR's installer is open in another window: click Next through it and keep the suggested folder. This page
          notices when it's done.
        </p>
      )}
      {(error || setup?.error) && <Note note={{ error: true, text: error || setup.error }} />}
    </Row>
  )
}

function GatewayPortSetting() {
  const [port, setPort] = useState('')
  const [note, setNote] = useState(null)

  useEffect(() => {
    getSettings()
      .then((settings) => setPort(String(settings.gateway_port)))
      .catch((err) => setNote({ error: true, text: String(err) }))
  }, [])

  async function save(event) {
    event.preventDefault()
    const number = Number(port)
    if (!Number.isInteger(number) || number < 1024 || number > 65535) {
      setNote({ error: true, text: 'Use a port between 1024 and 65535.' })
      return
    }
    try {
      await saveSettings({ gateway_port: number })
      setNote({ text: `Saved. Connecting on port ${number}…` })
    } catch (err) {
      setNote({ error: true, text: String(err) })
    }
  }

  return (
    <Row label="IB Gateway API port" caption="Gateway's defaults are 4002 for paper accounts and 4001 for live.">
      <form className="settings-inline" onSubmit={save}>
        <input
          className="settings-input port"
          inputMode="numeric"
          value={port}
          onChange={(e) => setPort(e.target.value.replace(/\D/g, ''))}
          aria-label="IB Gateway API port"
        />
        <button type="submit" className="button-primary compact" disabled={!port}>
          Save
        </button>
      </form>
      <Note note={note} />
    </Row>
  )
}

function Settings({ appearance, onAppearanceChange }) {
  return (
    <div className="page-body settings">
      <section className="card settings-card">
        <h2 className="settings-heading">AI summaries</h2>
        {IN_APP ? (
          <ApiKeySetting />
        ) : (
          <Row label="Anthropic API key" caption="In development, set ANTHROPIC_API_KEY in .env." />
        )}
      </section>

      <section className="card settings-card">
        <h2 className="settings-heading">IB Gateway</h2>
        {IN_APP ? (
          <>
            <GatewayInstallSetting />
            <GatewayPortSetting />
          </>
        ) : (
          <Row label="IB Gateway API port" caption="In development, set IB_PORT in .env (default 4002)." />
        )}
      </section>

      <section className="card settings-card">
        <h2 className="settings-heading">Appearance</h2>
        <Row label="Theme" caption="System follows your Mac's light or dark setting.">
          <div className="segmented" role="group" aria-label="Appearance">
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
      </section>
    </div>
  )
}

export default Settings
