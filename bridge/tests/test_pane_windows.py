"""Pane windows: a session taken out of the cockpit (2026-09-29).

A session tab dragged out of the strip floats over the cockpit, or becomes
its own window (a browser popup, or a Tauri window in ORRERY.app).  Both are
the cockpit page in solo mode on the same backend, so they share the
session's recorder instead of opening another tmux client.  The pure helpers
run under node from the real cockpit.html; the wiring checks read the page
and the app sources, which have no browser here to run in.

Run from bridge/: ``python -m pytest tests/test_pane_windows.py``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = Path(os.environ.get("ORRERY_BRIDGE_SOURCES", ROOT))
COCKPIT = SOURCES / "cockpit.html"
APP = ROOT.parent / "app" / "src-tauri"

PURE_BLOCK = r"/\* ── pane windows: one session taken out of the cockpit.*?(?=/\* COCKPIT_PURE_LOGIC_END \*/)"


def _html() -> str:
    return COCKPIT.read_text(encoding="utf-8")


def _run(body: str):
    match = re.search(PURE_BLOCK, _html(), re.DOTALL)
    assert match, "pane-window helpers missing from cockpit.html"
    script = f"{match.group(0)}\nconsole.log(JSON.stringify((()=>{{{body}}})()));"
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# --- the solo page and its address ---------------------------------------------


def test_solo_mode_needs_both_the_flag_and_a_session():
    r = _run("""return [
      soloSessionFrom('?solo=1&session=CoralCurie'),
      soloSessionFrom('?session=CoralCurie'),
      soloSessionFrom('?solo=1'),
      soloSessionFrom('?solo=0&session=CoralCurie'),
      soloSessionFrom(''),
    ];""")
    assert r == ["CoralCurie", "", "", "", ""]


def test_window_url_keeps_origin_and_backend_but_nothing_else():
    r = _run("""return [
      paneWindowUrl('http://127.0.0.1:8791/cockpit.html?popout=x&session=Old#frag','Coral Curie&x'),
      paneWindowUrl('http://127.0.0.1:8791/cockpit.html?ws=ws%3A%2F%2F127.0.0.1%3A9%2Fws','A'),
    ];""")
    first, second = r
    assert first.startswith("http://127.0.0.1:8791/cockpit.html?")
    assert "#" not in first and "popout" not in first and "Old" not in first
    assert "solo=1" in first and "session=Coral+Curie%26x" in first
    assert "ws=ws%3A%2F%2F127.0.0.1%3A9%2Fws" in second


def test_window_names_are_distinct_for_names_that_look_alike():
    r = _run("""const S='ws://127.0.0.1:8791/ws';
      return [paneWindowName(S,'a_b'),paneWindowName(S,'a-b'),paneWindowName(S,'日本')];""")
    assert len(set(r)) == 3
    assert all(re.fullmatch(r"orrery-pane-[0-9a-f]+", name) for name in r)


# --- one origin, several backends (review of 3232dba, P2-2) -----------------------


def test_the_backend_scope_separates_same_named_sessions():
    r = _run("""
      const A=paneScopeFrom('ws://127.0.0.1:8791/ws');
      const B=paneScopeFrom('ws://127.0.0.1:59751/ws2');
      return {
        A,B,
        sameScopeIgnoresQuery:paneScopeFrom('ws://127.0.0.1:8791/ws?x=1')===A,
        names:paneWindowName(A,'ReviewAlpha')!==paneWindowName(B,'ReviewAlpha'),
        drafts:paneDraftKey(A,'ReviewAlpha')!==paneDraftKey(B,'ReviewAlpha'),
        inScope:paneMessageInScope({type:'open',session:'ReviewAlpha',scope:A},A),
        otherBackend:paneMessageInScope({type:'open',session:'ReviewAlpha',scope:B},A),
        unscoped:paneMessageInScope({type:'open',session:'ReviewAlpha'},A),
      };""")
    assert r["A"] == "ws://127.0.0.1:8791/ws" and r["B"] == "ws://127.0.0.1:59751/ws2"
    assert r["sameScopeIgnoresQuery"] and r["names"] and r["drafts"]
    assert r["inScope"] is True and r["otherBackend"] is False and r["unscoped"] is False


def test_every_channel_message_is_scoped_and_checked_first():
    html = _html()
    post = _function_body("postPaneMessage")
    assert "scope:paneScope" in post
    handler = html[html.index("paneChannel.addEventListener('message'"):]
    first_lines = handler.split("\n")[:3]
    assert any("paneMessageInScope(msg,paneScope)" in line for line in first_lines)
    assert "paneWindowName(paneScope,session)" in html
    assert "const paneScope=paneScopeFrom(wsUrl);" in html


# --- unsent text in a window (review of 3232dba, P2-1) ------------------------------


def test_a_windows_unsent_text_comes_back_without_overwriting_the_cockpit():
    r = _run("""return {
      nothing:returnedDraftPlan('ALPHA draft',''),
      blank:returnedDraftPlan('ALPHA draft','   '),
      emptyCockpit:returnedDraftPlan('','BETA new unfinished instruction'),
      sameText:returnedDraftPlan('BETA x','BETA x'),
      cockpitHasOther:returnedDraftPlan('ALPHA unfinished instruction','BETA new unfinished instruction'),
    };""")
    assert r == {"nothing": "none", "blank": "none", "emptyCockpit": "restore",
                 "sameText": "restore", "cockpitHasOther": "keep"}


def test_a_pane_window_keeps_its_own_draft_and_the_cockpit_takes_it_back():
    html = _html()
    assert "const PROMPT_DRAFT_KEY=soloSession?paneDraftKey(paneScope,soloSession):'oc-prompt-draft';" in html
    assert "takeBackPaneDraft(session);" in _function_body("returnPaneSession")
    # Returning only marks the text as waiting; nothing reaches the composer
    # (or leaves the window's key) until that session is the active pane here,
    # and a session that is gone keeps its text (review of f25e5b4).
    take = _function_body("takeBackPaneDraft")
    assert "promptInput.value" not in take and "removeItem" not in take
    assert "if(!availableSessions.has(session)){" in take
    assert "pendingPaneDraft=session;" in take
    restore = _function_body("restorePendingPaneDraft")
    assert restore.lstrip().startswith("if(!session||pendingPaneDraft!==session)return;")
    assert "returnedDraftPlan(promptInput.value,text)" in restore
    assert "localStorage.removeItem(key)" in restore.split("else if")[0]  # only after restoring
    assert "showToast(" in restore.split("else if")[1]                  # kept text is announced
    assert ("document.addEventListener('oc:focus-agent',event=>"
            "restorePendingPaneDraft(event.detail&&event.detail.name));") in html
    set_active = _function_body("setActive")
    assert "new CustomEvent('oc:focus-agent',{detail:{name:p.session}})" in set_active


def test_history_merges_into_what_is_stored_now():
    r = _run("""return [
      mergePromptHistory(['a','b','c'],'d'),
      mergePromptHistory(['a','b'],'b'),
      mergePromptHistory(null,'x'),
      mergePromptHistory(['a',3,'b'],'c'),
      mergePromptHistory(Array.from({length:50},(_,i)=>'h'+i),'new').length,
    ];""")
    assert r[0] == ["a", "b", "c", "d"]
    assert r[1] == ["a", "b"]
    assert r[2] == ["x"]
    assert r[3] == ["a", "b", "c"]
    assert r[4] == 50
    push = _function_body("pushPromptHistory")
    assert "localStorage.getItem(PROMPT_HISTORY_KEY)" in push
    assert "mergePromptHistory(stored,text)" in push


# --- where a drop lands ----------------------------------------------------------


def test_outside_includes_the_edge_band_so_a_maximized_window_can_drop_out():
    r = _run("""const W=1512,H=802;return {
      inside:pointerLeftViewport(700,400,W,H),
      justInside:pointerLeftViewport(8,8,W,H),
      rightEdge:pointerLeftViewport(W-3,400,W,H),
      topEdge:pointerLeftViewport(700,2,W,H),
      beyond:pointerLeftViewport(-40,400,W,H),
      below:pointerLeftViewport(700,H+30,W,H),
      hiddenWindow:pointerLeftViewport(700,400,0,0),
      garbage:pointerLeftViewport(NaN,400,W,H),
    };""")
    assert r == {
        "inside": False, "justInside": False, "rightEdge": True, "topEdge": True,
        "beyond": True, "below": True, "hiddenWindow": False, "garbage": False,
    }


def test_new_window_opens_under_the_pointer_and_stays_on_its_screen():
    r = _run("""return {
      centered:paneWindowGeometry({screenX:500,screenY:300,width:760,height:540,
        availLeft:0,availTop:0,availWidth:1512,availHeight:945}),
      rightEdge:paneWindowGeometry({screenX:1500,screenY:900,width:760,height:540,
        availLeft:0,availTop:0,availWidth:1512,availHeight:945}),
      upperDisplay:paneWindowGeometry({screenX:-1100,screenY:-1040,width:760,height:540,
        availLeft:-1140,availTop:-1050,availWidth:1920,availHeight:1050}),
      tiny:paneWindowGeometry({screenX:10,screenY:10,width:50,height:50,
        availLeft:0,availTop:0,availWidth:1512,availHeight:945}),
    };""")
    assert r["centered"] == {"left": 120, "top": 286, "width": 760, "height": 540}
    assert r["rightEdge"] == {"left": 752, "top": 405, "width": 760, "height": 540}
    assert r["upperDisplay"] == {"left": -1140, "top": -1050, "width": 760, "height": 540}
    assert r["tiny"]["width"] >= 360 and r["tiny"]["height"] >= 240


def test_a_float_may_hang_off_the_cockpit_but_its_bar_stays_reachable():
    r = _run("""return [
      clampFloatRect({left:-900,top:-50,width:600,height:400},1512,802),
      clampFloatRect({left:1500,top:900,width:600,height:400},1512,802),
      clampFloatRect({left:300,top:200,width:600,height:400},1512,802),
    ];""")
    assert r[0] == {"left": 96 - 600, "top": 0, "width": 600, "height": 400}
    assert r[1] == {"left": 1512 - 96, "top": 802 - 30, "width": 600, "height": 400}
    assert r[2] == {"left": 300, "top": 200, "width": 600, "height": 400}


# --- which channel messages change the cockpit ------------------------------------


def test_channel_messages_only_act_on_the_window_they_belong_to():
    r = _run("""
      const FLOAT={kind:'float'},NEW={kind:'window',instance:null},BOUND={kind:'window',instance:'w1'};
      const m=(type,id='w1',extra={})=>({type,session:'S',id,...extra});
      return {
        adoptUnknown:paneWindowMessageEffect(undefined,m('open')),
        bindNewWindow:paneWindowMessageEffect(NEW,m('open')),
        floatIgnoresOpen:paneWindowMessageEffect(FLOAT,m('open')),
        boundIgnoresSecondOpen:paneWindowMessageEffect(BOUND,m('open','w2')),
        closedReturns:paneWindowMessageEffect(BOUND,m('closed')),
        staleFloatGoodbye:paneWindowMessageEffect(NEW,m('closed','iframe')),
        otherInstanceGoodbye:paneWindowMessageEffect(BOUND,m('closed','w2')),
        floatIgnoresClosed:paneWindowMessageEffect(FLOAT,m('closed')),
        returnFromWindow:paneWindowMessageEffect(BOUND,m('return')),
        returnFromOther:paneWindowMessageEffect(BOUND,m('return','w2')),
        returnUnknown:paneWindowMessageEffect(undefined,m('return')),
        noSession:paneWindowMessageEffect(BOUND,{type:'closed',id:'w1'}),
        hello:paneWindowMessageEffect(undefined,{type:'hello',id:'x'}),
      };""")
    assert r == {
        "adoptUnknown": "adopt", "bindNewWindow": "bind", "floatIgnoresOpen": "ignore",
        "boundIgnoresSecondOpen": "ignore", "closedReturns": "return",
        "staleFloatGoodbye": "ignore", "otherInstanceGoodbye": "ignore",
        "floatIgnoresClosed": "ignore", "returnFromWindow": "return",
        "returnFromOther": "ignore", "returnUnknown": "ignore",
        "noSession": "ignore", "hello": "ignore",
    }


# --- wiring that keeps the default cockpit as it was --------------------------------


def _function_body(name: str) -> str:
    html = _html()
    match = re.search(rf"function {name}\([^)]*\)\{{\n(.*?)\n\}}\n", html, re.DOTALL)
    assert match, f"{name} not found"
    return match.group(1)


def test_a_session_that_is_out_is_never_attached_again_by_the_cockpit():
    assert _function_body("requestAttach").lstrip().startswith("if(!paneSessionAllowed(session))return false;")
    assert "paneWindows.has(name)" in _function_body("jumpToSessionTarget").splitlines()[0]
    assert "paneWindows.has(session)" in _function_body("toggleSplitSession").splitlines()[0]
    allowed = _function_body("paneSessionAllowed")
    assert "soloSession?session===soloSession:!paneWindows.has(session)" in allowed


def test_a_pane_window_polls_only_what_one_terminal_needs():
    html = _html()
    assert "if(!soloSession){pollUsage(false);" in html
    tail = html[html.index("if(soloSession){pollAgents();"):]
    solo_branch = tail[: tail.index("else{")]
    assert "pollMail" not in solo_branch and "pollGraph" not in solo_branch


def test_the_solo_class_is_set_before_first_paint():
    html = _html()
    head = html[: html.index("</head>")]
    assert "root.classList.add('pane-window')" in head
    assert "html.pane-window header" in head


def test_the_app_grants_pane_windows_the_cockpit_capability_and_commands():
    capability = json.loads((APP / "capabilities" / "default.json").read_text(encoding="utf-8"))
    assert "pane-*" in capability["windows"]
    commands = ("open_pane_window", "focus_pane_window", "close_pane_window")
    for command in commands:
        assert f"allow-{command.replace('_', '-')}" in capability["permissions"]
    build = (APP / "build.rs").read_text(encoding="utf-8")
    lib = (APP / "src" / "lib.rs").read_text(encoding="utf-8")
    handler = lib[lib.index("generate_handler!["):]
    handler = handler[: handler.index("])")]
    for command in commands:
        assert f'"{command}"' in build
        assert command in handler
        assert f"invoke('{command}'" in _html()
    assert 'const PANE_WINDOW_PREFIX: &str = "pane-";' in lib
    assert "'orrery://pane-window-closed'" in _html()
    assert '"orrery://pane-window-closed"' in lib


def test_late_pane_events_for_a_session_that_is_out_are_dropped():
    """Popping out detaches the session, but a resync the backend queued before
    the detach recreated the pane under the window (seen 2026-09-29)."""
    body = _function_body("handle")
    first = body.split("switch(msg.type){")[0]
    assert "paneWindows.has(msg.session)" in first
    for kind in ("reset", "add", "update"):
        assert f"msg.type==='{kind}'" in first


def test_a_pane_window_attaches_its_session_again_after_a_reconnect():
    """The deep link is spent on the first sessions event; a pane window has no
    roster to pick from, so a reconnect must reattach it (review of 3232dba)."""
    body = _function_body("handle")
    sessions_case = body[body.index('case "sessions":'):body.index('case "reset":')]
    assert ("else if(soloSession&&availableSessions.has(soloSession)"
            "&&!occupiedSessions().has(soloSession))requestAttach(soloSession,true);") in sessions_case


def test_the_apps_closed_event_is_matched_to_this_backend():
    """A window closed on another backend must not bring back the same-named
    session here (review of f25e5b4): the app sends the window's address and
    the cockpit derives the backend scope from it."""
    r = _run("""
      const cockpit='http://127.0.0.1:8791/cockpit.html';
      const other='http://127.0.0.1:8791/cockpit.html?ws='+encodeURIComponent('ws://127.0.0.1:9/ws2');
      const own=paneScopeFrom('ws://127.0.0.1:8791/ws');
      return {
        ownWindow:paneScopeFromPageUrl(paneWindowUrl(cockpit,'Beta'))===own,
        otherWindow:paneScopeFromPageUrl(paneWindowUrl(other,'Beta'))===own,
        otherScope:paneScopeFromPageUrl(paneWindowUrl(other,'Beta')),
        secure:paneScopeFromPageUrl('https://h.example/cockpit.html?solo=1&session=B'),
        garbage:paneScopeFromPageUrl(undefined),
      };""")
    assert r == {"ownWindow": True, "otherWindow": False, "otherScope": "ws://127.0.0.1:9/ws2",
                 "secure": "wss://h.example/ws", "garbage": ""}
    html = _html()
    listener = html[html.index("listen('orrery://pane-window-closed'"):]
    listener = listener[: listener.index("}).catch(")]
    assert "paneScopeFromPageUrl(payload.url)!==paneScope" in listener
    lib = (APP / "src" / "lib.rs").read_text(encoding="utf-8")
    assert 'serde_json::json!({ "session": session, "url": url.as_str() })' in lib
