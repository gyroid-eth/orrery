"""Real cockpit + WS + private tmux approval fixture, using an existing CDP."""
import asyncio
import json
import os
from pathlib import Path
import threading
import time
import urllib.request

import pytest
from aiohttp import web, ClientSession

from approval_fixture import fake_pane
from test_reader_approval import MCP, READ, COMMAND
from test_conversation_review_regressions import CDP, wait_reading_layout
from tools.theme_axis_browser_test import _WebSocket
import orrery_backend as backend


@pytest.fixture
def approval_browser(fake_pane,tmp_path,monkeypatch):
    if not CDP:pytest.skip('set ORRERY_CDP_URL to an existing browser')
    loop=asyncio.new_event_loop();ready=threading.Event();state={}
    async def start():
        manager=backend.SessionBridgeManager(str(fake_pane.wrapper),history_dir=tmp_path/'history')
        await manager._ensure_bridge('ApprovalFixture')
        app=web.Application();app[backend.BRIDGE_MANAGER_KEY]=manager;app[backend.TMUX_BIN_KEY]=str(fake_pane.wrapper)
        app.router.add_get('/ws',backend.websocket_handler)
        app[backend.HTTP_SESSION_KEY]=ClientSession()
        async def api(request):
            path=request.path
            harness=await fake_pane.harness(fake_pane.pane)
            agent=dict(name='ApprovalFixture',program=harness,provider='anthropic' if harness=='claude' else 'openai',running=True,act_state='ask',history_binding='bound')
            if path in ('/telemetry/agents','/api/agents'):return web.json_response(dict(agents=state.get('agents_override',[agent])))
            if path=='/telemetry/conversation':return web.json_response(dict(ok=True,agent='ApprovalFixture',provider='codex',mode='cursor',events=[dict(id=str(i),kind='text',role='assistant',text='A recorded explanation. '*20) for i in range(30)],after='tail'))
            if path=='/telemetry/host-platform':return web.json_response(dict(platform='macos'))
            return web.json_response(dict(agents=[],prefs={}))
        app.router.add_route('*','/telemetry/{tail:.*}',api)
        app.router.add_get('/api/agents',api)
        for path in backend.PUBLIC_FILES:app.router.add_get(path,backend.serve_public_file)
        runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        state.update(manager=manager,runner=runner,url='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1]))
    def thread_main():
        asyncio.set_event_loop(loop)
        try:loop.run_until_complete(start())
        except BaseException as exc:state['error']=exc
        ready.set();loop.run_forever()
    thread=threading.Thread(target=thread_main,daemon=True);thread.start();assert ready.wait(10)
    if 'error' in state:raise state['error']
    monkeypatch.setattr(backend,'DASHBOARD_URL',state['url'])
    tab=json.load(urllib.request.urlopen(urllib.request.Request(CDP+'/json/new?about:blank',method='PUT')))
    client=_WebSocket(tab['webSocketDebuggerUrl']);client.call('Page.enable');client.call('Runtime.enable')
    client.call('Emulation.setDeviceMetricsOverride',width=1440,height=1000,deviceScaleFactor=1,mobile=False)
    client.call('Emulation.setFocusEmulationEnabled',enabled=True)
    client.call('Page.addScriptToEvaluateOnNewDocument',source="localStorage.clear();localStorage.setItem('oc-first-flight-v1',JSON.stringify({seen:true,open:false}));")
    def js(expression):
        result=client.call('Runtime.evaluate',expression=expression,returnByValue=True,awaitPromise=True)
        assert not result.get('exceptionDetails'),result.get('exceptionDetails')
        return result.get('result',{}).get('value')
    def wait(expression):
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            if js(expression):return
            time.sleep(.03)
        raise AssertionError((expression,js("document.querySelector('.reader-approval')?.outerHTML"),fake_pane.capture(),fake_pane.keys.read_text() if fake_pane.keys.exists() else 'no keys',js('window.approvalTrace'),[getattr(s.bridge,'_approval_coordinator',None).screens for s in state['manager'].states.values()]))
    try:
        client.call('Page.navigate',url=state['url']+'/cockpit.html')
        wait("typeof readerApproval!=='undefined'&&readerApproval!==null&&availableSessions.has('ApprovalFixture')")
        js("manualOverride.add('ApprovalFixture');requestAttach('ApprovalFixture',true)")
        wait('panes.size===1')
        js("window.approvalTrace=[];window.tracedHandle=handle;handle=msg=>{if(msg.type==='approval')approvalTrace.push(msg);tracedHandle(msg)}")
        js("conversationView.open()")
        wait("document.querySelector('.conversation-panel:not([hidden])')!==null")
        wait("document.querySelector('.reader-approval:not([hidden])')!==null")
        wait("document.querySelectorAll('.conversation-event').length===30")
        wait_reading_layout(js)
        yield js,wait,client,fake_pane,state
    finally:
        client.socket.close()
        urllib.request.urlopen(CDP+'/json/close/'+tab['id']).close()
        async def stop():
            await state['runner'].cleanup();await state['manager'].close()
            await state['runner'].app[backend.HTTP_SESSION_KEY].close()
        asyncio.run_coroutine_threadsafe(stop(),loop).result(10)
        loop.call_soon_threadsafe(loop.stop);thread.join(5);loop.close()


def enter(client):
    client.call('Input.dispatchKeyEvent',type='keyDown',key='Enter',code='Enter',windowsVirtualKeyCode=13,text='\r')
    client.call('Input.dispatchKeyEvent',type='keyUp',key='Enter',code='Enter',windowsVirtualKeyCode=13)


def test_two_enters_allow_once_and_keep_focus(approval_browser):
    js,wait,client,pane,_=approval_browser
    assert js("document.querySelectorAll('.reader-approval-choice').length")==0
    js("document.querySelector('.reader-approval-toggle').focus()")
    enter(client)
    wait("document.activeElement.matches('.reader-approval-choice.is-once')")
    assert js('document.activeElement.dataset.choice')=='1'
    assert not pane.keys.exists()
    enter(client)
    wait("document.querySelector('.reader-approval').textContent.includes('Prompt closed')")
    assert json.loads(pane.result.read_text())==dict(selected=1,key='\r')
    js("queueStageFit(activeId)")
    js("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
    assert js("document.activeElement.closest('.reader-approval')!==null")
    assert js("document.querySelectorAll('.reader-approval-choice').length")==0
    client.call('Input.dispatchKeyEvent',type='keyDown',key='q',text='q')
    client.call('Input.dispatchKeyEvent',type='keyUp',key='q')
    raw=b''.join(bytes(json.loads(line)) for line in pane.keys.read_text().splitlines())
    assert b'q' not in raw


def test_claude_once_is_four_and_stale_click_sends_nothing(approval_browser):
    js,wait,client,pane,state=approval_browser
    pane.change(READ)
    wait("document.querySelector('.reader-approval-summary').textContent.startsWith('Read ·')")
    js("document.querySelector('.reader-approval-toggle').click()")
    assert js('document.activeElement.dataset.choice')=='4'
    # Change the private TUI after rendering, without letting the browser consume output.
    js("window.heldApproval=[];window.realHandle=handle;handle=msg=>msg.type==='output'||msg.type==='approval'&&msg.state==='ready'?heldApproval.push(msg):realHandle(msg)")
    pane.change(READ.replace('PUBLIC.json','OTHER.json'))
    deadline=time.monotonic()+5
    while time.monotonic()<deadline and 'OTHER.json' not in pane.capture():time.sleep(.02)
    enter(client)
    wait("document.querySelector('.reader-approval-main-title').textContent.includes('Approval changed')")
    assert not pane.keys.exists()
    assert js("document.querySelector('.reader-approval-toggle').getAttribute('aria-expanded')")=='false'
    js("handle=realHandle;heldApproval.forEach(handle)")
    wait("document.querySelector('.reader-approval-summary').textContent.includes('OTHER.json')")
    js("document.querySelector('.reader-approval-toggle').click()")
    wait("document.activeElement.matches('.reader-approval-choice.is-once:not(:disabled)')")
    enter(client)
    wait("document.querySelector('.reader-approval').textContent.includes('Prompt closed')")
    assert json.loads(pane.result.read_text())['selected']==4


@pytest.mark.parametrize('theme',['dark','light'])
def test_terminal_only_and_reader_position(approval_browser,theme):
    js,wait,client,pane,_=approval_browser
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    wait_reading_layout(js)
    js("window.readScroll=document.querySelector('.conversation-panel:not([hidden]) .conversation-scroll');readScroll.dispatchEvent(new WheelEvent('wheel',{deltaY:-100}));readScroll.scrollTop=100;readScroll.dispatchEvent(new Event('scroll'));window.beforeReadTop=readScroll.scrollTop")
    js("document.querySelector('.reader-approval-toggle').click()")
    assert abs(js('readScroll.scrollTop-beforeReadTop'))<=1
    pane.change(MCP.replace('message_id: 9','message_id: …'))
    wait("document.querySelector('.reader-approval-terminal:not([hidden])')!==null")
    assert js("document.querySelectorAll('.reader-approval-choice').length")==0
    assert abs(js('readScroll.scrollTop-beforeReadTop'))<=1
    js("document.querySelector('.reader-approval-terminal').click()")
    wait("document.querySelector('.reader-approval').hidden")
    assert not pane.keys.exists()


def test_identical_next_prompt_can_be_answered_again(approval_browser):
    js,wait,client,pane,_=approval_browser
    js("document.querySelector('.reader-approval-toggle').click()")
    enter(client)
    wait("document.querySelector('.reader-approval-main-title').textContent==='Prompt closed'")
    first=pane.keys.read_text()
    pane.change(MCP)
    wait("document.querySelector('.reader-approval-main-title').textContent.startsWith('Approval needed')")
    # A new approval is collapsed even when the previous one was expanded.
    assert js("document.querySelector('.reader-approval-toggle').getAttribute('aria-expanded')")=='false'
    js("document.querySelector('.reader-approval-toggle').click()")
    enter(client)
    wait("document.querySelector('.reader-approval-main-title').textContent==='Prompt closed'")
    assert len(pane.keys.read_text())>len(first)


def test_ack_does_not_enable_repeat_and_timeout_keeps_terminal_link(approval_browser):
    js,wait,client,pane,_=approval_browser
    pane.change(MCP,stay=True)
    js("document.querySelector('.reader-approval-toggle').click()")
    enter(client)
    wait("document.querySelector('.reader-approval-main-title').textContent.startsWith('Response sent')")
    first=pane.keys.read_text()
    assert js("document.querySelectorAll('.reader-approval-choice').length")==0
    enter(client)
    wait("document.querySelector('.reader-approval-main-title').textContent==='Response sent — check terminal'")
    assert pane.keys.read_text()==first
    assert js("!document.querySelector('.reader-approval-terminal').hidden")


def test_unchanged_redraw_keeps_full_request_selection(approval_browser):
    js,wait,client,pane,_=approval_browser
    js("document.querySelector('.reader-approval-toggle').click();window.keptApprovalText=document.querySelector('.reader-approval-full').firstChild;const range=document.createRange();range.setStart(keptApprovalText,0);range.setEnd(keptApprovalText,10);getSelection().removeAllRanges();getSelection().addRange(range);window.beforeInspectCount=approvalTrace.length")
    pane.change(MCP)
    wait('approvalTrace.length>beforeInspectCount')
    assert js("document.querySelector('.reader-approval-full').firstChild===keptApprovalText")
    assert js('getSelection().toString()===keptApprovalText.textContent.slice(0,10)')


def test_detached_pane_reports_unavailable_without_sending(approval_browser):
    js,wait,client,pane,_=approval_browser
    js("document.querySelector('.reader-approval-toggle').click();send({type:'detach',session:'ApprovalFixture'})")
    enter(client)
    wait("document.querySelector('.reader-approval-main-title').textContent==='Pane unavailable'")
    assert not pane.keys.exists()
    assert js("!document.querySelector('.reader-approval-terminal').hidden")


@pytest.mark.parametrize('theme',['dark','light'])
@pytest.mark.parametrize('text,title,kind,keys',[
    (READ,'Read outside the working directories','Claude · Read',['1','2','3','4']),
    (MCP,'Allow a Mail tool?','Codex · MCP tool',['1','2','3','4']),
    (COMMAND,'Run outside the sandbox?','Codex · Local environment',['Y','P','Esc']),
])
def test_details_match_selected_b_components(approval_browser,theme,text,title,kind,keys):
    js,wait,client,pane,_=approval_browser
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    pane.change(text)
    wait("document.querySelector('.reader-approval-title').textContent==="+json.dumps(title))
    assert js("document.querySelector('.reader-approval-main-title').textContent")=='Approval needed'
    assert js("document.querySelector('.reader-approval-fold').textContent")=='Show details ▾'
    js("document.querySelector('.reader-approval-toggle').click()")
    assert js("document.querySelector('.reader-approval-eyebrow').textContent").startswith('Approval needed')
    assert js("document.querySelector('.reader-approval-kind').textContent")==kind
    assert js("getComputedStyle(document.querySelector('.reader-approval-title')).fontSize")=='21px'
    assert 'Fraunces' in js("getComputedStyle(document.querySelector('.reader-approval-title')).fontFamily")
    assert js("getComputedStyle(document.querySelector('.reader-approval-full')).borderTopWidth")=='1px'
    assert js("[...document.querySelectorAll('.reader-approval-choice kbd')].map(e=>e.textContent)")==keys
    assert js("document.querySelector('.reader-approval-fold').textContent")=='Hide details ▴'
    assert not pane.keys.exists()


def test_quoted_example_does_not_offer_or_send_approval(approval_browser):
    js,wait,client,pane,_=approval_browser
    js('window.beforeQuoteFrames=approvalTrace.length')
    pane.change('Example of a previous approval screen; DO NOT ANSWER this example:\n'+MCP)
    wait('approvalTrace.length>beforeQuoteFrames')
    js("document.querySelector('.reader-approval-toggle').click()")
    count=js("document.querySelectorAll('.reader-approval-choice').length")
    if count:
        enter(client)
        wait("document.querySelector('.reader-approval').textContent.includes('Prompt closed')")
    assert count==0, 'quoted output was promoted to approval controls'
    assert not pane.keys.exists()


@pytest.mark.parametrize('agents', [[], [dict(name='AnotherFixture',program='codex',provider='openai',running=True)],
    [dict(name='ApprovalFixture',program='claude-code',provider='anthropic',running=True)],
    [dict(name='ApprovalFixture',program='codex',provider='anthropic',running=True)]])
def test_server_roster_must_match_before_answer(approval_browser,agents):
    js,wait,client,pane,state=approval_browser
    js("document.querySelector('.reader-approval-toggle').click()")
    state['agents_override']=agents
    enter(client)
    wait("document.querySelector('.reader-approval-main-title').textContent.includes('terminal review')")
    assert js("document.querySelectorAll('.reader-approval-choice').length")==0
    assert not pane.keys.exists()


def test_unsent_preflight_can_be_reviewed_again_in_reader(approval_browser):
    from reader_approval import ApprovalNotSent
    js,wait,client,pane,state=approval_browser
    bridge=state['manager'].states['ApprovalFixture'].bridge
    original=bridge.approval_keys_locked
    async def refuse(*args,**kwargs):raise ApprovalNotSent('fixture admission changed before keys')
    bridge.approval_keys_locked=refuse
    js("document.querySelector('.reader-approval-toggle').click()")
    enter(client)
    wait("document.querySelector('.reader-approval-main-title').textContent.startsWith('Response not sent')")
    assert not pane.keys.exists()
    assert js("document.querySelector('.reader-approval-toggle').getAttribute('aria-expanded')")=='false'
    bridge.approval_keys_locked=original
    js("document.querySelector('.reader-approval-toggle').click()")
    wait("document.activeElement.matches('.reader-approval-choice.is-once:not(:disabled)')")
    enter(client)
    wait("document.querySelector('.reader-approval-main-title').textContent==='Prompt closed'")
    assert json.loads(pane.result.read_text())==dict(selected=1,key='\r')
