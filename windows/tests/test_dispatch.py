"""Phase 3: idle detection and the dispatcher that wakes agents with mail."""
from __future__ import annotations

import asyncio
import os
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

WINDOWS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS))
from hub.db import Hub  # noqa: E402
from host import activity, programs  # noqa: E402
from host.dispatcher import Dispatcher, notice  # noqa: E402

try:
    import winpty  # noqa: F401
    import aiohttp
    from aiohttp import web
except ImportError:  # pragma: no cover
    winpty = None

RULE = "─" * 60
AGY_IDLE = ["  ▄▀▀▄   Antigravity CLI", RULE, "> ", RULE,
            "? for shortcuts                       auto · Gemini"]
AGY_BUSY = ["● Running (Write-Output 1...)", "⢿  Running command...", RULE, ">", RULE,
            "esc to cancel                         auto · Gemini"]
AGY_TRUST = ["Do you trust the contents of this project?", "> Yes, I trust this folder",
             "  No, exit", "  ↑/↓ Navigate · enter Confirm"]
CLAUDE_IDLE = [" ▐▛███▜▌   Claude Code v2.1", RULE, '❯ Try "fix lint errors"', RULE,
               "  ⏵⏵ auto mode on (shift+tab to cycle)"]
CLAUDE_BUSY = ["❯ do the thing", "✻ Thinking… (esc to interrupt)", RULE, "❯", RULE]
# Claude Code can draw its prompt as ">" (read from a live agent, 2.1.330).
CLAUDE_IDLE_GT = ["> あれ，動いてる？", "", "● 動いています。", "",
                  "✻ Cogitated for 1m 1s · done 22:50", "", RULE, "> ", RULE,
                  "  ⏵⏵ auto mode on (shift+tab to cycle)"]
# Old prompts and quoted lines in the scrollback are not the live prompt.
CLAUDE_NO_PROMPT = ["> あれ，動いてる？", "", "● 引用します:", "  > a quoted line", "",
                    "  ⏵⏵ auto mode on (shift+tab to cycle)"]
CLAUDE_PERMISSION = ["Do you want to proceed?", "❯ 1. Yes", "  2. No"]
CLAUDE_TRUST = [" Quick safety check: Is this a project you created or one you trust?",
                " ❯ No, exit", "   Yes, I trust this folder", " Enter to confirm · Esc to cancel"]


class ScreenStateTest(unittest.TestCase):
    def test_antigravity(self):
        self.assertEqual(activity.screen_state("agy", AGY_IDLE), "idle")
        self.assertEqual(activity.screen_state("agy", AGY_BUSY), "busy")
        self.assertEqual(activity.screen_state("agy", AGY_TRUST), "dialog")
        self.assertEqual(activity.screen_state("agy", []), "busy")

    def test_claude(self):
        self.assertEqual(activity.screen_state("claude", CLAUDE_IDLE), "idle")
        self.assertEqual(activity.screen_state("claude", CLAUDE_BUSY), "busy")
        self.assertEqual(activity.screen_state("claude", CLAUDE_PERMISSION), "dialog")
        self.assertEqual(activity.screen_state("claude", CLAUDE_TRUST), "dialog")

    def test_claude_prompt_mark_greater_than(self):
        self.assertEqual(activity.screen_state("claude", CLAUDE_IDLE_GT), "idle")
        typed = CLAUDE_IDLE_GT[:-3] + [RULE, "> writerのノートできた？", RULE, CLAUDE_IDLE_GT[-1]]
        self.assertEqual(activity.screen_state("claude", typed), "idle")
        self.assertEqual(activity.screen_state("claude", CLAUDE_NO_PROMPT), "unclear")


