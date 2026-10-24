//! Non-secret settings from the Settings screen, in settings.json in Application Support.
//! The IBKR password is never stored. The Anthropic key is only stored if the user asks, encrypted,
//! by keystore.rs (not in this file).

use std::collections::BTreeMap;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    /// Settings format: 2 moved the default port from 4002 to 4012. A missing field (older files)
    /// reads as 0, so load() knows to update them once.
    #[serde(default)]
    pub version: u32,
    /// The API port of the app's IB Gateway. 4012 rather than Gateway's usual 4001/4002, so it
    /// never clashes with another Gateway or TWS (or a development backend) on this Mac.
    pub gateway_port: u16,
    /// The IBKR username last signed in with, to pre-fill the sign-in form (not a secret; the
    /// password is never stored)
    pub ibkr_username: Option<String>,
    /// "paper" or "live"
    pub trading_mode: String,
    /// Bring Gateway back by itself after its daily restart (no password needed). At launch and
    /// after IBKR's weekly re-login the user signs in.
    pub auto_reconnect: bool,
    /// The Claude model for AI summaries (the backend only accepts the ones it knows)
    pub ai_model: String,
    /// Let the backend load index members and their Yahoo data in the background (about 20 minutes
    /// of Yahoo calls). Off until a screen uses them (#114); no Settings row yet, so it is changed
    /// by editing settings.json.
    pub load_index_members: bool,
    /// IBKR accounts for which "Block borrowing" was switched off (after Touch ID or the Mac
    /// password, borrowing.rs). Missing = blocked. Only changed by the borrowing commands: save_settings
    /// keeps what's saved here, so the page can't switch it off by itself.
    pub allow_borrowing: BTreeMap<String, bool>,
    /// The Keychain items of earlier builds have been deleted (once, without reading them). The
    /// app no longer stores anything secret.
    pub keychain_removed: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            version: CURRENT_VERSION,
            gateway_port: 4012,
            ibkr_username: None,
            trading_mode: "paper".into(),
            auto_reconnect: true,
            ai_model: "claude-haiku-4-5".into(),
            load_index_members: false,
            allow_borrowing: BTreeMap::new(),
            keychain_removed: false,
        }
    }
}

const CURRENT_VERSION: u32 = 2;

fn path(app: &AppHandle) -> tauri::Result<PathBuf> {
    Ok(app.path().app_data_dir()?.join("settings.json"))
}

/// The saved settings, or the defaults when there are none (or the file can't be read).
pub fn load(app: &AppHandle) -> Settings {
    let saved: Option<Settings> = path(app)
        .ok()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|text| serde_json::from_str(&text).ok());
    let Some(mut settings) = saved else { return Settings::default() };
    if upgrade(&mut settings) {
        let _ = save(app, &settings);
    }
    settings
}

/// Brings older settings up to date; true if anything changed. Version 2: the port that version 1
/// saved by default (4002) becomes the new default, 4012. A port the user chose stays.
fn upgrade(settings: &mut Settings) -> bool {
    if settings.version >= CURRENT_VERSION {
        return false;
    }
    if settings.gateway_port == 4002 {
        settings.gateway_port = 4012;
    }
    settings.version = CURRENT_VERSION;
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn moves_the_old_default_port_once() {
        let mut old: Settings = serde_json::from_str(r#"{"gateway_port": 4002, "ibkr_username": "me"}"#).unwrap();
        assert_eq!(old.version, 0);
        assert!(upgrade(&mut old));
        assert_eq!((old.gateway_port, old.version), (4012, 2));
        assert_eq!(old.ibkr_username.as_deref(), Some("me"));
        // Later, choosing 4002 on purpose sticks
        old.gateway_port = 4002;
        assert!(!upgrade(&mut old));
        assert_eq!(old.gateway_port, 4002);
        // Another port the user picked is kept
        let mut custom: Settings = serde_json::from_str(r#"{"gateway_port": 4100}"#).unwrap();
        upgrade(&mut custom);
        assert_eq!(custom.gateway_port, 4100);
        assert_eq!(Settings::default().gateway_port, 4012);
    }
}

pub fn save(app: &AppHandle, settings: &Settings) -> Result<(), String> {
    if settings.gateway_port < 1024 {
        return Err("Use a port between 1024 and 65535.".into());
    }
    if settings.trading_mode != "paper" && settings.trading_mode != "live" {
        return Err("The account type must be paper or live.".into());
    }
    let path = path(app).map_err(|e| e.to_string())?;
    std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
    let text = serde_json::to_string_pretty(settings).map_err(|e| e.to_string())?;
    std::fs::write(path, text).map_err(|e| e.to_string())
}
