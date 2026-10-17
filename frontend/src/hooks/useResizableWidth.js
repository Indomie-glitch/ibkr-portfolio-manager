import { useRef, useState } from 'react'

const MIN_WIDTH = 220
const MAX_WIDTH = 480
const DEFAULT_WIDTH = 300

// Never narrower than MIN_WIDTH, so the list can't be dragged out of sight (#91); anything that isn't
// a number (a stray pointer event) falls back to the default
function clampWidth(width) {
  if (!Number.isFinite(width)) return DEFAULT_WIDTH
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width))
}

function loadWidth(storageKey) {
  try {
    const saved = Number(localStorage.getItem(storageKey))
    return saved > 0 ? clampWidth(saved) : DEFAULT_WIDTH
  } catch {
    return DEFAULT_WIDTH
  }
}

function saveWidth(storageKey, width) {
  try {
    localStorage.setItem(storageKey, String(width))
  } catch {
    // storage blocked (e.g. private window); the width just won't be remembered
  }
}

// A list pane's width, resizable by dragging (or the arrow keys on) its handle and remembered in
// localStorage. Returns the width and the props for the handle element.
export function useResizableWidth(storageKey, label) {
  const [width, setWidth] = useState(() => loadWidth(storageKey))
  const drag = useRef(null)

  // Dragging: remember where the pointer started, then grow/shrink by how far it moved.
  // setPointerCapture keeps sending move events to the handle even if the pointer leaves it.
  function startDrag(e) {
    drag.current = { startX: e.clientX, startWidth: width }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  function moveDrag(e) {
    if (!drag.current) return
    setWidth(clampWidth(drag.current.startWidth + e.clientX - drag.current.startX))
  }

  function endDrag() {
    if (!drag.current) return
    drag.current = null
    saveWidth(storageKey, width)
  }

  function handleKey(e) {
    const step = e.key === 'ArrowRight' ? 16 : e.key === 'ArrowLeft' ? -16 : 0
    if (!step) return
    e.preventDefault()
    const next = clampWidth(width + step)
    setWidth(next)
    saveWidth(storageKey, next)
  }

  const handleProps = {
    className: 'resize-handle',
    role: 'separator',
    'aria-orientation': 'vertical',
    'aria-label': label,
    'aria-valuemin': MIN_WIDTH,
    'aria-valuemax': MAX_WIDTH,
    'aria-valuenow': width,
    tabIndex: 0,
    onPointerDown: startDrag,
    onPointerMove: moveDrag,
    onPointerUp: endDrag,
    onPointerCancel: endDrag,
    onKeyDown: handleKey,
  }
  return [width, handleProps]
}
