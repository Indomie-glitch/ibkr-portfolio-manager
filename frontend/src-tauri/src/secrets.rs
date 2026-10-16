//! Secrets in the macOS Keychain. Only the app itself reads them: the frontend can save, delete
//! and ask which ones are set, but can never read one back.
//!
//! All of them live in a single Keychain item (a small JSON object), so macOS asks at most once
//! for permission to read it (an unsigned app is asked again after every update). It's read once
//! per launch and then kept in memory; a lock makes parallel readers wait for that one read
//! instead of each asking macOS.

use std::collections::BTreeMap;
use std::sync::Mutex;

use keyring::{Entry, Error};

const SERVICE: &str = "com.indomieglitch.portfoliomanager";
const ACCOUNT: &str = "app-secrets";

/// The secrets the app knows about; any other name is refused.
pub const NAMES: [&str; 3] = ["anthropic_api_key", "ibkr_password", "ibkr_username"];

/// Sent to the backend at launch and whenever they change. (The IBKR login is only used for the
/// Gateway sign-in.)
pub const FOR_BACKEND: [&str; 1] = ["anthropic_api_key"];

/// Before version 2 each secret was its own Keychain item (account = its name)
const OLD_ITEMS: [&str; 2] = ["anthropic_api_key", "ibkr_password"];

type Secrets = BTreeMap<String, String>;

/// The secrets once read (None until the first read)
static CACHE: Mutex<Option<Secrets>> = Mutex::new(None);

fn check_name(name: &str) -> Result<(), String> {
    if NAMES.contains(&name) {
        Ok(())
    } else {
        Err(format!("unknown secret {name}"))
    }
}

fn item(service: &str) -> Result<Entry, String> {
    Entry::new(service, ACCOUNT).map_err(|e| e.to_string())
}

/// Reads the single item, moving the old one-per-secret items into it the first time.
fn read_all(service: &str) -> Secrets {
    let Ok(entry) = item(service) else { return Secrets::new() };
    match entry.get_password() {
        Ok(json) => serde_json::from_str(&json).unwrap_or_default(),
        Err(Error::NoEntry) => migrate_old_items(service),
        // Access denied or the Keychain unavailable: work without secrets, and don't migrate
        Err(e) => {
            log::warn!("couldn't read the app's Keychain item: {e}");
            Secrets::new()
        }
    }
}

fn migrate_old_items(service: &str) -> Secrets {
    let mut secrets = Secrets::new();
    for name in OLD_ITEMS {
        if let Ok(entry) = Entry::new(service, name) {
            if let Ok(value) = entry.get_password() {
                secrets.insert(name.to_string(), value);
            }
        }
    }
    if !secrets.is_empty() && write_all(service, &secrets).is_ok() {
        for name in OLD_ITEMS {
            if let Ok(entry) = Entry::new(service, name) {
                let _ = entry.delete_credential();
            }
        }
    }
    secrets
}

fn write_all(service: &str, secrets: &Secrets) -> Result<(), String> {
    let entry = item(service)?;
    if secrets.is_empty() {
        return match entry.delete_credential() {
            Ok(()) | Err(Error::NoEntry) => Ok(()),
            Err(e) => Err(e.to_string()),
        };
    }
    let json = serde_json::to_string(secrets).map_err(|e| e.to_string())?;
    entry.set_password(&json).map_err(|e| e.to_string())
}

/// Runs `f` on the secrets, reading the Keychain first if this is the first use.
fn with_secrets<T>(f: impl FnOnce(&mut Secrets) -> T) -> T {
    let mut cache = CACHE.lock().unwrap();
    let secrets = cache.get_or_insert_with(|| read_all(SERVICE));
    f(secrets)
}

pub fn get(name: &str) -> Option<String> {
    check_name(name).ok()?;
    with_secrets(|secrets| secrets.get(name).cloned())
}

pub fn set(name: &str, value: &str) -> Result<(), String> {
    check_name(name)?;
    with_secrets(|secrets| {
        let mut next = secrets.clone();
        next.insert(name.to_string(), value.to_string());
        write_all(SERVICE, &next)?;
        *secrets = next;
        Ok(())
    })
}

pub fn delete(name: &str) -> Result<(), String> {
    check_name(name)?;
    with_secrets(|secrets| {
        if !secrets.contains_key(name) {
            return Ok(());
        }
        let mut next = secrets.clone();
        next.remove(name);
        write_all(SERVICE, &next)?;
        *secrets = next;
        Ok(())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const TEST_SERVICE: &str = "com.indomieglitch.portfoliomanager.test";

    #[test]
    fn unknown_names_are_refused() {
        assert!(check_name("something_else").is_err());
        assert!(check_name("ibkr_username").is_ok());
    }

    // Uses the real Keychain (a separate test service), so it only runs when asked:
    // cargo test -- --ignored
    #[test]
    #[ignore]
    fn moves_old_items_into_one_and_round_trips() {
        let old = |name: &str| Entry::new(TEST_SERVICE, name).unwrap();
        let _ = item(TEST_SERVICE).unwrap().delete_credential();
        old("anthropic_api_key").set_password("key-123").unwrap();
        old("ibkr_password").set_password("pw-456").unwrap();

        let secrets = read_all(TEST_SERVICE);
        assert_eq!(secrets.get("anthropic_api_key").map(String::as_str), Some("key-123"));
        assert_eq!(secrets.get("ibkr_password").map(String::as_str), Some("pw-456"));
        // The old items are gone, and the single item holds both
        assert!(matches!(old("anthropic_api_key").get_password(), Err(Error::NoEntry)));
        assert!(matches!(old("ibkr_password").get_password(), Err(Error::NoEntry)));
        assert_eq!(read_all(TEST_SERVICE), secrets);

        let mut more = secrets.clone();
        more.insert("ibkr_username".into(), "me".into());
        write_all(TEST_SERVICE, &more).unwrap();
        assert_eq!(read_all(TEST_SERVICE), more);
        write_all(TEST_SERVICE, &Secrets::new()).unwrap(); // empty removes the item
        assert!(matches!(item(TEST_SERVICE).unwrap().get_password(), Err(Error::NoEntry)));
    }
}
