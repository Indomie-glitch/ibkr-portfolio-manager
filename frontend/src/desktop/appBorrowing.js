// "Block borrowing" in the Mac app (#289, src-tauri/src/borrowing.rs). Only works inside the app.
import { invoke } from '@tauri-apps/api/core'

// Asks macOS for Touch ID or the Mac password first; true if confirmed (and switched off)
export function allowBorrowing(accountId) {
  return invoke('allow_borrowing', { accountId })
}

export function blockBorrowing(accountId) {
  return invoke('block_borrowing', { accountId })
}
