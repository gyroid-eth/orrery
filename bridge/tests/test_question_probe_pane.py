"""The question probe re-reads a pane only when it may have changed (2026-10-16).

Agents waiting for a reply have screens that do not change, yet each cost a
capture-pane (and its admission) about every other roster poll. One
list-panes -a per poll now names the pane a session-targeted capture reads
(the active pane of the active window) and its window_activity. A previous
read is reused only when it is provably of that same pane and began in a
strictly later second than the last activity (tmux keeps whole seconds, so a
read in the same second may have missed what came later in it). Otherwise the
pane is admitted alone -- the shared admission takes exactly one selector --
the proof's session is compared with the listing, and the pane is captured by
its id. Anything not known exactly falls back to the old session read.

These run against a real tmux server and the real shared helper
(ORRERY_TEST_TELEMETRY_ROOT, as test_runtime_target.py does). Refusals are
checked directly, not inferred from "no question mark shown": the probe turns
any refusal into "no question", which would hide an admission mistake.

Run from bridge/: ``python -m pytest tests/test_question_probe_pane.py``.
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
from runtime_target import LegacyTargetBoundary, TargetRefused, require_target  # noqa: E402
from test_runtime_target import deploy, endpoint  # noqa: E402,F401  (fixture)

QUESTION = "Should I also update the documentation for this change?"


class Probe:
    def __init__(self, endpoint, helper=True):
        self.ep = endpoint
        if helper:
            deploy(endpoint["home"])
        self.boundary = LegacyTargetBoundary(endpoint["binary"], home=endpoint["home"], environ=endpoint["env"])
        self.captures: list[list[str]] = []
        self.admissions: list[dict] = []
        self.failures: list[str] = []
        self.fallbacks = 0
        self.before_admission = None

    def tmux(self, *args) -> str:
        return subprocess.run([*self.ep["prefix"], *args], capture_output=True, text=True, check=True).stdout.strip()

    # Each pane runs cat with echo off: a line sent with send-keys is printed
    # once, as the pane's own output (nothing writes to a terminal device).
    PROGRAM = "sh -c 'stty -echo; exec cat'"

    def new_session(self, name: str) -> str:
        # Short panes: the prompt sits at the bottom, as Claude's does, within
        # the 32 lines the probe looks at.
        self.tmux("new-session", "-d", "-s", name, "-x", "120", "-y", "10", self.PROGRAM)
        time.sleep(0.1)
        return self.tmux("list-panes", "-t", "=" + name, "-F", "#{pane_id}").splitlines()[0]

    def split(self, pane: str) -> str:
        new = self.tmux("split-window", "-d", "-P", "-F", "#{pane_id}", "-t", pane, self.PROGRAM)
        time.sleep(0.1)
        return new

    def window(self, session: str) -> str:
        new = self.tmux("new-window", "-d", "-P", "-F", "#{pane_id}", "-t", "=" + session, self.PROGRAM)
        time.sleep(0.1)
        return new

    def write(self, pane: str, *lines: str) -> None:
        for line in lines:
            self.tmux("send-keys", "-t", pane, "-l", line)
            self.tmux("send-keys", "-t", pane, "Enter")
        time.sleep(0.15)

    def ask(self, pane: str) -> None:
        self.write(pane, "I updated the parser.", QUESTION, "", "❯")

    def answer_shown(self, pane: str) -> None:
        self.write(pane, "Done.", "", "❯")

    def run(self, session: str) -> bool:
        ob._question_probe_cache.clear()           # every call is a new roster poll
        ob._question_listing["at"] = -1e9
        return ob.pane_has_pending_user_question(session, self.boundary)


@pytest.fixture
def probe(endpoint, monkeypatch):  # noqa: F811
    p = Probe(endpoint)
    ob._question_proofs.clear()
    real_run, real_require = ob.subprocess.run, ob.require_target

    def spy_run(argv, *a, **k):
        if "capture-pane" in argv:
            p.captures.append(list(argv))
        return real_run(argv, *a, **k)

    def spy_require(binary, operation, *, session=None, pane=None):
        p.admissions.append({"session": session, "pane": pane})
        if p.before_admission:
            p.before_admission()
        return real_require(binary, operation, session=session, pane=pane)

    real_failure, real_fallback = p.boundary._helper_failure, p.boundary._fallback_admit

    def spy_failure(exc):
        p.failures.append(str(exc))
        return real_failure(exc)

    def spy_fallback():
        p.fallbacks += 1
        return real_fallback()

    monkeypatch.setattr(ob.subprocess, "run", spy_run)
    monkeypatch.setattr(ob, "require_target", spy_require)
    monkeypatch.setattr(p.boundary, "_helper_failure", spy_failure)
    monkeypatch.setattr(p.boundary, "_fallback_admit", spy_fallback)
    assert p.boundary.shared is not None
    return p


def next_second(offset: float = 0.05) -> None:
    time.sleep(1 - (time.time() % 1) + offset)


def assert_admitted_cleanly(p: Probe) -> None:
    assert p.failures == [] and p.fallbacks == 0


def test_question_is_seen_and_read_by_pane_id(probe):
    pane = probe.new_session("Asker")
    probe.ask(pane)
    assert probe.run("Asker") is True
    assert probe.captures[-1][-4:-2] == ["-t", pane]
    assert probe.admissions == [{"session": None, "pane": pane}]  # the pane alone, once
    assert ob._question_proofs["Asker"]["pane_id"] == pane
    assert_admitted_cleanly(probe)


def test_an_unchanged_pane_is_not_captured_again(probe):
    pane = probe.new_session("Waiter")
    probe.ask(pane)
    next_second()                                   # the read starts after the last output's second
    assert probe.run("Waiter") is True
    reads = len(probe.captures)
    for _ in range(3):
        assert probe.run("Waiter") is True
    assert len(probe.captures) == reads
    assert_admitted_cleanly(probe)


def test_a_question_written_in_the_second_of_the_read_is_not_missed(probe):
    """read (no question) -> question in the same second -> no more output."""
    pane = probe.new_session("SameSecond")
    next_second(0.02)
    probe.answer_shown(pane)
    assert probe.run("SameSecond") is False
    probe.ask(pane)                                 # same second, then silence
    started = ob._question_proofs["SameSecond"]["read_started"]
    activity = int(probe.tmux("display-message", "-p", "-t", pane, "#{window_activity}"))
    assert int(started) == activity, "the timeline must keep the read and the question in one second"
    assert probe.run("SameSecond") is True          # not reused: re-read, question found
    assert_admitted_cleanly(probe)


def test_a_question_after_the_read_is_seen_at_the_next_poll(probe):
    pane = probe.new_session("Later")
    probe.answer_shown(pane)
    next_second()
    assert probe.run("Later") is False
    next_second()
    probe.ask(pane)
    assert probe.run("Later") is True
    probe.answer_shown(pane)
    assert probe.run("Later") is False


@pytest.mark.parametrize("asking", ["A", "B"])
def test_switching_a_to_b_and_back_never_stores_b_as_a(probe, asking):
    a = probe.new_session("Split")
    b = probe.split(a)
    probe.tmux("select-pane", "-t", a)
    (probe.ask if asking == "A" else probe.answer_shown)(a)
    (probe.ask if asking == "B" else probe.answer_shown)(b)

    def switch_b_then_a():
        probe.tmux("select-pane", "-t", b)
        probe.tmux("select-pane", "-t", a)

    probe.before_admission = switch_b_then_a
    pending = probe.run("Split")
    assert probe.captures[-1][-4:-2] == ["-t", a]
    assert probe.admissions[-1] == {"session": None, "pane": a}
    assert pending is (asking == "A")
    assert ob._question_proofs["Split"]["pane_id"] == a and ob._question_proofs["Split"]["pending"] is (asking == "A")
    assert_admitted_cleanly(probe)


def test_switching_panes_without_output_is_re_read(probe):
    a = probe.new_session("Switch")
    b = probe.split(a)
    probe.answer_shown(a)
    probe.ask(b)
    probe.tmux("select-pane", "-t", a)
    next_second()
    assert probe.run("Switch") is False
    probe.tmux("select-pane", "-t", b)              # no output: window_activity unchanged
    assert probe.run("Switch") is True
    assert probe.captures[-1][-4:-2] == ["-t", b]


def test_another_window_without_output_is_re_read(probe):
    a = probe.new_session("Windows")
    probe.answer_shown(a)
    other = probe.window("Windows")
    probe.ask(other)
    next_second()
    assert probe.run("Windows") is False
    probe.tmux("select-window", "-t", other)
    assert probe.run("Windows") is True


def test_a_pane_moved_to_another_session_is_not_kept(probe):
    a = probe.new_session("Mover")
    probe.split(a)                                   # Mover keeps a pane after the move
    probe.tmux("select-pane", "-t", a)
    probe.ask(a)
    probe.new_session("Elsewhere")

    def move_away_once():
        probe.before_admission = None
        probe.tmux("move-pane", "-d", "-s", a, "-t", "=Elsewhere:")

    probe.before_admission = move_away_once
    probe.run("Mover")
    assert probe.admissions[0] == {"session": None, "pane": a}
    assert "Mover" not in ob._question_proofs        # the proof named another session
    assert probe.admissions[-1] == {"session": "Mover", "pane": None}  # fell back to the session read


def test_a_vanished_pane_falls_back_and_keeps_nothing(probe):
    probe.new_session("Gone")

    def kill_once():
        probe.before_admission = None
        probe.tmux("kill-session", "-t", "=Gone")

    probe.before_admission = kill_once
    assert probe.run("Gone") is False
    assert "Gone" not in ob._question_proofs


def test_a_recreated_session_of_the_same_name_is_re_read(probe):
    pane = probe.new_session("Again")
    probe.answer_shown(pane)
    next_second()
    assert probe.run("Again") is False
    probe.tmux("kill-session", "-t", "=Again")
    next_second()                                    # a new session_created
    pane = probe.new_session("Again")
    probe.ask(pane)
    assert probe.run("Again") is True


def test_a_failed_listing_reads_the_session_as_before(probe, monkeypatch):
    pane = probe.new_session("NoList")
    probe.ask(pane)
    monkeypatch.setattr(ob, "_QUESTION_LISTING_FORMAT", "#{no_such_format_errors_here")
    real = ob.tmux_argv
    monkeypatch.setattr(ob, "tmux_argv", lambda b, *a: real(b, *a) if a[0] != "list-panes" else [*real(b), "no-such-command"])
    assert probe.run("NoList") is True
    assert probe.captures[-1][-4:-2] == ["-t", "=NoList:"]
    assert "NoList" not in ob._question_proofs


def test_the_shared_admission_refuses_session_and_pane_together(probe):
    """Why the probe admits the pane alone (r3 of the plan got this wrong)."""
    pane = probe.new_session("Both")
    with pytest.raises(TargetRefused, match="TMUX_TARGET_INPUT_INVALID"):
        require_target(probe.boundary, "capture", session="Both", pane=pane)


def test_pure_legacy_admission_keeps_the_old_read(endpoint, monkeypatch):  # noqa: F811
    p = Probe(endpoint, helper=False)
    assert p.boundary.shared is None
    ob._question_proofs.clear()
    pane = p.new_session("Legacy")
    p.ask(pane)
    captured = []
    real_run = ob.subprocess.run
    monkeypatch.setattr(ob.subprocess, "run",
                        lambda argv, *a, **k: (captured.append(list(argv)) if "capture-pane" in argv else None)
                        or real_run(argv, *a, **k))
    assert p.run("Legacy") is True
    assert captured[-1][-4:-2] == ["-t", "=Legacy:"]
    assert "Legacy" not in ob._question_proofs
