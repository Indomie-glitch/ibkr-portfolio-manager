//! Non-secret settings from the Settings screen, in settings.json in Application Support.
//! (Secrets are in the Keychain: see secrets.rs.)

use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    /// IB Gateway's API port (4002 is Gateway's default for paper accounts)
    pub gateway_port: u16,
    /// The IBKR username last signed in with (the password is in the Keychain, if remembered)
    pub ibkr_username: Option<String>,
    /// "paper" or "live"
    pub trading_mode: String,
    /// Sign in at launch and bring Gateway back after its daily restart, when the password is remembered
    pub auto_reconnect: bool,
    /// The Claude model for AI summaries (the backend only accepts the ones it knows)
    pub ai_model: String,
}

impl Default for Settings {
    fn default() -> Self {
        Settings {
            gateway_port: 4002,
            ibkr_username: None,
            trading_mode: "paper".into(),
            auto_reconnect: true,
            ai_model: "claude-haiku-4-5".into(),
        }
    }
}

fn path(app: &AppHandle) -> tauri::Result<PathBuf> {
    Ok(app.path().app_data_dir()?.join("settings.json"))
}

/// The saved settings, or the defaults when there are none (or the file can't be read).
pub fn load(app: &AppHandle) -> Settings {
    path(app)
        .ok()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
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
