"""Which conversation each agent is in, so RESUME reopens that one and no other.

``claude --continue`` and ``agy --continue`` reopen the newest conversation
in the folder, which can be someone else's: a Claude Code panel in VS Code
working in the same repository, or another agent there. Resumed that way,
the agent would carry on that conversation as if it were its own. So the
host keeps each agent's conversation id in the roster and resumes by id.

- Claude Code: the host picks the id (``--session-id``) at the first start;
  the SessionStart hook reports the new one after ``/clear`` or ``/resume``.
- Antigravity has no hooks and no way to choose the id. It keeps one SQLite
  file per conversation, named by its id and recording its workspace folder,
  created when the conversation's first prompt is submitted. A new one in an
  agent's folder, created just after an Enter was typed into that agent, is
  that agent's.
"""
from __future__ import annotations

import os
import re
import sqlite3
import urllib.parse
from pathlib import Path

CONVERSATION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.I)
AFTER_ENTER = 30.0  # An agy conversation file appears within this many seconds of its first Enter.


def valid(conversation: object) -> bool:
    return isinstance(conversation, str) and bool(CONVERSATION_ID.match(conversation))


def claude_projects() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    return Path(base) / "projects"


def claude_saved(session_id: str) -> bool:
    """Whether Claude Code has a transcript for this id, so ``--resume`` can open it."""
    return valid(session_id) and any(claude_projects().glob(f"*/{session_id}.jsonl"))


def agy_conversations() -> Path:
    configured = os.environ.get("ORRERY_AGY_CONVERSATIONS")
    if configured:
        return Path(configured)
    return Path(os.path.expanduser("~")) / ".gemini" / "antigravity-cli" / "conversations"


def created(path: Path) -> float:
    st = path.stat()
    return getattr(st, "st_birthtime", st.st_ctime)  # st_ctime is the creation time on Windows.


def new_agy_conversations(since: float) -> list[tuple[str, float, Path]]:
    """(id, created, path) of conversation files created at or after ``since``."""
    found = []
    try:
        paths = list(agy_conversations().glob("*.db"))
    except OSError:
        return []
    for path in paths:
        if not valid(path.stem):
            continue
        try:
            when = created(path)
        except OSError:
            continue
        if when >= since:
            found.append((path.stem.lower(), when, path))
    return sorted(found, key=lambda item: item[1])


def folder_forms(cwd: str) -> list[bytes]:
    """How a folder appears in agy's records: a file URI, lower-cased, maybe percent-encoded."""
    path = os.path.normpath(cwd).replace("\\", "/")
    forms = {"file:///" + path, "file:///" + urllib.parse.quote(path, safe="/:")}
    return [form.lower().encode("utf-8") for form in forms]


def agy_workspace_is(path: Path, cwd: str) -> bool | None:
    """Whether the conversation's workspace is ``cwd``; None while it cannot be read yet."""
    try:
        db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1)
        try:
            rows = db.execute("SELECT * FROM trajectory_metadata_blob").fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return None
    blob = b"".join(value for row in rows for value in row if isinstance(value, bytes)).lower()
    if not blob:
        return None
    # The folder must end where the URI ends: .../orrery must not match .../orrery-old.
    return any(re.search(re.escape(form) + rb"(?![\w.%-]|/[\w.%-])", blob) for form in folder_forms(cwd))
