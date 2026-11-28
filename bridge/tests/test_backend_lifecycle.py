import asyncio
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from aiohttp import ClientSession, web

import backend_lifecycle as lifecycle
import orrery_backend as backend

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = {"runtime_mode": "legacy"}


def commit(root, message):
    subprocess.run(["git", "-C", root, "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit",
                    "--allow-empty", "-qm", message], check=True)
    return lifecycle.installed_commit(root)


def test_guard_blocks_restart_until_grouped_operation_and_http_write_finish():
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()

        async def write(_request):
            started.set()
            await finish.wait()
            return web.json_response({"ok": True})

        app = web.Application(middlewares=[backend.own_page_only, backend.json_writes_only,
                                           backend.track_backend_writes])
        app[backend.BACKEND_ACTIVITY_KEY] = backend.BackendActivity()
        app.on_shutdown.append(backend.close_backend_websockets)
        app.router.add_get("/telemetry/backend-operation", backend.backend_operation)
        app.router.add_post(backend.BACKEND_RESTART_ROUTE, backend.backend_restart_guard)
        app.router.add_post("/api/exit", write)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        url = f"http://127.0.0.1:{runner.addresses[0][1]}"
        restart = {"action": "drain", "boot": backend.BACKEND_BOOT_ID}
        try:
            async with ClientSession() as http:
                async with http.ws_connect(url + "/telemetry/backend-operation?kind=batch+send") as batch:
                    assert (await batch.receive()).data == "ready"
                    pending = asyncio.create_task(http.post(url + "/api/exit", json={}))
                    await asyncio.wait_for(started.wait(), 2)
                    async with http.post(url + backend.BACKEND_RESTART_ROUTE, json=restart) as response:
                        assert await response.json() == {"state": "busy", "operations": ["batch send", "exit"]}
                    finish.set()
                    response = await pending
                    assert (await response.json())["ok"]
                    async with http.post(url + backend.BACKEND_RESTART_ROUTE, json=restart) as response:
                        assert await response.json() == {"state": "busy", "operations": ["batch send"]}
                async with http.post(url + backend.BACKEND_RESTART_ROUTE, json=restart) as response:
                    drained = await response.json()
                    assert drained["state"] == "drained"
                async with http.post(url + "/api/exit", json={}) as response:
                    assert response.status == 503
                async with http.post(url + backend.BACKEND_RESTART_ROUTE,
                                     json={**restart, "action": "release", "token": drained["token"]}) as response:
                    assert (await response.json())["state"] == "released"
        finally:
            finish.set()
            await runner.cleanup()

    asyncio.run(run())


def test_shutdown_restores_open_terminal_windows_in_parallel(monkeypatch):
    async def run():
        manager = backend.SessionBridgeManager("tmux")
        restoring = set()
        restored = set()
        stopped = set()
        peak = 0

        def make_bridge(name):
            async def restore(window, snapshot):
                nonlocal peak
                assert (window, snapshot) == ("@1", "original size")
                restoring.add(name)
                peak = max(peak, len(restoring))
                await asyncio.sleep(.06)
                restoring.remove(name)
                restored.add(name)
                return True

            async def stop():
                assert name in restored
                stopped.add(name)

            return SimpleNamespace(clients=set(), client_locks={}, _fresh_peer_proofs={},
                                   config=SimpleNamespace(session=name), stop=stop,
                                   restore_window_size=restore)

        for name in ("One", "Two", "Three"):
            manager.states[name] = backend.SessionState(
                bridge=make_bridge(name), claimed_windows={"@1": "original size"})

        async def attach(peer, attached, payload):
            name = payload["session"]
            manager.states[name].bridge.clients.add(peer)
            attached.add(name)
            await peer.send_json({"attached": name})

        async def session_list(_tmux):
            return []

        async def close_manager(_app):
            await manager.close()

        monkeypatch.setattr(manager, "handle_message", attach)
        monkeypatch.setattr(backend, "shared_session_list", session_list)
        app = web.Application()
        app[backend.BACKEND_ACTIVITY_KEY] = backend.BackendActivity()
        app[backend.BRIDGE_MANAGER_KEY] = manager
        app[backend.TMUX_BIN_KEY] = "tmux"
        app.router.add_get("/ws", backend.websocket_handler)
        app.on_shutdown.append(backend.close_backend_websockets)
        app.on_cleanup.append(close_manager)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        async with ClientSession() as http, http.ws_connect(f"http://127.0.0.1:{port}/ws") as peer:
            await peer.receive_json()
            for name in manager.states:
                await peer.send_json({"type": "attach", "session": name})
                assert await peer.receive_json() == {"attached": name}
            await asyncio.gather(runner.cleanup(), peer.receive())
        assert restored == stopped == {"One", "Two", "Three"}
        assert peak == 3

    asyncio.run(run())


