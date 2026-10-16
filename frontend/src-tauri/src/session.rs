//! The IB Gateway session. Starts Gateway hidden through IBC with the user's credentials (sent
//! over stdin, never in a file or on the command line), follows the login in IBC's and Gateway's
//! logs, relaunches Gateway after its daily restart, notices when the session ends, and stops
//! Gateway when the user signs out or the app quits.

use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::Serialize;

use crate::gateway::{self, Installed};

/// Where the sign-in is, for the login screens.
#[derive(Clone, Debug, Default, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum LoginState {
    #[default]
    SignedOut,
    /// Gateway is starting (hidden)
    Starting,
    /// The login form was sent to IBKR
    SigningIn,
    /// IBKR sent an approval request to the IBKR Mobile app (live accounts)
    AwaitingApproval,
    SignedIn,
    /// IBKR rejected the username or password (or there were too many attempts)
    WrongPassword { too_many_attempts: bool },
    /// The phone approval was declined or timed out
    NotApproved,
    /// Signed in earlier, but the session ended: logged in elsewhere, the weekly re-login, or
    /// Gateway stopped
    SessionEnded { reason: EndReason },
    /// Something else went wrong (not installed, couldn't start)
    Error { message: String },
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum EndReason {
    /// The same username logged in somewhere else (TWS, the mobile app, the website)
    LoggedInElsewhere,
    /// IBKR needs a full sign-in again (weekly), and the password isn't remembered
    SignInAgain,
    /// Gateway stopped unexpectedly
    GatewayStopped,
}

impl LoginState {
    fn is_final_failure(&self) -> bool {
        matches!(self, LoginState::WrongPassword { .. } | LoginState::NotApproved | LoginState::Error { .. })
    }
}

/// What it takes to start Gateway: where everything is, and the account.
#[derive(Clone)]
pub struct Launch {
    pub installed: Installed,
    /// IBC.jar and portfolio-launcher.jar (Resources/ibc in the app)
    pub ibc_dir: PathBuf,
    /// Gateway's own settings for this account type (Application Support/gateway/<mode>)
    pub settings_dir: PathBuf,
    pub log_path: PathBuf,
    pub api_port: u16,
    /// "paper" or "live"
    pub mode: String,
}

/// The running Gateway and the login state. A "run" number makes the log readers and the exit
/// watcher of an older Gateway ignore themselves once a newer one has started.
#[derive(Default)]
pub struct Session {
    state: Mutex<LoginState>,
    child: Mutex<Option<Child>>,
    run: AtomicU64,
}

impl Session {
    pub fn state(&self) -> LoginState {
        self.state.lock().unwrap().clone()
    }

    fn set_state(&self, run: u64, state: LoginState) {
        if self.run.load(Ordering::SeqCst) != run {
            return;
        }
        let failed = state.is_final_failure();
        *self.state.lock().unwrap() = state;
        if failed {
            // Don't leave Gateway sitting on its error dialog; the error stays on screen and
            // nothing relaunches it (watch_exit sees the failure)
            let child = self.child.lock().unwrap().take();
            if let Some(mut child) = child {
                std::thread::spawn(move || stop_process(&mut child));
            }
        }
    }

    /// Stops Gateway (if running) and forgets its run, so nothing relaunches it.
    pub fn stop(&self, state: LoginState) {
        self.run.fetch_add(1, Ordering::SeqCst);
        if let Some(mut child) = self.child.lock().unwrap().take() {
            stop_process(&mut child);
        }
        *self.state.lock().unwrap() = state;
    }
}

