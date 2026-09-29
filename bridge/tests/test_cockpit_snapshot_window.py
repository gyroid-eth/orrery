"""A pane must open on the prompt, not on the top of its scrollback.

Two mechanisms put it on the top, and both were measured on the live cockpit
on 2026-09-15:

1. An attach replay is one big write that xterm parses across several frames.
   A scroll position read during that write describes a half-written buffer;
   restoring it pins the viewport, xterm reads the pin as "the reader scrolled
   up" and stops following, and the rest of the history lands off-screen.
2. A CLI reflowing after a resize clears the buffer and reprints its whole
   transcript. The viewport element shrinks with the buffer, the browser clamps
   its scrollTop, and xterm reads THAT as the reader scrolling too. Nothing in
   the page had touched scrollTop — the clamp is the browser's, which is why it
   survived an assignment trap.

The lesson both share: a DOM scroll position is not a statement of intent, and
mid-write DOM geometry is not even a statement of fact (scrollHeight still
equals clientHeight, so "scroll to the bottom" computes 0 — the first fix for
(1) reintroduced the bug through its own guard).

A browser check is worth having as an integration test but is not a regression
gate: whether either race happens depends on what the agent in the pane is
doing, so a quiet session passes with every guard removed (measured — it did,
in both directions). These drive the ordering directly, with a fake clock, a
write whose callback is held, and a buffer model that only follows when it is
already at the bottom.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# mutation_check.py points this at a throwaway copy so it never has to edit the
# working tree — a shared one, where another agent may be mid-edit.
SOURCES = Path(os.environ.get("ORRERY_BRIDGE_SOURCES", ROOT))
COCKPIT = SOURCES / "cockpit.html"
CONTROL_SERVER = SOURCES / "control_server.py"

BLOCKS = (
    r"function paneSnapshotEpoch\(host\)\{.*?\n",
    r"function hostSnapshotPending\(host\)\{.*?\n",
    r"function captureHostScrollState\(host\)\{.*?\n\}\n",
    r"function scrollStateIsStale\(host,state\)\{.*?\n\}\n",
    r"function restoreHostScrollState\(host,state\)\{.*?\n\}\n",
    r"const SNAPSHOT_PENDING_TIMEOUT_MS=.*?\n",
    r"let snapshotEpochSeq=.*?\n",
    r"function beginPaneSnapshot\(pane,\{timeout=true\}=\{\}\)\{.*?\n\}\n",
    r"function writePaneOutput\(pane,msg\)\{.*?\n\}\n",
    r"function relandAfterBufferReset\(pane\)\{.*?\n\}\n",
    r"function endPaneSnapshot\(pane,token=null\)\{.*?\n\}\n",
    r"const READER_SCROLL_KEYS=.*?\n",
    r"function isReaderScrollKey\(event\)\{.*?\n\}\n",
    r"function markReaderScroll\(pane,\{assume=false\}=\{\}\)\{.*?\n\}\n",
    r"function landPaneOnBottom\(pane\)\{.*?\n\}\n",
    r"function stickFollowHost\(p\)\{.*?\n\}\n",
)

# Everything the extracted functions touch that lives elsewhere in the page.
# The buffer model is xterm's rule: output scrolls the view only while the view
# is already at the bottom.
HARNESS = r"""
let now=0;const timers=new Map();let timerSeq=0;
function setTimeout(fn,ms){timers.set(++timerSeq,{at:now+ms,fn});return timerSeq;}
function clearTimeout(id){timers.delete(id);}
function advance(ms){
  now+=ms;
  [...timers.entries()].filter(([,t])=>t.at<=now).sort((a,b)=>a[1].at-b[1].at)
    .forEach(([id,t])=>{timers.delete(id);t.fn();});
}
const frames=[];
function requestAnimationFrame(fn){frames.push(fn);return frames.length;}
function flushFrames(){frames.splice(0).forEach(fn=>fn());}
function paintPaneBottomJump(){}
function makePane(id,{session='s1'}={}){
  const buf={viewportY:0,baseY:0};
  const viewport={scrollTop:0,scrollHeight:10000,clientHeight:700};
  const host={dataset:{},scrollTop:0,scrollHeight:10000,clientHeight:700,
    isConnected:true,classList:{contains:()=>true},querySelector:()=>viewport};
  const writes=[];
  return {meta:{paneId:id},session,host,viewport,writes,buf,
    term:{buffer:{active:buf},write:(data,cb)=>writes.push(cb),
      scrollToBottom(){buf.viewportY=buf.baseY;}}};
}
/* xterm's own rule: new lines carry the view only if it sits at the bottom. */
function emit(pane,rows){
  const buf=pane.buf;const following=buf.viewportY===buf.baseY;
  buf.baseY+=rows;
  if(following)buf.viewportY=buf.baseY;
}
function scrolledUp(pane,rows){pane.buf.viewportY=Math.max(0,pane.buf.viewportY-rows);}
function atBottom(pane){return pane.buf.viewportY===pane.buf.baseY;}
const panes=new Map();
console.log(JSON.stringify(run()));
"""


def _strip_js_comments(source: str) -> str:
    """So that a wiring check cannot be satisfied by a commented-out call."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"(?m)^\s*//.*$", "", source)


