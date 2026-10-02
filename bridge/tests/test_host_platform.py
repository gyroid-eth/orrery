"""Host detection and the Mac-only features' WSL routes (2026-09-28).

The detection is swapped out, not the machine: each test says which host it
is on, records the argv the opener would have run, and checks that WSL takes
the Windows route while Mac and plain Linux keep exactly the argv they had.

Run from bridge/: ``python -m pytest tests/test_host_platform.py``.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import orrery_backend as ob  # noqa: E402

WSL_KERNEL = "Linux version 5.15.167.4-microsoft-standard-WSL2 (gcc) #1 SMP"
PLAIN_KERNEL = "Linux version 6.8.0-45-generic (buildd@lcy02-amd64-075) #45-Ubuntu"


def _host(monkeypatch, kind, *, which=None, files=(), distro="Ubuntu"):
    """Pretend to be on ``kind`` ('mac' | 'wsl' | 'linux')."""
    platform = "darwin" if kind == "mac" else "linux"
    kernel = WSL_KERNEL if kind == "wsl" else PLAIN_KERNEL
    monkeypatch.setattr(ob, "_sys_platform", lambda: platform)
    monkeypatch.setattr(ob, "_proc_version", lambda: kernel)
    if distro:
        monkeypatch.setenv("WSL_DISTRO_NAME", distro)
    else:
        monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    table = dict(which or {})
    monkeypatch.setattr(ob.shutil, "which", lambda name: table.get(name))
    present = set(files)
    monkeypatch.setattr(ob.os.path, "isfile", lambda path: path in present)


@pytest.fixture
def opened(monkeypatch):
    """Every argv handed to run_opener, with its exit-status policy."""
    calls: list[tuple[list[str], bool]] = []

    def record(argv, *, trust_exit_status=True, confirm=False):
        calls.append((list(argv), trust_exit_status))

    monkeypatch.setattr(ob, "run_opener", record)
    return calls


# --- detection ----------------------------------------------------------------


def test_the_three_hosts_are_told_apart(monkeypatch):
    _host(monkeypatch, "mac")
    assert ob.host_kind() == "mac" and not ob.is_wsl()
    _host(monkeypatch, "linux")
    assert ob.host_kind() == "linux" and not ob.is_wsl()
    _host(monkeypatch, "wsl")
    assert ob.host_kind() == "wsl" and ob.is_wsl()


def test_a_darwin_kernel_string_never_reads_as_wsl(monkeypatch):
    _host(monkeypatch, "mac")
    monkeypatch.setattr(ob, "_proc_version", lambda: WSL_KERNEL)
    assert ob.host_kind() == "mac"


def test_wsl_without_windows_terminal_is_still_wsl_and_says_why(monkeypatch):
    _host(monkeypatch, "wsl", which={})
    info = ob.host_platform()
    assert info["host"] == "wsl"
    assert info["terminal"]["kind"] == "wt"
    assert info["terminal"]["available"] is False
    assert "wt.exe" in info["terminal"]["reason"]
    assert info["windows_interop"] is False
    assert info["file_paste"] is False


def test_wsl_without_a_distro_name_says_why(monkeypatch):
    _host(monkeypatch, "wsl", which={"wt.exe": "/mnt/c/wt.exe"}, distro="")
    info = ob.host_platform()
    assert info["terminal"]["available"] is False
    assert "WSL_DISTRO_NAME" in info["terminal"]["reason"]


def test_wsl_with_windows_terminal_and_interop(monkeypatch):
    _host(monkeypatch, "wsl", which={"wt.exe": "/mnt/c/wt.exe",
                                     "explorer.exe": "/mnt/c/Windows/explorer.exe"})
    info = ob.host_platform()
    assert info["terminal"] == {"kind": "wt", "label": "Windows Terminal",
                                "available": True, "reason": None}
    assert info["windows_interop"] is True
    assert info["distro"] == "Ubuntu"


@pytest.mark.parametrize("kind", ["mac", "linux"])
def test_mac_and_linux_report_what_they_always_had(monkeypatch, kind):
    _host(monkeypatch, kind, which={"wt.exe": "/x/wt.exe"})
    info = ob.host_platform()
    assert info["host"] == kind
    assert info["terminal"]["kind"] == "ghostty"
    assert info["terminal"]["label"] == "Ghostty"
    assert info["file_paste"] is (kind == "mac")


def test_windows_programs_are_found_off_path_too(monkeypatch):
    _host(monkeypatch, "wsl", which={}, files={"/mnt/c/Windows/explorer.exe"})
    assert ob.windows_exe("explorer.exe") == "/mnt/c/Windows/explorer.exe"
    assert ob.windows_exe("cmd.exe") is None


# --- opening a window on the session -------------------------------------------


def test_wsl_opens_a_windows_terminal_tab_back_into_the_distro(monkeypatch, opened):
    _host(monkeypatch, "wsl", which={"wt.exe": "/mnt/c/wt.exe"})
    ob.launch_terminal("/usr/bin/tmux", "orrery-AmberYukawa")
    assert opened == [([
        "wt.exe", "-w", "0", "new-tab", "--title", "orrery-AmberYukawa",
        "wsl.exe", "-d", "Ubuntu", "--exec", "/usr/bin/tmux", "attach", "-t",
        "orrery-AmberYukawa",
    ], True)]


def test_wsl_without_windows_terminal_fails_with_the_reason(monkeypatch, opened):
    _host(monkeypatch, "wsl", which={})
    with pytest.raises(OSError, match="wt.exe"):
        ob.launch_terminal("tmux", "s1")
    assert opened == []


@pytest.mark.parametrize("session", ["a;b", "a b", "a'b", 'a"b', "a$b"])
def test_session_names_wt_would_reinterpret_are_refused(monkeypatch, opened, session):
    _host(monkeypatch, "wsl", which={"wt.exe": "/mnt/c/wt.exe"})
    with pytest.raises(OSError, match="cannot be passed"):
        ob.launch_terminal("tmux", session)
    assert opened == []


@pytest.mark.parametrize("kind", ["mac", "linux"])
def test_mac_and_linux_still_launch_ghostty(monkeypatch, kind):
    _host(monkeypatch, kind)
    launched = []
    monkeypatch.setattr(ob.subprocess, "Popen", lambda argv, **kw: launched.append(argv))
    ob.launch_terminal("/opt/homebrew/bin/tmux", "s1")
    assert launched == [[ob.GHOSTTY_BIN, "--title=s1", "-e",
                         "/opt/homebrew/bin/tmux", "attach", "-t", "s1"]]


def test_the_endpoint_names_windows_terminal_in_its_error(monkeypatch):
    _host(monkeypatch, "wsl", which={})
    monkeypatch.setattr(ob, "tmux_session_exists", lambda tmux, s: True)
    monkeypatch.setattr(ob, "tmux_has_non_control_client", lambda tmux, s: False)

    class Request:
        app = {ob.TMUX_BIN_KEY: "tmux"}

        async def json(self):
            return {"session": "s1"}

    response = asyncio.run(ob.open_ghostty(Request()))
    assert response.status == 500
    assert "failed to open Windows Terminal" in response.text
    assert "wt.exe" in response.text


# --- URLs ----------------------------------------------------------------------


def test_wsl_prefers_wslview_for_urls(monkeypatch, opened):
    _host(monkeypatch, "wsl", which={"wslview": "/usr/bin/wslview",
                                     "explorer.exe": "/mnt/c/Windows/explorer.exe"})
    ob.launch_url("https://example.com/?a=1&b=2")
    assert opened == [(["wslview", "https://example.com/?a=1&b=2"], True)]


def test_wsl_falls_back_to_explorer_and_ignores_its_exit_status(monkeypatch, opened):
    _host(monkeypatch, "wsl", which={"explorer.exe": "/mnt/c/Windows/explorer.exe"})
    ob.launch_url("https://example.com/")
    assert opened == [(["/mnt/c/Windows/explorer.exe", "https://example.com/"], False)]


def test_wsl_with_no_route_to_windows_is_an_error(monkeypatch, opened):
    _host(monkeypatch, "wsl", which={})
    with pytest.raises(OSError, match="wslview"):
        ob.launch_url("https://example.com/")
    assert opened == []


@pytest.mark.parametrize("kind,argv0", [("mac", "open"), ("linux", "xdg-open")])
def test_mac_and_linux_urls_are_unchanged(monkeypatch, opened, kind, argv0):
    _host(monkeypatch, kind, which={"wslview": "/usr/bin/wslview"})
    ob.launch_url("https://example.com/")
    assert opened == [([argv0, "https://example.com/"], True)]


# --- paths ---------------------------------------------------------------------


def _wslpath(monkeypatch, result):
    seen = []

    def fake_run(argv, **kw):
        seen.append(argv)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(ob.subprocess, "run", fake_run)
    return seen


def test_wsl_opens_a_folder_in_explorer_by_its_windows_path(monkeypatch, opened, tmp_path):
    _host(monkeypatch, "wsl", which={"explorer.exe": "/mnt/c/Windows/explorer.exe"})
    seen = _wslpath(monkeypatch, subprocess.CompletedProcess(
        [], 0, stdout="\\\\wsl.localhost\\Ubuntu\\home\\u\\d\n", stderr=""))
    assert ob.reveal_in_finder(tmp_path) == "dir"
    assert seen == [["wslpath", "-w", str(tmp_path)]]
    assert opened == [(["/mnt/c/Windows/explorer.exe",
                        "\\\\wsl.localhost\\Ubuntu\\home\\u\\d"], False)]


def test_wsl_selects_a_file_in_explorer(monkeypatch, opened, tmp_path):
    target = tmp_path / "note.md"
    target.write_text("x")
    _host(monkeypatch, "wsl", which={"explorer.exe": "/mnt/c/Windows/explorer.exe"})
    _wslpath(monkeypatch, subprocess.CompletedProcess(
        [], 0, stdout="C:\\x\\note.md\n", stderr=""))
    assert ob.reveal_in_finder(target) == "file"
    assert opened == [(["/mnt/c/Windows/explorer.exe", "/select,", "C:\\x\\note.md"], False)]


def test_wsl_reports_a_failed_wslpath(monkeypatch, opened, tmp_path):
    _host(monkeypatch, "wsl", which={"explorer.exe": "/mnt/c/Windows/explorer.exe"})
    _wslpath(monkeypatch, subprocess.CompletedProcess([], 1, stdout="", stderr="bad path"))
    with pytest.raises(OSError, match="wslpath -w failed: bad path"):
        ob.reveal_in_finder(tmp_path)
    assert opened == []


def test_wsl_without_explorer_is_an_error(monkeypatch, opened, tmp_path):
    _host(monkeypatch, "wsl", which={})
    with pytest.raises(OSError, match="explorer.exe"):
        ob.reveal_in_finder(tmp_path)
    assert opened == []


def test_mac_paths_are_unchanged(monkeypatch, opened, tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("x")
    _host(monkeypatch, "mac")
    ob.reveal_in_finder(tmp_path)
    ob.reveal_in_finder(target)
    assert opened == [(["open", str(tmp_path)], True), (["open", "-R", str(target)], True)]


def test_linux_paths_are_unchanged(monkeypatch, opened, tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("x")
    _host(monkeypatch, "linux")
    ob.reveal_in_finder(tmp_path)
    ob.reveal_in_finder(target)
    assert opened == [(["xdg-open", str(tmp_path)], True), (["xdg-open", str(tmp_path)], True)]


# --- exit status ---------------------------------------------------------------


def test_an_untrusted_exit_status_is_not_an_error():
    ob.run_opener(["sh", "-c", "exit 1"], trust_exit_status=False)


def test_an_opener_that_cannot_start_is_an_error_even_when_untrusted():
    with pytest.raises(OSError):
        ob.run_opener(["/nonexistent/explorer.exe"], trust_exit_status=False)


# --- clipboard -----------------------------------------------------------------


def test_the_clipboard_reader_says_unsupported_on_wsl(monkeypatch):
    _host(monkeypatch, "wsl")

    async def never(*a, **kw):
        raise AssertionError("osascript must not run on WSL")

    monkeypatch.setattr(ob.asyncio, "create_subprocess_exec", never)
    response = asyncio.run(ob.serve_clipboard_files(None))
    assert '"clipboard_unsupported"' in response.text


# --- the Windows clipboard under WSL (2026-09-29) ---------------------------------
# powershell.exe and wslpath are fake programs in tmp_path: the reader really
# spawns them, so argv, encoding and exit status are exercised end to end.

FAKE_POWERSHELL = r"""#!/usr/bin/env python3
import base64, os, sys, time
args = sys.argv[1:]
script = base64.b64decode(args[args.index("-EncodedCommand") + 1]).decode("utf-16-le")
assert "FileDropList" in script and "UTF8Encoding" in script, script
assert "-NoProfile" in args and "-STA" in args, args
assert "ErrorActionPreference = 'Stop'" in script and "exit 1" in script, script
if os.environ.get("FAKE_PS_PIDFILE"):
    open(os.environ["FAKE_PS_PIDFILE"], "w").write(str(os.getpid()))
