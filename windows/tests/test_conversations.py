"""RESUME reopens the agent's own conversation, never just the folder's newest."""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

WINDOWS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS))

from host import conversations, programs  # noqa: E402
from host.sessions import Manager  # noqa: E402


class Env:
    """Set environment variables for a block, then put the old values back."""

    def __init__(self, **values):
        self.values, self.old = values, {}

    def __enter__(self):
        for key, value in self.values.items():
            self.old[key] = os.environ.get(key)
            os.environ[key] = value

    def __exit__(self, *exc):
        for key, value in self.old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def agy_conversation(folder: Path, workspace: str) -> str:
    """A stand-in for one of Antigravity's conversation files."""
    cid = str(uuid.uuid4())
    db = sqlite3.connect(folder / f"{cid}.db")
    db.execute("CREATE TABLE trajectory_metadata_blob (id TEXT, data BLOB)")
    uri = "file:///" + workspace.replace("\\", "/")
    blob = b"\n\xdd\x01\n7" + uri.encode() + b"\x127" + uri.encode() + b"\x1a[\n\x0fKMY/orrery"
    db.execute("INSERT INTO trajectory_metadata_blob VALUES ('main', ?)", (blob,))
    db.commit()
    db.close()
    return cid


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = Env(ORRERY_WIN_STATE=self.tmp.name, ORRERY_CLAUDE=sys.executable,
                       ORRERY_AGY=sys.executable, CLAUDE_CONFIG_DIR=self.tmp.name)
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__()
        self.tmp.cleanup()

    def flag(self, launch, name):
        return launch.argv[launch.argv.index(name) + 1] if name in launch.argv else None

    def test_claude_new_resume_and_unsaved(self):
        fresh = programs.build("claude", "alice")
        self.assertTrue(conversations.valid(fresh.conversation))
        self.assertEqual(self.flag(fresh, "--session-id"), fresh.conversation)

        saved = str(uuid.uuid4())
        transcript = Path(self.tmp.name) / "projects" / "C--work" / f"{saved}.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text("{}\n", encoding="utf-8")
        resumed = programs.build("claude", "alice", resume=True, conversation=saved)
        self.assertEqual((self.flag(resumed, "--resume"), resumed.conversation), (saved, saved))

        # Never prompted, so Claude saved nothing: start it again under the same id.
        unused = str(uuid.uuid4())
        again = programs.build("claude", "alice", resume=True, conversation=unused)
        self.assertEqual((self.flag(again, "--session-id"), self.flag(again, "--resume")), (unused, None))

        for launch in (fresh, resumed, again):
            self.assertNotIn("--continue", launch.argv)

    def test_agy(self):
        cid = str(uuid.uuid4())
        resumed = programs.build("agy", "bob", resume=True, conversation=cid)
        self.assertEqual(self.flag(resumed, "--conversation"), cid)
        unknown = programs.build("agy", "bob", resume=True)
        self.assertEqual((unknown.conversation, self.flag(unknown, "--conversation")), (None, None))
        self.assertNotIn("--continue", unknown.argv)


class WorkspaceTest(unittest.TestCase):
    def test_folder_must_match_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            cid = agy_conversation(Path(tmp), r"C:\Users\me\orrery")
            path = Path(tmp) / f"{cid}.db"
            self.assertTrue(conversations.agy_workspace_is(path, r"c:\users\me\orrery"))
            self.assertFalse(conversations.agy_workspace_is(path, r"C:\Users\me\orr"))
            other = agy_conversation(Path(tmp), r"C:\Users\me\orrery-old")
            self.assertFalse(conversations.agy_workspace_is(Path(tmp) / f"{other}.db", r"C:\Users\me\orrery"))
            sub = agy_conversation(Path(tmp), r"C:\Users\me\orrery\app")
            self.assertFalse(conversations.agy_workspace_is(Path(tmp) / f"{sub}.db", r"C:\Users\me\orrery"))


class FakeSession:
    program, status = "agy", "running"

    def __init__(self, started):
        self.started_ts = started
        self.enters = []


class TrackAgyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.convs = root / "conversations"
        self.convs.mkdir()
        self.work, self.elsewhere = root / "work", root / "elsewhere"
        self.work.mkdir()
        self.elsewhere.mkdir()
        self.env = Env(ORRERY_WIN_STATE=str(root), ORRERY_AGY_CONVERSATIONS=str(self.convs))
        self.env.__enter__()
        self.manager = Manager(asyncio.get_running_loop(), hub_db=str(root / "hub.db"))
        self.manager.create("bob", "agy", str(self.work))
        self.session = self.manager.sessions["bob"] = FakeSession(time.time() - 5)

    async def asyncTearDown(self):
        self.manager.hub.close()
        self.env.__exit__()
        self.tmp.cleanup()

    async def track(self):
        await asyncio.get_running_loop().run_in_executor(None, self.manager.track_agy)
        await asyncio.sleep(0)  # Let the assignment scheduled on the loop run.
        return self.manager.agents["bob"].conversation

    async def test_takes_the_conversation_its_enter_began(self):
        agy_conversation(self.convs, str(self.elsewhere))  # Another folder: never bob's.
        self.assertIsNone(await self.track())  # No Enter typed yet: nothing is bob's.
        self.session.enters.append(time.time())
        mine = agy_conversation(self.convs, str(self.work))
        self.assertEqual(await self.track(), mine)
        reloaded = Manager(asyncio.get_running_loop(), hub_db=self.manager.hub_db)
        reloaded.hub.close()
        self.assertEqual(reloaded.agents["bob"].conversation, mine)  # Kept in agents.json.

    async def test_never_takes_another_agents_conversation(self):
        self.manager.create("carol", "agy", str(self.work))
        self.session.enters.append(time.time())
        theirs = agy_conversation(self.convs, str(self.work))
        self.manager.conversation_seen("carol", theirs)
        self.assertIsNone(await self.track())


if __name__ == "__main__":
    unittest.main()
