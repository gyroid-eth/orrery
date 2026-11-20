"""Check the hover card's presentation against the telemetry field contract."""

import html
import json
from pathlib import Path
import re
import subprocess


SOURCE = (Path(__file__).resolve().parents[1] / "cockpit.html").read_text(encoding="utf-8")
RENDERER = SOURCE.split("const AGENT_DETAIL_HARNESSES=", 1)[1].split("function positionAgentDetail(", 1)[0]
ESCAPE = re.search(r"^function esc\(s\).*", SOURCE, re.MULTILINE).group()


def render(agent, home="/home/fixture"):
    script = (
        ESCAPE + "\nconst AGENT_DETAIL_HARNESSES=" + RENDERER
        + f"process.stdout.write(agentDetailHTML(agentDetailModel({json.dumps(agent)}, {json.dumps(home)})));"
    )
    return subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True, timeout=10).stdout


def test_card_displays_current_values_and_read_only_permissions():
    markup = render({
        "name": "FixtureAgent", "annot": {"role": "画像 <確認>"}, "parent_state": "child",
        "parent_agent": "FixtureParent", "computer_use": "off", "browser_use": False,
        "model_id": "fixture-model-id", "harness_kind": "codex", "effort": "xhigh",
        "ctx_window_tokens": 262144, "ctx_used": 0, "cwd": "/home/fixture/long directory/project",
    })
    expected_labels = (
        "Role: 画像 <確認>", "Parent: FixtureParent", "Computer use: Off", "Browser use: Off",
        "Model: fixture-model-id", "Harness: Codex CLI", "Effort: xhigh",
        "Context window: 262,144 tokens, 0% used", "Working directory: /home/fixture/long directory/project",
    )
    decoded = html.unescape(markup)
    for label in expected_labels:
        assert f'title="{label}" aria-label="{label}"' in decoded
    assert "画像 &lt;確認&gt;" in markup
    assert '<span class="current">Off</span>' in markup
    assert 'class="agent-detail-switch"' in markup
    assert "<strong>0%</strong>" in markup
    assert "~/<wbr>long directory/<wbr>project" in markup
    assert not re.search(r'<button|aria-checked|role="switch"|tabindex=', markup)


def test_unknown_fields_leave_no_rows_and_legacy_fields_never_render():
    markup = render({
        "name": "LegacyAgent", "cwd": None, "model_id": None, "effort": None,
        "ctx_window_tokens": None, "computer_use": None, "browser_use": None, "parent_state": None,
        "parent_agent": "Old parent", "live": "Old pane title", "instruction": {"subject": "Old mail"},
        "mail_active": 2, "observed_active": 2, "created": 2, "cmd": "Old runtime", "deliv": 4,
        "program": "codex", "model": "Old model", "ctx_window": "200K",
        "descriptor": {"primary": "Old description", "provenance": "Old source", "quality": "Old quality"},
    })
    assert markup.strip() == '<div class="agent-detail-name">LegacyAgent</div>'


def test_known_context_fields_render_independently_and_home_matches_on_a_path_boundary():
    partial = render({"name": "FixtureAgent", "parent_state": "top", "ctx_used": 27,
                      "cwd": "/home/fixture-other/project", "browser_use": True})
    assert 'aria-label="Top level"' in partial
    assert 'aria-label="Browser use: On"' in partial
    assert 'aria-label="Context window: 27% used"' in partial
    assert "tokens" not in partial
    assert "/<wbr>home/<wbr>fixture-other/<wbr>project" in partial
    assert "~" not in partial
    capacity_only = render({"name": "FixtureAgent", "ctx_window_tokens": 1000000, "cwd": "/home/fixture"})
    assert 'aria-label="Context window: 1,000,000 tokens"' in capacity_only
    assert "<span>1M</span>" in capacity_only
    assert "agent-detail-meter" not in capacity_only
    assert 'class="agent-detail-value agent-detail-directory">~</span>' in capacity_only
