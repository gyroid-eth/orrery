"""The E2E suite never sends a spawn to the real dashboard (2026-09-28).

test_118 posted a "dry_run" spawn to the real 127.0.0.1:8770, which has no
dry_run, and two real Codex agents started. Spawn requests now need an
explicit opt-in plus a dashboard URL that is not the real one, and every test
that posts /telemetry/spawn must ask first.

Run from bridge/: ``python -m pytest tests/test_e2e_spawn_guard.py``.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import e2e_bridge  # noqa: E402


@pytest.mark.parametrize("allow,url", [
    (None, None),
    (None, "http://127.0.0.1:18770"),
    ("1", None),
    ("1", ""),
    ("1", "http://127.0.0.1:8770"),
    ("1", "http://localhost:8770/"),
    ("1", "http://127.0.0.1"),
    ("0", "http://127.0.0.1:18770"),
])
def test_spawn_is_refused_unless_opted_in_against_a_fake(monkeypatch, allow, url):
    for key, value in (("ORRERY_E2E_ALLOW_SPAWN", allow), ("ORRERY_DASHBOARD_URL", url)):
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    assert e2e_bridge.spawn_request_refusal()


def test_spawn_is_allowed_against_a_fake_with_the_opt_in(monkeypatch):
    monkeypatch.setenv("ORRERY_E2E_ALLOW_SPAWN", "1")
    monkeypatch.setenv("ORRERY_DASHBOARD_URL", "http://127.0.0.1:18770")
    assert e2e_bridge.spawn_request_refusal() is None


def test_every_spawn_post_in_the_suite_asks_first():
    tree = ast.parse(Path(e2e_bridge.__file__).read_text(encoding="utf-8"))
    posting = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        source = ast.unparse(fn)
        if "'/telemetry/spawn'" in source and "method='POST'" in source:
            posting.append(fn.name)
            assert "spawn_request_refusal()" in source, fn.name
            first = fn.body[0]
            assert isinstance(first, ast.Assign) and "spawn_request_refusal" in ast.unparse(first), (
                f"{fn.name}: the refusal must be checked before any request")
    assert posting, "expected the suite to have spawn tests"


# --- the backend the suite starts never uses the real ~/.orrery ------------------
# (2026-09-28: a test backend's startup retention deleted 29 real history files;
# its tmux socket has none of the real sessions, so all of them looked orphaned.)


def test_a_test_backend_gets_throwaway_history_and_prefs():
    server = e2e_bridge.ManagedServer(["true"])
    env = server.isolated_state_env()
    try:
        for key in ("ORRERY_HISTORY_DIR", "ORRERY_PREFS_PATH"):
            path = Path(env[key]).resolve()
            assert e2e_bridge.REAL_ORRERY_DIR not in path.parents, key
        e2e_bridge.assert_not_real_state(env)
    finally:
        server._state_dir.cleanup()


@pytest.mark.parametrize("env", [
    {},
    {"ORRERY_HISTORY_DIR": "/tmp/h"},
    {"ORRERY_HISTORY_DIR": "~/.orrery/history", "ORRERY_PREFS_PATH": "/tmp/p.json"},
    {"ORRERY_HISTORY_DIR": "/tmp/h", "ORRERY_PREFS_PATH": "~/.orrery/prefs.json"},
    {"ORRERY_HISTORY_DIR": "~/.orrery", "ORRERY_PREFS_PATH": "/tmp/p.json"},
])
def test_the_real_orrery_directory_is_refused(env):
    with pytest.raises(AssertionError):
        e2e_bridge.assert_not_real_state(env)


def test_start_isolates_before_anything_can_override_and_checks_last():
    tree = ast.parse(Path(e2e_bridge.__file__).read_text(encoding="utf-8"))
    start = next(node for cls in ast.walk(tree) if isinstance(cls, ast.ClassDef)
                 and cls.name == "ManagedServer" for node in cls.body
                 if isinstance(node, ast.FunctionDef) and node.name == "start")
    source = ast.unparse(start)
    isolate = source.index("self.isolated_state_env()")
    check = source.index("assert_not_real_state(merged_env)")
    popen = source.index("subprocess.Popen")
    assert isolate < source.index("merged_env.update(self.env)") < check < popen
