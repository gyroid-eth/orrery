"""An action relayed to the dashboard is not cut off as a poll is (2026-10-02).

At the 162nd seminar (2026-10-01, load 40-50) a bulk EXIT in the NETWORK view
showed "Exited 0, failed 1". The embedded dashboard's POST /api/exit goes
through the cockpit's passthrough, whose shared session gives up after 6 s and
answered "dashboard offline" — while the dashboard went on and sent the exit.
Reproduced with a dashboard that takes 8 s: 502 after 6.8 s, exit sent.

A POST through the passthrough now has ACTION_PROXY_TIMEOUT, and running out
of it says the action may still go through. GETs keep the poll's limit.

Run from bridge/: ``python -m pytest tests/test_proxy_actions.py``.
"""
from __future__ import annotations

import asyncio
import json
import re
import socket
import sys
from pathlib import Path

import pytest

from aiohttp import ClientSession, ClientTimeout, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orrery_backend as ob  # noqa: E402

POLL_TIMEOUT = 0.3   # stands in for the shared session's 6 s


async def _start(app: web.Application) -> tuple[web.AppRunner, str]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


def _relay(method: str, path: str, *, delay: float = 0.0, action_timeout: float = 2.0,
           dashboard: bool = True, monkeypatch=None, answer: str = "json"):
    """Send one request through the real passthrough to a dashboard that takes
    `delay` seconds. Returns (status, body, what the dashboard received)."""
    received: list[tuple[str, str, dict]] = []

    async def main():
        async def handle(request):
            body = await request.json() if request.method == "POST" else {}
            await asyncio.sleep(delay)
            received.append((request.method, request.path, body))
            if answer == "close":      # took the action, then dropped the line
                request.transport.close()
                await asyncio.sleep(0.5)
            if answer == "short":      # began the answer, then dropped the line
                response = web.StreamResponse(headers={"Content-Type": "application/json"})
                response.content_length = 100
                await response.prepare(request)
                await response.write(b'{"ok": tr')
                request.transport.close()
                await asyncio.sleep(0.5)
                return response
            return web.json_response({"ok": True, "session": body.get("session")})

        upstream = web.Application()
        upstream.router.add_route("*", "/{tail:.*}", handle)
        up_runner, up_url = await _start(upstream)
        if not dashboard:
            await up_runner.cleanup()
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                up_url = f"http://127.0.0.1:{s.getsockname()[1]}"
        monkeypatch.setattr(ob, "DASHBOARD_URL", up_url)
        monkeypatch.setattr(ob, "ACTION_PROXY_TIMEOUT", action_timeout)
        backend = web.Application()
        backend[ob.HTTP_SESSION_KEY] = ClientSession(timeout=ClientTimeout(total=POLL_TIMEOUT))
        backend.router.add_route("*", "/api/{tail:.*}", ob.proxy_dashboard_passthrough)
        runner, url = await _start(backend)
        try:
            async with ClientSession() as client:
                kwargs = {"json": {"session": "AquaFermi"}} if method == "POST" else {}
                async with client.request(method, url + path, **kwargs) as response:
                    return response.status, json.loads(await response.read())
        finally:
            await runner.cleanup()
            await backend[ob.HTTP_SESSION_KEY].close()
            if dashboard:
                await asyncio.sleep(max(0.0, delay - POLL_TIMEOUT) + 0.1)
                await up_runner.cleanup()

    status, body = asyncio.run(main())
    return status, body, received


def test_an_exit_slower_than_a_poll_is_answered(monkeypatch):
    """The seminar's case: slower than the poll limit, well inside the action's."""
    status, body, received = _relay("POST", "/api/exit", delay=1.0, monkeypatch=monkeypatch)
    assert (status, body) == (200, {"ok": True, "session": "AquaFermi"})
    assert received == [("POST", "/api/exit", {"session": "AquaFermi"})]


UNKNOWN = "the action may still go through — check the agent before trying again"


def test_an_exit_past_the_action_limit_may_still_go_through(monkeypatch):
    status, body, received = _relay("POST", "/api/exit", delay=1.0, action_timeout=0.3,
                                    monkeypatch=monkeypatch)
    assert status == 504
    assert body == {"ok": False,
                    "error": f"the dashboard did not answer within 0.3 s; {UNKNOWN}"}
    # A timeout is not a cancel: the dashboard went on and acted.
    assert received == [("POST", "/api/exit", {"session": "AquaFermi"})]


@pytest.mark.parametrize("answer", ["close", "short"])
def test_an_answer_lost_after_the_action_was_received_is_not_offline(monkeypatch, answer):
    """Review of #11 (P2-1): the dashboard had the exit, then the connection
    closed (or the answer was cut short). That is not "offline"."""
    status, body, received = _relay("POST", "/api/exit", answer=answer, monkeypatch=monkeypatch)
    assert status == 502
    assert body == {"ok": False, "error": f"the dashboard's answer was lost; {UNKNOWN}"}
    assert received == [("POST", "/api/exit", {"session": "AquaFermi"})]


def test_an_exit_with_no_dashboard_is_offline(monkeypatch):
    status, body, _ = _relay("POST", "/api/exit", dashboard=False, monkeypatch=monkeypatch)
    assert (status, body) == (502, {"ok": False, "error": "dashboard offline"})


def test_a_get_keeps_the_poll_limit(monkeypatch):
    status, body, _ = _relay("GET", "/api/graph", delay=1.0, monkeypatch=monkeypatch)
    assert (status, body) == (502, {"error": "dashboard offline"})


def test_the_cockpit_bulk_exit_toast_carries_the_first_reason():
    html = (Path(__file__).resolve().parents[1] / "cockpit.html").read_text(encoding="utf-8")
    start = html.index("async function runBulkExit(){")
    body = html[start : html.index("\n}\n", start)]
    assert "${failures[0]}" in body
