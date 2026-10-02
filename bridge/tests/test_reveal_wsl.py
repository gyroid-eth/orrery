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


def _socket(path: str, *, listening: bool = True) -> socket.socket:
    """A Unix socket at ``path``: accepting connections, or closed with its
    file left behind (what a gone WSL session leaves in /run/WSL)."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(path)
    if listening:
        sock.listen(1)
    else:
        sock.close()
    return sock


# --- WSL_INTEROP --------------------------------------------------------------


def test_a_gone_wsl_interop_is_replaced_by_the_newest_answering_socket(monkeypatch, short_dir):
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


def test_a_closed_socket_left_behind_is_not_kept(monkeypatch, short_dir):
    """Review of #10 (P2-4): the file of a closed socket stays; connecting to
    it is refused. Its existence is not life."""
    _socket(f"{short_dir}/1_interop", listening=False)
    live = _socket(f"{short_dir}/2_interop")
    try:
        os.utime(f"{short_dir}/2_interop", (1, 1))  # the older one answers
        monkeypatch.setattr(ob, "WSL_INTEROP_DIR", short_dir)
        monkeypatch.setenv("WSL_INTEROP", f"{short_dir}/1_interop")
        assert ob.wsl_interop_env()["WSL_INTEROP"] == f"{short_dir}/2_interop"
    finally:
        live.close()


def test_the_newest_closed_socket_is_passed_over(monkeypatch, short_dir):
    live = _socket(f"{short_dir}/1_interop")
    time.sleep(0.05)
    _socket(f"{short_dir}/2_interop", listening=False)
    try:
        monkeypatch.setattr(ob, "WSL_INTEROP_DIR", short_dir)
        monkeypatch.delenv("WSL_INTEROP", raising=False)
        assert ob.wsl_interop_env()["WSL_INTEROP"] == f"{short_dir}/1_interop"
    finally:
        live.close()


def test_a_symlinked_socket_is_not_trusted(monkeypatch, short_dir):
    live = _socket(f"{short_dir}/real")
    try:
        os.symlink(f"{short_dir}/real", f"{short_dir}/9_interop")
        monkeypatch.setattr(ob, "WSL_INTEROP_DIR", short_dir)
        monkeypatch.delenv("WSL_INTEROP", raising=False)
        assert "WSL_INTEROP" not in ob.wsl_interop_env()
    finally:
        live.close()


def test_with_nothing_answering_the_environment_is_left_alone(monkeypatch, short_dir):
    _socket(f"{short_dir}/1_interop", listening=False)
    monkeypatch.setattr(ob, "WSL_INTEROP_DIR", short_dir)
    monkeypatch.setenv("WSL_INTEROP", f"{short_dir}/1_interop")
    assert ob.wsl_interop_env()["WSL_INTEROP"] == f"{short_dir}/1_interop"
    monkeypatch.delenv("WSL_INTEROP")
    assert "WSL_INTEROP" not in ob.wsl_interop_env()


def _owned_by(monkeypatch, uid: int, me: int = 1000):
    """Report every file as owned by ``uid`` while this process runs as ``me``
    (WSL's init creates the interop socket as root; tests cannot chown)."""
    real = os.lstat

    def lstat(path, *args, **kwargs):
        info = real(path, *args, **kwargs)
        return os.stat_result((info.st_mode, info.st_ino, info.st_dev, info.st_nlink,
                               uid, info.st_gid, info.st_size,
                               int(info.st_atime), int(info.st_mtime), int(info.st_ctime)))

    monkeypatch.setattr(ob.os, "lstat", lstat)
    monkeypatch.setattr(ob.os, "getuid", lambda: me)


def test_a_root_owned_interop_socket_is_used(monkeypatch, short_dir):
    """Review of #10 (R2-P2-1): WSL's own socket belongs to root."""
    live = _socket(f"{short_dir}/5_interop")
    try:
        _owned_by(monkeypatch, 0)
        monkeypatch.setattr(ob, "WSL_INTEROP_DIR", short_dir)
        monkeypatch.setenv("WSL_INTEROP", f"{short_dir}/1_interop")  # gone
        assert ob.wsl_interop_env()["WSL_INTEROP"] == f"{short_dir}/5_interop"
        monkeypatch.setenv("WSL_INTEROP", f"{short_dir}/5_interop")
        assert ob.wsl_interop_env()["WSL_INTEROP"] == f"{short_dir}/5_interop"
    finally:
        live.close()


def test_another_users_interop_socket_is_not_used(monkeypatch, short_dir):
    live = _socket(f"{short_dir}/5_interop")
    try:
        _owned_by(monkeypatch, 4242)
        monkeypatch.setattr(ob, "WSL_INTEROP_DIR", short_dir)
        monkeypatch.delenv("WSL_INTEROP", raising=False)
        assert "WSL_INTEROP" not in ob.wsl_interop_env()
    finally:
        live.close()


def test_a_symlinked_current_value_is_not_kept(monkeypatch, short_dir):
    live = _socket(f"{short_dir}/real")
    other = _socket(f"{short_dir}/3_interop")
    try:
        os.symlink(f"{short_dir}/real", f"{short_dir}/link")
        monkeypatch.setattr(ob, "WSL_INTEROP_DIR", short_dir)
        monkeypatch.setenv("WSL_INTEROP", f"{short_dir}/link")
        assert ob.wsl_interop_env()["WSL_INTEROP"] == f"{short_dir}/3_interop"
    finally:
        live.close()
        other.close()


def test_an_answering_wsl_interop_is_kept(monkeypatch, short_dir):
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


def test_the_opener_runs_with_the_answering_socket(monkeypatch, short_dir, tmp_path):
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


def _slow(monkeypatch, script):
    monkeypatch.setattr(ob, "OPENER_WAIT_SECONDS", 0.5)
    return ["sh", "-c", script]


def test_an_interop_failure_before_the_wait_runs_out_is_an_error(monkeypatch, tmp_path):
    """Review of #10 (P2-5): it said so on stderr, then hung."""
    _wsl(monkeypatch, tmp=tmp_path)
    argv = _slow(monkeypatch, "echo 'UtilConnectToInteropServer:300: connect failed 2' >&2; exec sleep 3")
    with pytest.raises(OSError, match="did not start: .*UtilConnectToInteropServer"):
        ob.run_opener(argv, trust_exit_status=False)


def test_an_explorer_that_does_not_return_is_unconfirmed(monkeypatch, tmp_path):
    _wsl(monkeypatch, tmp=tmp_path)
    with pytest.raises(OSError, match="not confirmed"):
        ob.run_opener(_slow(monkeypatch, "exec sleep 3"), trust_exit_status=False, confirm=True)


def test_without_confirm_a_quiet_slow_opener_is_still_delivered(monkeypatch, tmp_path):
    _wsl(monkeypatch, tmp=tmp_path)
    ob.run_opener(_slow(monkeypatch, "exec sleep 3"), trust_exit_status=False)


def test_explorer_is_run_asking_for_confirmation(monkeypatch, tmp_path):
    _wsl(monkeypatch, tmp=tmp_path)
    monkeypatch.setattr(ob, "windows_path", lambda path: r"C:\proj")
    seen = []
    monkeypatch.setattr(ob, "run_opener", lambda argv, **kw: seen.append(kw))
    ob.reveal_in_finder(tmp_path)
    assert seen == [{"trust_exit_status": False, "confirm": True}]


# --- a Mac bundle is revealed, never launched (review of #10, P1) -------------


@pytest.fixture
def mac(monkeypatch):
    monkeypatch.setattr(ob, "_sys_platform", lambda: "darwin")
    calls = []
    monkeypatch.setattr(ob, "run_opener", lambda argv, **kw: calls.append(argv))
    return calls


@pytest.mark.parametrize("make", ["app", "odd-bundle", "link-to-plain", "link-to-app", "app-inside-link"])
def test_a_bundle_or_a_link_is_revealed_not_opened(mac, tmp_path, make):
    app = tmp_path / "Report.app"
    (app / "Contents").mkdir(parents=True)
    plain = tmp_path / "plain"
    plain.mkdir()
    odd = tmp_path / "Odd Name"
    (odd / "Contents").mkdir(parents=True)
    (odd / "Contents" / "Info.plist").write_text("x")
    target = {
        "app": app,
        "odd-bundle": odd,
        "link-to-plain": tmp_path / "l1",
        "link-to-app": tmp_path / "l2",
        "app-inside-link": tmp_path / "l3" / "Report.app",
    }[make]
    (tmp_path / "l1").symlink_to(plain)
    (tmp_path / "l2").symlink_to(app)
    (tmp_path / "l3").symlink_to(tmp_path)
    assert ob.reveal_in_finder(target) == "bundle"
    assert mac == [["open", "-R", str(target)]]


def test_a_plain_folder_still_opens(mac, tmp_path):
    assert ob.reveal_in_finder(tmp_path) == "dir"
    assert mac == [["open", str(tmp_path)]]


def test_a_shortened_name_reaching_a_bundle_only_reveals_it(mac, tmp_path):
    """The review's route: "Report….app" resolved to Report-current.app."""
    (tmp_path / "Report-current.app" / "Contents").mkdir(parents=True)
    body = json.loads(asyncio.run(ob.reveal_path(_Request({"path": f"{tmp_path}/Report….app"}))).body)
    assert body["kind"] == "bundle"
    assert mac == [["open", "-R", str(tmp_path / "Report-current.app")]]


@pytest.mark.parametrize("kind,name", [("mac", "Finder"), ("wsl", "Explorer"), ("linux", "the file manager")])
def test_the_error_names_the_hosts_file_manager(monkeypatch, tmp_path, kind, name):
    monkeypatch.setattr(ob, "host_kind", lambda: kind)

    def broken(path):
        raise OSError("boom")

    monkeypatch.setattr(ob, "reveal_in_finder", broken)
    body = json.loads(asyncio.run(ob.reveal_path(_Request({"path": str(tmp_path)}))).body)
    assert body["error"] == f"failed to open {name}: boom"


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
        depth, i = 0, html.index("){", start) + 1  # the body, not a default parameter
        while True:
            depth += {"{": 1, "}": -1}.get(html[i], 0)
            i += 1
            if depth == 0:
                break
        parts.append(html[start:i])
    return "\n".join(parts)


NODE = shutil.which("node")


def _run_reveal(host: str, response: dict, status: int, clipboard) -> dict:
    """revealLocalPath against a canned backend answer. ``clipboard``: True
    (writes), "reject", "pending" (never answers) or False (none). The state
    is read 50 ms after the answer, whether or not the clipboard has."""
    clip = {True: "async t=>{copied=t;}", "reject": "async t=>{throw new Error('denied');}",
            "pending": "t=>new Promise(()=>{})"}.get(clipboard)
    script = _cockpit_functions("fileManagerLabel", "showUnopenedPath", "showCandidates",
                                "revealLocalPath") + f"""
const hostPlatform={{host:{json.dumps(host)}}};
const toasts=[];let copied=null;
const toastEl={{textContent:'',classList:{{add:c=>toasts.at(-1).classes.push(c)}}}};
function showToast(message,isError=false,ms=4200){{toastEl.textContent=message;toasts.push({{message,isError,ms,classes:[]}});}}
function appInvoke(){{return null;}}
Object.defineProperty(globalThis,'navigator',{{configurable:true,value:{json.dumps(clip is not None)}?{{clipboard:{{writeText:{clip or 'null'}}}}}:{{}}}});
globalThis.fetch=async()=>({{ok:{json.dumps(status < 400)},status:{status},json:async()=>({json.dumps(response)})}});
revealLocalPath('/home/u/proj');
setTimeout(()=>{{console.log(JSON.stringify({{toasts,copied,shown:toastEl.textContent}}));process.exit(0);}},50);
"""
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


SHOW = r"\\wsl.localhost\OrreryTest\home\u\proj"


@pytest.mark.skipif(NODE is None, reason="no node")
def test_the_cockpit_shows_and_copies_the_path_to_open_by_hand():
    result = _run_reveal("wsl", {"ok": False, "error": "failed to open Explorer: x",
                                 "show": SHOW}, 500, True)
    (toast,) = result["toasts"]
    assert result["copied"] == SHOW
    assert result["shown"].startswith("EXPLORER FAILED · open it by hand (copied): \\\\wsl.localhost")
    assert toast["isError"] and toast["ms"] == 15000
    assert toast["classes"] == ["selectable"]


@pytest.mark.skipif(NODE is None, reason="no node")
@pytest.mark.parametrize("clipboard", ["pending", "reject", False])
def test_the_path_is_shown_whatever_the_clipboard_does(clipboard):
    """Review of #10 (P2-6): a clipboard waiting for permission held back the
    failure and the path."""
    result = _run_reveal("wsl", {"ok": False, "error": "e", "show": r"C:\proj"}, 500, clipboard)
    assert result["copied"] is None
    assert result["shown"] == "EXPLORER FAILED · open it by hand: C:\\proj — e"


@pytest.mark.skipif(NODE is None, reason="no node")
def test_several_matches_are_listed_not_opened():
    result = _run_reveal("mac", {"ok": False, "error": "2 paths match; not opened",
                                 "candidates": ["/a/x/note.md", "/a/y/note.md"]}, 409, True)
    (toast,) = result["toasts"]
    assert toast["message"] == "FINDER · 2 paths match; not opened: /a/x/note.md  ·  /a/y/note.md"
    assert toast["classes"] == ["selectable"]


@pytest.mark.skipif(NODE is None, reason="no node")
@pytest.mark.parametrize("host,label", [("wsl", "EXPLORER"), ("mac", "FINDER"), ("linux", "FILES")])
def test_the_toast_names_the_hosts_file_manager(host, label):
    result = _run_reveal(host, {"ok": True, "kind": "dir"}, 200, True)
    assert result["toasts"][0]["message"] == f"{label} · opened /home/u/proj"
    bundle = _run_reveal(host, {"ok": True, "kind": "bundle", "path": "/a/R.app"}, 200, True)
    assert bundle["toasts"][0]["message"] == f"{label} · revealed /a/R.app"
