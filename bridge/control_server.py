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
import uuid
import weakref
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pyte
import websockets

from runtime_target import LegacyTargetBoundary, FreshPaneBoundary, FreshEffectProof, TargetRefused, admit_creation, admit_command, require_target, tmux_argv, tmux_env

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
    "#{window_name}\t#{pane_current_command}\t#{alternate_on}\t"
    "#{mouse_standard_flag}\t#{mouse_button_flag}\t#{mouse_all_flag}"
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
    overflow: bool = False


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
    alternate_on: bool | None = None
    mouse_tracking: bool | None = None

    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["paneId"] = payload.pop("pane_id")
        payload["windowId"] = payload.pop("window_id")
        payload["sessionId"] = payload.pop("session_id")
        payload["windowIndex"] = payload.pop("window_index")
        payload["paneIndex"] = payload.pop("pane_index")
        payload["currentCommand"] = payload.pop("current_command")
        payload["alternateOn"] = payload.pop("alternate_on")
        payload["mouseTracking"] = payload.pop("mouse_tracking")
        payload["windowName"] = payload.pop("window_name")
        return payload


@dataclass(frozen=True)
class ControlConfig:
    host: str
    port: int
    session: str
    tmux_bin: str | LegacyTargetBoundary
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
    if isinstance(tmux_bin,FreshPaneBoundary):
        try:tmux_bin.admit('attach',session=session);return True
        except TargetRefused:return False
    result = subprocess.run(
        tmux_argv(tmux_bin, "has-session", "-t", "=" + session),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        **tmux_env(tmux_bin),
    )
    return result.returncode == 0


