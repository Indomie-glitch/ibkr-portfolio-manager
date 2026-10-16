//! The Anthropic API key, the only thing the app keeps in the macOS Keychain. (The IBKR password
//! is never stored: it's used once to sign in.)
//!
//! An unsigned app is asked for permission each time it reads the Keychain after an update, so the
//! key is read only when an AI summary is requested, never at launch. Whether a key is saved is
//! kept separately in settings.json (ai_key_saved), so nothing else needs to read it.

use keyring::{Entry, Error};

const SERVICE: &str = "com.indomieglitch.portfoliomanager";
const API_KEY: &str = "anthropic-api-key";

/// Keychain items from earlier builds (one per secret, then all secrets in one). Deleted once,
/// without being read, so they can't cause any more prompts.
const OLD_ITEMS: [&str; 4] = ["anthropic_api_key", "ibkr_password", "ibkr_username", "app-secrets"];

fn api_key_entry() -> Result<Entry, String> {
    Entry::new(SERVICE, API_KEY).map_err(|e| e.to_string())
}

/// Reads the key (macOS may ask for permission). None if there's none or access was refused.
pub fn api_key() -> Option<String> {
    api_key_entry().ok()?.get_password().ok()
}

pub fn save_api_key(key: &str) -> Result<(), String> {
    api_key_entry()?.set_password(key).map_err(|e| e.to_string())
}

pub fn delete_api_key() -> Result<(), String> {
    match api_key_entry()?.delete_credential() {
        Ok(()) | Err(Error::NoEntry) => Ok(()),
        Err(e) => Err(e.to_string()),
    }
}

pub fn delete_old_items() {
    for name in OLD_ITEMS {
        if let Ok(entry) = Entry::new(SERVICE, name) {
            let _ = entry.delete_credential();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Uses the real Keychain, so it only runs when asked: cargo test -- --ignored
    #[test]
    #[ignore]
    fn save_read_delete_round_trip() {
        let before = api_key();
        save_api_key("test-value-123").unwrap();
        assert_eq!(api_key().as_deref(), Some("test-value-123"));
        delete_api_key().unwrap();
        assert_eq!(api_key(), None);
        delete_api_key().unwrap(); // deleting a missing key is fine
        if let Some(value) = before {
            save_api_key(&value).unwrap();
        }
    }
}
