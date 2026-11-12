"""The real desktop preference/mask scripts publish changes before navigation."""
import json
import os
import sys
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
import urllib.request

import pytest

from tools.theme_axis_browser_test import _WebSocket
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import orrery_backend as backend


def test_desktop_publishes_active_snapshot_and_explicit_off(tmp_path):
    cdp=os.environ.get('ORRERY_CDP_URL')
    if not cdp:pytest.skip('existing CDP required')
    root=Path(__file__).resolve().parents[1]
    state=dict(prefs={},rev=0,fail=False,puts=[])
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(root),**kwargs)
        def log_message(self,*_):pass
        def send(self,value,status=200,mime='application/json'):
            data=value if isinstance(value,bytes) else json.dumps(value).encode()
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path.startswith('/fixture'):
                return self.send(b'<!doctype html><head><script src="/prefs_sync.js"></script><script src="/demo_mask.js"></script><script src="/demo_mode.js"></script></head><body><p id="probe">Orchid on mira-node /Users/mira/notes</p><textarea id="draft">Orchid</textarea></body>',mime='text/html')
            if self.path=='/telemetry/prefs':return self.send(dict(prefs=state['prefs'],rev=state['rev']))
            if self.path=='/telemetry/identity':return self.send(dict(users=['mira'],hosts=['mira-node']))
            return super().do_GET()
        def do_PUT(self):
            value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['puts'].append(value)
            if state['fail']:return self.send(dict(error='unavailable'),503)
            state['prefs']=backend.merge_prefs(state['prefs'],value);state['rev']+=1
            return self.send(dict(prefs=state['prefs'],rev=state['rev']))
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    tab=client=None
    try:
        tab=json.load(urllib.request.urlopen(urllib.request.Request(cdp+'/json/new?about:blank',method='PUT')))
        client=_WebSocket(tab['webSocketDebuggerUrl']);client.call('Page.enable');client.call('Runtime.enable')
        def js(expression):
            result=client.call('Runtime.evaluate',expression=expression,returnByValue=True,awaitPromise=True)
            assert not result.get('exceptionDetails'),result
            return result.get('result',{}).get('value')
        def wait(expression):
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                if js(expression):return
                time.sleep(.03)
            raise AssertionError((expression,js('document.documentElement.outerHTML')))
        url=f'http://127.0.0.1:{server.server_port}/fixture'
        client.call('Page.navigate',url=url+'?demo=1&mask=Orchid')
        wait("window.OrreryDemo?.known===true")
        shared=json.loads(state['prefs']['orrery.demo.shared.v1'])
        assert shared==dict(version=1,on=True,words=['Orchid'])
        assert js("document.querySelector('#probe').textContent")=='****** on ********* /Users/****/notes'
        assert js("document.querySelector('#draft').value")=='Orchid'
        js('OrreryDemo.reloadFor(false);true')
        wait("window.OrreryDemo?.on===false&&location.search==='?mask=Orchid'")
        assert json.loads(state['prefs']['orrery.demo.shared.v1'])==dict(version=1,on=False,words=[])
        before=len(state['puts'])
        client.call('Page.reload')
        wait("window.OrreryDemo?.on===false&&document.readyState==='complete'")
        assert len(state['puts'])==before  # An ordinary off page cannot clear an active publisher.
        state['fail']=True
        client.call('Page.navigate',url=url+'?demo=1')
        wait("document.documentElement.dataset.demo==='failed'")
        assert js("getComputedStyle(document.body).visibility")=='hidden'
    finally:
        if client:client.socket.close()
        if tab:urllib.request.urlopen(cdp+'/json/close/'+tab['id']).close()
        server.shutdown();server.server_close();worker.join(3)
