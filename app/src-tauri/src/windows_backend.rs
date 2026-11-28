use std::{
    env,
    io::{self, Read, Write},
    net::{SocketAddr, TcpStream},
    os::windows::process::CommandExt,
    path::PathBuf,
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

use serde_json::{json, Value};
use tauri::{Manager, WebviewWindow};

const DEFAULT_PORT: u16 = 8791;
const CREATE_NO_WINDOW: u32 = 0x08000000;
const WSL_LAUNCHER: &str = include_str!("wsl-backend.sh");
const COCKPIT_CAPABILITY: &str = include_str!("../capabilities/default.json");

fn configured_port() -> Result<u16, String> {
    match env::var("ORRERY_WSL_PORT") {
        Ok(port) => port
            .parse::<u16>()
            .ok()
            .filter(|port| *port != 0)
            .ok_or_else(|| "ORRERY_WSL_PORT must be a port number from 1 to 65535.".to_owned()),
        Err(env::VarError::NotPresent) => Ok(DEFAULT_PORT),
        Err(_) => Err("ORRERY_WSL_PORT must be a port number from 1 to 65535.".to_owned()),
    }
}

fn cockpit_health(body: &str) -> Result<Value, String> {
    let mut health: Value = serde_json::from_str(body).map_err(|error| error.to_string())?;
    if health["backend"] != "ok"
        || health["boot"]
            .as_str()
            .filter(|boot| !boot.is_empty())
            .is_none()
        || !health["runtime"].is_object()
    {
        return Err("Unexpected cockpit health response.".to_owned());
    }
    // Telemetry can change state between the two probes. The rest identifies
    // the backend process and its runtime.
    health
        .as_object_mut()
        .expect("verified health object")
        .remove("dashboard");
    Ok(health)
}

fn windows_health(port: u16) -> Result<Option<Value>, String> {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = match TcpStream::connect_timeout(&address, Duration::from_millis(500)) {
        Ok(stream) => stream,
        // A closed loopback port can time out before Winsock reports refusal.
        // The WSL probe and health comparison still decide whether to connect.
        Err(error)
            if matches!(
                error.kind(),
                io::ErrorKind::ConnectionRefused | io::ErrorKind::TimedOut
            ) =>
        {
            return Ok(None);
        }
        Err(error) => {
            return Err(format!(
                "Could not connect to Windows localhost port {port}: {error}"
            ))
        }
    };
    let collision = || {
        format!(
        "Windows localhost port {port} did not answer as ORRERY. Check the service using this port or set ORRERY_WSL_PORT to a free port."
    )
    };
    stream
        .set_read_timeout(Some(Duration::from_secs(3)))
        .map_err(|_| collision())?;
    stream
        .set_write_timeout(Some(Duration::from_secs(1)))
        .map_err(|_| collision())?;
    write!(
        stream,
        "GET /telemetry/health HTTP/1.0\r\nHost: {address}\r\nConnection: close\r\n\r\n"
    )
    .map_err(|_| collision())?;
    let mut response = String::new();
    stream
        .take(65537)
        .read_to_string(&mut response)
        .map_err(|_| collision())?;
    if response.len() > 65536 {
        return Err(collision());
    }
    let (head, body) = response.split_once("\r\n\r\n").ok_or_else(collision)?;
    if !head.starts_with("HTTP/1.0 200 ") && !head.starts_with("HTTP/1.1 200 ") {
        return Err(collision());
    }
    cockpit_health(body).map(Some).map_err(|_| collision())
}

fn run_in_wsl(port: u16, mode: &str, args: &[&str]) -> Result<String, String> {
    let system_root = env::var_os("SystemRoot").ok_or("Windows SystemRoot is unavailable.")?;
    let mut command = Command::new(PathBuf::from(system_root).join("System32/wsl.exe"));
    for (name, flag) in [
        ("ORRERY_WSL_DISTRO", "--distribution"),
        ("ORRERY_WSL_USER", "--user"),
    ] {
        if let Some(value) = env::var_os(name).filter(|value| !value.is_empty()) {
            command.arg(flag).arg(value);
        }
    }
    let mut child = command
        .args(["--cd", "~", "--exec", "bash", "-s", "--"])
        .arg(port.to_string())
        .arg(mode)
        .arg(env::var_os("ORRERY_WSL_ROOT").unwrap_or_default())
        .args(args)
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("Could not start WSL. Check that WSL2 is installed. {error}"))?;
    let written = child
        .stdin
        .take()
        .expect("piped WSL stdin")
        .write_all(WSL_LAUNCHER.as_bytes());
    let output = child
        .wait_with_output()
        .map_err(|error| error.to_string())?;
    if !output.status.success() {
        let detail = String::from_utf8_lossy(&output.stderr).replace('\0', "");
        let detail = detail.trim();
        return if detail.is_empty() {
            Err(format!(
                "WSL exited with {}. Check the selected WSL2 distro and user.",
                output.status
            ))
        } else {
            Err(detail.to_owned())
        };
    }
    written.map_err(|error| error.to_string())?;
    String::from_utf8(output.stdout).map_err(|_| "Invalid WSL cockpit response.".to_owned())
}

