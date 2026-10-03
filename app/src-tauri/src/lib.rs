use std::{
    collections::HashMap,
    fs,
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::{Path, PathBuf},
    time::Duration,
};

use tauri::{
    AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, State, Theme, Url, WebviewUrl,
    WebviewWindow, WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_global_shortcut::{
    Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutEvent, ShortcutState,
};

const BACKEND_URL: &str = "http://127.0.0.1:8791/cockpit.html";
const FALLBACK_URL: &str = "tauri://localhost/index.html";
const CONFIG_RELATIVE_PATH: &str = ".orrery/config.json";

struct HotkeyBinding(String);

// Ordered fallbacks keep ORRERY usable when a resident macOS utility owns the
// preferred binding. Change this list to customize the application hotkey.
fn hotkey_candidates() -> [(&'static str, Shortcut); 4] {
    [
        (
            "Cmd+Shift+O",
            Shortcut::new(Some(Modifiers::SUPER | Modifiers::SHIFT), Code::KeyO),
        ),
        (
            "Cmd+Ctrl+O",
            Shortcut::new(Some(Modifiers::SUPER | Modifiers::CONTROL), Code::KeyO),
        ),
        (
            "Cmd+Alt+O",
            Shortcut::new(Some(Modifiers::SUPER | Modifiers::ALT), Code::KeyO),
        ),
        (
            "Cmd+Shift+F19",
            Shortcut::new(Some(Modifiers::SUPER | Modifiers::SHIFT), Code::F19),
        ),
    ]
}

fn backend_online() -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], 8791));
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(500)) else {
        return false;
    };

    let _ = stream.set_read_timeout(Some(Duration::from_millis(700)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));

    if stream
        .write_all(
            b"GET /cockpit.html HTTP/1.0\r\nHost: 127.0.0.1:8791\r\nConnection: close\r\n\r\n",
        )
        .is_err()
    {
        return false;
    }

    let mut response = [0_u8; 64];
    let Ok(bytes_read) = stream.read(&mut response) else {
        return false;
    };
    let status_line = String::from_utf8_lossy(&response[..bytes_read]);

    status_line.starts_with("HTTP/1.0 200") || status_line.starts_with("HTTP/1.1 200")
}

fn navigate(window: &WebviewWindow, url: &str) -> Result<(), String> {
    let url = Url::parse(url).map_err(|error| error.to_string())?;
    window.navigate(url).map_err(|error| error.to_string())
}

#[tauri::command]
fn retry_backend(window: WebviewWindow) -> Result<bool, String> {
    if !backend_online() {
        return Ok(false);
    }

    navigate(&window, BACKEND_URL)?;
    Ok(true)
}

#[tauri::command]
fn active_hotkey(binding: State<'_, HotkeyBinding>) -> String {
    binding.0.clone()
}

// Reading the pasteboard belongs to the app, not to the backend.
//
// A browser never learns where a pasted file lives, so the path has to come
// from the pasteboard itself — and whoever reads it must hold a live window
// server session. The Python backend outlives the app that spawns it (browsers
// share it), so it drifts into being an orphan of a long-dead app and then
// reports an empty pasteboard forever: on 2026-08-24 an eight-day-old sidecar
// answered [] for a two-file Finder copy that a freshly started one read
// correctly. The app process cannot drift that way — it *is* the GUI session —
// so the read lives here and the HTTP endpoint stays only as the fallback for
// cockpits opened in an ordinary browser.
#[cfg(target_os = "macos")]
const CLIPBOARD_FILES_JXA: &str = r#"
ObjC.import("AppKit");
const pb = $.NSPasteboard.generalPasteboard;
const items = pb.pasteboardItems;
const out = [];
if (!items.isNil()) {
  for (let i = 0; i < items.count; i++) {
    const s = items.objectAtIndex(i).stringForType("public.file-url");
    if (!s.isNil()) {
      const p = $.NSURL.URLWithString(s).path;
      if (!p.isNil()) out.push(ObjC.unwrap(p));
    }
  }
}
JSON.stringify({changeCount: Number(pb.changeCount) || 0, files: out});
"#;

