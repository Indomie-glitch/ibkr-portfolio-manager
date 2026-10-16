use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Manager, RunEvent};

/// The bundled Python backend (PyInstaller build in Resources/backend), while it runs.
struct Backend(Mutex<Option<Child>>);

const BACKEND_PORT: &str = "8000";

/// Starts the bundled backend. Returns None when there is none, as in `tauri dev`, where you run
/// the backend yourself (uvicorn main:app).
fn start_backend(app: &AppHandle) -> Result<Option<Child>, Box<dyn std::error::Error>> {
    let exe = app.path().resource_dir()?.join("backend").join("portfolio-backend");
    if !exe.exists() {
        log::info!("no bundled backend at {}; expecting one on port {BACKEND_PORT}", exe.display());
        return Ok(None);
    }
    let data_dir = app.path().app_data_dir()?;
    let log_dir = app.path().app_log_dir()?;
    std::fs::create_dir_all(&data_dir)?;
    std::fs::create_dir_all(&log_dir)?;
    let log_file = std::fs::File::create(log_dir.join("backend.log"))?;

    let child = Command::new(exe)
        .args(["--port", BACKEND_PORT])
        .env("PORTFOLIO_DATA_DIR", &data_dir)
        // Kept open while the app runs: the backend exits as soon as it closes, so it can't
        // outlive the app even if the app crashes
        .stdin(Stdio::piped())
        .stdout(log_file.try_clone()?)
        .stderr(log_file)
        .spawn()?;
    Ok(Some(child))
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
            let backend = start_backend(app.handle())?;
            app.manage(Backend(Mutex::new(backend)));
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
