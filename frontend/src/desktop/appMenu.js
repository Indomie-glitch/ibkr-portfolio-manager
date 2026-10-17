// The Mac app's menu bar (src-tauri/src/lib.rs): Settings… (⌘,) asks the page to open the Settings sheet.
import { listen } from '@tauri-apps/api/event'

// Calls handler when Settings… is chosen; returns a function that stops listening
export function onOpenSettingsMenu(handler) {
  const stop = listen('open-settings', handler)
  return () => {
    stop.then((unlisten) => unlisten())
  }
}
