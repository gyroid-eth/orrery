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


def test_of_several_matches_the_newest_wins(runs):
    older = runs / "The-fin-to-limb-old" / "draft" / "note.md"
    older.parent.mkdir(parents=True)
    older.write_text("x")
    past = time.time() - 3600
    os.utime(older, (past, past))
    assert ob.resolve_shown_path(f"{runs}/The-fin-to-lim…/note.md") == (
        runs / RUN / "draft" / "note.md"
    )


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


def test_the_walk_is_bounded(runs, monkeypatch):
    deep = runs / "The-fin-deep"
    for level in range(10):
        deep = deep / f"d{level}"
    deep.mkdir(parents=True)
    (deep / "far.md").write_text("x")
    assert ob.resolve_shown_path(f"{runs}/The-fin-deep…/far.md") is None


# --- the probe that turns the printed text into a link ------------------------


@pytest.mark.parametrize("after", [")", ") and more", " — next", "\"", ""])
def test_the_probe_links_the_whole_shortened_path(runs, after):
    shown = f"{runs}/The-fin-to-lim…/note.md"
    assert ob.longest_existing_path_prefix(shown + after) == shown


def test_the_probe_still_stops_at_prose(runs):
    path = runs / RUN / "draft" / "note.md"
    assert ob.longest_existing_path_prefix(f"{path} はうまくいった") == str(path)


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
