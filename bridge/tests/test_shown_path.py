"""A path Claude Code shortened with "…" still opens (2026-10-01 seminar).

In a narrow pane Claude Code prints
``Write(~/.agentstack/addons/digest-paper/runs/The-fin-to-lim…/note.md)``
for runs/The-fin-to-limb-transition-…-20261001T224253/draft/note.md: one "…"
stands for any run of characters, across folders too. Clicked as printed, the
cockpit answered "FINDER FAILED · no such path" (recording 1:38:24, the
cockpit under WSL in a Windows browser — a narrow pane, not WSL, made the
path short). The backend now reads the "…" against the disk, both when the
link is probed and when it is opened, and the app's literal "no such path"
falls through to it.

Run from bridge/: ``python -m pytest tests/test_shown_path.py``.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import orrery_backend as ob  # noqa: E402

RUN = "The-fin-to-limb-transition-as-the-re-org-bcaa45bc-20261001T224253"


@pytest.fixture
def runs(tmp_path):
    note = tmp_path / "runs" / RUN / "draft" / "note.md"
    note.parent.mkdir(parents=True)
    note.write_text("x")
    return tmp_path / "runs"


def test_the_recorded_path_resolves_across_folders(runs):
    shown = f"{runs}/The-fin-to-lim…/note.md"
    assert ob.resolve_shown_path(shown) == runs / RUN / "draft" / "note.md"


def test_an_ellipsis_inside_a_name_resolves(runs):
    shown = f"{runs}/The-fin…224253/draft"
    assert ob.resolve_shown_path(shown) == runs / RUN / "draft"


def test_a_tilde_path_with_an_ellipsis_resolves(runs, monkeypatch):
    monkeypatch.setenv("HOME", str(runs.parent))
    assert ob.resolve_shown_path("~/runs/The-fin-to-lim…/note.md") == (
        runs / RUN / "draft" / "note.md"
    )


def test_several_matches_resolve_to_nothing(runs):
    """Review of #10 (P2-1): the newest of several is not what the person
    pointed at. They are listed instead (see the endpoint tests)."""
    other = runs / "The-fin-to-limb-old" / "draft" / "note.md"
    other.parent.mkdir(parents=True)
    other.write_text("x")
    shown = f"{runs}/The-fin-to-lim…/note.md"
    assert ob.resolve_shown_path(shown) is None
    assert ob.shown_path_matches(shown) == [other, runs / RUN / "draft" / "note.md"]


def test_a_real_name_with_an_ellipsis_is_taken_as_it_is(runs):
    real = runs / "task…" / "note.md"
    real.parent.mkdir()
    real.write_text("x")
    newer = runs / "task-new" / "note.md"
    newer.parent.mkdir()
    newer.write_text("x")
    assert ob.shown_path_matches(f"{runs}/task…/note.md") == [real]


@pytest.mark.parametrize("kind", ["dir", "file", "bundle"])
def test_a_symlink_is_never_a_match(runs, tmp_path, kind):
    """Review of #10 (P2-2): the search stays under the folder before the "…"."""
    outside = tmp_path / "outside"
    target = {"dir": outside / "draft", "file": outside / "draft" / "note.md",
              "bundle": outside / "Report.app"}[kind]
    (outside / "draft").mkdir(parents=True)
    (outside / "draft" / "note.md").write_text("x")
    (outside / "Report.app").mkdir()
    task = runs / "task-new"
    task.mkdir()
    name = {"dir": "draft", "file": "note.md", "bundle": "Report.app"}[kind]
    (task / name).symlink_to(target)
    assert ob.shown_path_matches(f"{runs}/task…/{name}") == []
    (runs / "task-link").symlink_to(task)
    assert ob.shown_path_matches(f"{runs}/task-l…/{name}") == []


@pytest.mark.parametrize("shown", [
    "{runs}/Nothing-like-it…/note.md",       # no folder starts so
    "{runs}/The-fin-to-lim…/other.md",       # nothing ends so
    "{runs}/The…fin…/note.md",               # two ellipses: not a shortening
    "{runs}/The-fin-to-lim…",                # nothing after the ellipsis
])
def test_what_does_not_resolve(runs, shown):
    assert ob.resolve_shown_path(shown.format(runs=runs)) is None


def test_a_plain_path_is_unchanged(runs, tmp_path):
    assert ob.resolve_shown_path(str(runs)) == runs
    assert ob.resolve_shown_path(str(tmp_path / "missing")) is None


def test_the_walk_is_bounded_in_depth(runs):
    deep = runs / "The-fin-deep"
    for level in range(10):
        deep = deep / f"d{level}"
    deep.mkdir(parents=True)
    (deep / "far.md").write_text("x")
    assert ob.shown_path_matches(f"{runs}/The-fin-deep…/far.md") == []


def test_the_budget_counts_the_top_folder(tmp_path, monkeypatch):
    """Review of #10 (P2-3): 5,001 matching entries at the top were all read."""
    monkeypatch.setattr(ob, "ELLIPSIS_MAX_ENTRIES", 50)
    for i in range(51):
        (tmp_path / f"run-{i}.md").write_text("x")
    assert ob.shown_path_matches(f"{tmp_path}/run-….md") is None
    assert ob.resolve_shown_path(f"{tmp_path}/run-….md") is None


def test_the_budget_counts_one_wide_folder_below(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "ELLIPSIS_MAX_ENTRIES", 50)
    wide = tmp_path / "run" / "draft"
    wide.mkdir(parents=True)
    for i in range(60):
        (wide / f"f{i}").write_text("x")
    (wide / "note.md").write_text("x")
    assert ob.shown_path_matches(f"{tmp_path}/ru…/note.md") is None


