"""Opening a folder from a pane under WSL (2026-10-02).

The seminar failure itself (Claude Code's shortened "…" path, answered "no
such path") is covered in test_shown_path.py. This file covers the WSL route
the same click then takes: a Windows program started from WSL talks back
through the socket in WSL_INTEROP, and a tmux server keeps the value from the
terminal that started it — once that terminal closes, every .exe fails with
an interop error on stderr. explorer.exe exits 1 even after opening a window,
so its exit status is ignored, and with it that failure: the cockpit said
"opened" while nothing opened.

Now the opener runs with a live WSL_INTEROP, an interop failure on stderr is
an error, and when Explorer cannot be reached the cockpit is handed the path,
spelled for Explorer, to open by hand.

Run from bridge/: ``python -m pytest tests/test_reveal_wsl.py``.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import orrery_backend as ob  # noqa: E402

WSL_KERNEL = "Linux version 5.15.167.4-microsoft-standard-WSL2"
EXPLORER = "/mnt/c/Windows/explorer.exe"
COCKPIT = Path(__file__).resolve().parents[1] / "cockpit.html"


def _wsl(monkeypatch, *, explorer=True, binfmt=("WSLInterop",), tmp=None):
    monkeypatch.setattr(ob, "_sys_platform", lambda: "linux")
    monkeypatch.setattr(ob, "_proc_version", lambda: WSL_KERNEL)
    monkeypatch.setattr(ob, "windows_exe", lambda name: EXPLORER if explorer else None)
    if binfmt is None:
        monkeypatch.setattr(ob, "BINFMT_DIR", "/nonexistent/binfmt_misc")
    else:
        directory = Path(tmp) / "binfmt_misc"
        directory.mkdir(exist_ok=True)
        for name in binfmt:
            (directory / name).write_text("enabled\n")
        monkeypatch.setattr(ob, "BINFMT_DIR", str(directory))


@pytest.fixture
def short_dir():
    # AF_UNIX paths are limited to ~104 bytes on macOS: keep them short.
    path = tempfile.mkdtemp(prefix="wi", dir="/tmp")
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _socket(path: str) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(path)
    return sock


# --- WSL_INTEROP --------------------------------------------------------------


def test_a_stale_wsl_interop_is_replaced_by_the_newest_live_socket(monkeypatch, short_dir):
    old = _socket(f"{short_dir}/100_interop")
    time.sleep(0.05)
    new = _socket(f"{short_dir}/200_interop")
    (Path(short_dir) / "300_interop").write_text("not a socket")
    try:
        monkeypatch.setattr(ob, "WSL_INTEROP_DIR", short_dir)
        monkeypatch.setenv("WSL_INTEROP", f"{short_dir}/42_interop")  # gone
        assert ob.wsl_interop_env()["WSL_INTEROP"] == f"{short_dir}/200_interop"
    finally:
        old.close()
        new.close()


def test_a_live_wsl_interop_is_kept(monkeypatch, short_dir):
    mine = _socket(f"{short_dir}/1_interop")
    time.sleep(0.05)
    newer = _socket(f"{short_dir}/2_interop")
    try:
        monkeypatch.setattr(ob, "WSL_INTEROP_DIR", short_dir)
        monkeypatch.setenv("WSL_INTEROP", f"{short_dir}/1_interop")
        assert ob.wsl_interop_env()["WSL_INTEROP"] == f"{short_dir}/1_interop"
    finally:
        mine.close()
        newer.close()


def test_with_no_socket_to_pick_the_environment_is_left_alone(monkeypatch, short_dir):
    monkeypatch.setattr(ob, "WSL_INTEROP_DIR", short_dir)
    monkeypatch.delenv("WSL_INTEROP", raising=False)
    assert "WSL_INTEROP" not in ob.wsl_interop_env()


def test_the_opener_runs_with_the_live_socket(monkeypatch, short_dir, tmp_path):
    live = _socket(f"{short_dir}/7_interop")
    out = tmp_path / "env.txt"
    try:
        _wsl(monkeypatch, tmp=tmp_path)
        monkeypatch.setattr(ob, "WSL_INTEROP_DIR", short_dir)
        monkeypatch.setenv("WSL_INTEROP", "/run/WSL/1_interop")
        ob.run_opener(["sh", "-c", f'printf %s "$WSL_INTEROP" > {out}'])
        assert out.read_text() == f"{short_dir}/7_interop"
    finally:
        live.close()


# --- the exit status explorer.exe does not give -------------------------------


def test_explorer_exiting_1_without_complaint_is_still_success(monkeypatch, tmp_path):
    _wsl(monkeypatch, tmp=tmp_path)
    ob.run_opener(["sh", "-c", "exit 1"], trust_exit_status=False)


@pytest.mark.parametrize("stderr", [
    "<3>WSL (12) ERROR: UtilConnectToInteropServer:300: connect failed 2",
    "<3>WSL (9) ERROR: UtilBindVsockAnyPort:307: socket failed 1",
    "sh: 1: explorer.exe: Exec format error",
])
def test_an_interop_failure_on_stderr_is_an_error(monkeypatch, tmp_path, stderr):
    _wsl(monkeypatch, tmp=tmp_path)
    with pytest.raises(OSError, match=re.escape(stderr[:20])):
        ob.run_opener(["sh", "-c", f"echo '{stderr}' >&2; exit 1"], trust_exit_status=False)


def test_mac_openers_do_not_read_interop_stderr(monkeypatch):
    monkeypatch.setattr(ob, "_sys_platform", lambda: "darwin")
    ob.run_opener(["sh", "-c", "echo 'interop' >&2; exit 1"], trust_exit_status=False)


# --- interop turned off -------------------------------------------------------


def test_interop_off_is_told_from_binfmt_misc(monkeypatch, tmp_path):
    _wsl(monkeypatch, binfmt=("status", "register"), tmp=tmp_path)
    assert "interop is turned off" in ob.wsl_interop_problem()


@pytest.mark.parametrize("entry", ["WSLInterop", "WSLInterop-late"])
def test_interop_on_is_told_from_binfmt_misc(monkeypatch, tmp_path, entry):
    _wsl(monkeypatch, binfmt=("status", entry), tmp=tmp_path)
    assert ob.wsl_interop_problem() is None


def test_an_unreadable_binfmt_misc_is_not_a_problem(monkeypatch, tmp_path):
    _wsl(monkeypatch, binfmt=None, tmp=tmp_path)
    assert ob.wsl_interop_problem() is None


# --- revealing, and the path shown when it cannot be --------------------------


def _windows_path(monkeypatch, spelled):
    monkeypatch.setattr(ob, "windows_path", lambda path: spelled)


def test_a_distro_folder_opens_by_its_wsl_localhost_path(monkeypatch, tmp_path):
    _wsl(monkeypatch, tmp=tmp_path)
    _windows_path(monkeypatch, r"\\wsl.localhost\OrreryTest\home\u\proj")
    calls = []
    monkeypatch.setattr(ob, "run_opener", lambda argv, **kw: calls.append(argv))
    assert ob.reveal_in_finder(tmp_path) == "dir"
    assert calls == [[EXPLORER, r"\\wsl.localhost\OrreryTest\home\u\proj"]]


def test_a_windows_drive_file_is_selected_by_its_drive_path(monkeypatch, tmp_path):
    target = tmp_path / "note.md"
    target.write_text("x")
    _wsl(monkeypatch, tmp=tmp_path)
    _windows_path(monkeypatch, r"C:\Users\u\note.md")
    calls = []
    monkeypatch.setattr(ob, "run_opener", lambda argv, **kw: calls.append(argv))
    assert ob.reveal_in_finder(target) == "file"
    assert calls == [[EXPLORER, "/select,", r"C:\Users\u\note.md"]]


def test_explorer_failing_to_start_hands_back_the_windows_path(monkeypatch, tmp_path):
    _wsl(monkeypatch, tmp=tmp_path)
    _windows_path(monkeypatch, r"\\wsl.localhost\OrreryTest\home\u\proj")

    def fail(argv, **kw):
        raise OSError("explorer.exe exited 1: UtilConnectToInteropServer")

    monkeypatch.setattr(ob, "run_opener", fail)
    with pytest.raises(ob.RevealUnavailable) as raised:
        ob.reveal_in_finder(tmp_path)
    assert raised.value.shown == r"\\wsl.localhost\OrreryTest\home\u\proj"
    assert "UtilConnectToInteropServer" in str(raised.value)


@pytest.mark.parametrize("setup,reason", [
    (dict(explorer=False), "explorer.exe is not reachable"),
    (dict(binfmt=("status",)), "interop is turned off"),
])
def test_no_route_to_explorer_hands_back_the_windows_path(monkeypatch, tmp_path, setup, reason):
    _wsl(monkeypatch, tmp=tmp_path, **setup)
    _windows_path(monkeypatch, r"C:\proj")
    monkeypatch.setattr(ob, "run_opener", lambda argv, **kw: pytest.fail("ran an opener"))
    with pytest.raises(ob.RevealUnavailable, match=reason) as raised:
        ob.reveal_in_finder(tmp_path)
    assert raised.value.shown == r"C:\proj"


def test_without_wslpath_the_linux_path_is_shown(monkeypatch, tmp_path):
    _wsl(monkeypatch, tmp=tmp_path)

    def fail(path):
        raise OSError("wslpath could not run: No such file")

    monkeypatch.setattr(ob, "windows_path", fail)
    with pytest.raises(ob.RevealUnavailable, match="wslpath could not run") as raised:
        ob.reveal_in_finder(tmp_path)
    assert raised.value.shown == str(tmp_path)


class _Request:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def test_the_endpoint_sends_the_path_to_show(monkeypatch, tmp_path):
    def unavailable(path):
        raise ob.RevealUnavailable("explorer.exe is not reachable", r"C:\proj")

    monkeypatch.setattr(ob, "reveal_in_finder", unavailable)
    response = asyncio.run(ob.reveal_path(_Request({"path": str(tmp_path)})))
    body = json.loads(response.body)
    assert response.status == 500
    assert body["ok"] is False
    assert body["show"] == r"C:\proj"
    assert "explorer.exe is not reachable" in body["error"]


def test_other_failures_send_no_path_to_show(monkeypatch, tmp_path):
    def broken(path):
        raise OSError("open exited 1: no window server")

    monkeypatch.setattr(ob, "reveal_in_finder", broken)
    body = json.loads(asyncio.run(ob.reveal_path(_Request({"path": str(tmp_path)}))).body)
    assert "show" not in body


# --- the cockpit --------------------------------------------------------------


def _cockpit_functions(*names: str) -> str:
    html = COCKPIT.read_text(encoding="utf-8")
    parts = []
    for name in names:
        start = html.index(f"function {name}(")
        if html[start - 6 : start] == "async ":
            start -= 6
        depth, i = 0, html.index("{", start)
        while True:
            depth += {"{": 1, "}": -1}.get(html[i], 0)
            i += 1
            if depth == 0:
                break
        parts.append(html[start:i])
    return "\n".join(parts)


NODE = shutil.which("node")


def _run_reveal(host: str, response: dict, status: int, clipboard: bool) -> dict:
    script = _cockpit_functions("fileManagerLabel", "showUnopenedPath", "revealLocalPath") + f"""
