"""The question probe re-reads a pane only when it may have changed (2026-10-16).

Agents waiting for a reply have screens that do not change, yet each cost a
capture-pane and its admission (ps, list-panes, display-message) about every
other roster poll. Each probe now takes one list-panes -a at the moment it
decides: it names the pane a session-targeted capture reads (the active pane of
the active window) and its window_activity. A previous read is reused only when
it is provably of that same pane and began in a strictly later second than the
last activity (tmux keeps whole seconds, so a read in the same second may have
missed what came later in it). The listing is never shared over time, so a
reused answer is never older than a capture at the same moment would be.

Otherwise the pane alone is admitted -- the shared admission takes exactly one
selector -- the proof's session is checked against the listing, and the pane is
captured by its id. A refusal or a pane that moved is "no question" for that
probe, with its reason kept; nothing is retried under another selector. Only a
pure legacy admission (no proof) or a pane that cannot be told exactly reads
the session as before.

These run against a real tmux server and the real shared helper
(ORRERY_TEST_TELEMETRY_ROOT, as test_runtime_target.py does). Refusals are
checked directly, not inferred from "no question mark shown".

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
POLL = 3.0  # cockpit.html startPoll(pollAgents, 3000)


class Probe:
    # Each pane runs cat with echo off: a line sent with send-keys is printed
    # once, as the pane's own output (nothing writes to a terminal device).
    PROGRAM = "sh -c 'stty -echo; exec cat'"

    def __init__(self, endpoint, helper=True):
        self.ep = endpoint
        if helper:
            deploy(endpoint["home"])
        self.boundary = LegacyTargetBoundary(endpoint["binary"], home=endpoint["home"], environ=endpoint["env"])
        self.captures: list[list[str]] = []
        self.listings = 0
        self.admissions: list[dict] = []
        self.failures: list[str] = []
        self.fallbacks = 0
        self.before_admission = None
        self.around_capture = None  # (before, after) callables around the capture-pane process

    def tmux(self, *args) -> str:
        return subprocess.run([*self.ep["prefix"], *args], capture_output=True, text=True, check=True).stdout.strip()

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
        new = self.tmux("new-window", "-d", "-P", "-F", "#{pane_id}", "-t", "=" + session + ":", self.PROGRAM)
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
        """One probe as a new roster poll would make it: the short cache expired."""
        ob._question_probe_cache.pop(session, None)
        return ob.pane_has_pending_user_question(session, self.boundary)


@pytest.fixture
def probe(endpoint, monkeypatch):  # noqa: F811
    p = Probe(endpoint)
    for cache in (ob._question_probe_cache, ob._question_proofs, ob._question_refusals):
        cache.clear()
    real_run, real_require = ob.subprocess.run, ob.require_target

    def spy_run(argv, *a, **k):
        if "list-panes" in argv and "-a" in argv:
            p.listings += 1
        if "capture-pane" in argv:
            p.captures.append(list(argv))
            if p.around_capture:
                p.around_capture[0]()
            try:
                return real_run(argv, *a, **k)
            finally:
                if p.around_capture:
                    p.around_capture[1]()
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


def once(p: Probe, action):
    def fire():
        p.before_admission = None
        action()
    return fire


def assert_no_fallback(p: Probe) -> None:
    assert p.failures == [] and p.fallbacks == 0


# ------------------------------------------------------------------ reading

def test_question_is_seen_and_read_by_pane_id(probe):
    pane = probe.new_session("Asker")
    probe.ask(pane)
    assert probe.run("Asker") is True
    assert probe.captures[-1][-4:-2] == ["-t", pane]
    assert probe.admissions == [{"session": None, "pane": pane}]  # the pane alone, once
    assert ob._question_proofs["Asker"]["pane_id"] == pane
    assert "Asker" not in ob._question_refusals
    assert_no_fallback(probe)


def test_unchanged_panes_cost_one_listing_each_and_no_capture(probe):
    names = ["W1", "W2", "W3"]
    for name in names:
        probe.answer_shown(probe.new_session(name))
    next_second()                                   # reads start after the last output's second
    for name in names:
        assert probe.run(name) is False             # first poll: one capture each
    assert len(probe.captures) == 3 and len(probe.admissions) == 3
    probe.captures.clear()
    probe.admissions.clear()
    probe.listings = 0
    for _ in range(2):                              # later polls: nothing changed
        for name in names:
            assert probe.run(name) is False
    assert probe.captures == [] and probe.admissions == []
    assert probe.listings == 6                      # one list-panes per probe, nothing else
    assert_no_fallback(probe)


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
    assert_no_fallback(probe)


def test_a_question_after_the_listing_of_another_agent_is_seen_in_the_same_poll(probe):
    """listing for A -> B asks -> B's probe, in one roster poll (the order of the
    review's counterexample). B decides on its own fresh listing."""
    a, b = probe.new_session("PollA"), probe.new_session("PollB")
    probe.answer_shown(a)
    probe.answer_shown(b)
    next_second()
    assert probe.run("PollA") is False and probe.run("PollB") is False
    next_second()
    # the next poll: A first, then B asks, then B
    assert probe.run("PollA") is False
    probe.ask(b)
    assert probe.run("PollB") is True