class ClaudeActivityTest(unittest.TestCase):
    """The screen's busy marker beats a hook; a screen it cannot read does not."""

    def setUp(self):
        from host.sessions import Session

        self.now = 1_000_000.0
        self.session = Session("tech", asyncio.new_event_loop(), "claude")
        self.session.status, self.session.started_ts = "running", self.now - 600
        self.session.last_output = self.now - 5
        self.rows = CLAUDE_NO_PROMPT
        self.session.screen_rows = lambda: self.rows

    def tearDown(self):
        self.session.loop.close()

    def state(self, hook):
        self.session.hook_state = hook
        return self.session.refresh(self.now)

    def test_stop_hook_wins_over_an_unclear_screen(self):
        self.assertEqual(self.state("idle"), "idle")

    def test_unclear_screen_without_a_stop_stays_busy(self):
        self.assertEqual(self.state("busy"), "busy")
        self.session.last_output = self.now - 120  # Long quiet, still no prompt seen.
        self.assertEqual(self.state("busy"), "busy")
        self.assertEqual(self.state(None), "busy")  # No hooks at all: never guess idle.

    def test_busy_marker_and_dialog_still_beat_the_hook(self):
        self.rows = CLAUDE_BUSY
        self.assertEqual(self.state("idle"), "busy")
        self.rows = CLAUDE_PERMISSION
        self.assertEqual(self.state("idle"), "attention")

    def test_prompt_on_screen_is_idle(self):
        self.rows = CLAUDE_IDLE_GT
        self.assertEqual(self.state("idle"), "idle")
        self.session.last_output = self.now - 120  # Interrupted turn: no Stop came.
        self.assertEqual(self.state("busy"), "idle")


class TypedTest(unittest.TestCase):
    def test_terminal_reports_are_not_typing(self):
        from host.sessions import typed

        for data in ("\x1b[I", "\x1b[O", "\x1b[?1;2c", "\x1b[12;40R", "\x1b[A", "\x1bOB",
                     "\x1b]11;rgb:0b0b/0d0d/1111\x1b\\", "\x1b[<0;10;5M", "\x1bP>|xterm\x1b\\"):
            self.assertFalse(typed(data), repr(data))
        for data in ("a", "hello", "\r", "\x7f", "\x1b[Ax"):
            self.assertTrue(typed(data), repr(data))


class ReplayAndViewersTest(unittest.TestCase):
    def test_replay_drops_terminal_queries(self):
        from host.sessions import without_queries

        raw = "a\x1b[6nb\x1b[cc\x1b[>0cd\x1b[?ue\x1b]11;?\x07f\x1b[14tg\x1b[31mred\x1b[m\x1b[2J"
        self.assertEqual(without_queries(raw), "abcdefg\x1b[31mred\x1b[m\x1b[2J")

    def test_only_the_owner_sends_automatic_answers(self):
        import asyncio as _asyncio
        from host.sessions import Session

        session = Session("bob", _asyncio.new_event_loop(), "agy")
        written = []
        session.write = lambda data, user=True: written.append(data)
        tab_a, tab_b = object(), object()
        session.viewer_input(tab_a, "\x1b[12;1R")  # Nobody owns it yet: dropped.
        session.viewer_input(tab_a, "hi")           # Typing makes tab A the owner.
        session.viewer_input(tab_b, "\x1b[12;1R")  # Tab B's answer: dropped.
        session.viewer_input(tab_a, "\x1b[5;1R")
        session.status, session.proc = "stopped", None
        session.viewer_resize(tab_b, 30, 100)        # Resizing hands ownership to B.
        session.viewer_input(tab_b, "\x1b[7;1R")
        self.assertEqual(written, ["hi", "\x1b[5;1R", "\x1b[7;1R"])
        session.loop.close()

    def test_bracketed_paste_once_the_program_asks_for_it(self):
        import asyncio as _asyncio
        from host.sessions import Session

        session = Session("alice", _asyncio.new_event_loop(), "claude")
        self.assertEqual(session.pasted("one line"), "one line")
        self.assertEqual(session.pasted("a\nb"), "\x1b[200~a\rb\x1b[201~")
        session.stream.feed("\x1b[?2004h")  # Claude Code and Antigravity both send this.
        self.assertEqual(session.pasted("one line"), "\x1b[200~one line\x1b[201~")
        session.stream.feed("\x1b[?2004l")
        self.assertEqual(session.pasted("one line"), "one line")
        session.loop.close()


class NoticeTest(unittest.TestCase):
    def test_single_line_without_control_characters(self):
        text = notice([dict(sender="bob", subject="evil\r\nrm -rf /\x1b[2J", importance="normal")])
        self.assertNotRegex(text, r"[\x00-\x1f]")
        self.assertIn("from bob", text)
        self.assertIn("fetch_inbox", text)

    def test_several_messages_name_each_sender_once(self):
        rows = [dict(sender=s, subject="x", importance="normal") for s in ("bob", "carol", "bob")]
        self.assertIn("3 new messages (from bob, carol)", notice(rows))

    def test_importance(self):
        self.assertIn("[urgent]", notice([dict(sender="a", subject="s", importance="urgent")]))


