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
    assert js("document.querySelector('.conversation-subtitle').textContent.includes('ReviewFixture')")


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


@pytest.mark.parametrize('cockpit',[False,True],indirect=True,ids=['desktop','phone'])
def test_header_and_history_use_one_control_style_and_settings_keep_actions(cockpit):
    js,wait,client,requests,enable=cockpit
    enable(claimed=True,count=3)
    assert js("[...document.querySelectorAll('.scr-head button')].filter(e=>!e.hidden&&getComputedStyle(e).display!=='none').map(e=>e.id)")==['conversationToggle','panePopout']
    assert js("claimToggle.closest('#settingsPopover')!==null&&ghosttyAction.closest('#settingsPopover')!==null")
    assert not js("claimToggle.hidden||ghosttyAction.hidden")
    # Dialog remains a keyboard destination when a fit/poll occurs.
    js("paintClaimToggle(panes.get('%901').meta);document.querySelector('#settingsPopover').showPopover();claimToggle.focus();packets.length=0")
    assert js('document.activeElement===claimToggle')
    client.call('Input.dispatchKeyEvent',type='keyDown',key=' ',code='Space',text=' ',windowsVirtualKeyCode=32)
    client.call('Input.dispatchKeyEvent',type='keyUp',key=' ',code='Space',windowsVirtualKeyCode=32)
    wait("claimToggle.getAttribute('aria-pressed')==='false'")
    js("focusTerminalPreservingScroll(panes.get('%901'))")
    assert js("document.activeElement===claimToggle")
    assert js("packets.filter(p=>p.type==='release')")==[dict(type='release',paneId='%901')]
    assert not js("packets.some(p=>p.type==='input')")
    js("""window.settingsOpens=[];window.settingsFetch=window.fetch;
      window.fetch=async(url,options)=>url==='/telemetry/open-ghostty'?
        (settingsOpens.push({url,body:JSON.parse(options.body)}),{ok:true,json:async()=>({ok:true,already:true})}):settingsFetch(url,options);
      ghosttyAction.click();""")
    wait("settingsOpens.length===1&&!ghosttyAction.disabled")
    assert js('settingsOpens')==[dict(url='/telemetry/open-ghostty',body=dict(session='ReviewFixture'))]
    js('window.fetch=settingsFetch')
    js("document.querySelector('#settingsPopover').hidePopover()")
    for theme in ['dark','light']:
        js("document.documentElement.setAttribute('data-color-theme',"+json.dumps(theme)+")")
        styles=js("""(()=>{const selectors=['#conversationToggle','#panePopout','.conversation-expand','.conversation-close','.conversation-latest'];
          return selectors.map(selector=>{const s=getComputedStyle(document.querySelector(selector));return {
            padding:s.padding,borderRadius:s.borderRadius,font:s.font,height:s.height,borderWidth:s.borderWidth};});})()""")
        assert all(style==styles[0] for style in styles)
    js("document.querySelector('.conversation-expand').focus()")
    assert js("getComputedStyle(document.activeElement).outlineStyle!=='none'")


