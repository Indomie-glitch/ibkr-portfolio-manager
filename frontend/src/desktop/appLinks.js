// Links out in the Mac app open in the default browser (open_in_browser in src-tauri/src/lib.rs).
// When one can't be opened, Rust sends link-open-failed with the reason.
import { listen } from '@tauri-apps/api/event'

// Calls handler(reason) when a link couldn't be opened; returns a function that stops listening
export function onLinkOpenFailed(handler) {
  const stop = listen('link-open-failed', (event) => handler(event.payload))
  return () => {
    stop.then((unlisten) => unlisten())
  }
}
