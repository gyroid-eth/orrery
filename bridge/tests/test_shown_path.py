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
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from wcwidth import wcswidth

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import orrery_backend as ob  # noqa: E402
from control_server import CommandResult, PaneInfo  # noqa: E402

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
    assert "mk(start,found.path,found.resolved||found.path,Boolean(found.resolved))" in html
    assert "activate:(event)=>{event.preventDefault();revealLocalPath(open,{literal});}" in html


# --- the endpoint -------------------------------------------------------------


class _Request:
    def __init__(self, payload, app=None):
        self._payload = payload
        self.app = app

    async def json(self):
        return self._payload


@pytest.fixture
def pane_probe(tmp_path):
    manager = ob.SessionBridgeManager("tmux", history_dir=tmp_path)
    panes = {p: PaneInfo(p, "@1", "$1", "0", str(i), 80, 24, i == 0, "shell", "sh")
             for i, p in enumerate(("%1", "%2"))}
    workspaces = {p: tmp_path / p[1:] for p in panes}
    for folder in workspaces.values():
        (folder / "docs").mkdir(parents=True)
        (folder / "docs" / "note.md").touch()

    async def command(args, **_):
        pane = args[3]
        assert args == ["display-message", "-p", "-t", pane,
                        "#{session_id}\t#{window_id}\t#{pane_id}\t#{pane_current_path}"]
        return CommandResult(True, [f"$1\t@1\t{pane}\t{workspaces[pane]}"])

    bridge = SimpleNamespace(panes=panes, config=SimpleNamespace(session="Fixture", tmux_bin="tmux"),
                             _closed=False, send_command=command)
    manager.states["Fixture"] = ob.SessionState(bridge)

    def probe(text, pane="%1", session="Fixture"):
        return asyncio.run(ob.path_probe(_Request(dict(text=text, paneId=pane, session=session),
                                                  {ob.BRIDGE_MANAGER_KEY: manager})))

    return probe, bridge, workspaces, manager


def test_relative_probe_uses_the_selected_pane_and_its_current_directory(pane_probe):
    probe, _, cwd, _ = pane_probe
    for selected in ("%1", "%2"):
        body = json.loads(probe("docs/note.md", selected).body)
        assert body == dict(ok=True, path="docs/note.md", length=12,
                            resolved=str(cwd[selected] / "docs/note.md"))
    cwd["%1"] = cwd["%2"]
    assert json.loads(probe("docs/note.md").body)["resolved"] == str(cwd["%2"] / "docs/note.md")


@pytest.mark.parametrize("shown,name", [("docs/note.md:12", "docs/note.md"),
                                        ("./docs/note.md:12:3", "docs/note.md"),
                                        ("../2/docs/note.md", "../2/docs/note.md"),
                                        ("docs/記録 (1).md", "docs/記録 (1).md"),
                                        ("docs/record:12:3", "docs/record:12:3"),
                                        ("docs/record!", "docs/record!")])
def test_relative_probe_prefers_literal_names_and_keeps_the_display_suffix(pane_probe, shown, name):
    probe, _, cwd, _ = pane_probe
    (cwd["%1"] / "docs/record").touch()
    (cwd["%1"] / name).touch()
    body = json.loads(probe(shown).body)
    assert body["path"] == shown and body["resolved"] == str(cwd["%1"] / name)


def test_relative_probe_refuses_unknown_moved_and_replaced_panes(pane_probe):
    probe, bridge, cwd, manager = pane_probe
    assert probe("docs/note.md", session="Elsewhere").status == 404
    assert probe("docs/note.md", pane="%999").status == 404

    async def moved(*_, **__):
        return CommandResult(True, [f"$2\t@1\t%1\t{cwd['%1']}"])

    bridge.send_command = moved
    assert probe("docs/note.md").status == 404

    async def replaced(*_, **__):
        manager.states["Fixture"] = ob.SessionState(bridge)
        return CommandResult(True, [f"$1\t@1\t%1\t{cwd['%1']}"])

    bridge.send_command = replaced
    assert probe("docs/note.md").status == 404


