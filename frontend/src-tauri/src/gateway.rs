//! IB Gateway on this Mac: finding an installed copy, downloading and opening IBKR's installer,
//! and the IBC settings that configure its API automatically when the app starts it.

use std::path::{Path, PathBuf};

use serde::Serialize;

/// IBKR's standalone Gateway for Apple Silicon. "Standalone" doesn't update itself, which IBC
/// needs (a self-updating Gateway moves to a new folder on every update).
pub const DOWNLOAD_URL: &str =
    "https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-macos-arm.dmg";

#[derive(Clone, Debug, Serialize, PartialEq)]
pub struct Installed {
    /// "10.50"
    pub version: String,
    /// .../IB Gateway 10.50
    pub path: PathBuf,
}

impl Installed {
    /// IBC's name for the version: "10.50" -> "1050"
    #[allow(dead_code)]
    pub fn major_version(&self) -> String {
        self.version.replace('.', "")
    }

    /// Gateway's bundled Java, which runs IBC too, so the user never installs Java
    pub fn java(&self) -> PathBuf {
        self.path.join(".install4j/jre.bundle/Contents/Home/bin/java")
    }
}

/// "IB Gateway 10.50" -> Some("10.50")
fn version_from_folder(name: &str) -> Option<String> {
    let version = name.strip_prefix("IB Gateway ")?;
    let valid = !version.is_empty() && version.split('.').all(|part| !part.is_empty() && part.chars().all(|c| c.is_ascii_digit()));
    valid.then(|| version.to_string())
}

/// Compares "10.50" and "10.9" as numbers, part by part.
fn version_key(version: &str) -> Vec<u32> {
    version.split('.').filter_map(|part| part.parse().ok()).collect()
}

/// The newest complete Gateway install in the given folders (IBKR's installer uses
/// ~/Applications for a normal user, /Applications when run as an admin).
pub fn find_installed_in(folders: &[PathBuf]) -> Option<Installed> {
    let mut found: Vec<Installed> = folders
        .iter()
        .filter_map(|folder| std::fs::read_dir(folder).ok())
        .flatten()
        .filter_map(Result::ok)
        .filter_map(|entry| {
            let version = version_from_folder(&entry.file_name().to_string_lossy())?;
            let installed = Installed { version, path: entry.path() };
            let complete = installed.java().exists() && installed.path.join("jars").is_dir();
            complete.then_some(installed)
        })
        .collect();
    found.sort_by_key(|installed| version_key(&installed.version));
    found.pop()
}

pub fn find_installed() -> Option<Installed> {
    let mut folders = vec![PathBuf::from("/Applications")];
    if let Some(home) = std::env::var_os("HOME") {
        folders.insert(0, Path::new(&home).join("Applications"));
    }
    find_installed_in(&folders)
}

/// IBC's settings file. No credentials: the login sends those to IBC over stdin. IBC applies the
/// API settings to Gateway when it starts, so nobody has to open Gateway's configuration dialog.
pub fn ibc_config(trading_mode: &str, settings_dir: &Path, api_port: u16) -> String {
    format!(
        "\
TradingMode={trading_mode}
IbDir={settings_dir}
OverrideTwsApiPort={api_port}
ReadOnlyApi=yes
AutoRestartTime=11:45 PM
AcceptIncomingConnectionAction=reject
ExistingSessionDetectedAction=primaryoverride
MinimizeMainWindow=yes
ReloginAfterSecondFactorAuthenticationTimeout=no
SecondFactorAuthenticationTimeout=180
LoginDialogDisplayTimeout=60
AcceptNonBrokerageAccountWarning=yes
AllowBlindTrading=no
CommandServerPort=0
SuppressInfoMessages=yes
",
        settings_dir = settings_dir.display()
    )
}

/// Where the installer is: shown on the setup screen while it downloads and opens.
#[derive(Clone, Debug, Default, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Step {
    #[default]
    Idle,
    Downloading,
    Checking,
    /// IBKR's installer is open; the user clicks through it
    InstallerOpen,
    Failed,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct Progress {
    pub step: Step,
    pub received: u64,
    pub total: u64,
    pub error: Option<String>,
}

