"""Recorder recovery for a replaced legacy default tmux server."""
import asyncio
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_target import LegacyTargetBoundary, TargetRefused
from orrery_backend import SessionBridgeManager
from control_server import HISTORY_SCHEMA, history_file_path
import orrery_backend as ob


@pytest.fixture
def default_server(monkeypatch):
    tmux = shutil.which("tmux")
    if not tmux:
        pytest.skip("tmux unavailable")
    base = "/private/tmp" if Path("/private/tmp").is_dir() else tempfile.gettempdir()
    with tempfile.TemporaryDirectory(prefix="orrc-", dir=base) as temp:
        root = Path(temp)
        home = root / "home"
        home.mkdir(mode=0o700)
        tempdir = root / "sockets"
        socket_dir = tempdir / f"tmux-{os.getuid()}"
        socket_dir.mkdir(parents=True, mode=0o700)
        socket = socket_dir / "default"
        for key in list(os.environ):
            if key.startswith(("AGENTSTACK_", "MCP_AGENT_")) or key in (
                "TMUX", "TMUX_PANE", "AGENT_NAME", "PARENT_AGENT",
                "CHILD_REGISTRATION_TOKEN",
            ):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("AGENTSTACK_HOME", str(home))
        monkeypatch.setenv("TMUX_TMPDIR", str(tempdir))
        env = dict(os.environ)
        root_value = os.environ.get("ORRERY_TEST_TELEMETRY_ROOT")
        if not root_value:
            pytest.fail("ORRERY_TEST_TELEMETRY_ROOT is required")
        library = runpy.run_path(str(Path(root_value) / "tests/_installed_client_payload.py"))
        library["copy_client_library"](home)
        command = [tmux, "-S", str(socket)]

        def run(*args, check=True):
            result = subprocess.run([*command, *args], env=env, capture_output=True,
                                    text=True, check=False, timeout=8)
            if check and result.returncode:
                raise RuntimeError(f"tmux {args}: {result.stderr.strip() or result.stdout.strip()}")
            return result

        run("new-session", "-d", "-s", "before", "sleep", "300")
        try:
            yield tmux, home, env, socket, run
        finally:
            run("kill-server", check=False)


def test_replaced_socket_is_not_retried_inside_a_refused_admission(default_server):
    binary, home, env, socket, run = default_server
    boundary = LegacyTargetBoundary(binary, home=home, environ=env)
    before = boundary.transport.identity
    assert boundary.admit("capture", session="before")["allowed"]
    run("kill-server")
    run("new-session", "-d", "-s", "after", "sleep", "300")
    assert boundary.socket_replaced()
    with pytest.raises(TargetRefused, match="^TMUX_SOCKET_CHANGED$"):
        boundary.admit("capture", session="after")
    assert boundary.transport.identity == before
    assert boundary.rebind_server()
    assert boundary.transport.identity != before
    assert boundary.admit("capture", session="after")["allowed"]


def test_rebind_rejects_another_restart_during_validation(default_server, monkeypatch):
    binary, home, env, _, run = default_server
    boundary = LegacyTargetBoundary(binary, home=home, environ=env)
    original = boundary.history_server()
    run("kill-server")
    run("new-session", "-d", "-s", "second", "sleep", "300")
    global_proofs = boundary.shared["global_proofs"]

    def restart_during_check(*args):
        run("kill-server")
        run("new-session", "-d", "-s", "third", "sleep", "300")
        return global_proofs(*args)

    with monkeypatch.context() as changes:
        changes.setitem(boundary.shared, "global_proofs", restart_during_check)
        with pytest.raises(TargetRefused, match="^TMUX_SOCKET_CHANGED$"):
            boundary.rebind_server()
    assert boundary.generation == 0 and boundary.history_server() == original
    assert boundary.rebind_server()
    boundary.observe_server_pid(original["pid"], generation=0)
    assert not boundary.tmux_restarted
    assert boundary.admit("capture", session="third")["allowed"]


