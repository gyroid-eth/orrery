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
    if after is None:
        # Newest first, stopping at the page limit: the same page as parsing
        # the whole window and keeping its last `limit` events.
        complete_end = position + len(data)
        cursor = complete_end
        for raw in reversed(data.splitlines(keepends=True)):
            cursor -= len(raw)
            event = codex_event(raw, cursor)
            if event is not None:
                entries.append((event, cursor + len(raw)))
                if len(entries) >= limit:
                    break
        entries.reverse()
    else:
        for raw in data.splitlines(keepends=True):
            event = codex_event(raw, position)
            position += len(raw)
            if event is not None:
                entries.append((event, position))
            complete_end = position
            if len(entries) >= limit:
                break
    if after is None:
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


def open_reader(row, expect_inode=None):
    from conversation_readers import open_reader as native_reader
    return native_reader(row, expect_inode=expect_inode)


REVALIDATE_SECONDS = 30.0


def bound_signature(path: str) -> tuple:
    """(dev, inode, size, mtime) of a bound record, plus a Hermes WAL sidecar.

    Read only through the same no-follow walk as a full read. Any change,
    including a WAL appearing or a checkpoint, makes the next poll a full read.
    """
    paths = [path] + ([path + '-wal'] if path.endswith('/state.db') else [])
    out = []
    for item in paths:
        if item != path and not os.path.lexists(item):
            out.append(None)
            continue
        with open_bound_transcript(item) as stream:
            info = os.fstat(stream.fileno())
            out.append((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns))
    return tuple(out)


class UnchangedPolls:
    """Answers a repeated poll without reading the record or the dashboard.

    An entry exists only after a full, dashboard-verified read returned that
    `after` cursor. The answer carries no events or text, so it can never show
    content that was not verified; the dashboard is asked again on the first
    change or at the latest after `ttl` seconds (a held poll checks this at
    every wait step, so it holds no longer than that plus one step).
    """

    def __init__(self, *, ttl: float = REVALIDATE_SECONDS, size: int = 256, clock=None):
        import threading
        import time
        from collections import OrderedDict
        self.ttl, self.size, self.clock = ttl, size, clock or time.monotonic
        self.entries = OrderedDict()
        self.rows = OrderedDict()  # name -> the last dashboard-verified binding
        self.lock = threading.Lock()

    def remember_row(self, name, row, inode, verified_at):
        """A binding the dashboard confirmed after a read of the file `inode`."""
        with self.lock:
            self.rows[name] = dict(row=dict(row), inode=tuple(inode), verified=verified_at)
            self.rows.move_to_end(name)
            while len(self.rows) > self.size:
                self.rows.popitem(last=False)

    def recent_row(self, name):
        """That binding while it is at most `ttl` old, else None.

        A caller may skip the dashboard before a read with it, never after:
        the read's content is published only after a new dashboard check, and
        only from a file whose (dev, inode) equals the one recorded here.
        """
        with self.lock:
            entry = self.rows.get(name)
            if entry is None or self.clock() - entry['verified'] > self.ttl:
                return None
            return dict(entry, row=dict(entry['row']))

    def forget_row(self, name):
        with self.lock:
            self.rows.pop(name, None)

    def remember(self, name, row, result, signature, verified_at, digest=None, *, provider=None, fingerprint=None):
        after = result.get('after')
        reply = dict(events=[], before=None, after=after, has_older=False, has_newer=False, unchanged=True,
                     mode=result.get('mode', 'cursor'), notice=result.get('notice', ''), provider=provider)
        if not isinstance(after, str) or result.get('has_newer') or signature is None:
            return reply
        with self.lock:
            self.entries[(name, after)] = dict(path=row['transcript_path'], signature=signature,
                                               verified=verified_at, digest=digest, reply=reply,
                                               fingerprint=fingerprint)
            self.entries.move_to_end((name, after))
            while len(self.entries) > self.size:
                self.entries.popitem(last=False)
        return reply

    def same_session(self, name, after, fingerprint, signature):
        """Hermes: the file changed but this session's rows did not.

        Adopt the new signature and keep the entry (and its verification
        time), so the poll stays unchanged without a full read.
        """
        with self.lock:
            entry = self.entries.get((name, after))
            if (entry is None or fingerprint is None or signature is None
                    or entry.get('fingerprint') != fingerprint):
                return False
            entry['signature'] = signature
            return True

    def entry(self, name, after, *, fresh=True):
        with self.lock:
            entry = self.entries.get((name, after))
            if entry is None or fresh and self.clock() - entry['verified'] > self.ttl:
                return None
            return entry

    def quick(self, name, after):
        """A cheap change hint while a poll is held: lstat of the stored files.

        Only a trigger. The answer still comes from unchanged() (the no-follow
        walk), run whenever this hint moves and again before replying.
        """
        entry = self.entries.get((name, after))
        if entry is None:
            return None
        paths = [entry['path']] + ([entry['path'] + '-wal'] if entry['path'].endswith('/state.db') else [])
        out = []
        for item in paths:
            try:
                info = os.lstat(item)
                out.append((info.st_ino, info.st_size, info.st_mtime_ns))
            except OSError:
                out.append(None)
        return tuple(out)

    def unchanged(self, name, after):
        """The stored no-content reply, or None when a full read is needed."""
        entry = self.entry(name, after) if isinstance(after, str) else None
        if entry is None:
            return None
        try:
            if bound_signature(entry['path']) != entry['signature']:
                return None
        except (HistoryUnavailable, OSError):
            return None
        return dict(entry['reply'])
