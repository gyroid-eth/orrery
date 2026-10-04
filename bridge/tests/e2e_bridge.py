#!/usr/bin/env python3
"""Self-contained E2E checks for the ORRERY tmux bridge protocols.

The always-enabled smoke test exercises the current v1 ``control_server.py``.
The v2 contract tests are parked behind ``ORRERY_E2E_V2=1`` until
``orrery_backend.py`` lands.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import difflib
import fcntl
import json
import os
import pty
import secrets
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

import pyte
import websockets


BRIDGE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRIDGE_DIR))
from control_server import ControlConfig, TmuxControlBridge  # noqa: E402

CONTROL_SERVER = BRIDGE_DIR / "control_server.py"
V2_BACKEND = BRIDGE_DIR / "orrery_backend.py"
QA_HOST = "127.0.0.1"
QA_PORT = 8802
WS_URL = f"ws://{QA_HOST}:{QA_PORT}/ws"
HTTP_BASE = f"http://{QA_HOST}:{QA_PORT}"
SERVER_START_TIMEOUT = 12.0
EVENT_TIMEOUT = 10.0
STREAM_QUIET_SECONDS = 0.2
STREAM_ROUNDS = int(os.environ.get("ORRERY_STREAM_ROUNDS", "5"))
OLD_DETACH_LINGER_SECONDS = 30.0
ROSTER_POLL_TIMEOUT = 20.0
V2_OPT_IN = os.environ.get("ORRERY_E2E_V2") == "1"
V2_ENABLED = V2_OPT_IN and V2_BACKEND.is_file()
V2_SKIP_REASON = (
    "v2 contract suite is parked until bridge/orrery_backend.py lands; "
    "set ORRERY_E2E_V2=1 for an integration run"
)
if V2_OPT_IN and not V2_BACKEND.is_file():
    V2_SKIP_REASON = f"ORRERY_E2E_V2=1 but backend is missing: {V2_BACKEND}"

# POST /telemetry/spawn is proxied to the dashboard, and the dashboard has no
# dry_run: on 2026-09-28 two "dry-run" probes of test_118 against the real
# 127.0.0.1:8770 registered and launched two real Codex agents. A test may
# send a spawn only when the run opts in AND the backend's dashboard is a
# stand-in, never the real one (ORRERY_DASHBOARD_URL unset means the real one).
REAL_DASHBOARD_PORT = 8770


def spawn_request_refusal() -> str | None:
    """Why this run must not POST /telemetry/spawn, or None when it may."""
    if os.environ.get("ORRERY_E2E_ALLOW_SPAWN") != "1":
        return ("spawn requests reach the dashboard for real (it ignores dry_run); "
                "set ORRERY_E2E_ALLOW_SPAWN=1 and point ORRERY_DASHBOARD_URL at a fake dashboard")
    url = os.environ.get("ORRERY_DASHBOARD_URL", "").strip()
    if not url:
        return "ORRERY_E2E_ALLOW_SPAWN=1 but ORRERY_DASHBOARD_URL is unset, i.e. the real dashboard"
    try:
        port = urllib.parse.urlsplit(url).port
    except ValueError:
        return f"ORRERY_DASHBOARD_URL is not a URL: {url!r}"
    if port in (None, REAL_DASHBOARD_PORT):
        return f"ORRERY_DASHBOARD_URL={url} is (or may be) the real dashboard on :{REAL_DASHBOARD_PORT}"
    return None

FIXTURE_PROJECT_KEY = "/fixture/orrery-project"
QA_TMUX_LABEL = f"orrery-e2e-{os.getpid()}-{secrets.token_hex(4)}"
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_QA_TMUX_WRAPPER_DIR: tempfile.TemporaryDirectory[str] | None = None
_QA_TMUX_BIN: str | None = None


def random_session(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def qa_tmux_bin() -> str:
    """Return a tmux wrapper pinned to this process's isolated QA server."""
    global _QA_TMUX_BIN, _QA_TMUX_WRAPPER_DIR
    if _QA_TMUX_BIN is None:
        _QA_TMUX_WRAPPER_DIR = tempfile.TemporaryDirectory(
            prefix="orrery-e2e-tmux-",
            dir="/private/tmp",
        )
        wrapper = Path(_QA_TMUX_WRAPPER_DIR.name) / "tmux-qa"
        wrapper.write_text(
            "#!/bin/sh\n"
            "unset TMUX TMUX_PANE\n"
            f'export TMUX_TMPDIR="{_QA_TMUX_WRAPPER_DIR.name}"\n'
            f'exec tmux -L "{QA_TMUX_LABEL}" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o700)
        _QA_TMUX_BIN = str(wrapper)
    return _QA_TMUX_BIN


def tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [qa_tmux_bin(), *args],
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def create_test_session(name: str, *, panes: int = 1) -> None:
    """Create only a harness-owned, zshexit-guarded tmux session."""
    tmux("new-session", "-d", "-s", name, "-e", "CLAUDECODE=1")
    for _ in range(1, panes):
        tmux("split-window", "-h", "-t", f"{name}:0")


def tmux_session_exists(name: str) -> bool:
    return tmux("has-session", "-t", name, check=False).returncode == 0


def kill_test_session(name: str) -> None:
    if tmux_session_exists(name):
        tmux("kill-session", "-t", name, check=False)


def pane_count(name: str) -> int:
    result = tmux("list-panes", "-s", "-t", name, "-F", "#{pane_id}")
    return len([line for line in result.stdout.splitlines() if line])


def tmux_window_size(name: str) -> tuple[int, int]:
    result = tmux(
        "display-message",
        "-p",
        "-t",
        f"{name}:0",
        "#{window_width}\t#{window_height}",
    )
    width, height = result.stdout.strip().split("\t")
    return int(width), int(height)


def tmux_window_size_policy(name: str) -> str:
    result = tmux(
        "show-window-options",
        "-v",
        "-t",
        f"{name}:0",
        "window-size",
    )
    local = result.stdout.strip()
    if local:
        return local
    global_result = tmux(
        "show-window-options",
        "-g",
        "-v",
        "window-size",
    )
    return global_result.stdout.strip()


class AttachedTmuxClient:
    """A real PTY tmux client with a controllable terminal grid."""

    def __init__(self, session: str, *, cols: int, rows: int) -> None:
        self.session = session
        self.cols = cols
        self.rows = rows
        self.master_fd: int | None = None
        self.process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> AttachedTmuxClient:
        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd
        self._set_winsize(slave_fd, self.cols, self.rows)
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        try:
            self.process = subprocess.Popen(
                [qa_tmux_bin(), "attach-session", "-t", self.session],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                close_fds=True,
                start_new_session=True,
            )
        finally:
            os.close(slave_fd)
        os.set_blocking(master_fd, False)

        deadline = time.monotonic() + EVENT_TIMEOUT
        while time.monotonic() < deadline:
            self.drain()
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"interactive tmux client exited with {self.process.returncode}"
                )
            clients = tmux(
                "list-clients",
                "-t",
                self.session,
                "-F",
                "#{client_pid}",
                check=False,
            )
            if str(self.process.pid) in clients.stdout.splitlines():
                return self
            time.sleep(0.05)
        raise TimeoutError(f"interactive tmux client did not attach to {self.session}")

    def __exit__(self, *_exc: object) -> None:
        master_fd = self.master_fd
        self.master_fd = None
        if master_fd is not None:
            with contextlib.suppress(OSError):
                os.close(master_fd)

        process = self.process
        self.process = None
        if process is None:
            return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)

    @staticmethod
    def _set_winsize(fd: int, cols: int, rows: int) -> None:
        fcntl.ioctl(
            fd,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, cols, 0, 0),
        )

    def drain(self) -> None:
        if self.master_fd is None:
            return
        while True:
            try:
                if not os.read(self.master_fd, 8192):
                    return
            except BlockingIOError:
                return
            except OSError:
                return

    def resize(self, *, cols: int, rows: int) -> None:
        if self.master_fd is None or self.process is None:
            raise RuntimeError("interactive tmux client is not attached")
        self.drain()
        self.cols = cols
        self.rows = rows
        self._set_winsize(self.master_fd, cols, rows)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(self.process.pid, signal.SIGWINCH)

    def activity(self) -> None:
        if self.master_fd is None:
            raise RuntimeError("interactive tmux client is not attached")
        self.drain()
        os.write(self.master_fd, b"\r")


def wait_for_window_size(
    session: str,
    expected: tuple[int, int],
    client: AttachedTmuxClient,
    *,
    timeout: float = EVENT_TIMEOUT,
) -> None:
    deadline = time.monotonic() + timeout
    actual = tmux_window_size(session)
    while actual != expected and time.monotonic() < deadline:
        client.drain()
        time.sleep(0.05)
        actual = tmux_window_size(session)
    if actual != expected:
        raise AssertionError(
            f"window size for {session!r} did not converge to {expected}; got {actual}"
        )


def wait_for_window_size_policy(
    session: str,
    expected: str,
    client: AttachedTmuxClient,
    *,
    timeout: float = EVENT_TIMEOUT,
) -> None:
    deadline = time.monotonic() + timeout
    actual = tmux_window_size_policy(session)
    while actual != expected and time.monotonic() < deadline:
        client.drain()
        time.sleep(0.05)
        actual = tmux_window_size_policy(session)
    if actual != expected:
        raise AssertionError(
            f"window-size policy for {session!r} did not converge to "
            f"{expected!r}; got {actual!r}"
        )


def assert_port_available() -> None:
    with socket.socket() as probe:
        probe.settimeout(0.15)
        if probe.connect_ex((QA_HOST, QA_PORT)) == 0:
            raise AssertionError(
                f"{QA_HOST}:{QA_PORT} is already in use; the QA harness never "
                "reuses or stops an unrelated listener"
            )


