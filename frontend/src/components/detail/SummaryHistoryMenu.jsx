import { useEffect, useRef, useState } from 'react'
import { formatSummaryTime } from '../../format.js'
import { ChevronIcon } from '../icons.jsx'

function label(item) {
  return item.price ? `${formatSummaryTime(item.created_at)} · ${item.price}` : formatSummaryTime(item.created_at)
}

// "History" pill next to Regenerate: pick a past summary to read, or tick two to compare
function SummaryHistoryMenu({ items, shownId, disabled, onView, onCompare }) {
  const [open, setOpen] = useState(false)
  const [picking, setPicking] = useState(false)
  const [picked, setPicked] = useState([])
  const menuRef = useRef(null)

  function close() {
    setOpen(false)
    setPicking(false)
    setPicked([])
  }

  // Close on Escape or a click anywhere outside the menu
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && close()
    const onClick = (e) => !menuRef.current?.contains(e.target) && close()
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  function toggle(id) {
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2)))
  }

  const tooFew = items.length < 2
  return (
    <div className="history-menu" ref={menuRef}>
      <button
        type="button"
        className="button compact"
        aria-haspopup="true"
        aria-expanded={open}
        disabled={disabled || tooFew}
        title={tooFew ? 'History appears once there are two or more summaries' : undefined}
        onClick={() => (open ? close() : setOpen(true))}
      >
        History <span className="history-chevron"><ChevronIcon size={10} /></span>
      </button>
      {open && (
        <div className="history-popover" role="menu">
          <p className="history-heading">{picking ? 'Pick two summaries to compare' : 'Past summaries'}</p>
          <ul className="history-list">
            {items.map((item, i) => (
              <li key={item.id}>
                {picking ? (
                  <label className="history-item">
                    <input type="checkbox" checked={picked.includes(item.id)} onChange={() => toggle(item.id)} />
                    <span className="num">{label(item)}</span>
                    {i === 0 && <span className="history-tag">Latest</span>}
                  </label>
                ) : (
                  <button
                    type="button"
                    role="menuitem"
                    className="history-item"
                    aria-current={item.id === shownId ? 'true' : undefined}
                    onClick={() => {
                      onView(i === 0 ? null : item.id)
                      close()
                    }}
                  >
                    <span className="num">{label(item)}</span>
                    {i === 0 && <span className="history-tag">Latest</span>}
                  </button>
                )}
              </li>
            ))}
          </ul>
          <div className="history-footer">
            {picking ? (
              <>
                <button type="button" className="link-button" onClick={() => setPicking(false)}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="button-primary compact"
                  disabled={picked.length !== 2}
                  onClick={() => {
                    onCompare(picked)
                    close()
                  }}
                >
                  Compare
                </button>
              </>
            ) : (
              <button type="button" className="link-button" onClick={() => setPicking(true)}>
                Compare two…
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default SummaryHistoryMenu
