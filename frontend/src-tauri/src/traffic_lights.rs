//! Moves the window's traffic-light buttons inside the sidebar, as in the Figma frames.
//!
//! Tauri's own option for this (`traffic_light_position`) wraps the web view in an extra view,
//! which stopped our page from loading (no requests reached the backend). So the buttons are moved
//! directly on the window instead, the same way wry does it, and again after every resize because
//! macOS lays them out again then.

use tauri::{WebviewWindow, WindowEvent};

/// Where the close button's top-left corner goes, from the window's top-left corner (points)
const X: f64 = 20.0;
const Y: f64 = 22.0;

pub fn inset(window: &WebviewWindow) {
    apply(window);
    let again = window.clone();
    window.on_window_event(move |event| {
        if matches!(event, WindowEvent::Resized(_) | WindowEvent::ScaleFactorChanged { .. } | WindowEvent::Focused(_)) {
            apply(&again);
        }
    });
}

#[cfg(target_os = "macos")]
fn apply(window: &WebviewWindow) {
    use objc2_app_kit::{NSView, NSWindow, NSWindowButton};

    let Ok(pointer) = window.ns_window() else { return };
    let pointer = pointer as usize;
    let _ = window.run_on_main_thread(move || unsafe {
        let window = &*(pointer as *const NSWindow);
        let (Some(close), Some(miniaturize)) = (
            window.standardWindowButton(NSWindowButton::CloseButton),
            window.standardWindowButton(NSWindowButton::MiniaturizeButton),
        ) else {
            return;
        };
        let zoom = window.standardWindowButton(NSWindowButton::ZoomButton);

        // Make the (hidden) title bar tall enough for the buttons at their new height
        let Some(title_bar) = close.superview().and_then(|view| view.superview()) else { return };
        let close_frame = NSView::frame(&close);
        let height = close_frame.size.height + Y;
        let mut title_bar_frame = NSView::frame(&title_bar);
        title_bar_frame.size.height = height;
        title_bar_frame.origin.y = window.frame().size.height - height;
        title_bar.setFrame(title_bar_frame);

        let spacing = NSView::frame(&miniaturize).origin.x - close_frame.origin.x;
        for (i, button) in [Some(close), Some(miniaturize), zoom].into_iter().flatten().enumerate() {
            let mut origin = NSView::frame(&button).origin;
            origin.x = X + i as f64 * spacing;
            button.setFrameOrigin(origin);
        }
    });
}

#[cfg(not(target_os = "macos"))]
fn apply(_window: &WebviewWindow) {}
