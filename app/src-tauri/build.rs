// The cockpit is served by the backend over http, which Tauri treats as a
// remote origin. Without an app manifest no app command is allowed from there
// ("Command ... not allowed by ACL"), and the cockpit silently fell back to the
// backend for every app-side reader (2026-09-25). Declaring the commands
// generates allow-<command> permissions that the capabilities grant.
fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "retry_backend",
            "active_hotkey",
            "clipboard_file_paths",
            "open_external_url",
            "reveal_local_path",
            "set_native_color_theme",
            "open_pane_window",
            "focus_pane_window",
            "close_pane_window",
            "open_tour_window",
            "close_tour_window",
        ]),
    ))
    .expect("failed to run tauri-build");
}