class FakeSession:
    def __init__(self, name, now):
        self.name, self.status, self.injecting = name, "running", False
        self.activity, self.idle_since = "idle", now - 10
        self.last_output, self.last_input = now - 10, 0.0
        self.written: list[str] = []

    def refresh(self, now):
        return self.activity

    def notified(self, now):
        self.activity, self.idle_since = "busy", None

    def write(self, data, *, user=True):
        assert not user
        self.written.append(data)

    def pasted(self, text):
        return text


class FakeManager:
    def __init__(self, hub):
        self.hub, self.sessions, self.queued, self.paused, self.waiting = hub, {}, {}, set(), {}


class DispatcherTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hub = Hub(Path(self.tmp.name) / "hub.db")
        for name in ("alice", "bob"):
            self.hub.register(name)
        self.manager = FakeManager(self.hub)
        self.dispatcher = Dispatcher(self.manager, enter_delay=0)
        self.now = 1_000_000.0
        self.bob = self.manager.sessions["bob"] = FakeSession("bob", self.now)

    async def asyncTearDown(self):
        self.hub.close()
        self.tmp.cleanup()

    async def drain(self):
        await asyncio.gather(*self.dispatcher.tasks)

    async def test_idle_recipient_is_woken_once(self):
        self.hub.send("alice", "bob", "hello", "body")
        self.assertEqual(self.dispatcher.tick(self.now), ["bob"])
        await self.drain()
        self.assertEqual(len(self.bob.written), 2)
        self.assertIn('from alice: "hello"', self.bob.written[0])
        self.assertEqual(self.bob.written[1], "\r")
        self.assertEqual(self.hub.pending_notifications(), [])
        self.bob.activity, self.bob.idle_since = "idle", self.now
        self.assertEqual(self.dispatcher.tick(self.now + 5), [])  # Already told.

    async def test_waits_while_busy_in_a_dialog_or_just_idle(self):
        self.hub.send("alice", "bob", "hello", "body")
        for activity_state in ("busy", "attention", "starting"):
            self.bob.activity = activity_state
            self.assertEqual(self.dispatcher.tick(self.now), [])
        self.bob.activity, self.bob.idle_since = "idle", self.now - 0.5
        self.assertEqual(self.dispatcher.tick(self.now), [])  # Not settled yet.
        self.assertEqual(self.manager.queued, {"bob": 1})
        self.bob.idle_since = self.now - 5
        self.assertEqual(self.dispatcher.tick(self.now), ["bob"])

    async def test_never_appends_to_a_persons_draft(self):
        self.hub.send("alice", "bob", "hello", "body")
        self.bob.last_input = self.bob.idle_since + 1  # Someone typed after it went idle.
        self.assertEqual(self.dispatcher.tick(self.now), [])
        self.assertEqual(self.bob.written, [])
        self.assertEqual(self.manager.waiting, {"bob": "you typed in this terminal"})

    async def test_recipient_without_a_terminal_keeps_its_mail(self):
        self.hub.send("bob", "alice", "hello", "body")
        self.assertEqual(self.dispatcher.tick(self.now), [])
        self.assertEqual(len(self.hub.pending_notifications()), 1)

    async def test_lost_notice_is_repeated_a_few_times(self):
        # Antigravity can drop a notice ("empty conversation id") and leave the mail unread.
        start = time.time()  # notified_ts is stamped with the real clock.
        self.hub.send("alice", "bob", "hello", "body")
        self.bob.idle_since = self.bob.last_output = start - 10
        self.assertEqual(self.dispatcher.tick(start), ["bob"])
        await self.drain()
        self.assertIn("New mail", self.bob.written[0])
        self.bob.activity, self.bob.idle_since = "idle", start + 20
        self.assertEqual(self.dispatcher.tick(start + 30), [])  # Too soon to repeat.
        for attempt in (1, 2):
            later = start + 100 * attempt
            self.bob.activity, self.bob.idle_since = "idle", later - 10
            self.assertEqual(self.dispatcher.tick(later), ["bob"])
            await self.drain()
            self.assertIn('Unread mail from alice: "hello"', self.bob.written[-2])
        self.bob.activity, self.bob.idle_since = "idle", start + 290
        self.assertEqual(self.dispatcher.tick(start + 300), [])  # Gave up; it stays unread.
        self.hub.inbox("bob")
        self.assertEqual(self.hub.pending_notifications(renotify_before="9999"), [])

    async def test_wake_budget_pauses_runaway_agents(self):
        dispatcher = Dispatcher(self.manager, enter_delay=0, budget=2, window=60)
        for i in range(3):
            self.hub.send("alice", "bob", f"m{i}", "b")
            self.bob.activity, self.bob.idle_since = "idle", self.now + i * 10 - 5
            woken = dispatcher.tick(self.now + i * 10)
            await asyncio.gather(*dispatcher.tasks)
            self.assertEqual(woken, ["bob"] if i < 2 else [])
        self.assertIn("bob", self.manager.paused)
        self.bob.activity, self.bob.idle_since = "idle", self.now + 100
        self.assertEqual(dispatcher.tick(self.now + 120), ["bob"])  # Window passed.
        self.assertNotIn("bob", self.manager.paused)


