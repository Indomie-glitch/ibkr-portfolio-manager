// The IBKR sign-in, run by the Mac app (src-tauri/src/session.rs). Only works inside the app.
import { invoke } from '@tauri-apps/api/core'

// { state: 'signed_out' | 'starting' | 'signing_in' | 'awaiting_approval' | 'signed_in'
//          | 'wrong_password' | 'not_approved' | 'session_ended' | 'error', ...details }
export function loginState() {
  return invoke('login_state')
}

// { username, mode } to pre-fill the sign-in form (the password is never stored)
export function savedLogin() {
  return invoke('saved_login')
}

// The password goes to IB Gateway once and isn't kept
export function signIn({ username, password, mode }) {
  return invoke('sign_in', { username, password, mode })
}

export function cancelSignIn() {
  return invoke('cancel_sign_in')
}

export function signOut() {
  return invoke('sign_out')
}
