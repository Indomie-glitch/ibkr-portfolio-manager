//! Secrets in the macOS Keychain. Only the app itself reads them: the frontend can save, delete
//! and ask which ones are set, but can never read one back.

use keyring::{Entry, Error};

const SERVICE: &str = "com.indomieglitch.portfoliomanager";

/// The secrets the app knows about; any other name is refused.
pub const NAMES: [&str; 2] = ["anthropic_api_key", "ibkr_password"];

/// Sent to the backend at launch and whenever they change. (The IBKR password is only used for
/// the Gateway login, in a later step.)
pub const FOR_BACKEND: [&str; 1] = ["anthropic_api_key"];

fn entry(name: &str) -> Result<Entry, String> {
    if !NAMES.contains(&name) {
        return Err(format!("unknown secret {name}"));
    }
    Entry::new(SERVICE, name).map_err(|e| e.to_string())
}

pub fn get(name: &str) -> Option<String> {
    entry(name).ok()?.get_password().ok()
}

pub fn set(name: &str, value: &str) -> Result<(), String> {
    entry(name)?.set_password(value).map_err(|e| e.to_string())
}

pub fn delete(name: &str) -> Result<(), String> {
    match entry(name)?.delete_credential() {
        Ok(()) | Err(Error::NoEntry) => Ok(()),
        Err(e) => Err(e.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Uses the real Keychain, so it only runs when asked: cargo test -- --ignored
    #[test]
    #[ignore]
    fn set_get_delete_round_trip() {
        let name = "ibkr_password";
        let before = get(name);
        set(name, "test-value-123").unwrap();
        assert_eq!(get(name).as_deref(), Some("test-value-123"));
        delete(name).unwrap();
        assert_eq!(get(name), None);
        delete(name).unwrap(); // deleting a missing secret is fine
        if let Some(value) = before {
            set(name, &value).unwrap();
        }
    }

    #[test]
    fn unknown_names_are_refused() {
        assert!(set("something_else", "x").is_err());
        assert_eq!(get("something_else"), None);
    }
}
