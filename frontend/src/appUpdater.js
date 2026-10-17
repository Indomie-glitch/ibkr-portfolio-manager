// App updates through the Mac app (src-tauri/src/updater.rs). Only works inside the app.
import { Channel, invoke } from '@tauri-apps/api/core'
import { listen } from '@tauri-apps/api/event'

// { version, current_version, notes } when a newer version is out, otherwise null. Rejects when
// the check itself fails (offline, GitHub down).
export function checkForUpdate() {
  return invoke('check_for_update')
}

// Downloads the update; onEvent gets { event: 'progress', received, total } and { event: 'finished' }
export function downloadUpdate(onEvent) {
  const channel = new Channel()
  channel.onmessage = onEvent
  return invoke('download_update', { onEvent: channel })
}

// Stops IB Gateway and the backend, installs and relaunches (only returns on an error)
export function installUpdate() {
  return invoke('install_update')
}

export function restartApp() {
  return invoke('restart_app')
}

export function openReleasePage(version) {
  return invoke('open_release_page', { version })
}

// "Check for Updates…" in the app menu; returns a promise of the function that stops listening
export function onCheckForUpdatesMenu(handler) {
  return listen('check-for-updates', handler)
}
