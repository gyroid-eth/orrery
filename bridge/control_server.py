#!/usr/bin/env python3
"""Multi-pane tmux control-mode bridge for the ORRERY vertical slice."""

from __future__ import annotations

import argparse
import asyncio
import codecs
import contextlib
import hashlib
import json
import math
import os
import pty
import re
import signal
import subprocess
import sys
import tempfile
import time
import tty
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pyte
import websockets

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8780
DEFAULT_TEST_SESSION = "orrery-control-test"
RECORDER_HISTORY_LINES = 2000
SNAPSHOT_HISTORY_LINES = 1000
HISTORY_SCHEMA = 1
HISTORY_FLUSH_SECONDS = 30
HISTORY_RETENTION_SECONDS = 7 * 24 * 60 * 60
ORPHAN_HISTORY_RETENTION_SECONDS = 24 * 60 * 60
DEFAULT_HISTORY_DIR = "~/.orrery/history"
PANE_FORMAT = (
    "#{pane_id}\t#{window_id}\t#{session_id}\t#{window_index}\t"
    "#{pane_index}\t#{pane_width}\t#{pane_height}\t#{pane_active}\t"
    "#{window_name}\t#{pane_current_command}"
)
CLIENT_SIZE_FORMAT = (
    "#{client_control_mode}\t#{client_width}\t#{client_height}\t"
    "#{client_activity}"
)
# capture-pane returns text only, so a replay alone leaves a viewer that
# attached after the app turned on mouse tracking without it. The first viewer
# usually gets the mode anyway, from the redraw its attach resize causes; a
# second viewer (another tab, the app, a pane window, a reload) attaches at the
# size already claimed, nothing redraws, and the wheel never reaches the app:
# Claude Code (tui: fullscreen) and Codex track the mouse on the alternate
# screen, and neither could be scrolled back (2026-10-02 report).
# The replay therefore ends with the modes tmux reports as on. Only "on": the
# replay never turns off a mode the viewer's live output turned on. It can
# still turn back on a mode that live output switched off between the query
# and the replay's arrival, until the app sends that mode again.
PANE_MODE_SEQUENCES = {
    "mouse_standard_flag": "\x1b[?1000h",
    "mouse_button_flag": "\x1b[?1002h",
    "mouse_all_flag": "\x1b[?1003h",
    "mouse_sgr_flag": "\x1b[?1006h",
    "mouse_utf8_flag": "\x1b[?1005h",
    "keypad_cursor_flag": "\x1b[?1h",
    "keypad_flag": "\x1b=",
}
PANE_STATE_FORMAT = "\t".join(
    ["#{cursor_x}", "#{cursor_y}"] + [f"#{{{flag}}}" for flag in PANE_MODE_SEQUENCES]
)


def pane_mode_sequences(fields: list[str]) -> str:
    """The on-modes in a PANE_STATE_FORMAT reply (after the cursor). A flag an
    older tmux does not know formats as empty and counts as off."""
    return "".join(
        sequence
        for sequence, value in zip(PANE_MODE_SEQUENCES.values(), fields[2:])
        if value == "1"
    )


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    lines: list[str]


@dataclass(frozen=True)
class PaneInfo:
    pane_id: str
    window_id: str
    session_id: str
    window_index: str
    pane_index: str
    width: int
    height: int
    active: bool
    window_name: str
    current_command: str

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["paneId"] = payload.pop("pane_id")
        payload["windowId"] = payload.pop("window_id")
        payload["sessionId"] = payload.pop("session_id")
        payload["windowIndex"] = payload.pop("window_index")
        payload["paneIndex"] = payload.pop("pane_index")
        payload["currentCommand"] = payload.pop("current_command")
        payload["windowName"] = payload.pop("window_name")
        return payload


@dataclass(frozen=True)
class ControlConfig:
    host: str
    port: int
    session: str
    tmux_bin: str
    session_created: int | None = None
    history_dir: Path | None = None


@dataclass
class PaneRecorder:
    screen: pyte.HistoryScreen
    stream: pyte.Stream
    feed_count: int = 0
    flushed_feed_count: int = 0

    @classmethod
    def create(cls, columns: int, lines: int) -> PaneRecorder:
        screen = pyte.HistoryScreen(
            max(1, columns),
            max(1, lines),
            history=RECORDER_HISTORY_LINES,
        )
        return cls(screen=screen, stream=pyte.Stream(screen))

    def resize(self, columns: int, lines: int) -> None:
        self.screen.resize(lines=max(1, lines), columns=max(1, columns))

    def feed(self, data: str) -> None:
        self.stream.feed(data)
        self.feed_count += 1

    def history_lines(self, limit: int = SNAPSHOT_HISTORY_LINES) -> list[str]:
        rows = list(self.screen.history.top)[-limit:]
        return [
            "".join(
                row[column].data for column in range(self.screen.columns)
            ).rstrip()
            for row in rows
        ]


