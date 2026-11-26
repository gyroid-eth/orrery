"""Interactive Antigravity transcripts, using synthetic provider records only."""
import asyncio
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image

import conversation_history as history
from conversation_preview import ReferenceStore


SID = "12345678-1234-4321-8421-123456789abc"
STAMP = "2026-10-01T10:00:00Z"
SHOW_FILES_TRANSCRIPT = Path(__file__).parent / "fixtures/antigravity-show-files.jsonl"


def step(index, kind, source, content=None, **fields):
    return dict(step_index=index, type=kind, source=source, status="DONE",
                created_at=STAMP, content=content, **fields)


def line(item):
    return (json.dumps(item) + "\n").encode()


@pytest.fixture
def log(tmp_path):
    path = tmp_path.resolve() / "antigravity-cli/brain" / SID / ".system_generated/logs/transcript.jsonl"
    path.parent.mkdir(parents=True)
    items = [
        step(0, "USER_INPUT", "USER_EXPLICIT",
             "<USER_REQUEST>\nOne\n\nTwo\n</USER_REQUEST>\n<ADDITIONAL_METADATA>HIDDEN_META</ADDITIONAL_METADATA>"),
        step(1, "PLANNER_RESPONSE", "MODEL", thinking="HIDDEN_REASONING",
             tool_calls=[{"name": "read_file", "args": {"path": "/HIDDEN_PATH/notes.md"}}]),
        step(2, "GENERIC", "MODEL", "Created At: time\nCompleted At: time\nHIDDEN_RESULT"),
        step(3, "PLANNER_RESPONSE", "MODEL", "Fixture reply.", model="gemini-example"),
        step(4, "USER_INPUT", "USER_EXPLICIT", "<USER_REQUEST>\n /compact \n</USER_REQUEST>"),
        step(5, "CHECKPOINT", "SYSTEM", "HIDDEN_SUMMARY"),
        step(6, "SYSTEM_MESSAGE", "SYSTEM", "HIDDEN_SYSTEM"),
        step(7, "USER_INPUT", "SYSTEM", "<USER_REQUEST>\nHIDDEN_INJECTED\n</USER_REQUEST>"),
    ]
    path.write_bytes(b"".join(map(line, items)))
    row = dict(name="FixtureAgent", program="antigravity-cli", history_binding="bound",
               history_session_id=SID, history_receipt_ts=STAMP, transcript_path=str(path))
    return path, row


def page(row, **kwargs):
    with history.open_reader(row) as reader:
        return reader.read_page(**kwargs)


@pytest.mark.parametrize("server,expected", [
    ("orrery-mail", True), ("agentstack", True), ("unrelated", False), ("orrery_mail", False),
])
@pytest.mark.parametrize("filename,kind", [("comparison.png", "image"), ("report.md", "text")])
def test_native_mcp_file_chip_uses_only_an_explicit_orrery_call(tmp_path, log, server, expected, filename, kind):
    path, row = log
    shown = tmp_path / filename
    if kind == "image":
        Image.new("RGB", (32, 16), "teal").save(shown)
    else:
        shown.write_text("# Fixture report\n")
    # This file is outside all configured roots. It must be explicitly named
    # in the native call, even when a tool result mentions the same path.
    path.write_text(SHOW_FILES_TRANSCRIPT.read_text().replace("/fixture", str(tmp_path.resolve()))
                    .replace("comparison.png", filename)
                    .replace('"ServerName":"orrery-mail"', f'"ServerName":"{server}"'))
    store = ReferenceStore()
    with history.open_reader(row) as reader:
        events = reader.read_page()["events"]
        store.decorate_all(row, reader, events)
    calls = [event for event in events if event["kind"] == "tool"]
    assert [event["step"]["tool"].split("__")[-1] for event in calls] == ["read_file", "show_files"]
    assert [event["step"]["detail"] for event in calls] == ["notes.md", filename]
    assert all(event["step"]["status"] == "observed" for event in calls)
    assert "Sensitive result placeholder" not in json.dumps(events)
    assert all(not event.get("references") for event in events if event is not calls[1])
    assert bool(calls[1].get("references")) is expected
    if expected:
        assert calls[1]["text"] == "mcp__orrery_mail__show_files"
        ref, = calls[1]["references"]
        assert ref["label"] == filename
        for mobile in (False, True):
            result = store.read(ref["id"], row, mobile=mobile)
            assert result["kind"] == kind
            if kind == "text":
                assert result["text"] == "# Fixture report\n"