const hostPlatform={{host:{json.dumps(host)}}};
const toasts=[];let copied=null;
const toastEl={{classList:{{add:c=>toasts.at(-1).classes.push(c)}}}};
function showToast(message,isError=false,ms=4200){{toasts.push({{message,isError,ms,classes:[]}});}}
function appInvoke(){{return null;}}
Object.defineProperty(globalThis,'navigator',{{configurable:true,value:{json.dumps(clipboard)}?{{clipboard:{{writeText:async t=>{{copied=t;}}}}}}:{{}}}});
globalThis.fetch=async()=>({{ok:{json.dumps(status < 400)},status:{status},json:async()=>({json.dumps(response)})}});
revealLocalPath('/home/u/proj').then(ok=>console.log(JSON.stringify({{ok,toasts,copied}})));
"""
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.skipif(NODE is None, reason="no node")
def test_the_cockpit_shows_and_copies_the_path_to_open_by_hand():
    result = _run_reveal("wsl", {"ok": False, "error": "failed to open Explorer: x",
                                 "show": r"\\wsl.localhost\OrreryTest\home\u\proj"}, 500, True)
    (toast,) = result["toasts"]
    assert result["ok"] is False
    assert result["copied"] == r"\\wsl.localhost\OrreryTest\home\u\proj"
    assert toast["message"].startswith("EXPLORER FAILED · open it by hand (copied): \\\\wsl.localhost")
    assert toast["isError"] and toast["ms"] == 15000
    assert toast["classes"] == ["selectable"]


@pytest.mark.skipif(NODE is None, reason="no node")
def test_without_a_clipboard_the_path_is_still_shown():
    result = _run_reveal("wsl", {"ok": False, "error": "e", "show": r"C:\proj"}, 500, False)
    assert result["copied"] is None
    assert "open it by hand: C:\\proj" in result["toasts"][0]["message"]


@pytest.mark.skipif(NODE is None, reason="no node")
@pytest.mark.parametrize("host,label", [("wsl", "EXPLORER"), ("mac", "FINDER"), ("linux", "FILES")])
def test_the_toast_names_the_hosts_file_manager(host, label):
    result = _run_reveal(host, {"ok": True, "kind": "dir"}, 200, True)
    assert result["toasts"][0]["message"] == f"{label} · opened /home/u/proj"
    failed = _run_reveal(host, {"ok": False, "error": "failed to open Finder: boom"}, 500, True)
    assert failed["toasts"][0]["message"] == f"{label} FAILED · failed to open Finder: boom"
