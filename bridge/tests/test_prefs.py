"""Shared cockpit preferences (bridge/orrery_backend.py prefs_* helpers).

Run from bridge/: ``python -m pytest tests/test_prefs.py``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from test_cockpit_tour import tour_browser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import orrery_backend as ob  # noqa: E402


def test_whitelist_keeps_preferences_and_drops_drafts_and_histories():
    assert ob.prefs_key_ok("oc-mini-view")
    assert ob.prefs_key_ok("oc-term-font")
    assert ob.prefs_key_ok("oc-term-conversation-enabled")
    assert ob.prefs_key_ok("oc-split-ratio-3-row")
    assert ob.prefs_key_ok("orrery.color-theme.v1")
    assert ob.prefs_key_ok("agentstack.theme-profile.v1.state")
    assert not ob.prefs_key_ok("agentstack.theme-profile.v1.history")
    assert not ob.prefs_key_ok("oc-prompt-draft")
    assert not ob.prefs_key_ok("oc-descriptor-task")
    assert not ob.prefs_key_ok("oc-last-activity")
    assert not ob.prefs_key_ok(42)
    assert not ob.prefs_key_ok("oc-mini-" + "x" * 200)


def test_merge_applies_set_and_remove_and_ignores_junk():
    current = {"oc-mini-view": "orrery", "oc-term-font": "12.5"}
    merged = ob.merge_prefs(current, {
        "set": {"oc-mini-view": "network", "oc-prompt-draft": "secret", "oc-term-autoshrink": True,
                "oc-mini-network-depth": "3"},
        "remove": ["oc-term-font", "never-there", 7],
    })
    assert merged == {"oc-mini-view": "network", "oc-mini-network-depth": "3"}
    assert current == {"oc-mini-view": "orrery", "oc-term-font": "12.5"}  # input untouched
    assert ob.merge_prefs(current, "not a dict") == current
    assert ob.merge_prefs(current, {"set": {"oc-mini-view": "x" * (ob.PREFS_MAX_VALUE + 1)}}) == current


def test_round_trip_through_the_file(tmp_path):
    path = tmp_path / "prefs.json"
    assert ob.read_prefs(path) == {}
    rev1 = ob.write_prefs({"oc-mini-view": "network", "oc-prompt-draft": "no"}, path)
    assert ob.read_prefs(path) == {"oc-mini-view": "network"}
    assert json.loads(path.read_text())["version"] == 1
    assert ob.prefs_rev(path) == rev1 and rev1 > 0
    path.write_text("{not json")
    assert ob.read_prefs(path) == {}


@pytest.fixture
def legacy_mini_startup(tmp_path):
    path = tmp_path / 'prefs.json'
    path.write_text(json.dumps({
        'version': 1,
        'prefs': {'oc-mini-view': 'network', 'oc-mini-network-depth': '3'},
    }), encoding='utf-8')
    return {
        'oc-mini-view': 'orrery', 'oc-mini-network-depth': '1', 'oc-mini-mail-graph': '1',
    }, ob.prefs_response(path).body


@pytest.mark.parametrize('tour_browser', ['legacy_mini_startup'], indirect=True)
def test_mail_links_default_to_keep_when_upgrading_saved_preferences(tour_browser):
    _, evaluate = tour_browser
    assert evaluate("OC.miniView()") == {'mode': 'network', 'depth': 3, 'mailLinks': 'keep'}
    assert evaluate("document.getElementById('miniMailLinks').value") == 'keep'
    assert evaluate("document.getElementById('mailGraphBtn').getAttribute('aria-expanded')") == 'true'
    assert evaluate("localStorage.getItem('oc-mini-mail-links')") is None
