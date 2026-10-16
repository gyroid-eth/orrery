"""The roster answer is parsed and written once per dashboard answer (2026-10-16).

/telemetry/agents is about half a megabyte every 3 s. The backend used to parse
it and write it again to add the annotations and the question state, then a
second time to drop the self-test agents -- the second time once for every tab
waiting on the shared answer. prepare_agents_payload does all three in one
pass inside the shared request. What the cockpit receives must not change:
these compare it, as JSON, with the two old steps run one after the other.
Run from bridge/: ``python -m pytest tests/test_agents_payload_once.py``.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orrery_backend as ob  # noqa: E402
from test_proxy_coalesce import FakeDashboard, run  # noqa: E402

SELFTEST = "agentstack-selftest"


# The two steps as they were before this change (6fbb441), kept verbatim so the
# comparison is against the old behaviour, not against a re-derivation of it.
def old_merge_agent_annotations(payload, labels, probe):
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return payload
    agents = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(agents, list):
        return payload
    changed = False
    for agent in agents:
        if isinstance(agent, dict) and isinstance(agent.get("name"), str):
            annot = labels.get(agent["name"])
            if annot:
                agent["annot"] = annot
                changed = True
            if agent.get("running") and agent.get("act_state") == "wait" \
                    and probe(agent["name"]):
                agent["act_state"] = "question"
                changed = True
    return json.dumps(data, ensure_ascii=False).encode("utf-8") if changed else payload


def old_hide_selftest_agents(path, body):
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    if not isinstance(payload, dict):
        return body

    def is_selftest(entry):
        return isinstance(entry, dict) and entry.get("program") == SELFTEST

    if path == "/telemetry/agents":
        agents = payload.get("agents")
        if not isinstance(agents, list) or not any(is_selftest(a) for a in agents):
            return body
        payload["agents"] = [a for a in agents if not is_selftest(a)]
        return json.dumps(payload).encode()
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        return body
    hidden = {n.get("name") for n in nodes if is_selftest(n)}
    if not hidden:
        return body
    payload["nodes"] = [n for n in nodes if not is_selftest(n)]
    for key in ("edges", "spawn"):
        links = payload.get(key)
        if isinstance(links, list):
            payload[key] = [link for link in links
                            if not (isinstance(link, dict)
                                    and (link.get("source") in hidden or link.get("target") in hidden))]
    for key in ("total", "shown"):
        if isinstance(payload.get(key), int):
            payload[key] = max(0, payload[key] - len(hidden))
    return json.dumps(payload).encode()


def old_pipeline(payload, labels, probe):
    return old_hide_selftest_agents("/telemetry/agents", old_merge_agent_annotations(payload, labels, probe))


def roster(*, selftest: bool, annotated: bool, question: bool) -> tuple[bytes, dict, set]:
    agents = [
        {"name": "PinkSomerville", "program": "claude-code", "running": True, "act_state": "wait",
         "task": "パーサーを直す", "unknown_field": {"nested": [1, 2]}},
        {"name": "QuietNoether", "program": "codex-cli", "running": True, "act_state": "work"},
        {"name": "OldHopper", "program": "claude-code", "running": False, "category": "retired"},
        {"name": "名前のある子", "program": "claude-code", "running": True, "act_state": "wait"},
    ]
    if selftest:
        agents.insert(1, {"name": "FreshLovelace", "program": SELFTEST, "retired": True})
        agents.append({"name": "LiveSelftest", "program": SELFTEST, "running": True, "act_state": "wait"})
    labels = {"PinkSomerville": {"role": "reader"}, "名前のある子": {"role": "書き手"}} if annotated else {}
    asking = {"名前のある子", "LiveSelftest"} if question else set()
    return json.dumps({"ts": 1, "history_days": 30.0, "agents": agents}, ensure_ascii=False).encode(), labels, asking


@pytest.mark.parametrize("selftest,annotated,question", list(itertools.product([False, True], repeat=3)))
def test_same_roster_as_the_two_old_steps(monkeypatch, selftest, annotated, question):
    payload, labels, asking = roster(selftest=selftest, annotated=annotated, question=question)
    monkeypatch.setattr(ob, "pane_has_pending_user_question", lambda name, *a, **k: name in asking)
    new = ob.prepare_agents_payload(payload, labels)
    old = old_pipeline(payload, labels, lambda name: name in asking)
    assert json.loads(new) == json.loads(old)
    if not (selftest or annotated or question):
        assert new is payload  # nothing to change: the dashboard's bytes pass through


@pytest.mark.parametrize("payload", [
    b"not json", b"\xff\xfe", b"[1, 2]", b'{"ts": 1}', b'{"agents": {"a": 1}}', b'{"agents": null}', b"",
])
def test_answers_that_are_not_a_roster_pass_through(monkeypatch, payload):
    monkeypatch.setattr(ob, "pane_has_pending_user_question", lambda *a, **k: pytest.fail("probed"))
    assert ob.prepare_agents_payload(payload, {"x": {"role": "r"}}) is payload
    assert old_pipeline(payload, {"x": {"role": "r"}}, lambda name: False) == payload


def test_rows_that_are_not_agents_are_kept(monkeypatch):
    monkeypatch.setattr(ob, "pane_has_pending_user_question", lambda *a, **k: False)
    payload = json.dumps({"agents": ["text", 3, None, {"no_name": True},
                                     {"name": "Kid", "program": SELFTEST}]}).encode()
    new = ob.prepare_agents_payload(payload, {})
    assert json.loads(new) == json.loads(old_pipeline(payload, {}, lambda name: False))


def test_graph_is_unchanged():
    graph = {
        "nodes": [{"name": "FreshLovelace", "program": SELFTEST}, {"name": "Pink", "program": "claude-code"}],
        "edges": [{"source": "FreshLovelace", "target": "Pink"}, {"source": "Pink", "target": "Pink"}],
        "spawn": [{"source": "Pink", "target": "FreshLovelace"}],
        "total": 2, "shown": 2,
    }
    body = json.dumps(graph).encode()
    assert json.loads(ob.hide_selftest_nodes(body)) == json.loads(old_hide_selftest_agents("/telemetry/graph", body))
    plain = json.dumps({"nodes": [{"name": "Pink"}], "edges": []}).encode()
    assert ob.hide_selftest_nodes(plain) is plain


def test_tabs_waiting_together_share_one_prepared_answer(monkeypatch):
    """Three tabs at once: one dashboard request, one preparation, the same roster."""
    calls = []
    real = ob.prepare_agents_payload

    def counting(payload, labels, tmux_bin="tmux"):
        calls.append(len(payload))
        return real(payload, labels, tmux_bin)

    monkeypatch.setattr(ob, "prepare_agents_payload", counting)
    monkeypatch.setattr(ob, "pane_has_pending_user_question", lambda *a, **k: False)
    dash = FakeDashboard(delay=0.3)
    roster_with_selftest = {"agents": [{"name": "Kid", "running": True},
                                       {"name": "Fresh", "program": SELFTEST}]}
    monkeypatch.setattr("test_proxy_coalesce.AGENTS", roster_with_selftest)

    async def scenario(get, *_):
        return await asyncio.gather(*(get("/telemetry/agents") for _ in range(3)))
    answers = run(scenario, dash)
    assert dash.asked_for("/api/agents") == 1
    assert len(calls) == 1
    assert answers[0] == answers[1] == answers[2]
    status, body = answers[0]
    assert status == 200
    assert [a["name"] for a in body["agents"]] == ["Kid"]
    assert body["agents"][0]["annot"]["role"] == "reader"


def test_the_live_scope_roster_is_prepared_once_too(monkeypatch):
    """The roster poll asks /telemetry/agents?scope=live (P4). That answer goes
    through the same single preparation in the shared request."""
    calls = []
    real = ob.prepare_agents_payload

    def counting(payload, labels, tmux_bin="tmux"):
        calls.append(len(payload))
        return real(payload, labels, tmux_bin)

    monkeypatch.setattr(ob, "prepare_agents_payload", counting)
    monkeypatch.setattr(ob, "pane_has_pending_user_question", lambda *a, **k: False)
    dash = FakeDashboard(delay=0.3)
    monkeypatch.setattr("test_proxy_coalesce.AGENTS", {"scope": "live", "retired": ["Old"],
                                                       "agents": [{"name": "Kid", "running": True},
                                                                  {"name": "Fresh", "program": SELFTEST,
                                                                   "running": True}]})

    async def scenario(get, *_):
        return await asyncio.gather(*(get("/telemetry/agents?scope=live") for _ in range(3)))
    answers = run(scenario, dash)
    assert [p for p in dash.asked if p.startswith("/api/agents")] == ["/api/agents?scope=live"]
    assert len(calls) == 1
    status, body = answers[0]
    assert status == 200 and answers[0] == answers[1] == answers[2]
    assert [a["name"] for a in body["agents"]] == ["Kid"] and body["retired"] == ["Old"]
