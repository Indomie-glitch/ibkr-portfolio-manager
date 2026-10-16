use std::io::{Read, Write};
use std::net::TcpListener;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

/// The bundled Python backend (PyInstaller build in Resources/backend), while it runs.
struct Backend(Mutex<Option<Child>>);

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
fn start_backend(app: &AppHandle) -> Result<Option<(Child, Connection)>, Box<dyn std::error::Error>> {
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
    let stdin = child.stdin.as_mut().ok_or("backend stdin unavailable")?;
    writeln!(stdin, "{}", connection.token)?;
    stdin.flush()?;
    Ok(Some((child, connection)))
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
            let (child, connection) = match start_backend(app.handle())? {
                Some((child, connection)) => (Some(child), Some(connection)),
                None => (None, None),
            };
            app.manage(Backend(Mutex::new(child)));
            open_main_window(app.handle(), connection.as_ref())?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut child) = app.state::<Backend>().0.lock().unwrap().take() {
                    stop_backend(&mut child);
                }
            }
        });
}
