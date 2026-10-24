//! "Block borrowing" (#289): orders that would borrow from IBKR are blocked unless the user switches
//! this off for their IBKR account. Switching it off asks macOS to confirm it's the Mac's owner
//! (Touch ID, or the Mac password: the same prompt as System Settings). Nothing is stored for that;
//! the app only gets a yes or no. The choice is saved per account in settings.json and sent to the
//! backend, which does the blocking (backend/borrowing.py).

/// Asks macOS for Touch ID or the Mac password. Ok(true) when confirmed, Ok(false) when cancelled or
/// failed. Blocks until the user answers, so it's called from an async command (off the main thread).
#[cfg(target_os = "macos")]
pub fn confirm_owner(reason: &str) -> Result<bool, String> {
    use std::sync::{Mutex, mpsc};

    use block2::RcBlock;
    use objc2::runtime::Bool;
    use objc2_foundation::{NSError, NSString};
    use objc2_local_authentication::{LAContext, LAPolicy};

    let (sender, receiver) = mpsc::channel();
    // The reply block may be called on any thread, and only once
    let sender = Mutex::new(Some(sender));
    unsafe {
        let context = LAContext::new();
        if let Err(error) = context.canEvaluatePolicy_error(LAPolicy::DeviceOwnerAuthentication) {
            return Err(format!("This Mac can't confirm it's you ({}).", error.localizedDescription()));
        }
        let reply = RcBlock::new(move |ok: Bool, _error: *mut NSError| {
            if let Some(sender) = sender.lock().unwrap().take() {
                let _ = sender.send(ok.as_bool());
            }
        });
        context.evaluatePolicy_localizedReason_reply(
            LAPolicy::DeviceOwnerAuthentication,
            &NSString::from_str(reason),
            &reply,
        );
        receiver.recv().map_err(|_| "macOS didn't answer.".to_string())
    }
}

#[cfg(not(target_os = "macos"))]
pub fn confirm_owner(_reason: &str) -> Result<bool, String> {
    Err("Only available on a Mac.".into())
}

/// The text macOS shows in its prompt, after "Portfolio Manager is trying to …"
pub const REASON: &str = "allow orders to borrow money from IBKR";
