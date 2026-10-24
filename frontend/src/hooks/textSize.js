import { useCallback, useEffect, useState } from 'react'
import { DEFAULT_TEXT_SIZE, isTextSize, stepTextSize, zoomFor } from '../lib/textSize.js'
import { onTextSizeMenu } from '../desktop/appMenu.js'
import { IN_APP } from '../lib/api.js'

const STORAGE_KEY = 'textSize'

function loadTextSize() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return isTextSize(saved) ? saved : DEFAULT_TEXT_SIZE
  } catch {
    return DEFAULT_TEXT_SIZE
  }
}

// The saved text size, applied as page zoom. --text-zoom lets heights written in vh (which zoom
// does not shrink) divide it back out. In the Mac app the View menu's Bigger / Smaller / Actual Size
// (⌘+ ⌘− ⌘0) call the same setter.
export function useTextSize() {
  const [size, setSize] = useState(loadTextSize)

  useEffect(() => {
    const zoom = zoomFor(size)
    document.documentElement.style.zoom = zoom === 1 ? '' : String(zoom)
    document.documentElement.style.setProperty('--text-zoom', String(zoom))
  }, [size])

  const choose = useCallback((next) => {
    setSize(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // storage blocked; the choice lasts until the page is reloaded
    }
  }, [])

  useEffect(() => {
    if (!IN_APP) return undefined
    return onTextSizeMenu((action) => {
      if (action === 'reset') choose(DEFAULT_TEXT_SIZE)
      else setSize((current) => {
        const next = stepTextSize(current, action === 'bigger' ? 1 : -1)
        try {
          localStorage.setItem(STORAGE_KEY, next)
        } catch {
          // as above
        }
        return next
      })
    })
  }, [choose])

  return [size, choose]
}
