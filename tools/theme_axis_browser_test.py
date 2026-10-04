#!/usr/bin/env python3
"""Run the cockpit theme-axis adversarial contract in a real browser.

This runner is intentionally stdlib-only.  It serves ``bridge/`` from an
ephemeral port, drives Chromium over CDP, and evaluates the checked-in browser
fixture.  Pytest opts into it with ``ORRERY_THEME_BROWSER=1``; it can also be
run directly when investigating a visual-guard regression.
"""

from __future__ import annotations

import base64
import contextlib
import glob
import json
import os
import random
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bridge"
FIXTURE = ROOT / "tools" / "fixtures" / "theme_axis_adversarial.js"
PROFILE_FIXTURE = ROOT / "tools" / "fixtures" / "theme_axis_profile.js"
IFRAME_FIXTURE = ROOT / "tools" / "fixtures" / "theme_axis_profile_iframe.js"
RECEIVER_FIXTURE = ROOT / "tools" / "fixtures" / "theme_profile_receiver.html"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] in {"/network", "/network/", "/network/index.html"}:
            payload = RECEIVER_FIXTURE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()


class _WebSocket:
    def __init__(self, url: str) -> None:
        _, rest = url.split("://", 1)
        hostport, path = rest.split("/", 1)
        host, port = hostport.split(":")
        self.socket = socket.create_connection((host, int(port)))
        key = base64.b64encode(os.urandom(16)).decode()
        self.socket.sendall(
            f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n".encode()
        )
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.socket.recv(1)
        self.buffer = response.split(b"\r\n\r\n", 1)[1]
        self.request_id = 0

    def _receive(self, size: int) -> bytes:
        while len(self.buffer) < size:
            chunk = self.socket.recv(65536)
            if not chunk:
                raise EOFError("CDP websocket closed")
            self.buffer += chunk
        result, self.buffer = self.buffer[:size], self.buffer[size:]
        return result

    def _message(self) -> dict[str, object]:
        first, second = self._receive(2)
        size = second & 0x7F
        if size == 126:
            size = struct.unpack("!H", self._receive(2))[0]
        elif size == 127:
            size = struct.unpack("!Q", self._receive(8))[0]
        return json.loads(self._receive(size))

    def call(self, method: str, **params: object) -> dict[str, object]:
        self.request_id += 1
        request_id = self.request_id
        data = json.dumps({"id": request_id, "method": method, "params": params}).encode()
        size = len(data)
        header = b"\x81"
        if size < 126:
            header += struct.pack("!B", size | 0x80)
        elif size < 65536:
            header += struct.pack("!BH", 126 | 0x80, size)
        else:
            header += struct.pack("!BQ", 127 | 0x80, size)
        mask = struct.pack("!I", random.getrandbits(32))
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
        self.socket.sendall(header + mask + payload)
        while True:
            message = self._message()
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(message["error"])
            return message.get("result", {})


def find_chrome() -> str | None:
    configured = os.environ.get("ORRERY_CHROME")
    if configured:
        return configured
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
    ]
    candidates.extend(sorted(glob.glob(
        str(Path.home() / "Library/Caches/ms-playwright/chromium_headless_shell-*/"
            "chrome-headless-shell-*/chrome-headless-shell")
    ), reverse=True))
    return next((str(candidate) for candidate in candidates if candidate and Path(candidate).is_file()), None)


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


