"""One SQLite file shared by every agent on this PC.

Each agent's MCP server process, the host and the CLI open the same file.
WAL lets readers run while one writer commits; every write is a short
BEGIN IMMEDIATE transaction, so concurrent senders queue instead of failing.

The tables follow ORRERY Mail's shape (agents / messages /
message_recipients) so the two read alike; ``board`` is the shared
whiteboard, an append-only log of posts per topic.
"""
from __future__ import annotations

import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 1
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
TOPIC = re.compile(r"[^\x00-\x1f\x7f]{1,128}\Z")
IMPORTANCE = ("low", "normal", "high", "urgent")
MAX_SUBJECT = 200
MAX_BODY = 64 * 1024
MAX_RECIPIENTS = 16

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    program TEXT,
    cwd TEXT,
    created_ts TEXT NOT NULL,
    last_seen_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    sender_id INTEGER NOT NULL REFERENCES agents(id),
    thread_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    importance TEXT NOT NULL DEFAULT 'normal',
    body_md TEXT NOT NULL,
    created_ts TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS message_recipients (
    message_id INTEGER NOT NULL REFERENCES messages(id),
    agent_id INTEGER NOT NULL REFERENCES agents(id),
    kind TEXT NOT NULL DEFAULT 'to',
    read_ts TEXT,
    notified_ts TEXT,
    PRIMARY KEY (message_id, agent_id)
);
CREATE INDEX IF NOT EXISTS recipients_unread
    ON message_recipients(agent_id, read_ts);