def test_recorder_rebuilds_bridges_and_preserves_new_session(default_server):
    binary, home, env, socket, run = default_server
    boundary = LegacyTargetBoundary(binary, home=home, environ=env)
    async def scenario():
        manager = SessionBridgeManager(boundary, history_dir=home/"history")
        try:
            await manager._reconcile_sessions()
            assert set(manager.states) == {"before"}
            old = manager.states["before"].bridge
            old_pid = boundary.pin["server_pid"]
            run("kill-server")
            await asyncio.sleep(0.5)
            run("new-session", "-d", "-s", "after", "sleep", "300")
            assert old_pid != int(run("display-message", "-p", "#{pid}").stdout.strip())
            await manager._reconcile_sessions()
            assert set(manager.states) == {"after"}
            assert old._closed
            assert boundary.admit("capture", session="after")["allowed"]
            assert not boundary.socket_replaced()
            await manager._reconcile_sessions()
            assert set(manager.states) == {"after"}
            former = manager.states["after"].bridge
            run("kill-server")
            await asyncio.sleep(0.5)
            run("new-session", "-d", "-s", "again", "sleep", "300")
            await manager._reconcile_sessions()
            assert set(manager.states) == {"again"}
            assert former._closed
            assert boundary.admit("capture", session="again")["allowed"]
        finally:
            await manager.close()
    asyncio.run(scenario())


def test_old_websocket_cannot_inherit_reused_pane_on_server_rollover(default_server):
    binary, home, env, socket, run = default_server
    boundary = LegacyTargetBoundary(binary, home=home, environ=env)

    class Peer:
        def __init__(self):
            self.response = self
            self.closed = False
            self.messages = []

        async def send(self, data):
            return None

        async def send_json(self, payload):
            self.messages.append(payload)

        async def close(self, *, code, message):
            assert code == 1012
            self.closed = True

    async def scenario():
        manager = SessionBridgeManager(boundary, history_dir=home / "history")
        try:
            await manager._reconcile_sessions()
            old = manager.states["before"]
            peer = Peer()
            attached = set()
            await manager.attach(peer, attached, "before")
            assert manager._legacy_peers[peer] == 0
            run("kill-server")
            await asyncio.sleep(0.5)
            # Reuse the session name and numeric pane ID on the replacement.
            run("new-session", "-d", "-s", "before", "sleep", "300")
            await manager._reconcile_sessions()
            current = manager.states["before"]
            assert current is not old and old.bridge._closed
            assert peer.closed
            assert manager._legacy_peers[peer] != manager._legacy_epoch
            # The numeric pane ID may be identical, but old peers may not
            # write to the new session without a fresh attachment.
            with pytest.raises(TargetRefused, match="^TMUX_SOCKET_CHANGED$"):
                await manager.handle_message(peer, attached, {
                    "type": "input", "paneId": next(iter(current.bridge.panes)), "data": "stale",
                })
        finally:
            await manager.close()

    asyncio.run(scenario())


def test_untrusted_replacement_socket_is_not_adopted(default_server):
    binary, home, env, socket, run = default_server
    boundary = LegacyTargetBoundary(binary, home=home, environ=env)
    original = boundary.transport.identity
    run("kill-server")
    # The socket path is owned by the test, but a symlink/file is never
    # a legitimate replacement tmux server even under that directory.
    if socket.exists():
        socket.unlink()
    socket.symlink_to(home)
    assert not socket.is_socket()
    with pytest.raises(TargetRefused, match="^TMUX_SOCKET_UNSAFE$"):
        boundary.socket_replaced()
    assert boundary.transport.identity == original
    assert boundary.pin["server_pid"] is not None


def test_inherited_tmux_pin_is_not_silently_replaced(default_server):
    binary, home, env, socket, run = default_server
    pid = run("display-message", "-p", "#{pid}").stdout.strip()
    inherited = {**env, "TMUX": f"{socket},{pid},0"}
    boundary = LegacyTargetBoundary(binary, home=home, environ=inherited)
    run("kill-server")
    run("new-session", "-d", "-s", "after", "sleep", "300")
    assert not boundary.socket_replaced()
    with pytest.raises(TargetRefused, match="^TMUX_SOCKET_CHANGED$"):
        boundary.rebind_server()
    with pytest.raises(TargetRefused):
        boundary.admit("capture", session="after")


def test_recovery_errors_are_rate_limited(capsys):
    manager = SessionBridgeManager("tmux")
    for _ in range(1000):
        manager._log_attach_error("same", TargetRefused("TMUX_SOCKET_CHANGED"))
    assert capsys.readouterr().err.count("TMUX_SOCKET_CHANGED") == 1


