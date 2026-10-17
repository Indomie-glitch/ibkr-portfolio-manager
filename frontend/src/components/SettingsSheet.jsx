import { useEffect, useRef } from 'react'
import Settings from '../pages/Settings.jsx'
import { CloseIcon } from './icons.jsx'

// Settings as a floating sheet over the current page (Figma "Overview / Light / Settings overlay",
// node 45:389): a frosted panel with a close button, the title and Done, over a dimmed window.
// Closes with Done, ×, Escape or a click outside the panel.
function SettingsSheet({ onClose, ...settingsProps }) {
  const doneRef = useRef(null)

  useEffect(() => {
    const previous = document.activeElement
    doneRef.current?.focus()
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      previous?.focus?.() // back to whatever opened it
    }
  }, [onClose])

  return (
    <div className="settings-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="settings-sheet" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div className="settings-sheet-header">
          <button type="button" className="settings-sheet-close" aria-label="Close" onClick={onClose}>
            <CloseIcon />
          </button>
          <h2 id="settings-title" className="settings-sheet-title">
            Settings
          </h2>
          <div className="spacer" />
          <button ref={doneRef} type="button" className="settings-sheet-done" onClick={onClose}>
            Done
          </button>
        </div>
        <div className="settings-sheet-body">
          <Settings {...settingsProps} />
        </div>
      </div>
    </div>
  )
}

export default SettingsSheet
