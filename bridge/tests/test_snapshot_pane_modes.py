"""A replay must leave a later viewer in the pane's mouse mode (2026-10-02).

capture-pane returns text only. A viewer learns the pane's modes from live
output; the first one usually gets them from the redraw its attach resize
causes, but a second viewer (another tab, the app, a pane window, a reload)
attaches at the size already claimed and nothing redraws. Claude Code (tui:
fullscreen) tracks the mouse, so in that viewer the wheel never reached it and
its transcript could not be scrolled back. Measured on 2026-10-02 against a
real Claude Code 2.1.287 in a throwaway tmux: the second viewer had
mouseTrackingMode "none" before this change and "any" after it, and the wheel
scrolled the transcript.

The replay text is left exactly as it was; the on-modes tmux reports are added
at its end. An earlier, larger version also rebuilt the screen (alternate
buffer, reset, held delivery) and each review round found a new race in it;
these tests pin that the text and delivery stay as before.

Run from bridge/: ``python -m pytest tests/test_snapshot_pane_modes.py``.
"""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from control_server import (  # noqa: E402
    PANE_MODE_SEQUENCES,
    CommandResult,
    ControlConfig,
    PaneInfo,
    TmuxControlBridge,
)

PANE = PaneInfo(
    pane_id="%1",
    window_id="@1",
    session_id="$1",
    window_index="0",
    pane_index="0",
    width=20,
    height=3,
    active=True,
    window_name="claude",
    current_command="claude",
)


class FakeBridge(TmuxControlBridge):
    def __init__(self, screen: list[str], state: str | None) -> None:
        super().__init__(
            ControlConfig(
                host="127.0.0.1", port=0, session="orrery-test", tmux_bin="tmux"
            )
        )
        self.panes = {PANE.pane_id: PANE}
        self._screen = screen
        self._state = state
        self.sent: list[list[str]] = []

    async def send_command(self, args: list[str], **_: Any) -> CommandResult | None:
        if args[0] == "capture-pane":
            return CommandResult(ok=True, lines=list(self._screen))
        if args[0] == "display-message":
            if self._state is None:
                return CommandResult(ok=False, lines=[])
            return CommandResult(ok=True, lines=[self._state])
        if args[0] == "send-keys":
            self.sent.append(args)
            return None
        raise AssertionError(f"unexpected tmux command {args}")


def _state(cursor: tuple[int, int], **flags: str) -> str:
    values = [str(cursor[0]), str(cursor[1])]
    values += [flags.get(flag, "0") for flag in PANE_MODE_SEQUENCES]
    return "\t".join(values)


def _replay(screen: list[str], state: str | None, history: list[str] = ()) -> str:
    bridge = FakeBridge(screen, state)
    if history:
        bridge._restored_history[PANE.pane_id] = list(history)
    return asyncio.run(bridge.capture_pane(PANE.pane_id))


FULLSCREEN = dict(mouse_all_flag="1", mouse_sgr_flag="1")


def test_a_mouse_tracking_tui_gets_its_mouse_mode_at_the_end():
    replay = _replay(["transcript", "", "> "], _state((2, 2), **FULLSCREEN))
    assert replay == "transcript\r\n\r\n> \x1b[?1003h\x1b[?1006h\r\x1b[2C"


def test_the_text_is_what_it_was_before():
    """Same text, same cursor walk-back as before this change: only the
    on-modes are inserted ahead of the walk-back."""
    plain = _replay(["$ ls", "a b", "$ "], _state((2, 2)), history=["older"])
    moded = _replay(["$ ls", "a b", "$ "], _state((2, 2), **FULLSCREEN),
                    history=["older"])
    assert plain == "older\r\n$ ls\r\na b\r\n$ \r\x1b[2C"
    assert moded.replace("\x1b[?1003h\x1b[?1006h", "") == plain


def test_nothing_is_reset_cleared_or_switched():
    replay = _replay(["x", "", ""], _state((0, 0), **FULLSCREEN,
                     keypad_cursor_flag="1", keypad_flag="1"))
    for sequence in ("\x1bc", "\x1b[?1049", "\x1b[2J", "\x1b[3J", "2004"):
        assert sequence not in replay
    # Nothing is turned off: a newer live state is never undone.
    assert not re.search(r"\x1b\[\?\d+l|\x1b>", replay)


def test_keypad_modes_are_carried():
    replay = _replay(["x", "", ""], _state((0, 0), keypad_cursor_flag="1",
                     keypad_flag="1"))
    assert "\x1b[?1h\x1b=" in replay


