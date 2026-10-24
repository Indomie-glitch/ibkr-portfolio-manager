// "Block borrowing" in the Mac app (#289, src-tauri/src/borrowing.rs). Only works inside Tauri.
import { invoke, isTauri } from '@tauri-apps/api/core'

// The macOS prompt can be shown: the built app, and `npm run tauri dev` (which has no bundled
// backend, so IN_APP is false there)
export const CAN_CONFIRM_OWNER = isTauri()

// `npm run tauri dev` only: just the Touch ID / Mac password prompt; true if confirmed
export function confirmOwner() {
  return invoke('confirm_borrowing')
}

// Asks macOS for Touch ID or the Mac password first; true if confirmed (and switched off)
export function allowBorrowing(accountId) {
  return invoke('allow_borrowing', { accountId })
}

export function blockBorrowing(accountId) {
  return invoke('block_borrowing', { accountId })
}