/// Downloads IBKR's installer and opens it. Runs on a background thread; `update` reports progress.
/// The user then clicks through IBKR's own installer; find_installed() notices when it's done.
pub fn download_and_open_installer(cache_dir: &Path, update: impl Fn(Progress)) -> Result<(), String> {
    let installer = prepare_installer(cache_dir, &update)?;
    let opened = std::process::Command::new("/usr/bin/open").arg(&installer).status().map_err(|e| e.to_string())?;
    if !opened.success() {
        return Err("Couldn't open IBKR's installer.".into());
    }
    update(Progress { step: Step::InstallerOpen, ..Default::default() });
    Ok(())
}

/// Downloads the installer (resuming a partial download), mounts it, and checks it's signed by
/// Interactive Brokers and notarised by Apple. Returns the installer app.
fn prepare_installer(cache_dir: &Path, update: &impl Fn(Progress)) -> Result<PathBuf, String> {
    std::fs::create_dir_all(cache_dir).map_err(|e| e.to_string())?;
    let dmg = cache_dir.join("ibgateway-stable-standalone-macos-arm.dmg");
    let total = remote_size()?;

    let have = std::fs::metadata(&dmg).map(|m| m.len()).unwrap_or(0);
    if have != total {
        let mut curl = std::process::Command::new("/usr/bin/curl")
            .args(["--location", "--fail", "--silent", "--continue-at", "-", "--output"])
            .arg(&dmg)
            .arg(DOWNLOAD_URL)
            .spawn()
            .map_err(|e| format!("couldn't start the download: {e}"))?;
        loop {
            let received = std::fs::metadata(&dmg).map(|m| m.len()).unwrap_or(0);
            update(Progress { step: Step::Downloading, received, total, error: None });
            if let Some(status) = curl.try_wait().map_err(|e| e.to_string())? {
                if !status.success() {
                    return Err("The download from Interactive Brokers failed. Check your internet connection and try again.".into());
                }
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(500));
        }
        if std::fs::metadata(&dmg).map(|m| m.len()).unwrap_or(0) != total {
            let _ = std::fs::remove_file(&dmg);
            return Err("The download was incomplete. Try again.".into());
        }
    }

    update(Progress { step: Step::Checking, received: total, total, error: None });
    let installer = mount_and_find_installer(&dmg, &cache_dir.join("installer-volume"))?;
    if let Err(e) = check_signed_by_ibkr(&installer) {
        unmount_installer(cache_dir);
        return Err(e);
    }
    Ok(installer)
}

/// The installer's size, from the server (so a partial download can be detected and resumed).
fn remote_size() -> Result<u64, String> {
    let output = std::process::Command::new("/usr/bin/curl")
        .args(["--location", "--fail", "--silent", "--head", DOWNLOAD_URL])
        .output()
        .map_err(|e| e.to_string())?;
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter_map(|line| line.to_ascii_lowercase().strip_prefix("content-length:").map(|v| v.trim().to_string()))
        .filter_map(|v| v.parse().ok())
        .last()
        .ok_or_else(|| "Couldn't reach Interactive Brokers' download server. Check your internet connection.".into())
}

/// Mounts the disk image (read-only, hidden from Finder) and returns the installer app inside.
fn mount_and_find_installer(dmg: &Path, mount_point: &Path) -> Result<PathBuf, String> {
    let _ = std::process::Command::new("/usr/bin/hdiutil").arg("detach").arg(mount_point).arg("-quiet").status();
    std::fs::create_dir_all(mount_point).map_err(|e| e.to_string())?;
    let attached = std::process::Command::new("/usr/bin/hdiutil")
        .args(["attach", "-nobrowse", "-readonly", "-noverify", "-quiet", "-mountpoint"])
        .arg(mount_point)
        .arg(dmg)
        .status()
        .map_err(|e| e.to_string())?;
    if !attached.success() {
        let _ = std::fs::remove_file(dmg); // probably corrupt: download again next time
        return Err("The downloaded installer couldn't be opened. Try again.".into());
    }
    std::fs::read_dir(mount_point)
        .map_err(|e| e.to_string())?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .find(|path| path.extension().is_some_and(|ext| ext == "app"))
        .ok_or_else(|| "IBKR's installer wasn't in the download.".into())
}

