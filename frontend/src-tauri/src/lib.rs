mod gateway;
mod session;
mod settings;
mod traffic_lights;
mod updater;

use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::json;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, Url, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_opener::OpenerExt;

/// The bundled Python backend (PyInstaller build in Resources/backend), while it runs, and the
/// pipe to its stdin: one JSON message per line (see watch_parent in backend/app_main.py).
struct Backend {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
    /// Whether the user has given an Anthropic key this session (it lives only in the backend's
    /// memory and is gone when the app quits)
    api_key_set: std::sync::atomic::AtomicBool,
}

impl Backend {
    fn send(&self, message: serde_json::Value) -> Result<(), String> {
        if let Some(stdin) = self.stdin.lock().unwrap().as_mut() {
            writeln!(stdin, "{message}").and_then(|_| stdin.flush()).map_err(|e| e.to_string())?;
        }
        Ok(())
    }
}

/// Where the frontend finds the backend, and the access token every request must carry.
struct Connection {
    port: u16,
    token: String,
}

/// A port nothing is using right now (the OS picks one), so the app never clashes with another
/// program or a backend you run yourself on 8000.
fn free_port() -> std::io::Result<u16> {
    Ok(TcpListener::bind("127.0.0.1:0")?.local_addr()?.port())
}

/// 32 random bytes as hex, new at every launch.
fn random_token() -> std::io::Result<String> {
    let mut bytes = [0u8; 32];
    std::fs::File::open("/dev/urandom")?.read_exact(&mut bytes)?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

/// Starts the bundled backend. Returns None when there is none, as in `tauri dev`, where you run
/// the backend yourself (uvicorn main:app on port 8000, no token).
fn start_backend(app: &AppHandle) -> Result<Option<(Backend, Connection)>, Box<dyn std::error::Error>> {
    let exe = app.path().resource_dir()?.join("backend").join("portfolio-backend");
    if !exe.exists() {
        log::info!("no bundled backend at {}; expecting one on port 8000", exe.display());
        return Ok(None);
    }
    let data_dir = app.path().app_data_dir()?;
    let log_dir = app.path().app_log_dir()?;
    std::fs::create_dir_all(&data_dir)?;
    std::fs::create_dir_all(&log_dir)?;
    let log_file = std::fs::File::create(log_dir.join("backend.log"))?;

    let connection = Connection { port: free_port()?, token: random_token()? };
    let mut child = Command::new(exe)
        .args(["--port", &connection.port.to_string(), "--token-stdin"])
        .env("PORTFOLIO_DATA_DIR", &data_dir)
        // The token goes over stdin, never on the command line where other programs can see it.
        // stdin then stays open while the app runs: the backend exits as soon as it closes, so it
        // can't outlive the app even if the app crashes
        .stdin(Stdio::piped())
        .stdout(log_file.try_clone()?)
        .stderr(log_file)
        .spawn()?;
    let mut stdin = child.stdin.take().ok_or("backend stdin unavailable")?;
    writeln!(stdin, "{}", connection.token)?;
    stdin.flush()?;
    let backend = Backend { child: Mutex::new(Some(child)), stdin: Mutex::new(Some(stdin)), api_key_set: Default::default() };
    send_settings_to_backend(&backend, &settings::load(app))?;
    Ok(Some((backend, connection)))
}

fn send_settings_to_backend(backend: &Backend, settings: &settings::Settings) -> Result<(), String> {
    backend.send(json!({ "set_setting": "ib_port", "value": settings.gateway_port }))?;
    backend.send(json!({ "set_setting": "ai_model", "value": settings.ai_model }))
}

// ---------- IBKR sign-in (IB Gateway through IBC, see session.rs) ----------

type SharedSession = Arc<session::Session>;

/// IBC and our launcher: Resources/ibc in the app; ibc/dist (from build-ibc.sh) in `tauri dev`.
fn ibc_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let bundled = app.path().resource_dir().map_err(|e| e.to_string())?.join("ibc");
    if bundled.join("IBC.jar").exists() {
        return Ok(bundled);
    }
    let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("ibc/dist");
    if dev.join("IBC.jar").exists() {
        return Ok(dev);
    }
    Err("IBC is missing from the app.".into())
}

