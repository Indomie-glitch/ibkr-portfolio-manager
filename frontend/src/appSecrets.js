// The Anthropic API key in the macOS Keychain, through the Mac app (src-tauri/src/secrets.rs). The
// page can save or delete it and ask whether one is saved, but never read it back. Only works
// inside the app.
import { invoke } from '@tauri-apps/api/core'

// { anthropic_api_key: true/false } (no Keychain read, so no permission prompt)
export function secretStatus() {
  return invoke('secret_status')
}

export function saveSecret(name, value) {
  return invoke('save_secret', { name, value })
}

export function deleteSecret(name) {
  return invoke('delete_secret', { name })
}

// Reads the key from the Keychain (macOS may ask for permission) and hands it to the backend.
// Called just before an AI summary, never at launch.
export function loadApiKey() {
  return invoke('load_api_key')
}
