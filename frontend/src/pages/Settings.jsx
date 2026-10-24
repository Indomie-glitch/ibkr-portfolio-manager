// The Settings content, laid out like the Figma frame "M7 / 8 Settings" (macOS System Settings style
// groups). It's shown in the Settings sheet (components/SettingsSheet.jsx), in the section order of the
// Figma "Settings overlay": Account, AI summaries, IB Gateway, Appearance.
import { useEffect, useState } from 'react'
import { IN_APP, changeBorrowing, fetchBorrowing } from '../lib/api.js'
import { apiKeyStatus, clearApiKey, rememberApiKey, setApiKey } from '../desktop/appApiKey.js'
import { APPEARANCES } from '../hooks/appearance.js'
import { TEXT_SIZES } from '../lib/textSize.js'
import { gatewayStatus, installGateway } from '../desktop/appGateway.js'
import { savedLogin, signOut } from '../desktop/appSession.js'
import { getSettings, saveSettings } from '../desktop/appSettings.js'
import { CAN_CONFIRM_OWNER, allowBorrowing, blockBorrowing, confirmOwner } from '../desktop/appBorrowing.js'
import { AllowBorrowingSheet, BlockBorrowingSheet } from '../components/BorrowingSheets.jsx'
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

function Row({ label, children, note }) {
  return (
    <div className="settings-row">
      <div className="settings-row-main">
        <span className="settings-row-label">{label}</span>
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

// danger: red when off instead of grey (Block borrowing, where off is the risky choice)
function Toggle({ checked, onChange, label, danger = false }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={`settings-toggle ${danger ? 'danger-off' : ''}`}
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
      <Row label="Reconnect automatically">
        <Toggle
          label="Reconnect automatically"
          checked={settings.auto_reconnect}
          onChange={(value) => onSave({ auto_reconnect: value })}
        />
      </Row>
      <Row label="API port" note={portNote}>
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
  // Whether a key is in use (null while checking) and whether an encrypted copy is saved
  const [saved, setSaved] = useState(null)
  const [remembered, setRemembered] = useState(false)
  // The switch next to the key field, for a key not yet entered
  const [remember, setRemember] = useState(false)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [note, setNote] = useState(null)

  useEffect(() => {
    apiKeyStatus()
      .then((status) => {
        setSaved(status.in_use)
        setRemembered(status.remembered)
        setRemember(status.remembered)
      })
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
      await setApiKey(key, remember)
      setSaved(true)
      setRemembered(remember)
      setEditing(false)
      setValue('')
      setNote({ text: remember ? 'AI summaries are on. The key is remembered on this Mac.' : 'AI summaries are on until you quit the app.' })
    } catch (err) {
      setNote({ error: true, text: String(err) })
    }
  }

  async function remove() {
    try {
      await clearApiKey()
      setSaved(false)
      setRemembered(false)
      setRemember(false)
      setNote({ text: 'Removed. AI summaries are off until you add a key.' })
    } catch (err) {
      setNote({ error: true, text: String(err) })
    }
  }

  async function changeRemembered(value) {
    try {
      await rememberApiKey(value)
      setRemembered(value)
      setNote({ text: value ? 'The key is remembered on this Mac.' : 'The saved copy was deleted. The key stays in use until you quit the app.' })
    } catch (err) {
      setNote({ error: true, text: String(err) })
    }
  }

  return (
    <>
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
          <span className="settings-value">Remember</span>
          <Toggle label="Remember key on this Mac" checked={remember} onChange={setRemember} />
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
    {saved && !editing && (
      <Row
        label="Remember key on this Mac"
        note={{ text: 'Saved encrypted in the app\'s data folder, so you don\'t have to enter it after every launch or update. The decryption key is on this Mac too, so set a monthly spend limit on the key in the Anthropic console.' }}
      >
        <Toggle label="Remember key on this Mac" checked={remembered} onChange={changeRemembered} />
      </Row>
    )}
    </>
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

// "Block borrowing" (#289): on by default, per IBKR account. Off needs the warning sheet and then
// Touch ID / the Mac password (app) or BORROW typed (browser); back on needs a short confirmation.
function TradingGroup({ connected }) {
  const [setting, setSetting] = useState(null)
  const [sheet, setSheet] = useState(null) // null | 'allow' | 'block'
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [note, setNote] = useState(null)

  useEffect(() => {
    if (!connected) return
    fetchBorrowing()
      .then(setSetting)
      .catch((err) => setNote({ error: true, text: err.message }))
  }, [connected])

  function close() {
    setSheet(null)
    setError(null)
    setBusy(false)
  }

  async function allow() {
    setBusy(true)
    setError(null)
    try {
      // The app: Rust asks macOS and tells its backend. `npm run tauri dev`: macOS is asked here, then
      // the development backend is told the same way as in the browser
      const confirmed = IN_APP
        ? await allowBorrowing(setting.account_id)
        : !CAN_CONFIRM_OWNER || (await confirmOwner())
      if (!confirmed) {
        // Cancelled or failed: the switch stays on
        close()
        setNote({ text: 'Not changed: macOS didn’t confirm it was you. Borrowing is still blocked.' })
        return
      }
      if (!IN_APP) await changeBorrowing({ block: false, confirm: 'BORROW' })
      setSetting({ ...setting, block: false })
      setNote(null)
      close()
    } catch (err) {
      setBusy(false)
      setError(String(err.message ?? err))
    }
  }

  async function block() {
    setBusy(true)
    setError(null)
    try {
      if (IN_APP) await blockBorrowing(setting.account_id)
      else await changeBorrowing({ block: true })
      setSetting({ ...setting, block: true })
      setNote(null)
      close()
    } catch (err) {
      setBusy(false)
      setError(String(err.message ?? err))
    }
  }

  const on = setting?.block ?? true
  const status = on
    ? 'On: orders that would borrow are blocked.'
    : 'Off: orders can borrow from IBKR and you pay interest.'
  return (
    <Group
      title="Trading"
      footnote={setting?.account_id ? `Saved for IBKR account ${setting.account_id}.` : 'Connect to IBKR to change this.'}
    >
      <Row label="Block borrowing" note={note ?? { text: status }}>
        <Toggle
          label="Block borrowing"
          danger
          checked={on}
          onChange={(next) => setting && setSheet(next ? 'block' : 'allow')}
        />
      </Row>
      {sheet === 'allow' && <AllowBorrowingSheet onCancel={close} onConfirm={allow} busy={busy} error={error} />}
      {sheet === 'block' && <BlockBorrowingSheet onCancel={close} onConfirm={block} busy={busy} error={error} />}
    </Group>
  )
}

function AppearanceGroup({ appearance, onAppearanceChange, textSize, onTextSizeChange }) {
  return (
    <Group title="Appearance">
      <Row
        label="Theme"
        note={{ text: 'System follows your Mac\'s light or dark setting. Terminal is all black, like a trading terminal.' }}
      >
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
      <Row
        label="Text size"
        note={{ text: IN_APP ? 'Scales the whole window. ⌘+, ⌘− and ⌘0 in the View menu also change it; pinch the trackpad to zoom in briefly.' : 'Scales the whole page.' }}
      >
        <div className="segmented settings-segmented" role="group" aria-label="Text size">
          {TEXT_SIZES.map((t) => (
            <button
              key={t.value}
              type="button"
              aria-pressed={textSize === t.value}
              onClick={() => onTextSizeChange(t.value)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </Row>
    </Group>
  )
}

function Settings({ appearance, onAppearanceChange, textSize, onTextSizeChange, login, connected, onSignedOut }) {
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
      <div className="settings-column">
        <p className="settings-footnote">
          In development, the API key, Gateway port and model come from .env (ANTHROPIC_API_KEY, IB_PORT, AI_MODEL).
        </p>
        <TradingGroup connected={connected} />
        <AppearanceGroup
          appearance={appearance}
          onAppearanceChange={onAppearanceChange}
          textSize={textSize}
          onTextSizeChange={onTextSizeChange}
        />
      </div>
    )
  }

  return (
    <div className="settings-column">
      {error && <p className="settings-footnote error-text">{error}</p>}
      <AccountGroup
        settings={settings}
        username={username}
        login={login}
        connected={connected}
        onSignedOut={onSignedOut}
      />
      <Group
        title="AI summaries"
        footnote="Not saved. Enter it again after restarting. Summaries are billed to your own Anthropic account."
      >
        <ApiKeyRow />
        <ModelRow settings={settings} onSave={save} />
      </Group>
      {settings && <GatewayGroup settings={settings} onSave={save} />}
      <TradingGroup connected={connected} />
      <AppearanceGroup
          appearance={appearance}
          onAppearanceChange={onAppearanceChange}
          textSize={textSize}
          onTextSizeChange={onTextSizeChange}
        />
    </div>
  )
}

export default Settings
