"""start-cockpit.sh does not stop a start because the dashboard's first
answer is slow (issue #1, 2026-09-30).

Run from bridge/: ``python -m pytest tests/test_start_cockpit_dashboard_probe.py``.

On WSL the first /api/agents after the dashboard (re)starts took 3.7 and
6.9 s, and the 3 s check said "does not answer" while it was fine. The check
now asks /api/version (instant), gives a slow first answer one more, longer
chance, and still checks a release without /api/version on /api/agents. The
harness is the one of test_start_cockpit_telemetry.py: a fake dashboard, a
private HOME, and a missing tmux that stops the run before anything starts.
"""
from __future__ import annotations

import json
import time

import pytest

from test_start_cockpit_telemetry import CURRENT, closed_url, serve, start, version

AGENTS = (200, b'{"agents": []}')


def test_positive_a_slow_agent_list_does_not_matter(tmp_path):
    """The first /api/agents of a just-started dashboard on WSL: 7 s."""
    dash, url, asked = serve({"/api/version": (200, version(CURRENT)), "/api/agents": (*AGENTS, [7])})
    began = time.monotonic()
    out = start(tmp_path, url)
    dash.shutdown()
    assert "ok    orrery-telemetry dashboard" in out
    assert "/api/agents" not in asked            # not needed to know it is there
    assert time.monotonic() - began < 5


def test_positive_a_slow_first_answer_gets_a_second_chance(tmp_path):
    dash, url, asked = serve({"/api/version": (200, version(CURRENT), [4.5, 0]), "/api/agents": AGENTS})
    out = start(tmp_path, url)
    dash.shutdown()
    assert "the dashboard did not answer in 3 s; one that has just started can take a few seconds" in out
    assert "ok    orrery-telemetry dashboard" in out
    assert "does not answer" not in out


def test_positive_a_release_without_api_version_is_still_found_on_the_agent_list(tmp_path):
    """2026.09.16 and older: /api/version is a 404."""
    dash, url, asked = serve({"/api/agents": (*AGENTS, [4])})
    out = start(tmp_path, url)
    dash.shutdown()
    assert "ok    orrery-telemetry dashboard" in out
    assert "/api/agents" in asked
    assert "could not read its API generation" in out   # and the API warning still shows


def test_negative_nothing_there_still_stops_the_start(tmp_path):
    out = start(tmp_path, closed_url().rsplit("/", 2)[0], problems=2)
    assert "NG    The orrery-telemetry dashboard does not answer" in out


def test_negative_a_dashboard_that_never_answers_stops_after_the_second_chance(tmp_path):
    dash, url, asked = serve({"/api/version": (200, version(CURRENT), [30]), "/api/agents": AGENTS})
    began = time.monotonic()
    out = start(tmp_path, url, problems=2)
    elapsed = time.monotonic() - began
    dash.shutdown()
    assert "did not answer in 3 s" in out and "NG    The orrery-telemetry dashboard does not answer" in out
    assert 12 < elapsed < 25                      # 3 s, then 10 s, not forever


@pytest.mark.parametrize("routes", [
    {},                                                                   # 404 everywhere
    {"/api/version": (200, b"<html>hello</html>"), "/api/agents": (200, b"<html></html>")},
    {"/api/version": (200, json.dumps({"name": "other", "api": 2}).encode())},
])
def test_negative_something_else_on_the_port_is_named(tmp_path, routes):
    dash, url, asked = serve(routes)
    out = start(tmp_path, url, problems=2)
    dash.shutdown()
    assert "NG    Something answers at" in out and "not the orrery-telemetry dashboard" in out