def test_relative_probe_follows_the_fresh_wire_handle(pane_probe):
    probe, bridge, _, manager = pane_probe
    target = object.__new__(ob.FreshPaneBoundary)
    target.pane_id, target.wire_pane = "%1", "fresh-fixture-1"
    bridge.config.tmux_bin = target
    manager.states["fresh-fixture"] = manager.states.pop("Fixture")
    assert probe("docs/note.md", pane="%1").status == 404
    response = probe("docs/note.md", pane=target.wire_pane)
    assert response.status == 200


def test_relative_probe_does_not_guess_missing_or_shortened_paths(pane_probe, monkeypatch):
    probe, _, cwd, _ = pane_probe
    path = cwd["%1"] / "docs/note.md"
    resolved = json.loads(probe("docs/note.md").body)["resolved"]
    path.rename(path.with_name("note-long.md"))
    path.with_name("note-other.md").touch()
    assert probe("docs/note.md").status == probe("docs/note-….md").status == 404
    monkeypatch.setattr(ob, "reveal_in_finder", lambda path: pytest.fail(f"opened {path}"))
    response = asyncio.run(ob.reveal_path(_Request({"path": resolved, "literal": True})))
    assert response.status == 404


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


def test_a_probed_path_is_opened_as_it_is_or_not_at_all(tmp_path, monkeypatch):
    """Review of #10 (R2-P2-2): the probe resolved task…/note.md to a real
    task…-one/note.md; that file goes, task-long-one/note.md appears. The
    click must not read the resolved path's own "…" as a shortening."""
    (tmp_path / "task…-one").mkdir()
    (tmp_path / "task…-one" / "note.md").write_text("x")
    probe = json.loads(asyncio.run(ob.path_probe(_Request({"text": f"{tmp_path}/task…/note.md"}))).body)
    resolved = probe["resolved"]
    assert resolved == f"{tmp_path}/task…-one/note.md"
    (tmp_path / "task…-one" / "note.md").unlink()
    (tmp_path / "task-long-one").mkdir()
    (tmp_path / "task-long-one" / "note.md").write_text("x")
    monkeypatch.setattr(ob, "reveal_in_finder", lambda path: pytest.fail(f"opened {path}"))
    response = asyncio.run(ob.reveal_path(_Request({"path": resolved, "literal": True})))
    assert response.status == 404


def test_a_probed_path_that_is_still_there_opens(runs, monkeypatch):
    seen = []
    monkeypatch.setattr(ob, "reveal_in_finder", lambda path: seen.append(path) or "file")
    real = runs / RUN / "draft" / "note.md"
    body = json.loads(asyncio.run(ob.reveal_path(_Request({"path": str(real), "literal": True}))).body)
    assert body["ok"] is True and seen == [real]


NODE = shutil.which("node")


def _pane_link_script(*, probe=False):
    html = (Path(__file__).resolve().parents[1] / "cockpit.html").read_text(encoding="utf-8")
    start = html.index("  // Local paths in pane output:")
    provider = html[start : html.index("\n  });", start) + len("\n  });")]
    end = html.index("/* The file manager's name" if probe else "const probeCache")
    return html[html.index("function relativePathEnd") : end] + provider


