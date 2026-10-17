// Settings from the Mac app's Settings screen, stored by the app (src-tauri/src/settings.rs) and
// applied to the backend right away. Only works inside the app.
import { invoke } from '@tauri-apps/api/core'

// { gateway_port }
export function getSettings() {
  return invoke('get_settings')
}

export function saveSettings(settings) {
  return invoke('save_settings', { settings })
}
