import { useEffect, useState } from 'react'

// Behaviour shared by the app's menus (the account menu, PopupMenu, the summary History menu; #206).
// Each keeps its own look; these hooks are what they had copied.

// Calls onOutside when the mouse goes down outside ref's element, while active
export function useClickOutside(ref, onOutside, active = true) {
  useEffect(() => {
    if (!active) return
    const onDown = (e) => !ref.current?.contains(e.target) && onOutside()
    window.addEventListener('mousedown', onDown)
    return () => window.removeEventListener('mousedown', onDown)
  }, [ref, onOutside, active])
}

// Calls onEscape when Escape is pressed anywhere, while active
export function useEscapeKey(onEscape, active = true) {
  useEffect(() => {
    if (!active) return
    const onKey = (e) => e.key === 'Escape' && onEscape()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onEscape, active])
}

// Moving through a menu like a macOS one: the arrow keys go from enabled item to enabled item
// (wrapping round), Return or Space chooses. items: { disabled? } or 'separator'.
// moveKey(e) handles one key press and returns whether it did anything.
export function useMenuKeys(items, onChoose) {
  const [active, setActive] = useState(-1)
  const choices = items.map((item, i) => (item !== 'separator' && !item.disabled ? i : -1)).filter((i) => i >= 0)

  function moveKey(e) {
    const at = choices.indexOf(active)
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive(choices[(at + 1) % choices.length])
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive(choices[(at - 1 + choices.length) % choices.length])
    } else if ((e.key === 'Enter' || e.key === ' ') && active >= 0) {
      e.preventDefault()
      onChoose(items[active])
    } else {
      return false
    }
    return true
  }

  return { active, setActive, choices, moveKey }
}
