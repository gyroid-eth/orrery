"""Exercise the cockpit's host-specific labels, shortcuts and clipboard routes.

The Node harness runs the current paste listener and attachment module with
browser File objects and fixtures for the Mac app and local HTTP clipboard.
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

HOST_BLOCK = r"/\* ── host: Mac, WSL or plain Linux.*?(?=/\* COCKPIT_PURE_LOGIC_END \*/)"
PASTE_BLOCK = (
    r"^async function readClipboardAttachments\(\).*?"
    r"^promptInput\.addEventListener\('paste',handleComposerPaste\);"
)

HOSTS = """
const MAC={host:'mac',terminal:{kind:'ghostty',label:'Ghostty',available:true},file_paste:true};
const WSL={host:'wsl',terminal:{kind:'wt',label:'Windows Terminal',available:true},file_paste:false};
const WSL_READER={...WSL,file_paste:true};
const LINUX={host:'linux',terminal:{kind:'ghostty',label:'Ghostty',available:true},file_paste:false};
"""

PASTE_HARNESS = r"""
const {File}=require('node:buffer');
const calls=[],toasts=[],sent=[],listeners=new Map();
let hostPlatform,promptBusy=false,hostReloads=0;
let snapshot;
const promptInput={
  value:'',
  addEventListener(name,handler){listeners.set(name,handler);}
};
function showToast(message,isError=false){toasts.push({message,isError});}
function send(packet){sent.push(packet);return true;}
function loadHostPlatform(){hostReloads++;}

