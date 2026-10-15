import { useEffect, useState } from 'react'

// 'system' follows the macOS setting; 'light' and 'dark' override it.
// index.html applies the same rules before React loads, to avoid a flash of the wrong theme.
const STORAGE_KEY = 'appearance'
const CHOICES = ['system', 'light', 'dark']

function loadAppearance() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return CHOICES.includes(saved) ? saved : 'system'
  } catch {
    return 'system'
  }
}

export function useAppearance() {
  const [appearance, setAppearance] = useState(loadAppearance)

  useEffect(() => {
    // matchMedia lets JavaScript read (and watch) the same setting CSS media queries see
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const dark = appearance === 'dark' || (appearance === 'system' && media.matches)
      document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    }
    apply()
    // Only follow macOS changes while on System
    if (appearance !== 'system') return
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [appearance])

  function choose(next) {
    setAppearance(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // storage blocked; the choice lasts until the page is reloaded
    }
  }

  return [appearance, choose]
}
