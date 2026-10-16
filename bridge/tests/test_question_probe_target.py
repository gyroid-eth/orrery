"""The question probe reads the session's pane (2026-10-16).

pane_has_pending_user_question captured "-t =<session>". capture-pane takes a
target pane, and tmux 3.6 does not resolve a bare "=name" as one: it answers
"can't find pane: =name" and exit 1, which the probe read as an empty screen,
so a question never showed. "=name:" is the exact session's active pane.

These run against a real tmux server, with the shared helper and without it
(pure legacy), as test_runtime_target.py does.
Run from bridge/: ``python -m pytest tests/test_question_probe_target.py``.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orrery_backend as ob  # noqa: E402
from runtime_target import LegacyTargetBoundary  # noqa: E402
from test_runtime_target import deploy, endpoint  # noqa: E402,F401  (fixture)

QUESTION = "Should I also update the documentation for this change?"
# cat with echo off prints each line sent with send-keys once, as pane output
PROGRAM = "sh -c 'stty -echo; exec cat'"


def tmux(ep, *args) -> str:
    return subprocess.run([*ep["prefix"], *args], capture_output=True, text=True, check=True).stdout.strip()


def session(ep, name: str, *lines: str) -> None:
    # a short pane: the prompt sits at the bottom, as Claude's does
    tmux(ep, "new-session", "-d", "-s", name, "-x", "120", "-y", "10", PROGRAM)
    time.sleep(0.1)
    pane = tmux(ep, "list-panes", "-t", "=" + name, "-F", "#{pane_id}").splitlines()[0]
    for line in lines:
        tmux(ep, "send-keys", "-t", pane, "-l", line)
        tmux(ep, "send-keys", "-t", pane, "Enter")
    time.sleep(0.15)


@pytest.mark.parametrize("helper", ["actual", "missing"])
def test_a_question_before_the_idle_prompt_is_seen(endpoint, helper):  # noqa: F811
    if helper == "actual":
        deploy(endpoint["home"])
    boundary = LegacyTargetBoundary(endpoint["binary"], home=endpoint["home"], environ=endpoint["env"])
    assert (boundary.shared is not None) is (helper == "actual")
    session(endpoint, "Asker", "I updated the parser.", QUESTION, "", "❯")
    session(endpoint, "Ask", "Done.", "", "❯")          # a prefix of Asker: exact match only
    ob._question_probe_cache.clear()
    assert ob.pane_has_pending_user_question("Asker", boundary) is True
    assert ob.pane_has_pending_user_question("Ask", boundary) is False


def test_the_capture_target_is_the_exact_session_pane(endpoint, monkeypatch):  # noqa: F811
    deploy(endpoint["home"])
    boundary = LegacyTargetBoundary(endpoint["binary"], home=endpoint["home"], environ=endpoint["env"])
    session(endpoint, "Target", QUESTION, "❯")
    seen = []
    real = ob.subprocess.run

    def spy(argv, *a, **k):
        result = real(argv, *a, **k)
        if "capture-pane" in argv:
            seen.append((argv[argv.index("-t") + 1], result.returncode))
        return result

    monkeypatch.setattr(ob.subprocess, "run", spy)
    ob._question_probe_cache.clear()
    ob.pane_has_pending_user_question("Target", boundary)
    assert seen == [("=Target:", 0)]
