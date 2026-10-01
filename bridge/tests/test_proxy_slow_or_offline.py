"""The backend tells a slow dashboard from one that is not there (2026-10-01).

Both are a 502 to the cockpit, which keeps its last roster either way; the body
says which, so a dashboard that only took longer than 6 s is shown as slow and
nobody is sent to restart it. Run from bridge/:
``python -m pytest tests/test_proxy_slow_or_offline.py``.
"""
from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orrery_backend as ob  # noqa: E402


async def start(app: web.Application) -> tuple[web.AppRunner, str]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


def ask(dashboard_url: str, path: str, upstream_timeout: float) -> tuple[int, object]:
    async def main():
        old, ob.DASHBOARD_URL = ob.DASHBOARD_URL, dashboard_url
        ob._annotations_cache = (0.0, {})
        backend = web.Application()
        backend[ob.HTTP_SESSION_KEY] = ClientSession(timeout=ClientTimeout(total=upstream_timeout))
        for route in ob.PROXY_ROUTES:
            backend.router.add_get(route, ob.proxy_dashboard)
        runner, url = await start(backend)
        try:
            async with ClientSession() as client, client.get(url + path) as response:
                return response.status, json.loads(await response.read())
        finally:
            await runner.cleanup()
            await backend[ob.HTTP_SESSION_KEY].close()
            ob.DASHBOARD_URL = old
    return asyncio.run(main())


def with_dashboard(delay: float, path: str, upstream_timeout: float):
    async def main():
        async def handle(_request):
            await asyncio.sleep(delay)
            return web.json_response({"agents": []})
        app = web.Application()
        app.router.add_route("GET", "/{tail:.*}", handle)
        runner, url = await start(app)
        try:
            return await asyncio.to_thread(ask, url, path, upstream_timeout)
        finally:
            await runner.cleanup()
    return asyncio.run(main())


def test_a_dashboard_that_answers_in_time_is_passed_through():
    assert with_dashboard(0.0, "/telemetry/agents", 2) == (200, {"agents": []})


def test_a_dashboard_that_takes_too_long_is_slow():
    assert with_dashboard(1.0, "/telemetry/agents", 0.3) == (502, {"error": "dashboard slow"})


def test_no_dashboard_at_all_is_offline():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]   # free, and nothing listens once closed
    assert ask(f"http://127.0.0.1:{port}", "/telemetry/graph?all=1", 2) == (502, {"error": "dashboard offline"})