def _run_browser_fixture(fixture: Path, chrome: str | None = None) -> dict[str, object]:
    executable = chrome or find_chrome()
    if not executable:
        raise RuntimeError("Chromium not found; set ORRERY_CHROME")
    handler = partial(_QuietHandler, directory=str(BRIDGE))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    cdp_port = _free_port()
    profile = tempfile.mkdtemp(prefix="orrery-theme-cdp-")
    process = subprocess.Popen(
        [executable, "--headless=new", "--use-mock-keychain", "--password-store=basic", "--no-sandbox", "--single-process", "--disable-gpu",
         f"--remote-debugging-port={cdp_port}", "--window-size=1600,1000",
         f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        tabs = None
        for _ in range(80):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json"))
                break
            except OSError:
                time.sleep(.1)
        if not tabs:
            raise RuntimeError("Chromium CDP endpoint did not start")
        page = next(tab for tab in tabs if tab["type"] == "page")
        client = _WebSocket(page["webSocketDebuggerUrl"])
        client.call("Page.enable")
        client.call("Runtime.enable")
        client.call("Network.enable")
        client.call("Network.setCacheDisabled", cacheDisabled=True)
        client.call(
            "Page.navigate",
            url=f"http://127.0.0.1:{server.server_port}/cockpit.html",
        )
        for _ in range(80):
            ready = client.call(
                "Runtime.evaluate",
                expression="document.readyState",
                returnByValue=True,
            ).get("result", {}).get("value")
            if ready == "complete":
                break
            time.sleep(.1)
        time.sleep(.5)
        evaluated = client.call(
            "Runtime.evaluate",
            expression=fixture.read_text(),
            awaitPromise=True,
            returnByValue=True,
        )
        if evaluated.get("exceptionDetails"):
            raise AssertionError(evaluated["exceptionDetails"])
        return evaluated["result"]["value"]
    finally:
        process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=5)
        if process.poll() is None:
            process.kill()
        server.shutdown();server.server_close();server_thread.join(timeout=2)
        shutil.rmtree(profile, ignore_errors=True)


def run_browser_contract(chrome: str | None = None) -> dict[str, object]:
    return _run_browser_fixture(FIXTURE, chrome)


def run_profile_contract(chrome: str | None = None) -> dict[str, object]:
    return _run_browser_fixture(PROFILE_FIXTURE, chrome)


def run_profile_iframe_contract(chrome: str | None = None) -> dict[str, object]:
    return _run_browser_fixture(IFRAME_FIXTURE, chrome)


def assert_browser_contract(result: dict[str, object]) -> None:
    normal = result["normal"]
    assert len(normal) == 20
    for record in normal:
        assert record["ok"] is True, record
        effect = record["effect"]
        assert effect["visibleReached"] == effect["visibleExpected"] > 0, record
        assert effect["visibleChanged"] > 0 and effect["changed"] > 0, record
    assert any(record["preReachedVisible"] > 0 for record in normal)

    for key in ("zero", "minimum"):
        records = result[key]
        assert len(records) == 5
        for record in records:
            assert record["ok"] is False and record["reason"] == "no-effective-change", record
            assert record["active"] is None, record

    important = result["adversarial"]["important"]
    assert important["beforeMembership"] == important["afterMembership"] > 0
    assert important["ok"] is False and important["reason"] == "effect-count-mismatch"
    assert important["effect"]["visibleReached"] < important["effect"]["visibleExpected"]
    for key in ("hidden", "offscreen"):
        record = result["adversarial"][key]
        assert record["ok"] is False and record["reason"] == "no-visible-targets", record
        assert record["active"] is None, record
    assert result["final"] == {"active": None, "runtimeStyle": False}


def assert_profile_contract(result: dict[str, object]) -> None:
    normal = result["normal"]
    assert normal["ok"] is True and normal["staleIgnored"] is True
    assert normal["values"]["small-text"] == .25
    assert normal["values"]["tracking"] == .25
    assert normal["stored"]["values"] == normal["values"]
    assert normal["axes"] == ["small-text", "tracking"]
    assert "small-text 0.25 / tracking 0.25" in normal["header"]
    assert "small-text 0.25 / tracking 0.25" in normal["settingsHeader"]

    handler_error = result["handlerError"]
    assert handler_error["accepted"] is False
    assert handler_error["reason"] == "telemetry-profile-handler-error"
    assert handler_error["observable"] is True and handler_error["rolledBack"] is True
    assert handler_error["elapsedMs"] < 2500
    assert handler_error["timeoutCallbacksRun"] is False

    order = result["order"]
    assert len(order) == 16
    for record in order:
        assert all(record[key] is True for key in
                   ("smallFirst", "smallFinal", "trackingFirst", "trackingFinal")), record
        assert record["membershipEqual"] is True and record["computedEqual"] is True, record
        assert record["members"] > 0, record

    negative = result["negativeControl"]
    assert negative["accepted"] is False
    assert negative["comparatorDetected"] is True
    assert negative["correctPairPassed"] is True
    assert negative["reason"].startswith(("mutation coverage", "effect-count-mismatch"))

    timeout = result["timeout"]
    assert timeout["accepted"] is False
    for key in ("candidateAppliedBeforeReplyLoss", "rollbackFreshId", "telemetryRolledBack",
                "cockpitRolledBack", "storageUnchanged", "historyUnchanged",
                "headerUnchanged", "lateIgnored", "recoveryIdle"):
        assert timeout[key] is True, (key, timeout)
    assert timeout["scheduledDelays"] and all(
        delay == 2500 for delay in timeout["scheduledDelays"])

    recovery = result["recovery"]
    assert recovery["accepted"] is False and recovery["recoveryCandidateApplied"] is True
    for key in ("recoveryCompleted", "busyBeforeReady", "telemetryRolledBack", "controlsEnabled"):
        assert recovery[key] is True, (key, recovery)
    assert recovery["reloads"] > 0

    ready_failure = result["readyFailure"]
    for key in ("busyWithoutReady", "observable", "bounded", "completedAfterReady"):
        assert ready_failure[key] is True, (key, ready_failure)
    assert result["aLevels"] == {"small-text": "true", "tracking": "true"}
    assert all(value is None for value in result["final"]["values"].values())
    assert result["final"]["pending"] is False


def assert_profile_iframe_contract(result: dict[str, object]) -> None:
    success = result["success"]
    assert success["accepted"] is True and success["readyExact"] is True
    assert success["receiver"] == success["cockpit"]
    assert success["axes"] == ["small-text", "tracking"]

    unit = result["unitMismatch"]
    assert unit["accepted"] is False
    assert unit["reason"] == "telemetry-profile-axis-failed"
    assert unit["receiverRolledBack"] is True and unit["cockpitRolledBack"] is True
    assert unit["recoveryIdle"] is True

    handler = result["handlerError"]
    assert handler["accepted"] is False
    assert handler["reason"] == "telemetry-profile-handler-error"
    assert handler["observable"] is True and handler["timedOut"] is False
    assert handler["elapsedMs"] < 2500
    assert handler["receiverRolledBack"] is True and handler["cockpitRolledBack"] is True

    reply = result["replyLoss"]
    assert reply["accepted"] is False and reply["appliedBeforeReplyLoss"] is True
    assert reply["receiverRolledBack"] is True and reply["cockpitRolledBack"] is True
    assert reply["recoveryIdle"] is True

    recovery = result["recovery"]
    assert recovery["accepted"] is False and recovery["profileReadyObserved"] is True
    assert recovery["receiverRolledBack"] is True and recovery["cockpitRolledBack"] is True
    assert recovery["controlsEnabled"] is True

    ready_loss = result["readyLoss"]
    for key in ("axisReadyObserved", "profileReadyNotSubstituted", "observable",
                "controlsDisabled", "persistentStatus", "receiverRolledBack",
                "cockpitRolledBack"):
        assert ready_loss[key] is True, (key, ready_loss)


if __name__ == "__main__":
    output = run_browser_contract()
    assert_browser_contract(output)
    print(json.dumps(output, indent=2))
