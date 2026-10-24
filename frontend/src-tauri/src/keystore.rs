//! "Remember key on this Mac": the Anthropic API key, encrypted in Application Support (#277).
//!
//! Two files, both readable only by the user (mode 600): `api_key.secret` holds a random 32 byte
//! encryption key made once per install, and `api_key.enc` holds the API key encrypted with it
//! (ChaCha20-Poly1305: a random nonce, then the ciphertext, which also carries an authentication
//! tag so any change to the file is detected). No Keychain, so macOS never asks for a password.
//! The trade-off: the encryption key sits on the same Mac, so this stops casual reading of the
//! file but not malware running as the user. The key can only spend Anthropic credit.

use std::fs;
use std::io::Write;
use std::path::Path;

use chacha20poly1305::aead::{Aead, AeadCore, KeyInit, OsRng};
use chacha20poly1305::{ChaCha20Poly1305, Key, Nonce};

const KEY_FILE: &str = "api_key.secret";
const DATA_FILE: &str = "api_key.enc";
const NONCE_LEN: usize = 12;

/// Writes a file that only the user can read (mode 600), replacing any older one.
fn write_private(path: &Path, bytes: &[u8]) -> Result<(), String> {
    use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
    let _ = fs::remove_file(path);
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .map_err(|e| e.to_string())?;
    // The mode above is subject to the umask, so set it exactly as well
    file.set_permissions(fs::Permissions::from_mode(0o600)).map_err(|e| e.to_string())?;
    file.write_all(bytes).and_then(|_| file.flush()).map_err(|e| e.to_string())
}

/// The install's encryption key, made (and saved) the first time.
fn encryption_key(dir: &Path) -> Result<Key, String> {
    if let Ok(bytes) = fs::read(dir.join(KEY_FILE)) {
        if bytes.len() == 32 {
            return Ok(*Key::from_slice(&bytes));
        }
    }
    let key = ChaCha20Poly1305::generate_key(&mut OsRng);
    fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    write_private(&dir.join(KEY_FILE), &key)?;
    Ok(key)
}

/// Encrypts and saves the API key.
pub fn save(dir: &Path, api_key: &str) -> Result<(), String> {
    let cipher = ChaCha20Poly1305::new(&encryption_key(dir)?);
    let nonce = ChaCha20Poly1305::generate_nonce(&mut OsRng);
    let encrypted = cipher.encrypt(&nonce, api_key.as_bytes()).map_err(|_| "Couldn't encrypt the key.".to_string())?;
    let mut bytes = nonce.to_vec();
    bytes.extend(encrypted);
    write_private(&dir.join(DATA_FILE), &bytes)
}

/// The saved API key; None when nothing is saved. A file that can't be decrypted (damaged, or
/// the other file is missing or changed) is deleted, so the user is simply asked again.
pub fn load(dir: &Path) -> Option<String> {
    let bytes = fs::read(dir.join(DATA_FILE)).ok()?;
    let key = fs::read(dir.join(KEY_FILE)).ok().filter(|k| k.len() == 32);
    let decrypted = key.filter(|_| bytes.len() > NONCE_LEN).and_then(|key| {
        let cipher = ChaCha20Poly1305::new(Key::from_slice(&key));
        let (nonce, encrypted) = bytes.split_at(NONCE_LEN);
        cipher.decrypt(Nonce::from_slice(nonce), encrypted).ok()
    });
    match decrypted.and_then(|plain| String::from_utf8(plain).ok()) {
        Some(api_key) => Some(api_key),
        None => {
            remove(dir);
            None
        }
    }
}

pub fn exists(dir: &Path) -> bool {
    dir.join(DATA_FILE).exists()
}

/// Deletes both files.
pub fn remove(dir: &Path) {
    let _ = fs::remove_file(dir.join(DATA_FILE));
    let _ = fs::remove_file(dir.join(KEY_FILE));
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;

    fn temp_dir(name: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("keystore-test-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn round_trip_without_the_key_in_plain_text() {
        let dir = temp_dir("round");
        save(&dir, "fake-secret-value").unwrap();
        assert_eq!(load(&dir).as_deref(), Some("fake-secret-value"));
        for file in [KEY_FILE, DATA_FILE] {
            let bytes = fs::read(dir.join(file)).unwrap();
            assert!(!bytes.windows(10).any(|w| w == b"fake-secre"));
        }
        // Saving again with a new key replaces it
        save(&dir, "fake-other-value").unwrap();
        assert_eq!(load(&dir).as_deref(), Some("fake-other-value"));
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn files_are_private() {
        let dir = temp_dir("mode");
        save(&dir, "fake-x-value").unwrap();
        for file in [KEY_FILE, DATA_FILE] {
            assert_eq!(fs::metadata(dir.join(file)).unwrap().permissions().mode() & 0o777, 0o600);
        }
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn nothing_saved_loads_nothing() {
        let dir = temp_dir("none");
        assert_eq!(load(&dir), None);
        assert!(!exists(&dir));
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn damaged_or_mismatched_files_are_deleted() {
        let dir = temp_dir("bad");
        save(&dir, "fake-x-value").unwrap();
        let mut bytes = fs::read(dir.join(DATA_FILE)).unwrap();
        *bytes.last_mut().unwrap() ^= 1;
        fs::write(dir.join(DATA_FILE), bytes).unwrap();
        assert_eq!(load(&dir), None);
        assert!(!exists(&dir) && !dir.join(KEY_FILE).exists());

        // The encryption key replaced by another one
        save(&dir, "fake-x-value").unwrap();
        fs::write(dir.join(KEY_FILE), [7u8; 32]).unwrap();
        assert_eq!(load(&dir), None);
        assert!(!exists(&dir));

        // Too short to hold a nonce
        save(&dir, "fake-x-value").unwrap();
        fs::write(dir.join(DATA_FILE), [1u8; 5]).unwrap();
        assert_eq!(load(&dir), None);
        assert!(!exists(&dir));

        // The encryption key file lost
        save(&dir, "fake-x-value").unwrap();
        fs::remove_file(dir.join(KEY_FILE)).unwrap();
        assert_eq!(load(&dir), None);
        assert!(!exists(&dir));
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn remove_deletes_both_files() {
        let dir = temp_dir("remove");
        save(&dir, "fake-x-value").unwrap();
        remove(&dir);
        assert!(!dir.join(KEY_FILE).exists() && !dir.join(DATA_FILE).exists());
        fs::remove_dir_all(dir).unwrap();
    }
}
