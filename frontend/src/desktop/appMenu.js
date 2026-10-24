// The Mac app's menu bar (src-tauri/src/lib.rs): Settings… (⌘,) opens the Settings sheet; View sets the text size.
import { listen } from '@tauri-apps/api/event'

// Calls handler when Settings… is chosen; returns a function that stops listening
export function onOpenSettingsMenu(handler) {
  const stop = listen('open-settings', handler)
  return () => {
    stop.then((unlisten) => unlisten())
  }
}

// Calls handler('bigger' | 'smaller' | 'reset') for the View menu's text size items
export function onTextSizeMenu(handler) {
  const stop = listen('text-size', (event) => handler(event.payload))
  return () => {
    stop.then((unlisten) => unlisten())
  }
}
