// IB Gateway setup through the Mac app (src-tauri/src/gateway.rs). Only works inside the app.
import { invoke } from '@tauri-apps/api/core'

// { installed: { version, path } | null, setup: { step, received, total, error } }
// step: idle | downloading | checking | installer_open | failed
export function gatewayStatus() {
  return invoke('gateway_status')
}

// Downloads IBKR's installer, checks its signature and opens it, in the background
export function installGateway() {
  return invoke('install_gateway')
}
