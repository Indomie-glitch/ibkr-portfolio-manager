import { useId, useState } from 'react'
import { DisclosureIcon } from '../icons.jsx'

const STORAGE_KEY = 'detailSections'

// Open/closed state for every section, remembered across visits: { keyStats: true, news: false, ... }
function loadOpenState() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) ?? {}
  } catch {
    return {}
  }
}

function saveOpenState(id, open) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...loadOpenState(), [id]: open }))
  } catch {
    // storage blocked; the section still works, it just won't be remembered
  }
}

// A macOS-style collapsible section. The content only renders while open, so a closed
// section doesn't fetch its data at all.
function DisclosureSection({ id, title, note, actions, accent = false, children }) {
  const [open, setOpen] = useState(() => loadOpenState()[id] ?? true)
  const contentId = useId()

  function toggle() {
    setOpen(!open)
    saveOpenState(id, !open)
  }

  return (
    <section className="disclosure">
      <div className="disclosure-header">
        <button
          type="button"
          className={`disclosure-toggle ${accent ? 'accent' : ''}`}
          aria-expanded={open}
          aria-controls={contentId}
          onClick={toggle}
        >
          <span className={`disclosure-arrow ${open ? 'open' : ''}`}>
            <DisclosureIcon />
          </span>
          <h3>{title}</h3>
        </button>
        {note && <span className="disclosure-note">{note}</span>}
        {actions}
      </div>
      {open && (
        <div id={contentId} className="disclosure-content">
          {children}
        </div>
      )}
    </section>
  )
}

// Shown inside a section whose data couldn't be loaded; the rest of the page still works
export function SectionUnavailable({ what, reason }) {
  return (
    <p className="section-unavailable">
      {what} unavailable{reason ? ` · ${reason}` : ''}
    </p>
  )
}

export function SectionLoading({ lines = 3 }) {
  return (
    <div className="section-loading" aria-label="Loading">
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="skeleton-line" style={{ width: `${90 - i * 18}%` }} />
      ))}
    </div>
  )
}

export default DisclosureSection
