"""Closed-session status is conservative and exact.

Run from bridge/: ``python -m pytest tests/test_closed_session_removal.py``.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import control_server
from control_server import ControlConfig, TmuxControlBridge, tmux_session_gone  # noqa: E402


def completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["tmux"], returncode, stdout=stdout)


@pytest.mark.parametrize(
    "answer,expected",
    [
        (True, {"sessionGone": True}),
        (False, {"sessionGone": False}),
        (None, {}),
    ],
)
@pytest.mark.parametrize("source", ["exit", "eof", "read-error"])
def test_closed_status_reports_only_a_reliable_tmux_answer(monkeypatch, answer, expected, source):
    bridge = TmuxControlBridge(
        ControlConfig(host="127.0.0.1", port=0, session="Brisk", tmux_bin="tmux")
    )
    events = []
    monkeypatch.setattr(control_server, "tmux_session_gone", lambda *_: answer)

    async def scenario():
        emitted = asyncio.Event()

        async def broadcast(payload):
            events.append(payload)
            emitted.set()

        bridge.broadcast = broadcast  # type: ignore[method-assign]
        if source == "exit":
            bridge._handle_line("%exit")
        else:
            bridge.master_fd = 42

            def read(*_args):
                if source == "read-error":
                    raise OSError("control client closed")
                return b""

            monkeypatch.setattr(control_server.os, "read", read)
            bridge._read_ready()
        await asyncio.wait_for(emitted.wait(), 1)

    asyncio.run(scenario())

    assert events == [
        {"type": "status", "state": "closed", "session": "Brisk",
         "incarnation": bridge._incarnation, **expected}
    ]


@pytest.mark.parametrize("source", ["exit", "eof", "read-error"])
def test_closed_reader_is_removed_and_tmux_is_checked_only_once(monkeypatch, source):
    bridge = TmuxControlBridge(
        ControlConfig(host="127.0.0.1", port=0, session="Brisk", tmux_bin="tmux")
    )
    checked = []

    def probe(*args):
        checked.append(args)
        return True

    monkeypatch.setattr(control_server, "tmux_session_gone", probe)

    async def scenario():
        events = []
        emitted = asyncio.Event()
        loop = asyncio.get_running_loop()
        reader, writer = os.pipe()
        os.set_blocking(reader, False)
        bridge.master_fd = reader
        bridge._loop = loop
        loop.add_reader(reader, bridge._read_ready)

        async def broadcast(payload):
            events.append(payload)
            emitted.set()

        bridge.broadcast = broadcast  # type: ignore[method-assign]
        try:
            if source == "exit":
                bridge._handle_line("%exit")
                bridge._handle_line("%exit")
            elif source == "read-error":
                with monkeypatch.context() as patch:
                    def read_error(*_args):
                        raise OSError("control client closed")

                    patch.setattr(control_server.os, "read", read_error)
                    bridge._read_ready()
                    bridge._read_ready()
            else:
                os.close(writer)
                writer = None

            await asyncio.wait_for(emitted.wait(), 1)
            # A readable EOF would otherwise keep invoking the callback here.
            await asyncio.sleep(.02)
            assert checked == [("tmux", "Brisk")]
            assert len(events) == 1
            assert loop.remove_reader(reader) is False, "closed reader was still registered"
        finally:
            loop.remove_reader(reader)
            os.close(reader)
            if writer is not None:
                os.close(writer)

    asyncio.run(scenario())


def test_event_loop_stays_responsive_during_the_tmux_check(monkeypatch):
    bridge = TmuxControlBridge(
        ControlConfig(host="127.0.0.1", port=0, session="Brisk", tmux_bin="tmux")
    )
    progressed = threading.Event()
    progress_during_probe = []

    def slow_probe(*_args):
        time.sleep(.1)
        progress_during_probe.append(progressed.is_set())
        return True

    monkeypatch.setattr(control_server, "tmux_session_gone", slow_probe)

    async def scenario():
        emitted = asyncio.Event()

        async def broadcast(_payload):
            emitted.set()

        async def heartbeat():
            await asyncio.sleep(.01)
            progressed.set()

        bridge.broadcast = broadcast  # type: ignore[method-assign]
        beat = asyncio.create_task(heartbeat())
        bridge._handle_line("%exit")
        await asyncio.wait_for(emitted.wait(), 1)
        await beat

    asyncio.run(scenario())
    assert progress_during_probe == [True]


@pytest.mark.parametrize("stop_before_release", [False, True])
def test_queued_old_closed_is_identified_or_cancelled_before_a_new_reset(
    monkeypatch, tmp_path, stop_before_release
):
    from orrery_backend import WebSocketPeer

    monkeypatch.setattr(control_server, "tmux_session_gone", lambda *_: True)

    async def scenario():
        output_began = asyncio.Event()
        closed_waiting = asyncio.Event()
        release = asyncio.Event()
        events = []

        class Response:
            async def send_str(self, raw):
                event = json.loads(raw)
                if event['type'] == 'output':
                    output_began.set()
                    await release.wait()
                events.append(event)

        peer = WebSocketPeer(Response())
        old = TmuxControlBridge(ControlConfig(
            host='127.0.0.1', port=0, session='B', tmux_bin='unused',
            history_dir=tmp_path, session_created=1,
        ))
        new = TmuxControlBridge(ControlConfig(
            host='127.0.0.1', port=0, session='B', tmux_bin='unused',
            history_dir=tmp_path, session_created=2,
        ))
        old.clients.add(peer)
        old_send = old.send_json

        async def observe_old_send(websocket, payload):
            if payload.get('state') == 'closed':
                closed_waiting.set()
            await old_send(websocket, payload)

        old.send_json = observe_old_send
        output = asyncio.create_task(old.send_json(peer, {
            'type': 'output', 'session': 'B', 'data': 'old final bytes',
        }))
        await output_began.wait()
        old._handle_line('%exit')
        await asyncio.wait_for(closed_waiting.wait(), 1)
        reset = asyncio.create_task(new.send_snapshot(peer))
        await asyncio.sleep(0)
        if stop_before_release:
            # The close task is already awaiting its client's send lock.
            await old.stop()
        release.set()
        await asyncio.gather(output, reset)
        if not stop_before_release:
            await old._closed_task
        try:
            if stop_before_release:
                assert [event['type'] for event in events] == ['output', 'reset']
            else:
                assert [event['type'] for event in events] == ['output', 'reset', 'status']
                assert events[1]['incarnation'] != events[2]['incarnation']
                assert events[2]['sessionGone'] is True
        finally:
            await old.stop()
            await new.stop()

    asyncio.run(scenario())


def test_a_prefix_match_does_not_keep_a_gone_session(monkeypatch):
    calls = []

    def run(argv, **_kwargs):
        calls.append(argv)
        if argv[1] == "has-session":
            return completed(1)
        return completed(0, "BriskFermi\n")

    monkeypatch.setattr(control_server.subprocess, "run", run)

    assert tmux_session_gone("tmux", "Brisk") is True
    assert calls[0] == ["tmux", "has-session", "-t", "=Brisk"]


@pytest.mark.parametrize(
    "has_returncode,list_returncode,probe_returncode",
    [(2, None, None), (1, 1, 1)],
)
def test_an_unreliable_tmux_check_keeps_the_group(
    monkeypatch, has_returncode, list_returncode, probe_returncode
):
    def run(argv, **_kwargs):
        if argv[1] == "has-session":
            return completed(has_returncode)
        if argv[1] == "list-sessions":
            assert list_returncode is not None
            return completed(list_returncode)
        assert probe_returncode is not None
        return completed(probe_returncode)

    monkeypatch.setattr(control_server.subprocess, "run", run)

    assert tmux_session_gone("tmux", "Brisk") is None


def test_a_live_tmux_server_with_no_sessions_confirms_the_session_is_gone(monkeypatch):
    answers = iter([completed(1), completed(1), completed(0)])
    monkeypatch.setattr(control_server.subprocess, "run", lambda *_args, **_kwargs: next(answers))

    assert tmux_session_gone("tmux", "Brisk") is True


def test_an_unavailable_tmux_binary_keeps_the_group(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise FileNotFoundError("tmux")

    monkeypatch.setattr(control_server.subprocess, "run", unavailable)

    assert tmux_session_gone("tmux", "Brisk") is None


def test_a_tmux_timeout_keeps_the_group(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("tmux", 1)

    monkeypatch.setattr(control_server.subprocess, "run", timeout)

    assert tmux_session_gone("tmux", "Brisk") is None


@pytest.mark.skipif(shutil.which("tmux") is None, reason="no tmux")
def test_exact_session_identity_against_an_isolated_tmux_server(monkeypatch):
    tmux = shutil.which("tmux")
    temporary = tempfile.TemporaryDirectory(prefix="orrery-gone-", dir="/tmp")
    socket = str(Path(temporary.name) / "tmux.sock")
    original_run = subprocess.run

    def isolated_run(argv, **kwargs):
        return original_run([argv[0], "-f", "/dev/null", "-S", socket, *argv[1:]], **kwargs)

    monkeypatch.setattr(control_server.subprocess, "run", isolated_run)
    try:
        isolated_run([tmux, "new-session", "-d", "-s", "BriskFermi", "-e", "CLAUDECODE=1", "sleep 60"], check=True)
        assert control_server.tmux_session_exists(tmux, "BriskFermi") is True
        assert control_server.tmux_session_exists(tmux, "Brisk") is False
        assert tmux_session_gone(tmux, "Brisk") is True
        assert tmux_session_gone(tmux, "BriskFermi") is False
        isolated_run([tmux, "set-option", "-g", "exit-empty", "off"], check=True)
        isolated_run([tmux, "kill-session", "-t", "=BriskFermi"], check=True)
        assert tmux_session_gone(tmux, "BriskFermi") is True
        isolated_run([tmux, "kill-server"], check=True)
        assert tmux_session_gone(tmux, "BriskFermi") is None
    finally:
        isolated_run([tmux, "kill-server"], check=False, stderr=subprocess.DEVNULL)
        temporary.cleanup()