def test_detection_delay_matches_the_old_read_on_a_poll_timeline(probe):
    """Polls every 3 s with the 4 s cache: the poll at which the question is first
    shown is the same as with a capture on every probe (P0). The clock of the
    cache is moved, the tmux clock is real."""
    pane = probe.new_session("Timeline")
    probe.answer_shown(pane)
    next_second()

    def poll():
        return ob.pane_has_pending_user_question("Timeline", probe.boundary)

    def advance():
        for key, (at, value) in list(ob._question_probe_cache.items()):
            ob._question_probe_cache[key] = (at - POLL, value)

    shown = []
    for index in range(6):
        if index == 2:
            next_second()
            probe.ask(pane)                         # between poll 1 and poll 2
        shown.append(poll())
        advance()
    # P0: poll 0 reads (cached 4 s), poll 1 cached, poll 2 reads -> question.
    assert shown == [False, False, True, True, True, True]


# ------------------------------------------------------------- pane identity

@pytest.mark.parametrize("asking", ["A", "B"])
def test_b_active_during_the_capture_never_becomes_a(probe, asking):
    """The listing picks A; B is the active pane while the capture runs, A again
    afterwards. The capture is of A by id, so A's screen is what is kept."""
    a = probe.new_session("Split")
    b = probe.split(a)
    probe.tmux("select-pane", "-t", a)
    (probe.ask if asking == "A" else probe.answer_shown)(a)
    (probe.ask if asking == "B" else probe.answer_shown)(b)
    probe.around_capture = (lambda: probe.tmux("select-pane", "-t", b),
                            lambda: probe.tmux("select-pane", "-t", a))
    pending = probe.run("Split")
    assert probe.captures[-1][-4:-2] == ["-t", a]
    assert probe.admissions[-1] == {"session": None, "pane": a}
    assert pending is (asking == "A")
    assert ob._question_proofs["Split"]["pane_id"] == a
    assert ob._question_proofs["Split"]["pending"] is (asking == "A")
    assert_no_fallback(probe)


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


# ----------------------------------------------------- refusals and recovery

def test_a_pane_moved_to_another_session_ends_the_probe_and_the_next_poll_recovers(probe):
    a = probe.new_session("Mover")
    rest = probe.split(a)                            # Mover keeps a pane after the move
    probe.tmux("select-pane", "-t", a)
    probe.ask(a)
    probe.ask(rest)
    probe.new_session("Elsewhere")
    probe.before_admission = once(probe, lambda: probe.tmux("move-pane", "-d", "-s", a, "-t", "=Elsewhere:"))
    assert probe.run("Mover") is False
    assert ob._question_refusals["Mover"] == "PANE_NOT_IN_SESSION"
    assert probe.admissions == [{"session": None, "pane": a}]  # no retry under the session
    assert probe.captures == [] and "Mover" not in ob._question_proofs
    # the next poll lists Mover's remaining pane and reads it
    assert probe.run("Mover") is True
    assert probe.captures[-1][-4:-2] == ["-t", rest]
    assert "Mover" not in ob._question_refusals
    assert_no_fallback(probe)


def test_a_pane_gone_before_admission_is_refused_with_its_reason(probe):
    a = probe.new_session("Vanish")
    rest = probe.split(a)
    probe.tmux("select-pane", "-t", a)
    probe.ask(rest)
    probe.before_admission = once(probe, lambda: probe.tmux("kill-pane", "-t", a))
    assert probe.run("Vanish") is False
    assert ob._question_refusals["Vanish"] == "TMUX_TARGET_UNAVAILABLE"
    assert probe.admissions == [{"session": None, "pane": a}]
    assert probe.captures == [] and "Vanish" not in ob._question_proofs
    assert probe.run("Vanish") is True              # next poll: the remaining pane
    assert probe.captures[-1][-4:-2] == ["-t", rest]


def test_the_shared_admission_refuses_session_and_pane_together(probe):
    """Why the probe admits the pane alone."""
    pane = probe.new_session("Both")
    with pytest.raises(TargetRefused, match="TMUX_TARGET_INPUT_INVALID"):
        require_target(probe.boundary, "capture", session="Both", pane=pane)


# --------------------------------------------------------- reading as before

def test_a_failed_listing_reads_the_session_as_before(probe, monkeypatch):
    pane = probe.new_session("NoList")
    probe.ask(pane)
    real = ob.tmux_argv
    monkeypatch.setattr(ob, "tmux_argv",
                        lambda b, *a: [*real(b), "no-such-command"] if a and a[0] == "list-panes" else real(b, *a))
    assert probe.run("NoList") is True
    assert probe.captures[-1][-4:-2] == ["-t", "=NoList:"]
    assert probe.admissions == [{"session": "NoList", "pane": None}]
    assert "NoList" not in ob._question_proofs


def test_pure_legacy_admission_keeps_the_old_read(endpoint, monkeypatch):  # noqa: F811
    p = Probe(endpoint, helper=False)
    assert p.boundary.shared is None
    for cache in (ob._question_probe_cache, ob._question_proofs, ob._question_refusals):
        cache.clear()
    pane = p.new_session("Legacy")
    p.ask(pane)
    captured = []
    real_run = ob.subprocess.run

    def spy(argv, *a, **k):
        if "capture-pane" in argv:
            captured.append(list(argv))
        return real_run(argv, *a, **k)

    monkeypatch.setattr(ob.subprocess, "run", spy)
    assert p.run("Legacy") is True
    assert captured[-1][-4:-2] == ["-t", "=Legacy:"]
    assert "Legacy" not in ob._question_proofs