function node(){
  return {
    addEventListener(){},setAttribute(){},focus(){},append(){},replaceChildren(){},
    classList:{add(){}},
  };
}
const document={createElement:node,createElementNS:node};
const promptFiles=OrreryPromptAttachments.mount({
  host:node(),clip:node(),picker:node(),list:node(),
  onChange(){},onError:message=>showToast(message,true),mayEdit:()=>!promptBusy,
});
const PNG=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZioAAAAASUVORK5CYII=','base64');
const IMAGE={name:'Clipboard image.png',type:'image/png',data:PNG.toString('base64')};
const NOTE={name:'資料 with space.txt',type:'text/plain',data:Buffer.from('Fixture note').toString('base64')};
const fileOf=entry=>new File([Buffer.from(entry.data,'base64')],entry.name,{type:entry.type});
globalThis.fetch=async (url,options)=>{
  calls.push({via:'http',url,method:options.method,body:options.body,type:options.headers['Content-Type']});
  return {ok:snapshot!==null,json:async()=>snapshot};
};
async function paste(host,{files=[],items=[],types=[],plain='',uris='',app,busy=false,answer={attachments:[]}}={}){
  promptFiles.clear();
  calls.length=0;toasts.length=0;sent.length=0;hostReloads=0;
  hostPlatform=normalizeHostPlatform(host);
  snapshot=answer;
  promptBusy=busy;
  promptInput.value='Keep this draft';
  window.__TAURI__=app===undefined?undefined:{core:{invoke:async (command,args)=>{
    calls.push({via:'app',command,args});
    if(app===false)throw Error('app failure');
    return app;
  }}};
  const event={
    prevented:false,preventDefault(){this.prevented=true;},
    clipboardData:{files,items,types,getData:type=>type==='text/plain'?plain:type==='text/uri-list'?uris:''},
  };
  listeners.get('paste')(event);
  await new Promise(resolve=>setImmediate(resolve));
  const attachments=await Promise.all(promptFiles.entries.map(async entry=>({
    name:entry.file.name,kind:entry.kind,preview:!!entry.preview,
    data:Buffer.from(await entry.file.arrayBuffer()).toString('base64'),
  })));
  return {prevented:event.prevented,value:promptInput.value,hostReloads,attachments,
    calls:[...calls],sent:[...sent],toasts:[...toasts]};
}
"""

HTTP = {"via": "http", "url": "/telemetry/clipboard/attachments", "method": "POST",
        "body": "{}", "type": "application/json"}
APP = {"via": "app", "command": "clipboard_file_paths", "args": {"attachments": True}}


def _run(body: str, *, paste=False):
    html = COCKPIT.read_text(encoding="utf-8")
    host = re.search(HOST_BLOCK, html, re.DOTALL)
    assert host, "missing cockpit host logic"
    parts = [host.group(0), HOSTS]
    if paste:
        listener = re.search(PASTE_BLOCK, html, re.DOTALL | re.MULTILINE)
        assert listener, "missing composer clipboard listener"
        assets = (SOURCES / "prompt_attachments.js").read_text(encoding="utf-8")
        parts.extend(["const window=globalThis;", assets, PASTE_HARNESS, listener.group(0)])
    parts.extend([f"async function run(){{\n{body}\n}}",
                  "run().then(result=>console.log(JSON.stringify(result))).catch(error=>{"
                  "console.error(error);process.exitCode=1;});"])
    done = subprocess.run(["node", "-e", "\n".join(parts)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _paste(body):
    return _run(body, paste=True)


def assert_staged(out, names):
    assert out["prevented"]
    assert out["value"] == "Keep this draft"
    assert out["sent"] == []
    assert [(entry["name"], entry["kind"], entry["preview"]) for entry in out["attachments"]] == names


# --- paste ---------------------------------------------------------------------


def test_browser_files_stage_on_mac_wsl_and_linux_even_without_a_host_reader():
    result = _paste("""
      const outputs=[];
      for(const host of [MAC,WSL,LINUX,null])outputs.push(await paste(host,{
        files:[fileOf(IMAGE),fileOf(NOTE)],plain:'A text representation of the files',
      }));
      return outputs;
    """)
    for out in result:
        assert_staged(out, [("Clipboard image.png", "image", True), ("資料 with space.txt", "file", False)])
        assert out["attachments"][0]["data"].startswith("iVBORw0KGgo")
        assert out["attachments"][1]["data"] == "Rml4dHVyZSBub3Rl"
        assert out["calls"] == out["toasts"] == []
        assert out["hostReloads"] == 0


def test_linux_reads_an_image_from_clipboard_items_if_file_list_is_empty():
    result = _paste("""return paste(LINUX,{items:[
      {kind:'string'}, {kind:'file',getAsFile:()=>new File([PNG],'capture',{type:'image/png'})},
    ]});""")
    assert_staged(result, [("capture.png", "image", True)])
    assert result["calls"] == result["toasts"] == []


def test_wsl_without_reader_keeps_the_draft_and_reports_why_native_paste_is_unavailable():
    result = _paste("""return paste(WSL,{types:['Files'],uris:'file:///C:/Users/u/Note%20one.txt'});""")
    assert_staged(result, [])
    assert result["calls"] == []
    [error] = result["toasts"]
    assert error["isError"] and "Windows clipboard" in error["message"]


def test_unknown_host_refreshes_platform_before_trying_native_paste():
    result = _paste("""return paste(null,{types:['Files']});""")
    assert_staged(result, [])
    assert result["calls"] == []
    assert result["hostReloads"] == 1
    assert [toast["isError"] for toast in result["toasts"]] == [True]


def test_wsl_reader_stages_explorer_bytes_and_screenshots_without_inserting_windows_paths():
    result = _paste("""return {
      explorer:await paste(WSL_READER,{
        uris:'file:///C:/Users/u/Note%20one.txt',plain:'C:/Users/u/Note one.txt',
        answer:{attachments:[NOTE]},
      }),
      screenshot:await paste(WSL_READER,{types:['Files'],answer:{attachments:[IMAGE]}}),
    };""")
    assert_staged(result["explorer"], [("資料 with space.txt", "file", False)])
    assert_staged(result["screenshot"], [("Clipboard image.png", "image", True)])
    for out in result.values():
        assert out["calls"] == [HTTP]
        assert out["toasts"] == []


def test_wsl_keeps_successful_files_when_the_native_reader_skips_one():
    result = _paste("""return paste(WSL_READER,{answer:{attachments:[NOTE],skipped:1}});""")
    assert_staged(result, [("資料 with space.txt", "file", False)])
    assert result["calls"] == [HTTP]
    assert result["toasts"] == [{"message": "1 clipboard item could not be attached.", "isError": True}]


def test_native_reader_failures_do_not_send_to_the_terminal():
    result = _paste("""return [
      await paste(WSL_READER,{answer:{attachments:[]}}),
      await paste(WSL_READER,{answer:{error:'clipboard_no_session'}}),
      await paste(LINUX,{answer:{error:'clipboard_unsupported'}}),
      await paste(MAC,{answer:null}),
    ];""")
    for out in result:
        assert_staged(out, [])
        assert out["calls"] == [HTTP]
        assert [toast["isError"] for toast in out["toasts"]] == [True]


def test_mac_uses_the_app_snapshot_and_falls_back_to_http_after_old_app_or_error():
    result = _paste("""return {
      app:await paste(MAC,{app:{attachments:[NOTE]}}),
      emptyApp:await paste(MAC,{app:{attachments:[]},answer:{attachments:[NOTE]}}),
      oldApp:await paste(MAC,{app:['/old/path'],answer:{attachments:[IMAGE]}}),
      failedApp:await paste(MAC,{app:false,answer:{attachments:[IMAGE]}}),
      browser:await paste(MAC,{answer:{attachments:[IMAGE]}}),
    };""")
    assert_staged(result["app"], [("資料 with space.txt", "file", False)])
    assert_staged(result["emptyApp"], [])
    assert result["app"]["calls"] == result["emptyApp"]["calls"] == [APP]
    for route in ("oldApp", "failedApp", "browser"):
        assert_staged(result[route], [("Clipboard image.png", "image", True)])
        assert result[route]["calls"] == ([HTTP] if route == "browser" else [APP, HTTP])


def test_text_paste_is_left_to_the_textarea_on_every_host():
    result = _paste("""return [
      await paste(MAC,{plain:'hello'}),
      await paste(WSL,{plain:'hello'}),
      await paste(WSL_READER,{plain:'hello'}),
      await paste(LINUX,{plain:'hello'}),
      await paste(null,{plain:'hello'}),
    ];""")
    for out in result:
        assert not out["prevented"]
        assert out["calls"] == out["toasts"] == out["attachments"] == out["sent"] == []


def test_new_clipboard_attachments_are_ignored_while_sending():
    result = _paste("""return [
      await paste(MAC,{files:[fileOf(IMAGE)],busy:true}),
      await paste(WSL_READER,{answer:{attachments:[IMAGE]},busy:true}),
    ];""")
    for out in result:
        assert_staged(out, [])
        assert out["calls"] == out["toasts"] == []


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
      mac:[paletteShortcutLabel(h(MAC)),splitClickLabel(h(MAC)),terminalActionText(h(MAC))],
      linux:[paletteShortcutLabel(h(LINUX)),terminalActionText(h(LINUX))],
      wsl:[paletteShortcutLabel(h(WSL)),splitClickLabel(h(WSL)),terminalActionText(h(WSL))],
    };""")
    assert r["mac"] == ["⌘K", "⌘+click", "GHOSTTY"]
    assert r["linux"] == ["⌘K", "GHOSTTY"]
    assert r["wsl"] == ["Alt+K", "Ctrl+click", "WIN TERMINAL"]


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
    # The extracted WS functions share these optional modules with the page.
    for module in ('readerApproval', 'readerActivity'):
        declaration = re.search(r'^let '+module+r'=null;$', html, re.MULTILINE)
        assert declaration, module
        functions.append(declaration.group(0))
    script = r'''
const groups=new Map(),sessionGroups=groups,panes=new Map(),sent=[],toasts=[],links=[];
const attachedSessions=new Set(),requestedSessions=new Set(),availableSessions=new Map([['Alpha',{}],['Beta',{}]]);
const manualDetached=new Set(),paneWindows=new Set(),selectedPaneBySession=new Map();
const permissionRestarts=new Map();
const pendingAgentExits=new Map();
let pendingJump=null,activeId=null,splitVisible=false,focusedSplitSession=null,paneWindowSelection=null;
function ensureSessionGroup(session){
  if(!groups.has(session))groups.set(session,{incarnation:null,attachGeneration:null,
    el:{classList:{toggle(){}}},state:{textContent:''},empty:{textContent:'',style:{}}});
  return groups.get(session);
}
function closeSessionPanes(session){for(const [key,p] of panes)if(p.session===session)panes.delete(key);}
function paintSessionAction(group){group.state.textContent={connecting:'…',live:'live',error:'error',closed:'closed'}[group.connectionState]||'';}
function removeSplitSessionState(){} function removeSessionGroup(s){groups.delete(s);}
function renderStage(){} function refreshHeaderStats(){} function refreshSessionGroup(){}
function showToast(message,isError){toasts.push({message,isError});}
function paneSessionAllowed(){return true;} function occupiedSessions(){return new Set([...attachedSessions,...requestedSessions]);}
function activeSession(){return null;} function send(payload){sent.push(payload);return true;}
function createPane(session,meta){panes.set(meta.paneId,{session});}
function focusSession(){} function focusSplitSession(){} function applyAutoClaims(){}
const MAX_ATTACHED_SESSIONS=12;
const events={};let socket=null;const wsUrl='private';
const composerAttaching=new Map();
const document={dispatchEvent(){}};
class CustomEvent{constructor(type,options){this.type=type;this.detail=options.detail;}}
function cancelComposerAcks(){}
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
handle({type:'approval',state:'ready'}); // Reader has not been initialized yet.
connect();events.close();
if(attachedSessions.size||requestedSessions.size||groups.get('Alpha').state.textContent!=='closed'||links.at(-1)[1]!=='disconnected')throw Error('transport failure remained live');
const approvalEvents=[];
readerApproval={receive:msg=>approvalEvents.push(msg.state),disconnected:()=>approvalEvents.push('disconnected')};
handle({type:'approval',state:'ready'});connect();events.close();
if(JSON.stringify(approvalEvents)!==JSON.stringify(['ready','disconnected']))throw Error('approval lifecycle not forwarded');
console.log(JSON.stringify({gapVisible:true,reattach:true,oldErrorIgnored:true,otherSessionPreserved:true,transportFailureClosed:true,approvalLifecycle:true}));
'''
    done = subprocess.run(['node', '-e', '\n'.join(functions)+'\n'+script],
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
