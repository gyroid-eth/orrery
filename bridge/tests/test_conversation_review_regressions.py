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
def cockpit():
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
    client.call("Emulation.setDeviceMetricsOverride", width=1600, height=1000, deviceScaleFactor=1, mobile=False)
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
