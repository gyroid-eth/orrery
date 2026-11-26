"""Check the hover card's presentation against the telemetry field contract."""

import html
import json
from pathlib import Path
import re
import subprocess


SOURCE = (Path(__file__).resolve().parents[1] / "cockpit.html").read_text(encoding="utf-8")
RENDERER = SOURCE.split("const AGENT_DETAIL_HARNESSES=", 1)[1].split("function positionAgentDetail(", 1)[0]
ESCAPE = re.search(r"^function esc\(s\).*", SOURCE, re.MULTILINE).group()


def render(agent, home="/home/fixture", api=45):
    script = (
        ESCAPE + "\nconst AGENT_DETAIL_HARNESSES=" + RENDERER
        + f"process.stdout.write(agentDetailHTML(agentDetailModel({json.dumps(agent)}, {json.dumps(home)}, [], {api})));"
    )
    return subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True, timeout=10).stdout


def test_card_displays_current_values_and_permission_controls():
    markup = render({
        "name": "FixtureAgent", "annot": {"role": "画像 <確認>"}, "parent_state": "child",
        "parent_agent": "FixtureParent", "computer_use": "off", "browser_use": False,
        "model_id": "fixture-model-id", "harness_kind": "codex", "effort": "xhigh",
        "category": "retired", "running": False, "history_binding": "bound",
        "history_session_id": "01234567-1234-1234-1234-012345678901", "resume_capability": "ready",
        "ctx_window_tokens": 262144, "ctx_used": 0, "cwd": "/home/fixture/long directory/project",
    })
    expected_labels = (
        "Role: 画像 <確認>", "Parent: FixtureParent",
        "Model: fixture-model-id", "Harness: Codex CLI", "Effort: xhigh",
        "Context window: 262,144 tokens, 0% used", "Working directory: /home/fixture/long directory/project",
    )
    decoded = html.unescape(markup)
    for label in expected_labels:
        assert f'title="{label}" aria-label="{label}"' in decoded
    assert "画像 &lt;確認&gt;" in markup
    assert 'data-computer="off" aria-pressed="true"' in markup
    assert 'data-computer="control" aria-pressed="false"' in markup
    assert 'aria-label="Computer use: Off" title="Computer use: Off"' in markup
    assert 'role="switch" aria-checked="false"' in markup
    assert 'aria-label="Browser use" title="Browser use: Off"' in markup
    assert 'class="agent-detail-switch"' in markup
    assert "<strong>0%</strong>" in markup
    assert "~/<wbr>long directory/<wbr>project" in markup
    assert ' disabled' not in markup


def test_unsupported_agents_explain_why_controls_are_disabled():
    base = {"name": "FixtureAgent", "category": "retired", "running": False, "parent_state": "child",
            "harness_kind": "claude", "history_binding": "bound", "browser_use": True,
            "history_session_id": "01234567-1234-1234-1234-012345678901", "resume_capability": "ready"}
    for fields, reason in [
        ({"lifecycle": "persistent"}, "Persistent agent"),
        ({"parent_state": "top"}, "Standalone agent"),
        ({"surface": "codex-app"}, "Codex App"),
        ({"harness_kind": "dsh"}, "Requires a Claude Code or Codex CLI child"),
        ({"harness_kind": "hermes"}, "Requires a Claude Code or Codex CLI child"),
        ({"category": "agent", "running": True, "history_binding": "pending"}, "No verified child conversation"),
        ({"category": "finished"}, "Exit this agent first"),
        ({"resume_mode": "conversation_only"}, "Conversation-only resume has no saved permissions"),
        ({"history_binding": "unbound"}, "No verified child conversation"),
        ({"running": False, "resume_capability": "no_history"}, "Conversation cannot be resumed"),
    ]:
        markup = render(base | fields)
        assert 'data-computer' not in markup and 'data-browser' not in markup
        assert f'title="Browser use: On ({reason})"' in markup
        assert f'>{reason}</small>' in markup
    assert 'title="Browser use: On (Requires Telemetry API 45)"' in render(base, api=44)


def test_running_child_can_change_permissions_even_when_resume_is_not_required_yet():
    markup = render({
        "name": "FixtureAgent", "category": "agent", "running": True, "parent_state": "child",
        "harness_kind": "codex", "history_binding": "bound", "browser_use": False,
        "history_session_id": "01234567-1234-1234-1234-012345678901", "resume_capability": "not_required",
    })
    assert 'aria-label="Browser use" title="Browser use: Off"' in markup
    assert ' disabled' not in markup


def test_antigravity_card_discloses_launch_permissions_and_a_reason_for_unknown():
    markup = render({
        "name": "FixtureAgent", "category": "agent", "running": True, "parent_state": "top",
        "harness_kind": "antigravity", "computer_use": "view", "browser_use": None,
        "browser_use_reason": "Antigravity browser mode was not recorded",
    }, api=53)
    assert 'title="Harness: Antigravity"' in markup
    assert 'data-computer' not in markup
    assert '<span>View</span>' in markup
    assert 'Browser use: Unknown (Antigravity browser mode was not recorded)' in markup


