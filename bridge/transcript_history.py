"""Read-only, explicitly bound provider transcripts for cockpit history browsing.

The visible tmux buffer is not the history of an alternate-screen CLI.
Only files bound to a running process in the selected pane are eligible;
neither the browser nor this endpoint supplies an arbitrary filesystem path.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

from runtime_target import tmux_argv, tmux_env

SESSION_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
PANE_ID = re.compile(r"^%\d+$")
CLAUDE_SESSION = re.compile(r"--(?:resume|session-id)(?:=|\s+)([a-fA-F0-9-]{36})(?:\s|$)")
PAGE_BYTES = 1_048_576
MAX_ITEMS = 240
MAX_TEXT = 18_000


class TranscriptUnavailable(Exception):
    """The requested pane cannot be bound to one provider transcript."""


def _command(argv: list[str], *, timeout: float = 3) -> str:
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TranscriptUnavailable("process metadata unavailable") from exc
    if result.returncode:
        raise TranscriptUnavailable("process metadata unavailable")
    return result.stdout


def _pane_details(tmux_bin, session: str, pane_id: str) -> tuple[int, Path]:
    if not SESSION_NAME.fullmatch(session) or not PANE_ID.fullmatch(pane_id):
        raise TranscriptUnavailable("invalid session or pane")
    try:
        result = subprocess.run(
            tmux_argv(tmux_bin, "list-panes", "-s", "-t", session,
                      "-F", "#{pane_id}\t#{pane_pid}\t#{pane_current_path}"),
            capture_output=True, text=True, check=False, timeout=3,
            **tmux_env(tmux_bin),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TranscriptUnavailable("tmux unavailable") from exc
    if result.returncode:
        raise TranscriptUnavailable("session unavailable")
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if len(fields) == 3 and fields[0] == pane_id:
            try:
                return int(fields[1]), Path(fields[2]).resolve(strict=True)
            except (ValueError, OSError) as exc:
                raise TranscriptUnavailable("pane path unavailable") from exc
    raise TranscriptUnavailable("pane does not belong to session")


def _cli_process(pane_pid: int) -> tuple[str, int, str]:
    """Find the nearest active provider process descended from the pane shell."""
    by_parent: dict[int, list[tuple[int, str]]] = {}
    for line in _command(["ps", "-axo", "pid=,ppid=,command="]).splitlines():
        parts = line.strip().split(maxsplit=2)
        if len(parts) != 3:
            continue
        try:
            pid, parent = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        by_parent.setdefault(parent, []).append((pid, parts[2]))
    frontier = [pane_pid]
    visited = {pane_pid}
    for _ in range(6):
        next_frontier = []
        matches = []
        for parent in frontier:
            for pid, command in by_parent.get(parent, []):
                if pid in visited:
                    continue
                visited.add(pid)
                executable = Path(command.split(maxsplit=1)[0]).name
                if executable in ("codex", "claude"):
                    matches.append((executable, pid, command))
                else:
                    next_frontier.append(pid)
        if matches:
            if len(matches) != 1:
                raise TranscriptUnavailable("ambiguous CLI processes in pane")
            return matches[0]
        frontier = next_frontier
    raise TranscriptUnavailable("no supported CLI in selected pane")


def _safe_file(path: Path, root: Path) -> Path:
    root = root.resolve()
    try:
        actual = path.resolve(strict=True)
        info = path.lstat()
    except OSError as exc:
        raise TranscriptUnavailable("transcript missing") from exc
    if (not actual.is_relative_to(root) or path.is_symlink()
            or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()):
        raise TranscriptUnavailable("transcript rejected")
    return actual


def _matching_cwd(path: Path, provider: str, cwd: Path) -> bool:
    try:
        with path.open("rb") as infile:
            for _ in range(60):
                line = infile.readline(256_000)
                if not line:
                    break
                try:
                    record = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if provider == "codex" and record.get("type") == "session_meta":
                    source = record.get("payload", {}).get("cwd")
                    return bool(source and Path(source).resolve() == cwd)
                if provider == "claude" and record.get("type") in ("user", "assistant", "system"):
                    source = record.get("cwd")
                    if source:
                        return Path(source).resolve() == cwd
    except OSError:
        pass
    return False


def _transcript_path(provider: str, pid: int, argv: str, cwd: Path,
                     home: Path) -> Path:
    if provider == "codex":
        root = home / ".codex" / "sessions"
        paths = set()
        for line in _command(["lsof", "-nP", "-Fn", "-p", str(pid)]).splitlines():
            if not line.startswith("n/") or not line.endswith(".jsonl"):
                continue
            try:
                candidate = _safe_file(Path(line[1:]), root)
            except TranscriptUnavailable:
                continue
            if _matching_cwd(candidate, provider, cwd):
                paths.add(candidate)
        if len(paths) == 1:
            return paths.pop()
    elif provider == "claude":
        match = CLAUDE_SESSION.search(argv)
        if not match:
            raise TranscriptUnavailable("Claude session id unavailable")
        root = home / ".claude" / "projects"
        paths = []
        for candidate in root.glob("*/" + match.group(1) + ".jsonl"):
            try:
                candidate = _safe_file(candidate, root)
            except TranscriptUnavailable:
                continue
            if _matching_cwd(candidate, provider, cwd):
                paths.append(candidate)
        if len(paths) == 1:
            return paths[0]
    raise TranscriptUnavailable("no uniquely bound transcript")


def _message(record: dict, provider: str) -> dict | None:
    if provider == "codex":
        if record.get("type") != "response_item":
            return None
        payload = record.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "message":
            return None
        role = payload.get("role")
        content = payload.get("content", [])
    else:
        role = record.get("type")
        if role not in ("user", "assistant") or record.get("isSidechain"):
            return None
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        content = message.get("content", [])
    if role not in ("user", "assistant"):
        return None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "\n".join(str(part["text"]) for part in content
                         if isinstance(part, dict)
                         and part.get("type") in ("text", "input_text", "output_text")
                         and isinstance(part.get("text"), str))
    else:
        return None
    if not text.strip():
        return None
    clipped = len(text) > MAX_TEXT
    return {
        "role": role, "text": text[:MAX_TEXT], "clipped": clipped,
        "timestamp": record.get("timestamp", ""),
    }


def _page(path: Path, provider: str, before: int | None,
          source_id: str | None = None) -> dict:
    identity = hashlib.sha256(os.fsencode(path)).hexdigest()[:16]
    if source_id is not None and source_id != identity:
        raise TranscriptUnavailable("transcript changed; reopen history")
    size = path.stat().st_size
    if before is not None and (before < 0 or before > size):
        raise TranscriptUnavailable("invalid history cursor")
    end = size if before is None else before
    start = max(0, end - PAGE_BYTES)
    records: list[tuple[int, dict]] = []
    with path.open("rb") as infile:
        if start:
            infile.seek(start - 1)
            infile.readline()
        cursor = infile.tell()
        while infile.tell() < end:
            line_start = infile.tell()
            line = infile.readline()
            if infile.tell() > end:
                break  # The writer may currently be appending an unfinished JSON line.
            try:
                record = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            item = _message(record, provider)
            if item:
                records.append((line_start, item))
    if len(records) > MAX_ITEMS:
        cursor = records[-MAX_ITEMS][0]
        records = records[-MAX_ITEMS:]
    return {
        "provider": provider, "source_id": identity,
        "items": [item for _, item in records],
        "older_before": cursor if cursor > 0 else None,
        "has_older": cursor > 0,
        "scope": "provider text transcript, not live TUI scroll position",
    }


def read_pane_history(tmux_bin, session: str, pane_id: str,
                      before: int | None = None, source_id: str | None = None,
                      *, home: Path | None = None) -> dict:
    pid, cwd = _pane_details(tmux_bin, session, pane_id)
    provider, cli_pid, command = _cli_process(pid)
    source = _transcript_path(provider, cli_pid, command, cwd, home or Path.home())
    try:
        return _page(source, provider, before, source_id)
    except OSError as exc:
        raise TranscriptUnavailable("transcript no longer available") from exc