@pytest.mark.parametrize("retirement_failure", ["stop-error", "process-still-alive"])
def test_retirement_retries_before_repinning(monkeypatch, tmp_path, retirement_failure):
    async def scenario():
        boundary = object.__new__(LegacyTargetBoundary)
        boundary.generation = 0
        events = []
        can_stop = False
        stopping = asyncio.Event()
        release = asyncio.Event()

        def rebind():
            events.append("rebound")
            boundary.generation += 1
            return True

        async def stop():
            events.append("stop")
            stopping.set()
            await release.wait()
            if retirement_failure == "stop-error" and not can_stop:
                raise OSError("stop interrupted")

        monkeypatch.setattr(boundary, "socket_replaced", lambda: True)
        monkeypatch.setattr(boundary, "rebind_server", rebind)
        manager = SessionBridgeManager(boundary, history_dir=tmp_path)
        process = SimpleNamespace(poll=lambda: 0 if can_stop else None)
        bridge = SimpleNamespace(stop=stop, process=process, clients=set())
        manager.states["same-name"] = ob.SessionState(bridge=bridge)
        peer = object()
        assert manager._legacy_peer_current(peer)
        recovery = asyncio.create_task(manager._recover_legacy_socket())
        try:
            await asyncio.wait_for(stopping.wait(), timeout=5)
            assert not manager._legacy_peer_current(peer)
            with pytest.raises(TargetRefused, match="^TMUX_SOCKET_CHANGED$"):
                await manager._ensure_bridge("same-name", legacy_epoch=0)
            release.set()
            assert not await recovery
            assert boundary.generation == 0 and not manager.states
            can_stop = True
            assert await manager._recover_legacy_socket()
            assert boundary.generation == 1
            assert events == ["stop", "stop", "rebound"]
            assert not manager._legacy_peer_current(peer)
            assert manager._legacy_peer_current(object())
        finally:
            release.set()
            await recovery
            await manager.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("with_provenance", [False, True])
def test_same_second_session_does_not_restore_old_server_history(default_server, with_provenance):
    binary, home, env, _, run = default_server
    boundary = LegacyTargetBoundary(binary, home=home, environ=env)
    old = boundary.pinned_copy()
    run("kill-server")
    run("new-session", "-d", "-s", "before", "sleep", "300")
    assert boundary.rebind_server()
    assert boundary.history_server() != old.history_server()

    bridge = ob.SessionTmuxBridge(ob.ControlConfig(
        host=ob.DEFAULT_HOST, port=0, session="before", session_created=1,
        tmux_bin=boundary.pinned_copy(), history_dir=home / "history",
    ))
    history = history_file_path(bridge._history_dir, "before", "%0")
    history.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": HISTORY_SCHEMA, "session": "before", "pane_id": "%0",
        "session_created": 1, "saved_ts": ob.time.time(), "lines": ["old-server"],
    }
    if with_provenance:
        payload["legacy_server"] = old.history_server()
    history.write_text(json.dumps(payload))
    assert bridge._read_restored_history("%0") == []
    assert not history.exists()


@pytest.mark.parametrize("old_result", ["cached", "pending", "pending-error"])
def test_rebound_server_replaces_shared_roster_for_all_waiters(monkeypatch, tmp_path, old_result):
    boundary = object.__new__(LegacyTargetBoundary)
    boundary.generation = 0
    current = "before"
    calls = []
    started = threading.Event()
    release = threading.Event()
    rosters = {
        name: [{"session": name, "created": created}]
        for name, created in (("before", 1), ("after", 2))
    }

    def rebind():
        nonlocal current
        current = "after"
        boundary.generation += 1
        return True

    def listing(target):
        assert target is boundary
        observed = current
        calls.append(observed)
        if observed == "before":
            started.set()
            if old_result != "cached":
                assert release.wait(10), "old roster was not released"
            if old_result == "pending-error":
                raise OSError("retired tmux server")
        return rosters[observed]

    monkeypatch.setattr(boundary, "socket_replaced", lambda: current == "before")
    monkeypatch.setattr(boundary, "rebind_server", rebind)
    monkeypatch.setattr(ob, "list_tmux_sessions", listing)
    monkeypatch.setattr(ob, "_session_list_shared", {})
    # The old entry cannot expire on its own and conceal a missing invalidation.
    monkeypatch.setattr(ob, "SESSION_LIST_SHARE_SECONDS", float("inf"))

    async def scenario():
        manager = SessionBridgeManager(boundary, history_dir=tmp_path)
        first = asyncio.create_task(ob.shared_session_list(boundary))
        second = asyncio.create_task(ob.shared_session_list(boundary))
        try:
            assert await asyncio.to_thread(started.wait, 10), "old roster did not start"
            if old_result == "cached":
                assert await first == rosters["before"]
                assert await second == rosters["before"]
            assert await manager._recover_legacy_socket()
            release.set()
            assert await ob.shared_session_list(boundary) == rosters["after"]
            if old_result != "cached":
                assert await first == rosters["after"]
                assert await second == rosters["after"]
            assert calls == ["before", "after"]
        finally:
            release.set()
            await asyncio.gather(first, second, return_exceptions=True)
            await manager.close()

    asyncio.run(scenario())