@pytest.mark.parametrize("state", ["exited", "port occupied", "still running"])
def test_shutdown_rechecks_at_the_deadline(monkeypatch, state):
    clock = 0.0

    def sleep(seconds):
        nonlocal clock
        clock = round(clock + seconds, 3)

    monkeypatch.setattr(lifecycle, "BACKEND_STOP_TIMEOUT", 0.3)
    monkeypatch.setattr(lifecycle, "time", SimpleNamespace(monotonic=lambda: clock, sleep=sleep))
    before = {"birth": "fixture"}
    observer = SimpleNamespace(process=lambda _pid: before if clock < 0.3 or state == "still running" else None)
    timings = {}
    listener = socket.socket()
    try:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        if state == "port occupied":
            listener.listen()
        else:
            listener.close()
        if state == "exited":
            lifecycle._wait_for_backend_exit(123, None, observer, "fixture", port, timings)
        else:
            reason = "port is still in use" if state == "port occupied" else "did not exit"
            with pytest.raises(lifecycle.LifecycleError, match=reason):
                lifecycle._wait_for_backend_exit(123, None, observer, "fixture", port, timings)
    finally:
        listener.close()
    assert clock == 0.3
    assert ("process_exited_at" in timings) is (state != "still running")
    assert ("port_cleared_at" in timings) is (state != "port occupied")


SERVER = """\
import asyncio
import os
from pathlib import Path
import sys
from aiohttp import web
import orrery_backend as backend
from backend_lifecycle import installed_commit

root = Path(__file__).resolve().parents[1]
commit = installed_commit(root)
async def health(request):
    return web.json_response(dict(backend="ok", boot=backend.BACKEND_BOOT_ID,
        root=str(root), commit=commit, runtime={"runtime_mode":"legacy"}, restart_guard=True,
        listening_at=backend.BACKEND_LISTENING_AT))
app = web.Application(middlewares=[backend.own_page_only, backend.json_writes_only,
                                  backend.track_backend_writes])
app[backend.BACKEND_ACTIVITY_KEY] = backend.BackendActivity()
app.on_shutdown.append(backend.close_backend_websockets)
async def finish_cleanup(_app):
    delay = root / "slow-shutdown"
    if delay.exists():
        seconds = float(delay.read_text())
        delay.unlink()
    else:
        seconds = .3
    await asyncio.sleep(seconds)
app.on_shutdown.append(finish_cleanup)
app.router.add_get("/telemetry/health", health)
app.router.add_get("/telemetry/backend-operation", backend.backend_operation)
app.router.add_post(backend.BACKEND_RESTART_ROUTE, backend.backend_restart_guard)
web.run_app(app, host="127.0.0.1", port=int(sys.argv[1]), print=backend._announce_listener)
"""


def await_health(port):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        health = lifecycle.read_health(port)
        if health:
            return health
        time.sleep(0.04)
    pytest.fail("fixture backend did not start")


@pytest.fixture
def lifecycle_root():
    with tempfile.TemporaryDirectory(prefix="orrery-life-", dir="/tmp") as root:
        yield Path(root).resolve()


