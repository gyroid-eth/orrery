"""A roster poll that finds nothing new leaves the DOM alone (2026-11-16).

Every 3 s the cockpit repainted every roster tile, about 600 DOM writes for 20
agents even when no row had changed, which
kept style and layout work running in an idle tab. These run the real cockpit
against a disposable fake dashboard and count DOM mutations around one poll.

Needs ORRERY_CDP_URL (an existing test browser). Run from bridge/:
``ORRERY_CDP_URL=http://127.0.0.1:9250 python -m pytest tests/test_cockpit_idle_dom.py``.
"""

import copy
import json
import os
from pathlib import Path
import sys
import threading
import time
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.theme_axis_browser_test import _WebSocket

CDP = os.environ.get('ORRERY_CDP_URL')
NAMES = ['AlphaNode', 'BetaNode', 'GammaNode', 'DeltaNode', 'EpsilonNode', 'ZetaNode']
AGENTS = [{
    'name': name, 'task': 'Fixture task ' + name, 'running': True, 'category': 'agent',
    'provider': 'anthropic' if i % 2 else 'openai', 'model': 'fixture-model', 'ctx_window': '200k',
    'ctx_used': 10 + i * 5, 'act_state': 'work' if i < 2 else 'wait', 'live': 'step %d' % i,
} for i, name in enumerate(NAMES)]


@pytest.fixture
def cockpit():
    if not CDP:
        pytest.skip('set ORRERY_CDP_URL to an existing test browser')
    state = {'agents': copy.deepcopy(AGENTS)}

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / 'bridge'), **kwargs)
        def log_message(self, *_):
            pass
        def answer(self, data):
            raw = json.dumps(data).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            path = urlsplit(self.path).path
            if path == '/api/version':
                self.answer({'api': 38})
            elif path == '/telemetry/agents':
                self.answer({'agents': state['agents']})
            elif path.startswith(('/api/', '/telemetry/')):
                self.answer({'agents': [], 'prefs': {}, 'messages': [], 'spawn': []})
            elif path.startswith('/cockpit-assets/'):
                self.path = '/assets/' + path.rsplit('/', 1)[1]
                super().do_GET()
            else:
                super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    tab = json.load(urllib.request.urlopen(urllib.request.Request(CDP + '/json/new?about:blank', method='PUT')))
    client = _WebSocket(tab['webSocketDebuggerUrl'])
    client.call('Page.enable')
    client.call('Runtime.enable')
    client.call('Emulation.setFocusEmulationEnabled', enabled=True)
    client.call('Emulation.setDeviceMetricsOverride', width=1600, height=1000, deviceScaleFactor=1, mobile=False)
    client.call('Page.addScriptToEvaluateOnNewDocument',
                source="localStorage.clear();localStorage.setItem('oc-term-conversation-enabled','0');")

    def js(expression):
        result = client.call('Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=True)
        assert not result.get('exceptionDetails'), result.get('exceptionDetails')
        return result.get('result', {}).get('value')
    def wait(expression):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if js(expression):
                return
            time.sleep(.05)
        raise AssertionError(expression)
    try:
        client.call('Page.navigate', url=f'http://127.0.0.1:{server.server_port}/cockpit.html')
        wait(f"typeof currentAgents!=='undefined'&&currentAgents.length=={len(NAMES)}")
        # the poll timers must not add writes of their own while a poll is measured
        js("""clearTimeout(reconnectTimer);scheduleReconnect=()=>{};send=()=>true;""")
        yield js, wait, state
    finally:
        urllib.request.urlopen(CDP + '/json/close/' + tab['id']).close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


# one poll, with the writes it made to the roster and to the rail's orrery counted
POLL = """(async()=>{
  const seen={roster:[],orrery:[]};
  const watch=(key,node)=>{const o=new MutationObserver(r=>seen[key].push(...r));
    o.observe(node,{subtree:true,childList:true,attributes:true,characterData:true});return o;};
  const a=watch('roster',document.getElementById('roster')),b=watch('orrery',document.getElementById('orrery'));
  await pollAgents();await new Promise(r=>setTimeout(r,60));
  seen.roster.push(...a.takeRecords());seen.orrery.push(...b.takeRecords());a.disconnect();b.disconnect();
  return {roster:seen.roster.length,orrery:seen.orrery.length,
    rosterTiles:[...new Set(seen.roster.map(r=>(r.target.closest&&r.target.closest('.agent')||r.target.parentElement.closest('.agent')||{dataset:{}}).dataset.agent))]};
})()"""


def settle(js):
    js("pollAgents()")           # the first poll after load may still paint late things
    time.sleep(.3)
    js("pollAgents()")
    # until the rail's nodes have finished fading in and stopped moving
    js("""(async()=>{let last=Date.now();const start=last;
      const o=new MutationObserver(()=>{last=Date.now();});
      o.observe(document.getElementById('orrery'),{subtree:true,childList:true,attributes:true});
      while(Date.now()-last<700&&Date.now()-start<8000)await new Promise(r=>setTimeout(r,100));
      o.disconnect();return 1;})()""")


def test_an_unchanged_roster_writes_nothing_to_the_roster(cockpit):
    js, wait, state = cockpit
    settle(js)
    r = js(POLL)
    assert r['roster'] == 0, r


def test_a_changed_row_repaints_only_that_tile(cockpit):
    js, wait, state = cockpit
    settle(js)
    state['agents'][3]['ctx_used'] = 77
    r = js(POLL)
    assert r['rosterTiles'] == ['DeltaNode'], r
    assert js("tiles.get('DeltaNode').querySelector('.pct').textContent") == '77%'
    state['agents'][4]['act_state'] = 'work'
    js(POLL)
    assert js("tiles.get('EpsilonNode').classList.contains('working')") is True
    assert js("document.querySelectorAll('#orrery .mini-agent.is-working').length") == 3
    state['agents'][4]['act_state'] = 'wait'
    js(POLL)
    assert js("tiles.get('EpsilonNode').classList.contains('working')") is False
    assert js("document.querySelectorAll('#orrery .mini-agent.is-working').length") == 2


def test_classes_the_poll_does_not_own_survive_it(cockpit):
    js, wait, state = cockpit
    settle(js)
    js("pinnedAgents.add('BetaNode');pollAgents()")
    time.sleep(.3)
    js("pollAgents()")
    assert js("tiles.get('BetaNode').classList.contains('pinned')") is True
    js("pinnedAgents.delete('BetaNode');pollAgents()")
    time.sleep(.3)
    js("pollAgents()")
    assert js("tiles.get('BetaNode').classList.contains('pinned')") is False
    assert js("tiles.get('AlphaNode').classList.contains('working')") is True


def test_a_mail_event_draws_a_line_between_the_two_agents(cockpit):
    js, wait, state = cockpit
    settle(js)
    assert js("document.querySelectorAll('#orrery .orrery-comm-edge').length") == 0
    js("""document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages:[{id:1,
      sender:'AlphaNode',recipients:[{name:'BetaNode',kind:'to'}],ts:Math.floor(Date.now()/1000),subject:'x'}]}}))""")
    wait("document.querySelectorAll('#orrery .orrery-comm-edge').length>0")