def _links_for(row: str, probe: dict | None, *, ranges=False, trace=False, wrap=(False, False)):
    """Run the cockpit's own link provider on one pane row, with the probe
    answering ``probe``; return each link's text and what a click sends."""
    script = f"""
const sent=[],requests=[],session='Fixture',meta={{paneId:'%1'}};
function revealLocalPath(path,opts={{}}){{sent.push({{path,literal:Boolean(opts.literal)}});}}
async function probeLocalPath(text,pane=null){{requests.push({{text,pane}});return {json.dumps(probe)};}}
const row={json.dumps(row)},cells=[];
for(const ch of row){{cells.push(ch);if(/[\u3040-\u9fff]/.test(ch))cells.push('');}}
const line={{isWrapped:{json.dumps(wrap[0])},translateToString:()=>row,
  getCell(col,cell){{Object.assign(cell,{{getChars:()=>cells[col],getWidth:()=>cells[col+1]===''?2:1}});return cell;}}}};
const term={{buffer:{{active:{{getLine:y=>y===0?line:{{isWrapped:{json.dumps(wrap[1])}}},getNullCell:()=>({{}})}}}},registerLinkProvider(p){{this.p=p;}}}};
{_pane_link_script()}
term.p.provideLinks(1,links=>{{
  for(const l of links||[])l.activate({{preventDefault(){{}}}});
  const result=(links||[]).map((l,i)=>({{text:l.text,...sent[i],...({json.dumps(ranges or trace)}?{{range:l.range}}:{{}})}}));
  console.log(JSON.stringify({json.dumps(trace)}?{{links:result,requests}}:result));
}});
"""
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.skipif(NODE is None, reason="no node")
@pytest.mark.parametrize("opener,closer", [("(", ")"), ("<", ">"), ('"', '"')])
def test_relative_link_ranges_use_cells_and_exclude_wrappers(opener, closer):
    shown, resolved = "Lab Notes/記録 (1).md:12:3", "/fixture/Lab Notes/記録 (1).md"
    result = _links_for(f"配線 {opener}{shown}{closer}", {"path": shown, "resolved": resolved}, trace=True)
    assert result == {"links": [{"text": shown, "path": resolved, "literal": True,
                                "range": {"start": {"x": 7, "y": 1}, "end": {"x": 32, "y": 1}}}],
                      "requests": [{"text": shown, "pane": {"session": "Fixture", "paneId": "%1"}}]}


@pytest.mark.skipif(NODE is None, reason="no node")
def test_relative_links_skip_url_parts_missing_and_incomplete_candidates():
    row = "https://example.com/a?ref=docs/note.md docs/missing.md /compact"
    result = _links_for(row, None, trace=True)
    assert result == {"links": [], "requests": [{"text": "docs/missing.md /compact",
                                                 "pane": {"session": "Fixture", "paneId": "%1"}}]}
    prefix = {"path": "docs/note.md", "resolved": "/fixture/docs/note.md"}
    assert _links_for("<docs/note.md extra>", prefix) == []
    assert _links_for("docs/note.md", prefix, wrap=(False, True)) == []
    assert _links_for("docs/note.md", prefix, wrap=(True, False)) == []


@pytest.mark.skipif(NODE is None, reason="no node")
def test_new_relative_links_use_the_current_directory_in_the_same_pane(pane_probe):
    _, _, workspaces, _ = pane_probe
    script = f"const workspaces={json.dumps([str(workspaces[p]) for p in ('%1', '%2')])};\n" + """
const fs=require('node:fs'),path=require('node:path');
const performance={now:()=>0},requests=[],opened=[],session='Fixture',meta={paneId:'%1'};
const rows=['Before (docs/note.md) (docs/note.md)','After (docs/note.md)'];
const term={buffer:{active:{getLine(i){return rows[i]&&{translateToString:()=>rows[i]};}}},
  registerLinkProvider(provider){this.provider=provider;}};
let cwd=workspaces[0];
function revealLocalPath(path,{literal}){opened.push({path,literal});}
async function fetch(url,options){
  const payload=JSON.parse(options.body);
  requests.push(payload);
  const resolved=path.join(cwd,payload.text),ok=fs.existsSync(resolved);
  return {ok,json:async()=>({ok,path:payload.text,resolved})};
}
""" + _pane_link_script(probe=True) + """
(async()=>{
  const linksAt=y=>new Promise(resolve=>term.provider.provideLinks(y,resolve));
  const before=await linksAt(1);
  cwd=workspaces[1];
  const after=await linksAt(2);
  for(const link of [...before,...after])link.activate({preventDefault(){}});
  console.log(JSON.stringify({opened,requests}));
})();
"""
    done = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=20, check=True)
    assert json.loads(done.stdout) == {
        "opened": [dict(path=str(workspaces[p] / "docs/note.md"), literal=True)
                   for p in ("%1", "%1", "%2")],
        "requests": [dict(text="docs/note.md", session="Fixture", paneId="%1")] * 2,
    }