@pytest.mark.parametrize("mode", ["mac-sidecar", "wsl-launcher"])
@pytest.mark.parametrize("operation", ["permission restart", "exit", "batch send"])
def test_restarts_only_backend_after_a_finished_checkout(lifecycle_root, monkeypatch, mode, operation):
    tmux = shutil.which("tmux")
    if tmux is None:
        pytest.skip("tmux is required for the restart integration fixture")
    if sys.platform not in ("darwin", "linux"):
        pytest.skip("requires one of the backend host operating systems")
    root = lifecycle_root
    bridge = root / "bridge"
    bridge.mkdir()
    script = bridge / "orrery_backend.py"
    # Keep the real backend import separate from the process's launcher path.
    script.write_text(SERVER.replace("import orrery_backend as backend",
                                   "sys.path.remove(str(Path(__file__).resolve().parent))\n"
                                   "import orrery_backend as backend"))
    for name in ("backend_lifecycle.py", "mobile_input.py", "question_screen.py"):
        shutil.copy(ROOT / "bridge" / name, bridge)
    (bridge / "runtime_target.py").write_text('print(\'{"env": {}, "identity": {"runtime_mode": "legacy"}}\')\n')
    subprocess.run(["git", "init", "-q", root], check=True)
    subprocess.run(["git", "-C", root, "add", "bridge"], check=True)
    old = commit(root, "Old checkout")
    (root / "scripts").mkdir()
    (root / "scripts" / "start-cockpit.sh").write_text(
        f'cd {shlex.quote(str(bridge))}\nexec {shlex.quote(sys.executable)} orrery_backend.py "$PORT"\n')
    shim_dir = root / "bin"
    shim_dir.mkdir()
    app_socket = root / "app.sock"
    tmux_shim = shim_dir / "tmux"
    tmux_shim.write_text(f'#!/bin/bash\nshift 2\nexec {shlex.quote(tmux)} -S {shlex.quote(str(app_socket))} -f /dev/null "$@"\n')
    tmux_shim.chmod(0o700)
    agents = [tmux, "-S", str(root / "agents.sock"), "-f", "/dev/null"]
    app_tmux = [tmux, "-S", str(app_socket)]
    env = {**os.environ, "PATH": str(shim_dir) + ":" + os.environ["PATH"],
           "PYTHONPATH": str(ROOT / "bridge"), "ORRERY_PYTHON": sys.executable,
           "ORRERY_DASHBOARD_URL": "http://127.0.0.1:1", "XDG_STATE_HOME": str(root / "state")}
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    monkeypatch.setenv("XDG_STATE_HOME", env["XDG_STATE_HOME"])
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    children = []
    launcher = ROOT / "app/src-tauri/src/wsl-backend.sh"

    def run_wsl(action, *args):
        return subprocess.run(["bash", launcher, str(port), action, root, *args],
                              env=env, capture_output=True, timeout=30)

    def wsl(action, *args):
        result = run_wsl(action, *args)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        return result.stdout

    try:
        subprocess.run([*agents, "new-session", "-d", "-s", "unchanged", "sleep 90"], env=env, check=True)
        if mode == "mac-sidecar":
            children.append(subprocess.Popen([sys.executable, str(script), str(port)], env=env))
        else:
            wsl("start")
        before = await_health(port)
        boot = before["boot"]
        assert before["commit"] == old
        new = commit(root, "New checkout")
        previous_script = script.read_text()
        script.write_text(previous_script + "\n# incomplete checkout\n")
        result = lifecycle.stop_stale(port, root, RUNTIME, boot, new, True)
        assert result == {"state": "busy", "operations": ["checkout"]}
        assert lifecycle.read_health(port)["boot"] == boot
        script.write_text(previous_script)
        with pytest.raises(lifecycle.LifecycleError, match="changed"):
            lifecycle.stop_stale(port, root, RUNTIME, "10-2", new, True)
        async def check_busy():
            async with ClientSession() as client:
                query = urlencode({"kind": operation})
                async with client.ws_connect(f"http://127.0.0.1:{port}/telemetry/backend-operation?{query}") as lease:
                    assert (await lease.receive()).data == "ready"
                    if mode == "wsl-launcher":
                        answer = await asyncio.to_thread(wsl, "restart", boot, new, "automatic")
                        result = json.loads(answer.rstrip(b"\0"))
                    else:
                        result = await asyncio.to_thread(lifecycle.stop_stale, port, root, RUNTIME, boot, new, True)
                    assert result == {"state": "busy", "operations": [operation]}
        asyncio.run(check_busy())
        slow_shutdown = mode == "wsl-launcher" and operation == "permission restart"
        if slow_shutdown:
            (root / "slow-shutdown").write_text("8.2")
        stopped = {"state": "stopped", "boot": boot, "installed_commit": new}
        if mode == "mac-sidecar":
            assert lifecycle.stop_stale(port, root, RUNTIME, boot, new, True) == stopped
            children[0].wait(timeout=5)
            children.append(subprocess.Popen([sys.executable, str(script), str(port)], env=env))
        else:
            stop, _, _, health = wsl("restart", boot, new, "automatic").split(b"\0")
            assert json.loads(stop) == stopped
            assert json.loads(health)["commit"] == new
        after = await_health(port)
        assert after["commit"] == new and after["boot"] != boot
        subprocess.run([*agents, "has-session", "-t", "=unchanged"], env=env, check=True)
        # Simulate a rollback of the running code while HEAD remains new.
        fake_old = {**after, "commit": old}
        with monkeypatch.context() as patch:
            patch.setattr(lifecycle, "read_health", lambda _port: fake_old)
            assert lifecycle.stop_stale(port, root, RUNTIME, after["boot"], new, True) == {"state": "spent"}
        lifecycle._log_restart({"boot": boot, "running_commit": old, "installed_commit": new,
                                "waited": ["batch send", "checkout"], "error": None}, port, root, RUNTIME)
        log = json.loads((root / "state/orrery/backend-updates.jsonl").read_text())
        assert (log["old_sha"], log["new_sha"], log["waited"], log["error"]) == (
            old, new, ["batch send", "checkout"], None)
        assert str(log["new_pid"]) == after["boot"].split("-")[1]
        term, exited, cleared, listening = (datetime.fromisoformat(log[key]) for key in (
            "term_sent_at", "process_exited_at", "port_cleared_at", "new_listening_at"))
        assert term <= cleared <= listening
        assert term <= exited <= listening
        if slow_shutdown:
            assert (exited - term).total_seconds() > 8
        assert log["new_listening_at"] == after["listening_at"]
        print(f"{mode} {operation}: TERM to port clear {(cleared-term).total_seconds():.3f}s, "
              f"TERM to exit {(exited-term).total_seconds():.3f}s")

        # Exercise a failed real startup, rollback of HEAD, and a manual retry
        # carrying the stale context still present in the open error banner.
        script.write_text("raise SystemExit(23)\n")
        subprocess.run(["git", "-C", root, "add", "bridge/orrery_backend.py"], check=True)
        bad = commit(root, "Fail at startup")
        failed_boot = after["boot"]
        if mode == "mac-sidecar":
            assert lifecycle.stop_stale(port, root, RUNTIME, failed_boot, bad, True) == {
                "state": "stopped", "boot": failed_boot, "installed_commit": bad,
            }
            children[-1].wait(timeout=5)
            failed = subprocess.run([sys.executable, str(script), str(port)], env=env, timeout=5)
            assert failed.returncode == 23
        else:
            failed = run_wsl("restart", failed_boot, bad, "automatic")
            assert failed.returncode != 0
            assert json.loads(failed.stdout.rstrip(b"\0"))["installed_commit"] == bad
        assert lifecycle.read_health(port) is None
        subprocess.run(["git", "-C", root, "checkout", "-q", "--detach", new], check=True)
        # Simulate a failed stop with an old backend that exited later and no
        # acknowledgement from the helper. The button must still recover it.
        lifecycle._attempt_file(root, RUNTIME, port, bad).unlink()
        recovered = {"state": "stopped", "boot": failed_boot, "installed_commit": new}
        if mode == "mac-sidecar":
            assert lifecycle.stop_stale(port, root, RUNTIME, failed_boot, bad, False) == recovered
            children.append(subprocess.Popen([sys.executable, str(script), str(port)], env=env))
        else:
            answer, _, _, health = wsl("restart", failed_boot, bad, "manual").split(b"\0")
            assert json.loads(answer) == recovered
            assert json.loads(health)["commit"] == new
        healthy = await_health(port)
        assert healthy["commit"] == new and healthy["boot"] != failed_boot
        if mode == "mac-sidecar":
            unchanged = lifecycle.stop_stale(port, root, RUNTIME, failed_boot, bad, False)
        else:
            unchanged = json.loads(wsl("restart", failed_boot, bad, "manual").rstrip(b"\0"))
        assert unchanged["state"] == "current" and unchanged["restarted"] is False
        assert lifecycle.read_health(port)["boot"] == healthy["boot"]
        subprocess.run([*agents, "has-session", "-t", "=unchanged"], env=env, check=True)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for command in (agents, app_tmux):
            subprocess.run([*command, "kill-server"], env=env, capture_output=True, timeout=5)