time.sleep(float(os.environ.get("FAKE_PS_SLEEP", "0")))
sys.stdout.buffer.write(open(os.environ["FAKE_PS_OUT"], "rb").read())
sys.stderr.write(os.environ.get("FAKE_PS_ERR", ""))
sys.exit(int(os.environ.get("FAKE_PS_RC", "0")))
"""

FAKE_WSLPATH = r"""#!/usr/bin/env python3
import sys
flag, path = sys.argv[1], sys.argv[2]
assert flag == "-u"
if len(path) < 3 or path[1:3] != ":\\":
    sys.stderr.write("wslpath: " + path + ": Invalid argument\n")
    sys.exit(1)
print("/mnt/" + path[0].lower() + "/" + path[3:].replace("\\", "/"))
"""


@pytest.fixture
def windows_clipboard(monkeypatch, tmp_path):
    """A WSL host whose powershell.exe answers with ``answer(bytes)``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("powershell.exe", FAKE_POWERSHELL), ("wslpath", FAKE_WSLPATH)):
        exe = bin_dir / name
        exe.write_text(body)
        exe.chmod(0o755)
    _host(monkeypatch, "wsl", which={"powershell.exe": str(bin_dir / "powershell.exe"),
                                     "wslpath": str(bin_dir / "wslpath")})
    images = tmp_path / "images"
    monkeypatch.setenv("ORRERY_CLIPBOARD_DIR", str(images))
    out = tmp_path / "ps-out"
    monkeypatch.setenv("FAKE_PS_OUT", str(out))

    def answer(stdout: bytes, **env):
        out.write_bytes(stdout)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        response = asyncio.run(ob.serve_clipboard_files(None))
        return json.loads(response.text)

    answer.images = images
    return answer


PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(64))


def test_wsl_reports_file_paste_when_powershell_and_wslpath_are_there(monkeypatch):
    _host(monkeypatch, "wsl", which={"powershell.exe": "/mnt/c/ps.exe", "wslpath": "/usr/bin/wslpath"})
    assert ob.host_platform()["file_paste"] is True
    _host(monkeypatch, "wsl", which={"wslpath": "/usr/bin/wslpath"})
    assert ob.host_platform()["file_paste"] is False
    _host(monkeypatch, "wsl", which={"wslpath": "/usr/bin/wslpath"},
          files={ob.POWERSHELL_FALLBACK})
    assert ob.host_platform()["file_paste"] is True


def test_wsl_without_powershell_says_unsupported_and_why(monkeypatch):
    _host(monkeypatch, "wsl", which={"wslpath": "/usr/bin/wslpath"})
    response = asyncio.run(ob.serve_clipboard_files(None))
    body = json.loads(response.text)
    assert body["error"] == "clipboard_unsupported"
    assert "powershell.exe" in body["detail"]


def test_windows_file_copies_become_wsl_paths(windows_clipboard):
    stdout = ("﻿S\t1\r\n"
              "F\tC:\\Users\\u\\Desktop\\実験 ノート.pdf\r\n"
              "F\tD:\\data\\a.csv\r\n").encode("utf-8")
    body = windows_clipboard(stdout)
    assert body == {"files": ["/mnt/c/Users/u/Desktop/実験 ノート.pdf", "/mnt/d/data/a.csv"]}


