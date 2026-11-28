import asyncio
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import time

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


SERVER = """\
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
        root=str(root), commit=commit, runtime={"runtime_mode":"legacy"}, restart_guard=True))
app = web.Application(middlewares=[backend.own_page_only, backend.json_writes_only,
                                  backend.track_backend_writes])
app[backend.BACKEND_ACTIVITY_KEY] = backend.BackendActivity()
app.on_shutdown.append(backend.close_backend_websockets)
app.router.add_get("/telemetry/health", health)
app.router.add_get("/telemetry/backend-operation", backend.backend_operation)
app.router.add_post(backend.BACKEND_RESTART_ROUTE, backend.backend_restart_guard)
web.run_app(app, host="127.0.0.1", port=int(sys.argv[1]), print=None)
"""


def await_health(port):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        health = lifecycle.read_health(port)
        if health:
            return health
        time.sleep(0.04)
    pytest.fail("fixture backend did not start")


@pytest.mark.parametrize("mode", ["mac-sidecar", "wsl-launcher"])
def test_restarts_only_backend_after_a_finished_checkout(tmp_path, monkeypatch, mode):
    tmux = shutil.which("tmux")
    if tmux is None:
        pytest.skip("tmux is required for the restart integration fixture")
    if sys.platform not in ("darwin", "linux"):
        pytest.skip("requires one of the backend host operating systems")
    root = tmp_path.resolve()
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

    def wsl(action, *args):
        result = subprocess.run(["bash", launcher, str(port), action, root, *args],
                                env=env, capture_output=True, timeout=30)
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
                async with client.ws_connect(f"http://127.0.0.1:{port}/telemetry/backend-operation?kind=permission+restart") as lease:
                    assert (await lease.receive()).data == "ready"
                    if mode == "wsl-launcher":
                        answer = await asyncio.to_thread(wsl, "restart", boot, new, "automatic")
                        result = json.loads(answer.rstrip(b"\0"))
                    else:
                        result = await asyncio.to_thread(lifecycle.stop_stale, port, root, RUNTIME, boot, new, True)
                    assert result == {"state": "busy", "operations": ["permission restart"]}
        asyncio.run(check_busy())
        if mode == "mac-sidecar":
            assert lifecycle.stop_stale(port, root, RUNTIME, boot, new, True) == {"state": "stopped"}
            children[0].wait(timeout=5)
            children.append(subprocess.Popen([sys.executable, str(script), str(port)], env=env))
        else:
            stop, _, _, health = wsl("restart", boot, new, "automatic").split(b"\0")
            assert json.loads(stop) == {"state": "stopped"}
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
