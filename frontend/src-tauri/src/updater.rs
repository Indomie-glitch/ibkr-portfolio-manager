//! App updates through GitHub Releases (tauri-plugin-updater). The page asks for a check at
//! launch and from the "Check for Updates…" menu item; nothing is installed without the user
//! clicking Update Now.
//!
//! Update Now runs in this order: download (the signature is checked against the public key in
//! tauri.conf.json), stop IB Gateway and the backend (both run from inside the app bundle, so
//! they must stop before it's replaced), install, relaunch. If installing fails, the page offers
//! the release page's DMG and a restart, which brings the old version back up.

use std::sync::Mutex;

use serde::Serialize;
use tauri::ipc::Channel;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_updater::{Update, UpdaterExt};

/// The update found by the last check, then its downloaded package
#[derive(Default)]
pub struct PendingUpdate {
    update: Mutex<Option<Update>>,
    package: Mutex<Option<Vec<u8>>>,
}

#[derive(Serialize)]
pub struct UpdateInfo {
    version: String,
    current_version: String,
    notes: Option<String>,
}

/// Download progress, sent to the page as it arrives
#[derive(Clone, Serialize)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum DownloadEvent {
    Progress { received: u64, total: Option<u64> },
    Finished,
}

/// Asks GitHub whether there's a newer version. None when there isn't; an error when the check
/// itself failed (offline, GitHub down), which the page ignores at launch.
#[tauri::command]
pub async fn check_for_update(app: AppHandle, pending: State<'_, PendingUpdate>) -> Result<Option<UpdateInfo>, String> {
    let update = app.updater().map_err(|e| e.to_string())?.check().await.map_err(|e| e.to_string())?;
    let info = update.as_ref().map(|u| UpdateInfo {
        version: u.version.clone(),
        current_version: u.current_version.clone(),
        notes: u.body.clone(),
    });
    *pending.update.lock().unwrap() = update;
    *pending.package.lock().unwrap() = None;
    Ok(info)
}

/// Downloads the update found by check_for_update and checks its signature.
#[tauri::command]
pub async fn download_update(pending: State<'_, PendingUpdate>, on_event: Channel<DownloadEvent>) -> Result<(), String> {
    let update = pending.update.lock().unwrap().clone().ok_or("No update to download.")?;
    let mut received: u64 = 0;
    let package = update
        .download(
            |chunk, total| {
                received += chunk as u64;
                let _ = on_event.send(DownloadEvent::Progress { received, total });
            },
            || {
                let _ = on_event.send(DownloadEvent::Finished);
            },
        )
        .await
        .map_err(|e| e.to_string())?;
    *pending.package.lock().unwrap() = Some(package);
    Ok(())
}

/// Stops IB Gateway (which ends the IBKR session) and the backend, then replaces the app with the
/// downloaded version and relaunches it. On an error the old app is still in place (the plugin
/// restores it) but stopped: the page then offers the DMG and a restart.
#[tauri::command]
pub fn install_update(app: AppHandle, pending: State<'_, PendingUpdate>) -> Result<(), String> {
    let update = pending.update.lock().unwrap().clone().ok_or("No update to install.")?;
    let package = pending.package.lock().unwrap().take().ok_or("The update hasn't been downloaded.")?;
    crate::shutdown_for_update(&app);
    update.install(&package).map_err(|e| e.to_string())?;
    app.restart();
}

/// Relaunches the app as it is (after a failed install, this brings Gateway's sign-in and the
/// backend back up).
#[tauri::command]
pub fn restart_app(app: AppHandle) {
    app.restart();
}

/// Opens the release page for a version in the browser, to download the DMG by hand.
#[tauri::command]
pub fn open_release_page(version: String) -> Result<(), String> {
    // Only version numbers: never pass anything else to `open`
    if !version.chars().all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-') {
        return Err("invalid version".into());
    }
    let url = format!("https://github.com/Indomie-glitch/ibkr-portfolio-manager/releases/tag/v{version}");
    std::process::Command::new("/usr/bin/open").arg(url).status().map_err(|e| e.to_string())?;
    Ok(())
}

pub fn manage(app: &AppHandle) {
    app.manage(PendingUpdate::default());
}