def test_a_classic_mouse_mode_is_carried():
    replay = _replay(["x", "", ""], _state((0, 0), mouse_standard_flag="1"))
    assert "\x1b[?1000h" in replay
    assert "\x1b[?1006h" not in replay


def test_a_blank_screen_still_gets_its_modes():
    """A TUI that turned its modes on and has not drawn yet."""
    assert _replay(["", "", ""], _state((0, 0), **FULLSCREEN)) == (
        "\x1b[?1003h\x1b[?1006h"
    )


def test_a_blank_plain_screen_is_still_not_replayed():
    assert _replay(["", "", ""], _state((0, 0))) == ""


def test_a_tmux_without_the_flags_replays_as_before():
    # Formats an older tmux does not know expand to "" and count as off.
    replay = _replay(["$ ", "", ""], "1\t0" + "\t" * len(PANE_MODE_SEQUENCES))
    assert replay == "$ \r\n\r\n\x1b[2A\r\x1b[1C"


def test_a_failed_state_query_replays_the_text():
    assert _replay(["$ ", "", ""], None) == "$ \r\n\r\n"


# --- classic mouse ----------------------------------------------------------

# A classic wheel-up report at column 193: Cb = 32+64, Cx = 32+193 (0xE1).
CLASSIC_WHEEL = "\x1b[M`\xe1!"
BRACKETED_PASTE = "\x1b[200~first\rsecond\x1b[201~"


def _sent_bytes(bridge: FakeBridge) -> bytes:
    return bytes(
        int(value, 16) for args in bridge.sent for value in args[args.index("-H") + 1 :]
    )


def _input(data: str, **extra: Any) -> FakeBridge:
    bridge = FakeBridge([], None)
    asyncio.run(
        bridge.handle_client_message(
            {"type": "input", "paneId": PANE.pane_id, "data": data, **extra}
        )
    )
    return bridge


def test_binary_input_reaches_tmux_byte_for_byte():
    assert _sent_bytes(_input(CLASSIC_WHEEL, binary=True)) == b"\x1b[M`\xe1!"


def test_text_input_is_still_utf8():
    assert _sent_bytes(_input("é")) == "é".encode()
    assert _sent_bytes(_input(BRACKETED_PASTE)) == BRACKETED_PASTE.encode()


def test_binary_input_that_is_not_bytes_is_dropped():
    assert _input("あ", binary=True).sent == []


def test_the_cockpit_forwards_binary_reports_as_binary():
    html = (Path(__file__).resolve().parent.parent / "cockpit.html").read_text(
        encoding="utf-8"
    )
    assert re.search(
        r"term\.onBinary\(data=>\{if\(activeId===meta\.paneId\)"
        r"send\(\{type:\"input\",paneId:meta\.paneId,data,binary:true\}\);\}\);",
        html,
    )


@pytest.mark.skipif(shutil.which("tmux") is None, reason="no tmux")
@pytest.mark.parametrize(
    "data,binary",
    [(CLASSIC_WHEEL, True), (BRACKETED_PASTE, False)],
    ids=["classic-wheel", "bracketed-paste"],
)
def test_input_reaches_the_programs_stdin(tmp_path, data, binary):
    """send-keys -H with the bytes the bridge builds, on a private tmux server:
    the program reads exactly what xterm produced."""
    expected = data.encode("latin-1" if binary else "utf-8")
    out = tmp_path / "stdin.bin"
    reader = (
        "import os,tty,time;tty.setraw(0);b=b'';t=time.time()\n"
        f"while len(b)<{len(expected)} and time.time()-t<5: b+=os.read(0,64)\n"
        f"open({str(out)!r},'wb').write(b)"
    )
    tmux = ["tmux", "-L", f"orrery-modes-{os.getpid()}", "-f", "/dev/null"]
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    subprocess.run(
        tmux + ["new-session", "-d", "-s", "modes", sys.executable, "-c", reader],
        check=True,
        env=env,
    )
    try:
        time.sleep(0.5)
        bridge = FakeBridge([], None)
        asyncio.run(bridge.send_input(PANE.pane_id, data, binary=binary))
        for args in bridge.sent:
            subprocess.run(
                tmux + [args[0], "-t", "modes", *args[3:]], check=True, env=env
            )
        deadline = time.time() + 5
        while time.time() < deadline and not (out.exists() and out.stat().st_size):
            time.sleep(0.1)
        assert out.read_bytes() == expected
    finally:
        subprocess.run(tmux + ["kill-server"], env=env, capture_output=True)
