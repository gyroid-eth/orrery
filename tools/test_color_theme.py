from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path


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
        "--bg": "#f5efe1",
        "--panel": "#e8dfcd",
        "--panel-2": "#ddd2bc",
        "--elev": "#d1c3a9",
        "--ink": "#010100",
        "--ink-dim": "#3a3528",
        "--ink-faint": "#545148",
        "--amber": "#704a00",
        "--amber-glow": "transparent",
        "--ln-local": "#005c50",
        "--ln-remote": "#673f8d",
        "--ln-delegate": "#335b16",
        "--theme-surface-terminal": "#fdf7ea",
        "--theme-status-alert": "#a6060e",
        "--theme-status-question": "#005a65",
        "--theme-border-control": "#5f5c52",
        "--theme-focus-ring": "#704a00",
        "--theme-ink-rgb": "1 1 0",
        "--theme-accent-rgb": "112 74 0",
        "--theme-local-rgb": "0 92 80",
        "--theme-remote-rgb": "103 63 141",
        "--theme-delegate-rgb": "51 91 22",
        "--eng-google": "#25576f",
        "--theme-google-rgb": "37 87 111",
        "--theme-alert-rgb": "166 6 14",
        "--theme-question-rgb": "0 90 101",
        "--hair": "rgb(1 1 0 / 0.16)",
        "--hair-2": "rgb(1 1 0 / 0.08)",
        "--theme-shadow-low": "rgb(1 1 0 / 0.12)",
        "--theme-shadow-high": "rgb(1 1 0 / 0.08)",
    }
    for role, measurement in result["report"].items():
        assert measurement["passes"], role
        assert measurement["ratio"] >= measurement["target"], role
    assert min(
        measurement["ratio"]
        for role, measurement in result["report"].items()
        if role != "control"
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
    assert result["theme"]["background"] == "#fdf7ea"
    assert result["theme"]["foreground"] == "#010100"


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
