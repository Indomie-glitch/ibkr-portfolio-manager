import { useRef, useSyncExternalStore } from 'react'

const MIN_WIDTH = 220
const MAX_WIDTH = 480
const DEFAULT_WIDTH = 300
// Dragging this far past the minimum snaps the list closed; letting go before it snaps back to the
// minimum (#91). Dragging a hidden list open needs a smaller pull from the left edge.
const COLLAPSE_PAST = 80
const REOPEN_AFTER = 40
// How long the snap animation runs (matches the CSS transition)
const SNAP_MS = 200

function clampWidth(width) {
  if (!Number.isFinite(width)) return DEFAULT_WIDTH
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, width))
}

// ---------- shared state: each list's width and whether it's hidden, kept in localStorage ----------
// The toolbar's show/hide button, the ⌘⌥S shortcut and the list itself all read and change it.

const panes = new Map()
const listeners = new Set()

function load(key) {
  let width = DEFAULT_WIDTH
  let collapsed = false
  try {
    const saved = Number(localStorage.getItem(key))
    if (saved > 0) width = clampWidth(saved)
    collapsed = localStorage.getItem(`${key}Collapsed`) === 'true'
  } catch {
    // storage blocked (e.g. private window); the list just won't be remembered
  }
  return { width, collapsed, snapping: false }
}

function paneState(key) {
  if (!panes.has(key)) panes.set(key, load(key))
  return panes.get(key)
}

function update(key, change) {
  panes.set(key, { ...paneState(key), ...change })
  listeners.forEach((listener) => listener())
}

function save(key) {
  const { width, collapsed } = paneState(key)
  try {
    localStorage.setItem(key, String(width))
    localStorage.setItem(`${key}Collapsed`, String(collapsed))
  } catch {
    // see load()
  }
}

const timers = new Map()

// Hides or shows the list with the short animation
function snap(key, change) {
  clearTimeout(timers.get(key))
  update(key, { ...change, snapping: true })
  timers.set(key, setTimeout(() => update(key, { snapping: false }), SNAP_MS))
}

function subscribe(listener) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

// Whether a list is hidden, for the toolbar button (re-renders when it changes)
export function useListCollapsed(key) {
  return useSyncExternalStore(subscribe, () => paneState(key).collapsed)
}

// Shows a hidden list at its last width, or hides it (toolbar button, ⌘⌥S)
export function toggleList(key) {
  snap(key, { collapsed: !paneState(key).collapsed })
  save(key)
}

// A list pane that can be resized by dragging (or the arrow keys on) its divider and hidden by
// dragging the divider past the minimum. Returns props for the pane and for the divider.
export function useResizableWidth(storageKey, label) {
  const { width, collapsed, snapping } = useSyncExternalStore(subscribe, () => paneState(storageKey))
  const drag = useRef(null)

  // Dragging: remember where the pointer started, then grow/shrink by how far it moved.
  // setPointerCapture keeps sending move events to the divider even if the pointer leaves it.
  function startDrag(e) {
    drag.current = { startX: e.clientX, startWidth: collapsed ? 0 : width }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  function moveDrag(e) {
    if (!drag.current) return
    const raw = drag.current.startWidth + e.clientX - drag.current.startX
    const state = paneState(storageKey)
    // Where the list closes and reopens during this drag, with a gap between them so it doesn't
    // flicker: from an open list it closes past the hide point; from a hidden one a short pull
    // from the edge opens it, and it only closes again if pulled almost all the way back
    const fromHidden = drag.current.startWidth === 0
    const closeBelow = fromHidden ? REOPEN_AFTER / 2 : MIN_WIDTH - COLLAPSE_PAST
    const openAbove = fromHidden ? REOPEN_AFTER : MIN_WIDTH - COLLAPSE_PAST + 20
    if (!state.collapsed && raw < closeBelow) snap(storageKey, { collapsed: true })
    else if (state.collapsed && raw > openAbove) snap(storageKey, { collapsed: false, width: clampWidth(raw) })
    else if (!state.collapsed) update(storageKey, { width: clampWidth(raw) })
  }

  function endDrag() {
    if (!drag.current) return
    drag.current = null
    save(storageKey)
  }

  function handleKey(e) {
    const step = e.key === 'ArrowRight' ? 16 : e.key === 'ArrowLeft' ? -16 : 0
    if (!step) return
    e.preventDefault()
    if (collapsed) {
      if (step > 0) toggleList(storageKey)
      return
    }
    update(storageKey, { width: clampWidth(width + step) })
    save(storageKey)
  }

  const paneProps = {
    className: `holdings-pane ${collapsed ? 'collapsed' : ''} ${snapping ? 'snapping' : ''}`,
    style: { width: collapsed ? 0 : width },
  }
  const handleProps = {
    className: 'resize-handle',
    role: 'separator',
    'aria-orientation': 'vertical',
    'aria-label': collapsed ? `${label} (hidden; drag right or press → to show it)` : label,
    'aria-valuemin': MIN_WIDTH,
    'aria-valuemax': MAX_WIDTH,
    'aria-valuenow': collapsed ? 0 : width,
    tabIndex: 0,
    onPointerDown: startDrag,
    onPointerMove: moveDrag,
    onPointerUp: endDrag,
    onPointerCancel: endDrag,
    onKeyDown: handleKey,
  }
  return { collapsed, paneProps, handleProps }
}
