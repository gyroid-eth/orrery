"""The link opener reports failures instead of answering "opened" (2026-09-25).

Run from bridge/: ``python -m pytest tests/test_opener.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import orrery_backend as ob  # noqa: E402


def test_a_failing_opener_is_an_error_with_its_message():
    with pytest.raises(OSError) as raised:
        ob.run_opener(["sh", "-c", "echo 'LSOpenURLsWithRole() failed' >&2; exit 1"])
    assert "exited 1" in str(raised.value)
    assert "LSOpenURLsWithRole() failed" in str(raised.value)


def test_a_successful_opener_returns():
    ob.run_opener(["true"])


def test_a_slow_opener_is_left_running_rather_than_blocking(monkeypatch):
    monkeypatch.setattr(ob, "OPENER_WAIT_SECONDS", 0.2)
    ob.run_opener(["sleep", "2"])


def test_reveal_reports_the_opener_failure(monkeypatch, tmp_path):
    def failing(argv):
        raise OSError("open exited 1: no window server")

    monkeypatch.setattr(ob, "run_opener", failing)
    with pytest.raises(OSError, match="no window server"):
        ob.reveal_in_finder(tmp_path)
