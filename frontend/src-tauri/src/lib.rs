mod secrets;

use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
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
    Ok(Some((backend, connection)))
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
        window = window.initialization_script(&format!(
            "window.__PORTFOLIO_BACKEND__ = {{ url: 'http://127.0.0.1:{}', token: '{}' }};",
            c.port, c.token
        ));
    }
    window.build()?;
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
            open_main_window(app.handle(), connection.as_ref())?;
            send_secrets_to_backend(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![secret_status, save_secret, delete_secret])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut child) = app.state::<Backend>().child.lock().unwrap().take() {
                    stop_backend(&mut child);
                }
            }
        });
}