def test_antigravity_card_labels_the_relay_and_the_recorded_browser_separately():
    markup = render({
        "name": "FixtureAgent", "category": "agent", "running": True, "parent_state": "top",
        "harness_kind": "antigravity", "computer_use": "view", "computer_use_source": "relay",
        "browser_use": False, "browser_use_source": "launch",
    }, api=53)
    assert 'aria-label="Computer use: View (Current screen relay)"' in markup
    assert 'aria-label="Browser use: Off (ORRERY launch selection)"' in markup


def test_api46_permission_reason_is_rendered_as_text():
    markup = render({
        "name": "FixtureAgent", "category": "agent", "running": True, "parent_state": "top",
        "harness_kind": "claude", "browser_use": True, "permission_resume_supported": False,
        "permission_resume_reason": 'Missing "settings" <details>',
    }, api=46)
    assert 'title="Browser use: On (Missing &quot;settings&quot; &lt;details&gt;)"' in markup
    assert 'data-computer' not in markup and 'data-browser' not in markup


def test_permission_controls_can_offer_only_one_action_and_keep_display_evidence():
    agent = {
        "name": "FixtureAgent", "running": True, "harness_kind": "dsh",
        "computer_use": "off", "browser_use": True,
        "permission_controls": {
            "computer_use": {"value": "view", "source": "relay", "can_change": True, "action": "restart"},
            "browser_use": {"value": False, "source": "launch", "can_change": False,
                            "change_reason": "Browser needs human setup"},
        },
    }
    markup = render(agent, api=54)
    assert 'data-computer="view" aria-pressed="true"' in markup
    assert 'data-browser' not in markup
    assert 'Browser needs human setup</small>' in markup
    assert 'title="Browser use: Off (ORRERY launch selection)"' in markup


def test_api54_keeps_legacy_values_read_only_without_a_server_verdict():
    markup = render({
        "name": "FixtureAgent", "running": True, "harness_kind": "codex",
        "category": "agent", "parent_state": "child", "history_binding": "bound",
        "history_session_id": "known", "computer_use": "control",
    }, api=54)
    assert 'data-computer' not in markup
    assert '<span>Control</span>' in markup
    assert '>Permission information unavailable</small>' in markup


def test_api54_shows_the_browser_mode_as_text_on_the_change_button():
    markup = render({
        "name": "FixtureAgent", "running": True, "harness_kind": "codex",
        "permission_controls": {
            "browser_use": {"value": True, "mode": "temporary", "options": ["off", "temporary", "personal"],
                            "can_change": True, "action": "restart"},
        },
    }, api=54)
    assert 'data-browser' in markup
    assert 'Temporary Chrome</button>' in markup
    assert 'role="switch"' not in markup


def test_live_process_observations_show_unknown_and_reason_without_controls():
    agent = {
        "name": "FixtureAgent", "running": True, "harness_kind": "claude",
        "permission_source": "process", "computer_use": None, "browser_use": True,
        "computer_use_reason": "Screen relay mode could not be verified",
    }
    markup = render(agent, api=52)
    assert 'aria-label="Computer use: Unknown (Screen relay mode could not be verified)"' in markup
    assert '<small>Screen relay mode could not be verified</small>' in markup
    assert 'aria-label="Browser use: On (' in markup
    assert 'data-browser' not in markup and 'data-computer' not in markup


def test_shared_unknown_reason_appears_once_visibly():
    reason = "Agent process could not be verified"
    markup = render({
        "name": "FixtureAgent", "running": True, "harness_kind": "codex",
        "permission_source": "process", "computer_use_reason": reason, "browser_use_reason": reason,
    }, api=52)
    assert markup.count(">Unknown</span>") == 2
    assert markup.count(f'>{reason}</small>') == 1


def test_unknown_fields_leave_no_rows_and_legacy_fields_never_render():
    markup = render({
        "name": "LegacyAgent", "cwd": None, "model_id": None, "effort": None,
        "ctx_window_tokens": None, "computer_use": None, "browser_use": None, "parent_state": None,
        "parent_agent": "Old parent", "live": "Old pane title", "instruction": {"subject": "Old mail"},
        "mail_active": 2, "observed_active": 2, "created": 2, "cmd": "Old runtime", "deliv": 4,
        "program": "codex", "model": "Old model", "ctx_window": "200K",
        "descriptor": {"primary": "Old description", "provenance": "Old source", "quality": "Old quality"},
    })
    assert markup.strip() == '<div class="agent-detail-name" id="agentDetailName">LegacyAgent</div>'


def test_known_context_fields_render_independently_and_home_matches_on_a_path_boundary():
    partial = render({"name": "FixtureAgent", "parent_state": "top", "ctx_used": 27,
                      "cwd": "/home/fixture-other/project", "browser_use": True})
    assert 'aria-label="Top level"' in partial
    assert 'aria-label="Browser use: On (Standalone agent)"' in partial
    assert 'aria-label="Context window: 27% used"' in partial
    assert "tokens" not in partial
    assert "/<wbr>home/<wbr>fixture-other/<wbr>project" in partial
    assert "~" not in partial
    capacity_only = render({"name": "FixtureAgent", "ctx_window_tokens": 1000000, "cwd": "/home/fixture"})
    assert 'aria-label="Context window: 1,000,000 tokens"' in capacity_only
    assert "<span>1M</span>" in capacity_only
    assert "agent-detail-meter" not in capacity_only
    assert 'class="agent-detail-value agent-detail-directory">~</span>' in capacity_only
