"""start-cockpit.sh checks the orrery-telemetry API generation and whether a
newer release is out, and never stops for either (2026-09-30).

Run from bridge/: ``python -m pytest tests/test_start_cockpit_telemetry.py``.

The script runs against a fake dashboard and a fake GitHub with a private
HOME and AGENTSTACK_HOME. TMUX_BIN points at nothing, so the run stops at the
prerequisite check (after these checks) and never creates a venv or starts a
backend. Nothing here reaches the real GitHub.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "start-cockpit.sh"
# macOS keeps bash 3.2 at /bin/bash; the script must work there.
BASH = "/bin/bash" if Path("/bin/bash").exists() else shutil.which("bash")
MIN_API = int(re.search(r"^MIN_TELEMETRY_API=(\d+)$", SCRIPT.read_text(), re.M).group(1))
CURRENT = "2026.09.30.1"


def test_no_release_date_is_hard_coded():
    """2026-09-30: the script should not need an edit for every release."""
    code = [line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#")]
    assert not [line for line in code if re.search(r"\b20\d\d\.\d\d\.\d\d", line)]


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
    ("2026.09.30.1", "2026.10.01", 0),
    ("abc", "2026.09.30.1", 2),
    ("2026..1", "2026.09.30.1", 2),
    ("2026.09.30.1-dev", "2026.09.30.1", 2),
    ("", "2026.09.30.1", 2),
])
def test_versions_compare_as_date_and_count(a, b, expected):
    assert version_older(a, b) == expected


def serve(routes: dict[str, tuple[int, bytes]], delay: float = 0.0, trickle: float = 0.0):
    """A tiny HTTP server; records the paths it was asked for. With trickle,
    the body goes out a few bytes at a time, that many seconds apart."""
    asked: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            asked.append(self.path)
            time.sleep(delay)
            status, body = routes.get(self.path, (404, b"{}"))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not trickle:
                self.wfile.write(body)
                return
            for start in range(0, len(body), 8):
                try:
                    self.wfile.write(body[start:start + 8])
                    self.wfile.flush()
                except OSError:
                    return
                time.sleep(trickle)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", asked


def closed_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}/releases/latest"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def dashboard(version_body: bytes | None):
    routes = {"/api/agents": (200, b'{"agents": []}')}
    if version_body is not None:
        routes["/api/version"] = (200, version_body)
    return serve(routes)


def github(tag: str | None = None, status: int = 200, delay: float = 0.0, trickle: float = 0.0):
    body = json.dumps({"tag_name": tag}).encode() if tag else b'{"message": "API rate limit exceeded"}'
    return serve({"/releases/latest": (status, body)}, delay, trickle)


def version(v: str | None, api=MIN_API) -> bytes:
    data = {"name": "orrery-telemetry"}
    if v is not None:
        data["version"] = v
    if api is not None:
        data["api"] = api
    return json.dumps(data).encode()


def start(tmp_path, dash_url: str, releases_url: str | None = None, script: Path = SCRIPT,
          **env_extra) -> str:
    home = tmp_path / "home"
    agentstack = home / ".agentstack"
    agentstack.mkdir(parents=True, exist_ok=True)
    (agentstack / "env.sh").write_text(f"export AGENTSTACK_PROJECT_KEY='{tmp_path}'\n")
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "AGENTSTACK_HOME": str(agentstack),
        "ORRERY_DASHBOARD_URL": dash_url,
        "ORRERY_UPDATE_CHECK_URL": releases_url or closed_url(),
        "ORRERY_VENV": str(tmp_path / "venv"),
        "PORT": str(free_port()),
        "TMUX_BIN": str(tmp_path / "no-tmux"),
        **env_extra,
    }
    result = subprocess.run([BASH, str(script), "--check"], env=env, capture_output=True,
                            text=True, timeout=60, check=False)
    # Stopped by the missing tmux alone, as intended: the warnings are not
    # counted as missing prerequisites, and no venv was created.
    assert result.returncode == 1 and "Stopped: 1 prerequisite(s) missing" in result.stdout, result.stdout
    assert not (tmp_path / "venv" / "bin").exists()
    return result.stdout


# ---------------------------------------------------------------- positive
# Nothing to report: no WARN and no "newer" note, and the start goes on.

def quiet(out: str):
    assert "WARN" not in out and "newer orrery-telemetry" not in out, out


@pytest.mark.parametrize("api, local, latest", [
    (MIN_API, CURRENT, CURRENT),           # same release
    (MIN_API, "2026.10.01", CURRENT),      # GitHub's is older than this one
    (MIN_API + 1, CURRENT, CURRENT),       # a later API generation is fine
])
def test_positive_current_api_and_no_newer_release(tmp_path, api, local, latest):
    dash, dash_url, _ = dashboard(version(local, api=api))
    gh, gh_url, asked = github(latest)
    out = start(tmp_path, dash_url, gh_url + "/releases/latest")
    assert f"ok    orrery-telemetry version: {local} (API {api})" in out
    quiet(out)
    assert asked == ["/releases/latest"]  # it did ask, and found nothing newer
    dash.shutdown(), gh.shutdown()


@pytest.mark.parametrize("kind", ["offline", "slow", "trickle", "403", "429", "bad json", "bad tag"])
def test_positive_a_failed_release_check_is_silent(tmp_path, kind):
    dash, dash_url, _ = dashboard(version("2026.09.30"))  # older: a note would show if asked well
    gh = None
    if kind == "offline":
        url = closed_url()
    else:
        gh, base, _ = {
            "slow": lambda: github(CURRENT, delay=6),
            # VioletBohr 2026-09-30: a few bytes every 1.2 s kept each read under
            # urllib's per-read timeout, and the lookup took 6.8 s in all.
            "trickle": lambda: github(CURRENT, trickle=1.2),
            "403": lambda: github(None, status=403),
            "429": lambda: github(None, status=429),
            "bad json": lambda: serve({"/releases/latest": (200, b"{not json")}),
            "bad tag": lambda: github("latest"),
        }[kind]()
        url = base + "/releases/latest"
    began = time.monotonic()
    out = start(tmp_path, dash_url, url)
    quiet(out)
    # The whole lookup is cut off at 3 s; the rest of the check takes about 1 s.
    assert time.monotonic() - began < 5.5
    dash.shutdown()
    if gh:
        gh.shutdown()


def test_positive_turned_off_asks_github_nothing(tmp_path):
    dash, dash_url, _ = dashboard(version("2026.09.30"))
    gh, gh_url, asked = github(CURRENT)
    out = start(tmp_path, dash_url, gh_url + "/releases/latest", ORRERY_NO_UPDATE_CHECK="1")
    quiet(out)
    assert asked == []
    dash.shutdown(), gh.shutdown()


def test_positive_a_cache_younger_than_a_day_is_used(tmp_path):
    dash, dash_url, _ = dashboard(version("2026.09.30"))
    gh, gh_url, asked = github(CURRENT)
    releases = gh_url + "/releases/latest"
    (tmp_path / "venv").mkdir()  # an existing venv folder holds the cache
    for _ in range(2):
        assert "newer orrery-telemetry is available" in start(tmp_path, dash_url, releases)
    assert asked == ["/releases/latest"]  # the second run asked nobody
    cache = json.loads((tmp_path / "venv" / ".orrery-telemetry-latest.json").read_text())
    assert cache["tag"] == CURRENT and cache["url"] == releases
    dash.shutdown(), gh.shutdown()


# ---------------------------------------------------------------- negative
# Something to report: the words must be in the output (a silent run fails).

@pytest.mark.parametrize("body, found", [
    (version(CURRENT, api=MIN_API - 1), f"has API {MIN_API - 1}"),
    (version(CURRENT, api=None), "does not report an API generation"),
    (version(CURRENT, api="1"), "does not report an API generation"),
    (None, "could not read its API generation"),        # /api/version is 404
    (b"not json", "could not read its API generation"),
    (json.dumps({"name": "other", "api": 9}).encode(), "could not read its API generation"),
])
def test_negative_an_old_or_unknown_api_is_a_warning(tmp_path, body, found):
    dash, dash_url, _ = dashboard(body)
    out = start(tmp_path, dash_url)  # start() also checks the start was not stopped by it
    assert f"WARN  This cockpit needs orrery-telemetry API {MIN_API} or later; " in out
    assert found in out
    assert "resuming a Codex agent that has exited" in out
    assert "with this command (the cockpit starts anyway):" in out
    assert f"          {SCRIPT.parent}/update.sh\n" in out
    dash.shutdown()


@pytest.mark.parametrize("local, latest", [
    ("2026.09.30", "2026.09.30.1"),
    ("2026.09.30.1", "2026.10.01"),
    ("2026.09.30", "2026.10.01"),
])
def test_negative_a_newer_release_is_a_two_line_note(tmp_path, local, latest):
    dash, dash_url, _ = dashboard(version(local))
    gh, gh_url, _ = github(latest)
    out = start(tmp_path, dash_url, gh_url + "/releases/latest")
    notes = [line for line in out.splitlines() if line.startswith("  note")]
    assert notes == [
        f"  note  a newer orrery-telemetry is available: {latest} (this one is {local}).",
        "  note  Update it, then this cockpit, with:",
        f"  note    {SCRIPT.parent}/update.sh",
    ]
    assert "WARN" not in out  # the API is new enough; being behind is only news
    dash.shutdown(), gh.shutdown()


def test_negative_an_old_api_and_a_newer_release_show_the_steps_once(tmp_path):
    dash, dash_url, _ = dashboard(version("2026.09.29.1", api=None))
    gh, gh_url, _ = github(CURRENT)
    out = start(tmp_path, dash_url, gh_url + "/releases/latest")
    assert "WARN  This cockpit needs orrery-telemetry API" in out
    assert f"  note  a newer orrery-telemetry is available: {CURRENT} (this one is 2026.09.29.1)." in out
    assert out.count("/update.sh\n") == 1
    dash.shutdown(), gh.shutdown()


def test_negative_a_cache_older_than_a_day_is_asked_again(tmp_path):
    dash, dash_url, _ = dashboard(version("2026.09.30"))
    gh, gh_url, asked = github(CURRENT)
    releases = gh_url + "/releases/latest"
    venv = tmp_path / "venv"
    venv.mkdir()
    (venv / ".orrery-telemetry-latest.json").write_text(json.dumps(
        {"url": releases, "checked": time.time() - 25 * 60 * 60, "tag": "2026.09.29"}))
    out = start(tmp_path, dash_url, releases)
    assert asked == ["/releases/latest"]
    assert f"newer orrery-telemetry is available: {CURRENT}" in out  # GitHub's answer, not the stale one
    assert json.loads((venv / ".orrery-telemetry-latest.json").read_text())["tag"] == CURRENT
    dash.shutdown(), gh.shutdown()


def test_the_cache_is_written_in_the_venv_folder_and_nowhere_else(tmp_path):
    """VioletBohr 2026-09-30: without a venv folder this never reached the
    branch that writes the cache."""
    dash, dash_url, _ = dashboard(version("2026.09.30"))
    gh, gh_url, _ = github(CURRENT)
    (tmp_path / "venv").mkdir()
    start(tmp_path, dash_url, gh_url + "/releases/latest")
    everything = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    # home/.agentstack/env.sh is the test's own setup.
    assert everything == ["home", "home/.agentstack", "home/.agentstack/env.sh",
                          "venv", "venv/.orrery-telemetry-latest.json"]
    dash.shutdown(), gh.shutdown()


def test_the_update_command_it_shows_can_be_pasted_even_from_a_folder_with_a_space(tmp_path):
    """VioletBohr 2026-09-30: the hint ended in "(orrery-telemetry first, ...)",
    which is a syntax error when pasted, and the path was not quoted."""
    checkout = tmp_path / "my cockpit"
    (checkout / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT, checkout / "scripts" / "start-cockpit.sh")
    dash, dash_url, _ = dashboard(version(CURRENT, api=MIN_API - 1))
    out = start(tmp_path, dash_url, script=checkout / "scripts" / "start-cockpit.sh")
    dash.shutdown()
    lines = out.splitlines()
    hint = lines[lines.index(next(line for line in lines if "with this command" in line)) + 1].strip()
    assert subprocess.run([BASH, "-n", "-c", hint], check=False).returncode == 0
    words = subprocess.run([BASH, "-c", 'set -- ' + hint + '; printf "%s\\n" "$#" "$1"'],
                           capture_output=True, text=True, check=True).stdout.splitlines()
    assert words == ["1", str(checkout / "scripts" / "update.sh")]
