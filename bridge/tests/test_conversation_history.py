"""Provider records and cursors: no live provider, tmux, or dashboard state."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import conversation_history as history
import orrery_backend as backend


def record(text, role="assistant", **payload):
    return (json.dumps(dict(timestamp="2026-11-04T04:00:00Z", type="response_item",
        payload=dict(type="message", role=role, content=[dict(type="output_text", text=text)], **payload)))+"\n").encode()


def test_pages_cover_each_record_once_and_incremental_reads_wait_for_complete_lines(tmp_path):
    file = tmp_path / "rollout.jsonl"
    file.write_bytes(b"".join(record(str(i)) for i in range(13)))
    page = history.read_codex_page(str(file), limit=4)
    assert [e["text"] for e in page["events"]] == ["9", "10", "11", "12"]
    after = page["after"]
    values = [e["text"] for e in page["events"]]
    while page["has_older"]:
        page = history.read_codex_page(str(file), before=page["before"], limit=4)
        values = [e["text"] for e in page["events"]] + values
    assert values == [str(i) for i in range(13)]
    addition = record("new 日本語")
    with file.open("ab") as stream:
        stream.write(addition[:-3])
    page = history.read_codex_page(str(file), after=after)
    assert page["events"] == []
    assert page["after"] == after
    with file.open("ab") as stream:
        stream.write(addition[-3:])
    page = history.read_codex_page(str(file), after=page["after"])
    assert [e["text"] for e in page["events"]] == ["new 日本語"]
    assert not page["has_newer"]


def test_tool_names_only_no_arguments_results_reasoning_or_developer_content(tmp_path):
    file = tmp_path / "rollout.jsonl"
    raw = [record("visible"), record("private", "developer"), record("private", phase="analysis")]
    for kind in ["function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output", "reasoning"]:
        raw.append((json.dumps(dict(type="response_item", payload=dict(type=kind, name="functions.exec",
            arguments="SECRET_ARGUMENT", input="SECRET_INPUT", output="SECRET_OUTPUT", encrypted_content="SECRET_REASONING")))+"\n").encode())
    raw += [b"broken json\n", b'{"type":"event_msg","payload":{"type":"agent_message","message":"duplicate"}}\n']
    file.write_bytes(b"".join(raw))
    page = history.read_codex_page(str(file))
    assert [e["text"] for e in page["events"]] == ["visible", "functions.exec", "functions.exec"]
    assert "SECRET" not in json.dumps(page)


def test_file_replacement_foreign_cursor_and_truncation_fail_closed(tmp_path):
    one = tmp_path / "one.jsonl"
    two = tmp_path / "two.jsonl"
    one.write_bytes(record("first"))
    two.write_bytes(record("second"))
    cursor = history.read_codex_page(str(one))["after"]
    with pytest.raises(history.HistoryUnavailable, match="history_changed"):
        history.read_codex_page(str(two), after=cursor)
    replacement = tmp_path / "replacement.jsonl"
    replacement.write_bytes(record("replacement"))
    replacement.replace(one)
    with pytest.raises(history.HistoryUnavailable, match="history_changed"):
        history.read_codex_page(str(one), after=cursor)
    cursor = history.read_codex_page(str(one))["after"]
    one.write_bytes(b"")
    with pytest.raises(history.HistoryUnavailable, match="history_changed"):
        history.read_codex_page(str(one), after=cursor)


def test_bound_reader_rejects_symlink_and_pins_file_across_binding_recheck(tmp_path):
    good = tmp_path / "good.jsonl"
    other = tmp_path / "other.jsonl"
    link = tmp_path / "link.jsonl"
    good.write_bytes(record("BOUND_FIXTURE"))
    other.write_bytes(record("UNBOUND_FIXTURE"))
    link.symlink_to(good)
    with pytest.raises(history.HistoryUnavailable):
        history.read_codex_page(str(link))
    with history.open_bound_transcript(str(good)) as stream:
        moved = tmp_path / "moved.jsonl"
        good.rename(moved)
        other.rename(good)
        # Read only the pinned original, or reject the identity change.
        with pytest.raises(history.HistoryUnavailable, match="history_changed"):
            history.read_codex_page(str(good), stream=stream)


def test_scan_budget_paginates_past_non_message_records(tmp_path, monkeypatch):
    file = tmp_path / "rollout.jsonl"
    data = b"".join(record(str(i)) for i in range(10))
    file.write_bytes(data)
    monkeypatch.setattr(history, "MAX_SCAN", 400)
    page = history.read_codex_page(str(file), limit=100)
    found = [e["text"] for e in page["events"]]
    for _ in range(30):
        if not page["has_older"]:
            break
        page = history.read_codex_page(str(file), before=page["before"], limit=100)
        found = [e["text"] for e in page["events"]] + found
    assert found == [str(i) for i in range(10)]


def test_scan_window_exactly_on_record_boundary_keeps_first_record(tmp_path, monkeypatch):
    file = tmp_path / "rollout.jsonl"
    file.write_bytes(b"".join(record(str(i)) for i in range(6)))
    monkeypatch.setattr(history, "MAX_SCAN", len(record("1")) * 3)
    page = history.read_codex_page(str(file))
    assert [e["text"] for e in page["events"]] == ["3", "4", "5"]


def test_text_is_bounded_and_images_are_not_loaded(tmp_path):
    file = tmp_path / "rollout.jsonl"
    file.write_bytes(record("x" * (history.MAX_TEXT + 3)))
    event = history.read_codex_page(str(file))["events"][0]
    assert len(event["text"]) == history.MAX_TEXT and event["truncated"]
    raw = json.dumps(dict(type="response_item", payload=dict(type="message", role="user",
        content=[dict(type="input_image", image_url="DO_NOT_FETCH")]))).encode()
    assert history.codex_event(raw, 0)["text"] == "\n[image attachment]"


async def start(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


def run_api(tmp_path, monkeypatch, scenario, *, row_update=None, fresh=False, change_binding=False):
    async def main():
        file = tmp_path / "bound.jsonl"
        file.write_bytes(record("bound conversation"))
        row = dict(name="BoundAgent", program="codex", history_binding="bound", transcript_path=str(file))
        row.update(row_update or {})
        reads = []
        async def agents(request):
            reads.append(request.path_qs)
            result = dict(row)
            if change_binding and len(reads) > 1:
                result["transcript_path"] = str(tmp_path / "other.jsonl")
            return web.json_response(dict(agents=[result]))
        class Fresh:
            def resolve(self, name, ref=None):
                assert name == "BoundAgent"
                return type("Target", (), dict(revision="a" * 64, ref=dict(mail_instance_id="f" * 32, mail_agent_id=7)))()
        async def fresh_history(request):
            reads.append(request.path_qs)
            assert set(request.query) == {"session", "mail_instance_id", "mail_agent_id", "limit"}
            return web.json_response(dict(ok=True, source="codex", history_binding="bound", has_more=True,
                mail_instance_id="f" * 32, mail_agent_id=7,
                events=[dict(role="assistant", kind="text", ts="2026-11-04T04:00:00Z", text="projected text")]))
        upstream = web.Application()
        upstream.router.add_get("/api/agents", agents)
        upstream.router.add_get("/api/history", fresh_history)
        upstream_runner, upstream_url = await start(upstream)
        monkeypatch.setattr(backend, "DASHBOARD_URL", upstream_url)
        if fresh:
            monkeypatch.setattr(backend, "FreshTargetBoundary", Fresh)
        app = web.Application(middlewares=[backend.own_page_only, backend.json_writes_only])
        app[backend.HTTP_SESSION_KEY] = ClientSession()
        app[backend.TMUX_BIN_KEY] = Fresh() if fresh else object()
        app.router.add_get("/telemetry/conversation", backend.serve_conversation)
        runner, url = await start(app)
        try:
            async with ClientSession() as client:
                await scenario(client, url, reads)
        finally:
            await runner.cleanup()
            await app[backend.HTTP_SESSION_KEY].close()
            await upstream_runner.cleanup()
    asyncio.run(main())


def test_api_reads_only_bound_path_and_revalidates_binding(tmp_path, monkeypatch):
    async def scenario(client, url, reads):
        async with client.get(url + "/telemetry/conversation?agent=BoundAgent") as response:
            payload = await response.json()
            assert response.status == 200
            assert payload["events"][0]["text"] == "bound conversation"
            assert response.headers["Cache-Control"] == "no-store"
            assert "transcript_path" not in payload and "file" not in payload
        assert len(reads) == 2
    run_api(tmp_path, monkeypatch, scenario)


@pytest.mark.parametrize("query", [
    "agent=BoundAgent&path=/tmp/unrelated.jsonl", "agent=BoundAgent&transcript_path=/tmp/unrelated.jsonl",
    "agent=BoundAgent&agent=Other", "agent=../Other", "agent=BoundAgent&limit=0",
    "agent=BoundAgent&before=x&after=x",
])
def test_api_rejects_browser_paths_and_bad_selectors_before_reading(tmp_path, monkeypatch, query):
    async def scenario(client, url, reads):
        async with client.get(url + "/telemetry/conversation?" + query) as response:
            assert response.status == 400
        assert reads == []
    run_api(tmp_path, monkeypatch, scenario)


@pytest.mark.parametrize("row_update,error", [
    ({"history_binding": "pending"}, "history_unconfirmed"),
    ({"history_binding": "unconfirmed"}, "history_unconfirmed"),
    ({"transcript_path": None}, "history_unconfirmed"),
    ({"program": "claude-code"}, "claude_next_phase"),
    ({"program": "hermes"}, "provider_unavailable"),
])
def test_api_does_not_fall_back_to_other_provider_or_unconfirmed_file(tmp_path, monkeypatch, row_update, error):
    async def scenario(client, url, reads):
        async with client.get(url + "/telemetry/conversation?agent=BoundAgent") as response:
            assert (await response.json())["error"] == error
        assert len(reads) == 1
    run_api(tmp_path, monkeypatch, scenario, row_update=row_update)


def test_binding_change_during_read_returns_no_events(tmp_path, monkeypatch):
    async def scenario(client, url, reads):
        async with client.get(url + "/telemetry/conversation?agent=BoundAgent") as response:
            assert response.status == 409
            assert await response.json() == dict(ok=False, error="history_changed")
    run_api(tmp_path, monkeypatch, scenario, change_binding=True)


def test_fresh_uses_protected_projected_history_without_raw_file_reads(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Fresh must not read a raw transcript")
    monkeypatch.setattr(backend, "read_codex_page", forbidden)
    async def scenario(client, url, reads):
        async with client.get(url + "/telemetry/conversation?agent=BoundAgent") as response:
            payload = await response.json()
            assert response.status == 200
            assert payload["mode"] == "fresh_tail" and payload["limited"]
            assert payload["before"] is None and not payload["has_older"]
            assert payload["events"][0]["text"] == "projected text"
        assert len(reads) == 1 and reads[0].startswith("/api/history?")
        async with client.get(url + "/telemetry/conversation?agent=BoundAgent&before=anything") as response:
            assert response.status == 409
    run_api(tmp_path, monkeypatch, scenario, fresh=True)