def _output_handler() -> str:
    """The real `case "output"` body, wrapped so it can be called directly.

    Testing writePaneOutput alone would still pass if the message handler
    stopped calling it.
    """
    html = COCKPIT.read_text(encoding="utf-8")
    match = re.search(r'case "output":\{\n(.*?)\n    \}\n', html, re.DOTALL)
    assert match, "missing the output case in handle()"
    return "function handleOutput(msg){switch(0){case 0:{\n%s\n}}}" % match.group(1)


def _run(body: str) -> dict:
    html = COCKPIT.read_text(encoding="utf-8")
    parts = [_output_handler()]
    for pattern in BLOCKS:
        match = re.search(pattern, html, re.DOTALL)
        assert match, f"missing block in cockpit.html: {pattern}"
        parts.append(match.group(0))
    script = "\n".join([f"function run(){{\n{body}\n}}", *parts, HARNESS])
    done = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# --- the replay window: a position read mid-replay is never restored ---------


def test_a_stale_position_is_not_put_back_on_the_viewport():
    """The deferred rAF restore in focusTerminalPreservingScroll runs a frame
    after the replay may have finished, carrying a mid-write position."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        const token=beginPaneSnapshot(p,{timeout:false});
        p.viewport.scrollTop=300;                   // xterm is mid-parse
        const preserved=captureHostScrollState(p.host);
        endPaneSnapshot(p,token);
        p.viewport.scrollTop=9300;                  // where the replay ended
        restoreHostScrollState(p.host,preserved);   // the late rAF
        return {viewport:p.viewport.scrollTop};
        """
    )
    assert result["viewport"] == 9300, result


def test_a_position_from_before_the_replay_is_not_restored_into_it():
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        p.viewport.scrollTop=300;                 // reader had scrolled up
        const before=captureHostScrollState(p.host);
        beginPaneSnapshot(p,{timeout:false});     // replay starts
        p.viewport.scrollTop=1200;
        restoreHostScrollState(p.host,before);    // a resize lands mid-write
        return {viewport:p.viewport.scrollTop};
        """
    )
    assert result["viewport"] == 1200, result


def test_a_position_from_an_earlier_generation_is_not_restored_after_one():
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        p.viewport.scrollTop=300;
        const before=captureHostScrollState(p.host);
        const token=beginPaneSnapshot(p,{timeout:false});
        endPaneSnapshot(p,token);
        p.viewport.scrollTop=9300;
        restoreHostScrollState(p.host,before);
        return {viewport:p.viewport.scrollTop};
        """
    )
    assert result["viewport"] == 9300, result


def test_an_ordinary_position_is_still_restored():
    """The guard must not swallow the case it exists to protect: a reader's
    position across a resize, outside any replay."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        const token=beginPaneSnapshot(p,{timeout:false});
        endPaneSnapshot(p,token);                 // replay over
        p.viewport.scrollTop=300;                 // the reader scrolled up
        const state=captureHostScrollState(p.host);
        p.viewport.scrollTop=9300;                // a resize moved it
        restoreHostScrollState(p.host,state);
        return {viewport:p.viewport.scrollTop};
        """
    )
    assert result["viewport"] == 300, result