fn launch_for(app: &AppHandle, mode: &str) -> Result<session::Launch, String> {
    let installed = gateway::find_installed().ok_or("IB Gateway isn't installed yet.")?;
    let data_dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    let log_dir = app.path().app_log_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&log_dir).map_err(|e| e.to_string())?;
    Ok(session::Launch {
        installed,
        ibc_dir: ibc_dir(app)?,
        // Gateway's own settings, per account type, kept away from any Gateway you run yourself (~/Jts)
        settings_dir: data_dir.join("gateway").join(mode),
        log_path: log_dir.join("gateway.log"),
        api_port: settings::load(app).gateway_port,
        mode: mode.to_string(),
    })
}

/// For relaunching Gateway after its daily restart, which needs no password: the saved username.
/// None when the user turned "Reconnect automatically" off.
fn saved_credentials(app: &AppHandle) -> Option<session::Credentials> {
    let settings = settings::load(app);
    if !settings.auto_reconnect {
        return None;
    }
    Some(session::Credentials { username: settings.ibkr_username?, password: None })
}

fn start_session(app: &AppHandle, credentials: session::Credentials, mode: &str) -> Result<(), String> {
    let launch = launch_for(app, mode)?;
    let handle = app.clone();
    session::start(
        app.state::<SharedSession>().inner().clone(),
        launch,
        credentials,
        None,
        Arc::new(move || saved_credentials(&handle)),
    )
}

#[tauri::command]
fn login_state(session: State<SharedSession>) -> session::LoginState {
    session.state()
}

#[derive(serde::Serialize)]
struct SavedLogin {
    username: Option<String>,
    mode: String,
}

/// The username and account type to pre-fill the sign-in form with (from settings.json; the
/// password is never stored).
#[tauri::command]
fn saved_login(app: AppHandle) -> SavedLogin {
    let settings = settings::load(&app);
    SavedLogin { username: settings.ibkr_username, mode: settings.trading_mode }
}

/// Signs in to IBKR: saves the username and account type for next time and starts Gateway. The
/// password goes to Gateway once and isn't kept. Follow it with login_state.
#[tauri::command]
fn sign_in(app: AppHandle, username: String, password: String, mode: String) -> Result<(), String> {
    let username = username.trim().to_string();
    if username.is_empty() || password.is_empty() {
        return Err("Enter your IBKR username and password.".into());
    }
    let mut saved = settings::load(&app);
    saved.ibkr_username = Some(username.clone());
    saved.trading_mode = mode.clone();
    settings::save(&app, &saved)?;
    start_session(&app, session::Credentials { username, password: Some(password) }, &mode)
}

/// Stops a sign-in in progress (Cancel).
#[tauri::command]
fn cancel_sign_in(session: State<SharedSession>) {
    session.stop(session::LoginState::SignedOut);
}

/// Signs out: stops Gateway.
#[tauri::command]
fn sign_out(session: State<SharedSession>) {
    session.stop(session::LoginState::SignedOut);
}

/// Keychain items that earlier builds created (service com.indomieglitch.portfoliomanager)
const OLD_KEYCHAIN_ITEMS: [&str; 5] = ["anthropic-api-key", "anthropic_api_key", "ibkr_password", "ibkr_username", "app-secrets"];

/// Once: deletes the Keychain items of earlier builds without reading them, using macOS's own
/// `security` tool (the app has no Keychain code any more). Runs in the background after the
/// window opens.
fn remove_old_keychain_items(app: AppHandle) {
    std::thread::spawn(move || {
        let mut saved = settings::load(&app);
        if saved.keychain_removed {
            return;
        }
        for account in OLD_KEYCHAIN_ITEMS {
            // Repeat in case an item exists more than once; stops when there's none left
            for _ in 0..5 {
                let deleted = Command::new("/usr/bin/security")
                    .args(["delete-generic-password", "-s", "com.indomieglitch.portfoliomanager", "-a", account])
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .status()
                    .is_ok_and(|status| status.success());
                if !deleted {
                    break;
                }
            }
        }
        saved.keychain_removed = true;
        let _ = settings::save(&app, &saved);
    });
}