def test_uses_existing_cursor_pages_and_keeps_content_boundaries(log):
    _, row = log
    newest = page(row, limit=3)
    assert newest["has_older"] is True
    older = page(row, before=newest["before"], limit=3)
    events = older["events"] + newest["events"]
    assert [(e["kind"], e["role"], e["text"]) for e in events] == [
        ("text", "user", "One\n\nTwo"), ("tool", "assistant", "read_file"),
        ("tool_result", "assistant", "Tool result"), ("text", "assistant", "Fixture reply."),
        ("system", "system", "Context compacted"),
    ]
    assert events[3]["model"] == "gemini-example"
    assert events[1]["step"]["detail"] == "notes.md"
    assert "HIDDEN" not in json.dumps(events)
    assert len({e["id"] for e in events}) == len(events)


def test_after_cursor_waits_for_a_complete_append_and_includes_native_truncation(log):
    path, row = log
    before = page(row)
    new = line(step(8, "USER_INPUT", "USER_EXPLICIT", "<USER_REQUEST>\nHIDDEN_PARTIAL",
                    truncated_fields=["content"]))
    with path.open("ab") as stream:
        stream.write(new[:-1])
    assert not page(row, after=before["after"])["events"]
    with path.open("ab") as stream:
        stream.write(b"\n")
    events = page(row, after=before["after"])["events"]
    assert [(e["role"], e["text"], e["truncated"]) for e in events] == [
        ("user", "Input shortened by Antigravity.", True)]


def test_bare_compact_is_hidden_even_without_a_checkpoint_but_instructions_remain(log):
    path, row = log
    cursor = page(row)["after"]
    with path.open("ab") as stream:
        for index, request in enumerate(("/compact", "/compact Keep the example", "Explain /compact"), 8):
            stream.write(line(step(index, "USER_INPUT", "USER_EXPLICIT", f"<USER_REQUEST>\n{request}\n</USER_REQUEST>")))
    assert [e["text"] for e in page(row, after=cursor)["events"]] == [
        "/compact Keep the example", "Explain /compact"]


def test_rejects_wrong_native_session_or_unnegotiated_provider(log):
    _, row = log
    with pytest.raises(history.HistoryUnavailable, match="dashboard_upgrade_required"):
        history.bound_agent({"agents": [row]}, "FixtureAgent", api_generation=47)
    assert history.bound_agent({"agents": [row]}, "FixtureAgent", api_generation=48) == row
    with pytest.raises(history.HistoryUnavailable, match="invalid_binding"):
        page(dict(row, history_session_id="12345678-1234-4321-8421-123456789aba"))


def test_reads_the_full_transcript_when_the_official_hook_selects_it(log):
    path, row = log
    full = path.with_name("transcript_full.jsonl")
    path.rename(full)
    assert len(page(dict(row, transcript_path=str(full)))["events"]) == 5


def test_conversation_uses_api_48_binding_route(log, monkeypatch):
    import aiohttp
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    import orrery_backend as backend

    _, row = log

    async def check():
        upstream = web.Application()

        async def version(_):
            return web.json_response({"api": 48})

        async def binding(_):
            return web.json_response({"ok": True, "agent": row})

        upstream.router.add_get("/api/version", version)
        upstream.router.add_get("/api/agents/FixtureAgent/history-binding", binding)
        async with TestServer(upstream) as dash, aiohttp.ClientSession() as client:
            monkeypatch.setattr(backend, "DASHBOARD_URL", str(dash.make_url("/")).rstrip("/"))
            app = web.Application()
            app[backend.HTTP_SESSION_KEY] = client
            app[backend.TMUX_BIN_KEY] = "fixture-unused"
            app[backend.CONVERSATION_DASHBOARD_KEY] = {}
            app.router.add_get("/telemetry/conversation", backend.serve_conversation)
            async with TestClient(TestServer(app)) as browser:
                response = await browser.get("/telemetry/conversation", params={"agent": "FixtureAgent"})
                body = await response.json()
                assert response.status == 200, body
                assert body["provider"] == "antigravity" and len(body["events"]) == 5
                assert "transcript_path" not in json.dumps(body)

    asyncio.run(check())


def test_native_compacting_status_and_completion():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    source = Path(__file__).resolve().parents[1] / "reader_activity.js"
    test = r"""
const assert=require('node:assert/strict');
const {compaction}=require(process.argv[1]);
const status='\u28f7  Compacting conversation\u2026 (1m 2s \u00b7 esc to cancel)';
for(const alias of ['agy','antigravity','antigravity-cli','antigravity-agent']){
  assert.deepEqual(compaction(status,alias),{reader_phase:'compacting',reader_phase_elapsed:'1m 2s'});
  assert.equal(compaction(status+'\n\u2500\u2500 Conversation compacted \u2500\u2500',alias),null);
  assert.equal(compaction(status+'\nCompaction cancelled. Conversation was not compacted.',alias),null);
  assert.equal(compaction('Output: '+status,alias),null);
}
assert.equal(compaction(status,'codex'),null);
"""
    subprocess.run([node, "-e", test, str(source)], check=True)
