"""The cockpit follows the backend's host: labels, shortcuts and paste (2026-09-28).

On WSL the page is shown in a Windows browser. The three file routes of the
composer paste (a file item, an image item, a file:// uri-list) all depend on
the macOS pasteboard reader, and before this change the image route sent ^V
and toasted success even when nothing could be read. These run the real
functions from cockpit.html under node with the host swapped, and check that
WSL never reports a paste it did not make while the Mac keeps every route.
Since 2026-09-29 a WSL backend that can run powershell.exe reads the Windows
clipboard itself (file_paste: true), and only then do the WSL routes proceed.

Run from bridge/: ``python -m pytest tests/test_cockpit_host.py``.
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

BLOCKS = (
    r"/\* ── host: Mac, WSL or plain Linux.*?(?=/\* COCKPIT_PURE_LOGIC_END \*/)",
    r"function quotePath\(path\)\{.*?\n\}\n",
    r"function handleComposerPaste\(e\)\{.*?\n\}\n",
)

HARNESS = r"""
const toasts=[],sent=[],reads=[];let drafts=0;
function showToast(message,isError=false){toasts.push({message,isError});}
function send(msg){sent.push(msg);}
function saveDraft(){drafts++;}
let clipboardAnswer={files:[]};
function readClipboardFiles(){reads.push(1);return Promise.resolve(clipboardAnswer);}
const panes=new Map([['%1',{session:'orrery-A'}]]);let activeId='%1';
const promptInput={value:'',selectionStart:0,selectionEnd:0,
  setSelectionRange(){},focus(){}};