#[tauri::command]
fn get_settings(app: AppHandle) -> settings::Settings {
    settings::load(&app)
}

/// Saves the settings and applies them to the running backend right away.
#[tauri::command]
fn save_settings(app: AppHandle, backend: State<Backend>, settings: settings::Settings) -> Result<(), String> {
    settings::save(&app, &settings)?;
    send_settings_to_backend(&backend, &settings)
}

/// Gateway setup in progress (download, checking, installer open).
struct GatewaySetup(Mutex<gateway::Progress>);

#[derive(serde::Serialize)]
struct GatewayStatus {
    installed: Option<gateway::Installed>,
    setup: gateway::Progress,
}

/// Whether IB Gateway is installed, and how its download or installer is going.
#[tauri::command]
fn gateway_status(app: AppHandle, setup: State<GatewaySetup>) -> Result<GatewayStatus, String> {
    let installed = gateway::find_installed();
    let mut progress = setup.0.lock().unwrap();
    if installed.is_some() && matches!(progress.step, gateway::Step::InstallerOpen) {
        // Installed: the installer's disk image isn't needed any more
        gateway::unmount_installer(&app.path().app_cache_dir().map_err(|e| e.to_string())?);
        *progress = gateway::Progress::default();
    }
    Ok(GatewayStatus { installed, setup: progress.clone() })
}

/// Downloads IBKR's installer and opens it, in the background (follow it with gateway_status).
#[tauri::command]
fn install_gateway(app: AppHandle, setup: State<GatewaySetup>) -> Result<(), String> {
    {
        let mut progress = setup.0.lock().unwrap();
        if matches!(progress.step, gateway::Step::Downloading | gateway::Step::Checking) {
            return Ok(()); // already on its way
        }
        *progress = gateway::Progress { step: gateway::Step::Downloading, ..Default::default() };
    }
    let cache_dir = app.path().app_cache_dir().map_err(|e| e.to_string())?;
    std::thread::spawn(move || {
        let setup = app.state::<GatewaySetup>();
        let result = gateway::download_and_open_installer(&cache_dir, |progress| *setup.0.lock().unwrap() = progress);
        if let Err(error) = result {
            *setup.0.lock().unwrap() = gateway::Progress { step: gateway::Step::Failed, error: Some(error), ..Default::default() };
        }
    });
    Ok(())
}

/// Whether an Anthropic key has been given this session.
#[tauri::command]
fn api_key_status(backend: State<Backend>) -> bool {
    backend.api_key_set.load(std::sync::atomic::Ordering::SeqCst)
}

/// Hands the Anthropic key to the backend, which keeps it in memory only. Nothing is stored: it's
/// gone when the app quits.
#[tauri::command]
fn set_api_key(backend: State<Backend>, key: String) -> Result<(), String> {
    let key = key.trim();
    if key.is_empty() || key.len() > 1000 {
        return Err("That doesn't look right: it's empty or too long.".into());
    }
    backend.send(json!({ "set_secret": "anthropic_api_key", "value": key }))?;
    backend.api_key_set.store(true, std::sync::atomic::Ordering::SeqCst);
    Ok(())
}

#[tauri::command]
fn clear_api_key(backend: State<Backend>) -> Result<(), String> {
    backend.send(json!({ "clear_secret": "anthropic_api_key" }))?;
    backend.api_key_set.store(false, std::sync::atomic::Ordering::SeqCst);
    Ok(())
}

