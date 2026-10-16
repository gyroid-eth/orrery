"""The roster poll asks only for the live rows (2026-10-16).

The dashboard's full /api/agents answer is the 30-day roster, about half a
megabyte, of which the cockpit shows the live rows only (a few percent). The
roster poll now asks /telemetry/agents?scope=live. The one other use of the
full answer was unpinning agents that retired: a live answer carries their
names in `retired`, and a dashboard that does not know `scope` still answers
the full roster, whose rows say which are retired. Both must unpin the same.

The backend forwards `scope` to the dashboard; /telemetry/agents without it is
still the full roster (the descriptor tools in tools/ read the retired rows).

Run from bridge/: ``python -m pytest tests/test_agents_scope_live.py``.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orrery_backend as ob  # noqa: E402
from test_proxy_coalesce import FakeDashboard, run  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COCKPIT = ROOT / "cockpit.html"
NODE = shutil.which("node")

BLOCK = r"/\* The live roster \(scope=live\).*?\nfunction pruneRetiredPins\(roster\)\{.*?\n\}"


def prune(roster: object, pins: list[str]) -> dict:
    html = COCKPIT.read_text(encoding="utf-8")
    match = re.search(BLOCK, html, re.DOTALL)
    assert match, "missing retiredNamesOf / pruneRetiredPins in cockpit.html"
    script = "\n".join([
        f"const pinnedAgents=new Set({json.dumps(pins)});let persisted=0;",
        "function persistPinnedAgents(){persisted++;}",
        match.group(0),
        f"pruneRetiredPins({json.dumps(roster)});",
        "console.log(JSON.stringify({pins:[...pinnedAgents].sort(),persisted}));",
    ])
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=False, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


FULL = {"agents": [
    {"name": "Live", "category": "agent", "running": True},
    {"name": "OldOne", "category": "retired"},
    {"name": "Gone", "category": "gone"},
    {"name": "OldTwo", "category": "retired"},
]}
LIVE = {"scope": "live", "agents": [{"name": "Live", "category": "agent", "running": True}],
        "retired": ["OldOne", "OldTwo"]}
PINS = ["Live", "OldOne", "Gone", "Elsewhere"]


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("roster", [LIVE, FULL], ids=["live answer", "full answer (older dashboard)"])
def test_retired_pins_are_dropped_from_either_answer(roster):
    assert prune(roster, PINS) == {"pins": ["Elsewhere", "Gone", "Live"], "persisted": 1}


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("roster", [
    {"scope": "live", "agents": [], "retired": []},
    {"agents": []},
    {},
    None,
    {"scope": "live", "retired": [None, 3, {"name": "OldOne"}]},
])
def test_nothing_to_unpin_writes_nothing(roster):
    assert prune(roster, PINS) == {"pins": sorted(PINS), "persisted": 0}


def test_the_roster_poll_asks_for_the_live_scope():
    html = COCKPIT.read_text(encoding="utf-8")
    poll = re.search(r"async function pollAgents\(\)\{.*?\n\}", html, re.DOTALL).group(0)
    assert "fetch('/telemetry/agents?scope=live'" in poll
    assert "pruneRetiredPins(d);" in poll
    # the client-side live filter stays: an older dashboard answers the full roster
    assert "(a.running||a.category==='agent')&&a.category!=='warmup'" in poll


def test_the_backend_forwards_scope_and_keeps_the_full_roster_without_it():
    dash = FakeDashboard(delay=0.2)

    async def scenario(get, *_):
        return await asyncio.gather(get("/telemetry/agents?scope=live"), get("/telemetry/agents"),
                                    get("/telemetry/agents?scope=live"))
    answers = run(scenario, dash)
    assert all(status == 200 for status, _ in answers)
    asked = sorted(p for p in dash.asked if p.startswith("/api/agents"))
    # one shared request per distinct query: live and full do not share
    assert asked == ["/api/agents", "/api/agents?scope=live"]


def test_scope_is_the_only_new_query_passed_through():
    assert ob.PROXY_ROUTES["/telemetry/agents"] == ("/api/agents", ("scope",))
