"""start-cockpit.sh warns about an old orrery-telemetry, and never stops for it
(2026-09-30).

Run from bridge/: ``python -m pytest tests/test_start_cockpit_version.py``.

The script runs against a fake dashboard with a private HOME and
AGENTSTACK_HOME. TMUX_BIN points at nothing, so the run stops at the
prerequisite check (after the version check) and never creates a venv or
starts a backend.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "start-cockpit.sh"
# macOS keeps bash 3.2 at /bin/bash; the script must work there.
BASH = "/bin/bash" if Path("/bin/bash").exists() else shutil.which("bash")
MIN_VERSION = re.search(r"^MIN_TELEMETRY_VERSION=(\S+)$", SCRIPT.read_text(), re.M).group(1)


def version_older(a: str, b: str) -> int:
    body = re.search(r"^version_older\(\) \{\n.*?^\}\n", SCRIPT.read_text(), re.M | re.S).group(0)
    return subprocess.run([BASH, "-c", body + 'version_older "$1" "$2"', "-", a, b],
                          capture_output=True, text=True, check=False).returncode


@pytest.mark.parametrize("a, b, expected", [
    ("2026.09.30", "2026.09.30.1", 0),
    ("2026.09.29.9", "2026.09.30.1", 0),
    ("2026.09.08", "2026.09.30.1", 0),       # "08" is not octal
    ("2026.09.30.1", "2026.09.30.1", 1),
    ("2026.09.30.2", "2026.09.30.1", 1),
    ("2026.10.01", "2026.09.30.1", 1),
    ("2027.01.01", "2026.09.30.1", 1),
    ("abc", "2026.09.30.1", 2),
    ("2026..1", "2026.09.30.1", 2),
    ("2026.09.30.1-dev", "2026.09.30.1", 2),
    ("", "2026.09.30.1", 2),
])
def test_versions_compare_as_date_and_count(a, b, expected):
    assert version_older(a, b) == expected


class FakeDashboard(BaseHTTPRequestHandler):
    version_body: bytes | None = None

    def do_GET(self):  # noqa: N802
        if self.path == "/api/agents":
            body = b'{"agents": []}'
        elif self.path == "/api/version" and self.version_body is not None:
            body = self.version_body
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(tmp_path, version_body: bytes | None) -> subprocess.CompletedProcess:
    handler = type("Handler", (FakeDashboard,), {"version_body": version_body})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    home = tmp_path / "home"
    agentstack = home / ".agentstack"
    agentstack.mkdir(parents=True)
    (agentstack / "env.sh").write_text(f"export AGENTSTACK_PROJECT_KEY='{tmp_path}'\n")
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "AGENTSTACK_HOME": str(agentstack),
        "ORRERY_DASHBOARD_URL": f"http://127.0.0.1:{server.server_address[1]}",
        "ORRERY_VENV": str(tmp_path / "venv"),
        "PORT": str(free_port()),
        "TMUX_BIN": str(tmp_path / "no-tmux"),
    }
    try:
        result = subprocess.run([BASH, str(SCRIPT), "--check"], env=env, capture_output=True,
                                text=True, timeout=60, check=False)
    finally:
        server.shutdown()
    # Stopped by the missing tmux, as intended: nothing was created or started.
    assert result.returncode == 1 and "tmux is not installed" in result.stdout, result.stdout
    assert not (tmp_path / "venv").exists()
    return result


def version(v: str) -> bytes:
    return json.dumps({"name": "orrery-telemetry", "version": v, "api": 1}).encode()


def test_a_current_telemetry_passes_quietly(tmp_path):
    out = start(tmp_path, version(MIN_VERSION)).stdout
    assert f"ok    orrery-telemetry version: {MIN_VERSION}" in out
    assert "WARN" not in out


def test_an_old_telemetry_is_a_warning_with_what_breaks_and_how_to_update(tmp_path):
    out = start(tmp_path, version("2026.09.30")).stdout
    assert f"WARN  orrery-telemetry 2026.09.30 is older than {MIN_VERSION}" in out
    assert "resuming a Codex agent that has exited" in out
    assert "git pull && ./scripts/install.sh" in out
    # Only tmux stops this run; the old version is not counted as missing.
    assert "Stopped: 1 prerequisite(s) missing" in out


@pytest.mark.parametrize("body", [None, b"not json", json.dumps({"name": "other", "version": "9"}).encode()])
def test_an_unreadable_version_is_one_note(tmp_path, body):
    out = start(tmp_path, body).stdout
    lines = [line for line in out.splitlines() if "orrery-telemetry version" in line]
    assert len(lines) == 1 and lines[0].startswith("  note  could not read the orrery-telemetry version")
    assert "WARN" not in out and "Stopped: 1 prerequisite(s) missing" in out


def test_a_version_in_another_form_is_one_note(tmp_path):
    out = start(tmp_path, version("2026.09.30.1-dev")).stdout
    assert "reports version '2026.09.30.1-dev', which is not in the usual form" in out
    assert "WARN" not in out