CREATE INDEX IF NOT EXISTS messages_thread ON messages(thread_id, id);
CREATE TABLE IF NOT EXISTS board (
    id INTEGER PRIMARY KEY,
    topic TEXT NOT NULL,
    author_id INTEGER NOT NULL REFERENCES agents(id),
    text TEXT NOT NULL,
    created_ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS board_topic ON board(topic, id);
"""


class HubError(ValueError):
    """A request the hub refuses; the message is safe to show an agent."""


def default_path() -> Path:
    configured = os.environ.get("ORRERY_HUB_DB")
    if configured:
        return Path(configured).expanduser()
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    return Path(base) / "orrery-win" / "hub.db"


def now(offset: float = 0.0) -> str:
    """UTC timestamp, ``offset`` seconds from now; such strings sort in time order."""
    moment = datetime.now(timezone.utc) + timedelta(seconds=offset)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def check_name(name: object) -> str:
    if not isinstance(name, str) or not NAME.match(name):
        raise HubError(
            f"invalid agent name {name!r}: start with a letter, then letters, "
            "digits, '_', '.' or '-' (up to 64)")
    return name


class Hub:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path is not None else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None,
                                  check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=10000")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise HubError(f"hub.db schema {version} is newer than this code ({SCHEMA_VERSION})")
        if version < SCHEMA_VERSION:
            with self.write():
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        self.db.execute(statement)
                self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def write(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    # Agents ---------------------------------------------------------------

    def register(self, name: str, *, program: str | None = None, cwd: str | None = None) -> int:
        """Create or refresh an agent; returns its id. The name is the address."""
        check_name(name)
        ts = now()
        with self.write() as db:
            db.execute(
                "INSERT INTO agents(name, program, cwd, created_ts, last_seen_ts)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET last_seen_ts=excluded.last_seen_ts,"
                " program=COALESCE(excluded.program, agents.program),"
                " cwd=COALESCE(excluded.cwd, agents.cwd)",
                (name, program, cwd, ts, ts))
            return db.execute("SELECT id FROM agents WHERE name=?", (name,)).fetchone()[0]

    def agent_id(self, name: str) -> int | None:
        row = self.db.execute("SELECT id FROM agents WHERE name=?", (name,)).fetchone()
        return row[0] if row else None

    def agents(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT a.name, a.program, a.cwd, a.last_seen_ts,"
            " (SELECT count(*) FROM message_recipients r"
            "   WHERE r.agent_id=a.id AND r.read_ts IS NULL) AS unread"
            " FROM agents a ORDER BY a.name COLLATE NOCASE")
        return [dict(row) for row in rows]

    # Mail -----------------------------------------------------------------

    def send(self, sender: str, to, subject: str, body: str, *,
             importance: str = "normal", reply_to: int | None = None) -> dict:
        recipients = [to] if isinstance(to, str) else to
        if not isinstance(recipients, list) or not recipients:
            raise HubError("'to' must be an agent name or a list of names")
        if len(recipients) > MAX_RECIPIENTS:
            raise HubError(f"at most {MAX_RECIPIENTS} recipients")
        if not isinstance(subject, str) or not subject.strip():
            raise HubError("subject is required")
        if not isinstance(body, str):
            raise HubError("body must be text")
        if len(subject) > MAX_SUBJECT or len(body) > MAX_BODY:
            raise HubError(f"subject is limited to {MAX_SUBJECT} and body to {MAX_BODY} characters")
        if importance not in IMPORTANCE:
            raise HubError(f"importance must be one of {', '.join(IMPORTANCE)}")
        sender_id = self.agent_id(check_name(sender))
        if sender_id is None:
            raise HubError(f"sender {sender!r} is not registered")
        ids, unknown = {}, []
        for name in recipients:
            agent = self.agent_id(check_name(name))
            if agent is None:
                unknown.append(name)
            else:
                ids.setdefault(agent, name)
        if unknown:
            known = ", ".join(a["name"] for a in self.agents()) or "(none)"
            raise HubError(f"unknown recipient(s): {', '.join(unknown)}. Known agents: {known}")
        with self.write() as db:
            thread = None
            if reply_to is not None:
                parent = db.execute("SELECT thread_id FROM messages WHERE id=?", (reply_to,)).fetchone()
                if parent is None:
                    raise HubError(f"message {reply_to} does not exist")
                thread = parent[0]
            cursor = db.execute(
                "INSERT INTO messages(sender_id, thread_id, subject, importance, body_md, created_ts)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (sender_id, thread or "", subject.strip(), importance, body, now()))
            message_id = cursor.lastrowid
            if thread is None:
                thread = str(message_id)
                db.execute("UPDATE messages SET thread_id=? WHERE id=?", (thread, message_id))
            db.executemany(
                "INSERT INTO message_recipients(message_id, agent_id, kind) VALUES (?, ?, 'to')",
                [(message_id, agent) for agent in ids])
        return dict(id=message_id, thread_id=thread, to=list(ids.values()))

    def _messages(self, where: str, params: tuple, limit: int) -> list[dict]:
        rows = self.db.execute(
            "SELECT m.id, m.thread_id, m.subject, m.importance, m.body_md AS body,"
            " m.created_ts AS ts, s.name AS sender,"
            " (SELECT group_concat(a.name, ', ') FROM message_recipients r"
            "   JOIN agents a ON a.id=r.agent_id WHERE r.message_id=m.id) AS recipients"
            " FROM messages m JOIN agents s ON s.id=m.sender_id"
            f" WHERE {where} ORDER BY m.id LIMIT ?", (*params, limit))
        return [dict(row) for row in rows]

    def inbox(self, name: str, *, unread_only: bool = True, mark_read: bool = True,
              limit: int = 20) -> list[dict]:
        agent = self.agent_id(check_name(name))
        if agent is None:
            raise HubError(f"agent {name!r} is not registered")
        limit = max(1, min(int(limit), 100))
        unread = " AND r.read_ts IS NULL" if unread_only else ""
        messages = self._messages(
            "m.id IN (SELECT r.message_id FROM message_recipients r"
            f" WHERE r.agent_id=?{unread})", (agent,), limit)
        if mark_read and messages:
            with self.write() as db:
                db.executemany(
                    "UPDATE message_recipients SET read_ts=? WHERE message_id=? AND agent_id=?"
                    " AND read_ts IS NULL", [(now(), m["id"], agent) for m in messages])
        return messages

    def thread(self, thread_id: str, *, limit: int = 50) -> list[dict]:
        return self._messages("m.thread_id=?", (str(thread_id),), max(1, min(int(limit), 200)))

    def recent(self, *, limit: int = 50) -> list[dict]:
        """The latest messages across every agent, newest first, for the host's UI."""
        limit = max(1, min(int(limit), 200))
        rows = self.db.execute(
            "SELECT id FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        if not rows:
            return []
        oldest = rows[-1][0]
        return list(reversed(self._messages("m.id>=?", (oldest,), limit)))

    def pending_notifications(self, renotify_before: str | None = None) -> list[dict]:
        """Unread mail nobody has been told about yet, for the host's dispatcher.

        With ``renotify_before`` (a timestamp like ``now()``), mail that was
        notified before then and is still unread comes too: the notice may
        have been lost, for example when the CLI failed to start its turn.
        """
        rows = self.db.execute(
            "SELECT r.message_id, a.name AS recipient, s.name AS sender, m.subject, m.importance,"
            " r.notified_ts"
            " FROM message_recipients r JOIN agents a ON a.id=r.agent_id"
            " JOIN messages m ON m.id=r.message_id JOIN agents s ON s.id=m.sender_id"
            " WHERE r.read_ts IS NULL AND (r.notified_ts IS NULL OR r.notified_ts < ?)"
            " ORDER BY r.message_id", (renotify_before or "",))
        return [dict(row) for row in rows]

    def mark_notified(self, message_id: int, recipient: str) -> None:
        with self.write() as db:
            db.execute(
                "UPDATE message_recipients SET notified_ts=? WHERE message_id=?"
                " AND agent_id=(SELECT id FROM agents WHERE name=?)",
                (now(), message_id, recipient))

    # Board ----------------------------------------------------------------

    def board_write(self, author: str, topic: str, text: str) -> dict:
        if not isinstance(topic, str) or not TOPIC.match(topic.strip() or "\0"):
            raise HubError("topic must be 1-128 printable characters")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_BODY:
            raise HubError(f"text must be 1-{MAX_BODY} characters")
        author_id = self.agent_id(check_name(author))
        if author_id is None:
            raise HubError(f"agent {author!r} is not registered")
        with self.write() as db:
            cursor = db.execute(
                "INSERT INTO board(topic, author_id, text, created_ts) VALUES (?, ?, ?, ?)",
                (topic.strip(), author_id, text, now()))
        return dict(id=cursor.lastrowid, topic=topic.strip())

    def board_read(self, topic: str | None = None, *, limit: int = 30) -> list[dict]:
        limit = max(1, min(int(limit), 200))
        if topic is None:
            rows = self.db.execute(
                "SELECT topic, count(*) AS posts, max(created_ts) AS last_ts FROM board"
                " GROUP BY topic ORDER BY max(id) DESC LIMIT ?", (limit,))
            return [dict(row) for row in rows]
        rows = self.db.execute(
            "SELECT * FROM (SELECT b.id, b.topic, a.name AS author, b.text, b.created_ts AS ts"
            " FROM board b JOIN agents a ON a.id=b.author_id WHERE b.topic=?"
            " ORDER BY b.id DESC LIMIT ?) ORDER BY id", (topic.strip(), limit))
        return [dict(row) for row in rows]