# A stand-in Antigravity: draws its idle footer, turns busy on a line.
AGENT = r"""
import sys, time
def idle():
    print('-' * 40); print('> '); print('-' * 40); print('? for shortcuts', flush=True)
idle()
for line in sys.stdin:
    print('esc to cancel', flush=True)
    time.sleep(0.5)
    print('GOT ' + line.strip(), flush=True)
    idle()
"""


@unittest.skipUnless(sys.platform == "win32" and winpty is not None, "needs Windows and pywinpty")
class WakeOverConPtyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from host.server import make_app

        self.tmp = tempfile.TemporaryDirectory()
        self.old_state = os.environ.get("ORRERY_WIN_STATE")
        os.environ["ORRERY_WIN_STATE"] = self.tmp.name
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.db = str(Path(self.tmp.name) / "hub.db")

        def builder(program, name, **kwargs):
            return programs.Launch(argv=[sys.executable, "-u", "-c", AGENT], env=dict(os.environ))

        app = make_app(self.port, self.db, builder=builder, check_agy=False,
                       dispatcher=dict(interval=0.2, settle=0.5, enter_delay=0.2))
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        await web.TCPSite(self.runner, "127.0.0.1", self.port).start()
        self.http = aiohttp.ClientSession(headers={"X-Orrery": "1"})

    async def asyncTearDown(self):
        await self.http.close()
        await self.runner.cleanup()
        if self.old_state is None:
            os.environ.pop("ORRERY_WIN_STATE", None)
        else:
            os.environ["ORRERY_WIN_STATE"] = self.old_state
        self.tmp.cleanup()

    async def state(self):
        async with self.http.get(self.base + "/api/state") as response:
            return {a["name"]: a for a in (await response.json())["agents"]}

    async def wait_for(self, predicate, timeout=15):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            value = await predicate()
            if value:
                return value
            await asyncio.sleep(0.2)
        self.fail("condition not reached")

    async def test_mail_wakes_an_idle_agent(self):
        async with self.http.post(self.base + "/api/agents", json=dict(
                name="bob", program="agy", cwd=self.tmp.name, rows=24, cols=100)) as response:
            self.assertEqual(response.status, 200, await response.text())

        async def idle():
            return (await self.state())["bob"]["activity"] == "idle"
        await self.wait_for(idle)

        hub = Hub(self.db)
        try:
            hub.register("me", program="human")
            hub.send("me", "bob", "status?", "How is it going?")
        finally:
            hub.close()

        async with self.http.ws_connect(self.base + "/ws/bob") as ws:
            seen = ""
            deadline = asyncio.get_running_loop().time() + 15
            while 'GOT [ORRERY] New mail from me: "status?"' not in seen:
                remaining = deadline - asyncio.get_running_loop().time()
                self.assertGreater(remaining, 0, seen[-400:])
                message = await ws.receive_json(timeout=remaining)
                if message["type"] == "output":
                    seen += message["data"]

        async def told():
            agent = (await self.state())["bob"]
            return agent["queued"] == 0 and agent["unread"] == 1
        await self.wait_for(told)


if __name__ == "__main__":
    unittest.main()
