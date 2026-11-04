"""Review regressions against the real cockpit and an explicitly supplied CDP.

No browser is launched; no live dashboard, provider, terminal or credentials are
used. Run serially with ORRERY_CDP_URL=http://127.0.0.1:9250.
"""
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(os.environ.get("ORRERY_CONVERSATION_TEST_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(ROOT))
from tools.theme_axis_browser_test import _WebSocket

CDP = os.environ.get("ORRERY_CDP_URL")


@pytest.fixture
def cockpit(request):
    if not CDP:
        pytest.skip("set ORRERY_CDP_URL to an existing private/shared CDP browser")
    requests = []
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / "bridge"), **kwargs)
        def log_message(self, *_):
            pass
        def do_GET(self):
            path = urlsplit(self.path).path
            requests.append(path)
            if path.startswith(("/telemetry/", "/api/")):
                data = {"agents": [], "prefs": {}}
                raw = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            else:
                super().do_GET()
        def do_PUT(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"prefs":{}}')
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    tab = json.load(urllib.request.urlopen(urllib.request.Request(CDP + "/json/new?about:blank", method="PUT")))
    client = _WebSocket(tab["webSocketDebuggerUrl"])
    client.call("Page.enable")
    client.call("Runtime.enable")
    client.call("Network.enable")
    client.call("Network.setCacheDisabled", cacheDisabled=True)
    mobile=getattr(request,'param',False)
    client.call("Emulation.setDeviceMetricsOverride", width=390 if mobile else 1600, height=844 if mobile else 1000, deviceScaleFactor=1, mobile=mobile)
    client.call("Page.addScriptToEvaluateOnNewDocument", source="localStorage.clear();localStorage.setItem('oc-first-flight-v1',JSON.stringify({seen:true,open:false}));")
    def js(expression):
        result = client.call("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        assert not result.get("exceptionDetails"), result.get("exceptionDetails")
        return result.get("result", {}).get("value")
    def wait(expression):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if js(expression):
                return
            time.sleep(.03)
        raise AssertionError(expression)
    try:
        client.call("Page.navigate", url=f"http://127.0.0.1:{server.server_port}/cockpit.html")
        wait("typeof conversationView!=='undefined'&&typeof createPane==='function'")
        def enable(*, claimed=False, mode="cursor", count=80, text_size=120):
            js("conversationEnabled.checked=true;conversationEnabled.dispatchEvent(new Event('change'))")
            wait("typeof OrreryConversationSource!=='undefined'&&typeof OrreryConversation!=='undefined'")
            js("""window.packets=[];window.send=p=>{packets.push(p);return true};
              currentAgents=[{name:'ReviewFixture',program:'codex',provider:'openai',history_binding:'bound',transcript_path:'/fixture/one.jsonl'}];
              createPane('ReviewFixture',{paneId:'%901',windowId:'@901',width:80,height:20,alternateOn:true,mouseTracking:false});
              setActive('%901');window.pageNumber=0;
            """)
            if claimed:
                js("claimedSessions.add('ReviewFixture')")
            js(f"""OrreryConversationSource.Source.prototype.read=async()=>{{
              const n=++pageNumber;
              return {{ok:true,agent:'ReviewFixture',mode:{json.dumps(mode)},events:Array.from({{length:{count}}},(_,i)=>({{
                id:String(n*1000+i),kind:'text',role:'assistant',text:'x'.repeat({text_size}),
                cursor_before:'file:'+String(n*1000+i),cursor_after:'file:'+String(n*1000+i+1)
              }})),before:'file:'+String(n*1000),after:'file:'+String(n*1000+{count}),has_older:true,has_newer:false}};
            }};""")
            time.sleep(.12)
            js("packets.length=0;conversationView.open()")
            wait("document.querySelectorAll('.conversation-event').length>0")
        yield js, wait, client, requests, enable
    finally:
        urllib.request.urlopen(CDP + "/json/close/" + tab["id"]).close()
        server.shutdown()
        server.server_close()


def test_disabled_does_not_fetch_conversation_assets(cockpit):
    js, wait, client, requests, enable = cockpit
    assert not [path for path in requests if path.startswith("/conversation_")]


def test_reader_keys_and_automatic_fit_do_not_focus_or_type_into_terminal(cockpit):
    js, wait, client, requests, enable = cockpit
    enable()
    js("document.querySelector('.conversation-scroll').focus();packets.length=0")
    for key, code, modifiers in [("ArrowDown", 40, 4), ("ArrowUp", 38, 0), ("PageDown", 34, 0)]:
        client.call("Input.dispatchKeyEvent", type="keyDown", key=key, windowsVirtualKeyCode=code, modifiers=modifiers)
        client.call("Input.dispatchKeyEvent", type="keyUp", key=key, windowsVirtualKeyCode=code, modifiers=0)
    js("focusTerminalPreservingScroll(panes.get('%901'));queueStageFit('%901')")
    time.sleep(.1)
    assert js("Boolean(document.activeElement.closest('.conversation-panel'))")
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


def test_claimed_grid_is_not_resized_by_open_close_or_disable(cockpit):
    js, wait, client, requests, enable = cockpit
    enable(claimed=True)
    time.sleep(.1)
    assert js("packets.filter(p=>p.type==='resize')") == []
    js("packets.length=0;conversationView.close()")
    time.sleep(.1)
    assert js("packets.filter(p=>p.type==='resize')") == []
    js("conversationView.open()")
    wait("document.querySelectorAll('.conversation-event').length>0")
    js("packets.length=0;conversationEnabled.checked=false;conversationEnabled.dispatchEvent(new Event('change'))")
    time.sleep(.1)
    assert js("packets.filter(p=>p.type==='resize')") == []


def test_same_name_provider_and_binding_changes_clear_previous_records(cockpit):
    js, wait, client, requests, enable = cockpit
    enable()
    js("OrreryConversationSource.Source.prototype.read=()=>new Promise(()=>{});currentAgents[0].transcript_path='/fixture/two.jsonl';document.dispatchEvent(new Event('oc:agents'))")
    assert js("document.querySelectorAll('.conversation-event').length") == 0
    js("currentAgents[0].program='claude-code';document.dispatchEvent(new Event('oc:agents'))")
    assert js("document.querySelectorAll('.conversation-event').length") == 0
    assert js("document.querySelector('.conversation-toolbar .conversation-status').textContent.includes('next phase')")


def test_fresh_is_a_bounded_snapshot_and_legacy_retention_has_a_byte_cap(cockpit):
    js, wait, client, requests, enable = cockpit
    enable(mode="fresh_tail", count=200)
    for _ in range(5):
        js("conversationView.refresh()")
        time.sleep(.03)
    assert js("document.querySelectorAll('.conversation-event').length") <= 200
    js("conversationView.close()")
    js("""OrreryConversationSource.Source.prototype.read=async()=>{
      const n=++pageNumber;return {ok:true,agent:'ReviewFixture',mode:'cursor',
      events:Array.from({length:80},(_,i)=>({id:String(n*1000+i),kind:'text',role:'assistant',text:'x'.repeat(40000),
        cursor_before:'file:'+String(n*1000+i),cursor_after:'file:'+String(n*1000+i+1)})),
      before:'file:'+String(n*1000),after:'file:'+String(n*1000+80),has_older:true,has_newer:false};};
      conversationView.open();""")
    wait("document.querySelectorAll('.conversation-event').length>0")
    for _ in range(4):
        js("document.querySelector('.conversation-scroll').scrollTop=1e9;conversationView.refresh()")
        time.sleep(.03)
    assert js("document.querySelectorAll('.conversation-event').length") <= 400
    assert js("[...document.querySelectorAll('.conversation-text')].reduce((n,e)=>n+new TextEncoder().encode(e.textContent).length,0)") <= 2*1024*1024


def test_legacy_limit_pauses_updates_while_reading_and_latest_reloads(cockpit):
    js, wait, client, requests, enable = cockpit
    enable(mode="cursor", count=200)
    js("document.querySelector('.conversation-scroll').scrollTop=1e9;conversationView.refresh()")
    wait("document.querySelectorAll('.conversation-event').length===400")
    js("document.querySelector('.conversation-scroll').scrollTop=110;conversationView.refresh()")
    wait("document.querySelector('.conversation-latest').textContent.includes('resume')")
    assert js("document.querySelectorAll('.conversation-event').length") == 400
    assert js("document.querySelector('.conversation-scroll').scrollTop") == 110
    js("document.querySelector('.conversation-latest').click()")
    wait("document.querySelectorAll('.conversation-event').length===200")
    assert not js("document.querySelector('.conversation-latest').textContent.includes('resume')")
def test_retry_after_history_change_resets_retention_accounting(cockpit):
 js,wait,client,requests,enable=cockpit
 enable(mode='cursor',count=80,text_size=40000)
 before=js("document.querySelectorAll('.conversation-event').length")
 js("""OrreryConversationSource.Source.prototype.read=async()=>{const e=new Error('changed');e.code='history_changed';throw e};conversationView.refresh();""")
 wait("document.querySelector('.conversation-retry').hidden===false")
 cleared=js("document.querySelectorAll('.conversation-event').length")
 js("""OrreryConversationSource.Source.prototype.read=async()=>({mode:'cursor',events:[{id:'retry',kind:'text',role:'assistant',text:'x'.repeat(40000),cursor_before:'file:0',cursor_after:'file:1'}],before:'file:0',after:'file:1',has_older:false});document.querySelector('.conversation-retry').click()""")
 time.sleep(.15)
 loaded=js("document.querySelectorAll('.conversation-event').length")
 print(json.dumps(dict(before_error=before,after_error=cleared,after_successful_retry=loaded,status=js("document.querySelector('.conversation-toolbar .conversation-status').textContent"))))
 assert loaded==1


def test_recorded_chips_open_inert_split_preview_without_resizing(cockpit):
    js,wait,client,requests,enable=cockpit
    enable(mode='cursor',count=2)
    js("""window.previewRequests=[];OrreryConversationSource.Source.prototype.reference=async(ref,options)=>{
      previewRequests.push({ref,reveal:!!options.reveal});return {ok:true,kind:'text',text:'<img src=https://example.test/never>\\ncurrent file'};};
      OrreryConversationSource.Source.prototype.read=async()=>({mode:'cursor',events:[{id:'artifacts',kind:'tool',role:'assistant',text:'functions.exec',
        references:[{id:'A'.repeat(32),label:'sample.txt',kind:'file'}],diff:'--- a/sample.txt\\n+++ b/sample.txt\\n@@\\n-old\\n+new',
        diff_status:'Recorded edit request · outcome unconfirmed'}],before:'file:0',after:'file:1',has_older:false});
      conversationView.close();conversationView.open();packets.length=0;""")
    wait("document.querySelector('.conversation-file')!==null")
    js("document.querySelector('.conversation-file').click()")
    wait("document.querySelector('.conversation-preview-text')!==null")
    assert js("document.querySelector('.screen').classList.contains('conversation-full')")
    assert js("document.querySelector('.conversation-preview-text').textContent.startsWith('<img')")
    assert js("document.querySelectorAll('.conversation-preview-content img').length")==0
    assert js("previewRequests")==[dict(ref='A'*32,reveal=False)]
    assert js("document.querySelectorAll('.conversation-diff-add').length")==1
    assert js("document.querySelector('.conversation-diff-summary').textContent").endswith('unconfirmed')
    js("document.querySelector('.conversation-reveal').click()")
    wait("previewRequests.length===2")
    assert js("previewRequests[1].reveal")
    js("document.querySelector('.conversation-preview-close').click();document.querySelector('.conversation-expand').click();conversationView.close()")
    assert not js("packets.some(p=>p.type==='resize'||p.type==='input')")


def test_preview_request_cancels_and_cannot_restore_after_close(cockpit):
    js,wait,client,requests,enable=cockpit
    enable(count=1)
    js("""window.previewSignal=null;window.finishPreview=null;
      OrreryConversationSource.Source.prototype.reference=(ref,options)=>{previewSignal=options.signal;return new Promise(resolve=>finishPreview=resolve)};
      OrreryConversationSource.Source.prototype.read=async()=>({events:[{id:'ref',kind:'tool',role:'assistant',text:'view_image',references:[{id:'B'.repeat(32),label:'plot.png',kind:'image'}]}],has_older:false});
      conversationView.close();conversationView.open();""")
    wait("document.querySelector('.conversation-file')!==null")
    js("document.querySelector('.conversation-file').click();conversationView.close()")
    assert js("previewSignal.aborted")
    js("finishPreview({kind:'text',text:'STALE_CONTENT'})")
    time.sleep(.1)
    assert js("document.querySelector('.conversation-preview').hidden")
    assert not js("document.querySelector('.conversation-panel').textContent.includes('STALE_CONTENT')")


@pytest.mark.parametrize('cockpit',[False,True],indirect=True,ids=['desktop','phone'])
def test_full_history_keeps_original_composer_usable_and_guarded(cockpit):
    js,wait,client,requests,enable=cockpit
    enable(claimed=True,count=6)
    js("document.querySelector('.conversation-expand').click();packets.length=0")
    hit=js("""(()=>{const input=document.getElementById('promptInput'),r=input.getBoundingClientRect();
      const panel=document.querySelector('.conversation-panel').getBoundingClientRect();
      return {visible:r.width>50&&r.left>=0&&r.right<=(visualViewport?.width||innerWidth)&&r.bottom<=(visualViewport?.height||innerHeight),
        hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===input,
        separate:panel.bottom<=document.querySelector('.promptbar').getBoundingClientRect().top+1,
        count:document.querySelectorAll('#promptInput').length};})()""")
    assert hit==dict(visible=True,hit=True,separate=True,count=1)
    # Reading/selection keys remain inert. Only the existing composer's
    # explicit send path may write to the selected pane.
    js("document.querySelector('.conversation-scroll').focus()")
    client.call('Input.dispatchKeyEvent',type='keyDown',key='Enter',windowsVirtualKeyCode=13)
    client.call('Input.dispatchKeyEvent',type='keyUp',key='Enter',windowsVirtualKeyCode=13)
    assert not js("packets.some(p=>p.type==='input')")
    js("promptInput.focus();promptInput.value='/logout';promptSend.click()")
    assert js("!sendGuard.hidden")
    assert not js("packets.some(p=>p.type==='input')")
    # IME confirmation must not submit; Shift+Enter remains a newline.
    js("sendGuardCancel.click();promptInput.value='fixture prompt';promptInput.focus();promptInput.dispatchEvent(new CompositionEvent('compositionstart'))")
    client.call('Input.dispatchKeyEvent',type='keyDown',key='Enter',windowsVirtualKeyCode=13)
    assert not js("packets.some(p=>p.type==='input')")
    js("promptInput.dispatchEvent(new CompositionEvent('compositionend'))")
    time.sleep(.1)
    client.call('Input.dispatchKeyEvent',type='keyDown',key='Enter',windowsVirtualKeyCode=13,modifiers=8)
    assert not js("packets.some(p=>p.type==='input')")
    js("promptInput.value='fixture prompt';promptSend.click()")
    wait("packets.filter(p=>p.type==='input').length===2")
    assert js("packets.filter(p=>p.type==='input')")==[
        dict(type='input',paneId='%901',data='\x1b[200~fixture prompt\x1b[201~'),
        dict(type='input',paneId='%901',data='\r')]
    assert js("document.querySelector('.screen').classList.contains('conversation-full')")
    assert not js("packets.some(p=>p.type==='resize')")
    assert js("promptInput.value")==''
    assert js("""(()=>{const r=document.querySelector('.conversation-panel').getBoundingClientRect(),v=visualViewport;
      return r.height>200&&r.top>=v.offsetTop&&r.bottom<=v.offsetTop+v.height-80;})()""")
    if js('visualViewport.width<600'):
        client.call('Emulation.setDeviceMetricsOverride',width=390,height=600,deviceScaleFactor=1,mobile=True)
        wait("document.querySelector('.screen').style.getPropertyValue('--conversation-viewport-height')==='600px'")
        assert js("""(()=>{const p=document.querySelector('.conversation-panel').getBoundingClientRect(),r=promptInput.getBoundingClientRect();
          return p.top>=0&&p.height>150&&r.bottom<=visualViewport.height;})()""")
