from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "bridge" / "theme_core.js"
CONTROLLER = ROOT / "bridge" / "theme_controller.js"
LIGHT_CSS = ROOT / "bridge" / "theme_light.css"


def _node(script: str) -> dict:
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return json.loads(result.stdout)


def test_warm_paper_dom_and_control_contrast_contract():
    result = _node(
        """
const core=require('./bridge/theme_core.js');
const theme=core.deriveWarmPaperLightTheme();
process.stdout.write(JSON.stringify({vars:theme.cssVariables,report:core.contrastReport(theme)}));
"""
    )
    assert result["vars"] == {
        "--bg": "#f8f6f1",
        "--panel": "#fdfcf8",
        "--panel-2": "#f1eee7",
        "--elev": "#f1eee7",
        "--ink": "#25231f",
        "--ink-dim": "#615e55",
        "--ink-faint": "#615e55",
        "--amber": "#895c00",
        "--amber-glow": "transparent",
        "--ln-local": "#005c50",
        "--ln-remote": "#673f8d",
        "--ln-delegate": "#335b16",
        "--theme-surface-terminal": "#fdfcf8",
        "--theme-status-alert": "#a6060e",
        "--theme-status-question": "#005a65",
        "--theme-border-control": "#838179",
        "--theme-focus-ring": "#895c00",
        "--theme-accent-edge": "#ac7500",
        "--theme-accent-fill": "#f2b65a",
        "--theme-ink-rgb": "37 35 31",
        "--theme-accent-rgb": "137 92 0",
        "--theme-local-rgb": "0 92 80",
        "--theme-remote-rgb": "103 63 141",
        "--theme-delegate-rgb": "51 91 22",
        "--eng-google": "#25576f",
        "--theme-google-rgb": "37 87 111",
        "--theme-alert-rgb": "166 6 14",
        "--theme-question-rgb": "0 90 101",
        "--hair": "rgb(37 35 31 / 0.26)",
        "--hair-2": "rgb(37 35 31 / 0.16)",
        "--theme-shadow-low": "rgb(37 35 31 / 0.12)",
        "--theme-shadow-high": "rgb(37 35 31 / 0.08)"
    }
    for role, measurement in result["report"].items():
        assert measurement["passes"], role
        assert measurement["ratio"] >= measurement["target"], role
    assert min(
        measurement["ratio"]
        for role, measurement in result["report"].items()
        if role not in {"control", "accentEdge"}
    ) >= 4.5
    assert result["report"]["control"]["ratio"] >= 3


def test_xterm_ansi_16_palette_is_readable_on_terminal_surface():
    result = _node(
        """
const core=require('./bridge/theme_core.js');
const theme=core.deriveWarmPaperLightTheme();
const parse=value=>[1,3,5].map(offset=>parseInt(value.slice(offset,offset+2),16));
const background=parse(theme.terminalTheme.background);
const textRoles=['foreground','cursor','black','brightBlack','red','brightRed','green',
  'brightGreen','yellow','brightYellow','blue','brightBlue','magenta','brightMagenta',
  'cyan','brightCyan','white','brightWhite'];
const ratios=Object.fromEntries(textRoles.map(role=>[
  role,core.contrast(parse(theme.terminalTheme[role]),background)
]));
process.stdout.write(JSON.stringify({theme:theme.terminalTheme,ratios}));
"""
    )
    assert set(result["ratios"]) == {
        "foreground",
        "cursor",
        "black",
        "brightBlack",
        "red",
        "brightRed",
        "green",
        "brightGreen",
        "yellow",
        "brightYellow",
        "blue",
        "brightBlue",
        "magenta",
        "brightMagenta",
        "cyan",
        "brightCyan",
        "white",
        "brightWhite",
    }
    for role, ratio in result["ratios"].items():
        assert ratio >= 4.5, role
    assert result["theme"]["background"] == "#fdfcf8"
    assert result["theme"]["foreground"] == "#25231f"


def test_light_stylesheet_cannot_mutate_physical_dark_default():
    source = LIGHT_CSS.read_text(encoding="utf-8")
    without_comments = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    selectors = re.findall(r"(?:^|\})([^{}]+)\{", without_comments)
    assert selectors
    for selector_group in selectors:
        assert all(
            selector.strip().startswith('html[data-color-theme="light"]')
            for selector in selector_group.split(",")
        ), selector_group
    assert "color-scheme:light" in source
    assert "--theme-border-control" in source
    assert ".screen .glassglow{display:none}" in source


def test_controller_keeps_dark_as_storage_fallback_and_supports_system():
    source = CONTROLLER.read_text(encoding="utf-8")
    assert "let preference='dark'" in source
    assert "new Set(['dark','light','system'])" in source
    assert "prefers-color-scheme: light" in source
    assert "root.removeAttribute('data-color-theme')" in source
    assert "localStorage.getItem(STORAGE_KEY)" in source
    assert "localStorage.setItem(STORAGE_KEY,value)" in source
    assert "orrery-color-theme-change" in source
    assert "orrery-color-theme'" in source
    assert "orrery-color-theme-ready" in source
    assert "orrery-color-theme-telemetry-result" in source
    assert "location.origin" in source


def test_color_theme_javascript_has_valid_syntax():
    for path in (CORE, CONTROLLER):
        subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )


def test_mobile_telemetry_shares_the_cockpit_palette():
    telemetry_core = os.environ.get("ORRERY_TELEMETRY_THEME_CORE")
    if not telemetry_core:
        pytest.skip("set ORRERY_TELEMETRY_THEME_CORE to dashboard/theme_core.js")
    result = _node(
        f'''
const cockpit=require('./bridge/theme_core.js').deriveWarmPaperLightTheme();
const telemetry=require({json.dumps(str(Path(telemetry_core).resolve()))}).deriveWarmPaperLightTheme();
process.stdout.write(JSON.stringify({{cockpit:cockpit.cssVariables,telemetry:telemetry.cssVariables}}));
'''
    )
    cockpit, telemetry = result["cockpit"], result["telemetry"]
    # Shared UI roles used by both the desktop and mobile implementations.
    shared = {
        "--bg", "--panel", "--panel-2", "--elev", "--ink", "--ink-dim",
        "--ink-faint", "--amber", "--theme-accent-fill", "--theme-accent-edge",
        "--theme-focus-ring", "--theme-border-control", "--theme-surface-terminal",
        "--theme-ink-rgb", "--theme-accent-rgb", "--theme-shadow-low", "--theme-shadow-high",
        "--hair", "--hair-2", "--ln-local", "--ln-remote", "--ln-delegate",
        "--theme-status-alert", "--theme-status-question",
    }
    assert {key: cockpit[key] for key in shared} == {key: telemetry[key] for key in shared}