fn stop_process(child: &mut Child) {
    unsafe {
        libc::kill(child.id() as libc::pid_t, libc::SIGTERM);
    }
    for _ in 0..50 {
        if let Ok(Some(_)) = child.try_wait() {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let _ = child.kill();
    let _ = child.wait();
}

/// Credentials for one launch. `None` for the password when it isn't remembered: then Gateway can
/// only come back after its daily restart if IBKR doesn't ask for a full sign-in.
pub struct Credentials {
    pub username: String,
    pub password: Option<String>,
}

/// Starts Gateway and signs in. `restart` is Gateway's autorestart folder after its daily restart
/// (no full sign-in needed); `fetch_credentials` is called again for each relaunch.
pub fn start(
    session: Arc<Session>,
    launch: Launch,
    credentials: Credentials,
    restart: Option<String>,
    fetch_credentials: Arc<dyn Fn() -> Option<Credentials> + Send + Sync>,
) -> Result<(), String> {
    // Stop any earlier Gateway first
    let run = {
        let old = session.child.lock().unwrap().take();
        if let Some(mut child) = old {
            stop_process(&mut child);
        }
        session.run.fetch_add(1, Ordering::SeqCst) + 1
    };
    session.set_state(run, LoginState::Starting);

    std::fs::create_dir_all(&launch.settings_dir).map_err(|e| e.to_string())?;
    let ini = launch.settings_dir.join("ibc.ini");
    std::fs::write(&ini, gateway::ibc_config(&launch.mode, &launch.settings_dir, launch.api_port))
        .map_err(|e| e.to_string())?;

    let restarting = restart.is_some();
    let mut child = java_command(&launch, &ini, restart.as_deref())?
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Couldn't start IB Gateway: {e}"))?;

    // Username and password over stdin (read by StdinLauncher), then close it
    {
        let mut stdin = child.stdin.take().ok_or("Gateway stdin unavailable")?;
        let password = credentials.password.as_deref().unwrap_or("");
        writeln!(stdin, "{}\n{}", credentials.username, password).map_err(|e| e.to_string())?;
    }
    let has_password = credentials.password.is_some();
    drop(credentials);

    let log = Arc::new(Mutex::new(
        std::fs::OpenOptions::new().create(true).append(true).open(&launch.log_path).map_err(|e| e.to_string())?,
    ));
    for stream in [child.stdout.take().map(|s| Box::new(s) as Box<dyn std::io::Read + Send>),
                   child.stderr.take().map(|s| Box::new(s) as Box<dyn std::io::Read + Send>)]
        .into_iter()
        .flatten()
    {
        let (session, log) = (session.clone(), log.clone());
        std::thread::spawn(move || {
            for line in BufReader::new(stream).lines().map_while(Result::ok) {
                let _ = writeln!(log.lock().unwrap(), "{line}");
                if let Some(state) = state_from_ibc_line(&line, has_password || !restarting) {
                    session.set_state(run, state);
                }
            }
        });
    }
    *session.child.lock().unwrap() = Some(child);

    watch_gateway_log(session.clone(), run, launch.settings_dir.join("launcher.log"));
    watch_exit(session, run, launch, fetch_credentials);
    Ok(())
}

/// What a line of IBC's output says about the login. `can_sign_in` is false when Gateway was
/// relaunched without a password: if it then asks for a full sign-in, the user has to do it.
fn state_from_ibc_line(line: &str, can_sign_in: bool) -> Option<LoginState> {
    if line.contains("Login dialog WINDOW_OPENED") && !can_sign_in {
        return Some(LoginState::SessionEnded { reason: EndReason::SignInAgain });
    }
    if line.contains("Starting Gateway") {
        Some(LoginState::Starting)
    } else if line.contains("Setting user name") {
        Some(LoginState::SigningIn)
    } else if line.contains("Second Factor Authentication initiated") {
        Some(LoginState::AwaitingApproval)
    } else if line.contains("Re-login after second factor authentication timeout") {
        Some(LoginState::NotApproved)
    } else if line.contains("Login has completed") {
        Some(LoginState::SignedIn)
    } else if line.contains("Too many failed login attempts") {
        Some(LoginState::WrongPassword { too_many_attempts: true })
    } else if line.contains("Unrecognized Username or Password") || line.contains("IBC: Login failed") {
        Some(LoginState::WrongPassword { too_many_attempts: false })
    } else if line.contains("End this session and let the other session proceed")
        || line.contains("so end this session")
    {
        Some(LoginState::SessionEnded { reason: EndReason::LoggedInElsewhere })
    } else {
        None
    }
}

/// Gateway's own log names the exact reason when IBKR refuses a login.
fn watch_gateway_log(session: Arc<Session>, run: u64, path: PathBuf) {
    std::thread::spawn(move || {
        // Start from the end: older runs' lines are already in the file
        let mut offset = std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
        while session.run.load(Ordering::SeqCst) == run {
            std::thread::sleep(Duration::from_millis(500));
            let Ok(text) = std::fs::read(&path) else { continue };
            if (text.len() as u64) < offset {
                offset = 0; // the log was replaced
            }
            let new = String::from_utf8_lossy(&text[offset as usize..]).to_string();
            offset = text.len() as u64;
            if new.contains("Authorization failed") || new.contains("INVALID_USERNAME") {
                session.set_state(run, LoginState::WrongPassword { too_many_attempts: false });
            }
        }
    });
}

/// When Gateway exits: relaunch it after its daily restart, otherwise report why the session ended.
/// After a failed login it's never relaunched (IBC asks for a "cold restart", which would retry
/// the same password).
fn watch_exit(
    session: Arc<Session>,
    run: u64,
    launch: Launch,
    fetch_credentials: Arc<dyn Fn() -> Option<Credentials> + Send + Sync>,
) {
    std::thread::spawn(move || loop {
        std::thread::sleep(Duration::from_millis(500));
        if session.run.load(Ordering::SeqCst) != run {
            return; // stopped or replaced
        }
        let exited = {
            let mut child = session.child.lock().unwrap();
            match child.as_mut().map(|c| c.try_wait()) {
                Some(Ok(Some(_))) => {
                    child.take();
                    true
                }
                _ => false,
            }
        };
        if !exited {
            continue;
        }
        let state = session.state();
        if state.is_final_failure() {
            return; // keep the error on screen; don't retry
        }
        if let (Some(folder), Some(credentials)) = (autorestart_folder(&launch.settings_dir), fetch_credentials()) {
            let _ = start(session.clone(), launch.clone(), credentials, Some(folder), fetch_credentials.clone());
            return;
        }
        let ended = match state {
            LoginState::SessionEnded { .. } => state,
            LoginState::SignedIn => LoginState::SessionEnded { reason: EndReason::GatewayStopped },
            _ => LoginState::Error { message: "IB Gateway stopped before signing in.".into() },
        };
        session.set_state(run, ended);
        return;
    });
}

/// Gateway leaves an "autorestart" file one folder down in its settings folder when it restarts
/// itself daily; that folder's name, passed back as -Drestart, lets it reconnect without a full
/// sign-in (the same as IBC's start script does).
fn autorestart_folder(settings_dir: &Path) -> Option<String> {
    let mut found = std::fs::read_dir(settings_dir)
        .ok()?
        .filter_map(Result::ok)
        .filter(|entry| entry.path().join("autorestart").is_file())
        .map(|entry| entry.file_name().to_string_lossy().to_string());
    let first = found.next()?;
    // More than one means IBC can't tell which is right either: full sign-in then
    found.next().is_none().then_some(first)
}

/// The same command IBC's start script would run, but without its side effects (it renames
/// Gateway's app) and with our launcher, which reads the credentials from stdin.
fn java_command(launch: &Launch, ini: &Path, restart: Option<&str>) -> Result<Command, String> {
    let gateway_dir = &launch.installed.path;
    let install4j = gateway_dir.join(".install4j");
    let params = std::fs::read_to_string(install4j.join("i4jparams.conf")).map_err(|e| e.to_string())?;
    let extra_options = params
        .split("<variable name=\"javaOptions\" value=\"")
        .nth(1)
        .and_then(|rest| rest.split('"').next())
        .map(|value| value.replace("&quot;", "\"").replace("&amp;", "&"))
        .unwrap_or_default();
    let vm_options: Vec<String> = std::fs::read_to_string(gateway_dir.join("ibgateway.vmoptions"))
        .map_err(|e| e.to_string())?
        .lines()
        .map(str::trim)
        .filter(|line| !line.is_empty() && !line.starts_with('#') && !line.starts_with("-D"))
        .map(String::from)
        .collect();
    let mut jars: Vec<PathBuf> = std::fs::read_dir(gateway_dir.join("jars"))
        .map_err(|e| e.to_string())?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "jar"))
        .collect();
    jars.sort();
    jars.push(install4j.join("i4jruntime.jar"));
    jars.push(launch.ibc_dir.join("IBC.jar"));
    jars.push(launch.ibc_dir.join("portfolio-launcher.jar"));
    let classpath = jars.iter().map(|p| p.display().to_string()).collect::<Vec<_>>().join(":");

    let mut command = Command::new(launch.installed.java());
    command
        .args(extra_options.split_whitespace())
        .arg("-cp")
        .arg(classpath)
        .args(&vm_options)
        .arg("-Dtwslaunch.autoupdate.serviceImpl=com.ib.tws.twslaunch.install4j.Install4jAutoUpdateService")
        .arg("-Dchannel=latest")
        .arg("-Dexe4j.isInstall4j=true")
        .arg("-Dinstall4jType=standalone")
        .arg(format!("-DjtsConfigDir={}", launch.settings_dir.display()))
        .arg(format!("-Dibcsessionid={:08x}", std::process::id() ^ (std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.subsec_nanos()).unwrap_or(0))))
        // No Dock icon or menu bar: the user never deals with Gateway directly
        .arg("-Dapple.awt.UIElement=true");
    if let Some(folder) = restart {
        command.arg(format!("-Drestart={folder}"));
    }
    command.arg("portfolio.StdinLauncher").arg(ini).arg(&launch.mode).current_dir(&launch.settings_dir);
    Ok(command)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Launches the real Gateway (opt-in: cargo test --lib real_sign_in -- --ignored --nocapture).
    /// Credentials come from PM_TEST_USER / PM_TEST_PASSWORD, or are asked for in the terminal
    /// (password hidden). Uses a temporary settings folder and port 4012.
    #[test]
    #[ignore]
    fn real_sign_in() {
        let read = |prompt: &str, hidden: bool| -> String {
            print!("{prompt}");
            std::io::stdout().flush().unwrap();
            if hidden {
                let _ = Command::new("stty").arg("-echo").stdin(Stdio::inherit()).status();
            }
            let mut line = String::new();
            std::io::stdin().read_line(&mut line).unwrap();
            if hidden {
                let _ = Command::new("stty").arg("echo").stdin(Stdio::inherit()).status();
                println!();
            }
            line.trim_end_matches(['\r', '\n']).to_string()
        };
        let username = std::env::var("PM_TEST_USER").unwrap_or_else(|_| read("IBKR paper username: ", false));
        let password = std::env::var("PM_TEST_PASSWORD").unwrap_or_else(|_| read("IBKR paper password (hidden): ", true));
        let dir = std::env::temp_dir().join(format!("pm-session-test-{}", std::process::id()));
        let launch = Launch {
            installed: gateway::find_installed().expect("IB Gateway installed"),
            ibc_dir: PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("ibc/dist"),
            settings_dir: dir.join("gateway"),
            log_path: dir.join("gateway.log"),
            api_port: 4012,
            mode: "paper".into(),
        };
        let session = Arc::new(Session::default());
        let check_password = password.clone();
        start(session.clone(), launch, Credentials { username, password: Some(password) }, None, Arc::new(|| None)).unwrap();

        let pid = session.child.lock().unwrap().as_ref().map(|c| c.id()).unwrap();
        let args = Command::new("ps").args(["-o", "command=", "-p", &pid.to_string()]).output().unwrap();
        println!("password in process list: {}", String::from_utf8_lossy(&args.stdout).contains(&check_password));

        let mut last = LoginState::SignedOut;
        let started = std::time::Instant::now();
        while started.elapsed() < Duration::from_secs(120) {
            let state = session.state();
            if state != last {
                println!("{:>5.1}s  {:?}", started.elapsed().as_secs_f32(), state);
                last = state.clone();
            }
            if state == LoginState::SignedIn || state.is_final_failure() {
                break;
            }
            std::thread::sleep(Duration::from_millis(200));
        }
        // After a failure, Gateway must stop by itself and never be relaunched
        std::thread::sleep(Duration::from_secs(8));
        let running = session.child.lock().unwrap().as_mut().map(|c| c.try_wait().map(|s| s.is_none()).unwrap_or(false)).unwrap_or(false);
        println!("after 8 s: state {:?}, Gateway still running: {running}", session.state());
        let found = std::fs::read_dir(&dir).map(|_| {
            fn walk(p: &Path, needle: &[u8]) -> Vec<PathBuf> {
                std::fs::read_dir(p).into_iter().flatten().flatten().flat_map(|e| {
                    let path = e.path();
                    if path.is_dir() { walk(&path, needle) }
                    else if std::fs::read(&path).map(|b| b.windows(needle.len()).any(|w| w == needle)).unwrap_or(false) { vec![path] }
                    else { vec![] }
                }).collect()
            }
            walk(&dir, check_password.as_bytes())
        }).unwrap_or_default();
        println!("password found in files: {found:?}");
        session.stop(LoginState::SignedOut);
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn reads_login_progress_from_ibc_output() {
        let read = |line| state_from_ibc_line(line, true);
        assert_eq!(read("2026-10-16 19:00:01:000 IBC: Setting user name"), Some(LoginState::SigningIn));
        assert_eq!(read("IBC: Second Factor Authentication initiated"), Some(LoginState::AwaitingApproval));
        assert_eq!(read("2026-10-16 19:00:15:143 IBC: Login has completed"), Some(LoginState::SignedIn));
        assert_eq!(
            read("IBC: detected dialog entitled: Unrecognized Username or Password; event=Opened"),
            Some(LoginState::WrongPassword { too_many_attempts: false })
        );
        assert_eq!(
            read("IBC: End this session and let the other session proceed (scenario 2)"),
            Some(LoginState::SessionEnded { reason: EndReason::LoggedInElsewhere })
        );
        assert_eq!(read("IBC: Click button: OK"), None);
    }

    #[test]
    fn relaunch_without_password_asks_the_user_to_sign_in() {
        assert_eq!(
            state_from_ibc_line("IBC: Login dialog WINDOW_OPENED: LoginState is LOGGED_OUT", false),
            Some(LoginState::SessionEnded { reason: EndReason::SignInAgain })
        );
        assert_eq!(state_from_ibc_line("IBC: Login dialog WINDOW_OPENED: LoginState is LOGGED_OUT", true), None);
    }

    #[test]
    fn finds_a_single_autorestart_folder() {
        let dir = std::env::temp_dir().join(format!("autorestart-test-{}", std::process::id()));
        std::fs::create_dir_all(dir.join("abc123")).unwrap();
        assert_eq!(autorestart_folder(&dir), None);
        std::fs::write(dir.join("abc123/autorestart"), "").unwrap();
        assert_eq!(autorestart_folder(&dir).as_deref(), Some("abc123"));
        std::fs::create_dir_all(dir.join("def456")).unwrap();
        std::fs::write(dir.join("def456/autorestart"), "").unwrap();
        assert_eq!(autorestart_folder(&dir), None); // ambiguous: full sign-in
        std::fs::remove_dir_all(dir).unwrap();
    }
}