def test_state_captured_mid_replay_reports_the_pane_as_following():
    """resizePaneToFollow seeds the pane's _xtermAtBottom from this flag, and a
    pane that starts with follow disabled never turns it back on by itself."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        beginPaneSnapshot(p,{timeout:false});
        p.viewport.scrollTop=300;      // xterm is mid-parse, not a reader
        const s=captureHostScrollState(p.host);
        return {pending:s.pending,viewportAtBottom:s.viewportAtBottom,
                hostAtBottom:s.hostAtBottom};
        """
    )
    assert result == {
        "pending": True,
        "viewportAtBottom": True,
        "hostAtBottom": True,
    }, result


def test_a_mid_replay_state_is_stale_inside_its_own_generation():
    """The two halves of the guard answer different questions. Generation alone
    cannot see this one: the state was taken in the generation the pane is
    still in, and closing the window does not advance it."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        const token=beginPaneSnapshot(p,{timeout:false});
        const s=captureHostScrollState(p.host);
        const duringWrite=scrollStateIsStale(p.host,s);
        endPaneSnapshot(p,token);
        return {duringWrite,afterWrite:scrollStateIsStale(p.host,s),
                sameGeneration:s.epoch===paneSnapshotEpoch(p.host)};
        """
    )
    assert result == {
        "duringWrite": True,
        "afterWrite": True,
        "sameGeneration": True,
    }, result


# --- the replay window: ownership and lifetime -------------------------------


def test_the_replay_lands_the_pane_through_the_terminal():
    """Not through the DOM: mid-write the viewport element has not grown yet,
    so a bottom computed from scrollHeight is 0."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        const token=beginPaneSnapshot(p,{timeout:false});
        p.buf.baseY=966;p.buf.viewportY=0;          // replay parsed, view high
        p.viewport.scrollHeight=p.viewport.clientHeight;   // DOM not caught up
        endPaneSnapshot(p,token);
        return {ydisp:p.buf.viewportY,base:p.buf.baseY};
        """
    )
    assert result == {"ydisp": 966, "base": 966}, result


def test_the_replay_window_does_not_time_out():
    """The write owns its window. A timeout would drop the guard mid-parse and
    reopen the bug, which is what the first fix did."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        beginPaneSnapshot(p);                        // speculative, on create
        handleOutput({paneId:'pane-1',session:'s1',data:'x',snapshot:true});
        advance(SNAPSHOT_PENDING_TIMEOUT_MS*3);       // xterm is still parsing
        const pendingDuringWrite=hostSnapshotPending(p.host);
        p.buf.baseY=966;p.buf.viewportY=0;
        p.writes.pop()();                             // xterm finishes
        return {pendingDuringWrite,closed:!hostSnapshotPending(p.host),
                landed:atBottom(p)};
        """
    )
    assert result == {
        "pendingDuringWrite": True,
        "closed": True,
        "landed": True,
    }, result


def test_the_speculative_window_times_out_and_a_late_replay_still_lands():
    """An empty capture is sent no output at all, so the create-time window has
    to expire — and a capture that arrives after it must still land."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        beginPaneSnapshot(p);
        advance(SNAPSHOT_PENDING_TIMEOUT_MS+1);
        const releasedForIdlePane=!hostSnapshotPending(p.host);
        handleOutput({paneId:'pane-1',session:'s1',data:'x',snapshot:true});
        const reopened=hostSnapshotPending(p.host);
        p.buf.baseY=966;p.buf.viewportY=0;
        p.writes.pop()();
        return {releasedForIdlePane,reopened,landed:atBottom(p)};
        """
    )
    assert result == {
        "releasedForIdlePane": True,
        "reopened": True,
        "landed": True,
    }, result


def test_live_output_neither_opens_nor_closes_the_window():
    """The backend adds the peer to its client set before it captures, so live
    output can arrive ahead of the replay. Driven through the real message
    handler, so this also fails if the handler stops using writePaneOutput."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        beginPaneSnapshot(p);
        handleOutput({paneId:'pane-1',session:'s1',data:'live'});
        p.writes.pop()();
        const stillPending=hostSnapshotPending(p.host);
        handleOutput({paneId:'pane-1',session:'s1',data:'snap',snapshot:true});
        const reopened=hostSnapshotPending(p.host);
        p.buf.baseY=966;p.buf.viewportY=0;
        p.writes.pop()();
        return {stillPending,reopened,landed:atBottom(p)};
        """
    )
    assert result == {"stillPending": True, "reopened": True, "landed": True}, result