def test_a_search_within_budget_still_resolves(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "ELLIPSIS_MAX_ENTRIES", 50)
    (tmp_path / "run" / "draft").mkdir(parents=True)
    (tmp_path / "run" / "draft" / "note.md").write_text("x")
    assert ob.resolve_shown_path(f"{tmp_path}/ru…/note.md") == tmp_path / "run" / "draft" / "note.md"


def test_the_budget_is_shared_by_every_prefix_a_probe_tries(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "ELLIPSIS_MAX_ENTRIES", 30)
    for i in range(20):
        (tmp_path / f"a{i}").mkdir()
    looked: list[int] = []
    real = ob.shown_path_matches

    def counting(text, budget=None):
        result = real(text, budget)
        looked.append(budget.left if budget else -1)
        return result

    monkeypatch.setattr(ob, "shown_path_matches", counting)
    # Four prefixes, each a 20-entry search: one budget of 30 runs out.
    text = f"{tmp_path}/a…/x one two three"
    assert ob.probe_shown_path(text) is None
    assert looked[-1] == 0


# --- the probe that turns the printed text into a link ------------------------


@pytest.mark.parametrize("after", [")", ") and more", " — next", "\"", ""])
def test_the_probe_links_the_whole_shortened_path(runs, after):
    shown = f"{runs}/The-fin-to-lim…/note.md"
    assert ob.longest_existing_path_prefix(shown + after) == shown


def test_the_probe_still_stops_at_prose(runs):
    path = runs / RUN / "draft" / "note.md"
    assert ob.longest_existing_path_prefix(f"{path} はうまくいった") == str(path)


def test_the_probe_binds_the_link_to_the_path_it_resolved(runs):
    """Review of #10 (P2-1): the click opens what the link was made for."""
    shown = f"{runs}/The-fin-to-lim…/note.md"
    response = asyncio.run(ob.path_probe(_Request({"text": shown + ")"})))
    body = json.loads(response.body)
    assert body == {"ok": True, "path": shown, "length": len(shown),
                    "resolved": str(runs / RUN / "draft" / "note.md")}


def test_an_ambiguous_probe_links_without_resolving(runs):
    other = runs / "The-fin-to-limb-old" / "draft" / "note.md"
    other.parent.mkdir(parents=True)
    other.write_text("x")
    body = json.loads(asyncio.run(ob.path_probe(_Request({"text": f"{runs}/The-fin-to-lim…/note.md"}))).body)
    assert body["ok"] is True and "resolved" not in body


def test_the_cockpit_opens_the_probed_path():
    html = (Path(__file__).resolve().parents[1] / "cockpit.html").read_text(encoding="utf-8")
    assert "mk(start,found.path,found.resolved||found.path)" in html
    assert "activate:(event)=>{event.preventDefault();revealLocalPath(open);}" in html


# --- the endpoint -------------------------------------------------------------


class _Request:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def test_reveal_opens_the_resolved_path(runs, monkeypatch):
    seen = []
    monkeypatch.setattr(ob, "reveal_in_finder", lambda path: seen.append(path) or "file")
    shown = f"{runs}/The-fin-to-lim…/note.md"
    body = json.loads(asyncio.run(ob.reveal_path(_Request({"path": shown}))).body)
    assert body == {"ok": True, "kind": "file", "path": str(runs / RUN / "draft" / "note.md")}
    assert seen == [runs / RUN / "draft" / "note.md"]


def test_reveal_lists_several_matches_and_opens_none(runs, monkeypatch):
    other = runs / "The-fin-to-limb-old" / "draft" / "note.md"
    other.parent.mkdir(parents=True)
    other.write_text("x")
    monkeypatch.setattr(ob, "reveal_in_finder", lambda path: pytest.fail("opened"))
    response = asyncio.run(ob.reveal_path(_Request({"path": f"{runs}/The-fin-to-lim…/note.md"})))
    body = json.loads(response.body)
    assert response.status == 409
    assert body["error"] == "2 paths match; not opened"
    assert body["candidates"] == [str(other), str(runs / RUN / "draft" / "note.md")]


def test_reveal_refuses_a_search_that_ran_out(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "ELLIPSIS_MAX_ENTRIES", 5)
    for i in range(10):
        (tmp_path / f"run-{i}.md").write_text("x")
    monkeypatch.setattr(ob, "reveal_in_finder", lambda path: pytest.fail("opened"))
    response = asyncio.run(ob.reveal_path(_Request({"path": f"{tmp_path}/run-….md"})))
    assert response.status == 422


def test_reveal_still_refuses_what_does_not_resolve(runs, monkeypatch):
    monkeypatch.setattr(ob, "reveal_in_finder", lambda path: pytest.fail("opened"))
    response = asyncio.run(ob.reveal_path(_Request({"path": f"{runs}/Nothing…/x.md"})))
    assert response.status == 404


def test_the_app_rejection_of_a_missing_path_falls_through_to_the_backend():
    html = (Path(__file__).resolve().parents[1] / "cockpit.html").read_text(encoding="utf-8")
    start = html.index("async function revealLocalPath(path){")
    body = html[start : html.index("async function openActivePaneInGhostty", start)]
    final = re.search(r"if\(/([^/]+)/\.test\(detail\)\)\{", body).group(1)
    assert "no such path" not in final
    assert "must be absolute" in final
