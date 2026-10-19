import { useContext, useEffect, useRef, useState } from 'react'
import { RefreshContext, useFetch } from '../hooks/useFetch.js'
import { loadRisk } from '../lib/riskData.js'
import { PANELS, TILE_ROWS } from '../lib/riskLayout.js'
import { DEFAULT_PERIOD, PERIODS, asOfText, calculatedNote, extraNotes, leftOutNote } from '../lib/riskFormat.js'
import ConcentrationPanel from '../components/risk/ConcentrationPanel.jsx'
import ExposurePanel from '../components/risk/ExposurePanel.jsx'
import RiskPanel from '../components/risk/RiskPanel.jsx'
import RiskTile from '../components/risk/RiskTile.jsx'
import VolatilityPanel from '../components/risk/VolatilityPanel.jsx'

const PERIOD_KEY = 'riskPeriod'
// The backend keeps a result for 10 minutes and prices are daily, so a refresh only asks again after that
const STALE_MS = 10 * 60_000

// Each panel's body and right-hand label, added by the issue that builds it
const BODIES = {
  concentration: ConcentrationPanel,
  exposure: ExposurePanel,
  volatility: VolatilityPanel,
}
const LABELS = {
  concentration: () => 'Money vs risk',
  exposure: () => '% of holdings',
  volatility: () => 'Per holding',
}

function savedPeriod() {
  try {
    const saved = localStorage.getItem(PERIOD_KEY)
    return PERIODS.includes(saved) ? saved : DEFAULT_PERIOD
  } catch {
    return DEFAULT_PERIOD
  }
}

function CommandBar({ period, onPeriod, meta }) {
  return (
    <div className="risk-command-bar">
      <span className="risk-bar-label" id="risk-period-label">
        Period
      </span>
      <div className="risk-period-keys" role="group" aria-labelledby="risk-period-label">
        {PERIODS.map((p) => (
          <button
            key={p}
            type="button"
            className={`risk-period-key ${p === period ? 'active' : ''}`}
            aria-pressed={p === period}
            onClick={() => onPeriod(p)}
          >
            {p}
          </button>
        ))}
      </div>
      <span className="risk-bar-label">Benchmarks</span>
      <span className="risk-bar-value">ASX 200 · S&amp;P 500</span>
      <span className="spacer" />
      {meta && <span className="risk-as-of">{asOfText(meta)}</span>}
    </div>
  )
}

function DataNotes({ meta }) {
  return (
    <footer className="risk-data-notes">
      <span>{calculatedNote(meta)}</span>
      <span>{leftOutNote(meta)}</span>
      {extraNotes(meta).map((note) => (
        <span key={note} className="risk-data-extra">
          {note}
        </span>
      ))}
    </footer>
  )
}

// The Risk page (Milestone 8, Figma Risk / V5A): command bar, two rows of headline tiles, twelve
// panels in two columns (one column on narrow windows) and the data notes. onMeta passes
// { meta, failed } up for the toolbar subtitle.
export default function Risk({ onMeta }) {
  const [period, setPeriod] = useState(savedPeriod)
  const [version, setVersion] = useState(0)
  // When the shown numbers arrived
  const loadedAt = useRef(0)
  const refresh = useContext(RefreshContext)
  const { data, error } = useFetch(() => loadRisk(period, version), `${period}:${version}`)
  const meta = data?.meta ?? null

  useEffect(() => {
    if (data) loadedAt.current = Date.now()
  }, [data])

  // The app's Refresh button and minute timer: fresh numbers once the old ones are 10 minutes old
  const firstRefresh = useRef(refresh)
  useEffect(() => {
    if (refresh === firstRefresh.current || !loadedAt.current || Date.now() - loadedAt.current < STALE_MS) return
    // oxlint-disable-next-line react/set-state-in-effect
    setVersion((v) => v + 1)
  }, [refresh])

  const failed = Boolean(error)
  useEffect(() => {
    onMeta?.({ meta, failed })
  }, [meta, failed, onMeta])

  function choosePeriod(p) {
    setPeriod(p)
    try {
      localStorage.setItem(PERIOD_KEY, p)
    } catch {
      // not remembered; the page still works
    }
  }

  const column = (side) =>
    PANELS.filter((p) => p.column === side).map((panel) => (
      <RiskPanel
        key={panel.id}
        panel={panel}
        Body={BODIES[panel.id]}
        label={LABELS[panel.id]}
        period={period}
        version={version}
      />
    ))

  return (
    <div className="page-body risk-page">
      <CommandBar period={period} onPeriod={choosePeriod} meta={meta} />
      {error && (
        <div className="risk-page-error" role="alert">
          <strong>Couldn’t calculate the risk figures.</strong> {error}
        </div>
      )}
      {TILE_ROWS.map((row, i) => (
        <div className="risk-tiles" key={i}>
          {row.map((tile) => (
            <RiskTile key={tile.id} tile={tile} period={period} version={version} />
          ))}
        </div>
      ))}
      <div className="risk-columns">
        <div className="risk-column">{column('left')}</div>
        <div className="risk-column">{column('right')}</div>
      </div>
      {meta && <DataNotes meta={meta} />}
    </div>
  )
}
