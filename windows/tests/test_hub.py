"""hub.db and the MCP server, without any agent CLI.

    python -m pytest windows/tests -q
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

WINDOWS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS))
from hub.db import Hub, HubError  # noqa: E402

SERVER = WINDOWS / "hub" / "mcp_server.py"


class HubTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "hub.db"
        self.hub = Hub(self.path)
        self.hub.register("alice", program="claude")
        self.hub.register("bob", program="agy")

    def tearDown(self):
        self.hub.close()
        self.tmp.cleanup()

    def test_send_and_inbox_marks_read(self):
        sent = self.hub.send("alice", "bob", "hello", "body text")
        self.assertEqual(sent["to"], ["bob"])
        self.assertEqual(sent["thread_id"], str(sent["id"]))
        messages = self.hub.inbox("bob")
        self.assertEqual([m["subject"] for m in messages], ["hello"])
        self.assertEqual(messages[0]["sender"], "alice")
        self.assertEqual(self.hub.inbox("bob"), [])
        self.assertEqual(len(self.hub.inbox("bob", unread_only=False)), 1)
        self.assertEqual(self.hub.inbox("alice"), [])

    def test_peek_keeps_unread(self):
        self.hub.send("alice", ["bob"], "s", "b")
        self.assertEqual(len(self.hub.inbox("bob", mark_read=False)), 1)
        self.assertEqual(len(self.hub.inbox("bob")), 1)

    def test_names_are_case_insensitive_addresses(self):
        self.hub.send("alice", "BOB", "s", "b")
        self.assertEqual(len(self.hub.inbox("Bob")), 1)

    def test_unknown_recipient_names_the_known_agents(self):
        with self.assertRaises(HubError) as caught:
            self.hub.send("alice", ["bob", "carol"], "s", "b")
        self.assertIn("carol", str(caught.exception))
        self.assertIn("alice, bob", str(caught.exception))
        self.assertEqual(self.hub.inbox("bob"), [])  # Nothing half-sent.

    def test_rejects_bad_input(self):
        bad = [
            ("alice", [], "s", "b", {}),
            ("alice", "9bad", "s", "b", {}),
            ("alice", "bob", " ", "b", {}),
            ("alice", "bob", "s", None, {}),
            ("alice", "bob", "s", "b", dict(importance="max")),
            ("nobody", "bob", "s", "b", {}),
        ]
        for sender, to, subject, body, kwargs in bad:
            with self.subTest(sender=sender, to=to, subject=subject, kwargs=kwargs):
                with self.assertRaises(HubError):
                    self.hub.send(sender, to, subject, body, **kwargs)

    def test_reply_keeps_thread(self):
        first = self.hub.send("alice", "bob", "q", "question")
        reply = self.hub.send("bob", "alice", "re: q", "answer", reply_to=first["id"])
        self.assertEqual(reply["thread_id"], first["thread_id"])
        self.assertEqual([m["body"] for m in self.hub.thread(first["thread_id"])], ["question", "answer"])
        with self.assertRaises(HubError):
            self.hub.send("bob", "alice", "s", "b", reply_to=9999)

    def test_pending_notifications(self):
        sent = self.hub.send("alice", ["bob", "alice"], "s", "b")
        pending = {p["recipient"] for p in self.hub.pending_notifications()}
        self.assertEqual(pending, {"alice", "bob"})
        self.hub.mark_notified(sent["id"], "bob")
        self.assertEqual([p["recipient"] for p in self.hub.pending_notifications()], ["alice"])
        self.hub.inbox("alice")  # Read mail needs no notification.
        self.assertEqual(self.hub.pending_notifications(), [])

    def test_board(self):
        self.hub.board_write("alice", "plan", "step 1")
        self.hub.board_write("bob", "plan", "step 2")
        self.hub.board_write("bob", "notes", "n")
        self.assertEqual([p["text"] for p in self.hub.board_read("plan")], ["step 1", "step 2"])
        self.assertEqual([p["author"] for p in self.hub.board_read("plan", limit=1)], ["bob"])
        topics = {t["topic"]: t["posts"] for t in self.hub.board_read()}
        self.assertEqual(topics, {"plan": 2, "notes": 1})
        with self.assertRaises(HubError):
            self.hub.board_write("alice", "", "x")

    def test_concurrent_writers_share_the_file(self):
        errors = []

        def writer(name):
            hub = Hub(self.path)
            try:
                hub.register(name)
                for i in range(25):
                    hub.send(name, "bob", f"{name} {i}", "b")
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)
            finally:
                hub.close()

        threads = [threading.Thread(target=writer, args=(f"w{n}",)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.hub.inbox("bob", limit=100)), 100)


class McpServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "hub.db")
        self.procs = []

    def tearDown(self):
        for proc in self.procs:
            proc.stdin.close()
            proc.wait(timeout=10)
            proc.stdout.close()
        self.tmp.cleanup()

    def start(self, *args, env=None):
        # An agent the host started has ORRERY_AGENT set; the server must not inherit it here.
        env = {k: v for k, v in os.environ.items() if k != "ORRERY_AGENT"} if env is None else env
        proc = subprocess.Popen([sys.executable, str(SERVER), "--db", self.db, *args],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=self.tmp.name,
                                env=env)
        self.procs.append(proc)
        return proc

    def rpc(self, proc, method, params=None, rid=1):
        proc.stdin.write(json.dumps(dict(jsonrpc="2.0", id=rid, method=method,
                                         params=params or {})).encode() + b"\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    def init(self, proc, client="claude-code"):
        reply = self.rpc(proc, "initialize", dict(protocolVersion="2025-06-18",
                                                  clientInfo=dict(name=client), capabilities={}))
        proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        return reply["result"]

    def tool(self, proc, name, **arguments):
        reply = self.rpc(proc, "tools/call", dict(name=name, arguments=arguments), rid=7)
        result = reply["result"]
        return result["content"][0]["text"], result["isError"]

    def test_two_agents_exchange_mail(self):
        alice, bob = self.start("--agent", "alice"), self.start("--agent", "bob")
        info = self.init(alice)
        self.assertEqual(info["protocolVersion"], "2025-06-18")
        self.assertIn("'alice'", info["instructions"])
        self.init(bob, client="antigravity")
        names = {t["name"] for t in self.rpc(alice, "tools/list")["result"]["tools"]}
        self.assertEqual(names, {"send_message", "fetch_inbox", "read_thread", "list_agents",
                                 "board_write", "board_read"})
        text, failed = self.tool(alice, "send_message", to="bob", subject="ping", body="日本語も通る")
        self.assertFalse(failed, text)
        text, failed = self.tool(bob, "fetch_inbox")
        self.assertFalse(failed)
        self.assertIn("from: alice", text)
        self.assertIn("日本語も通る", text)
        text, _ = self.tool(bob, "list_agents")
        self.assertIn("bob (you) · agy", text)

    def test_errors_are_tool_results_not_crashes(self):
        alice = self.start("--agent", "alice")
        self.init(alice)
        text, failed = self.tool(alice, "send_message", to=["ghost"], subject="s", body="b")
        self.assertTrue(failed)
        self.assertIn("unknown recipient", text)
        reply = self.rpc(alice, "no/such/method")
        self.assertEqual(reply["error"]["code"], -32601)
        text, failed = self.tool(alice, "list_agents")  # Still serving.
        self.assertFalse(failed)

    def test_fallback_name_from_cwd_and_client(self):
        proc = self.start()
        info = self.init(proc, client="claude-code")
        self.assertRegex(info["instructions"], r"You are '[A-Za-z][\w.-]*-claude'")


if __name__ == "__main__":
    unittest.main()
