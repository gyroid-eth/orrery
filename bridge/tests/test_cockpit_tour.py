"""First-flight persistence, success-only hooks, and shared help-map state.

Node cases need no browser. The DOM case connects to an existing CDP browser
when ORRERY_TEST_CDP_URL is set; it never launches Chrome or a real agent.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

BRIDGE = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


def node(script):
    if not NODE:
        pytest.skip('node not installed')
    result = subprocess.run([NODE, '-e', script], text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def state(script):
    return node(f"const tour=require({json.dumps(str(BRIDGE / 'cockpit_tour.js'))});"
                "let value=null;const storage={getItem:()=>value,setItem:(key,v)=>{value=v;}};" + script)


def test_first_visit_close_and_reopen_preserve_progress():
    assert state("""
      let s=tour.createState(storage);const first=s.open;s.mark('start');s.close();
      s=tour.createState(storage);const closed=!s.open;s.show();
      console.log(JSON.stringify({first,closed,done:[...s.done],current:s.current.id}));
    """) == {'first': True, 'closed': True, 'done': ['start'], 'current': 'choose'}


def test_out_of_order_actions_idempotence_and_restart():
    assert state("""
      const s=tour.createState(storage);s.mark('telemetry');s.mark('telemetry');s.mark('invalid');
      const before=[...s.done];tour.STEPS.forEach(step=>s.mark(step.id));
      const complete=s.current===null&&s.done.size===7;s.reset();
      console.log(JSON.stringify({before,complete,empty:s.done.size===0,open:s.open}));
    """) == {'before': ['telemetry'], 'complete': True, 'empty': True, 'open': True}


def test_storage_denial_and_corrupt_or_unknown_values():
    assert state("""
      value='{bad';const corrupt=tour.createState(storage).open;
      value=JSON.stringify({seen:true,open:false,done:['talk','injected','talk']});
      const s=tour.createState(storage);s.mark('mail');const closed=[...s.done];
      const blocked=tour.createState({getItem(){throw Error('blocked');},setItem(){throw Error('quota');}});
      blocked.mark('choose');console.log(JSON.stringify({corrupt,closed,blocked:[...blocked.done]}));
    """) == {'corrupt': True, 'closed': ['talk'], 'blocked': ['choose']}


def test_help_map_toggle_does_not_reset_or_dismiss_checklist():
    assert state("""
      const s=tour.createState(storage);s.mark('start');s.toggleMap();const shown=s.map;
      s.hideMap();const restored=s.open&&!s.map&&s.done.has('start');
      s.close();s.toggleMap();s.toggleMap();console.log(JSON.stringify({shown,restored,closed:!s.open}));
    """) == {'shown': True, 'restored': True, 'closed': True}


def prompt(connected=True, pane=True, text='Hello', guarded=False):
    source = (BRIDGE / 'cockpit.html').read_text()
    fn = re.search(r'function sendPrompt\(opts\)\{.*?(?=\nfunction sendInterrupt)', source, re.S).group()
    return node("const events=[];let cleared=false;const activeId='pane';"
                f"const promptInput={{value:{json.dumps(text)}}};"
                f"const panes=new Map({json.dumps([['pane', {'session': 'Test'}]] if pane else [])});"
                "const document={dispatchEvent:e=>events.push(e.detail.id)};"
                "class CustomEvent{constructor(_,v){this.detail=v.detail;}}"
                f"function send(){{return {str(connected).lower()};}}"
                f"function inspectPrompt(){{return {'{}' if guarded else 'null'};}}"
                "function showToast(){}function showSendGuard(){}function hideSendGuard(){}"
                "function pushPromptHistory(){}function saveDraft(){}function closeSlashMenu(){}"
                "function setTimeout(fn){fn();}"
                + fn + ";sendPrompt();console.log(JSON.stringify({events,value:promptInput.value}));")


def test_talk_completes_only_for_a_sent_nonempty_unguarded_prompt():
    assert prompt()['events'] == ['talk']
    assert prompt(False)['events'] == []
    assert prompt(False)['value'] == 'Hello'
    assert prompt(pane=False)['events'] == []
    assert prompt(text='   ')['events'] == []
    assert prompt(guarded=True)['events'] == []


def test_pending_spawn_does_not_complete_until_ready():
    source = (BRIDGE / 'cockpit.html').read_text()
    watch = re.search(r'async function watchSpawnLaunch\(name\)\{.*?(?=\nasync function submitSpawn)', source, re.S).group()
    for verdict, expected in [('ready', ['start']), ('failed', [])]:
        actual = node("const events=[];const document={dispatchEvent:e=>events.push(e.detail.id)};"
                      "class CustomEvent{constructor(_,v){this.detail=v.detail;}}"
                      "function showToast(){}function setTimeout(fn){fn();}"
                      f"async function fetch(){{return {{json:async()=>({{ok:true,state:'{verdict}'}})}};}}"
                      + watch + ";watchSpawnLaunch('Test').then(()=>console.log(JSON.stringify(events)));")
        assert actual == expected


@pytest.fixture
def tour_browser():
    """Connect to an existing CDP browser; serve only this isolated checkout."""
    import contextlib
    import sys
    import threading
    import time
    import urllib.request
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    endpoint = os.environ.get('ORRERY_TEST_CDP_URL')
    if not endpoint:
        pytest.skip('set ORRERY_TEST_CDP_URL to an existing CDP browser')
    sys.path.insert(0, str(BRIDGE.parent))
    from tools.theme_axis_browser_test import _WebSocket

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(BRIDGE), **kwargs)

        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path.startswith(('/telemetry/', '/ws', '/api/')):
                self.send_error(404)
                return
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    request = urllib.request.Request(endpoint + '/json/new?about:blank', method='PUT')
    tab = json.load(urllib.request.urlopen(request, timeout=5))
    client = _WebSocket(tab['webSocketDebuggerUrl'])
    try:
        client.call('Page.enable')
        client.call('Runtime.enable')
        client.call('Emulation.setDeviceMetricsOverride', width=1600, height=1000, deviceScaleFactor=1, mobile=False)
        client.call('Page.navigate', url=f'http://127.0.0.1:{server.server_port}/cockpit.html')

        def evaluate(expression):
            result = client.call('Runtime.evaluate', expression=expression, awaitPromise=True, returnByValue=True)
            assert 'exceptionDetails' not in result, result
            return result.get('result', {}).get('value')

        for _ in range(100):
            if evaluate('Boolean(window.OrreryTour && OrreryTour.state)'):
                break
            time.sleep(.1)
        else:
            pytest.fail('tour did not mount')
        yield client, evaluate
    finally:
        with contextlib.suppress(OSError):
            urllib.request.urlopen(endpoint + '/json/close/' + tab['id'], timeout=5)
        server.shutdown()
        server.server_close()


def test_dom_map_escape_and_settings_reopen_keep_progress(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      document.dispatchEvent(new CustomEvent('oc:tour-action',{detail:{id:'start'}}));
      const checked=document.querySelector('[data-step="start"]').classList.contains('done');
      document.querySelector('.flight-guide .flight-close').click();
      const closed=document.querySelector('.flight-guide').hidden;
      document.getElementById('firstFlightBtn').click();
      document.getElementById('helpMapBtn').click();
      const shown=!document.querySelector('.flight-map').hidden&&document.querySelector('.flight-guide').hidden;
      document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
      return {checked,closed,shown,restored:!document.querySelector('.flight-guide').hidden,
        retained:document.querySelector('[data-step="start"]').classList.contains('done'),
        mapClosed:document.querySelector('.flight-map').hidden};
    })()""")
    assert all(result.values()), result


