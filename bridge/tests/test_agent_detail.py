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
        assert markup.count(' disabled') == 4
        assert f'title="Browser use: On ({reason})"' in markup
    assert 'title="Browser use: On (Requires Telemetry API 45)"' in render(base, api=44)


def test_running_child_can_change_permissions_even_when_resume_is_not_required_yet():
    markup = render({
        "name": "FixtureAgent", "category": "agent", "running": True, "parent_state": "child",
        "harness_kind": "codex", "history_binding": "bound", "browser_use": False,
        "history_session_id": "01234567-1234-1234-1234-012345678901", "resume_capability": "not_required",
    })
    assert 'aria-label="Browser use" title="Browser use: Off"' in markup
    assert ' disabled' not in markup


def test_api46_permission_reason_is_rendered_as_text():
    markup = render({
        "name": "FixtureAgent", "category": "agent", "running": True, "parent_state": "top",
        "harness_kind": "claude", "browser_use": True, "permission_resume_supported": False,
        "permission_resume_reason": 'Missing "settings" <details>',
    }, api=46)
    assert 'title="Browser use: On (Missing &quot;settings&quot; &lt;details&gt;)"' in markup
    assert markup.count(' disabled') == 4


def test_values_read_from_the_process_mark_what_the_next_start_changes():
    agent = {
        "name": "FixtureAgent", "category": "agent", "running": True, "parent_state": "top",
        "harness_kind": "claude", "computer_use": "off", "computer_use_next": "control",
        "browser_use": True, "browser_use_next": False, "permission_source": "process",
        "permission_resume_supported": False, "permission_resume_reason": "No saved launch settings; use Resume",
    }
    markup = render(agent, api=46)
    assert 'aria-label="Computer use. Restart to apply: Control"' in markup
    assert 'title="Computer use: Off. Restart to apply: Control (No saved launch settings; use Resume)"' in markup
    assert re.search(r'data-computer="control"[^>]*aria-label="Computer use: Control \(restart to apply\)"[^>]*class="next"', markup)
    assert re.search(r'data-computer="off"[^>]*class="current"', markup)
    assert 'aria-label="Browser use: On. Restart to apply: Off"' in markup
    assert markup.count('class="agent-detail-pending"') == 2
    same = render({**agent, "computer_use_next": "off", "browser_use_next": True}, api=46)
    assert "agent-detail-pending" not in same and "Restart to apply" not in same and 'class="next"' not in same
    unknown = render({**agent, "computer_use": None, "browser_use": None}, api=46)
    assert "Restart to apply" not in unknown


def test_a_saved_choice_for_the_next_start_can_be_changed_without_a_restart():
    agent = {
        "name": "FixtureAgent", "category": "agent", "running": True, "lifecycle": "persistent",
        "harness_kind": "claude", "computer_use": "off", "computer_use_next": "control", "browser_use": True,
        "permission_save_supported": True, "permission_apply": "next_start",
        "permission_resume_supported": False, "permission_resume_reason": "Persistent agents cannot change permissions on resume",
    }
    markup = render(agent, api=52)
    assert " disabled" not in markup
    assert 'title="Computer use: Off. Restart to apply: Control (Saved for the next start)"' in markup
    # An older Telemetry without the save endpoint keeps the controls closed.
    assert render(agent, api=51).count(" disabled") == 4


def test_a_stopped_agent_shows_what_its_next_start_gets():
    markup = render({
        "name": "FixtureAgent", "category": "gone", "running": False, "harness_kind": "claude",
        "computer_use": None, "computer_use_next": "view", "browser_use": None, "browser_use_next": True,
        "history_binding": "bound", "history_session_id": "01234567-1234-1234-1234-012345678901",
        "resume_capability": "ready", "permission_save_supported": True, "permission_apply": "resume",
        "permission_resume_supported": True, "permission_resume_reason": "",
    }, api=52)
    assert 'title="Computer use: Unknown. Next start: View"' in markup
    assert 'aria-label="Browser use: Unknown. Next start: On"' in markup
    assert " disabled" not in markup


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
    assert 'aria-label="Browser use" title="Browser use: On (Standalone agent)"' in partial
    assert 'aria-label="Context window: 27% used"' in partial
    assert "tokens" not in partial
    assert "/<wbr>home/<wbr>fixture-other/<wbr>project" in partial
    assert "~" not in partial
    capacity_only = render({"name": "FixtureAgent", "ctx_window_tokens": 1000000, "cwd": "/home/fixture"})
    assert 'aria-label="Context window: 1,000,000 tokens"' in capacity_only
    assert "<span>1M</span>" in capacity_only
    assert "agent-detail-meter" not in capacity_only
    assert 'class="agent-detail-value agent-detail-directory">~</span>' in capacity_only