@pytest.mark.parametrize('cockpit',[False,True],indirect=True,ids=['desktop','phone'])
def test_pane_status_is_noninteractive_text_separate_from_buttons(cockpit):
    js,wait,client,requests,enable=cockpit
    enable(count=2)
    state=js("""(()=>{const e=document.getElementById('scrBadge'),s=getComputedStyle(e),name=document.getElementById('scrName');return {
      role:e.getAttribute('role'),atomic:e.getAttribute('aria-atomic'),buttonClass:e.classList.contains('cockpit-control'),
      border:s.borderTopWidth,background:s.backgroundColor,cursor:s.cursor,tabIndex:e.tabIndex,
      leftOfAction:e.getBoundingClientRect().right<document.getElementById('conversationToggle').getBoundingClientRect().left,
      nextToName:name.nextElementSibling===e};})()""")
    assert state==dict(role='status',atomic='true',buttonClass=False,border='0px',background='rgba(0, 0, 0, 0)',cursor='default',tabIndex=-1,leftOfAction=True,nextToName=True)
    before=js("getComputedStyle(scrBadge).cssText+getComputedStyle(scrBadge).color+getComputedStyle(scrBadge).backgroundColor+getComputedStyle(scrBadge).borderTopWidth")
    rect=js("(()=>{const r=scrBadge.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
    client.call('Input.dispatchMouseEvent',type='mouseMoved',**rect)
    assert js("getComputedStyle(scrBadge).cssText+getComputedStyle(scrBadge).color+getComputedStyle(scrBadge).backgroundColor+getComputedStyle(scrBadge).borderTopWidth")==before
    js("document.querySelector('.conversation-scroll').focus();scrBadge.focus()")
    assert not js('document.activeElement===scrBadge')


def test_provider_labels_snapshot_rewrite_and_receipt_changes_clear(cockpit):
    js,wait,client,requests,enable=cockpit
    enable(mode='snapshot',count=1)
    js("""OrreryConversationSource.Source.prototype.read=async()=>({ok:true,agent:'ReviewFixture',provider:'hermes',mode:'snapshot',events:[{id:'same',kind:'text',role:'assistant',text:'first'}],after:'snapshot',notice:'Active segment'});conversationView.refresh()""")
    wait("document.querySelector('.conversation-text').textContent==='first'")
    assert js("document.querySelector('.conversation-role').textContent")== 'Hermes'
    js("""OrreryConversationSource.Source.prototype.read=async()=>({ok:true,agent:'ReviewFixture',provider:'hermes',mode:'snapshot',events:[{id:'same',kind:'text',role:'assistant',text:'rewritten'}],after:'snapshot'});conversationView.refresh()""")
    wait("document.querySelector('.conversation-text').textContent==='rewritten'")
    js("OrreryConversationSource.Source.prototype.read=()=>new Promise(()=>{});currentAgents[0].history_session_id='changed';document.dispatchEvent(new Event('oc:agents'))")
    assert js("document.querySelectorAll('.conversation-event').length")==0
    for program,label in [('claude-code','Claude'),('dsh','dsh')]:
        js("OrreryConversationSource.Source.prototype.read=async()=>({events:[{id:'x',kind:'text',role:'assistant',text:'visible'}]});currentAgents[0].program="+json.dumps(program)+";document.dispatchEvent(new Event('oc:agents'))")
        wait("document.querySelector('.conversation-event')!==null")
        assert js("document.querySelector('.conversation-role').textContent")==label
        js("OrreryConversationSource.Source.prototype.read=()=>new Promise(()=>{});currentAgents[0].history_receipt_ts=String(Date.now());document.dispatchEvent(new Event('oc:agents'))")
        assert js("document.querySelectorAll('.conversation-event').length")==0


def test_stale_removes_previous_body_and_explains_previous_conversation(cockpit):
    js,wait,client,requests,enable=cockpit
    enable(count=2)
    js("OrreryConversationSource.Source.prototype.read=async()=>{const e=new Error('Previous conversation · fixture reason');e.code='history_stale';throw e};conversationView.refresh()")
    wait("document.querySelectorAll('.conversation-event').length===0")
    assert js("document.querySelector('.conversation-empty').textContent.includes('Previous conversation')")
    assert js("document.querySelector('.conversation-toolbar .conversation-status').textContent.includes('fixture reason')")


@pytest.mark.parametrize('count',[2,4],ids=['two-split','four-split'])
def test_split_history_is_per_cell_and_focus_keeps_existing_prompt_route(cockpit,count):
    js,wait,client,requests,enable=cockpit
    client.call('Emulation.setFocusEmulationEnabled',enabled=True)
    enable(claimed=True,count=3);js("document.querySelector('.conversation-expand').click();conversationView.close()")
    assert not js("document.querySelector('.screen').classList.contains('conversation-full')")
    names=['ReviewFixture']+[f'ReviewCell{i}' for i in range(1,count)]
    js("""window.splitNames="""+json.dumps(names)+""";
      for(let i=1;i<splitNames.length;i++){
        const name=splitNames[i];currentAgents.push({name,program:'codex',history_binding:'bound'});
        createPane(name,{paneId:'%'+String(901+i),windowId:'@'+String(901+i),width:80,height:20,alternateOn:true,mouseTracking:false});
        claimedSessions.add(name);
      }
      OrreryConversationSource.Source.prototype.read=async(name)=>({agent:name,provider:'codex',mode:'cursor',events:[
        {id:'one',kind:'text',role:'assistant',text:'History for '+name},
        {id:'file',kind:'tool',role:'assistant',text:'Read',references:[{id:'B'.repeat(32),label:'example.txt',kind:'file'}]}
      ],has_older:false});
      OrreryConversationSource.Source.prototype.reference=async()=>({kind:'text',text:'Generated preview'});
      replaceSplitSessions(splitNames);splitVisible=true;focusSplitSession(splitNames[0]);
    """)
    wait(f"document.querySelectorAll('.split-cell').length==={count}")
    wait("stageFitFrame===null")
    time.sleep(.15)
    assert js("document.querySelectorAll('.split-cell .split-history-toggle').length")==count
    js("window.splitBefore=[...document.querySelectorAll('.split-cell .termhost.on')].map(e=>({w:e.clientWidth,h:e.clientHeight}));packets.length=0;document.querySelector('.split-cell .split-history-toggle').click()")
    wait("document.querySelector('.split-cell .conversation-event')!==null")
    js("document.querySelector('.split-cell .conversation-expand').click()")
    assert js("""(()=>{const cell=document.querySelector('.split-cell'),panel=cell.querySelector('.conversation-panel'),a=cell.getBoundingClientRect(),b=panel.getBoundingClientRect();
      return b.left>=a.left&&b.right<=a.right&&b.top>=a.top&&b.bottom<=a.bottom&&b.width>a.width-4})()""")
    js("document.querySelectorAll('.split-cell .split-history-toggle')[1].click()")
    wait("document.querySelectorAll('.split-cell .conversation-panel:not([hidden])').length===2")
    assert js('promptTarget.textContent')==names[1]
    assert js('activeId')=='%902'
    js("document.querySelector('.split-cell .conversation-scroll').focus()")
    assert js('promptTarget.textContent')==names[0],js("({id:activeId,focus:document.activeElement.outerHTML,panels:[...document.querySelectorAll('.split-cell .conversation-panel')].map(e=>({id:e.id,hidden:e.hidden,owner:e.parentElement.dataset.session}))})")
    client.call('Input.dispatchKeyEvent',type='keyDown',key='ArrowUp',windowsVirtualKeyCode=38)
    client.call('Input.dispatchKeyEvent',type='keyUp',key='ArrowUp',windowsVirtualKeyCode=38)
    assert not js("packets.some(p=>p.type==='input')")
    js("promptInput.focus();promptInput.value='split fixture prompt';promptSend.click()")
    wait("packets.filter(p=>p.type==='input').length===2")
    assert js("packets.filter(p=>p.type==='input').map(p=>p.paneId)")==['%901','%901']
    js("document.querySelector('.split-cell .conversation-close').click();document.querySelectorAll('.split-cell')[1].querySelector('.conversation-file').click()")
    wait("document.querySelectorAll('.split-cell')[1].querySelector('.conversation-preview-text')!==null")
    assert js('promptTarget.textContent')==names[1]
    assert js("document.querySelector('.screen').classList.contains('conversation-open')")==False
    assert js("document.querySelectorAll('.split-cell .conversation-panel:not([hidden])').length")==1
    assert js("""(()=>{const cell=document.querySelectorAll('.split-cell')[1],p=cell.querySelector('.conversation-preview'),r=p.getBoundingClientRect(),c=cell.getBoundingClientRect();
      return r.left>=c.left&&r.right<=c.right&&r.top>=c.top&&r.bottom<=c.bottom&&getComputedStyle(cell.querySelector('.conversation-thread')).display==='none'})()""")
    js("document.querySelectorAll('.split-cell')[1].querySelector('.conversation-preview-close').click()")
    assert js("document.activeElement===document.querySelectorAll('.split-cell')[1].querySelector('.conversation-scroll')")
    assert js("[...document.querySelectorAll('.split-cell .termhost.on')].map(e=>({w:e.clientWidth,h:e.clientHeight}))")==js('splitBefore')
    assert not js("packets.some(p=>p.type==='resize')")


def test_disabling_split_readers_aborts_each_request_and_removes_local_controls(cockpit):
    js,wait,client,requests,enable=cockpit
    enable(count=1);js('conversationView.close()')
    js("""currentAgents.push({name:'OtherCell',program:'codex'});
      createPane('OtherCell',{paneId:'%902',windowId:'@902',width:80,height:20});
      window.pendingHistory=[];
      OrreryConversationSource.Source.prototype.read=(name,options)=>new Promise(resolve=>pendingHistory.push({name,signal:options.signal,resolve}));
      replaceSplitSessions(['ReviewFixture','OtherCell']);splitVisible=true;focusSplitSession('ReviewFixture');
      document.querySelectorAll('.split-history-toggle').forEach(button=>button.click());
    """)
    assert js('pendingHistory.length')==2
    js("conversationEnabled.checked=false;conversationEnabled.dispatchEvent(new Event('change'))")
    assert js('pendingHistory.every(request=>request.signal.aborted)')
    assert js("document.querySelectorAll('.split-history-toggle,.split-cell .conversation-panel,.split-cell.conversation-cell').length")==0
    js("pendingHistory.forEach(request=>request.resolve({events:[{id:'stale',kind:'text',role:'assistant',text:'STALE_SPLIT_BODY'}]}))")
    time.sleep(.05)
    assert not js("document.querySelector('.screen').textContent.includes('STALE_SPLIT_BODY')")
    assert js('conversationToggle.hidden')
