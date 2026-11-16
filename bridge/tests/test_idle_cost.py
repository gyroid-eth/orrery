"""What a cockpit that nobody is looking at costs the backend (2026-11-16).

The health check only asks whether the dashboard is alive, so it asks the
small version route, not the half-megabyte roster. The tmux session list is
shared between the connections that ask within the same two seconds.

Run from bridge/: ``python -m pytest tests/test_idle_cost.py``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import orrery_backend as ob  # noqa: E402


def _health_with(asked: list[str], *, fail: bool = False):
    class Reply:
        async def __aenter__(self):
            if fail:
                raise ob.ClientError("down")
            return self

        async def __aexit__(self, *args):
            pass

    class Http:
        def get(self, url, **kwargs):
            asked.append(url)
            return Reply()

    app = ob.create_app("tmux")
    app[ob.HTTP_SESSION_KEY] = Http()
    return asyncio.run(ob.serve_health(SimpleNamespace(app=app)))


def test_health_asks_the_light_version_route_not_the_roster():
    asked: list[str] = []
    data = json.loads(_health_with(asked).body)
    assert asked == [ob.DASHBOARD_URL + "/api/version"]
    assert data["dashboard"] is True and data["backend"] == "ok"


def test_health_still_reports_an_unreachable_dashboard():
    asked: list[str] = []
    data = json.loads(_health_with(asked, fail=True).body)
    assert data["dashboard"] is False


def test_connections_share_one_tmux_session_list(monkeypatch):
    calls: list[str] = []

    def listing(tmux_bin):
        calls.append(tmux_bin)
        return [{"session": "A", "attached": False, "windows": 1, "created": 1}]

    monkeypatch.setattr(ob, "list_tmux_sessions", listing)
    ob._session_list_shared.clear()

    async def scenario():
        first = await asyncio.gather(*(ob.shared_session_list("tmux") for _ in range(5)))
        again = await ob.shared_session_list("tmux")     # right after: still shared
        assert all(item == first[0] for item in first) and again == first[0]
        assert len(calls) == 1
        # an answer older than the share window is not reused
        key = "tmux"
        started, task = ob._session_list_shared[key]
        ob._session_list_shared[key] = (started - ob.SESSION_LIST_SHARE_SECONDS - 1, task)
        await ob.shared_session_list("tmux")
        assert len(calls) == 2

    asyncio.run(scenario())


def test_a_failed_session_list_reaches_every_waiter_and_is_not_kept(monkeypatch):
    calls: list[int] = []

    def listing(tmux_bin):
        calls.append(1)
        raise OSError("tmux gone")

    monkeypatch.setattr(ob, "list_tmux_sessions", listing)
    ob._session_list_shared.clear()

    async def scenario():
        results = await asyncio.gather(
            *(ob.shared_session_list("tmux") for _ in range(3)), return_exceptions=True
        )
        assert all(isinstance(item, OSError) for item in results) and len(calls) == 1
        started, task = ob._session_list_shared["tmux"]
        ob._session_list_shared["tmux"] = (started - ob.SESSION_LIST_SHARE_SECONDS - 1, task)
        monkeypatch.setattr(ob, "list_tmux_sessions", lambda tmux_bin: [])
        assert await ob.shared_session_list("tmux") == []

    asyncio.run(scenario())
