"""Only the cockpit's own loopback page may use the backend (2026-10-26).

A page from any site could open ws://127.0.0.1:8791/ws and send keys into a
pane, and a DNS-rebound name could read /telemetry/fs/dirs. These run the real
app on a private port with a fake tmux boundary and send the headers a browser
would send in each case. No live tmux, agent or pane is touched.

Run from bridge/: ``python -m pytest tests/test_own_page_guard.py``.
"""
import asyncio
from pathlib import Path
import sys

import pytest

BRIDGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRIDGE))

WS = {"Connection": "Upgrade", "Upgrade": "websocket", "Sec-WebSocket-Version": "13",
      "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="}


def run_cases(tmp_path, monkeypatch, cases):
    import orrery_backend as ob
    from aiohttp import ClientSession, web

    class Boundary:
        shared = None
        transport = None
        home = tmp_path

    monkeypatch.setattr(ob, "LegacyTargetBoundary", Boundary)
    # The guard runs before any handler; stand-ins keep tmux and the dashboard out.
    async def ok(request):
        return web.json_response({"ok": True})
    monkeypatch.setattr(ob, "websocket_handler", ok)
    monkeypatch.setattr(ob, "serve_fs_dirs", ok)
    monkeypatch.setattr(ob, "serve_clipboard_files", ok)

    async def scenario():
        app = ob.create_app(Boundary())
        app.cleanup_ctx.clear()
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        results = []
        try:
            async with ClientSession(auto_decompress=False) as client:
                for path, headers in cases(port):
                    async with client.get(f"http://127.0.0.1:{port}{path}", headers=headers) as response:
                        results.append(response.status)
        finally:
            await runner.cleanup()
        return results

    return asyncio.run(scenario())


def test_foreign_pages_cannot_open_the_pane_socket(tmp_path, monkeypatch):
    statuses = run_cases(tmp_path, monkeypatch, lambda port: [
        ("/ws", {**WS, "Origin": "https://evil.example"}),
        ("/ws", {**WS, "Origin": "null"}),
        ("/ws", {**WS, "Host": f"evil.example:{port}", "Origin": f"http://evil.example:{port}"}),
        ("/ws", {**WS, "Origin": f"http://127.0.0.1:{port + 1}"}),
    ])
    assert statuses == [403, 403, 403, 403]


def test_own_page_and_local_processes_keep_the_pane_socket(tmp_path, monkeypatch):
    statuses = run_cases(tmp_path, monkeypatch, lambda port: [
        ("/ws", {**WS, "Origin": f"http://127.0.0.1:{port}"}),
        ("/ws", {**WS, "Origin": f"http://localhost:{port}", "Host": f"localhost:{port}"}),
        ("/ws", dict(WS)),
    ])
    assert statuses == [200, 200, 200]


@pytest.mark.parametrize("path", ["/telemetry/fs/dirs?path=/", "/telemetry/clipboard/files"])
def test_foreign_pages_cannot_read_local_files(tmp_path, monkeypatch, path):
    statuses = run_cases(tmp_path, monkeypatch, lambda port: [
        (path, {"Origin": "https://evil.example"}),
        (path, {"Host": f"evil.example:{port}"}),
        (path, {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "no-cors"}),
        (path, {"Origin": f"http://127.0.0.1:{port}", "Sec-Fetch-Site": "same-origin"}),
    ])
    assert statuses == [403, 403, 403, 200]


def test_a_link_from_elsewhere_still_opens_the_cockpit(tmp_path, monkeypatch):
    statuses = run_cases(tmp_path, monkeypatch, lambda port: [
        ("/cockpit.html", {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Mode": "navigate"}),
    ])
    assert statuses == [200]
