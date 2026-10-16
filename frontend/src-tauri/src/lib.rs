mod gateway;
mod secrets;
mod session;
mod settings;
mod traffic_lights;

use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::json;
use tauri::{AppHandle, Manager, RunEvent, State, WebviewUrl, WebviewWindowBuilder};

/// The bundled Python backend (PyInstaller build in Resources/backend), while it runs, and the
/// pipe to its stdin: one JSON message per line (see watch_parent in backend/app_main.py).
struct Backend {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
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
    let backend = Backend { child: Mutex::new(Some(child)), stdin: Mutex::new(Some(stdin)) };
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

/// For relaunching Gateway after its daily restart: the saved username and, if remembered, the
/// password. None when the user turned "Reconnect automatically" off.
fn saved_credentials(app: &AppHandle) -> Option<session::Credentials> {
    let settings = settings::load(app);
    if !settings.auto_reconnect {
        return None;
    }
    Some(session::Credentials { username: settings.ibkr_username?, password: secrets::get("ibkr_password") })
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
    password_saved: bool,
}

/// The username and account type to pre-fill the sign-in form with (never the password).
#[tauri::command]
fn saved_login(app: AppHandle) -> SavedLogin {
    let settings = settings::load(&app);
    SavedLogin {
        username: settings.ibkr_username,
        mode: settings.trading_mode,
        password_saved: secrets::get("ibkr_password").is_some(),
    }
}

/// Signs in to IBKR: saves the username and account type, keeps the password in the Keychain if
/// asked to (or forgets it), and starts Gateway. Follow it with login_state.
#[tauri::command]
fn sign_in(app: AppHandle, username: String, password: String, mode: String, remember: bool) -> Result<(), String> {
    let username = username.trim().to_string();
    if username.is_empty() || password.is_empty() {
        return Err("Enter your IBKR username and password.".into());
    }
    let mut saved = settings::load(&app);
    saved.ibkr_username = Some(username.clone());
    saved.trading_mode = mode.clone();
    settings::save(&app, &saved)?;
    if remember {
        secrets::set("ibkr_password", &password)?;
    } else {
        secrets::delete("ibkr_password")?;
    }
    start_session(&app, session::Credentials { username, password: Some(password) }, &mode)
}

/// Signs in again with the saved username and remembered password (Reconnect, Try Again).
#[tauri::command]
fn reconnect(app: AppHandle) -> Result<(), String> {
    let saved = settings::load(&app);
    let username = saved.ibkr_username.ok_or("password_needed")?;
    let password = secrets::get("ibkr_password").ok_or("password_needed")?;
    start_session(&app, session::Credentials { username, password: Some(password) }, &saved.trading_mode)
}

/// Stops a sign-in in progress (Cancel); keeps the saved login.
#[tauri::command]
fn cancel_sign_in(session: State<SharedSession>) {
    session.stop(session::LoginState::SignedOut);
}

/// Signs out: stops Gateway and forgets the remembered password, so the app doesn't sign in again
/// by itself.
#[tauri::command]
fn sign_out(session: State<SharedSession>) -> Result<(), String> {
    session.stop(session::LoginState::SignedOut);
    secrets::delete("ibkr_password")
}

/// At launch: sign in by itself when the password is remembered and Gateway is installed.
fn sign_in_at_launch(app: AppHandle) {
    std::thread::spawn(move || {
        let settings = settings::load(&app);
        if !settings.auto_reconnect || gateway::find_installed().is_none() {
            return;
        }
        if let (Some(username), Some(password)) = (settings.ibkr_username, secrets::get("ibkr_password")) {
            let credentials = session::Credentials { username, password: Some(password) };
            if let Err(e) = start_session(&app, credentials, &settings.trading_mode) {
                log::error!("couldn't sign in at launch: {e}");
            }
        }
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

/// Hands the secrets the backend needs from the Keychain straight to its memory. Runs after the
/// window opens: macOS may ask permission to read the Keychain (for an unsigned app, after each
/// update), and the app shouldn't sit there without a window while it waits.
fn send_secrets_to_backend(app: AppHandle) {
    std::thread::spawn(move || {
        let backend = app.state::<Backend>();
        for name in secrets::FOR_BACKEND {
            if let Some(value) = secrets::get(name) {
                if let Err(e) = backend.send(json!({ "set_secret": name, "value": value })) {
                    log::error!("couldn't send {name} to the backend: {e}");
                }
            }
        }
    });
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

/// Which secrets are saved (never their values).
#[tauri::command]
fn secret_status() -> HashMap<&'static str, bool> {
    secrets::NAMES.iter().map(|name| (*name, secrets::get(name).is_some())).collect()
}

/// Saves a secret in the Keychain and, if the backend uses it, hands it over right away.
#[tauri::command]
fn save_secret(backend: State<Backend>, name: String, value: String) -> Result<(), String> {
    let value = value.trim();
    if value.is_empty() || value.len() > 1000 {
        return Err("That doesn't look right: it's empty or too long.".into());
    }
    secrets::set(&name, value)?;
    if secrets::FOR_BACKEND.contains(&name.as_str()) {
        backend.send(json!({ "set_secret": name, "value": value }))?;
    }
    Ok(())
}

#[tauri::command]
fn delete_secret(backend: State<Backend>, name: String) -> Result<(), String> {
    secrets::delete(&name)?;
    if secrets::FOR_BACKEND.contains(&name.as_str()) {
        backend.send(json!({ "clear_secret": name }))?;
    }
    Ok(())
}

/// The main window. With a bundled backend, a script run before the page tells the frontend
/// where the backend is and which token to send (api.js reads window.__PORTFOLIO_BACKEND__).
fn open_main_window(app: &AppHandle, connection: Option<&Connection>) -> tauri::Result<()> {
    let mut window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
        .title("Portfolio Manager")
        .inner_size(1320.0, 860.0)
        .min_inner_size(960.0, 640.0)
        .center();
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
                None => (Backend { child: Mutex::new(None), stdin: Mutex::new(None) }, None),
            };
            app.manage(backend);
            app.manage(GatewaySetup(Mutex::new(gateway::Progress::default())));
            app.manage::<SharedSession>(Arc::new(session::Session::default()));
            open_main_window(app.handle(), connection.as_ref())?;
            send_secrets_to_backend(app.handle().clone());
            sign_in_at_launch(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            secret_status,
            save_secret,
            delete_secret,
            get_settings,
            save_settings,
            gateway_status,
            install_gateway,
            login_state,
            saved_login,
            sign_in,
            reconnect,
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