def tmux_session_gone(tmux_bin: str, session: str) -> bool | None:
    """Return True only when tmux can confirm that *session* is absent.

    ``has-session`` uses prefix matching unless its target starts with ``=``.
    A missing server and a missing session both return 1, so confirm that the
    server can list sessions before calling the session gone.  ``None`` keeps
    the cockpit's closed group when tmux itself cannot answer reliably.
    """
    if isinstance(tmux_bin,FreshPaneBoundary):return None
    try:
        result = subprocess.run(
            tmux_argv(tmux_bin, "has-session", "-t", f"={session}"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=1,
            **tmux_env(tmux_bin),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 0:
        return False
    if result.returncode != 1:
        return None

    try:
        roster = subprocess.run(
            tmux_argv(tmux_bin, "list-sessions", "-F", "#{session_name}"),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=1,
            **tmux_env(tmux_bin),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if roster.returncode == 0:
        return session not in roster.stdout.splitlines()
    if roster.returncode != 1:
        return None

    # With ``exit-empty off`` a live tmux server may have zero sessions, and
    # list-sessions then returns the same 1 as a missing server.  A global
    # option query needs no session and distinguishes those two cases.
    try:
        server_probe = subprocess.run(
            tmux_argv(tmux_bin, "show-options", "-gqv", "exit-empty"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=1,
            **tmux_env(tmux_bin),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return True if server_probe.returncode == 0 else None


def ensure_tmux_session(tmux_bin: str, session: str, *, create: bool) -> None:
    if tmux_session_exists(tmux_bin, session):
        return

    if not create:
        raise SystemExit(
            f"tmux session {session!r} does not exist; create it or omit --session "
            f"to let this bridge create {DEFAULT_TEST_SESSION!r}."
        )

    admit_creation(tmux_bin)

    # -e CLAUDECODE=1: guard the test session's interactive shell against a
    # destructive zsh/bash exit hook (e.g. a ~/.zshrc zshexit that kills tmux
    # sessions). Without it, exiting this throwaway session can cascade-kill the
    # whole tmux server. Requires tmux >= 3.0.
    subprocess.run(
        tmux_argv(tmux_bin, "new-session", "-d", "-s", session, "-e", "CLAUDECODE=1"), check=True, **tmux_env(tmux_bin)
    )
    require_target(tmux_bin, "split", session=session)
    subprocess.run(tmux_argv(tmux_bin, "split-window", "-h", "-t", f"={session}:0"), check=True, **tmux_env(tmux_bin))


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
    if len(fields) not in (10, 14):
        return None

    pane_id, window_id, session_id, window_index, pane_index = fields[:5]
    width, height, active, window_name, current_command = fields[5:10]
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
        alternate_on=(fields[10] == "1" if len(fields) == 14 and fields[10] in ("0", "1") else None),
        mouse_tracking=(any(flag == "1" for flag in fields[11:14])
                        if len(fields) == 14 and all(flag in ("0", "1") for flag in fields[11:14]) else None),
    )


class TmuxControlBridge:
    def __init__(self, config: ControlConfig) -> None:
        self.config = config
        self._incarnation = uuid.uuid4().hex
        self.master_fd: int | None = None
        self.process: subprocess.Popen[bytes] | None = None
        self._lifetime_fd: int | None = None
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
        # Only the opt-in finite mobile capture uses these limits. Ordinary
        # recorder/PC commands retain their existing output behavior.
        self._bounded_blocks: dict[asyncio.Future, int] = {}
        self._block_limit: int | None = None
        self._block_bytes = 0
        self._block_overflow = False
        self._block_boundary: bytes | None = None
        self._discard_block_line = False
        self._write_lock = asyncio.Lock()
        self._refresh_lock = asyncio.Lock()
        self._history_flush_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._history_flush_task: asyncio.Task[None] | None = None
        self._closed_task: asyncio.Task[None] | None = None
        self._closed = False
        self._history_dir = config.history_dir or history_directory()
        if isinstance(config.tmux_bin,FreshPaneBoundary):self._history_dir=self._history_dir/config.tmux_bin.history_key
        self._session_created = config.session_created
        self._loop: asyncio.AbstractEventLoop | None = None
        self._fresh_output=[]
        self._fresh_output_bytes=0
        self._fresh_output_task=None
        self._fresh_peer_proofs={}
        self._fresh_peer_locks=weakref.WeakKeyDictionary()
        self._fresh_peer_generations=weakref.WeakKeyDictionary()
        self._fresh_recorder_proof=(FreshEffectProof(config.tmux_bin,'capture',membership=self._fresh_control_membership) if isinstance(config.tmux_bin,FreshPaneBoundary) else None)
        self._fresh_sink_tasks=set();self._fresh_recorder_tasks=set();self._fresh_sink_locks={};self._fresh_sink_bytes={};self._fresh_sink_counts={}

    def _schedule_closed(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.master_fd is not None and self._loop is not None:
            self._loop.remove_reader(self.master_fd)
        self._closed_task = asyncio.create_task(self._broadcast_closed())

    async def _broadcast_closed(self) -> None:
        payload: dict[str, Any] = {
            "type": "status",
            "state": "closed",
            "session": self.config.session,
            "incarnation": self._incarnation,
        }
        session_gone = await asyncio.to_thread(
            tmux_session_gone,
            self.config.tmux_bin,
            self.config.session,
        )
        if session_gone is not None:
            payload["sessionGone"] = session_gone
        await self.broadcast(payload)

    async def start(self) -> None:
        await asyncio.to_thread(require_target, self.config.tmux_bin, "attach", session=self.config.session)
        self._loop = asyncio.get_running_loop()
        master_fd, slave_fd = pty.openpty()
        tty.setraw(slave_fd)
        self.master_fd = master_fd
        os.set_blocking(master_fd, False)

        lifetime_read = lifetime_write = None
        try:
            lifetime_read, lifetime_write = os.pipe()
            # The guard watches a private pipe, rather than trusting PTY HUP.
            # Only this backend holds its writer; the guard owns exactly one
            # tmux child, in the same process group used by stop().
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).with_name("control_client_guard.py")),
                    str(lifetime_read),
                    *tmux_argv(self.config.tmux_bin, "-CC", "attach", "-t",
                        self.config.tmux_bin.session_id if isinstance(self.config.tmux_bin,FreshPaneBoundary) else "="+self.config.session),
                ],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                pass_fds=(lifetime_read,),
                start_new_session=True,
                **tmux_env(self.config.tmux_bin),
            )
            self._lifetime_fd = lifetime_write
        except BaseException:
            if lifetime_write is not None:
                os.close(lifetime_write)
            os.close(master_fd)
            self.master_fd = None
            raise
        finally:
            if lifetime_read is not None:
                os.close(lifetime_read)
            os.close(slave_fd)

        self._loop.add_reader(master_fd, self._read_ready)
        await asyncio.sleep(0.2)
        await self._resolve_session_created(refresh=True)
        await self.refresh_panes(send_captures=False)
        self._history_flush_task = asyncio.create_task(self._history_flush_loop())

    async def stop(self) -> None:
        if self._fresh_recorder_proof is not None:self._fresh_recorder_proof.close()
        for proofs in self._fresh_peer_proofs.values():
            for proof in proofs:proof.close()
        self._fresh_peer_proofs.clear()
        self._closed = True
        task=self._fresh_output_task;self._fresh_output_task=None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError,RuntimeError):await task
        sinks=list(self._fresh_sink_tasks)
        for sink in sinks:sink.cancel()
        if sinks:await asyncio.gather(*sinks,return_exceptions=True)
        self._fresh_sink_tasks.clear();self._fresh_recorder_tasks.clear();self._fresh_sink_locks.clear();self._fresh_sink_bytes.clear();self._fresh_sink_counts.clear()
        self._fresh_peer_locks.clear();self._fresh_peer_generations.clear()
        self._fresh_output.clear();self._fresh_output_bytes=0
        closed_task = self._closed_task
        self._closed_task = None
        if closed_task is not None:
            closed_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await closed_task

        if self._lifetime_fd is not None:
            os.close(self._lifetime_fd)
            self._lifetime_fd = None
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

        # Consume group ownership before yielding: later (or concurrent) stops
        # must not signal a PGID that may have been recycled after cleanup.
        process = self.process
        self.process = None
        if process is not None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.to_thread(process.wait, 2)
            except subprocess.TimeoutExpired:
                pass
            finally:
                # A killed/reaped guard can leave tmux in its process group.
                # Waiting for the leader alone does not prove the group exited.
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(process.pid, signal.SIGKILL)
            try:
                await asyncio.to_thread(process.wait, 1)
            except subprocess.TimeoutExpired:
                print(
                    f"ORRERY control guard {process.pid} not reaped after bounded "
                    "group cleanup; continuing history flush",
                    file=sys.stderr,
                    flush=True,
                )

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
        pending=[task for task in self._fresh_recorder_tasks if task is not asyncio.current_task()]
        if pending:await asyncio.gather(*pending,return_exceptions=True)
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
        if self.master_fd is None or self._closed:
            return

        while True:
            try:
                chunk = os.read(self.master_fd, 8192)
            except BlockingIOError:
                return
            except OSError:
                self._schedule_closed()
                return

            if not chunk:
                self._schedule_closed()
                return

            if self._discard_block_line:
                _, separator, chunk = chunk.partition(b"\n")
                if not separator:
                    continue
                self._discard_block_line = False
            self._buffer += chunk
            while b"\n" in self._buffer:
                raw_line, self._buffer = self._buffer.split(b"\n", 1)
                self._handle_line(raw_line.rstrip(b"\r"))
                if self._closed:
                    return
            if (self._current_block is not None and self._block_limit is not None
                    and len(self._buffer) + self._block_bytes > self._block_limit):
                # A single unbounded output line must not bypass the cap while
                # waiting for its newline. Discard that line, then continue to
                # the matching ACK without changing the queue position.
                self._block_overflow = True
                self._current_block.clear()
                self._buffer = b""
                self._discard_block_line = True

    def _handle_line(self, line: str | bytes) -> None:
        raw_line = line.encode("utf-8") if isinstance(line, str) else line
        raw_line = raw_line.replace(b"\x1bP1000p", b"").replace(b"\x1b\\", b"")

        # tmux guarantees notifications never occur inside a command output
        # block. Preserve arbitrary command output (including lines which look
        # like notifications) before dispatching raw pane output below.
        if self._current_block is not None:
            text = raw_line.decode("utf-8", "replace")
            terminal = text.startswith("%end") or text.startswith("%error")
            if self._block_limit is not None:
                terminal = raw_line in (b"%end " + (self._block_boundary or b""),
                                        b"%error " + (self._block_boundary or b""))
            if terminal:
                block = self._current_block
                self._current_block = None
                pending = self._pending_blocks.popleft() if self._pending_blocks else None
                if pending is not None:
                    self._bounded_blocks.pop(pending, None)
                if pending is not None and not pending.done():
                    pending.set_result(
                        CommandResult(ok=text.startswith("%end"), lines=block,
                                      overflow=self._block_overflow)
                    )
                self._block_limit = None
                self._block_boundary = None
                self._block_overflow = False
                self._block_bytes = 0
                return
            if self._block_limit is not None:
                self._block_bytes += len(raw_line) + 1
                if self._block_bytes > self._block_limit:
                    self._block_overflow = True
                    self._current_block.clear()
                if self._block_overflow:
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
            pending = self._pending_blocks[0] if self._pending_blocks else None
            self._block_limit = self._bounded_blocks.get(pending)
            self._block_bytes = 0
            self._block_overflow = False
            self._block_boundary = raw_line.partition(b" ")[2]
            return

        if line.startswith("%exit"):
            self._schedule_closed()
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
        if isinstance(self.config.tmux_bin,FreshPaneBoundary) and pane_id!=self.config.tmux_bin.pane_id:return
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
        if isinstance(self.config.tmux_bin,FreshPaneBoundary) and pane_id!=self.config.tmux_bin.pane_id:return
        data = self._decode_pane_output(pane_id, escaped)
        if data:
            self._record_and_broadcast(pane_id, data)

    def _record_and_broadcast(self, pane_id: str, data: str) -> None:
        if isinstance(self.config.tmux_bin,FreshPaneBoundary):
            if self._closed or pane_id!=self.config.tmux_bin.pane_id:return
            self._fresh_output_bytes+=len(data.encode('utf-8'))
            if self._fresh_output_bytes>262144:
                self._fresh_output.clear();self._schedule_closed();return
            self._fresh_output.append(data)
            if self._fresh_output_task is None:
                self._fresh_output_task=asyncio.create_task(self._publish_fresh_output())
            return
        recorder = self._pane_recorders.get(pane_id)
        if recorder is not None:
            recorder.feed(data)
        self._schedule_broadcast(
            {"type": "output", "paneId": pane_id, "data": data}
        )

    async def _publish_fresh_output(self):
        try:
            while self._fresh_output and not self._closed:
                data=''.join(self._fresh_output);self._fresh_output.clear();self._fresh_output_bytes=0
                pane_id=self.config.tmux_bin.pane_id
                recorder=self._pane_recorders.get(pane_id)
                if recorder is not None:
                    self._schedule_fresh_sink(self._fresh_recorder_proof,data,recorder=recorder)
                for peer in list(self.clients):
                    proofs=self._fresh_peer_proofs.get(peer)
                    if proofs is None:continue
                    self._schedule_fresh_sink(proofs[1],data,peer=peer)
        finally:
            self._fresh_output_task=None
            if self._closed:self._fresh_output.clear();self._fresh_output_bytes=0

    def _schedule_fresh_sink(self,proof,data,*,peer=None,recorder=None):
        size=len(data.encode('utf-8'));pending=self._fresh_sink_bytes.get(proof,0)
        if pending+size>262144 or self._fresh_sink_counts.get(proof,0)>=256:
            self._fail_fresh_sink(proof,peer=peer,recorder=recorder);return
        self._fresh_sink_bytes[proof]=pending+size
        self._fresh_sink_counts[proof]=self._fresh_sink_counts.get(proof,0)+1
        lock=self._fresh_sink_locks.setdefault(proof,asyncio.Lock())
        async def deliver():
            try:
                async with lock:
                    if self._closed:return
                    if recorder is not None:
                        await proof.check()
                        if not self._closed and self._fresh_recorder_proof is proof:recorder.feed(data)
                    elif peer in self.clients and self._fresh_peer_proofs.get(peer,(None,None))[1] is proof:
                        await self.send_json(peer,{'type':'output','paneId':self.config.tmux_bin.pane_id,'data':data},proof=proof)
            except (OSError,RuntimeError) as exc:
                self._fail_fresh_sink(proof,peer=peer,recorder=recorder)
            finally:
                left=self._fresh_sink_bytes.get(proof,0)-size
                count=self._fresh_sink_counts.get(proof,0)-1
                if count>0:self._fresh_sink_counts[proof]=count
                else:self._fresh_sink_counts.pop(proof,None)
                if left>0:self._fresh_sink_bytes[proof]=left
                else:self._fresh_sink_bytes.pop(proof,None);self._fresh_sink_locks.pop(proof,None)
        task=asyncio.create_task(deliver());self._fresh_sink_tasks.add(task)
        task.add_done_callback(self._fresh_sink_tasks.discard)
        if recorder is not None:
            self._fresh_recorder_tasks.add(task);task.add_done_callback(self._fresh_recorder_tasks.discard)

    def _fail_fresh_sink(self,proof,*,peer=None,recorder=None):
        if proof.closed:return
        proof.close()
        if recorder is not None:
            print('ORRERY: fresh recorder output incomplete; history may have a gap',file=sys.stderr,flush=True)
        elif peer is not None:
            proofs=self._fresh_peer_proofs.get(peer)
            if proofs is None or proofs[1] is not proof:return
            self._fresh_peer_proofs.pop(peer,None)
            for item in proofs:item.close()
            generation=self._fresh_peer_generations.get(peer)
            self.clients.discard(peer)
            async def notify():
                try:
                    await self.send_json(peer,{'type':'error','code':'FRESH_OUTPUT_INCOMPLETE',
                        'attachGeneration':generation,'incarnation':self._incarnation,
                        'message':'Output stopped; some output or history may be missing. Reattach to continue.'},
                        attach_generation=generation)
                except Exception:
                    # A failed error frame cannot leave a live-looking socket.
                    # Closing only this peer drives the existing UI disconnect path.
                    async with self._fresh_peer_lock(peer):
                        if self._fresh_peer_generations.get(peer)!=generation:return
                        response=getattr(peer,'response',peer)
                        close=getattr(response,'close',None)
                        if close is not None:
                            await close(code=1011,message=b'Output incomplete; reconnect may have a gap')
            task=asyncio.create_task(notify());self._fresh_sink_tasks.add(task)
            task.add_done_callback(self._fresh_sink_tasks.discard)

    def _fresh_peer_lock(self,peer):
        return self._fresh_peer_locks.setdefault(peer,asyncio.Lock())

    async def attach_fresh_peer(self,peer):
        async with self._fresh_peer_lock(peer):
            if self._closed:raise TargetRefused('FRESH_TARGET_UNAVAILABLE')
            old=self._fresh_peer_proofs.pop(peer,None)
            if old is not None:
                for proof in old:proof.close()
            generation=uuid.uuid4().hex
            self._fresh_peer_generations[peer]=generation
            self._fresh_peer_proofs[peer]=(FreshEffectProof(self.config.tmux_bin,'input',membership=self._fresh_control_membership_locked),
                FreshEffectProof(self.config.tmux_bin,'capture',membership=self._fresh_control_membership))
            self.clients.add(peer)
            return generation

    async def detach_fresh_peer(self,peer,*,generation=None):
        async with self._fresh_peer_lock(peer):
            if generation is not None and self._fresh_peer_generations.get(peer)!=generation:return
            self._fresh_peer_generations.pop(peer,None)
            proofs=self._fresh_peer_proofs.pop(peer,None)
            if proofs is not None:
                for proof in proofs:proof.close()
            self.clients.discard(peer)
            self.client_locks.pop(peer,None)

    async def _fresh_control_membership(self,*,deadline):
        try:
            async with asyncio.timeout(max(0,deadline-time.monotonic())):
                async with self._write_lock:
                    await self._fresh_control_membership_locked(deadline=deadline)
        except TimeoutError:
            raise TargetRefused('FRESH_TARGET_PROOF_EXPIRED') from None

    async def _fresh_control_membership_locked(self,*,deadline):
        """A fixed PC-only read on the existing stream, with its write lock held."""
        target=self.config.tmux_bin
        if not isinstance(target,FreshPaneBoundary) or not self._write_lock.locked():
            raise TargetRefused('FRESH_TMUX_TARGET_CHANGED')
        if self.master_fd is None or self._closed or deadline<=time.monotonic():
            raise TargetRefused('FRESH_TARGET_PROOF_EXPIRED')
        transport=target.control_membership_transport()
        future=asyncio.get_running_loop().create_future();started=False
        # No caller-supplied argv and no general admission bypass. The same
        # parser/ACK queue used by normal control commands retains its order.
        args=['display-message','-p','-t',target.pane_id,
              '#{session_id}\t#{session_name}\t#{pane_id}\t#{pane_pid}']
        try:
            async with asyncio.timeout(max(0,deadline-time.monotonic())):
                self._bounded_blocks[future]=16384
                self._pending_blocks.append(future);started=True
                await self._write_master((make_tmux_command(args)+'\n').encode('utf-8'))
                result=await future
        except (Exception,asyncio.CancelledError):
            if started:self._abort_mobile_stream()
            raise TargetRefused('FRESH_TARGET_UNAVAILABLE') from None
        if not result.ok or result.overflow:
            raise TargetRefused('FRESH_TMUX_TARGET_CHANGED')
        target.check_control_membership(transport,result.lines)
        if self._closed or self.master_fd is None or deadline<=time.monotonic():
            raise TargetRefused('FRESH_TARGET_PROOF_EXPIRED')

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

        if isinstance(self.config.tmux_bin,FreshPaneBoundary):
            args=list(args)
            if '-t' in args:
                index=args.index('-t')+1
                if args[index] in {self.config.session,'='+self.config.session}:args[index]=self.config.tmux_bin.session_id
                if args[0]=='list-panes' and args[index]==self.config.tmux_bin.session_id:args[index]=self.config.tmux_bin.pane_id
        command = make_tmux_command(args) + "\n"
        async with self._write_lock:
            await asyncio.to_thread(admit_command, self.config.tmux_bin, args, session=self.config.session)
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
            if written <= 0:
                raise OSError('tmux control stream made no write progress')
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
                if isinstance(self.config.tmux_bin,FreshPaneBoundary) and (pane is None or pane.pane_id!=self.config.tmux_bin.pane_id):continue
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

    async def send_snapshot(self, websocket: Any, *, attach_generation=None) -> None:
        if isinstance(self.config.tmux_bin,FreshPaneBoundary):
            await asyncio.to_thread(self.config.tmux_bin.admit,'capture')
        await self.send_json(
            websocket,
            {
                "type": "reset",
                "session": self.config.session,
                "incarnation": self._incarnation,
                **({'attachGeneration':attach_generation} if attach_generation is not None else {}),
                "panes": [pane.to_json() for pane in sorted(self.panes.values(), key=pane_key)],
            },
            **({'attach_generation':attach_generation} if attach_generation is not None else {}),
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
                    **({'attach_generation':attach_generation} if attach_generation is not None else {}),
                )

    async def handle_client_message(self, payload: dict[str, Any]) -> None:
        message_type = payload.get("type")
        pane_id = payload.get("paneId")
        if not isinstance(pane_id, str) and message_type in {
            "input",
            "codex-page",
            "resize",
            "release",
            "split",
            "close",
        }:
            return

        if message_type == "codex-page":
            await self.send_codex_page(pane_id, payload.get("direction"), payload.get("count"))
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

    async def send_codex_page(self, pane_id: str, direction: Any, count: Any, *, proof=None) -> None:
        """Recheck live tmux state before a wheel becomes application keys.

        The viewer also requires the canonical agent record. This guard rejects
        a pane that became a shell, normal screen, mouse-on app, or unknown while
        that viewer's metadata was in flight. Ordinary xterm input is unchanged.
        """
        if pane_id not in self.panes or direction not in ("up", "down"):
            return
        if type(count) is not int or not 1 <= count <= 3:
            return
        result = await self.send_command(
            ["display-message", "-p", "-t", pane_id,
             "#{pane_current_command}\t#{alternate_on}\t#{mouse_standard_flag}\t#{mouse_button_flag}\t#{mouse_all_flag}"],
            wait=True, timeout=5.0,
        )
        if result is None or not result.ok or not result.lines:
            return
        fields = result.lines[0].split("\t")
        if len(fields) != 5 or fields[0] not in ("codex", "node") or fields[1:] != ["1", "0", "0", "0"]:
            return
        await self.send_input(pane_id, ("\x1b[5~" if direction == "up" else "\x1b[6~") * count, proof=proof)

    async def send_input(
        self, pane_id: str, data: str, *, binary: bool = False, proof=None
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
        commands = [
            ['send-keys', '-t', pane_id, '-H', *[f'{byte:02x}' for byte in raw[start:start+64]]]
            for start in range(0, len(raw), 64)
        ]
        if not commands:
            return
        if self.master_fd is None:
            raise RuntimeError('tmux control bridge is not running')
        # One input intent, one admission, one lock. No other command can
        # interleave between the proof and any chunk of this paste.
        async with self._write_lock:
            if proof is None:
                await asyncio.to_thread(admit_command, self.config.tmux_bin, commands[0], session=self.config.session)
            else:
                if not isinstance(self.config.tmux_bin,FreshPaneBoundary) or pane_id!=self.config.tmux_bin.pane_id or proof.target is not self.config.tmux_bin or proof.purpose!='input':
                    raise TargetRefused('FRESH_TMUX_TARGET_CHANGED')
                await proof.check()
                if proof.closed:raise TargetRefused('FRESH_TARGET_VIEW_CHANGED')
            for args in commands:
                self._pending_blocks.append(None)
                await self._write_master((make_tmux_command(args) + '\n').encode('utf-8'))

    async def capture_mobile_preview(self, pane_id: str, height: int, *, deadline: float) -> CommandResult:
        """One finite raw capture; never recorder or restored-history output."""
        from mobile_input import InputRefused, _deadline, MAX_CAPTURE_BYTES
        if (not re.fullmatch(r'%[0-9]+', pane_id) or type(height) is not int
                or not 1 <= height <= 10000 or deadline <= time.monotonic()
                or deadline > time.monotonic() + 3.01):
            raise InputRefused('preview_unavailable')
        future = asyncio.get_running_loop().create_future()
        args = ['capture-pane', '-p', '-J', '-t', pane_id,
                '-S', str(height - 40), '-E', str(height - 1)]
        started = False
        try:
            async with _deadline(deadline):
                async with self._write_lock:
                    if self.master_fd is None or self._closed:
                        raise InputRefused('preview_unavailable')
                    await asyncio.to_thread(admit_command, self.config.tmux_bin,
                                            args, session=self.config.session)
                    if deadline <= time.monotonic() or self.master_fd is None or self._closed:
                        raise InputRefused('preview_unavailable')
                    self._bounded_blocks[future] = MAX_CAPTURE_BYTES
                    self._pending_blocks.append(future)
                    started = True
                    await self._write_master((make_tmux_command(args) + '\n').encode('ascii'))
                result = await future
        except (Exception, asyncio.CancelledError):
            if started:
                self._abort_mobile_stream()
            raise InputRefused('preview_unavailable') from None
        if not result.ok or result.overflow:
            # Its matching ACK was consumed, so this complete stream is still
            # synchronized. An overflow never becomes a partial successful view.
            raise InputRefused('preview_unavailable')
        return result

    async def send_confirmed_input(self, pane_id: str, text: str, *, admission,
                                   valid, claim, deadline=None) -> str:
        from mobile_input import confirmed_batch
        return await confirmed_batch(self, pane_id, text, admission=admission,
                                     valid=valid, claim=claim, deadline=deadline)

    def _abort_mobile_stream(self) -> None:
        """Quarantine unknown ACK synchronization; no replay or agent exit."""
        fd, self.master_fd = self.master_fd, None
        if fd is not None:
            if self._loop is not None:
                with contextlib.suppress(Exception): self._loop.remove_reader(fd)
            with contextlib.suppress(OSError): os.close(fd)
        for pending in self._pending_blocks:
            if pending is not None and not pending.done(): pending.cancel()
        self._pending_blocks.clear()
        self._bounded_blocks.clear()
        self._current_block = None
        self._buffer = b''
        self._discard_block_line = False
        self._block_limit = None
        self._schedule_closed()

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

    async def send_json(self, websocket: Any, payload: dict[str, Any], *, proof=None, attach_generation=None) -> None:
        if isinstance(self.config.tmux_bin,FreshPaneBoundary):
            target=self.config.tmux_bin;payload=dict(payload,**target.ref)
            if 'paneId' in payload:
                if payload['paneId']!=target.pane_id:return
                payload['paneId']=target.wire_pane
            if 'panes' in payload:
                payload['panes']=[dict(row,paneId=target.wire_pane) for row in payload['panes'] if row.get('paneId')==target.pane_id]
            if 'pane' in payload:
                if payload['pane'].get('paneId')!=target.pane_id:return
                payload['pane']=dict(payload['pane'],paneId=target.wire_pane)
        lock = (self._fresh_peer_lock(websocket) if isinstance(self.config.tmux_bin,FreshPaneBoundary)
                else self.client_locks.setdefault(websocket, asyncio.Lock()))
        async with lock:
            if attach_generation is not None and self._fresh_peer_generations.get(websocket)!=attach_generation:
                return
            if attach_generation is not None and payload.get('type')!='error' and websocket not in self.clients:
                return
            if proof is not None:
                await proof.check()
                if self._closed or websocket not in self.clients or self._fresh_peer_proofs.get(websocket,(None,None))[1] is not proof:
                    raise TargetRefused('FRESH_TARGET_VIEW_CHANGED')
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
        # Browsers always send Origin on a WebSocket handshake; only this
        # bridge's own loopback page may connect. Local tools send none.
        origins = [None, *(f"http://{name}:{config.port}" for name in ("127.0.0.1", "localhost", "[::1]"))]
        async with websockets.serve(handler, config.host, config.port, origins=origins):
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
    target = LegacyTargetBoundary(args.tmux_bin)
    ensure_tmux_session(target, session, create=args.session is None)
    config = ControlConfig(
        host=args.host,
        port=args.port,
        session=session,
        tmux_bin=target,
    )
    try:
        asyncio.run(run_server(config))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
