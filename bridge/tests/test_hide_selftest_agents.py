"""The cockpit does not show the install self-test's agents (2026-10-02).

agentstack-selftest (which the one-line install runs) registers two test
agents with program "agentstack-selftest" and retires them. On a fresh install
they were the only agents in TELEMETRY's network and in the roster, and a first
user saw "two agents I do not know". The backend drops them, and the edges and
spawn links that touch them, from /telemetry/agents and /telemetry/graph. The
dashboard itself still lists them (the self-test checks the dashboard).
Run from bridge/: ``python -m pytest tests/test_hide_selftest_agents.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_proxy_slow_or_offline import with_dashboard  # noqa: E402

SELFTEST = {"name": "FreshLovelace", "program": "agentstack-selftest", "retired": True}
SELFTEST2 = {"name": "GustyLamarr", "program": "agentstack-selftest", "retired": True}
AGENT = {"name": "PinkSomerville", "program": "claude-code"}


def test_roster_drops_selftest_agents():
    status, body = with_dashboard(0.0, "/telemetry/agents", 2,
                                  body={"ts": 1, "agents": [SELFTEST, AGENT, SELFTEST2]})
    assert status == 200
    assert [a["name"] for a in body["agents"]] == ["PinkSomerville"]
    assert body["ts"] == 1


def test_graph_drops_selftest_nodes_and_their_links():
    graph = {
        "nodes": [SELFTEST, SELFTEST2, AGENT, {"name": "Other", "program": "codex"}],
        "edges": [
            {"source": "FreshLovelace", "target": "GustyLamarr", "count": 2},
            {"source": "PinkSomerville", "target": "Other", "count": 1},
            {"source": "Other", "target": "GustyLamarr", "count": 1},
        ],
        "spawn": [{"source": "PinkSomerville", "target": "FreshLovelace", "type": "spawn"}],
        "total": 4,
        "shown": 4,
    }
    status, body = with_dashboard(0.0, "/telemetry/graph?all=1", 2, body=graph)
    assert status == 200
    assert [n["name"] for n in body["nodes"]] == ["PinkSomerville", "Other"]
    assert body["edges"] == [{"source": "PinkSomerville", "target": "Other", "count": 1}]
    assert body["spawn"] == []
    assert body["total"] == 2 and body["shown"] == 2


def test_nothing_else_changes():
    graph = {"nodes": [AGENT], "edges": [], "spawn": [], "total": 1, "shown": 1, "degraded": False}
    assert with_dashboard(0.0, "/telemetry/graph", 2, body=graph) == (200, graph)
    assert with_dashboard(0.0, "/telemetry/agents", 2, body={"agents": [AGENT]}) == (200, {"agents": [AGENT]})