@pytest.mark.skipif(NODE is None, reason="no node")
@pytest.mark.parametrize('template', ['<{path}>', '[file](<{path}>)', 'file (<{path}>)'])
@pytest.mark.parametrize('path', ['/fixture/report.md', '~/A B/画像(1).png'])
def test_angle_wrapped_pane_path_range_and_activation(template, path):
    row = template.format(path=path)
    resolved = '/fixture/resolved.png'
    (link,) = _links_for(row, {'path': path, 'resolved': resolved}, ranges=True)
    start = row.index(path)
    assert link['text'] == row[start:start+len(path)] == path
    start_column = wcswidth(row[:start])
    assert link['range'] == {'start': {'x': start_column+1, 'y': 1},
                             'end': {'x': start_column+wcswidth(path), 'y': 1}}
    # ASCII paths need no probe; paths with spaces/Unicode open the probe result.
    probed = ' ' in path
    assert link['path'] == (resolved if probed else path)
    assert link['literal'] is probed


@pytest.mark.skipif(NODE is None, reason="no node")
def test_a_probed_path_spelled_like_the_text_is_still_sent_literally(tmp_path):
    """Review of #10 (R3): a real task…/note.md resolves to itself; the click
    must still open exactly it, not re-read its "…" once it has gone."""
    real = f"{tmp_path}/task…/note.md"
    (link,) = _links_for(f"● Write({real})", {"path": real, "resolved": real})
    assert link == {"text": real, "path": real, "literal": True}


@pytest.mark.skipif(NODE is None, reason="no node")
def test_a_shortened_link_sends_its_resolved_path_literally(tmp_path):
    shown, real = f"{tmp_path}/ta…/note.md", f"{tmp_path}/task-x/note.md"
    (link,) = _links_for(f"● Write({shown})", {"path": shown, "resolved": real})
    assert link == {"text": shown, "path": real, "literal": True}


@pytest.mark.skipif(NODE is None, reason="no node")
def test_an_ambiguous_link_is_sent_as_printed(tmp_path):
    shown = f"{tmp_path}/ta…/note.md"
    (link,) = _links_for(f"● Write({shown})", {"path": shown, "resolved": None})
    assert link == {"text": shown, "path": shown, "literal": False}


def test_the_backend_receives_literal_from_the_cockpit():
    html = (Path(__file__).resolve().parents[1] / "cockpit.html").read_text(encoding="utf-8")
    assert "JSON.stringify(literal?{path,literal:true}:{path})" in html


def test_reveal_still_refuses_what_does_not_resolve(runs, monkeypatch):
    monkeypatch.setattr(ob, "reveal_in_finder", lambda path: pytest.fail("opened"))
    response = asyncio.run(ob.reveal_path(_Request({"path": f"{runs}/Nothing…/x.md"})))
    assert response.status == 404


def test_the_app_rejection_of_a_missing_path_falls_through_to_the_backend():
    html = (Path(__file__).resolve().parents[1] / "cockpit.html").read_text(encoding="utf-8")
    start = html.index("async function revealLocalPath(path,")
    body = html[start : html.index("async function openActivePaneInGhostty", start)]
    final = re.search(r"if\(/([^/]+)/\.test\(detail\)\)\{", body).group(1)
    assert "no such path" not in final
    assert "must be absolute" in final