/// The main window. With a bundled backend, a script run before the page tells the frontend
/// where the backend is and which token to send (api.js reads window.__PORTFOLIO_BACKEND__).
fn open_main_window(app: &AppHandle, connection: Option<&Connection>) -> tauri::Result<()> {
    let mut window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Portfolio Manager")
        .inner_size(1320.0, 860.0)
        .min_inner_size(960.0, 640.0)
        .center()
        // The app takes no file drops; Tauri's own drop handling would get in the way of the page's
        // drag and drop (dragging stocks onto watchlists, #88)
        .disable_drag_drop_handler();
    // Links to websites (news, company sites, citations, the Flex guide) open in the default browser:
    // a link that asks for a new window (target="_blank") or would take the app's page away (#202)
    let for_new_window = app.clone();
    let for_navigation = app.clone();
    window = window
        .on_new_window(move |url, _features| {
            open_in_browser(&for_new_window, &url);
            tauri::webview::NewWindowResponse::Deny
        })
        .on_navigation(move |url| {
            if is_app_page(url) {
                return true;
            }
            open_in_browser(&for_navigation, url);
            false
        });
    if let Some(c) = connection {
        // Starts as the small startup window; the page sizes it for each screen (appWindow.js).
        // No visible title bar, as in the Figma frames: the traffic lights sit over the content
        window = window
            .inner_size(360.0, 280.0)
            .min_inner_size(360.0, 280.0)
            .resizable(false)
            .title_bar_style(tauri::TitleBarStyle::Overlay)
            .hidden_title(true);
        window = window.initialization_script(&format!(
            "window.__PORTFOLIO_BACKEND__ = {{ url: 'http://127.0.0.1:{}', token: '{}' }};",
            c.port, c.token
        ));
    }
    let window = window.build()?;
    if connection.is_some() {
        traffic_lights::inset(&window);
    }
    Ok(())
}

/// Before an update replaces the app bundle: stops IB Gateway (ending the IBKR session) and the
/// backend, both of which run from inside the bundle, and waits for them to exit.
/// The app's own page: the bundled frontend (tauri://localhost), or the Vite dev server during
/// `npm run tauri dev`. Anything else is a link out.
fn is_app_page(url: &Url) -> bool {
    url.scheme() == "tauri"
        || url.scheme() == "about"
        || (tauri::is_dev() && url.scheme() == "http" && matches!(url.host_str(), Some("localhost") | Some("127.0.0.1")))
}

/// Only http and https links leave the app: never a file, another app's URL scheme or javascript:
/// (a news headline's link comes from Yahoo).
fn is_web_link(url: &Url) -> bool {
    matches!(url.scheme(), "http" | "https")
}

/// Opens a web link in the default browser.
fn open_in_browser(app: &AppHandle, url: &Url) {
    if !is_web_link(url) {
        log::warn!("Not opening a link with the {} scheme", url.scheme());
        return;
    }
    if let Err(e) = app.opener().open_url(url.as_str(), None::<&str>) {
        log::warn!("Couldn't open a link in the browser: {e}");
    }
}

pub(crate) fn shutdown_for_update(app: &AppHandle) {
    app.state::<SharedSession>().stop(session::LoginState::SignedOut);
    let backend = app.state::<Backend>();
    backend.stdin.lock().unwrap().take();
    if let Some(mut child) = backend.child.lock().unwrap().take() {
        stop_backend(&mut child);
    }
}

/// The macOS menu: the default one plus, under the app name after About, "Check for Updates…" and
/// "Settings…" (⌘,). Choosing one tells the page: to check for an update (and to say so if there's
/// none), or to open the Settings sheet.
fn add_app_menu_items(app: &AppHandle) -> tauri::Result<()> {
    use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
    let menu = Menu::default(app)?;
    if let Some(app_menu) = menu.items()?.first().and_then(|item| item.as_submenu().cloned()) {
        let check = MenuItem::with_id(app, "check_for_updates", "Check for Updates…", true, None::<&str>)?;
        app_menu.insert(&check, 1)?;
        let separator = PredefinedMenuItem::separator(app)?;
        app_menu.insert(&separator, 2)?;
        let settings = MenuItem::with_id(app, "open_settings", "Settings…", true, Some("CmdOrCtrl+,"))?;
        app_menu.insert(&settings, 3)?;
    }
    app.set_menu(menu)?;
    app.on_menu_event(|app, event| {
        if event.id() == "check_for_updates" {
            let _ = app.emit("check-for-updates", ());
        } else if event.id() == "open_settings" {
            let _ = app.emit("open-settings", ());
        }
    });
    Ok(())
}