def test_a_finished_window_does_not_close_the_next_one():
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        writePaneOutput(p,{data:'a',snapshot:true});
        const finishA=p.writes.pop();
        writePaneOutput(p,{data:'b',snapshot:true});   // B takes over
        const finishB=p.writes.pop();
        finishA();                                     // A's callback, late
        const stillPendingForB=hostSnapshotPending(p.host);
        finishB();
        return {stillPendingForB,closed:!hostSnapshotPending(p.host)};
        """
    )
    assert result == {"stillPendingForB": True, "closed": True}, result


def test_a_replaced_pane_is_not_yanked_by_the_old_ones_callback():
    """reset closes and recreates panes under the same id. A write callback
    still held by the old object must not reach through the id and drag the
    new pane away from where its reader left it."""
    result = _run(
        """
        const old=makePane('pane-1');panes.set('pane-1',old);
        writePaneOutput(old,{data:'old',snapshot:true});
        const finishOld=old.writes.pop();
        const fresh=makePane('pane-1');panes.set('pane-1',fresh);   // reset
        fresh.buf.baseY=966;fresh.buf.viewportY=966;
        const token=beginPaneSnapshot(fresh,{timeout:false});
        endPaneSnapshot(fresh,token);
        scrolledUp(fresh,400);                   // the reader scrolled up
        finishOld();                             // the old callback, late
        return {readerKept:fresh.buf.viewportY===566};
        """
    )
    assert result["readerKept"] is True, result


def test_panes_hold_independent_windows():
    result = _run(
        """
        const a=makePane('pane-a');panes.set('pane-a',a);
        const b=makePane('pane-b');panes.set('pane-b',b);
        writePaneOutput(a,{data:'a',snapshot:true});
        writePaneOutput(b,{data:'b',snapshot:true});
        a.buf.baseY=100;a.buf.viewportY=0;b.buf.baseY=100;b.buf.viewportY=0;
        a.writes.pop()();
        return {aClosed:!hostSnapshotPending(a.host),
                bStillPending:hostSnapshotPending(b.host),
                aLanded:atBottom(a),bLanded:atBottom(b)};
        """
    )
    assert result == {
        "aClosed": True,
        "bStillPending": True,
        "aLanded": True,
        "bLanded": False,
    }, result


# --- the repaint: a clamped viewport is not a reader -------------------------


def test_a_repaint_that_clears_the_buffer_lands_the_pane_again():
    """The CLI reflows, clears, and reprints. The clamp that follows makes
    xterm stop following, so the reprinted history would end up scrolled to the
    top. A buffer that shrank is not a reader."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        p.buf.baseY=966;p.buf.viewportY=966;
        writePaneOutput(p,{data:'settled'});p.writes.pop()();
        p.buf.baseY=0;p.buf.viewportY=0;          // the CLI cleared the screen
        writePaneOutput(p,{data:'repaint'});p.writes.pop()();
        p.buf.viewportY=0;                        // the browser clamped it
        flushFrames();                            // xterm resized its spacer
        emit(p,966);                              // the transcript reprints
        return {ydisp:p.buf.viewportY,base:p.buf.baseY,following:atBottom(p)};
        """
    )
    assert result["following"] is True, result
    assert result["ydisp"] == 966, result


def test_live_output_reasserts_the_bottom_until_a_gesture_says_otherwise():
    """xterm's own follow cannot be trusted through a repaint, and a scroll
    event cannot tell a clamp from a reader. A gesture and its outcome can."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        p.buf.baseY=500;p.buf.viewportY=500;
        scrolledUp(p,200);                    // a clamp, no gesture
        stickFollowHost(p);
        const recovered=atBottom(p);
        markReaderScroll(p,{assume:true});    // a real wheel event
        scrolledUp(p,200);
        flushFrames();                        // the outcome is sampled
        stickFollowHost(p);
        return {recovered,readerKept:p.buf.viewportY===300};
        """
    )
    assert result == {"recovered": True, "readerKept": True}, result


def test_a_gesture_that_ends_at_the_bottom_is_not_a_reader():
    """Rolling the wheel while already at the bottom, or scrolling back down to
    it. Treating either as "the reader is reading" would silence the clamp
    recovery for the rest of the pane's life."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        p.buf.baseY=500;p.buf.viewportY=500;
        markReaderScroll(p,{assume:true});   // wheel, but the view stays put
        flushFrames();
        const atBottomGesture=Boolean(p._readerScrolled);
        markReaderScroll(p,{assume:true});scrolledUp(p,200);flushFrames();
        const readingNow=Boolean(p._readerScrolled);
        markReaderScroll(p,{assume:true});   // wheel back down
        p.buf.viewportY=p.buf.baseY;flushFrames();
        return {atBottomGesture,readingNow,backAtBottom:Boolean(p._readerScrolled)};
        """
    )
    assert result == {
        "atBottomGesture": False,
        "readingNow": True,
        "backAtBottom": False,
    }, result


def test_clicking_into_a_pane_is_not_scrolling():
    """mousedown is focus, selection and link clicks as much as a scrollbar
    drag, so it may not assume intent — only its outcome counts."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        p.buf.baseY=500;p.buf.viewportY=500;
        markReaderScroll(p);              // a click to type into the pane
        const immediately=Boolean(p._readerScrolled);
        flushFrames();
        scrolledUp(p,200);                // a later clamp
        stickFollowHost(p);
        return {immediately,recovered:atBottom(p)};
        """
    )
    assert result == {"immediately": False, "recovered": True}, result


def test_a_protected_gesture_survives_output_before_the_sample():
    """The sample lands a frame later; a line of output in between must not
    undo a reader who has just paged up or grabbed the scrollbar."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        p.buf.baseY=500;p.buf.viewportY=500;
        markReaderScroll(p,{assume:isReaderScrollKey(
          {shiftKey:true,key:'PageUp'})});
        scrolledUp(p,200);            // xterm scrolled its own viewport
        stickFollowHost(p);           // live output, before the frame
        const keptBeforeSample=p.buf.viewportY===300;
        flushFrames();
        stickFollowHost(p);
        return {keptBeforeSample,keptAfterSample:p.buf.viewportY===300};
        """
    )
    assert result == {"keptBeforeSample": True, "keptAfterSample": True}, result


def test_typing_is_not_reading_even_with_a_modifier():
    result = _run(
        """
        const keys=[{shiftKey:true,key:'PageUp'},{shiftKey:true,key:'End'},
                    {shiftKey:false,key:'PageUp'},{shiftKey:true,key:'a'},
                    {shiftKey:true,key:'Enter'}];
        return {flags:keys.map(k=>isReaderScrollKey(k))};
        """
    )
    assert result["flags"] == [True, True, False, False, False], result


def test_keyboard_scrollback_counts_as_reading():
    """xterm handles Shift+PageUp itself, as a local viewport scroll that emits
    no pointer event — without keydown the reader is yanked by the next line."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        p.buf.baseY=500;p.buf.viewportY=500;
        markReaderScroll(p);              // keydown: Shift+PageUp
        scrolledUp(p,200);                // xterm scrolled the viewport
        flushFrames();
        stickFollowHost(p);
        const kept=p.buf.viewportY===300;
        markReaderScroll(p);              // Shift+PageDown, back to the bottom
        p.buf.viewportY=p.buf.baseY;flushFrames();
        emit(p,10);
        return {kept,followsAgain:atBottom(p)};
        """
    )
    assert result == {"kept": True, "followsAgain": True}, result


def test_landing_clears_the_reader_gesture():
    """Otherwise one wheel event would disable follow for the life of the pane,
    including across the next replay."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        p.buf.baseY=500;p.buf.viewportY=300;
        markReaderScroll(p,{assume:true});flushFrames();   // reading history
        const reading=Boolean(p._readerScrolled);
        p.buf.viewportY=0;
        landPaneOnBottom(p);
        const landed=atBottom(p);
        scrolledUp(p,200);                 // a clamp after the landing
        stickFollowHost(p);
        return {reading,landed,recovers:atBottom(p)};
        """
    )
    assert result == {"reading": True, "landed": True, "recovers": True}, result


def test_a_repaint_recovers_a_pane_whose_reader_had_scrolled_up():
    """The reassert alone cannot help here: the gesture flag is set, and it is
    correct that it silences the reassert. What the reader was looking at no
    longer exists once the buffer is cleared."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        p.buf.baseY=966;p.buf.viewportY=966;
        writePaneOutput(p,{data:'settled'});p.writes.pop()();
        markReaderScroll(p);scrolledUp(p,400);   // the reader is reading
        p.buf.baseY=0;p.buf.viewportY=0;         // the CLI cleared the screen
        writePaneOutput(p,{data:'repaint'});p.writes.pop()();
        emit(p,966);                             // the transcript reprints
        return {following:atBottom(p),ydisp:p.buf.viewportY};
        """
    )
    assert result == {"following": True, "ydisp": 966}, result


def test_the_clamp_that_lands_a_frame_later_is_undone_too():
    """xterm resizes its spacer on the next frame; the browser clamps then, not
    when the write callback ran."""
    result = _run(
        """
        const p=makePane('pane-1');panes.set('pane-1',p);
        p.buf.baseY=966;p.buf.viewportY=966;
        writePaneOutput(p,{data:'settled'});p.writes.pop()();
        p.buf.baseY=0;p.buf.viewportY=0;
        writePaneOutput(p,{data:'repaint'});p.writes.pop()();
        emit(p,300);                  // some of the transcript is back
        markReaderScroll(p);          // the clamp reads as a gesture
        scrolledUp(p,300);
        flushFrames();                // the deferred re-land
        emit(p,666);
        return {following:atBottom(p),ydisp:p.buf.viewportY};
        """
    )
    assert result == {"following": True, "ydisp": 966}, result


# --- wiring and the backend contract ----------------------------------------


def test_a_new_pane_starts_inside_a_window():
    """A pane that has not received its replay yet has no position worth
    preserving. Wiring check: the behaviour is covered above, this pins that
    createPane still opens the window."""
    source = _strip_js_comments(COCKPIT.read_text(encoding="utf-8"))
    index = source.index("const paneRec={session,meta:normalized,term,fit,host,tab")
    assert "beginPaneSnapshot(paneRec)" in source[index : index + 400]


def test_reader_gestures_are_wired_to_the_pane():
    source = _strip_js_comments(COCKPIT.read_text(encoding="utf-8"))
    index = source.index("host.addEventListener('scroll'")
    window = source[index : index + 1200]
    # keydown matters as much as the pointer events: xterm handles
    # Shift+PageUp itself, with no pointer event to observe. mouseup matters
    # because a scrollbar drag ends somewhere else than it began.
    for gesture in ("wheel", "touchmove", "mousedown", "keydown", "mouseup"):
        assert gesture in window, f"{gesture} is not marking reader intent"
    assert "markReaderScroll(paneRec)" in window
    # The two gestures that can be known to be scrolling say so immediately,
    # instead of leaving the reader unprotected until the sample lands.
    assert "assume:isReaderScrollKey(event)" in window
    assert "assume:eventTargetsXtermScrollbar(event)" in window


def _output_messages() -> dict[str, list[dict]]:
    """Every `{"type": "output", ...}` the backend builds, by enclosing
    function. Read from the syntax tree, so a commented-out marker is absent
    rather than found by a substring search."""
    tree = ast.parse(CONTROL_SERVER.read_text(encoding="utf-8"))
    found: dict[str, list[dict]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Dict):
                continue
            keys = [
                k.value if isinstance(k, ast.Constant) else None for k in inner.keys
            ]
            if "type" not in keys:
                continue
            kind = inner.values[keys.index("type")]
            if not (isinstance(kind, ast.Constant) and kind.value == "output"):
                continue
            entry = {
                key: (
                    value.value
                    if isinstance(value, ast.Constant)
                    else ast.unparse(value)
                )
                for key, value in zip(keys, inner.values)
            }
            found.setdefault(node.name, []).append(entry)
    return found


def test_replay_captures_are_marked_and_live_output_is_not():
    """The client cannot infer which output is a replay; the marker is the
    whole mechanism. Marking live output too would make every tick a replay."""
    messages = _output_messages()
    replay = {"send_snapshot", "refresh_panes"}
    assert replay <= set(messages), messages.keys()
    for name, sent in messages.items():
        for message in sent:
            marked = message.get("snapshot") is True
            if name in replay:
                assert marked, f"{name} sends an unmarked replay capture"
            else:
                assert not marked, f"{name} marks live output as a replay"