def test_a_windows_screenshot_is_saved_as_a_png_the_agent_can_open(windows_clipboard):
    encoded = base64.b64encode(PNG)
    body = windows_clipboard(b"S\t1\r\nI\t" + encoded + b"\r\n")
    assert body["image"] is True
    [saved] = body["files"]
    assert Path(saved).parent == windows_clipboard.images
    assert Path(saved).name.startswith("clipboard-") and saved.endswith(".png")
    assert Path(saved).read_bytes() == PNG
    assert (windows_clipboard.images.stat().st_mode & 0o777) == 0o700


def test_only_the_newest_pasted_images_are_kept(windows_clipboard, monkeypatch):
    monkeypatch.setattr(ob, "CLIPBOARD_IMAGE_KEEP", 2)
    windows_clipboard.images.mkdir()
    for age, name in enumerate(["clipboard-old1.png", "clipboard-old2.png"]):
        old = windows_clipboard.images / name
        old.write_bytes(b"x")
        os.utime(old, (1000 + age, 1000 + age))
    keep = windows_clipboard.images / "notes.txt"
    keep.write_text("not ours")
    windows_clipboard(b"S\t1\nI\t" + base64.b64encode(PNG) + b"\n")
    left = sorted(p.name for p in windows_clipboard.images.iterdir())
    assert "clipboard-old1.png" not in left and "clipboard-old2.png" in left
    assert "notes.txt" in left and len(left) == 3