@pytest.mark.parametrize('width,height', [(1600, 1000), (1100, 700), (420, 800)])
def test_dom_map_cards_are_readable_and_do_not_overlap(tour_browser, width, height):
    client, evaluate = tour_browser
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
    result = evaluate("""new Promise(resolve=>{
      document.getElementById('helpMapBtn').click();
      requestAnimationFrame(()=>requestAnimationFrame(()=>{
        const cards=[...document.querySelectorAll('.flight-map-card')];
        const rects=cards.map(c=>c.getBoundingClientRect());
        const compact=document.querySelector('.flight-map').classList.contains('compact');
        const toolbar=document.querySelector('.flight-map-head').getBoundingClientRect();
        const headerOverlap=!compact&&rects.some(r=>r.left<toolbar.right&&r.right>toolbar.left&&r.top<toolbar.bottom&&r.bottom>toolbar.top);
        const overlap=headerOverlap||rects.some((a,i)=>rects.slice(i+1).some(b=>a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top));
        resolve({count:cards.length,overlap,within:rects.every(r=>r.left>=0&&r.right<=innerWidth),
          copy:cards.every(c=>c.querySelector('p').textContent===OrreryTour.STEPS.find(s=>s.id===c.dataset.step).copy),
          vertically:compact||rects.every(r=>r.top>=0&&r.bottom<=innerHeight)});
      }));
    })""")
    assert result == {'count': 7, 'overlap': False, 'within': True, 'copy': True, 'vertically': True}
