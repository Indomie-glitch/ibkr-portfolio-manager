import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { RiskInfoIcon } from '../icons.jsx'

const WIDTH = 340
const GAP = 6
const MARGIN = 12
const HOVER_DELAY_MS = 120

// Where the popover goes: below the button, its left edge at the button's, moved left to stay in
// the window, and above the button when there's no room below
function placement(button, height) {
  const rect = button.getBoundingClientRect()
  const left = Math.max(MARGIN, Math.min(rect.left, window.innerWidth - WIDTH - MARGIN))
  const below = rect.bottom + GAP
  const top = below + height > window.innerHeight - MARGIN ? Math.max(MARGIN, rect.top - GAP - height) : below
  return { left, top }
}

// The popover (Figma "Risk Explainer" 102:582)
function RiskExplainer({ id, text, style, onMouseEnter, onMouseLeave, popoverRef }) {
  return (
    <div
      id={id}
      ref={popoverRef}
      className="risk-explainer"
      role="tooltip"
      style={style}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <p className="risk-explainer-title">{text.title}</p>
      <div className="risk-explainer-part">
        <p className="risk-explainer-label">What it is</p>
        <p className="risk-explainer-body">{text.what}</p>
      </div>
      {text.yours && (
        <div className="risk-explainer-part">
          <p className="risk-explainer-label">What yours means</p>
          <p className="risk-explainer-body yours">{text.yours}</p>
        </div>
      )}
      <div className="risk-explainer-part">
        <p className="risk-explainer-label">Things to consider</p>
        <p className="risk-explainer-body">{text.consider}</p>
      </div>
      <p className="risk-explainer-footer">{text.footer ?? 'General information about your holdings, not financial advice.'}</p>
    </div>
  )
}

// The ⓘ on a tile or panel (Figma Info Button 102:581). Hovering (or keyboard focus) shows the
// explainer; a click keeps it open until a second click, Escape or a click elsewhere.
export default function InfoButton({ text }) {
  const popoverId = useId()
  const buttonRef = useRef(null)
  const popoverRef = useRef(null)
  const timer = useRef(null)
  const [open, setOpen] = useState(false)
  const [pinned, setPinned] = useState(false)
  const [position, setPosition] = useState(null)

  const show = () => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setOpen(true), HOVER_DELAY_MS)
  }
  const hide = () => {
    clearTimeout(timer.current)
    if (!pinned) timer.current = setTimeout(() => setOpen(false), HOVER_DELAY_MS)
  }
  const close = () => {
    clearTimeout(timer.current)
    setOpen(false)
    setPinned(false)
    setPosition(null)
  }

  useEffect(() => () => clearTimeout(timer.current), [])

  // Measure once it's rendered (off screen first), then place it
  useLayoutEffect(() => {
    if (!open || !buttonRef.current || !popoverRef.current) return
    // oxlint-disable-next-line react/set-state-in-effect
    setPosition(placement(buttonRef.current, popoverRef.current.offsetHeight))
  }, [open, text])

  useEffect(() => {
    if (!open) return
    const onKey = (e) => {
      if (e.key === 'Escape') {
        close()
        buttonRef.current?.focus()
      }
    }
    const onPointer = (e) => {
      if (!buttonRef.current?.contains(e.target) && !popoverRef.current?.contains(e.target)) close()
    }
    // A fixed popover would drift away from its button while the page scrolls
    const onScroll = () => close()
    window.addEventListener('keydown', onKey)
    window.addEventListener('pointerdown', onPointer)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('pointerdown', onPointer)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [open])

  if (!text) return null
  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={`risk-info ${open ? 'active' : ''}`}
        aria-label={`About ${text.title}`}
        aria-expanded={open}
        aria-describedby={open ? popoverId : undefined}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={(e) => {
          if (e.target.matches(':focus-visible')) show()
        }}
        onBlur={() => {
          if (!pinned) close()
        }}
        onClick={() => {
          if (pinned) close()
          else {
            clearTimeout(timer.current)
            setOpen(true)
            setPinned(true)
          }
        }}
      >
        <RiskInfoIcon />
      </button>
      {open && (
        <RiskExplainer
          id={popoverId}
          text={text}
          popoverRef={popoverRef}
          style={position ?? { left: -9999, top: 0, visibility: 'hidden' }}
          onMouseEnter={() => clearTimeout(timer.current)}
          onMouseLeave={hide}
        />
      )}
    </>
  )
}
