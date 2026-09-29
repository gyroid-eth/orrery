"""Manual tool: check that test_cockpit_snapshot_window really pins the guard.

Not collected by pytest (no test_ prefix) because it is a whole test run per
mutant. Run it by hand after changing the snapshot-window code:

    bridge/.venv/bin/python bridge/tests/mutation_check.py

Each entry breaks one guard and expects the suite to fail. A mutant that
survives is a guard no test is holding — the tests passing says nothing about
it. Two of these (the create-time window, the backend markers) are the
commented-out forms on purpose: a substring check would call those present.

The mutants are applied to a THROWAWAY COPY, never to the working tree: that
tree is shared with whoever else is editing right now, and a runner that
rewrites files from a snapshot it took minutes ago silently discards their
work — and leaves a mutant behind if it is killed. ORRERY_BRIDGE_SOURCES
points the suite at the copy.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COCKPIT = ROOT / "cockpit.html"
CONTROL = ROOT / "control_server.py"
SUITE = ROOT / "tests" / "test_cockpit_snapshot_window.py"

MUTANTS: list[tuple[str, Path, str, str]] = [
    (
        "restore: the stale guard is gone",
        COCKPIT,
        "  if(scrollStateIsStale(host,state)){",
        "  if(false){",
    ),
    (
        "land: the replay lands through the DOM again",
        COCKPIT,
        "  try{pane.term.scrollToBottom();}catch(_){}\n  pane.host.scrollTop=pane.host.scrollHeight;",
        "  pane.host.scrollTop=pane.host.scrollHeight;",
    ),
    (
        "reland: a cleared buffer is treated as a reader",
        COCKPIT,
        "  if(previous===undefined||base>=previous)return false;",
        "  if(true)return false;",
    ),
    (
        "reland: the deferred frame is dropped",
        COCKPIT,
        "  requestAnimationFrame(()=>{\n    if(!pane.host.isConnected||panes.get(pane.meta.paneId)!==pane)return;\n    pane._lastBaseY=pane.term.buffer.active.baseY;\n    landPaneOnBottom(pane);\n  });",
        "",
    ),
    (
        "stick: follow is never reasserted",
        COCKPIT,
        "  if(!p._readerScrolled){try{p.term.scrollToBottom();}catch(_){}}",
        "",
    ),
    (
        "stick: follow is reasserted even after a gesture",
        COCKPIT,
        "  if(!p._readerScrolled){try{p.term.scrollToBottom();}catch(_){}}",
        "  {try{p.term.scrollToBottom();}catch(_){}}",
    ),
    (
        "gesture: intent is assumed instead of sampled",
        COCKPIT,
        "    pane._readerScrolled=buffer.viewportY<buffer.baseY;",
        "    pane._readerScrolled=true;",
    ),
    (
        "gesture: the outcome is never sampled",
        COCKPIT,
        "  requestAnimationFrame(()=>{\n    if(!pane.host.isConnected)return;\n    const buffer=pane.term.buffer.active;\n    pane._readerScrolled=buffer.viewportY<buffer.baseY;\n  });",
        "",
    ),
    (
        "gesture: a click assumes scroll intent",
        COCKPIT,
        "  if(assume)pane._readerScrolled=true;",
        "  pane._readerScrolled=true;",
    ),
    (
        "gesture: a paging key is not protected immediately",
        COCKPIT,
        "    markReaderScroll(paneRec,{assume:isReaderScrollKey(event)});",
        "    markReaderScroll(paneRec);",
    ),
    (
        "gesture: a scrollbar grab is not protected immediately",
        COCKPIT,
        "    markReaderScroll(paneRec,{assume:eventTargetsXtermScrollbar(event)});",
        "    markReaderScroll(paneRec);",
    ),
    (
        "gesture: a drag is not re-sampled when it ends",
        COCKPIT,
        "  host.addEventListener('mouseup',()=>{markReaderScroll(paneRec);},{passive:true});",
        "",
    ),
    (
        "gesture: ordinary typing counts as scrolling",
        COCKPIT,
        "  return Boolean(event&&event.shiftKey&&READER_SCROLL_KEYS.has(event.key));",
        "  return Boolean(event);",
    ),
    (
        "gesture: keyboard scrollback is not wired",
        COCKPIT,
        "  host.addEventListener('keydown',event=>{\n    markReaderScroll(paneRec,{assume:isReaderScrollKey(event)});\n  },{passive:true});",
        "",
    ),
    (
        "land: the reader gesture is not cleared",
        COCKPIT,
        "  if(!pane)return;\n  pane._followStick=true;pane._xtermAtBottom=true;pane._readerScrolled=false;",
        "  if(!pane)return;\n  pane._followStick=true;pane._xtermAtBottom=true;",
    ),
    (
        "createPane: reader gestures are not wired",
        COCKPIT,
        "  ['wheel','touchmove'].forEach(kind=>{\n    host.addEventListener(kind,()=>{markReaderScroll(paneRec,{assume:true});},{passive:true});\n  });",
        "",
    ),
    (
        "stale: mid-replay states are no longer stale",
        COCKPIT,
        "  return state.pending||state.epoch!==paneSnapshotEpoch(host);",
        "  return state.epoch!==paneSnapshotEpoch(host);",
    ),
    (
        "stale: older generations are no longer stale",
        COCKPIT,
        "  return state.pending||state.epoch!==paneSnapshotEpoch(host);",
        "  return state.pending;",
    ),
    (
        "capture: mid-replay no longer reports the viewport as following",
        COCKPIT,
        "    viewportAtBottom:pending||Boolean(",
        "    viewportAtBottom:Boolean(",
    ),
    (
        "capture: mid-replay no longer reports the host as following",
        COCKPIT,
        "    hostAtBottom:pending||Boolean(",
        "    hostAtBottom:Boolean(",
    ),
    (
        "begin: the write-owned window can time out",
        COCKPIT,
        "beginPaneSnapshot(pane,{timeout:false})",
        "beginPaneSnapshot(pane)",
    ),
    (
        "begin: the speculative window never times out",
        COCKPIT,
        "  if(timeout){\n    pane._snapshotTimer=setTimeout(",
        "  if(false){\n    pane._snapshotTimer=setTimeout(",
    ),
    (
        "end: a window can be closed by an older one",
        COCKPIT,
        "  if(token!==null&&paneSnapshotEpoch(pane.host)!==token)return;",
        "",
    ),
    (
        "end: a replaced pane is reached through its id",
        COCKPIT,
        "  landPaneOnBottom(pane);\n}",
        "  jumpPaneToBottom(pane.meta.paneId,{focus:false});\n}",
    ),
    (
        "write: live output closes the window",
        COCKPIT,
        "    if(token!==null)endPaneSnapshot(pane,token);\n    else stickFollowHost(pane);",
        "    endPaneSnapshot(pane,token);stickFollowHost(pane);",
    ),
    (
        "handle: the output case bypasses writePaneOutput",
        COCKPIT,
        "      if(p&&p.session===msg.session)writePaneOutput(p,msg);",
        '      if(p&&p.session===msg.session)p.term.write(msg.data||"",()=>stickFollowHost(p));',
    ),
    (
        "createPane: the window is commented out",
        COCKPIT,
        "  beginPaneSnapshot(paneRec);",
        "  // beginPaneSnapshot(paneRec);",
    ),
    (
        "backend: the added-pane marker is commented out",
        CONTROL,
        '                                "snapshot": True,',
        '                                # "snapshot": True,',
    ),
    (
        "backend: the attach marker is commented out",
        CONTROL,
        '                        "snapshot": True,',
        '                        # "snapshot": True,',
    ),
    (
        "backend: live output is marked as a replay",
        CONTROL,
        '            {"type": "output", "paneId": pane_id, "data": data}',
        '            {"type": "output", "paneId": pane_id, "data": data, "snapshot": True}',
    ),
]


def _suite_fails(sources: Path) -> bool:
    environment = {**os.environ, "ORRERY_BRIDGE_SOURCES": str(sources)}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", str(SUITE), "-q", "--no-header", "--tb=no"],
        capture_output=True,
        text=True,
        env=environment,
    )
    return done.returncode != 0


def main() -> int:
    originals = {path: path.read_text(encoding="utf-8") for path in (COCKPIT, CONTROL)}
    survivors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="orrery-mutants-") as workspace:
        sources = Path(workspace)
        for path in originals:
            shutil.copy2(path, sources / path.name)
        if _suite_fails(sources):
            print("the suite is already red against a clean copy — fix that first")
            return 2
        for name, path, before, after in MUTANTS:
            source = originals[path]
            target = sources / path.name
            if before not in source:
                print(f"STALE   {name} (anchor no longer in {path.name})")
                survivors.append(name)
                continue
            target.write_text(source.replace(before, after, 1), encoding="utf-8")
            caught = _suite_fails(sources)
            target.write_text(source, encoding="utf-8")
            print(f"{'caught ' if caught else 'SURVIVED'} {name}")
            if not caught:
                survivors.append(name)
    print()
    print("survivors:", ", ".join(survivors) if survivors else "none")
    return 1 if survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
