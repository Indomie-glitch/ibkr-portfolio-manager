// The IBKR sign-in, run by the Mac app (src-tauri/src/session.rs). Only works inside the app.
import { invoke } from '@tauri-apps/api/core'

// { state: 'signed_out' | 'starting' | 'signing_in' | 'awaiting_approval' | 'signed_in'
//          | 'wrong_password' | 'not_approved' | 'session_ended' | 'error', ...details }
export function loginState() {
  return invoke('login_state')
}

// { username, mode, password_saved } (never the password itself)
export function savedLogin() {
  return invoke('saved_login')
}

export function signIn({ username, password, mode, remember }) {
  return invoke('sign_in', { username, password, mode, remember })
}

// Signs in again with the saved username and remembered password; rejects with
// 'password_needed' when the password isn't remembered
export function reconnect() {
  return invoke('reconnect')
}

export function cancelSignIn() {
  return invoke('cancel_sign_in')
}

export function signOut() {
  return invoke('sign_out')
}