def history_directory() -> Path:
    return Path(
        os.path.expanduser(
            os.environ.get("ORRERY_HISTORY_DIR", DEFAULT_HISTORY_DIR)
        )
    )


def history_file_path(history_dir: Path, session: str, pane_id: str) -> Path:
    digest = hashlib.sha256(
        f"{session}\0{pane_id}".encode()
    ).hexdigest()[:24]
    return history_dir / f"{digest}.json"


def log_history_error(action: str, path: Path, exc: BaseException) -> None:
    print(
        f"ORRERY history {action} failed for {path.name!r}: "
        f"{type(exc).__name__}: {exc}",
        file=sys.stderr,
        flush=True,
    )


def write_history_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(file_descriptor)
        with contextlib.suppress(OSError):
            os.unlink(temporary_name)
        raise


def prune_history_files(
    history_dir: Path,
    live_sessions: set[str] | None,
    *,
    now: float | None = None,
) -> None:
    """Apply startup retention without allowing filesystem failures to escape."""
    current_time = time.time() if now is None else now
    try:
        history_dir.mkdir(parents=True, exist_ok=True)
        paths = list(history_dir.glob("*.json"))
    except Exception as exc:
        log_history_error("retention scan", history_dir, exc)
        return

    for path in paths:
        try:
            modified_ts = path.stat().st_mtime
        except OSError as exc:
            log_history_error("retention stat", path, exc)
            continue

        payload: dict[str, Any] | None = None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            if current_time - modified_ts <= HISTORY_RETENTION_SECONDS:
                log_history_error("retention read", path, exc)

        timestamps = [modified_ts]
        if payload is not None:
            saved_ts = payload.get("saved_ts")
            if isinstance(saved_ts, (int, float)) and not isinstance(saved_ts, bool):
                try:
                    saved_ts_float = float(saved_ts)
                except (OverflowError, ValueError):
                    pass
                else:
                    if math.isfinite(saved_ts_float):
                        timestamps.append(saved_ts_float)
        age = current_time - min(timestamps)

        session = payload.get("session") if payload is not None else None
        expired = age > HISTORY_RETENTION_SECONDS
        orphaned = (
            live_sessions is not None
            and isinstance(session, str)
            and session not in live_sessions
            and age > ORPHAN_HISTORY_RETENTION_SECONDS
        )
        if not (expired or orphaned):
            continue
        try:
            path.unlink()
        except OSError as exc:
            log_history_error("retention delete", path, exc)


