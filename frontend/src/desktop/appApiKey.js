// The Anthropic API key in the Mac app. It's kept only in memory: entered in Settings, used for
// this session, gone when the app quits. Nothing secret is ever stored. Only works inside the app.
import { invoke } from '@tauri-apps/api/core'

// Whether a key has been entered this session (never the key itself)
export function apiKeyStatus() {
  return invoke('api_key_status')
}

export function setApiKey(key) {
  return invoke('set_api_key', { key })
}

export function clearApiKey() {
  return invoke('clear_api_key')
}
