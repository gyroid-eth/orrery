"""The host: request guard, roster, and a real ConPTY terminal over WebSocket.

A stand-in Python program plays the agent, so no agent CLI is started.
Windows only (ConPTY via pywinpty).
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

WINDOWS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS))

try:
    import winpty  # noqa: F401
    import aiohttp
    from aiohttp import web
except ImportError:  # pragma: no cover
    winpty = None

from host import programs  # noqa: E402

ECHO = ("import sys\nprint('READY', flush=True)\n"
        "for line in sys.stdin:\n    print('GOT ' + line.strip().upper(), flush=True)\n")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(sys.platform == "win32" and winpty is not None, "needs Windows and pywinpty")
class HostTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from host.server import make_app

        self.tmp = tempfile.TemporaryDirectory()
        self.old_state = os.environ.get("ORRERY_WIN_STATE")
        os.environ["ORRERY_WIN_STATE"] = self.tmp.name
        self.launches = []

        def builder(program, name, **kwargs):
            self.launches.append((program, name, kwargs))
            return programs.Launch(argv=[sys.executable, "-u", "-c", ECHO], env=dict(os.environ))

        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        app = make_app(self.port, str(Path(self.tmp.name) / "hub.db"), builder=builder, check_agy=False)
        self.app = app
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

    async def post(self, path, body=None, **kwargs):
        async with self.http.post(self.base + path, json=body or {}, **kwargs) as response:
            return response.status, await response.json()

    async def test_guard_rejects_cross_site_requests(self):
        async with aiohttp.ClientSession() as bare:
            async with bare.post(self.base + "/api/agents", json={}) as response:
                self.assertEqual(response.status, 403)  # No X-Orrery header.
        status, _ = await self.post("/api/agents", headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        async with self.http.get(self.base + "/api/state", headers={"Host": "evil.example"}) as response:
            self.assertEqual(response.status, 403)  # DNS rebinding.
        async with self.http.get(self.base + "/api/state",
                                 headers={"Origin": f"http://localhost:{self.port}"}) as response:
            self.assertEqual(response.status, 200)

    async def test_second_start_finds_the_running_host(self):
        from host import server

        loop = asyncio.get_running_loop()
        self.assertEqual(await loop.run_in_executor(None, server.probe, self.port), "orrery")
        self.assertEqual(await loop.run_in_executor(None, server.probe, free_port()), "free")
        other = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        try:
            port = other.sockets[0].getsockname()[1]
            self.assertEqual(await loop.run_in_executor(None, server.probe, port), "other")
        finally:
            other.close()

    async def test_original_graph_module_is_served_and_fed(self):
        """bridge/orrery_view.js loads unchanged and finds the /telemetry/ paths it reads."""
        from host.server import MANAGER

        for name in ("orrery_view.js", "orrery_view.css"):
            async with self.http.get(f"{self.base}/bridge/{name}") as response:
                self.assertEqual(response.status, 200, name)
        # Only those two: bridge/ also holds the macOS backend's sources.
        for name in ("orrery_backend.py", "cockpit.html", "..%2Fwindows%2Fhost%2Fserver.py"):
            async with self.http.get(f"{self.base}/bridge/{name}") as response:
                self.assertEqual(response.status, 404, name)
        async with self.http.get(self.base + "/cockpit-assets/anthropic.svg") as response:
            self.assertEqual(response.status, 200)

        for name in ("alice", "bob"):
            status, data = await self.post("/api/agents", dict(
                name=name, program="claude", cwd=self.tmp.name, start=False))
            self.assertEqual(status, 200, data)
        self.app[MANAGER].hub.send("alice", ["bob", "alice"], "hello", "body")
        async with self.http.get(self.base + "/telemetry/mail/recent?limit=40") as response:
            data = await response.json()
        self.assertTrue(data["ok"])
        self.assertGreater(data["now"], 1e12)  # Milliseconds, as orrery_view.js reads it.
        (message,) = data["messages"]
        self.assertEqual((message["sender"], message["subject"]), ("alice", "hello"))
        self.assertEqual(sorted(message["recipients"]), ["alice", "bob"])

        async with self.http.get(self.base + "/telemetry/portrait?v=4&style=pixel&name=alice") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.content_type, "image/png")
        async with self.http.get(self.base + "/telemetry/portrait?name=nobody") as response:
            self.assertEqual(response.status, 404)  # The graph then shows the initial.

    def test_portrait_matches_the_page(self):
        """The host picks the same portrait as portraitFor() in web/app.js (values from node)."""
        from host.server import portrait_index

        for name, small, large in (("tech", 67, 555981), ("Philosophy", 17, 677445),
                                   ("writer", 37, 382594),
                                   ("a-very_long.agent-name-0123456789abcdefghijklmnopqrstuvwxyz",
                                    74, 491843)):
            self.assertEqual((portrait_index(name, 97), portrait_index(name, 1000003)),
                             (small, large), name)

    async def test_create_validates(self):
        status, data = await self.post("/api/agents", dict(name="9bad", program="claude", cwd=self.tmp.name))
        self.assertEqual(status, 400)
        status, data = await self.post("/api/agents", dict(name="a", program="vim", cwd=self.tmp.name))
        self.assertEqual(status, 400)
        status, data = await self.post("/api/agents", dict(name="a", program="claude", cwd="relative"))
        self.assertEqual(status, 400)

    async def test_terminal_round_trip_and_replay(self):
        status, data = await self.post("/api/agents", dict(
            name="echo", program="agy", cwd=self.tmp.name, start=True, rows=24, cols=80))
        self.assertEqual(status, 200, data)
        self.assertEqual(self.launches[0][:2], ("agy", "echo"))

        async with self.http.ws_connect(self.base + "/ws/echo") as ws:
            hello = await ws.receive_json(timeout=10)
            self.assertEqual(hello["type"], "hello")
            await self.read_until(ws, "READY")
            await ws.send_str(json.dumps(dict(type="resize", rows=30, cols=100)))
            await ws.send_str(json.dumps(dict(type="input", data="hello\r")))
            await self.read_until(ws, "GOT HELLO")
            await ws.send_str(json.dumps(dict(type="submit", text="from composer")))
            await self.read_until(ws, "GOT FROM COMPOSER")

        async with self.http.get(self.base + "/api/state") as response:
            state = await response.json()
        (agent,) = state["agents"]
        self.assertEqual((agent["name"], agent["status"]), ("echo", "running"))

        async with self.http.ws_connect(self.base + "/ws/echo") as ws:  # A late viewer.
            await ws.receive_json(timeout=10)
            replay = await ws.receive_json(timeout=10)
            self.assertIn("GOT HELLO", replay["data"])
            status, _ = await self.post("/api/agents/echo/stop")
            self.assertEqual(status, 200)
            while True:
                message = await ws.receive_json(timeout=15)
                if message["type"] == "exit":
                    break

        roster = json.loads((Path(self.tmp.name) / "agents.json").read_text(encoding="utf-8"))
        self.assertEqual(roster[0]["name"], "echo")
        async with self.http.delete(self.base + "/api/agents/echo") as response:
            self.assertEqual(response.status, 200)
        async with self.http.get(self.base + "/api/state") as response:
            self.assertEqual((await response.json())["agents"], [])

    async def read_until(self, ws, needle, timeout=15):
        seen = ""
        deadline = asyncio.get_running_loop().time() + timeout
        while needle not in seen:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                self.fail(f"{needle!r} not seen in {seen[-500:]!r}")
            message = await ws.receive_json(timeout=remaining)
            if message["type"] == "output":
                seen += message["data"]
        return seen


class LauncherTest(unittest.TestCase):
    def test_npm_shim_resolves_to_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "node_modules" / "pkg" / "bin" / "tool.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"")
            shim = Path(tmp) / "tool.cmd"
            shim.write_text('@ECHO off\n"%dp0%\\node_modules\\pkg\\bin\\tool.exe"   %*\n', encoding="utf-8")
            self.assertEqual(Path(programs.resolve_launcher(str(shim))), exe)
            self.assertEqual(programs.resolve_launcher(str(exe)), str(exe))

    def test_parent_session_markers_are_not_inherited(self):
        env = programs.clean_environment({
            "CLAUDECODE": "1", "CLAUDE_CODE_CHILD_SESSION": "1", "CLAUDE_CODE_SESSION_ID": "x",
            "CLAUDE_CODE_MESSAGING_TOKEN": "t", "CLAUDE_CODE_ENTRYPOINT": "claude-vscode",
            "CLAUDE_PID": "1", "CLAUDE_CODE_GIT_BASH_PATH": "C:\\git\\bash.exe",
            "CLAUDE_CODE_USE_BEDROCK": "1", "PATH": "p"})
        self.assertEqual(env, {"CLAUDE_CODE_GIT_BASH_PATH": "C:\\git\\bash.exe",
                               "CLAUDE_CODE_USE_BEDROCK": "1", "PATH": "p"})

    def test_claude_launch_carries_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = {k: os.environ.get(k) for k in ("ORRERY_WIN_STATE", "ORRERY_CLAUDE")}
            os.environ["ORRERY_WIN_STATE"] = tmp
            os.environ["ORRERY_CLAUDE"] = sys.executable
            try:
                launch = programs.build("claude", "alice", resume=True)
            finally:
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
            self.assertEqual(launch.env["ORRERY_AGENT"], "alice")
            self.assertNotIn("--continue", launch.argv)  # Could open someone else's conversation.
            self.assertEqual(launch.argv[launch.argv.index("--session-id") + 1], launch.conversation)
            config = json.loads(Path(launch.argv[launch.argv.index("--mcp-config") + 1]).read_text())
            self.assertEqual(config["mcpServers"]["orrery-hub"]["args"][-2:], ["--agent", "alice"])


if __name__ == "__main__":
    unittest.main()
