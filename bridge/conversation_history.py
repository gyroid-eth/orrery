"""Bound conversation records, independent of HTTP and presentation.

The caller resolves the provider binding. This module never discovers sessions,
accepts browser paths, or writes provider files. Cursors address complete JSONL
records, so a pending partial write is picked up by the next incremental read.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager, nullcontext
from pathlib import Path
from conversation_mail import received, sent

MAX_SCAN = 4 * 1024 * 1024
MAX_TEXT = 64 * 1024
PAGE_SIZE = 80
CURSOR = re.compile(r"([a-f0-9]{24}):([0-9]{1,20})\Z")


class HistoryUnavailable(ValueError):
    """A stable public error code, never a local path or provider content."""


@contextmanager
def open_bound_transcript(path: str):
    """Pin a regular file without following symlinks in any path component."""
    if (not isinstance(path, str) or not os.path.isabs(path) or not path.endswith(('.jsonl','.jsonl.zstd','/state.db','/state.db-wal','/state.db-shm'))
            or '..' in Path(path).parts or not hasattr(os, 'O_NOFOLLOW')):
        raise HistoryUnavailable('invalid_binding')
    parent = descriptor = None
    stream = None
    try:
        parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        for component in Path(path).parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        descriptor = os.open(Path(path).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise HistoryUnavailable('invalid_binding')
        stream = os.fdopen(descriptor, 'rb')
        descriptor = None
        yield stream
    except OSError:
        raise HistoryUnavailable('history_unreadable') from None
    finally:
        if stream is not None:
            stream.close()
        if descriptor is not None:
            os.close(descriptor)
        if parent is not None:
            os.close(parent)


def assert_transcript_identity(path: str, stream) -> None:
    """Bind the actual descriptor to the path inspected by the dashboard.

    Keep the descriptor alive across the authoritative recheck, then compare it
    with a new no-follow path walk. A regular-file ABA replacement cannot return
    another file's content just because the path string was restored.
    """
    pinned = os.fstat(stream.fileno())
    with open_bound_transcript(path) as current:
        actual = os.fstat(current.fileno())
        if (pinned.st_dev, pinned.st_ino) != (actual.st_dev, actual.st_ino):
            raise HistoryUnavailable('history_changed')
    native = re.search(r'([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\.jsonl$', path)
    if native:
        try:
            first = json.loads(os.pread(stream.fileno(), 65536, 0).split(b'\n', 1)[0])
            matches = (first.get('type') == 'session_meta'
                       and str(first.get('payload', {}).get('id', '')).lower() == native[1].lower())
        except (ValueError, AttributeError, TypeError):
            matches = False
        if not matches:
            raise HistoryUnavailable('history_changed')


def codex_event(raw: bytes, offset: int) -> dict | None:
    try:
        item = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(item, dict) or item.get("type") != "response_item":
        return None
    payload = item.get("payload")
    if not isinstance(payload, dict):
        return None
    kind = payload.get("type")
    if not isinstance(kind, str):
        return None
    role = payload.get("role")
    ts = str(item.get("timestamp") or "")[:128]
    base = {"id": str(offset), "ts": ts}
    if kind == "message" and isinstance(role, str) and role in {"user", "assistant"}:
        # Provider reasoning is separate from user-visible commentary/final.
        if payload.get("role") == "assistant" and payload.get("phase") == "analysis":
            return None
        content = payload.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "\n".join(
                b["text"] for b in content
                if isinstance(b, dict) and isinstance(b.get("type"), str) and b["type"] in {"text", "input_text", "output_text"}
                and isinstance(b.get("text"), str)
            )
            if any(isinstance(b, dict) and isinstance(b.get("type"), str) and b["type"] in {"image", "input_image", "image_url"}
                   for b in content):
                text += "\n[image attachment]"
        else:
            return None
        if not text.strip():
            return None
        return received(dict(base, kind="text", role=payload["role"], text=text[:MAX_TEXT],
                    truncated=len(text) > MAX_TEXT))
    if kind in {"function_call", "custom_tool_call"}:
        # Arguments/results can contain credentials. The initial reader shows
        # only the call's name, rather than interpolating arbitrary tool input.
        name = payload.get("name")
        if isinstance(name, str):
            return sent(dict(base, kind="tool", role="assistant", text=name[:160]),name,
                        payload.get('input',payload.get('arguments')))
    return None


def _offset(cursor: str | None, file_id: str, size: int) -> int | None:
    if cursor is None:
        return None
    match = CURSOR.fullmatch(cursor)
    if not match:
        raise HistoryUnavailable("invalid_cursor")
    if match[1] != file_id or int(match[2]) > size:
        raise HistoryUnavailable("history_changed")
    return int(match[2])


def read_codex_page(path: str, *, before: str | None = None,
                    after: str | None = None, limit: int = PAGE_SIZE, stream=None) -> dict:
    if before is not None and after is not None:
        raise HistoryUnavailable("invalid_cursor")
    if not isinstance(path, str) or not os.path.isabs(path) or not path.endswith(".jsonl"):
        raise HistoryUnavailable("invalid_binding")
    if not 1 <= limit <= 200:
        raise HistoryUnavailable("invalid_limit")
    try:
        # The descriptor pins this read to one file even if its path is replaced.
        with (nullcontext(stream) if stream is not None else open_bound_transcript(path)) as stream:
            assert_transcript_identity(path, stream)
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise HistoryUnavailable("invalid_binding")
            identity = f"{os.path.realpath(path)}\0{info.st_dev}\0{info.st_ino}"
            file_id = hashlib.sha256(identity.encode()).hexdigest()[:24]
            size = info.st_size
            end = _offset(before, file_id, size) if before is not None else size
            start = _offset(after, file_id, size) if after is not None else max(0, end - MAX_SCAN)
            stream.seek(max(0, start - 1))
            starts_record = start == 0 or stream.read(1) == b"\n"
            if after is not None and not starts_record:
                raise HistoryUnavailable("invalid_cursor")
            stream.seek(start)
            data = stream.read(min(MAX_SCAN, size - start) if after is not None else end - start)
            assert_transcript_identity(path, stream)
    except OSError:
        raise HistoryUnavailable("history_unreadable") from None

    position = start
    if after is None and start and not starts_record:
        # The first bytes may start in the middle of a JSON record.
        newline = data.find(b"\n")
        if newline < 0:
            return dict(events=[], before=f"{file_id}:{start}", after=None,
                        has_older=True, has_newer=False, skipped_large_record=True)
        position += newline + 1
        data = data[newline + 1:]
    window_start = position
    complete = data.rfind(b"\n") + 1
    if after is not None and len(data) == MAX_SCAN and complete == 0:
        raise HistoryUnavailable("record_too_large")
    data = data[:complete]  # Never advance over an in-progress record.
    entries = []
    complete_end = position
    for raw in data.splitlines(keepends=True):
        event = codex_event(raw, position)
        position += len(raw)
        if event is not None:
            entries.append((event, position))
        complete_end = position
        if after is not None and len(entries) >= limit:
            break
    if after is None:
        entries = entries[-limit:]
        oldest = int(entries[0][0]["id"]) if entries else window_start
    else:
        oldest = int(entries[0][0]["id"]) if entries else start
    for event, next_offset in entries:
        event['cursor_before'] = f"{file_id}:{event['id']}"
        event['cursor_after'] = f"{file_id}:{next_offset}"
    return dict(events=[event for event, _ in entries],
                before=f"{file_id}:{oldest}", after=f"{file_id}:{complete_end}",
                has_older=oldest > 0, has_newer=after is not None and complete_end < size
                and complete_end > start, skipped_large_record=False)


def bound_agent(payload: object, name: str, *, api_generation: int = 34) -> dict:
    """Only an authoritative bound provider row; no candidate/path guessing."""
    rows = payload.get("agents") if isinstance(payload, dict) else None
    matches = [row for row in rows or [] if isinstance(row, dict) and row.get("name") == name]
    if len(matches) != 1:
        raise HistoryUnavailable("agent_unavailable")
    row = matches[0]
    program = row.get('program')
    if program not in {'codex','codex-cli','claude','claude-code','dsh','hermes'}:
        raise HistoryUnavailable('provider_unavailable')
    if program not in {'codex','codex-cli'} and api_generation < 35:
        raise HistoryUnavailable('dashboard_upgrade_required')
    if row.get('history_binding') != 'bound' or not isinstance(row.get('transcript_path'),str):
        from conversation_artifacts import redact
        error=HistoryUnavailable('history_stale' if row.get('history_binding')=='stale' else 'history_unconfirmed')
        error.reason=redact(str(row.get('history_binding_reason') or ''))[:512]
        error.reason_code=str(row.get('history_binding_reason_code') or '')[:128]
        raise error
    if program not in {'codex','codex-cli'} and not row.get('history_session_id'):
        raise HistoryUnavailable('invalid_binding')
    return row


def bound_codex_agent(payload: object, name: str) -> dict:
    """Compatibility selector for callers using the pre-35 contract."""
    return bound_agent(payload,name)


def open_reader(row):
    from conversation_readers import open_reader as native_reader
    return native_reader(row)