def wait_for_tcp(process: subprocess.Popen[bytes], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"bridge exited during startup with code {process.returncode}")
        with socket.socket() as probe:
            probe.settimeout(0.15)
            if probe.connect_ex((QA_HOST, QA_PORT)) == 0:
                return
        time.sleep(0.05)
    raise TimeoutError(f"bridge did not listen on {QA_HOST}:{QA_PORT} within {timeout}s")


# The backend writes and prunes ~/.orrery/history and writes ~/.orrery/prefs.json.
# A test backend runs on its own tmux socket, so every real session looks dead
# to it and its startup prune deletes real history older than a day: on
# 2026-09-28 E2E runs removed 29 real history files. Every test backend gets a
# throwaway history directory and prefs file unless the test passes its own.
REAL_ORRERY_DIR = Path(os.path.expanduser("~/.orrery")).resolve()


def assert_not_real_state(env: dict[str, str]) -> None:
    for key in ("ORRERY_HISTORY_DIR", "ORRERY_PREFS_PATH"):
        value = env.get(key, "")
        if not value:
            raise AssertionError(f"test backend started without {key}; it would use ~/.orrery")
        resolved = Path(os.path.expanduser(value)).resolve()
        if resolved == REAL_ORRERY_DIR or REAL_ORRERY_DIR in resolved.parents:
            raise AssertionError(f"test backend {key}={value} points into the real ~/.orrery")