def test_an_empty_windows_clipboard_is_empty_not_an_error(windows_clipboard):
    assert windows_clipboard(b"S\t2\r\n") == {"files": []}


def test_session_zero_is_a_backend_that_cannot_see_the_desktop(windows_clipboard):
    """A backend started over ssh runs PowerShell in session 0, whose
    clipboard is never the user's: that is not an empty clipboard."""
    assert windows_clipboard(b"S\t0\r\n") == {"files": [], "error": "clipboard_no_session"}


def test_a_failing_powershell_is_unreadable_with_its_stderr(windows_clipboard):
    body = windows_clipboard(b"", FAKE_PS_RC="1", FAKE_PS_ERR="Get-Clipboard: boom")
    assert body["error"] == "clipboard_unreadable"
    assert "boom" in body["detail"]


def test_a_hung_powershell_is_unavailable_and_is_killed(windows_clipboard, monkeypatch, tmp_path):
    """Review of 53a8642: wait_for alone left the hung child running, one
    more with every retry."""
    monkeypatch.setattr(ob, "WINDOWS_CLIPBOARD_TIMEOUT", 0.5)
    pidfile = tmp_path / "ps.pid"
    body = windows_clipboard(b"S\t1\n", FAKE_PS_SLEEP="30", FAKE_PS_PIDFILE=str(pidfile))
    assert body["error"] == "clipboard_unavailable"
    with pytest.raises(ProcessLookupError):      # killed and reaped, not a zombie
        os.kill(int(pidfile.read_text()), 0)


def test_windows_paths_wslpath_cannot_convert_are_reported(windows_clipboard):
    body = windows_clipboard(b"S\t1\r\nF\t\\\\server\\share\\x.pdf\r\n")
    assert body["files"] == [] and body["error"] == "clipboard_unreadable"
    assert "\\\\server\\share\\x.pdf" in body["detail"]
    mixed = windows_clipboard(b"S\t1\r\nF\t\\\\server\\x\r\nF\tC:\\a.txt\r\n")
    assert mixed == {"files": ["/mnt/c/a.txt"], "skipped": ["\\\\server\\x"]}


def test_an_existing_open_image_folder_is_tightened_and_images_are_private(
        windows_clipboard, monkeypatch):
    windows_clipboard.images.mkdir(mode=0o755)
    os.chmod(windows_clipboard.images, 0o755)
    old_umask = os.umask(0o022)
    try:
        [saved] = windows_clipboard(b"S\t1\nI\t" + base64.b64encode(PNG) + b"\n")["files"]
    finally:
        os.umask(old_umask)
    assert (windows_clipboard.images.stat().st_mode & 0o777) == 0o700
    assert (Path(saved).stat().st_mode & 0o777) == 0o600


def test_a_symlinked_image_folder_is_refused(windows_clipboard, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    windows_clipboard.images.symlink_to(elsewhere)
    body = windows_clipboard(b"S\t1\nI\t" + base64.b64encode(PNG) + b"\n")
    assert body["error"] == "clipboard_unreadable" and "symlink" in body["detail"]
    assert list(elsewhere.iterdir()) == []


def test_a_relative_image_folder_is_refused(windows_clipboard, monkeypatch):
    monkeypatch.setenv("ORRERY_CLIPBOARD_DIR", "relative/images")
    body = windows_clipboard(b"S\t1\nI\t" + base64.b64encode(PNG) + b"\n")
    assert body["error"] == "clipboard_unreadable" and "absolute" in body["detail"]


def test_the_mac_still_reads_the_pasteboard_with_osascript(monkeypatch):
    _host(monkeypatch, "mac", which={"powershell.exe": "/x/powershell.exe"})
    seen = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return b'{"changeCount": 7, "files": ["/Users/u/a.pdf"]}', b""

    async def fake_exec(*argv, **kw):
        seen.append(argv[0])
        return Proc()

    monkeypatch.setattr(ob.asyncio, "create_subprocess_exec", fake_exec)
    response = asyncio.run(ob.serve_clipboard_files(None))
    assert json.loads(response.text) == {"files": ["/Users/u/a.pdf"]}
    assert seen == ["osascript"]