fn parse_wsl_health(port: u16, output: &str) -> Result<Value, String> {
    let mut fields = output.splitn(3, '\0');
    let (Some(plan), Some(root), Some(health)) = (fields.next(), fields.next(), fields.next())
    else {
        return Err("Could not verify WSL cockpit startup.".to_owned());
    };
    let plan = super::parse_startup_plan(plan.as_bytes())?;
    let health = cockpit_health(health).map_err(|_| {
        format!("WSL port {port} did not answer as ORRERY. Check the service using this port or set ORRERY_WSL_PORT to a free port.")
    })?;
    if health["root"] != root {
        return Err(format!("WSL port {port} serves a different checkout. Check ORRERY_WSL_ROOT or choose a free ORRERY_WSL_PORT."));
    }
    if (plan["identity"]["runtime_mode"] == "fresh" || health["runtime"]["runtime_mode"] == "fresh")
        && health["runtime"] != plan["identity"]
    {
        return Err(
            "WSL cockpit runtime identity mismatch. Check the selected checkout and runtime."
                .to_owned(),
        );
    }
    Ok(health)
}

fn verified_port() -> Result<u16, String> {
    let port = configured_port()?;
    let existing = windows_health(port)?;
    let output = run_in_wsl(port, if existing.is_none() { "start" } else { "probe" }, &[])?;
    let expected = parse_wsl_health(port, &output)?;
    wait_for_forwarding(port, &expected)?;
    Ok(port)
}

fn wait_for_forwarding(port: u16, expected: &Value) -> Result<(), String> {
    // A newly started WSL listener can take a moment to reach Windows.
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        match windows_health(port)? {
            Some(health) if &health == expected => return Ok(()),
            Some(_) => return Err(format!(
                "Windows port {port} reaches a different cockpit. Check the selected WSL distro and user or set ORRERY_WSL_PORT."
            )),
            None if Instant::now() >= deadline => return Err(format!(
                "The cockpit is running in WSL, but Windows cannot reach port {port}. Check WSL localhost forwarding."
            )),
            None => thread::sleep(Duration::from_millis(250)),
        }
    }
}

fn backend_status_at(port: u16) -> Result<Value, String> {
    let Some(health) = windows_health(port)? else {
        return Ok(json!({"state":"unavailable"}));
    };
    let result = run_in_wsl(port, "status", &[])?;
    let version: Value = serde_json::from_str(&result).map_err(|_| "Invalid WSL version response.")?;
    if matches!(version["state"].as_str(), Some("current" | "stale"))
        && (version["boot"] != health["boot"]
            || version["running_commit"] != health["commit"]
            || version["root"] != health["root"]
            || version["runtime"] != health["runtime"])
    {
        return Err("Windows localhost is connected to a different cockpit.".to_owned());
    }
    Ok(version)
}

pub(super) fn backend_status() -> Result<Value, String> {
    backend_status_at(configured_port()?)
}

pub(super) fn restart_backend(boot: &str, commit: &str, automatic: bool) -> Result<Value, String> {
    let port = configured_port()?;
    let before = backend_status_at(port)?;
    if before["state"] != "unavailable" && (before["state"] != "stale" || before["boot"] != boot) {
        return Err("The running backend changed. Check for the update again.".to_owned());
    }
    let intent = if automatic { "automatic" } else { "manual" };
    let output = run_in_wsl(port, "restart", &[boot, commit, intent])?;
    let (stop, startup) = output.split_once('\0').ok_or("Could not verify the WSL backend stopped.")?;
    let result: Value = serde_json::from_str(stop).map_err(|_| "Invalid WSL backend restart response.")?;
    if matches!(result["state"].as_str(), Some("busy" | "spent")) {
        return Ok(result);
    }
    if result["state"] != "stopped" {
        return Err("The WSL backend did not confirm it stopped.".to_owned());
    }
    let new_health = parse_wsl_health(port, startup)?;
    wait_for_forwarding(port, &new_health)?;
    super::verify_restarted_backend(backend_status_at(port)?, boot, commit)
}

pub(super) fn record_backend_restart(entry: &str) -> Result<String, String> {
    run_in_wsl(configured_port()?, "record", &[entry])
}

pub(super) async fn connect(window: WebviewWindow) -> Result<bool, String> {
    let port = tauri::async_runtime::spawn_blocking(verified_port)
        .await
        .map_err(|error| error.to_string())??;

    // Enable IPC only for the verified loopback origin. Keep the same command
    // grants as the macOS cockpit so pane windows work on both platforms.
    let mut capability: Value =
        serde_json::from_str(COCKPIT_CAPABILITY).map_err(|error| error.to_string())?;
    capability["identifier"] = json!("windows-cockpit");
    capability["local"] = json!(false);
    capability["remote"]["urls"] = json!([format!("http://127.0.0.1:{port}/*")]);
    window
        .app_handle()
        .add_capability(capability.to_string())
        .map_err(|error| error.to_string())?;

    super::navigate(&window, &format!("http://127.0.0.1:{port}/cockpit.html"))?;
    Ok(true)
}
