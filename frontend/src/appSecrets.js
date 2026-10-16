// Secrets in the macOS Keychain, through the Mac app (src-tauri/src/secrets.rs). The page can save
// or delete a secret and ask which are set, but never read one back. Only works inside the app.
import { invoke } from '@tauri-apps/api/core'

// { anthropic_api_key: true/false, ibkr_password: true/false }
export function secretStatus() {
  return invoke('secret_status')
}

export function saveSecret(name, value) {
  return invoke('save_secret', { name, value })
}

export function deleteSecret(name) {
  return invoke('delete_secret', { name })
}