let hostPlatform;
function pasteEvent({items=[],plain='',uris=''}={}){
  const ev={prevented:false,preventDefault(){this.prevented=true;},
    clipboardData:{items,getData:t=>t==='text/plain'?plain:t==='text/uri-list'?uris:''}};
  return ev;
}
const FILE={kind:'file',type:'application/pdf'};
const IMAGE={kind:'file',type:'image/png'};
async function paste(host,spec,answer={files:[]}){
  hostPlatform=normalizeHostPlatform(host);clipboardAnswer=answer;
  toasts.length=0;sent.length=0;reads.length=0;promptInput.value='';
  const ev=pasteEvent(spec);handleComposerPaste(ev);
  await new Promise(r=>setTimeout(r,0));await new Promise(r=>setTimeout(r,0));
  return {prevented:ev.prevented,toasts:[...toasts],sent:[...sent],reads:reads.length,
    value:promptInput.value};
}
const MAC={host:'mac',terminal:{kind:'ghostty',label:'Ghostty',available:true},file_paste:true};
const WSL={host:'wsl',terminal:{kind:'wt',label:'Windows Terminal',available:true},file_paste:false};
const WSL_READER={...WSL,file_paste:true};
const LINUX={host:'linux',terminal:{kind:'ghostty',label:'Ghostty',available:true},file_paste:false};
run().then(r=>console.log(JSON.stringify(r)));
"""


def _run(body: str):
    html = COCKPIT.read_text(encoding="utf-8")
    parts = []
    for pattern in BLOCKS:
        match = re.search(pattern, html, re.DOTALL)
        assert match, f"missing block in cockpit.html: {pattern}"
        parts.append(match.group(0))
    script = "\n".join([f"async function run(){{\n{body}\n}}", *parts, HARNESS])
    done = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# --- paste ---------------------------------------------------------------------


def test_wsl_without_a_reader_does_not_report_any_of_the_three_file_routes_as_done():
    r = _run("""return {
      file:await paste(WSL,{items:[FILE]},{files:['/tmp/x.pdf']}),
      image:await paste(WSL,{items:[IMAGE]}),
      imageAfterReaderError:await paste(WSL,{items:[IMAGE]},{files:[],error:'clipboard_unsupported'}),
      uri:await paste(WSL,{uris:'file:///C:/Users/u/x.pdf'}),
    };""")
    for route, out in r.items():
        assert out["prevented"], route
        assert out["sent"] == [], route          # no ^V to the TUI
        assert out["reads"] == 0, route          # no pasteboard reader asked
        assert out["value"] == "", route         # nothing inserted
        assert len(out["toasts"]) == 1, route
        toast = out["toasts"][0]
        assert toast["isError"] is True, route
        assert "not available on Windows" in toast["message"], route


def test_an_undetermined_host_holds_the_three_file_routes():
    """Before /telemetry/platform answers, or when it failed, nothing is sent
    and nothing is reported as pasted (review of PR #2: the image route used
    to fall back to ^V and a success toast on a WSL backend)."""
    r = _run("""return {
      file:await paste(null,{items:[FILE]},{files:['/tmp/x.pdf']}),
      image:await paste(null,{items:[IMAGE]},{files:[],error:'clipboard_unsupported'}),
      imageBadAnswer:await paste({host:'windows'},{items:[IMAGE]}),
      uri:await paste(undefined,{uris:'file:///C:/Users/u/x.pdf'}),
      text:await paste(null,{plain:'hello'}),
    };""")
    for route in ("file", "image", "imageBadAnswer", "uri"):
        out = r[route]
        assert out["prevented"], route
        assert out["sent"] == [] and out["reads"] == 0 and out["value"] == "", route
        assert [t["isError"] for t in out["toasts"]] == [True], route
        assert "held" in out["toasts"][0]["message"], route
    assert r["text"]["prevented"] is False and r["text"]["toasts"] == []


def test_a_backend_without_a_reader_outranks_the_image_fallback():
    """Even on a host that allows the reader, clipboard_unsupported stops ^V."""
    r = _run("""return {
      mac:await paste(MAC,{items:[IMAGE]},{files:[],error:'clipboard_unsupported'}),
      prefixed:await paste(MAC,{items:[IMAGE]},{files:[],error:'app reader: x; clipboard_unsupported'}),
      linux:await paste(LINUX,{items:[IMAGE]},{files:[],error:'clipboard_unsupported'}),
    };""")
    for route, out in r.items():
        assert out["sent"] == [], route
        assert [t["isError"] for t in out["toasts"]] == [True], route
        assert "not available" in out["toasts"][0]["message"], route


def test_wsl_with_the_powershell_reader_pastes_windows_files_as_wsl_paths():
    """2026-09-29: the backend reads the Windows clipboard, so an Explorer
    copy lands as /mnt/c/... paths and a screenshot as the PNG it saved."""
    r = _run("""return {
      file:await paste(WSL_READER,{items:[FILE]},{files:['/mnt/c/Users/u/a b.pdf']}),
      image:await paste(WSL_READER,{items:[IMAGE]},
        {files:['/tmp/orrery-clipboard-1000/clipboard-1.png'],image:true}),
      uri:await paste(WSL_READER,{uris:'file:///C:/Users/u/x.pdf'},{files:['/mnt/c/Users/u/x.pdf']}),
    };""")
    assert r["file"]["value"] == "'/mnt/c/Users/u/a b.pdf'" and r["file"]["reads"] == 1
    assert r["image"]["value"] == "/tmp/orrery-clipboard-1000/clipboard-1.png"
    assert r["image"]["toasts"] == [{"message": "image saved as PNG → path → composer",
                                     "isError": False}]
    # the Windows file:// URI is never decoded into /C:/...; the backend answers
    assert r["uri"]["value"] == "/mnt/c/Users/u/x.pdf" and r["uri"]["reads"] == 1
    for route, out in r.items():
        assert out["prevented"] and out["sent"] == [], route


def test_wsl_says_which_files_did_not_become_wsl_paths():
    r = _run("""return await paste(WSL_READER,{items:[FILE]},
      {files:['/mnt/c/a.txt'],skipped:['\\\\\\\\server\\\\x.pdf']});""")
    assert r["value"] == "/mnt/c/a.txt"
    assert r["toasts"][-1]["isError"] is True
    assert r["toasts"][-1]["message"].startswith("1 of 2 files not pasted")
    assert "server" in r["toasts"][-1]["message"]


def test_wsl_never_falls_back_to_ctrl_v():
    """The TUI inside WSL cannot read the Windows clipboard: ^V would be
    reported as an image paste that read nothing."""
    r = _run("""return {
      empty:await paste(WSL_READER,{items:[IMAGE]},{files:[]}),
      noSession:await paste(WSL_READER,{items:[IMAGE]},{files:[],error:'clipboard_no_session'}),
      file:await paste(WSL_READER,{items:[FILE]},{files:[]}),
    };""")
    for route, out in r.items():
        assert out["sent"] == [] and out["value"] == "", route
        assert len(out["toasts"]) == 1, route
    assert r["empty"]["toasts"][0]["isError"] is True
    assert "Windows clipboard" in r["empty"]["toasts"][0]["message"]
    assert r["noSession"]["toasts"][0] == {
        "message": "clipboard reader failed (clipboard_no_session)", "isError": True}
    assert r["file"]["toasts"][0]["message"] == "nothing on the clipboard the composer can use"


def test_wsl_keeps_plain_text_paste():
    for host in ("WSL", "WSL_READER"):
        r = _run(f"return await paste({host},{{plain:'hello'}});")
        assert r == {"prevented": False, "toasts": [], "sent": [], "reads": 0, "value": ""}


def test_the_mac_keeps_every_route():
    r = _run("""return {
      file:await paste(MAC,{items:[FILE]},{files:['/tmp/a b.pdf']}),
      image:await paste(MAC,{items:[IMAGE]}),
      uri:await paste(MAC,{uris:'file:///Users/u/x.pdf'}),
      text:await paste(MAC,{plain:'hello'}),
    };""")
    assert r["file"]["value"] == "'/tmp/a b.pdf'"
    assert r["file"]["toasts"] == [{"message": "path → composer", "isError": False}]
    assert r["image"]["sent"] == [{"type": "input", "paneId": "%1", "data": "\x16"}]
    assert r["image"]["toasts"][0]["message"].startswith("image → orrery-A")
    assert r["uri"]["value"] == "/Users/u/x.pdf" and r["uri"]["reads"] == 0
    assert r["text"]["prevented"] is False


def test_plain_linux_paste_is_unchanged():
    r = _run("return await paste(LINUX,{items:[IMAGE]});")
    assert r["reads"] == 1
    assert r["sent"] == [{"type": "input", "paneId": "%1", "data": "\x16"}]


def test_the_handler_is_the_one_on_the_composer():
    html = COCKPIT.read_text(encoding="utf-8")
    assert "promptInput.addEventListener('paste',handleComposerPaste);" in html


# --- shortcuts -----------------------------------------------------------------


def test_shortcuts_follow_the_host():
    r = _run("""
      const ev=(key,mods={})=>({key,metaKey:false,ctrlKey:false,altKey:false,shiftKey:false,...mods});
      const h=normalizeHostPlatform;
      return {
        macPalette:isPaletteShortcut(ev('k',{metaKey:true}),h(MAC)),
        macPaletteAlt:isPaletteShortcut(ev('k',{altKey:true}),h(MAC)),
        macJump:sessionJumpNumber(ev('3',{metaKey:true}),h(MAC)),
        linuxPalette:isPaletteShortcut(ev('k',{metaKey:true}),h(LINUX)),
        wslPalette:isPaletteShortcut(ev('k',{altKey:true}),h(WSL)),
        wslPaletteUpper:isPaletteShortcut(ev('K',{altKey:true}),h(WSL)),
        wslPaletteCtrl:isPaletteShortcut(ev('k',{ctrlKey:true}),h(WSL)),
        wslPaletteMeta:isPaletteShortcut(ev('k',{metaKey:true}),h(WSL)),
        wslAltGr:isPaletteShortcut(ev('k',{altKey:true,ctrlKey:true}),h(WSL)),
        wslJump:sessionJumpNumber(ev('3',{altKey:true}),h(WSL)),
        wslJumpCtrl:sessionJumpNumber(ev('3',{ctrlKey:true}),h(WSL)),
        wslJumpZero:sessionJumpNumber(ev('0',{altKey:true}),h(WSL)),
        wslYield:terminalYieldsHostShortcut(ev('2',{altKey:true}),h(WSL)),
        wslYieldOther:terminalYieldsHostShortcut(ev('b',{altKey:true}),h(WSL)),
        macYield:terminalYieldsHostShortcut(ev('k',{metaKey:true}),h(MAC)),
        before:normalizeHostPlatform(null).host,
      };""")
    assert r == {
        "macPalette": True, "macPaletteAlt": False, "macJump": 3,
        "linuxPalette": True,
        "wslPalette": True, "wslPaletteUpper": True, "wslPaletteCtrl": False,
        "wslPaletteMeta": False, "wslAltGr": False,
        "wslJump": 3, "wslJumpCtrl": 0, "wslJumpZero": 0,
        "wslYield": True, "wslYieldOther": False, "macYield": False,
        "before": "unknown",
    }


def test_labels_follow_the_host():
    r = _run("""const h=normalizeHostPlatform;return {
      mac:[paletteShortcutLabel(h(MAC)),splitClickLabel(h(MAC)),terminalActionText(h(MAC)),terminalSpawnLabel(h(MAC))],
      linux:[paletteShortcutLabel(h(LINUX)),terminalActionText(h(LINUX)),terminalSpawnLabel(h(LINUX))],
      wsl:[paletteShortcutLabel(h(WSL)),splitClickLabel(h(WSL)),terminalActionText(h(WSL)),terminalSpawnLabel(h(WSL))],
    };""")
    assert r["mac"] == ["⌘K", "⌘+click", "GHOSTTY", "Open a Ghostty window"]
    assert r["linux"] == ["⌘K", "GHOSTTY", "Open a Ghostty window"]
    assert r["wsl"] == ["Alt+K", "Ctrl+click", "WIN TERMINAL", "Open a Windows Terminal tab"]


def test_the_shortcuts_are_wired_to_the_page_and_the_terminal():
    html = COCKPIT.read_text(encoding="utf-8")
    assert "if(isPaletteShortcut(event,hostPlatform)){" in html
    assert "sessionJumpNumber(event,hostPlatform)){" in html
    assert "if(terminalYieldsHostShortcut(event,hostPlatform))return false;" in html
    assert "fetch('/telemetry/platform'" in html
    # the old Cmd-only checks are gone, so nothing bypasses the host
    assert "event.metaKey&&!event.altKey&&!event.shiftKey&&key==='k'" not in html
    assert "/^[1-9]$/.test(event.key)){" not in html


def test_fresh_output_gap_uses_actual_caller_to_stop_only_affected_session_and_reattach():
    html = COCKPIT.read_text(encoding="utf-8")
    names = ('setGroupState', 'forgetSession', 'freshOutputIncomplete',
             'requestAttach', 'resetSession', 'handle', 'connect')
    functions = []
    for name in names:
        match = re.search(r'function '+name+r'\([^\n]*\)\{.*?\n\}', html, re.DOTALL)
        assert match, name
        functions.append(match.group(0))
    script = r'''
const groups=new Map(),sessionGroups=groups,panes=new Map(),sent=[],toasts=[],links=[];
const attachedSessions=new Set(),requestedSessions=new Set(),availableSessions=new Map([['Alpha',{}],['Beta',{}]]);
const manualDetached=new Set(),paneWindows=new Set(),selectedPaneBySession=new Map();
let pendingJump=null,activeId=null,splitVisible=false,focusedSplitSession=null,paneWindowSelection=null;
function ensureSessionGroup(session){
  if(!groups.has(session))groups.set(session,{incarnation:null,attachGeneration:null,
    el:{classList:{toggle(){}}},state:{textContent:''},empty:{textContent:'',style:{}}});
  return groups.get(session);
}
function closeSessionPanes(session){for(const [key,p] of panes)if(p.session===session)panes.delete(key);}
function removeSplitSessionState(){} function removeSessionGroup(s){groups.delete(s);}
function renderStage(){} function refreshHeaderStats(){} function refreshSessionGroup(){}
function showToast(message,isError){toasts.push({message,isError});}
function paneSessionAllowed(){return true;} function occupiedSessions(){return new Set([...attachedSessions,...requestedSessions]);}
function activeSession(){return null;} function send(payload){sent.push(payload);return true;}
function createPane(session,meta){panes.set(meta.paneId,{session});}
function focusSession(){} function focusSplitSession(){} function applyAutoClaims(){}
const MAX_ATTACHED_SESSIONS=12;
const events={};let socket=null;const wsUrl='private';
class WebSocket{addEventListener(name,fn){events[name]=fn;}}
function setLink(...args){links.push(args);} function scheduleFit(){} function scheduleReconnect(){}
function reset(session,generation){handle({type:'reset',session,incarnation:'i',attachGeneration:generation,panes:[{paneId:session+'-pane'}]});}
function error(generation){handle({type:'error',session:'Alpha',incarnation:'i',attachGeneration:generation,
  code:'FRESH_OUTPUT_INCOMPLETE',message:'Output incomplete'});}
reset('Alpha','old');reset('Beta','other');error('old');
if(attachedSessions.has('Alpha')||!attachedSessions.has('Beta')||panes.has('Alpha-pane')||!panes.has('Beta-pane'))throw Error('sink isolation');
if(groups.get('Alpha').state.textContent!=='error'||!groups.get('Alpha').empty.textContent.includes('missing')||!toasts[0].isError)throw Error('gap invisible');
if(!requestAttach('Alpha'))throw Error('reattach blocked');
reset('Alpha','new');error('old');
if(!attachedSessions.has('Alpha')||groups.get('Alpha').state.textContent!=='live'||toasts.length!==1)throw Error('old error applied');
// Ordinary backend errors retain their existing behavior.
handle({type:'error',session:'Beta',message:'legacy error'});
if(!attachedSessions.has('Beta'))throw Error('legacy error changed');
// If the server cannot send the error, it closes that WebSocket. Exercise
// the real close callback: the surviving UI must not continue showing live.
connect();events.close();
if(attachedSessions.size||requestedSessions.size||groups.get('Alpha').state.textContent!=='closed'||links.at(-1)[1]!=='disconnected')throw Error('transport failure remained live');
console.log(JSON.stringify({gapVisible:true,reattach:true,oldErrorIgnored:true,otherSessionPreserved:true,transportFailureClosed:true}));
'''
    done = subprocess.run(['/usr/local/bin/node', '-e', '\n'.join(functions)+'\n'+script],
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert all(json.loads(done.stdout).values())


def startup_settings(tmp_path):
    import shlex,shutil,sys
    t=Path(os.environ['ORRERY_TEST_TELEMETRY_ROOT'])
    home=tmp_path/'private-home';root=home/'telemetry';(root/'hooks').mkdir(parents=True)
    shutil.copy2(t/'hooks/project-context.sh',root/'hooks/project-context.sh')
    context=tmp_path/'prepared-context.json';context.write_text('{}');context.chmod(0o600)
    values=dict(AGENTSTACK_RUNTIME_MODE='fresh',AGENTSTACK_HOME=str(root),
        AGENTSTACK_FRESH_CLIENT_CONTEXT=str(context),AGENTSTACK_PYTHON=sys.executable,
        ORRERY_FRESH_MAIL_INSTANCE_ID='a'*32,AGENTSTACK_PORT='19877')
    path=root/'env.sh';path.write_text('\n'.join('export '+k+'='+shlex.quote(v) for k,v in values.items())+'\n');path.chmod(0o600)
    return home,root,path,values


def test_normal_startup_loader_saved_custom_root_is_literal_finite_and_refuses_conflicts(tmp_path,monkeypatch):
    import pytest,runtime_target as rt
    home,root,path,values=startup_settings(tmp_path)
    marker=tmp_path/'should-not-execute'
    with path.open('a') as stream:stream.write('touch '+str(marker)+'\n')
    env={'HOME':str(home),'PATH':os.environ['PATH']}
    loaded=rt.startup_environment(environ=env,config={'telemetry_home':str(root)})
    assert loaded['AGENTSTACK_FRESH_CLIENT_CONTEXT']==values['AGENTSTACK_FRESH_CLIENT_CONTEXT']
    assert loaded['AGENTSTACK_PYTHON']==values['AGENTSTACK_PYTHON']
    assert loaded['ORRERY_DASHBOARD_URL']=='http://127.0.0.1:19877' and not marker.exists()
    assert not {'registration_token','AGENTSTACK_MAIL_DB','AGENTSTACK_FRESH_SERVER_CONFIG'} & set(loaded)
    for changed in ({'AGENTSTACK_CLIENT_CONFIG':'old'}, {'AGENTSTACK_GLOBAL_SERVER_CONFIG':'old'},
                    {'AGENTSTACK_FRESH_CLIENT_CONTEXT':''}, {'ORRERY_FRESH_MAIL_INSTANCE_ID':'bad'}):
        with pytest.raises(rt.TargetRefused):rt.startup_environment(environ=env|changed,config={'telemetry_home':str(root)})
    class Host:
        def __init__(self,*args,**kwargs):
            assert kwargs['environ']['AGENTSTACK_HOME']==str(root)
            self.instance='a'*32;self.host_pin={'context_digest':'d'*64,'epoch':'e'*32}
        def call(self,args):assert args=={'operation':'catalog'}
    monkeypatch.setattr(rt,'FreshTargetBoundary',Host)
    plan=rt.startup_projection(environ=env,config={'telemetry_home':str(root)})
    assert plan['identity']==dict(runtime_mode='fresh',mail_instance_id='a'*32,context_digest='d'*64,host_epoch='e'*32)
    path.chmod(0o666)
    with pytest.raises(rt.TargetRefused,match='SETTINGS_UNAVAILABLE'):rt.startup_environment(environ=env,config={'telemetry_home':str(root)})
    assert rt.startup_environment(environ={'HOME':str(tmp_path/'empty')})=={'AGENTSTACK_RUNTIME_MODE':'legacy'}


def test_normal_startup_health_exposes_exact_host_pin_without_context_or_credentials(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import orrery_backend as ob,runtime_target as rt
    async def scenario():
        target=object.__new__(rt.FreshTargetBoundary);target.instance='a'*32
        target.wrapper=Path(os.environ['ORRERY_TEST_TELEMETRY_ROOT'])/'bin/agentstack-runtime-client'
        target.host_pin={'context_digest':'d'*64,'epoch':'e'*32}
        class Reply:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        class Http:
            def get(self,*args,**kwargs):return Reply()
        app=ob.create_app(target)
        app[ob.HTTP_SESSION_KEY]=Http()
        response=await ob.serve_health(SimpleNamespace(app=app))
        data=json.loads(response.body)
        assert data['runtime']==dict(runtime_mode='fresh',mail_instance_id='a'*32,context_digest='d'*64,host_epoch='e'*32)
        assert not {'registration_token','context_path','binding_path'} & set(data['runtime'])
    asyncio.run(scenario())
