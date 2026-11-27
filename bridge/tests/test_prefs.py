"""Shared cockpit preferences (bridge/orrery_backend.py prefs_* helpers).

Run from bridge/: ``python -m pytest tests/test_prefs.py``.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_cockpit_tour import tour_browser
from test_conversation_review_regressions import cockpit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import orrery_backend as ob  # noqa: E402


def test_whitelist_keeps_preferences_and_drops_drafts_and_histories():
    assert ob.prefs_key_ok("oc-mini-view")
    assert ob.prefs_key_ok("oc-mini-network-default-v1")
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


@pytest.mark.asyncio
async def test_old_shared_layouts_migrate_once_and_keep_later_choices(tmp_path, monkeypatch):
    path = tmp_path / 'prefs.json'
    old = {'oc-mail-view': 'recipient', 'oc-mini-mail-graph': '0', 'oc-mini-view': 'orrery',
           'oc-mini-network-depth': '3'}
    ob.write_prefs(old, path)
    read, write, response = ob.read_prefs, ob.write_prefs, ob.prefs_response
    monkeypatch.setattr(ob, 'read_prefs', lambda _path=path: read(path))
    monkeypatch.setattr(ob, 'write_prefs', lambda value: write(value, path))
    monkeypatch.setattr(ob, 'prefs_response', lambda: response(path))

    async def change():
        return {'set': {'oc-mail-view': 'recipient', 'oc-mini-mail-graph': '0', 'oc-mini-view': 'orrery'}}

    request = SimpleNamespace(app={ob.PREFS_LOCK_KEY: asyncio.Lock()}, json=change)
    first = json.loads((await ob.serve_prefs(request)).body)
    markers = {'oc-mail-layout-v1': '1', 'oc-mini-network-default-v1': '1'}
    assert first['prefs'] == {**old, **markers, 'oc-mail-view': 'timeline', 'oc-mini-mail-graph': '1',
                              'oc-mini-view': 'network'}
    assert read(path) == first['prefs']
    await ob.update_prefs(request)
    second = json.loads((await ob.serve_prefs(request)).body)
    assert second['prefs'] == {**old, **markers}


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


def test_local_mini_view_changes_to_network_once_and_saves_a_later_choice(cockpit):
    js, wait, client, _, _ = cockpit
    wait("Boolean(window.OC)")
    assert js("OC.miniView().mode") == "network"
    client.call('Page.removeScriptToEvaluateOnNewDocument', identifier=js.storage_bootstrap)
    address = js('location.href')

    def reload():
        js("window.beforeMiniReload=true")
        client.call('Page.navigate', url=address)
        wait("!window.beforeMiniReload&&Boolean(window.OC)")

    js("""localStorage.removeItem('oc-mini-network-default-v1');
      localStorage.setItem('oc-mini-view','orrery');""")
    reload()
    assert js("OC.miniView().mode") == "network"
    assert js("localStorage.getItem('oc-mini-network-default-v1')") == "1"

    js("miniViewOrrery.click();OrreryPrefs.flush()")
    reload()
    assert js("OC.miniView().mode") == "orrery"
    assert js("miniViewOrrery.checked")

    js("""localStorage.setItem('oc-mini-view','network');
      document.dispatchEvent(new CustomEvent('oc:prefs-changed',{detail:{keys:['oc-mini-view']}}));""")
    assert js("OC.miniView().mode") == "network"
    assert js("miniViewNetwork.checked")
