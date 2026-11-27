import os
from pathlib import Path

import pytest

from tools import theme_axis_browser_test


ROOT = Path(__file__).resolve().parents[1]
COCKPIT = ROOT / "bridge" / "cockpit.html"
FIXTURE = ROOT / "tools" / "fixtures" / "theme_axis_adversarial.js"


def test_theme_axis_inventory_removed_from_cockpit():
    source = COCKPIT.read_text()

    assert "agentstack-theme-axis-inventory" not in source
    assert "THEME_AXIS_SOURCE_INVENTORY" not in source
    assert "themeAxisSourceCoverage" not in source


def test_theme_axis_css_and_apply_wired_into_cockpit():
    source = COCKPIT.read_text()

    for selector in (
        ':root[data-theme-axis="dim-contrast"]',
        ':root[data-theme-axis="background"]',
        'html[data-theme-axis="glow"]',
        'html[data-theme-small-text="true"]',
        'html[data-theme-tracking="true"]',
    ):
        assert selector in source
    assert "function setThemeAxis(" in source
    assert "function applyThemeAxisState(" in source
    assert "THEME_GLOW_EFFECT_MANIFEST" in source


def test_browser_fixture_exercises_all_five_axes_without_inventory():
    source = FIXTURE.read_text()

    assert "setThemeAxis" in source
    assert "THEME_AXIS_IDS" in source
    assert "THEME_AXIS_SOURCE_INVENTORY" not in source


@pytest.mark.skipif(
    os.environ.get("ORRERY_THEME_BROWSER") != "1",
    reason="set ORRERY_THEME_BROWSER=1 to run the real Chromium theme-axis effect check",
)
def test_theme_axis_effect_in_real_browser():
    result = theme_axis_browser_test.run_browser_contract()
    theme_axis_browser_test.assert_browser_contract(result)
