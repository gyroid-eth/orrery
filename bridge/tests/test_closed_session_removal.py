"""Closed-session status is conservative and exact.

Run from bridge/: ``python -m pytest tests/test_closed_session_removal.py``.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
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
    bridge._schedule_broadcast = events.append  # type: ignore[method-assign]
    monkeypatch.setattr(control_server, "tmux_session_gone", lambda *_: answer)

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

    assert events == [
        {"type": "status", "state": "closed", "session": "Brisk", **expected}
    ]


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
