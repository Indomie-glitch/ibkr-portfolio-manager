// The Anthropic API key in the Mac app. It's entered in Settings and sent to the backend, which
// keeps it in memory. Only if "Remember key on this Mac" is on is an encrypted copy also saved in
// Application Support (src-tauri/src/keystore.rs), so it survives quitting and updates. Only works
// inside the app.
import { invoke } from '@tauri-apps/api/core'

// { in_use, remembered }: whether a key is in use, and whether a saved copy exists (never the key)
export function apiKeyStatus() {
  return invoke('api_key_status')
}

export function setApiKey(key, remember) {
  return invoke('set_api_key', { key, remember })
}

// Saves (true) or deletes (false) the encrypted copy of the key in use
export function rememberApiKey(remember) {
  return invoke('remember_api_key', { remember })
}

// Also deletes the saved copy
export function clearApiKey() {
  return invoke('clear_api_key')
}