/// Asks the backend to shut down cleanly (uvicorn closes the IB connection on SIGTERM), and
/// forces it after 3 seconds.
fn stop_backend(child: &mut Child) {
    unsafe {
        libc::kill(child.id() as libc::pid_t, libc::SIGTERM);
    }
    for _ in 0..30 {
        if let Ok(Some(_)) = child.try_wait() {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let _ = child.kill();
    let _ = child.wait();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        // The plugin's own click script would take over target="_blank" links, call the opener from
        // JavaScript (not allowed by our capabilities, so the click did nothing, #276) and stop the
        // window's new-window handler below from seeing them. Links are opened there instead.
        .plugin(tauri_plugin_opener::Builder::new().open_js_links_on_click(false).build())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            let (backend, connection) = match start_backend(app.handle())? {
                Some((backend, connection)) => (backend, Some(connection)),
                None => (Backend { child: Mutex::new(None), stdin: Mutex::new(None), api_key_set: Default::default() }, None),
            };
            app.manage(backend);
            app.manage(GatewaySetup(Mutex::new(gateway::Progress::default())));
            app.manage::<SharedSession>(Arc::new(session::Session::default()));
            updater::manage(app.handle());
            add_app_menu_items(app.handle())?;
            open_main_window(app.handle(), connection.as_ref())?;
            remove_old_keychain_items(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            api_key_status,
            set_api_key,
            clear_api_key,
            updater::check_for_update,
            updater::download_update,
            updater::install_update,
            updater::restart_app,
            updater::open_release_page,
            get_settings,
            save_settings,
            gateway_status,
            install_gateway,
            login_state,
            saved_login,
            sign_in,
            cancel_sign_in,
            sign_out
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                app.state::<SharedSession>().stop(session::LoginState::SignedOut);
                if let Ok(cache_dir) = app.path().app_cache_dir() {
                    gateway::unmount_installer(&cache_dir);
                }
                if let Some(mut child) = app.state::<Backend>().child.lock().unwrap().take() {
                    stop_backend(&mut child);
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn url(text: &str) -> Url {
        text.parse().unwrap()
    }

    #[test]
    fn only_web_links_leave_the_app() {
        assert!(is_web_link(&url("https://www.reuters.com/markets/story")));
        assert!(is_web_link(&url("http://example.com")));
        assert!(!is_web_link(&url("file:///etc/passwd")));
        assert!(!is_web_link(&url("javascript:alert(1)")));
        assert!(!is_web_link(&url("tauri://localhost/index.html")));
        assert!(!is_web_link(&url("mailto:someone@example.com")));
    }

    #[test]
    fn the_apps_own_page_stays_in_the_window() {
        assert!(is_app_page(&url("tauri://localhost/index.html")));
        assert!(is_app_page(&url("about:blank")));
        assert!(!is_app_page(&url("https://finance.yahoo.com/news/story")));
        assert!(!is_app_page(&url("https://localhost.evil.example/")));
    }

    // #276: the opener plugin's own click script swallowed every target="_blank" link (its
    // JavaScript call isn't allowed by our capabilities), so links must be left to open_main_window's
    // handlers. Split with concat! so this test's own text doesn't match.
    #[test]
    fn the_opener_plugin_leaves_link_clicks_to_the_window() {
        let source = include_str!("lib.rs");
        assert!(source.contains(concat!("open_js_links_on_click", "(false)")));
        assert!(!source.contains(concat!("tauri_plugin_opener", "::init()")));
    }
}
