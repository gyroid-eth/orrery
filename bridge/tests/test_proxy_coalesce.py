"""The backend shares one dashboard request among identical polls (2026-10-01).

Every cockpit tab and pane window polls /telemetry/agents, /telemetry/graph and
/telemetry/messages. While one of these is on its way to the dashboard, the
same request from another tab now waits for that answer instead of starting a
second computation. Nothing is cached: once the answer is in, the next request
goes to the dashboard again.

These run proxy_dashboard against a fake dashboard on a free local port.
Run from bridge/: ``python -m pytest tests/test_proxy_coalesce.py``.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orrery_backend as ob  # noqa: E402

GRAPH = {"spawn": [{"source": "Mom", "target": "Kid"}], "nodes": 2}
AGENTS = {"agents": [{"name": "Kid", "running": True}, {"name": "Mom", "running": False}]}


class FakeDashboard:
    """Answers after `delay` seconds and counts what it was asked."""

    def __init__(self, delay: float = 0.3, status: int = 200):
        self.delay, self.status, self.asked = delay, status, []

    async def handle(self, request: web.Request) -> web.Response:
        self.asked.append(request.path_qs)
        await asyncio.sleep(self.delay)
        if request.path == "/api/annotations":
            return web.json_response({"annotations": {"Kid": {"role": "reader"}}})
        if self.status != 200:
            return web.json_response({"error": "busy"}, status=self.status)
        if request.path == "/api/graph":
            return web.json_response(GRAPH)
        if request.path == "/api/agents":
            return web.json_response(AGENTS)
        return web.json_response({"ok": True, "now": 1, "messages": [], "asked": request.path_qs})

    def asked_for(self, path: str) -> int:
        return sum(1 for p in self.asked if p.split("?")[0] == path)


async def start(app: web.Application, **options) -> tuple[web.AppRunner, str]:
    runner = web.AppRunner(app, **options)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


def run(scenario, dashboard: FakeDashboard, upstream_timeout: float = 6):
    async def main():
        upstream = web.Application()
        upstream.router.add_route("GET", "/{tail:.*}", dashboard.handle)
        up_runner, up_url = await start(upstream)
        old_url, ob.DASHBOARD_URL = ob.DASHBOARD_URL, up_url
        ob._annotations_cache = (0.0, {})
        backend = web.Application()
        backend[ob.HTTP_SESSION_KEY] = ClientSession(timeout=ClientTimeout(total=upstream_timeout))
        backend[ob.PROXY_INFLIGHT_KEY] = {}
        for path in ob.PROXY_ROUTES:
            backend.router.add_get(path, ob.proxy_dashboard)
        # cancel a handler when its client goes, as some aiohttp setups do, so
        # a tab that leaves would take the shared request with it if unshielded
        runner, url = await start(backend, handler_cancellation=True)
        try:
            async with ClientSession() as client:
                async def get(path: str) -> tuple[int, object]:
                    async with client.get(url + path) as response:
                        return response.status, json.loads(await response.read())
                return await scenario(get, client, url, backend)
        finally:
            await runner.cleanup()
            await backend[ob.HTTP_SESSION_KEY].close()
            await up_runner.cleanup()
            ob.DASHBOARD_URL = old_url
    return asyncio.run(main())


# ---------------------------------------------------------------- positive

def test_tabs_asking_at_the_same_time_share_one_dashboard_request():
    dash = FakeDashboard()

    async def scenario(get, *_):
        return await asyncio.gather(*(get("/telemetry/graph?all=1&spawn_only=1") for _ in range(4)))
    answers = run(scenario, dash)
    assert answers == [(200, GRAPH)] * 4
    assert dash.asked == ["/api/graph?all=1&spawn_only=1"]


def test_a_tab_that_asks_while_the_answer_is_on_its_way_gets_it_too():
    dash = FakeDashboard(delay=0.4)

    async def scenario(get, *_):
        first = asyncio.ensure_future(get("/telemetry/agents"))
        await asyncio.sleep(0.2)
        return [await get("/telemetry/agents"), await first]
    second, first = run(scenario, dash)
    assert first == second
    assert dash.asked_for("/api/agents") == 1


def test_the_shared_answer_is_the_same_as_an_unshared_one():
    """Same payload, annotations merged in, as before the change."""
    dash = FakeDashboard(delay=0.05)

    async def scenario(get, client, url, backend):
        shared = await asyncio.gather(get("/telemetry/agents"), get("/telemetry/agents"))
        ob._annotations_cache = (0.0, {})
        direct = await ob.fetch_proxied(backend[ob.HTTP_SESSION_KEY], "/telemetry/agents",
                                        ob.DASHBOARD_URL + "/api/agents")
        return shared, json.loads(direct[0])
    shared, direct = run(scenario, dash)
    assert shared[0] == shared[1] == (200, direct)
    assert direct["agents"][0]["annot"]["role"] == "reader"


def test_a_tab_closing_mid_request_does_not_cancel_the_others():
    dash = FakeDashboard(delay=0.5)

    async def scenario(get, *_):
        leaving = asyncio.ensure_future(get("/telemetry/graph?all=1&spawn_only=1"))
        await asyncio.sleep(0.1)
        staying = asyncio.ensure_future(get("/telemetry/graph?all=1&spawn_only=1"))
        await asyncio.sleep(0.1)
        leaving.cancel()
        return await staying
    assert run(scenario, dash) == (200, GRAPH)
    assert dash.asked_for("/api/graph") == 1


# ---------------------------------------------------------------- negative

def test_nothing_is_kept_once_the_answer_is_in():
    """The next poll asks the dashboard again: no value older than before."""
    dash = FakeDashboard(delay=0.05)

    async def scenario(get, client, url, backend):
        await get("/telemetry/graph?all=1&spawn_only=1")
        await get("/telemetry/graph?all=1&spawn_only=1")
        return dict(backend[ob.PROXY_INFLIGHT_KEY])
    assert run(scenario, dash) == {}
    assert dash.asked_for("/api/graph") == 2


def test_different_queries_are_not_shared():
    dash = FakeDashboard()

    async def scenario(get, *_):
        return await asyncio.gather(get("/telemetry/messages?since=10&limit=40"),
                                    get("/telemetry/messages?since=20&limit=40"))
    a, b = run(scenario, dash)
    assert a[1]["asked"] == "/api/messages-since?since=10&limit=40"
    assert b[1]["asked"] == "/api/messages-since?since=20&limit=40"
    assert dash.asked_for("/api/messages-since") == 2


def test_routes_that_are_not_polled_are_not_shared():
    dash = FakeDashboard()

    async def scenario(get, *_):
        return await asyncio.gather(get("/telemetry/spawn-status?name=Kid"),
                                    get("/telemetry/spawn-status?name=Kid"))
    run(scenario, dash)
    assert dash.asked_for("/api/spawn-status") == 2


def test_a_dashboard_that_times_out_gives_every_waiting_tab_a_502_and_is_asked_again_next():
    dash = FakeDashboard(delay=0.6)

    async def scenario(get, client, url, backend):
        both = await asyncio.gather(get("/telemetry/agents"), get("/telemetry/agents"))
        left = dict(backend[ob.PROXY_INFLIGHT_KEY])
        dash.delay = 0
        return both, left, await get("/telemetry/agents")
    both, left, after = run(scenario, dash, upstream_timeout=0.3)
    assert both == [(502, {"error": "dashboard slow"})] * 2
    assert left == {}
    assert after[0] == 200
    assert dash.asked_for("/api/agents") == 2


def test_an_error_status_is_passed_on_to_every_waiting_tab():
    dash = FakeDashboard(status=503)

    async def scenario(get, *_):
        return await asyncio.gather(get("/telemetry/graph?all=1"), get("/telemetry/graph?all=1"))
    assert run(scenario, dash) == [(503, {"error": "busy"})] * 2
    assert dash.asked_for("/api/graph") == 1