def tmux_session_exists(tmux_bin: str, session: str) -> bool:
    result = subprocess.run(
        [tmux_bin, "has-session", "-t", session],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def ensure_tmux_session(tmux_bin: str, session: str, *, create: bool) -> None:
    if tmux_session_exists(tmux_bin, session):
        return

    if not create:
        raise SystemExit(
            f"tmux session {session!r} does not exist; create it or omit --session "
            f"to let this bridge create {DEFAULT_TEST_SESSION!r}."
        )

    # -e CLAUDECODE=1: guard the test session's interactive shell against a
    # destructive zsh/bash exit hook (e.g. a ~/.zshrc zshexit that kills tmux
    # sessions). Without it, exiting this throwaway session can cascade-kill the
    # whole tmux server. Requires tmux >= 3.0.
    subprocess.run(
        [tmux_bin, "new-session", "-d", "-s", session, "-e", "CLAUDECODE=1"], check=True
    )
    subprocess.run([tmux_bin, "split-window", "-h", "-t", f"{session}:0"], check=True)


def quote_tmux_arg(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./=@+-]+", value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


def make_tmux_command(args: list[str]) -> str:
    return " ".join(quote_tmux_arg(arg) for arg in args)


def unescape_tmux_output(value: str | bytes) -> bytes:
    raw = value.encode("utf-8", errors="replace") if isinstance(value, str) else value
    decoded = bytearray()
    index = 0
    while index < len(raw):
        byte = raw[index]
        if (
            byte == ord("\\")
            and index + 3 < len(raw)
            and all(ord("0") <= item <= ord("7") for item in raw[index + 1 : index + 4])
        ):
            decoded.append(int(raw[index + 1 : index + 4], 8))
            index += 4
            continue
        decoded.append(byte)
        index += 1
    return bytes(decoded)


def decode_tmux_output(value: str | bytes) -> str:
    """One-shot decode. For live pane streams use the per-pane incremental
    decoder instead: a multibyte character can straddle two %output events,
    and a per-event decode turns the boundary into U+FFFD mojibake."""
    return unescape_tmux_output(value).decode("utf-8", errors="replace")


def parse_pane_line(line: str) -> PaneInfo | None:
    fields = line.split("\t")
    if len(fields) != 10:
        return None

    pane_id, window_id, session_id, window_index, pane_index = fields[:5]
    width, height, active, window_name, current_command = fields[5:]
    try:
        width_int = int(width)
        height_int = int(height)
    except ValueError:
        return None

    return PaneInfo(
        pane_id=pane_id,
        window_id=window_id,
        session_id=session_id,
        window_index=window_index,
        pane_index=pane_index,
        width=width_int,
        height=height_int,
        active=active == "1",
        window_name=window_name,
        current_command=current_command,
    )


class TmuxControlBridge:
    def __init__(self, config: ControlConfig) -> None:
        self.config = config
        self.master_fd: int | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self.panes: dict[str, PaneInfo] = {}
        self.clients: set[Any] = set()
        self.client_locks: dict[Any, asyncio.Lock] = {}

        self._buffer = b""
        # pane id -> incremental UTF-8 decoder: multibyte characters can
        # straddle %output events, so per-event decoding mangles boundaries.
        self._pane_decoders: dict[str, codecs.IncrementalDecoder] = {}
        self._pane_recorders: dict[str, PaneRecorder] = {}
        self._restored_history: dict[str, list[str]] = {}
        self._persisted_history: dict[str, list[str]] = {}
        self._resync_tasks: dict[str, asyncio.Task[None]] = {}
        self._current_block: list[str] | None = None
        self._pending_blocks: deque[asyncio.Future[CommandResult] | None] = deque()
        self._write_lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()
        self._history_flush_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._history_flush_task: asyncio.Task[None] | None = None
        self._history_dir = config.history_dir or history_directory()
        self._session_created = config.session_created
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        master_fd, slave_fd = pty.openpty()
        tty.setraw(slave_fd)
        self.master_fd = master_fd
        os.set_blocking(master_fd, False)

        try:
            self.process = subprocess.Popen(
                [self.config.tmux_bin, "-CC", "attach", "-t", self.config.session],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                start_new_session=True,
            )
        finally:
            os.close(slave_fd)

        self._loop.add_reader(master_fd, self._read_ready)
        await asyncio.sleep(0.2)
        await self._resolve_session_created(refresh=True)
        await self.refresh_panes(send_captures=False)
        self._history_flush_task = asyncio.create_task(self._history_flush_loop())

    async def stop(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()

        history_flush_task = self._history_flush_task
        self._history_flush_task = None
        if history_flush_task is not None:
            history_flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await history_flush_task

        for task in self._resync_tasks.values():
            task.cancel()
        self._resync_tasks.clear()

        if self.master_fd is not None and self._loop is not None:
            with contextlib.suppress(Exception):
                self._loop.remove_reader(self.master_fd)
            with contextlib.suppress(OSError):
                os.close(self.master_fd)
            self.master_fd = None

        if self.process is not None and self.process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                await asyncio.to_thread(self.process.wait, 2)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                await asyncio.to_thread(self.process.wait)

        await self.flush_history()

    async def _resolve_session_created(self, *, refresh: bool = False) -> None:
        if self._session_created is not None and not refresh:
            return
        try:
            result = await self.send_command(
                [
                    "display-message",
                    "-p",
                    "-t",
                    self.config.session,
                    "#{session_created}",
                ],
                wait=True,
            )
            if result is not None and result.ok and result.lines:
                self._session_created = int(result.lines[-1])
        except (OSError, RuntimeError, ValueError, asyncio.TimeoutError) as exc:
            if self._session_created is None:
                print(
                    f"ORRERY history session timestamp unavailable for "
                    f"{self.config.session!r}: {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

    async def _history_flush_loop(self) -> None:
        while True:
            await asyncio.sleep(HISTORY_FLUSH_SECONDS)
            try:
                await self.flush_history()
            except Exception as exc:
                log_history_error("periodic flush", self._history_dir, exc)

    async def flush_history(self) -> None:
        async with self._history_flush_lock:
            if self._session_created is None and self.master_fd is not None:
                await self._resolve_session_created()
            for pane_id, recorder in list(self._pane_recorders.items()):
                await self._flush_pane_history(pane_id, recorder)

    async def _flush_pane_history(
        self,
        pane_id: str,
        recorder: PaneRecorder,
    ) -> None:
        feed_count = recorder.feed_count
        if feed_count == recorder.flushed_feed_count:
            return

        rendered = (
            self._restored_history.get(pane_id, [])
            + recorder.history_lines(RECORDER_HISTORY_LINES)
        )[-RECORDER_HISTORY_LINES:]
        if rendered == self._persisted_history.get(pane_id, []):
            recorder.flushed_feed_count = feed_count
            return
        if self._session_created is None:
            return

        path = history_file_path(
            self._history_dir,
            self.config.session,
            pane_id,
        )
        payload = {
            "schema": HISTORY_SCHEMA,
            "session": self.config.session,
            "pane_id": pane_id,
            "session_created": self._session_created,
            "saved_ts": time.time(),
            "lines": rendered,
        }
        try:
            await asyncio.to_thread(write_history_file, path, payload)
        except Exception as exc:
            log_history_error("flush", path, exc)
            return
        self._persisted_history[pane_id] = rendered
        recorder.flushed_feed_count = feed_count

    async def _create_pane_recorder(self, pane: PaneInfo) -> PaneRecorder:
        recorder = PaneRecorder.create(pane.width, pane.height)
        restored = await asyncio.to_thread(
            self._read_restored_history,
            pane.pane_id,
        )
        self._restored_history[pane.pane_id] = restored
        self._persisted_history[pane.pane_id] = list(restored)
        return recorder

    def _read_restored_history(self, pane_id: str) -> list[str]:
        if self._session_created is None:
            return []
        path = history_file_path(
            self._history_dir,
            self.config.session,
            pane_id,
        )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            log_history_error("restore", path, exc)
            return []

        valid_identity = (
            isinstance(payload, dict)
            and payload.get("schema") == HISTORY_SCHEMA
            and payload.get("session") == self.config.session
            and payload.get("pane_id") == pane_id
        )
        if not valid_identity:
            print(
                f"ORRERY history restore ignored invalid record {path.name!r}",
                file=sys.stderr,
                flush=True,
            )
            return []

        stored_session_created = payload.get("session_created")
        if (
            not isinstance(stored_session_created, int)
            or isinstance(stored_session_created, bool)
            or stored_session_created != self._session_created
        ):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                log_history_error("discard mismatched session", path, exc)
            return []

        lines = payload.get("lines")
        if not isinstance(lines, list) or not all(
            isinstance(line, str) for line in lines
        ):
            print(
                f"ORRERY history restore ignored invalid lines in {path.name!r}",
                file=sys.stderr,
                flush=True,
            )
            return []
        return lines[-RECORDER_HISTORY_LINES:]

    def _read_ready(self) -> None:
        if self.master_fd is None:
            return

        while True:
            try:
                chunk = os.read(self.master_fd, 8192)
            except BlockingIOError:
                return
            except OSError:
                self._schedule_broadcast({"type": "status", "state": "closed"})
                return

            if not chunk:
                self._schedule_broadcast({"type": "status", "state": "closed"})
                return

            self._buffer += chunk
            while b"\n" in self._buffer:
                raw_line, self._buffer = self._buffer.split(b"\n", 1)
                self._handle_line(raw_line.rstrip(b"\r"))

    def _handle_line(self, line: str | bytes) -> None:
        raw_line = line.encode("utf-8") if isinstance(line, str) else line
        raw_line = raw_line.replace(b"\x1bP1000p", b"").replace(b"\x1b\\", b"")

        # tmux guarantees notifications never occur inside a command output
        # block. Preserve arbitrary command output (including lines which look
        # like notifications) before dispatching raw pane output below.
        if self._current_block is not None:
            text = raw_line.decode("utf-8", "replace")
            if text.startswith("%end") or text.startswith("%error"):
                block = self._current_block
                self._current_block = None
                pending = self._pending_blocks.popleft() if self._pending_blocks else None
                if pending is not None and not pending.done():
                    pending.set_result(
                        CommandResult(ok=text.startswith("%end"), lines=block)
                    )
                return
            self._current_block.append(text)
            return

        # tmux may pass UTF-8 bytes >= 0x80 through %output verbatim. A pane
        # write can end inside a code point, so decoding the whole control line
        # here would turn each partial byte into U+FFFD before the per-pane
        # incremental decoder sees it.
        if raw_line.startswith(b"%output "):
            self._handle_output(raw_line)
            return

        if raw_line.startswith(b"%extended-output "):
            self._handle_extended_output(raw_line)
            return

        line = raw_line.decode("utf-8", "replace")

        if not line:
            return

        if line.startswith("%begin"):
            self._current_block = []
            return

        if line.startswith("%exit"):
            self._schedule_broadcast({"type": "status", "state": "closed"})
            return

        if line.startswith(
            (
                "%layout-change",
                "%session-changed",
                "%session-window-changed",
                "%sessions-changed",
                "%window-add",
                "%window-close",
                "%window-pane-changed",
                "%window-renamed",
                "%unlinked-window-add",
                "%unlinked-window-close",
                "%unlinked-window-renamed",
            )
        ):
            self.request_refresh()

    def _decode_pane_output(self, pane_id: str, escaped: str | bytes) -> str:
        decoder = self._pane_decoders.get(pane_id)
        if decoder is None:
            decoder = codecs.getincrementaldecoder("utf-8")("replace")
            self._pane_decoders[pane_id] = decoder
        return decoder.decode(unescape_tmux_output(escaped))

    def _handle_output(self, line: str | bytes) -> None:
        raw_line = line.encode("utf-8") if isinstance(line, str) else line
        parts = raw_line.split(b" ", 2)
        if len(parts) != 3:
            return
        _, raw_pane_id, escaped = parts
        pane_id = raw_pane_id.decode("ascii", "replace")
        data = self._decode_pane_output(pane_id, escaped)
        if data:
            self._record_and_broadcast(pane_id, data)

    def _handle_extended_output(self, line: str | bytes) -> None:
        raw_line = line.encode("utf-8") if isinstance(line, str) else line
        parts = raw_line.split(b" ", 2)
        if len(parts) != 3:
            return
        _, raw_pane_id, remainder = parts
        _metadata, separator, escaped = remainder.partition(b" : ")
        if not separator:
            return
        pane_id = raw_pane_id.decode("ascii", "replace")
        data = self._decode_pane_output(pane_id, escaped)
        if data:
            self._record_and_broadcast(pane_id, data)

    def _record_and_broadcast(self, pane_id: str, data: str) -> None:
        recorder = self._pane_recorders.get(pane_id)
        if recorder is not None:
            recorder.feed(data)
        self._schedule_broadcast(
            {"type": "output", "paneId": pane_id, "data": data}
        )

    async def send_command(
        self,
        args: list[str],
        *,
        wait: bool = True,
        timeout: float = 5.0,
    ) -> CommandResult | None:
        if self.master_fd is None:
            raise RuntimeError("tmux control bridge is not running")

        future: asyncio.Future[CommandResult] | None = None
        if wait:
            future = asyncio.get_running_loop().create_future()

        command = make_tmux_command(args) + "\n"
        async with self._write_lock:
            self._pending_blocks.append(future)
            await self._write_master(command.encode("utf-8"))

        if future is None:
            return None
        return await asyncio.wait_for(future, timeout=timeout)

    async def _write_master(self, payload: bytes) -> None:
        """Write to the control-client pty with backpressure.

        The master fd is non-blocking; a burst of commands (e.g. a long
        composer prompt chunked into many send-keys) can overrun the ~1 KB
        pty input buffer. A bare os.write silently truncates the command
        stream there (keystrokes vanish mid-paste) or raises
        BlockingIOError — loop until every byte is delivered.
        """
        if self.master_fd is None:
            raise RuntimeError("tmux control bridge is not running")
        view = memoryview(payload)
        while view:
            try:
                written = os.write(self.master_fd, view)
            except BlockingIOError:
                await asyncio.sleep(0.004)
                continue
            view = view[written:]

    def request_refresh(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(self._refresh_after_delay())

    async def _refresh_after_delay(self) -> None:
        await asyncio.sleep(0.08)
        await self.refresh_panes(send_captures=True)

    async def refresh_panes(self, *, send_captures: bool) -> None:
        async with self._refresh_lock:
            result = await self.send_command(
                [
                    "list-panes",
                    "-s",
                    "-t",
                    self.config.session,
                    "-F",
                    PANE_FORMAT,
                ],
                wait=True,
            )
            if result is None or not result.ok:
                await self.broadcast(
                    {"type": "error", "message": "Failed to enumerate tmux panes."}
                )
                return

            next_panes: dict[str, PaneInfo] = {}
            for line in result.lines:
                pane = parse_pane_line(line)
                if pane is not None:
                    next_panes[pane.pane_id] = pane

            previous_panes = self.panes
            old_ids = set(previous_panes)
            new_ids = set(next_panes)
            removed_ids = old_ids - new_ids
            added_ids = new_ids - old_ids
            retained_ids = old_ids & new_ids
            self.panes = next_panes

            for pane_id in sorted(removed_ids):
                self._pane_decoders.pop(pane_id, None)
                recorder = self._pane_recorders.pop(pane_id, None)
                if recorder is not None:
                    async with self._history_flush_lock:
                        await self._flush_pane_history(pane_id, recorder)
                self._restored_history.pop(pane_id, None)
                self._persisted_history.pop(pane_id, None)
                await self.broadcast({"type": "close", "paneId": pane_id})

            for pane_id in sorted(retained_ids):
                pane = self.panes[pane_id]
                previous = previous_panes[pane_id]
                recorder = self._pane_recorders.get(pane_id)
                if recorder is None:
                    recorder = await self._create_pane_recorder(pane)
                    self._pane_recorders[pane_id] = recorder
                await self.broadcast({"type": "update", "pane": pane.to_json()})
                if (pane.width, pane.height) != (previous.width, previous.height):
                    recorder.resize(pane.width, pane.height)
                    self._schedule_pane_resync(pane_id)

            for pane_id in sorted(added_ids):
                pane = self.panes[pane_id]
                self._pane_recorders[pane_id] = await self._create_pane_recorder(
                    pane
                )
                await self.send_command(["refresh-client", "-A", f"{pane_id}:on"], wait=False)
                await self.broadcast({"type": "add", "pane": pane.to_json()})
                if send_captures:
                    capture = await self.capture_pane(pane_id)
                    if capture:
                        # Same replay payload as the attach snapshot, so it
                        # carries the same marker: the client must land the new
                        # pane on the bottom instead of wherever the write
                        # happened to be interrupted.
                        await self.broadcast(
                            {
                                "type": "output",
                                "paneId": pane_id,
                                "data": capture,
                                "snapshot": True,
                            }
                        )

    async def capture_pane(self, pane_id: str) -> str:
        result = await self.send_command(
            ["capture-pane", "-p", "-t", pane_id],
            wait=True,
            timeout=5.0,
        )
        if result is None or not result.ok:
            return ""
        pane = self.panes.get(pane_id)
        if pane is None:
            text = "\r\n".join(result.lines).rstrip()
            return f"{text}\r\n" if text else ""
        # Replay = recorder history + the authoritative tmux SCREEN padded to exactly
        # pane.height rows, then walk the cursor back with relative moves
        # (anchored on the last written row, so history stacked above does
        # not disturb it — unlike absolute CUP, which was tried and is
        # fragile because tmux trims trailing blank rows from captures).
        lines = list(result.lines[: pane.height])
        recorder = self._pane_recorders.get(pane_id)
        live_history = recorder.history_lines() if recorder is not None else []
        history = (
            self._restored_history.get(pane_id, []) + live_history
        )[-SNAPSHOT_HISTORY_LINES:]
        state = await self.send_command(
            ["display-message", "-p", "-t", pane_id, PANE_STATE_FORMAT],
            wait=True,
            timeout=5.0,
        )
        fields = (
            state.lines[0].split("\t")
            if state is not None and state.ok and state.lines
            else []
        )
        modes = pane_mode_sequences(fields)
        if not any(line.strip() for line in history + lines):
            # A TUI that turned its modes on and has not drawn yet.
            return modes
        lines += [""] * (pane.height - len(lines))
        text = "\r\n".join(history + lines) + modes
        suffix = ""
        if len(fields) >= 2:
            try:
                cx, cy = int(fields[0]), int(fields[1])
                up = max(0, (pane.height - 1) - cy)
                suffix = (f"\x1b[{up}A" if up else "") + "\r"
                if cx > 0:
                    suffix += f"\x1b[{cx}C"
            except ValueError:
                pass
        return text + suffix

    async def send_snapshot(self, websocket: Any) -> None:
        await self.send_json(
            websocket,
            {
                "type": "reset",
                "session": self.config.session,
                "panes": [pane.to_json() for pane in sorted(self.panes.values(), key=pane_key)],
            },
        )
        for pane in sorted(self.panes.values(), key=pane_key):
            capture = await self.capture_pane(pane.pane_id)
            if capture:
                # "snapshot" marks the attach replay. The client suspends scroll
                # preservation for exactly this write and lands the pane on the
                # bottom afterwards; a live broadcast can interleave ahead of it
                # (the peer joins self.clients before this runs), so the client
                # cannot infer "first output == snapshot".
                await self.send_json(
                    websocket,
                    {
                        "type": "output",
                        "paneId": pane.pane_id,
                        "data": capture,
                        "snapshot": True,
                    },
                )

    async def handle_client_message(self, payload: dict[str, Any]) -> None:
        message_type = payload.get("type")
        pane_id = payload.get("paneId")
        if not isinstance(pane_id, str) and message_type in {
            "input",
            "resize",
            "release",
            "split",
            "close",
        }:
            return

        if message_type == "input":
            data = payload.get("data")
            if isinstance(data, str):
                await self.send_input(
                    pane_id, data, binary=payload.get("binary") is True
                )
            return

        if message_type == "resize":
            pane = self.panes.get(pane_id)
            cols = payload.get("cols")
            rows = payload.get("rows")
            if pane is None or not isinstance(cols, int) or not isinstance(rows, int):
                return
            size = f"{pane.window_id}:{max(1, cols)}x{max(1, rows)}"
            await self.send_command(["refresh-client", "-C", size], wait=False)
            # The attach snapshot is captured at the pane's PREVIOUS width
            # (e.g. the Ghostty client's), so every hard-wrapped line lands
            # misaligned in the xterm viewport until the next full redraw.
            # After the size settles, re-capture and let the client replace
            # its buffer ({"type":"refresh-pane"}).
            self._schedule_pane_resync(pane_id)
            return

        if message_type == "release":
            pane = self.panes.get(pane_id)
            if pane is None:
                return
            interactive_size = await self._latest_interactive_window_size()
            await self.send_command(
                ["set-option", "-w", "-t", pane.window_id, "-u", "window-size"],
                wait=False,
            )
            if interactive_size is not None:
                width, height = interactive_size
                await self.send_command(
                    [
                        "refresh-client",
                        "-C",
                        f"{pane.window_id}:{width}x{height}",
                    ],
                    wait=False,
                )
            self._schedule_pane_resync(pane_id)
            return

        if message_type == "split":
            direction = payload.get("direction")
            flag = "-v" if direction == "vertical" else "-h"
            await self.send_command(["split-window", flag, "-t", pane_id], wait=False)
            self.request_refresh()
            return

        if message_type == "close":
            if len(self.panes) <= 1:
                return
            await self.send_command(["kill-pane", "-t", pane_id], wait=False)
            self.request_refresh()
            return

        if message_type == "refresh":
            await self.refresh_panes(send_captures=True)

    async def _latest_interactive_window_size(self) -> tuple[int, int] | None:
        result = await self.send_command(
            [
                "list-clients",
                "-t",
                self.config.session,
                "-F",
                CLIENT_SIZE_FORMAT,
            ],
            wait=True,
        )
        if result is None or not result.ok:
            return None

        candidates: list[tuple[int, int, int]] = []
        for line in result.lines:
            fields = line.split("\t")
            if len(fields) != 4 or fields[0] != "0":
                continue
            try:
                width = int(fields[1])
                height = int(fields[2])
                activity = int(fields[3])
            except ValueError:
                continue
            candidates.append((activity, width, height))
        if not candidates:
            return None

        status_lines = 1
        status_result = await self.send_command(
            ["show-options", "-v", "-t", self.config.session, "status"],
            wait=True,
        )
        if status_result is not None and status_result.ok and status_result.lines:
            status_value = status_result.lines[-1].strip()
            if status_value == "off":
                status_lines = 0
            elif status_value != "on":
                with contextlib.suppress(ValueError):
                    status_lines = max(0, int(status_value))

        _, width, height = max(candidates)
        return max(1, width), max(1, height - status_lines)

    def _schedule_pane_resync(self, pane_id: str) -> None:
        prior = self._resync_tasks.get(pane_id)
        if prior is not None and not prior.done():
            prior.cancel()
        self._resync_tasks[pane_id] = asyncio.create_task(
            self._resync_pane(pane_id)
        )

    async def _resync_pane(self, pane_id: str) -> None:
        # Debounce: resizes arrive in bursts (drag, fit, claim); resync once
        # after they settle so xterm never replays a mid-reflow grid.
        await asyncio.sleep(0.6)
        if pane_id not in self.panes:
            return
        capture = await self.capture_pane_screen_addressed(pane_id)
        if capture:
            await self.broadcast(
                {"type": "refresh-pane", "paneId": pane_id, "data": capture}
            )

    async def capture_pane_screen_addressed(self, pane_id: str) -> str:
        """Screen replacement for resyncs: every row is written with absolute
        row addressing + erase-line, so applying it never scrolls and never
        touches the client's scrollback (term.reset() on resync was wiping
        the whole history on every claim/divider/size change — 2026-07-30
        user report: 'sometimes I can't scroll up')."""
        result = await self.send_command(
            ["capture-pane", "-p", "-t", pane_id],
            wait=True,
            timeout=5.0,
        )
        pane = self.panes.get(pane_id)
        if result is None or not result.ok or pane is None:
            return ""
        lines = list(result.lines[: pane.height])
        lines += [""] * (pane.height - len(lines))
        parts = [
            f"\x1b[{row + 1};1H\x1b[2K{line}"
            for row, line in enumerate(lines)
        ]
        cursor = await self.send_command(
            [
                "display-message", "-p", "-t", pane_id,
                "#{cursor_x}\t#{cursor_y}",
            ],
            wait=True,
            timeout=5.0,
        )
        cx = cy = 0
        if cursor is not None and cursor.ok and cursor.lines:
            fields = cursor.lines[0].split("\t")
            if len(fields) == 2:
                with contextlib.suppress(ValueError):
                    cx, cy = int(fields[0]), int(fields[1])
        parts.append(f"\x1b[{cy + 1};{cx + 1}H")
        return "".join(parts)

    async def send_input(
        self, pane_id: str, data: str, *, binary: bool = False
    ) -> None:
        # xterm hands classic (non-SGR) mouse reports to onBinary as a string
        # of byte values 0-255; UTF-8 would turn a coordinate byte >= 0x80
        # into two bytes and the app would misread the report.
        if binary:
            try:
                raw = data.encode("latin-1")
            except UnicodeEncodeError:
                return
        else:
            raw = data.encode("utf-8", errors="replace")
        for start in range(0, len(raw), 64):
            chunk = raw[start : start + 64]
            await self.send_command(
                ["send-keys", "-t", pane_id, "-H", *[f"{byte:02x}" for byte in chunk]],
                wait=False,
            )

    async def broadcast(self, payload: dict[str, Any]) -> None:
        stale_clients = []
        for websocket in list(self.clients):
            try:
                await self.send_json(websocket, payload)
            except Exception:
                stale_clients.append(websocket)
        for websocket in stale_clients:
            self.clients.discard(websocket)
            self.client_locks.pop(websocket, None)

    def _schedule_broadcast(self, payload: dict[str, Any]) -> None:
        asyncio.create_task(self.broadcast(payload))

    async def send_json(self, websocket: Any, payload: dict[str, Any]) -> None:
        lock = self.client_locks.setdefault(websocket, asyncio.Lock())
        async with lock:
            await websocket.send(json.dumps(payload, ensure_ascii=False))


def pane_key(pane: PaneInfo) -> tuple[int, int, str]:
    try:
        window_index = int(pane.window_index)
    except ValueError:
        window_index = 0
    try:
        pane_index = int(pane.pane_index)
    except ValueError:
        pane_index = 0
    return (window_index, pane_index, pane.pane_id)


async def handle_websocket(websocket: Any, bridge: TmuxControlBridge) -> None:
    bridge.clients.add(websocket)
    bridge.client_locks.setdefault(websocket, asyncio.Lock())
    await bridge.send_snapshot(websocket)

    try:
        async for raw_message in websocket:
            if not isinstance(raw_message, str):
                continue
            try:
                payload = json.loads(raw_message)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                await bridge.handle_client_message(payload)
    finally:
        bridge.clients.discard(websocket)
        bridge.client_locks.pop(websocket, None)


async def run_server(config: ControlConfig) -> None:
    bridge = TmuxControlBridge(config)
    await bridge.start()

    async def handler(websocket: Any, _path: str | None = None) -> None:
        await handle_websocket(websocket, bridge)

    try:
        async with websockets.serve(handler, config.host, config.port):
            print(
                f"ORRERY control bridge listening on ws://{config.host}:{config.port}/ws "
                f"for tmux session {config.session!r}",
                flush=True,
            )
            await asyncio.Future()
    finally:
        await bridge.stop()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.environ.get("HOST", DEFAULT_HOST))
    parser.add_argument("--port", default=int(os.environ.get("PORT", DEFAULT_PORT)), type=int)
    parser.add_argument(
        "--session",
        default=os.environ.get("SESSION") or os.environ.get("ORRERY_TMUX_SESSION"),
        help="tmux session to attach; defaults to a self-created two-pane test session",
    )
    parser.add_argument("--tmux-bin", default=os.environ.get("TMUX_BIN", "tmux"))
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.host != DEFAULT_HOST:
        raise SystemExit("This control-mode bridge is restricted to 127.0.0.1.")

    session = args.session or DEFAULT_TEST_SESSION
    ensure_tmux_session(args.tmux_bin, session, create=args.session is None)
    config = ControlConfig(
        host=args.host,
        port=args.port,
        session=session,
        tmux_bin=args.tmux_bin,
    )
    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
