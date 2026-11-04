"""History navigation binds a pane to one CLI file and never writes into tmux."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import transcript_history as history


def codex_record(role: str, text: str, *, timestamp: str = "2026-11-04") -> dict:
    return {
        "timestamp": timestamp, "type": "response_item",
        "payload": {
            "type": "message", "role": role,
            "content": [{"type": "input_text" if role == "user" else "output_text",
                         "text": text}],
        },
    }


def write_jsonl(file: Path, records: list[dict]) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("".join(json.dumps(r) + "\n" for r in records))


@pytest.mark.parametrize("session,pane", [
    ("../other", "%1"), ("hello world", "%1"), ("good", "%1;rm"),
    ("", "%1"), ("Good", "1"),
])
def test_invalid_session_or_pane_is_rejected_before_tmux(monkeypatch, session, pane):
    def never_run(*_args, **_kwargs):
        pytest.fail("untrusted input reached a subprocess")
    monkeypatch.setattr(history.subprocess, "run", never_run)
    with pytest.raises(history.TranscriptUnavailable):
        history.read_pane_history("tmux", session, pane)


def test_pane_must_belong_to_named_session(monkeypatch, tmp_path):
    def fake_run(argv, **_kwargs):
        if "list-panes" in argv:
            return subprocess.CompletedProcess(argv, 0, "%4\t3141\t" + str(tmp_path) + "\n", "")
        pytest.fail("must not inspect any process outside selected tmux pane")
    monkeypatch.setattr(history.subprocess, "run", fake_run)
    with pytest.raises(history.TranscriptUnavailable, match="does not belong"):
        history.read_pane_history("tmux", "Agent", "%5")


def test_multiple_cli_children_cannot_be_guessed(monkeypatch):
    def fake_run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 0, (
            "4242 1 /bin/zsh\n"
            "4411 4242 /usr/bin/codex\n"
            "4422 4242 /usr/bin/claude --resume some-session\n"
        ), "")
    monkeypatch.setattr(history.subprocess, "run", fake_run)
    with pytest.raises(history.TranscriptUnavailable, match="ambiguous"):
        history._cli_process(4242)


def test_codex_logfile_must_be_open_in_pane_cli_and_match_working_directory(
    monkeypatch, tmp_path
):
    home = tmp_path / "home"
    cwd = tmp_path / "worktree"
    cwd.mkdir()
    logfile = home / ".codex/sessions/2026/11/04/rollout.jsonl"
    write_jsonl(logfile, [
        {"type": "session_meta", "payload": {"cwd": str(cwd)}},
        codex_record("user", "first"),
        codex_record("assistant", "second"),
    ])
    def fake_run(argv, **_kwargs):
        if "list-panes" in argv:
            return subprocess.CompletedProcess(argv, 0, f"%8\t4242\t{cwd}\n", "")
        if argv[:2] == ["ps", "-axo"]:
            return subprocess.CompletedProcess(
                argv, 0,
                "4242 1 /bin/zsh\n4411 4242 /path/to/codex -C " + str(cwd) + "\n", "")
        if argv[0] == "lsof":
            return subprocess.CompletedProcess(argv, 0, "p4411\nn" + str(logfile) + "\n", "")
        pytest.fail("unexpected subprocess")
    monkeypatch.setattr(history.subprocess, "run", fake_run)
    page = history.read_pane_history("tmux", "Agent", "%8", home=home)
    assert page["provider"] == "codex"
    assert [item["text"] for item in page["items"]] == ["first", "second"]
    assert not page["has_older"]
    # A file opened by the CLI still must refer to this pane's cwd.
    write_jsonl(logfile, [{"type": "session_meta", "payload": {"cwd": "/other"}},
                          codex_record("assistant", "wrong session")])
    with pytest.raises(history.TranscriptUnavailable, match="uniquely bound"):
        history.read_pane_history("tmux", "Agent", "%8", home=home)


def test_claude_logfile_uses_cli_resume_id_and_matching_working_directory(
    monkeypatch, tmp_path
):
    home = tmp_path / "home"
    cwd = tmp_path / "worktree"
    cwd.mkdir()
    uuid = "4d62f9b2-6cf5-4743-893f-56c02d1c2aa0"
    logfile = home / ".claude/projects/project" / (uuid + ".jsonl")
    write_jsonl(logfile, [
        {"type": "user", "cwd": str(cwd),
         "message": {"role": "user", "content": "request"}},
        {"type": "assistant", "cwd": str(cwd),
         "message": {"role": "assistant", "content": [{"type": "text", "text": "answer"}]}},
    ])
    def fake_run(argv, **_kwargs):
        if "list-panes" in argv:
            return subprocess.CompletedProcess(argv, 0, f"%8\t4242\t{cwd}\n", "")
        if argv[:2] == ["ps", "-axo"]:
            return subprocess.CompletedProcess(
                argv, 0, "4242 1 /bin/zsh\n4411 4242 /usr/bin/claude --resume " + uuid + "\n", "")
        pytest.fail("unexpected subprocess")
    monkeypatch.setattr(history.subprocess, "run", fake_run)
    page = history.read_pane_history("tmux", "Agent", "%8", home=home)
    assert page["provider"] == "claude"
    assert [item["text"] for item in page["items"]] == ["request", "answer"]


def test_exact_message_types_only_exclude_internal_and_tool_records():
    developer = codex_record("developer", "internal")
    analysis = {"type": "response_item", "payload": {"type": "reasoning", "summary": "hidden"}}
    tool = {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "Shell", "input": {"command": "secret"}}]}}
    assert history._message(developer, "codex") is None
    assert history._message(analysis, "codex") is None
    assert history._message(tool, "claude") is None
    assert history._message({"type": "assistant", "isSidechain": True,
                             "message": {"content": "ignore"}}, "claude") is None


def test_pagination_reaches_oldest_message_without_duplicates(tmp_path, monkeypatch):
    records = [codex_record("assistant", f"message {n:02}") for n in range(35)]
    logfile = tmp_path / "log.jsonl"
    write_jsonl(logfile, records)
    monkeypatch.setattr(history, "PAGE_BYTES", 380)
    seen = []
    cursor = None
    while True:
        page = history._page(logfile, "codex", cursor)
        seen = [entry["text"] for entry in page["items"]] + seen
        if not page["has_older"]:
            break
        assert page["older_before"] != cursor
        cursor = page["older_before"]
    assert seen == [f"message {n:02}" for n in range(35)]


def test_browser_pagination_requires_source_identity(monkeypatch):
    from orrery_backend import TMUX_BIN_KEY, serve_transcript
    request = SimpleNamespace(query={"session": "Agent", "pane": "%1", "before": "512"},
                              app={TMUX_BIN_KEY: "tmux"})
    response = asyncio.run(serve_transcript(request))
    assert response.status == 400


def test_pagination_rejects_source_switch(tmp_path):
    logfile = tmp_path / "log.jsonl"
    write_jsonl(logfile, [codex_record("user", "hello")])
    page = history._page(logfile, "codex", None)
    assert len(page["source_id"]) == 16
    assert history._page(logfile, "codex", None, page["source_id"]) == page
    with pytest.raises(history.TranscriptUnavailable, match="transcript changed"):
        history._page(logfile, "codex", 0, "0" * 16)


def test_pagination_stops_on_incomplete_append(tmp_path):
    logfile = tmp_path / "unfinished.jsonl"
    logfile.write_text(json.dumps(codex_record("user", "complete")) +
                       '\n{"type":"response_item","payload":{"type":')
    page = history._page(logfile, "codex", None)
    assert [i["text"] for i in page["items"]] == ["complete"]


def test_symlinked_logfile_is_rejected(tmp_path):
    root = tmp_path / ".codex/sessions"
    root.mkdir(parents=True)
    external = tmp_path / "outside.jsonl"
    write_jsonl(external, [codex_record("assistant", "content")])
    link = root / "linked.jsonl"
    link.symlink_to(external)
    with pytest.raises(history.TranscriptUnavailable, match="rejected"):
        history._safe_file(link, root)


def test_http_rejects_cursor_before_reading_provider(monkeypatch):
    from orrery_backend import TMUX_BIN_KEY, serve_transcript
    monkeypatch.setattr(history, "read_pane_history", lambda *a: pytest.fail("should not read"))
    request = SimpleNamespace(query={"before": "1;rm"}, app={TMUX_BIN_KEY: "tmux"})
    response = asyncio.run(serve_transcript(request))
    assert response.status == 400
