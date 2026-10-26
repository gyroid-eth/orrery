import json
import os
from pathlib import Path

import pytest

from tools import theme_axis_browser_test


ROOT = Path(__file__).resolve().parents[1]
COCKPIT = ROOT / "bridge" / "cockpit.html"
FIXTURE = ROOT / "tools" / "fixtures" / "theme_axis_adversarial.js"
INVENTORY = ROOT / "tools" / "fixtures" / "theme_axis_inventory.json"


def test_effect_guard_contract_is_wired_into_cockpit():
    source = COCKPIT.read_text()

    assert "visibleReached" in source
    assert "effect.visibleReached!==effect.visibleExpected" in source
    assert "effect.visibleChanged<=0" in source
    assert "THEME_AXIS_LENGTH_EPSILON=.002" in source
    assert "THEME_AXIS_COMMITTED_STYLE_SHEETS" in source


def test_adversarial_fixture_uses_integrated_css_paths():
    source = FIXTURE.read_text()

    assert "Number.MIN_VALUE" in source
    assert "!important" in source
    assert "beforeMembership" in source and "afterMembership" in source
    assert "visibility:hidden!important" in source
    assert "translate(-20000px,-20000px)!important" in source
    assert "setThemeAxis" in source


def test_axis_inventory_units_are_exact():
    inventory = json.loads(INVENTORY.read_text())["axes"]
    source_units = {
        "dim-contrast": "token-write",
        "small-text": "declaration",
        "tracking": "declaration",
        "glow": "declaration",
        "background": "token-write",
    }
    mutation_units = {
        "dim-contrast": "token-write",
        "small-text": "element",
        "tracking": "element",
        "glow": "effect-component",
        "background": "token-write",
    }
    for axis in source_units:
        assert inventory[axis]["source"]["unit"] == source_units[axis]
        assert inventory[axis]["mutation"]["unit"] == mutation_units[axis]


@pytest.mark.skipif(
    os.environ.get("ORRERY_THEME_BROWSER") != "1",
    reason="set ORRERY_THEME_BROWSER=1 to run the real Chromium guard contract",
)
def test_theme_axis_guard_in_real_browser():
    result = theme_axis_browser_test.run_browser_contract()
    theme_axis_browser_test.assert_browser_contract(result)