class ManagedServer:
    def __init__(self, command: list[str], env: dict[str, str] | None = None) -> None:
        self.command = command
        self.env = env
        self.process: subprocess.Popen[bytes] | None = None
        self._log_file = tempfile.TemporaryFile()
        self._last_log = ""
        self._state_dir: tempfile.TemporaryDirectory[str] | None = None

    def start(self) -> None:
        assert_port_available()
        merged_env = os.environ.copy()
        merged_env["PYTHONUNBUFFERED"] = "1"
        merged_env.update(self.isolated_state_env())
        if self.env:
            merged_env.update(self.env)
        assert_not_real_state(merged_env)
        self.process = subprocess.Popen(
            self.command,
            cwd=BRIDGE_DIR,
            env=merged_env,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            wait_for_tcp(self.process, SERVER_START_TIMEOUT)
        except Exception as exc:
            self.stop()
            raise RuntimeError(f"{exc}\nbridge log:\n{self.logs()}") from exc

    def logs(self) -> str:
        if self._log_file.closed:
            return self._last_log
        self._log_file.flush()
        self._log_file.seek(0)
        data = self._log_file.read().decode("utf-8", errors="replace")
        self._log_file.seek(0, os.SEEK_END)
        return data[-20_000:]

    def isolated_state_env(self) -> dict[str, str]:
        if self._state_dir is None:
            self._state_dir = tempfile.TemporaryDirectory(prefix="orrery-e2e-state-")
        root = Path(self._state_dir.name)
        return {
            "ORRERY_HISTORY_DIR": str(root / "history"),
            "ORRERY_PREFS_PATH": str(root / "prefs.json"),
        }

    def stop(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)
        if not self._log_file.closed:
            self._last_log = self.logs()
            self._log_file.close()
        if self._state_dir is not None:
            self._state_dir.cleanup()
            self._state_dir = None


async def recv_json(websocket: Any, timeout: float = EVENT_TIMEOUT) -> dict[str, Any]:
    raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
    if not isinstance(raw, str):
        raise AssertionError(f"expected a text WebSocket frame, got {type(raw).__name__}")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise AssertionError(f"expected a JSON object, got {payload!r}")
    return payload


async def recv_matching(
    websocket: Any,
    predicate: Callable[[dict[str, Any]], bool],
    *,
    description: str,
    timeout: float = EVENT_TIMEOUT,
) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout
    seen: list[dict[str, Any]] = []
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise AssertionError(f"timed out waiting for {description}; seen={seen!r}")
        payload = await recv_json(websocket, remaining)
        seen.append(payload)
        if predicate(payload):
            return payload


async def wait_for_output_marker(
    websocket: Any,
    marker: str,
    *,
    expected_session: str | None = None,
    expected_pane: str | None = None,
) -> None:
    deadline = asyncio.get_running_loop().time() + EVENT_TIMEOUT
    output = ""
    seen: list[dict[str, Any]] = []
    while marker not in output:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise AssertionError(
                f"timed out waiting for output marker {marker!r}; "
                f"output={output!r}, seen={seen!r}"
            )
        payload = await recv_json(websocket, remaining)
        seen.append(payload)
        if payload.get("type") != "output":
            continue
        if expected_session is not None:
            if payload.get("session") != expected_session:
                continue
        if expected_pane is not None and payload.get("paneId") != expected_pane:
            continue
        data = payload.get("data")
        if isinstance(data, str):
            output += data


def http_response(
    path: str,
    *,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
) -> tuple[int, bytes]:
    status, body, _ = http_response_with_headers(
        path,
        method=method,
        json_body=json_body,
    )
    return status, body


def http_response_with_headers(
    path: str,
    *,
    method: str = "GET",
    json_body: dict[str, Any] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    body = None
    headers: dict[str, str] = {}
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{HTTP_BASE}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=EVENT_TIMEOUT) as response:
            status = response.status
            body = response.read()
            response_headers = dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            body = exc.read()
            response_headers = dict(exc.headers.items())
        finally:
            exc.close()
    return status, body, response_headers


def json_response(status: int, body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssertionError(
            f"expected JSON response for HTTP {status}, got {body[:500]!r}"
        ) from exc


def http_json(path: str) -> tuple[int, Any]:
    status, body = http_response(path)
    return status, json_response(status, body)


def pane_id_from_reset(reset: dict[str, Any]) -> str:
    panes = reset.get("panes")
    if not isinstance(panes, list) or not panes:
        raise AssertionError(f"reset did not contain panes: {reset!r}")
    if not all(isinstance(item, dict) for item in panes):
        raise AssertionError(f"reset contained a non-object pane: {reset!r}")
    pane = next((item for item in panes if item.get("active") is True), panes[0])
    pane_id = pane.get("paneId")
    if not isinstance(pane_id, str):
        raise AssertionError(f"pane did not contain paneId: {pane!r}")
    return pane_id


def pane_grid(pane_id: str) -> tuple[int, int]:
    result = tmux(
        "display-message",
        "-p",
        "-t",
        pane_id,
        "#{pane_width}\t#{pane_height}",
    )
    width, height = result.stdout.strip().split("\t")
    return int(width), int(height)


def tmux_pane_identity(session: str) -> tuple[str, int]:
    result = tmux(
        "display-message",
        "-p",
        "-t",
        f"{session}:0.0",
        "#{pane_id}\t#{session_created}",
    )
    pane_id, session_created = result.stdout.strip().split("\t")
    return pane_id, int(session_created)


def capture_pane_rows(pane_id: str, height: int) -> list[str]:
    result = tmux("capture-pane", "-p", "-t", pane_id)
    rows = result.stdout.splitlines()
    rows = rows[:height] + [""] * max(0, height - len(rows))
    return [row.rstrip() for row in rows]


STREAM_STRESS_DRIVER = r"""
import os
import sys
import time

fd = 1
marker_prefix = sys.argv[1]
rounds = int(sys.argv[2])

def write(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    os.write(fd, data)

def write_wide_split(prefix, wide, suffix):
    raw = wide.encode("utf-8")
    write(prefix)
    # Deliberately end write(2) calls inside the first UTF-8 code point.
    write(raw[:1])
    time.sleep(0.0005)
    write(raw[1:2])
    time.sleep(0.0005)
    write(raw[2:] + suffix.encode("utf-8"))

for round_index in range(rounds):
    marker = f"{marker_prefix}_{round_index:02d}"
    write("\x1b[2J\x1b[H")
    for index in range(120):
        prefix = f"BURST {round_index:02d}/{index:03d} "
        suffix = " ペインサイズ変化→再描画 主導権テスト\r\n"
        if index % 5 == 0:
            write_wide_split(prefix, "変", suffix)
        else:
            write(prefix + "主導権・日本語ワイド文字" + suffix)

    write("\x1b[2J\x1b[H")
    for frame in range(90):
        if frame:
            write("\x1b[5A")
        for row in range(5):
            label = (
                f"live {frame:03d}/{row} 長い古い状態を完全消去する行"
                if frame % 2 == 0
                else f"live {frame:03d}/{row} 短い行"
            )
            prefix = "\r\x1b[2K"
            suffix = "\r\n" if row < 4 else ""
            if row == frame % 5:
                write_wide_split(prefix + label + " ", "主", "導権" + suffix)
            else:
                write(prefix + label + suffix)

    columns, rows = os.get_terminal_size(fd)
    final_rows = []
    for row in range(rows):
        if row == 0:
            text = f"ORRERY STREAM QA round={round_index:02d}"
        elif row == rows - 2:
            text = "ペインサイズ変化→ 主導権を保持・古い行なし"
        elif row == rows - 1:
            text = marker
        else:
            text = f"row {row:02d} 日本語ワイド文字 CJK burst stable"
        final_rows.append(text)

    payload = "\x1b[2J\x1b[H" + "".join(
        "\x1b[2K" + text + ("\r\n" if row < rows - 1 else "")
        for row, text in enumerate(final_rows)
    )
    raw = payload.encode("utf-8")
    sizes = (17, 1, 2, 23, 3, 5, 11)
    offset = 0
    part = 0
    while offset < len(raw):
        size = sizes[part % len(sizes)]
        write(raw[offset:offset + size])
        offset += size
        part += 1
        time.sleep(0.0002)

    # The harness captures the stable frame, then sends Enter to continue.
    sys.stdin.readline()
"""


def stream_stress_command(
    driver_path: Path,
    marker_prefix: str,
    rounds: int,
) -> str:
    """Return a short command for the harness-owned stress driver."""
    return f"python3 {driver_path} {marker_prefix} {rounds}"


def dump_stream_mismatch(
    *,
    round_index: int,
    pane_id: str,
    actual: list[str],
    expected: list[str],
    events: list[dict[str, Any]],
) -> Path:
    artifact_dir = Path(
        tempfile.mkdtemp(prefix=f"orrery-stream-diff-r{round_index:02d}-")
    )
    (artifact_dir / "pyte-screen.txt").write_text(
        "\n".join(actual) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "tmux-capture.txt").write_text(
        "\n".join(expected) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "events.jsonl").write_text(
        "".join(
            json.dumps(event, ensure_ascii=True, separators=(",", ":")) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )
    diff = difflib.unified_diff(
        expected,
        actual,
        fromfile=f"tmux:{pane_id}",
        tofile=f"pyte:{pane_id}",
        lineterm="",
    )
    (artifact_dir / "screen.diff").write_text(
        "\n".join(diff) + "\n",
        encoding="utf-8",
    )
    return artifact_dir


def tmux_control_pids(session: str) -> set[int]:
    result = tmux(
        "list-clients",
        "-F",
        "#{client_pid}\t#{session_name}\t#{client_control_mode}",
        check=False,
    )
    matches: set[int] = set()
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) != 3:
            continue
        pid_text, client_session, control_mode = fields
        if client_session == session and control_mode == "1":
            with contextlib.suppress(ValueError):
                matches.add(int(pid_text))
    return matches


async def wait_for_control_process(
    session: str,
    *,
    timeout: float = EVENT_TIMEOUT,
) -> set[int]:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        pids = await asyncio.to_thread(tmux_control_pids, session)
        if pids:
            return pids
        await asyncio.sleep(0.1)
    return set()


def build_mail_fixture(path: Path) -> None:
    """Create the smallest agent-mail schema needed by the read-only API."""
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY,
                human_key TEXT NOT NULL
            );
            CREATE TABLE agents (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                project_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                thread_id TEXT,
                subject TEXT NOT NULL,
                importance TEXT NOT NULL,
                created_ts TEXT NOT NULL,
                body_md TEXT NOT NULL
            );
            CREATE TABLE message_recipients (
                message_id INTEGER NOT NULL,
                agent_id INTEGER NOT NULL,
                kind TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            "INSERT INTO projects (id, human_key) VALUES (?, ?)",
            [
                (1, FIXTURE_PROJECT_KEY),
                (2, "/fixture/other"),
            ],
        )
        connection.executemany(
            "INSERT INTO agents (id, name) VALUES (?, ?)",
            [
                (1, "BlueLake"),
                (2, "RedStone"),
                (3, "GreenCastle"),
                (4, "PurpleBear"),
                (5, "SilverMoon"),
            ],
        )
        connection.executemany(
            """
            INSERT INTO messages (
                id, project_id, sender_id, thread_id, subject, importance, created_ts, body_md
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    101,
                    1,
                    1,
                    "thread-cycle-4",
                    "Opening note",
                    "normal",
                    "2026-07-29T10:00:00+00:00",
                    "# Project **kickoff**\nSecond line.",
                ),
                (
                    102,
                    1,
                    2,
                    "thread-cycle-4",
                    "Reply one",
                    "high",
                    "2026-07-29T10:05:00+00:00",
                    "First reply\nWith the full body intact.",
                ),
                (
                    103,
                    1,
                    3,
                    None,
                    "Standalone",
                    "low",
                    "2026-07-29T10:10:00+00:00",
                    "- status ready\nNo thread.",
                ),
                (
                    104,
                    1,
                    1,
                    "thread-cycle-4",
                    "Reply two",
                    "urgent",
                    "2026-07-29T10:20:00+00:00",
                    "`Final` reply",
                ),
                (
                    201,
                    2,
                    4,
                    None,
                    "Other project",
                    "normal",
                    "2026-07-29T10:30:00+00:00",
                    "Must not leak into ORRERY.",
                ),
            ],
        )
        connection.executemany(
            """
            INSERT INTO message_recipients (message_id, agent_id, kind)
            VALUES (?, ?, ?)
            """,
            [
                (101, 2, "to"),
                (101, 3, "cc"),
                (102, 1, "to"),
                (103, 1, "to"),
                (104, 2, "to"),
                (201, 5, "to"),
            ],
        )


class ControlServerRawOutputTest(unittest.TestCase):
    """Raw control lines must reach the pane decoder before UTF-8 decoding."""

    def setUp(self) -> None:
        self.bridge = TmuxControlBridge(
            ControlConfig(
                host=QA_HOST,
                port=0,
                session="orrery-qa-parser-unit",
                tmux_bin="tmux",
            )
        )
        self.events: list[dict[str, Any]] = []
        self.bridge._schedule_broadcast = self.events.append  # type: ignore[method-assign]

    def test_output_preserves_codepoint_split_across_raw_lines(self) -> None:
        encoded = "変".encode("utf-8")
        self.bridge._handle_line(b"%output %7 prefix " + encoded[:1])
        self.bridge._handle_line(b"%output %7 " + encoded[1:2])
        self.bridge._handle_line(b"%output %7 " + encoded[2:] + b" suffix")
        self.assertEqual(
            "".join(str(event["data"]) for event in self.events),
            "prefix 変 suffix",
        )
        self.assertTrue(all(event["paneId"] == "%7" for event in self.events))

    def test_extended_output_preserves_raw_utf8_and_payload_spacing(self) -> None:
        encoded = "主".encode("utf-8")
        self.bridge._handle_line(
            b"%extended-output %8 12 future :  prefix " + encoded[:2]
        )
        self.bridge._handle_line(
            b"%extended-output %8 3 : " + encoded[2:] + b"  suffix"
        )
        self.assertEqual(
            "".join(str(event["data"]) for event in self.events),
            " prefix 主  suffix",
        )
        self.assertTrue(all(event["paneId"] == "%8" for event in self.events))


class V1ControlServerPlumbingTest(unittest.TestCase):
    """Keep subprocess, tmux, WebSocket, input, and cleanup plumbing green."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = random_session("orrery-qa")
        cls.server = ManagedServer(
            [
                sys.executable,
                str(CONTROL_SERVER),
                "--port",
                str(QA_PORT),
                "--session",
                cls.session,
                "--tmux-bin",
                qa_tmux_bin(),
            ]
        )
        try:
            create_test_session(cls.session)
            cls.server.start()
        except Exception:
            try:
                cls.server.stop()
            finally:
                kill_test_session(cls.session)
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.server.stop()
        finally:
            kill_test_session(cls.session)
        if tmux_session_exists(cls.session):
            raise AssertionError(f"failed to clean up tmux session {cls.session!r}")

    def test_v1_reset_and_keystroke_round_trip(self) -> None:
        async def scenario() -> None:
            marker = f"QA_MARKER_{secrets.token_hex(6)}"
            async with websockets.connect(WS_URL, open_timeout=EVENT_TIMEOUT) as websocket:
                reset = await recv_matching(
                    websocket,
                    lambda event: event.get("type") == "reset",
                    description="v1 reset",
                )
                self.assertEqual(reset.get("session"), self.session)
                pane_id = pane_id_from_reset(reset)
                await websocket.send(
                    json.dumps(
                        {
                            "type": "input",
                            "paneId": pane_id,
                            "data": f"echo {marker}\r",
                        }
                    )
                )
                await wait_for_output_marker(
                    websocket,
                    marker,
                    expected_pane=pane_id,
                )

        asyncio.run(scenario())


@unittest.skipUnless(V2_ENABLED, V2_SKIP_REASON)
class V2UnifiedBackendContractTest(unittest.TestCase):
    """Unified backend assertions through Cycle 9's recorder contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.session_a = random_session("orrery-qa")
        cls.session_b = random_session("orrery-qa")
        cls.follow_session = random_session("orrery-qa-follow")
        cls.release_session = random_session("orrery-qa-release")
        cls.stream_session = random_session("orrery-qa-stream")
        cls.history_session = random_session("orrery-qa-history")
        cls.death_session = random_session("orrery-qa-recorder-death")
        cls.guard_session = random_session("qa-guard")
        cls.sessions = [
            cls.session_a,
            cls.session_b,
            cls.follow_session,
            cls.release_session,
            cls.stream_session,
            cls.history_session,
            cls.death_session,
            cls.guard_session,
        ]
        cls.server = ManagedServer(
            [
                sys.executable,
                str(V2_BACKEND),
                "--port",
                str(QA_PORT),
                "--tmux-bin",
                qa_tmux_bin(),
            ]
        )
        try:
            create_test_session(cls.session_a)
            create_test_session(cls.session_b)
            create_test_session(cls.follow_session)
            create_test_session(cls.release_session)
            create_test_session(cls.stream_session)
            create_test_session(cls.history_session)
            create_test_session(cls.death_session)
            create_test_session(cls.guard_session, panes=2)
            cls.server.start()
        except Exception:
            try:
                cls.server.stop()
            finally:
                for session in cls.sessions:
                    kill_test_session(session)
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.server.stop()
        finally:
            for session in cls.sessions:
                kill_test_session(session)
        leaked = [session for session in cls.sessions if tmux_session_exists(session)]
        if leaked:
            raise AssertionError(f"failed to clean up tmux sessions: {leaked!r}")

    def test_10_sessions_http_lists_owned_sessions(self) -> None:
        status, payload = http_json("/telemetry/sessions")
        self.assertEqual(status, 200)
        self.assertIsInstance(payload, list)
        by_name = {
            item.get("session"): item for item in payload if isinstance(item, dict)
        }
        for session in self.sessions:
            self.assertIn(session, by_name)
            item = by_name[session]
            self.assertIsInstance(item.get("attached"), bool)
            self.assertIsInstance(item.get("windows"), int)
            self.assertIsInstance(item.get("created"), int)

    def test_20_ws_connect_receives_sessions(self) -> None:
        async def scenario() -> None:
            async with websockets.connect(WS_URL, open_timeout=EVENT_TIMEOUT) as websocket:
                event = await recv_json(websocket)
                self.assertEqual(
                    event.get("type"),
                    "sessions",
                    f"the first WS event must enumerate sessions: {event!r}",
                )
                sessions = event.get("sessions")
                self.assertIsInstance(sessions, list)
                names = {
                    item.get("session") for item in sessions if isinstance(item, dict)
                }
                self.assertIn(self.session_a, names)
                self.assertIn(self.session_b, names)

        asyncio.run(scenario())

    def test_30_attach_receives_session_reset_with_panes(self) -> None:
        async def scenario() -> None:
            async with websockets.connect(WS_URL, open_timeout=EVENT_TIMEOUT) as websocket:
                await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "sessions",
                    description="sessions event",
                )
                await websocket.send(
                    json.dumps({"type": "attach", "session": self.session_a})
                )
                reset = await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "reset"
                    and item.get("session") == self.session_a,
                    description=f"reset for {self.session_a}",
                )
                pane_id_from_reset(reset)

        asyncio.run(scenario())

    def test_31_attach_does_not_resize_and_external_resize_resyncs(self) -> None:
        marker = f"QA_FOLLOW_{secrets.token_hex(6)}"
        tmux(
            "send-keys",
            "-t",
            f"{self.follow_session}:0.0",
            f"printf '{marker}\\n'",
            "Enter",
        )

        with AttachedTmuxClient(
            self.follow_session,
            cols=91,
            rows=31,
        ) as interactive:
            baseline = tmux_window_size(self.follow_session)

            async def scenario() -> None:
                async with websockets.connect(
                    WS_URL,
                    open_timeout=EVENT_TIMEOUT,
                ) as websocket:
                    await recv_matching(
                        websocket,
                        lambda item: item.get("type") == "sessions",
                        description="sessions event",
                    )
                    await websocket.send(
                        json.dumps(
                            {"type": "attach", "session": self.follow_session}
                        )
                    )
                    reset = await recv_matching(
                        websocket,
                        lambda item: item.get("type") == "reset"
                        and item.get("session") == self.follow_session,
                        description=f"reset for {self.follow_session}",
                    )
                    pane_id = pane_id_from_reset(reset)
                    self.assertEqual(
                        tmux_window_size(self.follow_session),
                        baseline,
                        "control-mode attach must not alter an interactive client grid",
                    )

                    expected = (baseline[0] + 9, baseline[1] + 5)
                    interactive.resize(cols=expected[0], rows=expected[1] + 1)
                    await recv_matching(
                        websocket,
                        lambda item: item.get("type") == "update"
                        and item.get("session") == self.follow_session
                        and item.get("paneId") is None
                        and isinstance(item.get("pane"), dict)
                        and item["pane"].get("paneId") == pane_id
                        and item["pane"].get("width") == expected[0]
                        and item["pane"].get("height") == expected[1],
                        description="pane update after interactive client resize",
                    )
                    await recv_matching(
                        websocket,
                        lambda item: item.get("type") == "refresh-pane"
                        and item.get("session") == self.follow_session
                        and item.get("paneId") == pane_id
                        and marker in str(item.get("data")),
                        description="pane resync after retained size change",
                    )
                    self.assertEqual(
                        tmux_window_size(self.follow_session),
                        expected,
                    )

            asyncio.run(scenario())

    def test_32_claim_pins_and_release_restores_follow_mode(self) -> None:
        with AttachedTmuxClient(
            self.release_session,
            cols=96,
            rows=33,
        ) as interactive:
            baseline = tmux_window_size(self.release_session)

            async def scenario() -> None:
                async with websockets.connect(
                    WS_URL,
                    open_timeout=EVENT_TIMEOUT,
                ) as websocket:
                    await recv_matching(
                        websocket,
                        lambda item: item.get("type") == "sessions",
                        description="sessions event",
                    )
                    await websocket.send(
                        json.dumps(
                            {"type": "attach", "session": self.release_session}
                        )
                    )
                    reset = await recv_matching(
                        websocket,
                        lambda item: item.get("type") == "reset"
                        and item.get("session") == self.release_session,
                        description=f"reset for {self.release_session}",
                    )
                    pane_id = pane_id_from_reset(reset)
                    claimed = (baseline[0] - 19, baseline[1] - 7)
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "resize",
                                "paneId": pane_id,
                                "cols": claimed[0],
                                "rows": claimed[1],
                            }
                        )
                    )
                    await asyncio.to_thread(
                        wait_for_window_size,
                        self.release_session,
                        claimed,
                        interactive,
                    )
                    self.assertEqual(
                        tmux_window_size_policy(self.release_session),
                        "manual",
                        "resize must claim the window with a local manual policy",
                    )

                    await websocket.send(
                        json.dumps({"type": "release", "paneId": pane_id})
                    )
                    await asyncio.to_thread(
                        wait_for_window_size_policy,
                        self.release_session,
                        "latest",
                        interactive,
                    )
                    interactive.activity()
                    await asyncio.to_thread(
                        wait_for_window_size,
                        self.release_session,
                        baseline,
                        interactive,
                    )
                    self.assertEqual(
                        tmux_window_size_policy(self.release_session),
                        "latest",
                        "release must remove the local manual policy",
                    )
                    await recv_matching(
                        websocket,
                        lambda item: item.get("type") == "refresh-pane"
                        and item.get("session") == self.release_session
                        and item.get("paneId") == pane_id,
                        description="pane resync after release",
                    )

                    await websocket.send(
                        json.dumps({"type": "release", "paneId": pane_id})
                    )
                    await asyncio.to_thread(
                        wait_for_window_size_policy,
                        self.release_session,
                        "latest",
                        interactive,
                    )
                    interactive.activity()
                    await asyncio.to_thread(
                        wait_for_window_size,
                        self.release_session,
                        baseline,
                        interactive,
                    )
                    self.assertEqual(
                        tmux_window_size_policy(self.release_session),
                        "latest",
                        "releasing an already-following pane must be idempotent",
                    )

            asyncio.run(scenario())

    def test_40_keystroke_round_trip_has_session(self) -> None:
        async def scenario() -> None:
            marker = f"QA_MARKER_{secrets.token_hex(6)}"
            async with websockets.connect(WS_URL, open_timeout=EVENT_TIMEOUT) as websocket:
                await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "sessions",
                    description="sessions event",
                )
                await websocket.send(
                    json.dumps({"type": "attach", "session": self.session_a})
                )
                reset = await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "reset"
                    and item.get("session") == self.session_a,
                    description=f"reset for {self.session_a}",
                )
                pane_id = pane_id_from_reset(reset)
                await websocket.send(
                    json.dumps(
                        {
                            "type": "input",
                            "paneId": pane_id,
                            "data": f"echo {marker}\r",
                        }
                    )
                )
                await wait_for_output_marker(
                    websocket,
                    marker,
                    expected_session=self.session_a,
                    expected_pane=pane_id,
                )

        asyncio.run(scenario())

    def test_50_two_attached_sessions_keep_output_separate(self) -> None:
        async def scenario() -> None:
            markers = {
                self.session_a: f"QA_MARKER_{secrets.token_hex(6)}",
                self.session_b: f"QA_MARKER_{secrets.token_hex(6)}",
            }
            async with websockets.connect(WS_URL, open_timeout=EVENT_TIMEOUT) as websocket:
                await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "sessions",
                    description="sessions event",
                )
                panes: dict[str, str] = {}
                for session in markers:
                    await websocket.send(
                        json.dumps({"type": "attach", "session": session})
                    )
                while len(panes) < len(markers):
                    reset = await recv_matching(
                        websocket,
                        lambda item: item.get("type") == "reset"
                        and item.get("session") in markers
                        and item.get("session") not in panes,
                        description="both session resets",
                    )
                    session = reset["session"]
                    panes[session] = pane_id_from_reset(reset)

                for session, marker in markers.items():
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "input",
                                "paneId": panes[session],
                                "data": f"echo {marker}\r",
                            }
                        )
                    )

                pending = set(markers)
                buffers = {session: "" for session in markers}
                deadline = asyncio.get_running_loop().time() + EVENT_TIMEOUT
                while pending:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        self.fail(
                            f"timed out waiting for isolated output; buffers={buffers!r}"
                        )
                    event = await recv_json(websocket, remaining)
                    if event.get("type") != "output":
                        continue
                    session = event.get("session")
                    data = event.get("data")
                    if not isinstance(session, str) or not isinstance(data, str):
                        continue
                    if session in buffers:
                        buffers[session] += data
                        for owner, marker in markers.items():
                            if marker in buffers[session]:
                                self.assertEqual(
                                    session,
                                    owner,
                                    f"{marker!r} leaked onto the wrong session event",
                                )
                        if markers[session] in buffers[session]:
                            pending.discard(session)

        asyncio.run(scenario())

    def test_52_pane_window_peers_share_one_recorder(self) -> None:
        """A popped-out pane (2026-09-29) is a second websocket on the same
        session: it must reuse the recorder, see the same output, and keep
        seeing it after the cockpit that opened it lets go."""

        async def attach(websocket: Any, session: str) -> str:
            await recv_matching(
                websocket,
                lambda item: item.get("type") == "sessions",
                description="sessions event",
            )
            await websocket.send(json.dumps({"type": "attach", "session": session}))
            reset = await recv_matching(
                websocket,
                lambda item: item.get("type") == "reset"
                and item.get("session") == session,
                description=f"reset for {session}",
            )
            return pane_id_from_reset(reset)

        async def scenario() -> None:
            session = self.session_b
            recorder = await wait_for_control_process(session)
            self.assertEqual(len(recorder), 1, f"expected one recorder, got {recorder!r}")
            async with websockets.connect(WS_URL, open_timeout=EVENT_TIMEOUT) as cockpit:
                pane_id = await attach(cockpit, session)
                async with websockets.connect(WS_URL, open_timeout=EVENT_TIMEOUT) as window:
                    self.assertEqual(await attach(window, session), pane_id)
                    self.assertEqual(
                        await asyncio.to_thread(tmux_control_pids, session),
                        recorder,
                        "a second peer started another tmux control client",
                    )
                    marker = f"PANE_WINDOW_{secrets.token_hex(6)}"
                    await window.send(json.dumps(
                        {"type": "input", "paneId": pane_id, "data": f"echo {marker}\r"}
                    ))
                    await wait_for_output_marker(
                        window, marker, expected_session=session, expected_pane=pane_id
                    )
                    await wait_for_output_marker(
                        cockpit, marker, expected_session=session, expected_pane=pane_id
                    )

                    # The cockpit detaches while the pane is out; the window
                    # keeps receiving.
                    await cockpit.send(json.dumps({"type": "detach", "session": session}))
                    after = f"PANE_WINDOW_{secrets.token_hex(6)}"
                    await window.send(json.dumps(
                        {"type": "input", "paneId": pane_id, "data": f"echo {after}\r"}
                    ))
                    await wait_for_output_marker(
                        window, after, expected_session=session, expected_pane=pane_id
                    )
            self.assertEqual(
                await asyncio.to_thread(tmux_control_pids, session),
                recorder,
                "closing both peers replaced or stopped the recorder",
            )

        asyncio.run(scenario())

    def test_55_cjk_burst_screen_matches_tmux_capture(self) -> None:
        async def scenario(driver_path: Path) -> None:
            events: list[dict[str, Any]] = []
            async with websockets.connect(
                WS_URL,
                open_timeout=EVENT_TIMEOUT,
                max_size=None,
            ) as websocket:
                sessions = await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "sessions",
                    description="sessions event",
                )
                events.append(sessions)
                await websocket.send(
                    json.dumps({"type": "attach", "session": self.stream_session})
                )
                reset = await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "reset"
                    and item.get("session") == self.stream_session,
                    description=f"reset for {self.stream_session}",
                )
                events.append(reset)
                pane_id = pane_id_from_reset(reset)
                columns, rows = pane_grid(pane_id)
                screen = pyte.HistoryScreen(
                    columns,
                    rows,
                    history=max(2_000, STREAM_ROUNDS * 500),
                )
                stream = pyte.Stream(screen)

                def record(event: dict[str, Any]) -> str:
                    events.append(event)
                    if (
                        event.get("type") == "output"
                        and event.get("session") == self.stream_session
                        and event.get("paneId") == pane_id
                    ):
                        data = event.get("data")
                        if isinstance(data, str):
                            stream.feed(data)
                            return data
                    return ""

                # Replay the attach snapshot before the stress process starts.
                while True:
                    try:
                        event = await recv_json(websocket, STREAM_QUIET_SECONDS)
                    except TimeoutError:
                        break
                    record(event)

                marker_prefix = f"STREAM_QA_DONE_{secrets.token_hex(6)}"
                command = stream_stress_command(
                    driver_path,
                    marker_prefix,
                    STREAM_ROUNDS,
                )
                tmux("send-keys", "-t", pane_id, "-l", command)
                tmux("send-keys", "-t", pane_id, "Enter")

                for round_index in range(STREAM_ROUNDS):
                    marker = f"{marker_prefix}_{round_index:02d}"

                    marker_seen = False
                    marker_buffer = ""
                    deadline = (
                        asyncio.get_running_loop().time()
                        + max(EVENT_TIMEOUT, 20.0)
                    )
                    while not marker_seen:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            self.fail(
                                f"round {round_index}: timed out waiting for {marker!r}; "
                                f"server log:\n{self.server.logs()}"
                            )
                        try:
                            event = await recv_json(websocket, remaining)
                        except TimeoutError:
                            self.fail(
                                f"round {round_index}: timed out waiting for "
                                f"{marker!r}; recent_events={events[-20:]!r}; "
                                f"server log:\n{self.server.logs()}"
                            )
                        marker_buffer = (
                            marker_buffer + record(event)
                        )[-2 * len(marker) :]
                        marker_seen = marker in marker_buffer

                    # A quiet interval proves every event queued before the marker
                    # has reached the emulator; the driver holds the frame steady.
                    while True:
                        try:
                            event = await recv_json(
                                websocket,
                                STREAM_QUIET_SECONDS,
                            )
                        except TimeoutError:
                            break
                        record(event)

                    actual = [row.rstrip() for row in screen.display]
                    expected = capture_pane_rows(pane_id, rows)
                    replacement_events = [
                        event
                        for event in events
                        if "\ufffd" in str(event.get("data", ""))
                    ]
                    if actual != expected or replacement_events:
                        artifact_dir = dump_stream_mismatch(
                            round_index=round_index,
                            pane_id=pane_id,
                            actual=actual,
                            expected=expected,
                            events=events,
                        )
                        diff = "\n".join(
                            difflib.unified_diff(
                                expected,
                                actual,
                                fromfile="tmux capture-pane",
                                tofile="pyte replay",
                                lineterm="",
                            )
                        )
                        self.fail(
                            f"round {round_index}: stream diverged "
                            f"(replacement_events={len(replacement_events)}); "
                            f"artifacts={artifact_dir}\n{diff}"
                        )

                    # Release the driver's stdin barrier. The next frame starts
                    # with ED2+CUP, so the echoed newline is intentionally
                    # replayed and then cleared like normal terminal input.
                    tmux("send-keys", "-t", pane_id, "Enter")

        with tempfile.TemporaryDirectory(prefix="orrery-stream-driver-") as temp_dir:
            driver_path = Path(temp_dir) / "stress_driver.py"
            driver_path.write_text(STREAM_STRESS_DRIVER, encoding="utf-8")
            asyncio.run(scenario(driver_path))

    def test_60_history_survives_disconnect_past_old_linger(self) -> None:
        async def scenario() -> None:
            recorder_pids = await wait_for_control_process(self.history_session)
            self.assertTrue(
                recorder_pids,
                "always-on recorder did not start for an existing tmux session",
            )

            marker_prefix = f"RECORDER_QA_{secrets.token_hex(6)}"
            early_marker = f"{marker_prefix}_000"
            late_marker = f"{marker_prefix}_199"
            command = (
                "i=0; while [ $i -lt 200 ]; do "
                f"printf '{marker_prefix}_%03d\\n' $i; "
                "i=$((i+1)); done"
            )

            # Client A is the only cockpit client present while all 200 lines
            # are emitted. Closing this context exercises disconnect cleanup,
            # rather than the explicit detach message.
            async with websockets.connect(
                WS_URL,
                open_timeout=EVENT_TIMEOUT,
            ) as client_a:
                await recv_matching(
                    client_a,
                    lambda item: item.get("type") == "sessions",
                    description="sessions event",
                )
                await client_a.send(
                    json.dumps({"type": "attach", "session": self.history_session})
                )
                reset = await recv_matching(
                    client_a,
                    lambda item: item.get("type") == "reset"
                    and item.get("session") == self.history_session,
                    description=f"reset for {self.history_session}",
                )
                pane_id = pane_id_from_reset(reset)
                await client_a.send(
                    json.dumps(
                        {
                            "type": "input",
                            "paneId": pane_id,
                            "data": command + "\r",
                        }
                    )
                )
                await wait_for_output_marker(
                    client_a,
                    late_marker,
                    expected_session=self.history_session,
                    expected_pane=pane_id,
                )

            current_screen = await asyncio.to_thread(
                tmux,
                "capture-pane",
                "-p",
                "-t",
                pane_id,
            )
            self.assertNotIn(
                early_marker,
                current_screen.stdout,
                "the chosen history line must have scrolled off the current pane",
            )
            self.assertIn(
                late_marker,
                current_screen.stdout,
                "the line burst did not leave its final marker on the current pane",
            )

            # The old implementation stopped the bridge after 30 seconds.
            # Waiting beyond that exact contract boundary proves this is the
            # permanent recorder, not a still-live linger task.
            await asyncio.sleep(OLD_DETACH_LINGER_SECONDS + 1.0)
            persistent_pids = await asyncio.to_thread(
                tmux_control_pids,
                self.history_session,
            )
            self.assertTrue(
                recorder_pids & persistent_pids,
                "client disconnect replaced or stopped the permanent recorder",
            )
            self.assertTrue(
                tmux_session_exists(self.history_session),
                "client disconnect must not kill the tmux session",
            )

            # Client B did not exist when the line was emitted or while the old
            # linger window elapsed. Its first pane output is therefore the
            # attach snapshot whose recorder history is under test.
            async with websockets.connect(
                WS_URL,
                open_timeout=EVENT_TIMEOUT,
            ) as client_b:
                await recv_matching(
                    client_b,
                    lambda item: item.get("type") == "sessions",
                    description="sessions event for client B",
                )
                await client_b.send(
                    json.dumps({"type": "attach", "session": self.history_session})
                )
                reset_b = await recv_matching(
                    client_b,
                    lambda item: item.get("type") == "reset"
                    and item.get("session") == self.history_session,
                    description=f"client B reset for {self.history_session}",
                )
                self.assertEqual(pane_id_from_reset(reset_b), pane_id)
                snapshot = await recv_matching(
                    client_b,
                    lambda item: item.get("type") == "output"
                    and item.get("session") == self.history_session
                    and item.get("paneId") == pane_id,
                    description="client B attach snapshot",
                )
                self.assertIn(
                    early_marker,
                    str(snapshot.get("data", "")),
                    "attach snapshot omitted recorder history that predates client B",
                )

        asyncio.run(scenario())

    def test_65_session_death_removes_and_recreates_recorder(self) -> None:
        async def scenario() -> None:
            original_pids = await wait_for_control_process(self.death_session)
            self.assertTrue(
                original_pids,
                "always-on recorder did not start for the death-test session",
            )

            async with websockets.connect(
                WS_URL,
                open_timeout=EVENT_TIMEOUT,
            ) as websocket:
                initial = await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "sessions",
                    description="initial sessions event",
                )
                self.assertIn(
                    self.death_session,
                    {
                        item.get("session")
                        for item in initial.get("sessions", [])
                        if isinstance(item, dict)
                    },
                )

                kill_test_session(self.death_session)
                removed = await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "sessions"
                    and self.death_session
                    not in {
                        session.get("session")
                        for session in item.get("sessions", [])
                        if isinstance(session, dict)
                    },
                    description="sessions poll after recorder session death",
                    timeout=ROSTER_POLL_TIMEOUT,
                )
                self.assertIsInstance(removed.get("sessions"), list)
                self.assertTrue(
                    original_pids.isdisjoint(
                        await asyncio.to_thread(
                            tmux_control_pids,
                            self.death_session,
                        )
                    ),
                    "dead session retained a visible recorder control process",
                )

                # Reusing the exact session name catches a stale manager entry:
                # a leaked recorder would suppress creation of the new bridge.
                create_test_session(self.death_session)
                await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "sessions"
                    and self.death_session
                    in {
                        session.get("session")
                        for session in item.get("sessions", [])
                        if isinstance(session, dict)
                    },
                    description="recreated session in sessions poll",
                    timeout=ROSTER_POLL_TIMEOUT,
                )
                self.assertTrue(
                    await wait_for_control_process(
                        self.death_session,
                        timeout=ROSTER_POLL_TIMEOUT,
                    ),
                    "recreated session did not receive a fresh recorder",
                )

        asyncio.run(scenario())

    def test_70_unknown_session_returns_error_without_disconnect(self) -> None:
        async def scenario() -> None:
            missing = random_session("orrery-qa-missing")
            async with websockets.connect(WS_URL, open_timeout=EVENT_TIMEOUT) as websocket:
                await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "sessions",
                    description="sessions event",
                )
                await websocket.send(
                    json.dumps({"type": "attach", "session": missing})
                )
                error = await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "error",
                    description="unknown-session error",
                )
                self.assertIn(error.get("session"), {None, missing})
                self.assertIsInstance(error.get("message"), str)

                await websocket.send(
                    json.dumps({"type": "attach", "session": self.session_b})
                )
                await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "reset"
                    and item.get("session") == self.session_b,
                    description="valid reset after unknown-session error",
                )

        asyncio.run(scenario())

    def test_80_destructive_ops_refused_on_non_test_session(self) -> None:
        async def expect_refusal(websocket: Any, message_type: str, pane_id: str) -> None:
            payload: dict[str, Any] = {"type": message_type, "paneId": pane_id}
            if message_type == "split":
                payload["direction"] = "horizontal"
            await websocket.send(json.dumps(payload))
            error = await recv_matching(
                websocket,
                lambda item: item.get("type") == "error"
                and "refusing destructive op on non-test session"
                in str(item.get("message")),
                description=f"{message_type} safety refusal",
            )
            self.assertIn(error.get("session"), {None, self.guard_session})

        async def scenario() -> None:
            before = pane_count(self.guard_session)
            async with websockets.connect(WS_URL, open_timeout=EVENT_TIMEOUT) as websocket:
                await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "sessions",
                    description="sessions event",
                )
                await websocket.send(
                    json.dumps({"type": "attach", "session": self.guard_session})
                )
                reset = await recv_matching(
                    websocket,
                    lambda item: item.get("type") == "reset"
                    and item.get("session") == self.guard_session,
                    description=f"reset for {self.guard_session}",
                )
                pane_id = pane_id_from_reset(reset)
                await expect_refusal(websocket, "split", pane_id)
                await expect_refusal(websocket, "close", pane_id)
            self.assertEqual(pane_count(self.guard_session), before)

        asyncio.run(scenario())

    def test_90_agents_proxy_returns_json_without_crashing(self) -> None:
        status, payload = http_json("/telemetry/agents")
        self.assertIn(status, {200, 502})
        if status == 502:
            self.assertEqual(payload, {"error": "dashboard offline"})
        else:
            self.assertIsInstance(payload, (dict, list))

    def test_100_health_reports_backend_and_dashboard_reachability(self) -> None:
        status, body = http_response("/telemetry/health")
        if status == 404:
            self.skipTest("Cycle 3 health endpoint has not landed yet")

        payload = json_response(status, body)
        self.assertEqual(status, 200)
        self.assertIsInstance(payload, dict)
        # "boot" (11da62e) lets the cockpit reload after a backend restart;
        # "root" and "commit" (720a0e3) let setup.sh tell an old backend apart.
        self.assertEqual(set(payload), {"backend", "boot", "dashboard", "root", "commit"})
        self.assertEqual(payload["backend"], "ok")
        self.assertIsInstance(payload["boot"], str)
        self.assertTrue(payload["boot"])
        self.assertIsInstance(payload["dashboard"], bool)
        self.assertIsInstance(payload["root"], str)
        self.assertTrue(payload["root"])
        # None outside a git checkout (an unpacked release).
        self.assertTrue(payload["commit"] is None or isinstance(payload["commit"], str))

    def test_110_spawn_proxy_is_safe_for_dashboard_state(self) -> None:
        refusal = spawn_request_refusal()
        if refusal:
            self.skipTest(refusal)
        health_status, health_body = http_response("/telemetry/health")
        if health_status == 404:
            # Keep the spawn route independently testable while Cycle 3
            # endpoints are landing in parallel.
            agents_status, _ = http_response("/telemetry/agents")
            self.assertIn(agents_status, {200, 502})
            dashboard_reachable = agents_status == 200
        else:
            health = json_response(health_status, health_body)
            self.assertEqual(health_status, 200)
            self.assertIsInstance(health, dict)
            dashboard_reachable = health.get("dashboard")
        self.assertIsInstance(dashboard_reachable, bool)

        # Missing ``parent`` is intentionally invalid at the dashboard. Never
        # replace this with a valid payload: that would create a real agent,
        # tmux session, and possibly a Ghostty window.
        invalid_payload = {"task": "ORRERY E2E invalid spawn payload"}
        self.assertNotIn("parent", invalid_payload)
        status, body = http_response(
            "/telemetry/spawn",
            method="POST",
            json_body=invalid_payload,
        )
        if status in {404, 405}:
            self.skipTest("Cycle 3 spawn endpoint has not landed yet")

        payload = json_response(status, body)
        self.assertIsInstance(payload, dict)
        if dashboard_reachable:
            self.assertEqual(status, 400)
            self.assertEqual(set(payload), {"ok", "error"})
            self.assertIs(payload["ok"], False)
            self.assertIsInstance(payload["error"], str)
            self.assertTrue(payload["error"])
        else:
            self.assertEqual(status, 502)
            self.assertEqual(payload, {"error": "dashboard offline"})

    def test_112_spawn_catalog_proxy_shape(self) -> None:
        status, body = http_response("/telemetry/spawn-catalog")
        if status == 404:
            self.skipTest("Cycle 11 spawn catalog has not landed yet")
        self.assertIn(status, {200, 502})
        payload = json_response(status, body)
        if status == 502:
            self.assertEqual(payload, {"error": "dashboard offline"})
            return
        self.assertIsInstance(payload, dict)
        self.assertIsInstance(payload.get("providers"), list)
        self.assertTrue(payload["providers"])
        for provider in payload["providers"]:
            self.assertIn("id", provider)
            self.assertIsInstance(provider.get("models"), list)

    def test_114_skills_endpoint_lists_builtins(self) -> None:
        status, body = http_response("/telemetry/skills")
        if status == 404:
            self.skipTest("Cycle 11 skills endpoint has not landed yet")
        payload = json_response(status, body)
        self.assertEqual(status, 200)
        skills = payload.get("skills")
        self.assertIsInstance(skills, list)
        names = {entry.get("name") for entry in skills}
        # builtins are always present even if ~/.claude/skills is empty
        self.assertIn("compact", names)
        for entry in skills:
            self.assertIn(entry.get("kind"), {"builtin", "skill", "bundled"})
        # no ?program= means Claude, the historical behaviour
        self.assertEqual(payload.get("prefix", "/"), "/")

    def test_115_skills_endpoint_is_program_scoped(self) -> None:
        """Codex reads `$log`; serving it Claude's `/` vocabulary logs it out."""
        status, body = http_response("/telemetry/skills?program=codex")
        if status == 404:
            self.skipTest("skills endpoint has not landed yet")
        payload = json_response(status, body)
        self.assertEqual(status, 200)
        if payload.get("prefix") is None:
            self.skipTest("program-scoped skills have not landed yet")
        self.assertEqual(payload.get("program"), "codex")
        self.assertEqual(payload.get("prefix"), "$")

        claude = json_response(*http_response("/telemetry/skills?program=claude"))
        self.assertEqual(claude.get("prefix"), "/")

        # An unknown program must not fall through to an empty vocabulary: a
        # composer with no menu is recoverable, one with the wrong menu is not.
        unknown = json_response(*http_response("/telemetry/skills?program=nope"))
        self.assertEqual(unknown.get("program"), "claude")
        self.assertEqual(unknown.get("prefix"), "/")

    def test_117_clipboard_files_endpoint(self) -> None:
        """Paths for a Finder copy — the browser only ever sees a name."""
        status, body = http_response("/telemetry/clipboard/files")
        if status == 404:
            self.skipTest("clipboard endpoint has not landed yet")
        payload = json_response(status, body)
        self.assertEqual(status, 200)
        files = payload.get("files")
        self.assertIsInstance(files, list)
        # Whatever is on the developer's clipboard, the contract holds: a list
        # of absolute paths, and never an exception into the composer.
        for entry in files:
            self.assertIsInstance(entry, str)
            self.assertTrue(entry.startswith("/"), entry)

    def test_116_network_embed_passthrough(self) -> None:
        status, body = http_response("/network/?embed=1")
        if status == 404:
            self.skipTest("Cycle 11 network passthrough has not landed yet")
        self.assertIn(status, {200, 502})
        if status == 200:
            self.assertIn(b"<", body[:200])
        api_status, _ = http_response("/api/agents")
        self.assertIn(api_status, {200, 502})

    def test_118_spawn_dry_run_v2_argv(self) -> None:
        # The catalog probe that used to guard this proved nothing: the real
        # dashboard serves the catalog and still ignores dry_run (see
        # spawn_request_refusal). Only a fake dashboard may receive this.
        refusal = spawn_request_refusal()
        if refusal:
            self.skipTest(refusal)
        catalog_status, _ = http_response("/telemetry/spawn-catalog")
        if catalog_status != 200:
            self.skipTest("dashboard without cycle11 catalog")
        payload = {
            "standalone": True,
            "provider": "codex",
            "model": "gpt-5.6-sol",
            "effort": "low",
            "dir": "/tmp",
            "task": "ORRERY E2E dry-run probe",
            "headless": True,
            "dry_run": True,
        }
        status, body = http_response(
            "/telemetry/spawn", method="POST", json_body=payload,
        )
        result = json_response(status, body)
        self.assertEqual(status, 200)
        self.assertIs(result.get("ok"), True)
        self.assertIs(result.get("dry_run"), True)
        argv = result.get("argv")
        self.assertIsInstance(argv, list)
        self.assertIn("--standalone", argv)
        self.assertIn("--codex", argv)
        self.assertIn("gpt-5.6-sol", argv)


@unittest.skipUnless(V2_ENABLED, V2_SKIP_REASON)
class Cycle10PersistenceContractTest(unittest.TestCase):
    """Persisted recorder history must survive only the same tmux session."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(
            prefix="orrery-e2e-history-",
            dir="/private/tmp",
        )
        self.history_dir = Path(self.temp_dir.name)
        self.session = random_session("orrery-qa-persist")
        self.server: ManagedServer | None = None
        create_test_session(self.session)
        self._start_backend()

    def tearDown(self) -> None:
        try:
            if self.server is not None:
                self.server.stop()
        finally:
            try:
                kill_test_session(self.session)
            finally:
                self.temp_dir.cleanup()
        if tmux_session_exists(self.session):
            raise AssertionError(f"failed to clean up tmux session {self.session!r}")

    def _start_backend(self) -> None:
        server = ManagedServer(
            [
                sys.executable,
                str(V2_BACKEND),
                "--port",
                str(QA_PORT),
                "--tmux-bin",
                qa_tmux_bin(),
            ],
            env={"ORRERY_HISTORY_DIR": str(self.history_dir)},
        )
        server.start()
        self.server = server

    def _stop_backend(self) -> None:
        if self.server is None:
            return
        self.server.stop()
        self.server = None

    async def _emit_scrolled_markers(self) -> tuple[str, int, str, str]:
        recorder_pids = await wait_for_control_process(self.session)
        self.assertTrue(
            recorder_pids,
            "always-on recorder did not start for the persistence session",
        )
        expected_pane, session_created = await asyncio.to_thread(
            tmux_pane_identity,
            self.session,
        )
        marker_prefix = f"PERSIST_QA_{secrets.token_hex(6)}"
        early_marker = f"{marker_prefix}_000"
        late_marker = f"{marker_prefix}_199"
        command = (
            "i=0; while [ $i -lt 200 ]; do "
            f"printf '{marker_prefix}_%03d\\n' $i; "
            "i=$((i+1)); done"
        )

        async with websockets.connect(
            WS_URL,
            open_timeout=EVENT_TIMEOUT,
        ) as websocket:
            await recv_matching(
                websocket,
                lambda item: item.get("type") == "sessions",
                description="sessions event",
            )
            await websocket.send(
                json.dumps({"type": "attach", "session": self.session})
            )
            reset = await recv_matching(
                websocket,
                lambda item: item.get("type") == "reset"
                and item.get("session") == self.session,
                description=f"reset for {self.session}",
            )
            pane_id = pane_id_from_reset(reset)
            self.assertEqual(pane_id, expected_pane)
            await websocket.send(
                json.dumps(
                    {
                        "type": "input",
                        "paneId": pane_id,
                        "data": command + "\r",
                    }
                )
            )
            await wait_for_output_marker(
                websocket,
                late_marker,
                expected_session=self.session,
                expected_pane=pane_id,
            )

        current_screen = await asyncio.to_thread(
            tmux,
            "capture-pane",
            "-p",
            "-t",
            expected_pane,
        )
        self.assertNotIn(
            early_marker,
            current_screen.stdout,
            "persistence marker must be outside tmux's current screen",
        )
        self.assertIn(late_marker, current_screen.stdout)
        return expected_pane, session_created, early_marker, late_marker

    def _read_history_file(
        self,
        *,
        pane_id: str,
        session_created: int,
        early_marker: str,
    ) -> tuple[Path, dict[str, Any]]:
        files = sorted(self.history_dir.glob("*.json"))
        self.assertEqual(
            len(files),
            1,
            f"expected one persisted pane file in {self.history_dir}, got {files!r}",
        )
        history_file = files[0]
        payload = json.loads(history_file.read_text(encoding="utf-8"))
        self.assertIsInstance(payload, dict)
        self.assertTrue(
            {
                "schema",
                "session",
                "pane_id",
                "session_created",
                "saved_ts",
                "lines",
            }.issubset(payload),
            f"history file does not implement the Cycle 10-A schema: {payload!r}",
        )
        self.assertEqual(payload["schema"], 1)
        self.assertEqual(payload["session"], self.session)
        self.assertEqual(payload["pane_id"], pane_id)
        self.assertEqual(payload["session_created"], session_created)
        self.assertIsInstance(payload["saved_ts"], (int, float))
        self.assertIsInstance(payload["lines"], list)
        self.assertLessEqual(len(payload["lines"]), 2_000)
        self.assertTrue(all(isinstance(line, str) for line in payload["lines"]))
        self.assertIn(
            early_marker,
            payload["lines"],
            "graceful shutdown did not flush rendered recorder history",
        )
        return history_file, payload

    async def _attach_snapshot(self, pane_id: str) -> str:
        async with websockets.connect(
            WS_URL,
            open_timeout=EVENT_TIMEOUT,
        ) as websocket:
            await recv_matching(
                websocket,
                lambda item: item.get("type") == "sessions",
                description="sessions event after backend restart",
            )
            await websocket.send(
                json.dumps({"type": "attach", "session": self.session})
            )
            reset = await recv_matching(
                websocket,
                lambda item: item.get("type") == "reset"
                and item.get("session") == self.session,
                description=f"restart reset for {self.session}",
            )
            self.assertEqual(pane_id_from_reset(reset), pane_id)
            output = ""
            while True:
                try:
                    item = await recv_json(websocket, STREAM_QUIET_SECONDS)
                except TimeoutError:
                    break
                if (
                    item.get("type") == "output"
                    and item.get("session") == self.session
                    and item.get("paneId") == pane_id
                ):
                    output += str(item.get("data", ""))
            return output

    def test_history_survives_graceful_backend_restart(self) -> None:
        pane_id, session_created, early_marker, _ = asyncio.run(
            self._emit_scrolled_markers()
        )
        self._stop_backend()
        self._read_history_file(
            pane_id=pane_id,
            session_created=session_created,
            early_marker=early_marker,
        )

        self._start_backend()
        snapshot = asyncio.run(self._attach_snapshot(pane_id))
        self.assertIn(
            early_marker,
            snapshot,
            "backend B did not restore backend A's flushed recorder history",
        )

    def test_recreated_same_name_session_rejects_old_history(self) -> None:
        old_pane, old_created, early_marker, _ = asyncio.run(
            self._emit_scrolled_markers()
        )
        self._stop_backend()
        self._read_history_file(
            pane_id=old_pane,
            session_created=old_created,
            early_marker=early_marker,
        )

        kill_test_session(self.session)
        while int(time.time()) <= old_created:
            time.sleep(0.05)
        create_test_session(self.session)
        new_pane, new_created = tmux_pane_identity(self.session)
        self.assertEqual(
            new_pane,
            old_pane,
            "the isolated tmux server must reuse the pane id so this test "
            "exercises the created-ts guard, not a filename miss",
        )
        self.assertGreater(new_created, old_created)

        self._start_backend()
        snapshot = asyncio.run(self._attach_snapshot(new_pane))
        self.assertNotIn(
            early_marker,
            snapshot,
            "a recreated same-name session inherited the dead session's history",
        )


@unittest.skipUnless(V2_ENABLED, V2_SKIP_REASON)
class Cycle4MailPortraitContractTest(unittest.TestCase):
    """Cycle 4 mail reads and portrait resolution against isolated fixtures."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="orrery-e2e-cycle4-")
        cls.fixture_root = Path(cls.temp_dir.name)
        cls.mail_db = cls.fixture_root / "mail.sqlite3"
        cls.portraits_64 = cls.fixture_root / "portraits_64"
        cls.portraits_hi = cls.fixture_root / "portraits"
        cls.portraits_px = cls.fixture_root / "portraits_px"
        build_mail_fixture(cls.mail_db)
        cls.portraits_64.mkdir()
        cls.portraits_hi.mkdir()
        for directory in (cls.portraits_64, cls.portraits_hi):
            (directory / "CustomAgent.png").write_bytes(PNG_1X1 + b"exact")
            (directory / "Franklin.png").write_bytes(PNG_1X1 + b"suffix")
            (directory / "Galileo.png").write_bytes(PNG_1X1 + b"alias")
        cls.portraits_px.mkdir()
        (cls.portraits_px / "CustomAgent.png").write_bytes(
            PNG_1X1 + b"pixel-exact"
        )

        cls.server = ManagedServer(
            [
                sys.executable,
                str(V2_BACKEND),
                "--port",
                str(QA_PORT),
                "--tmux-bin",
                qa_tmux_bin(),
            ],
            env={
                "ORRERY_MAIL_DB": str(cls.mail_db),
                "ORRERY_PROJECT_KEY": FIXTURE_PROJECT_KEY,
                "ORRERY_PORTRAIT_DIR": str(cls.portraits_64),
                "ORRERY_PORTRAIT_DIR_HI": str(cls.portraits_hi),
                "ORRERY_PORTRAIT_DIR_PX": str(cls.portraits_px),
            },
        )
        try:
            cls.server.start()
        except Exception:
            try:
                cls.server.stop()
            finally:
                cls.temp_dir.cleanup()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.server.stop()
        finally:
            cls.temp_dir.cleanup()

    def assert_mail_meta(self, message: Any) -> None:
        self.assertIsInstance(message, dict)
        self.assertEqual(
            set(message),
            {
                "id",
                "ts",
                "sender",
                "recipients",
                "subject",
                "excerpt",
                "importance",
                "thread_id",
            },
        )
        self.assertIsInstance(message["id"], int)
        self.assertIsInstance(message["ts"], int)
        self.assertIsInstance(message["sender"], str)
        self.assertIsInstance(message["recipients"], list)
        self.assertTrue(
            all(
                isinstance(recipient, dict)
                and set(recipient) == {"name", "kind"}
                and isinstance(recipient["name"], str)
                and isinstance(recipient["kind"], str)
                for recipient in message["recipients"]
            )
        )
        self.assertIsInstance(message["subject"], str)
        self.assertIsInstance(message["excerpt"], str)
        self.assertLessEqual(len(message["excerpt"]), 120)
        self.assertIsInstance(message["importance"], str)
        self.assertTrue(
            message["thread_id"] is None or isinstance(message["thread_id"], str)
        )

    def test_mail_recent_shape_order_project_scope_and_agent_filter(self) -> None:
        status, payload = http_json("/telemetry/mail/recent?limit=40")
        self.assertEqual(status, 200)
        self.assertEqual(set(payload), {"ok", "now", "messages"})
        self.assertIs(payload["ok"], True)
        self.assertIsInstance(payload["now"], int)
        self.assertEqual(
            [message["id"] for message in payload["messages"]],
            [104, 103, 102, 101],
            "recent mail must be newest-first and exclude the other project",
        )
        for message in payload["messages"]:
            self.assert_mail_meta(message)

        by_id = {message["id"]: message for message in payload["messages"]}
        self.assertEqual(by_id[104]["excerpt"], "Final reply")
        self.assertEqual(by_id[103]["excerpt"], "status ready")
        self.assertEqual(
            {
                (recipient["name"], recipient["kind"])
                for recipient in by_id[101]["recipients"]
            },
            {("RedStone", "to"), ("GreenCastle", "cc")},
        )

        query = urllib.parse.urlencode({"limit": 40, "agent": "RedStone"})
        filter_status, filtered = http_json(f"/telemetry/mail/recent?{query}")
        self.assertEqual(filter_status, 200)
        self.assertIs(filtered["ok"], True)
        self.assertEqual(
            [message["id"] for message in filtered["messages"]],
            [104, 102, 101],
            "agent filter must match sender or any exact recipient",
        )

    def test_mail_message_body_and_not_found(self) -> None:
        status, payload = http_json("/telemetry/mail/message?id=102")
        self.assertEqual(status, 200)
        self.assertEqual(set(payload), {"ok", "message"})
        self.assertIs(payload["ok"], True)
        message = payload["message"]
        self.assertEqual(
            set(message),
            {
                "id",
                "ts",
                "sender",
                "recipients",
                "subject",
                "body_md",
                "importance",
                "thread_id",
            },
        )
        self.assertEqual(message["id"], 102)
        self.assertEqual(message["sender"], "RedStone")
        self.assertEqual(
            message["body_md"],
            "First reply\nWith the full body intact.",
        )

        missing_status, missing = http_json(
            "/telemetry/mail/message?id=999999"
        )
        self.assertEqual(missing_status, 404)
        self.assertEqual(missing, {"ok": False, "error": "not found"})

    def test_mail_thread_is_oldest_first(self) -> None:
        query = urllib.parse.urlencode(
            {"thread_id": "thread-cycle-4", "limit": 50}
        )
        status, payload = http_json(f"/telemetry/mail/thread?{query}")
        self.assertEqual(status, 200)
        self.assertEqual(set(payload), {"ok", "now", "messages"})
        self.assertIs(payload["ok"], True)
        self.assertEqual(
            [message["id"] for message in payload["messages"]],
            [101, 102, 104],
        )
        for message in payload["messages"]:
            self.assert_mail_meta(message)

    def assert_portrait(
        self,
        name: str,
        expected_marker: bytes,
        *,
        hi: bool = False,
        style: str | None = None,
    ) -> None:
        params = {"name": name, "hi": "1" if hi else "0"}
        if style is not None:
            params["style"] = style
        query = urllib.parse.urlencode(params)
        status, body, headers = http_response_with_headers(
            f"/telemetry/portrait?{query}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/png")
        self.assertEqual(body, PNG_1X1 + expected_marker)

    def test_portrait_exact_stem(self) -> None:
        self.assert_portrait("CustomAgent", b"exact", hi=True)

    def test_portrait_scientist_suffix(self) -> None:
        self.assert_portrait("WittyFranklin", b"suffix")

    def test_portrait_galilei_alias(self) -> None:
        self.assert_portrait("QuietGalilei", b"alias")

    def test_portrait_missing_name_returns_initials_svg(self) -> None:
        query = urllib.parse.urlencode({"name": "Unknown Person"})
        status, body, headers = http_response_with_headers(
            f"/telemetry/portrait?{query}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            headers.get("Content-Type", "").split(";", 1)[0],
            "image/svg+xml",
        )
        self.assertIn(b"<svg", body)

    def test_portrait_pixel_exact_stem_ignores_hi(self) -> None:
        self.assert_portrait(
            "CustomAgent",
            b"pixel-exact",
            hi=True,
            style="pixel",
        )

    def test_portrait_pixel_missing_name_returns_64px_initials_svg(self) -> None:
        query = urllib.parse.urlencode(
            {"name": "Unknown Person", "hi": "1", "style": "pixel"}
        )
        status, body, headers = http_response_with_headers(
            f"/telemetry/portrait?{query}"
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            headers.get("Content-Type", "").split(";", 1)[0],
            "image/svg+xml",
        )
        self.assertIn(b'<svg xmlns="http://www.w3.org/2000/svg" width="64"', body)
        self.assertIn(b">UN</text>", body)

    def test_portrait_unknown_style_preserves_existing_hi_behavior(self) -> None:
        self.assert_portrait(
            "CustomAgent",
            b"exact",
            hi=True,
            style="unknown",
        )


@unittest.skipUnless(V2_ENABLED, V2_SKIP_REASON)
class Cycle4CorruptMailDatabaseContractTest(unittest.TestCase):
    """A broken fixture path must degrade to dashboard-style JSON."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory(prefix="orrery-e2e-corrupt-")
        corrupt_db = Path(cls.temp_dir.name) / "corrupt.sqlite3"
        corrupt_db.write_bytes(b"this is deliberately not a sqlite database")
        cls.server = ManagedServer(
            [
                sys.executable,
                str(V2_BACKEND),
                "--port",
                str(QA_PORT),
                "--tmux-bin",
                qa_tmux_bin(),
            ],
            env={
                "ORRERY_MAIL_DB": str(corrupt_db),
                "ORRERY_PROJECT_KEY": FIXTURE_PROJECT_KEY,
            },
        )
        try:
            cls.server.start()
        except Exception:
            try:
                cls.server.stop()
            finally:
                cls.temp_dir.cleanup()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls.server.stop()
        finally:
            cls.temp_dir.cleanup()

    def test_mail_recent_reports_ok_false(self) -> None:
        status, payload = http_json("/telemetry/mail/recent?limit=40")
        self.assertEqual(status, 200)
        self.assertEqual(set(payload), {"ok", "error", "messages"})
        self.assertIs(payload["ok"], False)
        self.assertIsInstance(payload["error"], str)
        self.assertTrue(payload["error"])
        self.assertEqual(payload["messages"], [])


if __name__ == "__main__":
    unittest.main()