#[cfg(target_os = "macos")]
#[tauri::command]
fn clipboard_file_paths() -> Result<Vec<String>, String> {
    let output = std::process::Command::new("/usr/bin/osascript")
        .args(["-l", "JavaScript", "-e", CLIPBOARD_FILES_JXA])
        .output()
        .map_err(|error| format!("pasteboard reader could not run: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "pasteboard reader failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    let raw = String::from_utf8_lossy(&output.stdout);
    let parsed: serde_json::Value = serde_json::from_str(raw.trim())
        .map_err(|error| format!("pasteboard reader returned non-JSON: {error}"))?;
    // No change count means no pasteboard connection, which is a different
    // answer from "the clipboard holds no files" and must not be flattened
    // into an empty list.
    if parsed.get("changeCount").and_then(serde_json::Value::as_i64) == Some(0) {
        return Err("pasteboard reports no change count (no window server session)"
            .to_owned());
    }
    Ok(parsed
        .get("files")
        .and_then(serde_json::Value::as_array)
        .map(|entries| {
            entries
                .iter()
                .filter_map(serde_json::Value::as_str)
                .filter(|path| !path.is_empty())
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default())
}

#[cfg(not(target_os = "macos"))]
#[tauri::command]
fn clipboard_file_paths() -> Result<Vec<String>, String> {
    Err("pasteboard file paths are only available on macOS".to_owned())
}

// Opening links from a pane belongs to the app for the same reason as the
// pasteboard: on 2026-09-25 a sidecar left from 2026-09-18 ran `open` for every
// click and answered "opened" while nothing opened, and a freshly started one
// worked. The backend endpoints stay as the fallback for browser-hosted
// cockpits. The rules match the backend's: web URLs only; paths must be
// absolute or ~-relative and exist; a file is revealed, never opened.
fn url_opener_args(url: &str) -> Result<Vec<String>, String> {
    if url.len() > 4096 || url.chars().any(|ch| ch.is_whitespace() || ch.is_control()) {
        return Err("url is empty, too long, or contains whitespace".to_owned());
    }
    let parsed = Url::parse(url).map_err(|error| format!("invalid url: {error}"))?;
    if !matches!(parsed.scheme(), "http" | "https") || parsed.host_str().is_none() {
        return Err("only http(s) URLs can be opened".to_owned());
    }
    Ok(vec![url.to_owned()])
}

fn reveal_opener_args(raw: &str, home: Option<&Path>) -> Result<(String, Vec<String>), String> {
    if raw.is_empty() || raw.len() > 4096 || raw.contains('\0') {
        return Err("path is required".to_owned());
    }
    if !(raw.starts_with('/') || raw.starts_with('~')) {
        return Err("path must be absolute or start with ~".to_owned());
    }
    let path = expand_user_path(raw, home).ok_or("path could not be expanded")?;
    if !path.exists() {
        return Err("no such path".to_owned());
    }
    let shown = path.to_string_lossy().into_owned();
    // Only a plain folder is opened. `open` on a bundle (.app and the like)
    // launches it, and a symlink may lead into one: both are revealed, as the
    // backend does (orrery_backend.reveal_in_finder).
    let is_link = std::fs::symlink_metadata(&path)
        .map(|meta| meta.file_type().is_symlink())
        .unwrap_or(false);
    if !path.is_dir() {
        Ok(("file".to_owned(), vec!["-R".to_owned(), shown]))
    } else if is_link || is_mac_bundle(&path) {
        Ok(("bundle".to_owned(), vec!["-R".to_owned(), shown]))
    } else {
        Ok(("dir".to_owned(), vec![shown]))
    }
}

const MAC_BUNDLE_SUFFIXES: &[&str] = &[
    "app", "appex", "bundle", "framework", "plugin", "kext", "prefpane", "saver", "xpc",
    "qlgenerator", "mdimporter", "component", "action", "workflow", "pkg", "mpkg",
    "photoslibrary", "musiclibrary", "rtfd", "playground", "xcodeproj", "xcworkspace",
    "scptd", "docset",
];

fn is_mac_bundle(path: &Path) -> bool {
    let real = std::fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    if !real.is_dir() {
        return false;
    }
    let suffix = real
        .extension()
        .map(|ext| ext.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    MAC_BUNDLE_SUFFIXES.contains(&suffix.as_str()) || real.join("Contents/Info.plist").is_file()
}

#[cfg(target_os = "macos")]
fn run_open(args: &[String]) -> Result<(), String> {
    let output = std::process::Command::new("/usr/bin/open")
        .args(args)
        .stdin(std::process::Stdio::null())
        .output()
        .map_err(|error| format!("open could not run: {error}"))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(format!(
            "open failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        ))
    }
}

#[cfg(not(target_os = "macos"))]
fn run_open(_: &[String]) -> Result<(), String> {
    Err("opening from the app is only available on macOS".to_owned())
}

#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    run_open(&url_opener_args(url.trim())?)
}

#[tauri::command]
fn reveal_local_path(path: String) -> Result<String, String> {
    let (kind, args) = reveal_opener_args(&path, home_directory().as_deref())?;
    run_open(&args)?;
    Ok(kind)
}

// Pane windows: one session taken out of the cockpit into its own window.
// WKWebView drops window.open, so the cockpit asks the app for the window and
// the app loads the same cockpit page in solo mode from the caller's own
// origin. The window is one more websocket peer on the backend's existing
// recorder; closing it tells the main window, which attaches the session again.
const PANE_WINDOW_PREFIX: &str = "pane-";
const PANE_WINDOW_CLOSED_EVENT: &str = "orrery://pane-window-closed";

fn pane_session_ok(session: &str) -> bool {
    !session.is_empty()
        && session.len() <= 200
        && !session.chars().any(|ch| ch.is_control())
}

// Which backend a cockpit window talks to: its origin plus an explicit ?ws=
// override. Two backends can each have a session with the same name, so the
// window label covers both.
fn pane_backend_scope(origin: &Url) -> String {
    let ws = origin
        .query_pairs()
        .find(|(key, _)| key == "ws")
        .map(|(_, value)| value.into_owned())
        .unwrap_or_default();
    format!(
        "{}://{}:{}\n{ws}",
        origin.scheme(),
        origin.host_str().unwrap_or_default(),
        origin.port_or_known_default().unwrap_or_default()
    )
}

// FNV-1a keeps the label short and within the characters labels accept
// (a-zA-Z, 0-9, '-', '/', ':' and '_') for any session name.
fn pane_window_label(origin: &Url, session: &str) -> String {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in pane_backend_scope(origin)
        .bytes()
        .chain(std::iter::once(0))
        .chain(session.bytes())
    {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("{PANE_WINDOW_PREFIX}{hash:016x}")
}

// Every cockpit window loads a page of the caller's own local origin, keeping
// only the caller's ?ws= backend override next to its own query.
fn cockpit_window_url(origin: &Url, path: &str, pairs: &[(&str, &str)]) -> Result<Url, String> {
    if origin.scheme() != "http" || !matches!(origin.host_str(), Some("127.0.0.1" | "localhost")) {
        return Err("cockpit windows open only from the local cockpit".to_owned());
    }
    let mut url = origin.clone();
    url.set_path(path);
    url.set_fragment(None);
    let ws = origin
        .query_pairs()
        .find(|(key, _)| key == "ws")
        .map(|(_, value)| value.into_owned());
    {
        let mut query = url.query_pairs_mut();
        query.clear();
        for (key, value) in pairs {
            query.append_pair(key, value);
        }
        if let Some(ws) = ws.as_deref() {
            query.append_pair("ws", ws);
        }
    }
    Ok(url)
}

fn pane_window_url(origin: &Url, session: &str) -> Result<Url, String> {
    cockpit_window_url(origin, "/cockpit.html", &[("solo", "1"), ("session", session)])
}

// Builds a cockpit window, or brings back the one already open under the
// label. `closed` is sent to the main window when it goes away.
#[allow(clippy::too_many_arguments)]
fn open_cockpit_window(
    app: &AppHandle,
    label: &str,
    url: Url,
    title: String,
    closed: serde_json::Value,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    if let Some(existing) = app.get_webview_window(label) {
        let _ = existing.unminimize();
        let _ = existing.show();
        return existing.set_focus().map_err(|error| error.to_string());
    }
    let pane = WebviewWindowBuilder::new(app, label, WebviewUrl::External(url))
        .title(title)
        .inner_size(width.clamp(360.0, 4000.0), height.clamp(240.0, 3000.0))
        .min_inner_size(360.0, 240.0)
        .build()
        .map_err(|error| error.to_string())?;
    if x.is_finite() && y.is_finite() {
        let _ = pane.set_position(LogicalPosition::new(x, y));
    }
    let _ = pane.set_size(LogicalSize::new(
        width.clamp(360.0, 4000.0),
        height.clamp(240.0, 3000.0),
    ));
    let notifier = app.clone();
    pane.on_window_event(move |event| {
        if let WindowEvent::Destroyed = event {
            let _ = notifier.emit_to("main", PANE_WINDOW_CLOSED_EVENT, closed.clone());
        }
    });
    Ok(())
}

#[tauri::command]
fn open_pane_window(
    app: AppHandle,
    window: WebviewWindow,
    session: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    if !pane_session_ok(&session) {
        return Err("invalid session name".to_owned());
    }
    let origin = window.url().map_err(|error| error.to_string())?;
    let url = pane_window_url(&origin, &session)?;
    let label = pane_window_label(&origin, &session);
    // The payload carries the window's own address so the cockpit can tell
    // which backend it belonged to: the same session name on another backend
    // is another window.
    let closed = serde_json::json!({ "session": session, "url": url.as_str() });
    open_cockpit_window(&app, &label, url, format!("{session} · ORRERY"), closed, x, y, width, height)
}

// Focus and close resolve the label from the caller's own address, so a
// cockpit on one backend never reaches another backend's window. The pane
// window's address carries the same origin and ?ws= as the cockpit's.
fn caller_pane_label(window: &WebviewWindow, session: &str) -> Result<String, String> {
    let origin = window.url().map_err(|error| error.to_string())?;
    Ok(pane_window_label(&origin, session))
}

#[tauri::command]
fn focus_pane_window(app: AppHandle, window: WebviewWindow, session: String) -> Result<(), String> {
    let pane = app
        .get_webview_window(&caller_pane_label(&window, &session)?)
        .ok_or("no such pane window")?;
    let _ = pane.unminimize();
    let _ = pane.show();
    pane.set_focus().map_err(|error| error.to_string())
}

#[tauri::command]
fn close_pane_window(app: AppHandle, window: WebviewWindow, session: String) -> Result<(), String> {
    match app.get_webview_window(&caller_pane_label(&window, &session)?) {
        Some(pane) => pane.close().map_err(|error| error.to_string()),
        None => Ok(()),
    }
}

// Tour windows: a tour checklist (cockpit_tour.js) in a window of its own,
// tour.html?tour=<id>, a page with the checklist alone. The label keeps the pane- prefix so the
// pane capability covers it; the key starts with a control character, which no
// session name may contain, so a tour never takes a pane's window.
fn tour_id_ok(tour: &str) -> bool {
    !tour.is_empty()
        && tour.len() <= 64
        && tour.chars().all(|ch| ch.is_ascii_alphanumeric() || ch == '-' || ch == '_')
}

fn tour_window_key(tour: &str) -> String {
    format!("\u{1}tour\u{1}{tour}")
}

fn tour_window_url(origin: &Url, tour: &str) -> Result<Url, String> {
    if !tour_id_ok(tour) {
        return Err("invalid tour id".to_owned());
    }
    cockpit_window_url(origin, "/tour.html", &[("tour", tour)])
}

#[tauri::command]
fn open_tour_window(
    app: AppHandle,
    window: WebviewWindow,
    tour: String,
    x: f64,
    y: f64,
    width: f64,
    height: f64,
) -> Result<(), String> {
    let origin = window.url().map_err(|error| error.to_string())?;
    let url = tour_window_url(&origin, &tour)?;
    let label = pane_window_label(&origin, &tour_window_key(&tour));
    let closed = serde_json::json!({ "tour": tour, "url": url.as_str() });
    open_cockpit_window(&app, &label, url, "Tour · ORRERY".to_owned(), closed, x, y, width, height)
}

#[tauri::command]
fn close_tour_window(app: AppHandle, window: WebviewWindow, tour: String) -> Result<(), String> {
    if !tour_id_ok(&tour) {
        return Err("invalid tour id".to_owned());
    }
    let origin = window.url().map_err(|error| error.to_string())?;
    match app.get_webview_window(&pane_window_label(&origin, &tour_window_key(&tour))) {
        Some(pane) => pane.close().map_err(|error| error.to_string()),
        None => Ok(()),
    }
}

fn native_theme(preference: &str) -> Result<Option<Theme>, String> {
    match preference {
        "dark" => Ok(Some(Theme::Dark)),
        "light" => Ok(Some(Theme::Light)),
        "system" => Ok(None),
        _ => Err(format!("unknown color theme preference: {preference}")),
    }
}

#[cfg(target_os = "macos")]
fn set_dock_icon(app: &AppHandle, resolved: &str) -> Result<(), String> {
    use objc2::AllocAnyThread;
    use objc2_app_kit::{NSApplication, NSImage};
    use objc2_foundation::{MainThreadMarker, NSData};

    let bytes: &'static [u8] = match resolved {
        "dark" => include_bytes!("../icons/icon.png"),
        "light" => include_bytes!("../icons/icon-light.png"),
        _ => return Err(format!("unknown resolved color theme: {resolved}")),
    };
    app.run_on_main_thread(move || {
        let Some(marker) = MainThreadMarker::new() else {
            eprintln!("failed to update ORRERY Dock icon off the main thread");
            return;
        };
        let data = NSData::with_bytes(bytes);
        let Some(icon) = NSImage::initWithData(NSImage::alloc(), &data) else {
            eprintln!("failed to decode ORRERY Dock icon");
            return;
        };
        let application = NSApplication::sharedApplication(marker);
        unsafe { application.setApplicationIconImage(Some(&icon)) };
    })
    .map_err(|error| error.to_string())
}

#[cfg(not(target_os = "macos"))]
fn set_dock_icon(_: &AppHandle, resolved: &str) -> Result<(), String> {
    match resolved {
        "dark" | "light" => Ok(()),
        _ => Err(format!("unknown resolved color theme: {resolved}")),
    }
}

#[tauri::command]
fn set_native_color_theme(
    app: AppHandle,
    window: WebviewWindow,
    preference: String,
    resolved: String,
) -> Result<(), String> {
    window
        .set_theme(native_theme(&preference)?)
        .map_err(|error| error.to_string())?;
    set_dock_icon(&app, &resolved)
}

fn home_directory() -> Option<PathBuf> {
    std::env::var_os("HOME")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
}

fn expand_user_path(value: &str, home: Option<&Path>) -> Option<PathBuf> {
    let value = value.trim();
    if value.is_empty() {
        return None;
    }

    if value == "~" {
        return home.map(Path::to_path_buf);
    }
    if let Some(relative) = value.strip_prefix("~/") {
        return home.map(|directory| directory.join(relative));
    }

    Some(PathBuf::from(value))
}

fn load_orrery_config(home: Option<&Path>) -> HashMap<String, serde_json::Value> {
    let Some(home) = home else {
        return HashMap::new();
    };
    let path = home.join(CONFIG_RELATIVE_PATH);
    let contents = match fs::read_to_string(&path) {
        Ok(contents) => contents,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return HashMap::new(),
        Err(error) => {
            eprintln!("ORRERY config unreadable at {}: {error}", path.display());
            return HashMap::new();
        }
    };

    match serde_json::from_str::<serde_json::Value>(&contents) {
        Ok(serde_json::Value::Object(values)) => values.into_iter().collect(),
        Ok(_) => {
            eprintln!(
                "ORRERY config must contain a top-level JSON object: {}",
                path.display()
            );
            HashMap::new()
        }
        Err(error) => {
            eprintln!(
                "ORRERY config is invalid JSON at {}: {error}",
                path.display()
            );
            HashMap::new()
        }
    }
}

fn env_path(name: &str, home: Option<&Path>) -> Option<PathBuf> {
    std::env::var(name)
        .ok()
        .and_then(|value| expand_user_path(&value, home))
}

fn config_path(
    config: &HashMap<String, serde_json::Value>,
    name: &str,
    home: Option<&Path>,
) -> Option<PathBuf> {
    config
        .get(name)
        .and_then(serde_json::Value::as_str)
        .and_then(|value| expand_user_path(value, home))
}

fn backend_sidecar_paths() -> Result<(PathBuf, PathBuf), String> {
    let home = home_directory();
    let config = load_orrery_config(home.as_deref());
    let root = env_path("AGENTSTACK_ORRERY_ROOT", home.as_deref())
        .or_else(|| config_path(&config, "orrery_root", home.as_deref()));

    let python = env_path("ORRERY_BACKEND_PYTHON", home.as_deref()).or_else(|| {
        root.as_ref()
            .map(|path| path.join("bridge/.venv/bin/python"))
    });
    let script = env_path("ORRERY_BACKEND_SCRIPT", home.as_deref()).or_else(|| {
        root.as_ref()
            .map(|path| path.join("bridge/orrery_backend.py"))
    });

    match (python, script) {
        (Some(python), Some(script)) => Ok((python, script)),
        _ => Err(format!(
            "backend location is not configured; set AGENTSTACK_ORRERY_ROOT or \
             ORRERY_BACKEND_PYTHON and ORRERY_BACKEND_SCRIPT, or add orrery_root to ~/{CONFIG_RELATIVE_PATH}"
        )),
    }
}

fn backend_log_stdio() -> (std::process::Stdio, std::process::Stdio) {
    let log = home_directory().map(|home| home.join("Library/Logs/ORRERY/backend.log"));
    let opened = log.and_then(|path| {
        std::fs::create_dir_all(path.parent()?).ok()?;
        std::fs::OpenOptions::new().create(true).append(true).open(path).ok()
    });
    match opened.and_then(|file| Some((file.try_clone().ok()?, file))) {
        Some((out, err)) => (out.into(), err.into()),
        None => (std::process::Stdio::null(), std::process::Stdio::null()),
    }
}

// Spawn the backend as a detached sidecar. The process intentionally outlives
// the app (browsers and other clients share the same backend); it is cheap
// while idle and attaches tmux sessions lazily.
fn spawn_backend_sidecar() -> Result<(), String> {
    let (python, script) = backend_sidecar_paths()?;

    if !python.exists() || !script.exists() {
        return Err(format!(
            "configured backend sidecar unavailable (python: {}, script: {})",
            python.display(),
            script.display()
        ));
    }

    // The sidecar's own diagnostics (opener and pasteboard failures) used to go
    // to /dev/null, so a sidecar that had lost the window server left no trace.
    // It prints only on errors; append them to a per-user log.
    let (stdout, stderr) = backend_log_stdio();
    match std::process::Command::new(&python)
        .arg(&script)
        .stdin(std::process::Stdio::null())
        .stdout(stdout)
        .stderr(stderr)
        .spawn()
    {
        Ok(child) => {
            println!("ORRERY backend sidecar: spawned pid {}", child.id());
            Ok(())
        }
        Err(error) => Err(format!("backend sidecar spawn failed: {error}")),
    }
}

fn toggle_window(app: &AppHandle, _shortcut: &Shortcut, event: ShortcutEvent) {
    if event.state != ShortcutState::Pressed {
        return;
    }

    let Some(window) = app.get_webview_window("main") else {
        return;
    };

    match window.is_visible() {
        Ok(true) => {
            let _ = window.hide();
        }
        Ok(false) => {
            let _ = window.show();
            let _ = window.set_focus();
        }
        Err(error) => eprintln!("failed to read ORRERY window visibility: {error}"),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .setup(|app| {
            let mut active_hotkey = None;
            for (label, shortcut) in hotkey_candidates() {
                match app.global_shortcut().on_shortcut(shortcut, toggle_window) {
                    Ok(()) => {
                        println!("ORRERY global hotkey: {label}");
                        active_hotkey = Some(label);
                        break;
                    }
                    Err(error) => eprintln!("hotkey {label} unavailable: {error}"),
                }
            }

            let active_hotkey = active_hotkey.unwrap_or("unavailable");
            if active_hotkey == "unavailable" {
                eprintln!("no ORRERY global hotkey could be registered");
            }
            app.manage(HotkeyBinding(active_hotkey.to_owned()));

            if !backend_online() {
                // Offline page keeps retrying every 3 s and auto-navigates to
                // the cockpit once the sidecar is up.
                if let Err(reason) = spawn_backend_sidecar() {
                    eprintln!("ORRERY remains offline: {reason}");
                }
                let window = app
                    .get_webview_window("main")
                    .ok_or("ORRERY main window was not created")?;
                navigate(&window, FALLBACK_URL)?;
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            retry_backend,
            active_hotkey,
            clipboard_file_paths,
            open_external_url,
            reveal_local_path,
            set_native_color_theme,
            open_pane_window,
            focus_pane_window,
            close_pane_window,
            open_tour_window,
            close_tour_window
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn url_opener_accepts_only_web_urls() {
        assert_eq!(
            url_opener_args("https://github.com/a/b").unwrap(),
            vec!["https://github.com/a/b".to_owned()]
        );
        assert!(url_opener_args("file:///etc/passwd").is_err());
        assert!(url_opener_args("x-apple.systempreferences:").is_err());
        assert!(url_opener_args("https://a.example/ b").is_err());
        assert!(url_opener_args("").is_err());
    }

    #[test]
    fn reveal_opener_reveals_files_and_opens_directories() {
        let dir = std::env::temp_dir().join(format!("orrery-reveal-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let file = dir.join("note.md");
        std::fs::write(&file, "x").unwrap();

        let (kind, args) = reveal_opener_args(dir.to_str().unwrap(), None).unwrap();
        assert_eq!(kind, "dir");
        assert_eq!(args, vec![dir.to_string_lossy().into_owned()]);

        let (kind, args) = reveal_opener_args(file.to_str().unwrap(), None).unwrap();
        assert_eq!(kind, "file");
        assert_eq!(args, vec!["-R".to_owned(), file.to_string_lossy().into_owned()]);

        let (kind, _) = reveal_opener_args("~/note.md", Some(&dir)).unwrap();
        assert_eq!(kind, "file");

        assert!(reveal_opener_args("relative/path", None).is_err());
        assert!(reveal_opener_args("/definitely/not/here", None).is_err());
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn reveal_opener_never_opens_a_bundle_or_a_link() {
        let dir = std::env::temp_dir().join(format!("orrery-bundle-{}", std::process::id()));
        let app = dir.join("Report.app");
        let odd = dir.join("Odd Name");
        std::fs::create_dir_all(app.join("Contents")).unwrap();
        std::fs::create_dir_all(odd.join("Contents")).unwrap();
        std::fs::write(odd.join("Contents/Info.plist"), "x").unwrap();
        let plain = dir.join("plain");
        std::fs::create_dir_all(&plain).unwrap();
        let link = dir.join("link-to-plain");
        std::os::unix::fs::symlink(&plain, &link).unwrap();
        let app_link = dir.join("link-to-app");
        std::os::unix::fs::symlink(&app, &app_link).unwrap();

        for target in [&app, &odd, &link, &app_link] {
            let (kind, args) = reveal_opener_args(target.to_str().unwrap(), None).unwrap();
            assert_eq!(kind, "bundle", "{target:?}");
            assert_eq!(args[0], "-R", "{target:?} would be opened");
        }
        let (kind, args) = reveal_opener_args(plain.to_str().unwrap(), None).unwrap();
        assert_eq!((kind.as_str(), args.len()), ("dir", 1));
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn expands_tilde_from_the_supplied_home() {
        let home = Path::new("/tmp/orrery-home");
        assert_eq!(
            expand_user_path("~/.local/bin/python", Some(home)),
            Some(home.join(".local/bin/python"))
        );
    }

    #[test]
    fn ignores_empty_and_non_string_config_values() {
        let config = HashMap::from([
            (
                "empty".to_owned(),
                serde_json::Value::String("  ".to_owned()),
            ),
            ("number".to_owned(), serde_json::Value::from(7)),
        ]);
        let home = Path::new("/tmp/orrery-home");
        assert_eq!(config_path(&config, "empty", Some(home)), None);
        assert_eq!(config_path(&config, "number", Some(home)), None);
        assert_eq!(config_path(&config, "missing", Some(home)), None);
    }

    #[test]
    fn pane_window_labels_are_valid_and_scoped_to_the_backend() {
        let cockpit = Url::parse("http://127.0.0.1:8791/cockpit.html").unwrap();
        let label = pane_window_label(&cockpit, "Coral Curie/日本");
        assert!(label.starts_with(PANE_WINDOW_PREFIX));
        assert!(label[PANE_WINDOW_PREFIX.len()..]
            .chars()
            .all(|ch| ch.is_ascii_hexdigit()));
        assert_ne!(pane_window_label(&cockpit, "a_b"), pane_window_label(&cockpit, "a-b"));

        // The pane window's own address resolves to the same label.
        let pane = pane_window_url(&cockpit, "Coral Curie/日本").unwrap();
        assert_eq!(pane_window_label(&pane, "Coral Curie/日本"), label);

        // Same session name on another backend: a different window.
        let other_ws = Url::parse("http://127.0.0.1:8791/cockpit.html?ws=ws://127.0.0.1:9/ws").unwrap();
        let other_port = Url::parse("http://127.0.0.1:8797/cockpit.html").unwrap();
        assert_ne!(pane_window_label(&other_ws, "Coral Curie/日本"), label);
        assert_ne!(pane_window_label(&other_port, "Coral Curie/日本"), label);
        let other_pane = pane_window_url(&other_ws, "Coral Curie/日本").unwrap();
        assert_eq!(
            pane_window_label(&other_pane, "Coral Curie/日本"),
            pane_window_label(&other_ws, "Coral Curie/日本")
        );
    }

    #[test]
    fn pane_window_url_keeps_origin_and_ws_only() {
        let origin = Url::parse("http://127.0.0.1:8791/cockpit.html?ws=ws://127.0.0.1:9/ws&x=1#top").unwrap();
        let url = pane_window_url(&origin, "Coral Curie&x").unwrap();
        assert_eq!(url.host_str(), Some("127.0.0.1"));
        assert_eq!(url.port(), Some(8791));
        assert_eq!(url.path(), "/cockpit.html");
        assert_eq!(url.fragment(), None);
        let pairs: Vec<(String, String)> = url
            .query_pairs()
            .map(|(key, value)| (key.into_owned(), value.into_owned()))
            .collect();
        assert_eq!(
            pairs,
            vec![
                ("solo".to_owned(), "1".to_owned()),
                ("session".to_owned(), "Coral Curie&x".to_owned()),
                ("ws".to_owned(), "ws://127.0.0.1:9/ws".to_owned()),
            ]
        );
        assert!(pane_window_url(&Url::parse("https://example.com/cockpit.html").unwrap(), "a").is_err());
        assert!(pane_window_url(&Url::parse("tauri://localhost/index.html").unwrap(), "a").is_err());
    }

    #[test]
    fn tour_window_url_carries_only_the_tour_and_ws() {
        let origin = Url::parse("http://127.0.0.1:8791/cockpit.html?ws=ws://127.0.0.1:9/ws&solo=1&session=x#top").unwrap();
        let url = tour_window_url(&origin, "first-flight").unwrap();
        assert_eq!(url.path(), "/tour.html");
        assert_eq!(url.fragment(), None);
        let pairs: Vec<(String, String)> = url
            .query_pairs()
            .map(|(key, value)| (key.into_owned(), value.into_owned()))
            .collect();
        assert_eq!(
            pairs,
            vec![
                ("tour".to_owned(), "first-flight".to_owned()),
                ("ws".to_owned(), "ws://127.0.0.1:9/ws".to_owned()),
            ]
        );
        assert!(tour_window_url(&origin, "").is_err());
        assert!(tour_window_url(&origin, "a&solo=1").is_err());
        assert!(tour_window_url(&origin, &"x".repeat(65)).is_err());
        assert!(tour_window_url(&Url::parse("https://example.com/cockpit.html").unwrap(), "full-tour").is_err());
    }

    #[test]
    fn tour_window_labels_never_meet_a_pane_label() {
        let origin = Url::parse("http://127.0.0.1:8791/cockpit.html").unwrap();
        let tour = pane_window_label(&origin, &tour_window_key("first-flight"));
        assert!(tour.starts_with(PANE_WINDOW_PREFIX));
        // A session literally named like the tour key is refused, so it cannot share the label.
        assert!(!pane_session_ok(&tour_window_key("first-flight")));
        assert_ne!(tour, pane_window_label(&origin, "first-flight"));
        assert_ne!(tour, pane_window_label(&origin, &tour_window_key("full-tour")));
    }

    #[test]
    fn pane_session_names_are_bounded() {
        assert!(pane_session_ok("CoralCurie"));
        assert!(!pane_session_ok(""));
        assert!(!pane_session_ok("bad\nname"));
        assert!(!pane_session_ok(&"x".repeat(201)));
    }

    #[test]
    fn validates_native_theme_preferences() {
        assert_eq!(native_theme("dark"), Ok(Some(Theme::Dark)));
        assert_eq!(native_theme("light"), Ok(Some(Theme::Light)));
        assert_eq!(native_theme("system"), Ok(None));
        assert!(native_theme("sepia").is_err());
    }
}