/// Unmounts the installer's disk image once Gateway is installed (or when the app quits).
pub fn unmount_installer(cache_dir: &Path) {
    let _ = std::process::Command::new("/usr/bin/hdiutil")
        .arg("detach")
        .arg(cache_dir.join("installer-volume"))
        .arg("-quiet")
        .status();
}

/// Interactive Brokers LLC's Apple developer team, which signs their installers
const IBKR_TEAM_ID: &str = "L6H6D9Q7DY";

/// Refuses an installer that isn't signed by Interactive Brokers' developer team and accepted by
/// Gatekeeper (notarised by Apple).
fn check_signed_by_ibkr(app: &Path) -> Result<(), String> {
    let details = std::process::Command::new("/usr/bin/codesign")
        .args(["--display", "--verbose=2"])
        .arg(app)
        .output()
        .map_err(|e| e.to_string())?;
    let signer = String::from_utf8_lossy(&details.stderr);
    let gatekeeper = std::process::Command::new("/usr/sbin/spctl")
        .args(["--assess", "--type", "execute"])
        .arg(app)
        .status()
        .map_err(|e| e.to_string())?;
    let ibkr = signer.lines().any(|line| line == format!("TeamIdentifier={IBKR_TEAM_ID}"));
    if !ibkr || !gatekeeper.success() {
        return Err("The downloaded installer isn't signed by Interactive Brokers, so it wasn't opened.".into());
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reads_versions_from_folder_names() {
        assert_eq!(version_from_folder("IB Gateway 10.50").as_deref(), Some("10.50"));
        assert_eq!(version_from_folder("IB Gateway 10.50 Uninstaller.app"), None);
        assert_eq!(version_from_folder("IB Gateway"), None);
        assert_eq!(version_from_folder("Trader Workstation 10.50"), None);
    }

    #[test]
    fn picks_the_newest_complete_install() {
        let root = std::env::temp_dir().join(format!("gw-test-{}", std::process::id()));
        let make = |name: &str, complete: bool| {
            let dir = root.join(name);
            std::fs::create_dir_all(dir.join("jars")).unwrap();
            if complete {
                let java = dir.join(".install4j/jre.bundle/Contents/Home/bin");
                std::fs::create_dir_all(&java).unwrap();
                std::fs::write(java.join("java"), "").unwrap();
            }
        };
        make("IB Gateway 10.9", true);
        make("IB Gateway 10.50", true);
        make("IB Gateway 10.60", false); // half-installed: ignored
        let found = find_installed_in(&[root.clone()]).unwrap();
        assert_eq!(found.version, "10.50");
        assert_eq!(found.major_version(), "1050");
        std::fs::remove_dir_all(root).unwrap();
    }

    // Looks at this Mac's real Applications folders: cargo test -- --ignored --nocapture
    #[test]
    #[ignore]
    fn finds_gateway_on_this_mac() {
        println!("{:?}", find_installed());
    }

    // Uses the network (or a DMG already in GW_TEST_CACHE): cargo test -- --ignored --nocapture
    #[test]
    #[ignore]
    fn prepares_the_real_installer() {
        let cache = PathBuf::from(std::env::var("GW_TEST_CACHE").unwrap());
        let steps = std::sync::Mutex::new(Vec::new());
        let installer = prepare_installer(&cache, &|p: Progress| steps.lock().unwrap().push(format!("{:?}", p.step))).unwrap();
        println!("installer: {} | steps: {:?}", installer.display(), steps.lock().unwrap().iter().collect::<std::collections::BTreeSet<_>>());
        unmount_installer(&cache);
    }

    #[test]
    #[ignore]
    fn refuses_an_app_not_signed_by_ibkr() {
        // Safari: signed and notarised, but by Apple, not Interactive Brokers
        assert!(check_signed_by_ibkr(Path::new("/Applications/Safari.app")).is_err());
    }

    #[test]
    fn ibc_config_has_api_settings_and_no_credentials() {
        let config = ibc_config("paper", Path::new("/tmp/gw"), 4002);
        assert!(config.contains("OverrideTwsApiPort=4002"));
        assert!(config.contains("ReadOnlyApi=yes"));
        assert!(config.contains("IbDir=/tmp/gw"));
        assert!(!config.contains("IbPassword") && !config.contains("IbLoginId"));
    }
}
