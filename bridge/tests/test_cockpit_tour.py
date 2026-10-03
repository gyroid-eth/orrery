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


def test_any_tour_keeps_its_own_steps_key_and_fold():
    assert state("""
      const steps=[{id:'a',title:'A',copy:'a'},{id:'b',title:'B',copy:'b'}];
      const s=tour.createState(storage,{steps,key:'oc-other',autoOpen:false});
      const closed=!s.open;s.show();s.mark('a');s.mark('start');s.fold();
      const again=tour.createState(storage,{steps,key:'oc-other',autoOpen:false});
      console.log(JSON.stringify({closed,open:again.open,folded:again.folded,done:[...again.done],current:again.current.id,
        saved:Object.keys(JSON.parse(value))}));
    """) == {'closed': True, 'open': True, 'folded': True, 'done': ['a'], 'current': 'b',
             'saved': ['seen', 'open', 'folded', 'done']}


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
            if self.path.startswith('/tour-late-fixture.html'):
                # tour.html plus a page script that mounts its tour on DOMContentLoaded,
                # as a later tour's own script may; built here, never written to the checkout.
                late = ("<script>document.addEventListener('DOMContentLoaded',()=>OrreryTour.mountChecklist("
                        "{id:'late',title:'Current title',storageKey:'oc-test-late',"
                        "steps:[{id:'new',title:'Current step',copy:'From the page script.'}]}));</script></body>")
                body = (BRIDGE / 'tour.html').read_text().replace('</body>', late).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
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
        # Tests that open another page or window need the served address and the browser.
        evaluate.base = f'http://127.0.0.1:{server.server_port}'
        evaluate.endpoint = endpoint
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


MAP_LAYOUT = """new Promise(resolve=>{
  if(document.querySelector('.flight-map').hidden)document.getElementById('helpMapBtn').click();
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
    const map=document.querySelector('.flight-map');
    const notes=[...document.querySelectorAll('.flight-map-note')];
    const boxes=[...notes,document.querySelector('.flight-map-title')].map(el=>el.getBoundingClientRect());
    const overlap=boxes.some((a,i)=>boxes.slice(i+1).some(b=>a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top));
    const leaders=[...document.querySelectorAll('.flight-map-leader')].map(path=>{
      const step=OrreryTour.STEPS.find(s=>s.id===path.dataset.step);
      const r=document.querySelector(step.target).getBoundingClientRect();
      const n=document.querySelector('.flight-map-note[data-step="'+step.id+'"]').getBoundingClientRect();
      const pts=path.getAttribute('d').match(/-?[0-9.]+/g).map(Number);
      // The path starts on its control and its last point sits beside its own note.
      const [x0,y0]=pts;const end=path.getPointAtLength(path.getTotalLength());
      return {id:step.id,
        fromTarget:x0>=r.left-6&&x0<=r.right+6&&y0>=r.top-6&&y0<=r.bottom+6,
        toNote:end.y>=n.top&&end.y<=n.bottom&&Math.min(Math.abs(end.x-n.left),Math.abs(end.x-n.right))<=14};
    });
    resolve({count:notes.length,compact:map.classList.contains('compact'),overlap,leaders,
      frames:document.querySelectorAll('.flight-map-frame').length,
      within:boxes.every(r=>r.left>=0&&r.right<=innerWidth),
      vertically:map.classList.contains('compact')||boxes.every(r=>r.top>=0&&r.bottom<=innerHeight),
      copy:notes.every(n=>n.querySelector('p').textContent===OrreryTour.STEPS.find(s=>s.id===n.dataset.step).copy)});
  }));
})"""


@pytest.mark.parametrize('width,height', [(1600, 1000), (1440, 900), (1280, 800)])
def test_dom_map_annotates_every_control_with_a_leader(tour_browser, width, height):
    client, evaluate = tour_browser
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
    result = evaluate(MAP_LAYOUT)
    assert result['compact'] is False, result
    assert (result['count'], result['frames'], result['overlap'], result['within'], result['vertically'], result['copy']) == (7, 7, False, True, True, True)
    assert sorted(l['id'] for l in result['leaders']) == sorted(['start', 'choose', 'talk', 'mail', 'telemetry', 'planetarium', 'settings'])
    assert all(l['fromTarget'] and l['toNote'] for l in result['leaders']), result['leaders']


@pytest.mark.parametrize('width,height', [(1100, 700), (980, 800), (420, 800)])
def test_dom_map_falls_back_to_a_legend_when_leaders_do_not_fit(tour_browser, width, height):
    client, evaluate = tour_browser
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
    result = evaluate(MAP_LAYOUT)
    assert (result['compact'], result['count'], result['leaders'], result['overlap'], result['within'], result['copy']) == (True, 7, [], False, True, True)


def test_dom_map_click_anywhere_closes_but_legend_scrolls(tour_browser):
    client, evaluate = tour_browser
    evaluate(MAP_LAYOUT)
    closed_by_veil = evaluate("""(()=>{
      document.querySelector('.flight-map').dispatchEvent(new MouseEvent('click',{bubbles:true}));
      return document.querySelector('.flight-map').hidden;
    })()""")
    client.call('Emulation.setDeviceMetricsOverride', width=420, height=800, deviceScaleFactor=1, mobile=False)
    evaluate(MAP_LAYOUT)
    legend = evaluate("""(()=>{
      document.querySelector('.flight-map-note').click();
      const kept=!document.querySelector('.flight-map').hidden;
      document.querySelector('.flight-map-close').click();
      return {kept,closed:document.querySelector('.flight-map').hidden,
        focus:document.activeElement===document.getElementById('settingsBtn')};
    })()""")
    assert closed_by_veil is True
    assert legend == {'kept': True, 'closed': True, 'focus': True}


@pytest.mark.parametrize('outcome', ['success', 'local-reject', 'remote-reject', 'noop', 'busy'])
def test_profile_notifies_only_after_a_successful_commit(outcome):
    source = (BRIDGE / 'cockpit.html').read_text()
    commit = re.search(r'function commitThemeValuesTransaction\(transaction\)\{.*?(?=\nasync function setThemeProfile)', source, re.S).group()
    profile = re.search(r'async function setThemeProfile\(candidate,.*?(?=\nfunction setThemeAxis)', source, re.S).group()
    result = node(f"const outcome={json.dumps(outcome)};" + """
      const events=[];const document={dispatchEvent:e=>events.push(e.type)};
      class CustomEvent{constructor(type,v){this.type=type;this.detail=v.detail;}}
      let themeAxisState={values:{'small-text':null}};
      let themeAxisCommittedState={values:{'small-text':null}};
      let themeProfilePending=outcome==='busy',themeProfileRecovery=false;
      let themeAxisTransactionActive=false,themeProfileLastCandidateMeasurement,themeProfileLastTelemetryOutcome;
      function normalizeThemeAxisState(state){return {values:{...state.values}};}
      function themeAxisStrictProfileValues(values){return values;}
      function themeAxisValuesEqual(a,b){return JSON.stringify(a)===JSON.stringify(b);}
      function beginThemeValuesTransaction(values){
        const previousState=normalizeThemeAxisState(themeAxisState);
        themeAxisState={values};
        document.dispatchEvent(new CustomEvent('oc:theme-axis',{detail:{values}}));
        if(outcome==='local-reject')themeAxisState=previousState;
        return {ok:outcome!=='local-reject',transaction:{previousState,reason:'fixture'}};
      }
      async function requestTelemetryThemeProfile(){return {ok:outcome!=='remote-reject',rollbackVerified:true};}
      function restoreThemeValuesTransaction(tx){themeAxisState=tx.previousState;}
      function showToast(){}function setTelemetryThemeProfileReports(){}
      function appendThemeAxisHistory(){}function persistThemeAxisExperiment(){}
      function finishThemeAxisSettledTransaction(){}function paintThemeAxisControls(){}
      function activeThemeAxes(){return [];}
    """ + commit + profile + """
      setThemeProfile({'small-text':outcome==='noop'?null:1}).then(ok=>console.log(JSON.stringify({
        ok,events,committed:themeAxisCommittedState.values['small-text']})));
    """)
    assert ('oc:theme-profile-committed' in result['events']) is (outcome == 'success')
    assert result['committed'] == (1 if outcome == 'success' else None)
    assert result['ok'] is (outcome in {'success', 'noop'})


def test_dom_real_profile_button_completion_and_rejection(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(async()=>{
      for(const id of ['start','choose','talk','mail','telemetry','planetarium'])
        document.dispatchEvent(new CustomEvent('oc:tour-action',{detail:{id}}));
      const button=document.querySelector('[data-theme-axis-level="small-text"][data-theme-axis-value="1"]');
      // Keep the real click handler, setThemeProfile and commit function. Only
      // the local/remote acceptance stages are fixtures (coverage depends on
      // the browser's external fonts and styles).
      beginThemeValuesTransaction=values=>({ok:false,transaction:{reason:'fixture rejection'}});
      button.click();await new Promise(resolve=>setTimeout(resolve,0));
      const rejected=!OrreryTour.state.done.has('settings');
      document.dispatchEvent(new CustomEvent('oc:theme-axis',{detail:{values:{'small-text':1}}}));
      const provisional=!OrreryTour.state.done.has('settings');
      beginThemeValuesTransaction=values=>{
        const previousState=normalizeThemeAxisState(themeAxisState);
        themeAxisState=themeProfileStateAfter(values,new Date().toISOString());
        return {ok:true,transaction:{previousState,endSettledTransaction:()=>{},settledFinished:false}};
      };
      requestTelemetryThemeProfile=async()=>({ok:true});
      button.click();await new Promise(resolve=>setTimeout(resolve,0));
      return {rejected,provisional,committed:themeAxisCommittedState.values['small-text'],
        marked:OrreryTour.state.done.has('settings'),done:OrreryTour.state.done.size};
    })()""")
    assert result == {'rejected': True, 'provisional': True, 'committed': 1, 'marked': True, 'done': 7}


def test_dom_checklist_folds_to_a_band_that_follows_progress(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      const flight=OrreryTour.firstFlight,el=flight.el;flight.reset();
      document.dispatchEvent(new CustomEvent('oc:tour-action',{detail:{id:'start'}}));
      el.querySelector('.flight-fold').click();
      const band=el.querySelector('.flight-band');
      const folded={folded:el.classList.contains('folded'),panel:getComputedStyle(el.querySelector('.flight-panel')).display,
        text:band.textContent,height:Math.round(el.getBoundingClientRect().height)};
      document.dispatchEvent(new CustomEvent('oc:tour-action',{detail:{id:'choose'}}));
      const next=band.querySelector('.flight-item').textContent;
      band.click();
      return {...folded,next,unfolded:!el.classList.contains('folded'),saved:JSON.parse(localStorage.getItem(OrreryTour.KEY)).folded};
    })()""")
    assert result == {'folded': True, 'panel': 'none', 'text': 'Choose your agent' + 'now' + '1 / 7', 'height': 44,
                      'next': 'Talk to it', 'unfolded': True, 'saved': False}


def test_dom_tour_actions_are_scoped_to_their_tour(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      OrreryTour.firstFlight.reset();
      document.dispatchEvent(new CustomEvent('oc:tour-action',{detail:{id:'start',tour:'full-tour'}}));
      const foreign=OrreryTour.state.done.has('start');
      document.dispatchEvent(new CustomEvent('oc:tour-action',{detail:{id:'start',tour:'first-flight'}}));
      return {foreign,own:OrreryTour.state.done.has('start')};
    })()""")
    assert result == {'foreign': False, 'own': True}


def test_dom_checklist_drags_inside_the_window_and_remembers_the_spot(tour_browser):
    client, evaluate = tour_browser
    evaluate("localStorage.removeItem(OrreryTour.KEY+'-pos');OrreryTour.firstFlight.reset();OrreryTour.firstFlight.fold()")
    band = evaluate("(()=>{const r=document.querySelector('.flight-band').getBoundingClientRect();return {x:r.left+40,y:r.top+20};})()")
    mouse = lambda kind, x, y: client.call('Input.dispatchMouseEvent', type=kind, x=x, y=y, button='left',
                                           buttons=0 if kind == 'mouseReleased' else 1, clickCount=1)
    mouse('mousePressed', band['x'], band['y'])
    for step in range(1, 9):
        mouse('mouseMoved', band['x'] - 70 * step, band['y'] - 50 * step)
    mouse('mouseReleased', band['x'] - 560, band['y'] - 400)
    moved = evaluate("""(()=>{const el=OrreryTour.firstFlight.el,r=el.getBoundingClientRect();
      return {placed:el.classList.contains('placed'),folded:el.classList.contains('folded'),
        saved:JSON.parse(localStorage.getItem(OrreryTour.KEY+'-pos')),left:Math.round(r.left),top:Math.round(r.top)};})()""")
    assert moved['placed'] and moved['folded'], moved  # a drag is not a click on the band
    assert (moved['left'], moved['top']) == (round(moved['saved']['left']), round(moved['saved']['top']))
    # A spot outside a smaller window is pulled back in; a narrow window uses the default place.
    client.call('Emulation.setDeviceMetricsOverride', width=760, height=500, deviceScaleFactor=1, mobile=False)
    evaluate("localStorage.setItem(OrreryTour.KEY+'-pos',JSON.stringify({left:1500,top:900}));OrreryTour.firstFlight.render()")
    pulled = evaluate("(()=>{const r=OrreryTour.firstFlight.el.getBoundingClientRect();return r.right<=innerWidth&&r.bottom<=innerHeight&&r.left>=0;})()")
    client.call('Emulation.setDeviceMetricsOverride', width=420, height=800, deviceScaleFactor=1, mobile=False)
    evaluate("OrreryTour.firstFlight.render()")
    narrow = evaluate("(()=>{const el=OrreryTour.firstFlight.el,r=el.getBoundingClientRect();return {placed:el.classList.contains('placed'),left:r.left,right:r.right===innerWidth};})()")
    assert pulled is True
    assert narrow == {'placed': False, 'left': 0, 'right': True}


def test_dom_checklist_pops_out_to_its_own_window_and_comes_back(tour_browser):
    import time
    import urllib.request
    client, evaluate = tour_browser
    # A popup needs a user gesture, as it would from a real press of the button.
    client.call('Runtime.evaluate', expression="OrreryTour.firstFlight.reset();document.querySelector('.flight-popout').click()",
                userGesture=True)
    popup = None
    for _ in range(50):
        targets = json.load(urllib.request.urlopen(evaluate.endpoint + '/json', timeout=5))
        popup = next((t for t in targets if t.get('url', '').startswith(evaluate.base) and 'tour=first-flight' in t['url']), None)
        if popup:
            break
        time.sleep(.1)
    assert popup, 'no tour window opened'
    try:
        assert evaluate("OrreryTour.firstFlight.el.hidden") is True
        from tools.theme_axis_browser_test import _WebSocket
        other = _WebSocket(popup['webSocketDebuggerUrl'])
        other.call('Runtime.enable')

        def in_popup(expression):
            return other.call('Runtime.evaluate', expression=expression, returnByValue=True)['result'].get('value')
        for _ in range(100):
            if in_popup("Boolean(window.OrreryTour&&OrreryTour.state)"):
                break
            time.sleep(.1)
        evaluate("document.dispatchEvent(new CustomEvent('oc:tour-action',{detail:{id:'start'}}))")
        for _ in range(30):
            if in_popup("OrreryTour.state.done.has('start')"):
                break
            time.sleep(.1)
        alone = in_popup("""JSON.stringify({synced:OrreryTour.state.done.has('start'),
          shown:[...document.body.children].filter(e=>getComputedStyle(e).display!=='none').map(e=>e.className),
          map:!!document.querySelector('.flight-map'),popout:document.querySelector('.flight-popout').hidden})""")
        assert json.loads(alone) == {'synced': True, 'shown': ['flight-guide solo'], 'map': False, 'popout': True}
    finally:
        urllib.request.urlopen(evaluate.endpoint + '/json/close/' + popup['id'], timeout=5)
    for _ in range(40):
        if evaluate("!OrreryTour.firstFlight.el.hidden"):
            break
        time.sleep(.1)
    assert evaluate("!OrreryTour.firstFlight.el.hidden") is True


def test_dom_another_tours_window_leaves_the_first_flight_out(tour_browser):
    import time
    client, evaluate = tour_browser
    client.call('Page.navigate', url=evaluate.base + '/tour.html?tour=full-tour')
    for _ in range(100):
        if evaluate("Boolean(window.OrreryTour&&OrreryTour.mountChecklist&&document.readyState==='complete')"):
            break
        time.sleep(.1)
    result = evaluate("""(()=>{
      const before=document.querySelectorAll('.flight-guide').length;
      const later=OrreryTour.mountChecklist({id:'full-tour',title:'Full tour',storageKey:'oc-test-full-tour',
        steps:[{id:'exit',title:'Exit an agent',copy:'Use EXIT in the deck.'}]});
      let seen=null;later.onChange(()=>{seen=later.state.current&&later.state.current.id;});later.show();
      return {before,solo:later.el.classList.contains('solo'),visible:!later.el.hidden,seen};
    })()""")
    assert result == {'before': 0, 'solo': True, 'visible': True, 'seen': 'exit'}


def test_dom_tour_window_runs_no_cockpit_behind_the_checklist(tour_browser):
    """Review of #14: a hidden cockpit in the tour window answered Cmd+K, Enter."""
    import time
    client, evaluate = tour_browser
    client.call('Page.navigate', url=evaluate.base + '/tour.html?tour=first-flight')
    for _ in range(100):
        if evaluate("Boolean(window.OrreryTour&&OrreryTour.state)"):
            break
        time.sleep(.1)
    for key, modifiers in [('k', 4), ('Enter', 0), ('Escape', 0)]:
        client.call('Input.dispatchKeyEvent', type='keyDown', key=key, modifiers=modifiers)
        client.call('Input.dispatchKeyEvent', type='keyUp', key=key, modifiers=modifiers)
    result = evaluate("""JSON.stringify({
      cockpit:['jumpToAgent','sendPrompt','pollMail','startPoll'].filter(name=>name in window),
      elements:[...document.body.children].filter(e=>e.tagName!=='SCRIPT').map(e=>e.className),
      palette:!!document.getElementById('paletteOverlay'),
      shown:!OrreryTour.firstFlight.el.hidden,solo:OrreryTour.firstFlight.solo})""")
    assert json.loads(result) == {'cockpit': [], 'elements': ['flight-guide solo'], 'palette': False,
                                  'shown': True, 'solo': True}


def test_tour_page_keeps_the_cockpit_dark_palette():
    root = re.search(r':root\{(.*?)\n  \}', (BRIDGE / 'cockpit.html').read_text(), re.S).group(1)
    tour = re.search(r':root\{(.*?)\n  \}', (BRIDGE / 'tour.html').read_text(), re.S).group(1)
    token = lambda css: dict((k.strip(), v.split('/*')[0].strip()) for k, v in re.findall(r'(--[\w-]+):([^;]+);', css))
    cockpit, page = token(root), token(tour)
    assert page and all(cockpit.get(name) == value for name, value in page.items()), \
        {name: (value, cockpit.get(name)) for name, value in page.items() if cockpit.get(name) != value}


def test_cockpit_with_a_tour_query_is_still_the_cockpit():
    assert 'tour-window' not in (BRIDGE / 'cockpit.html').read_text()


def _popup_for(evaluate, tour):
    import time
    import urllib.request
    for _ in range(50):
        targets = json.load(urllib.request.urlopen(evaluate.endpoint + '/json', timeout=5))
        found = next((t for t in targets if t.get('url', '').startswith(evaluate.base + '/tour.html') and 'tour=' + tour in t['url']), None)
        if found:
            return found
        time.sleep(.1)
    return None


def test_dom_any_tour_pops_out_through_its_stored_definition(tour_browser):
    """Review of #14: a tour other than the first flight opened a blank window.
    Only the cockpit page is driven here; the tour window is read, never injected."""
    import time
    import urllib.request
    client, evaluate = tour_browser
    evaluate("""(()=>{
      const tour=OrreryTour.mountChecklist({id:'review-extended',title:'Review tour',storageKey:'oc-test-review-tour',autoOpen:true,
        steps:[{id:'one',title:'First thing',copy:'Do the first thing.'},{id:'two',title:'Second thing',copy:'Then this.'}]});
      tour.reset();
    })()""")
    client.call('Runtime.evaluate', userGesture=True,
                expression="OrreryTour.getChecklist('review-extended').el.querySelector('.flight-popout').click()")
    popup = _popup_for(evaluate, 'review-extended')
    assert popup, 'no tour window opened'
    try:
        from tools.theme_axis_browser_test import _WebSocket
        other = _WebSocket(popup['webSocketDebuggerUrl'])
        other.call('Runtime.enable')

        def read():
            value = other.call('Runtime.evaluate', returnByValue=True, expression="""JSON.stringify((()=>{
              const el=document.querySelector('.flight-guide[data-tour="review-extended"]');
              return el&&{solo:el.classList.contains('solo'),hidden:el.hidden,title:el.querySelector('h2').textContent,
                items:[...el.querySelectorAll('.flight-steps .flight-item')].map(n=>n.textContent),
                done:[...el.querySelectorAll('.flight-steps li.done')].map(n=>n.dataset.step)};
            })())""")['result'].get('value')
            return json.loads(value) if value else None
        for _ in range(60):
            if read():
                break
            time.sleep(.1)
        assert read() == {'solo': True, 'hidden': False, 'title': 'Review tour',
                          'items': ['First thing', 'Second thing'], 'done': []}
        for _ in range(30):
            if evaluate("OrreryTour.getChecklist('review-extended').el.hidden"):
                break
            time.sleep(.1)
        assert evaluate("OrreryTour.getChecklist('review-extended').el.hidden") is True
        evaluate("document.dispatchEvent(new CustomEvent('oc:tour-action',{detail:{id:'one',tour:'review-extended'}}))")
        for _ in range(30):
            if read()['done'] == ['one']:
                break
            time.sleep(.1)
        assert read()['done'] == ['one']
    finally:
        urllib.request.urlopen(evaluate.endpoint + '/json/close/' + popup['id'], timeout=5)


def test_dom_tour_window_without_a_definition_says_so(tour_browser):
    import time
    client, evaluate = tour_browser
    evaluate("localStorage.removeItem('oc-tour-definition:nowhere')")
    client.call('Page.navigate', url=evaluate.base + '/tour.html?tour=nowhere')
    for _ in range(100):
        if evaluate("document.readyState==='complete'&&Boolean(window.OrreryTour)"):
            break
        time.sleep(.1)
    time.sleep(.2)
    assert evaluate("""JSON.stringify({guides:document.querySelectorAll('.flight-guide').length,
      note:(document.querySelector('.flight-missing')||{}).textContent||null})""") == json.dumps(
        {'guides': 0, 'note': 'This tour is not available here. Close this window and open it again from the cockpit.'},
        separators=(',', ':'))


def test_dom_mounting_a_tour_twice_returns_the_first(tour_browser):
    _, evaluate = tour_browser
    assert evaluate("""(()=>{
      const def={id:'twice',title:'Twice',storageKey:'oc-test-twice',steps:[{id:'a',title:'A',copy:'a'}]};
      const a=OrreryTour.mountChecklist(def),b=OrreryTour.mountChecklist({...def,title:'Other'});
      return a===b&&OrreryTour.getChecklist('twice')===a&&document.querySelectorAll('[data-tour="twice"]').length===1;
    })()""") is True


def test_dom_tour_page_script_wins_over_the_stored_definition(tour_browser):
    """Review of #14 (P3): the stored-definition fallback must not pre-empt a page
    script that mounts its tour on DOMContentLoaded, nor keep an older definition."""
    import time
    client, evaluate = tour_browser
    evaluate("""localStorage.setItem('oc-tour-definition:late',JSON.stringify({id:'late',title:'Old title',
      storageKey:'oc-test-late',steps:[{id:'old',title:'Old step',copy:'Saved earlier.'}]}))""")
    client.call('Page.navigate', url=evaluate.base + '/tour-late-fixture.html?tour=late')
    for _ in range(100):
        if evaluate("document.readyState==='complete'&&Boolean(window.OrreryTour&&OrreryTour.getChecklist('late'))"):
            break
        time.sleep(.1)
    time.sleep(.2)
    shown = """JSON.stringify([...document.querySelectorAll('.flight-guide')].map(el=>({
      title:el.querySelector('h2').textContent,items:[...el.querySelectorAll('.flight-steps .flight-item')].map(n=>n.textContent)})))"""
    assert json.loads(evaluate(shown)) == [{'title': 'Current title', 'items': ['Current step']}]
    # A page script that only arrives after the fallback still replaces it.
    client.call('Page.navigate', url=evaluate.base + '/tour.html?tour=late')
    for _ in range(100):
        if evaluate("document.readyState==='complete'&&Boolean(window.OrreryTour&&OrreryTour.getChecklist('late'))"):
            break
        time.sleep(.1)
    fallback = json.loads(evaluate(shown))
    evaluate("""OrreryTour.mountChecklist({id:'late',title:'Current title',storageKey:'oc-test-late',
      steps:[{id:'new',title:'Current step',copy:'From the page script.'}]})""")
    assert fallback == [{'title': 'Old title', 'items': ['Old step']}]
    assert json.loads(evaluate(shown)) == [{'title': 'Current title', 'items': ['Current step']}]


FAKE_APP = """(()=>{
  // The desktop app's bridge, as far as the checklist uses it. Knobs set the timing
  // of the review cases: how long listen takes, whether it fails, and when the
  // native window closes relative to open_tour_window.
  window.appCalls=[];window.appClosed=null;window.appKnobs={listenMs:0,listenFails:false,closeAfterMs:null,closeDuringOpen:false,windowExists:true};
  const closeNotice={payload:{tour:'first-flight',url:location.origin+'/tour.html?tour=first-flight'}};
  let handler=null;
  const emit=()=>{if(handler)handler(closeNotice);};
  window.__TAURI__={core:{invoke:(name,args)=>{appCalls.push([name,args]);
      if(!window.appHasTourWindows)return Promise.reject('Command '+name+' not found');
      if(name==='open_tour_window'&&appKnobs.closeDuringOpen)emit();
      if(name==='open_tour_window'&&appKnobs.closeAfterMs!==null)setTimeout(emit,appKnobs.closeAfterMs);
      if(name==='tour_window_exists')return Promise.resolve(appKnobs.windowExists);
      return Promise.resolve();}},
    event:{listen:(name,fn)=>new Promise((resolve,reject)=>setTimeout(()=>{
      if(appKnobs.listenFails)return reject('no event permission');
      if(name==='orrery://pane-window-closed'){handler=fn;appClosed=fn;}
      resolve(()=>{});},appKnobs.listenMs))}};
})()"""


def test_dom_older_app_without_tour_windows_keeps_the_panel(tour_browser):
    _, evaluate = tour_browser
    evaluate(FAKE_APP)
    result = evaluate("""(async()=>{
      window.appHasTourWindows=false;
      const flight=OrreryTour.firstFlight;flight.reset();
      const offered=!flight.el.querySelector('.flight-popout').hidden;
      flight.el.querySelector('.flight-popout').click();
      await new Promise(resolve=>setTimeout(resolve,50));
      return {offered,calls:appCalls.map(c=>c[0]),panel:!flight.el.hidden,
        stillOffered:!flight.el.querySelector('.flight-popout').hidden};
    })()""")
    assert result == {'offered': True, 'calls': ['open_tour_window'], 'panel': True, 'stillOffered': False}


def test_dom_app_opens_a_tour_window_and_takes_the_panel_back_when_it_closes(tour_browser):
    _, evaluate = tour_browser
    evaluate(FAKE_APP)
    result = evaluate("""(async()=>{
      window.appHasTourWindows=true;
      const flight=OrreryTour.firstFlight;flight.reset();
      flight.el.querySelector('.flight-popout').click();
      await new Promise(resolve=>setTimeout(resolve,50));
      const [name,args]=appCalls[0];
      const opened={name,tour:args.tour,size:[args.width,args.height],hidden:flight.el.hidden};
      appClosed({payload:{tour:'first-flight',url:location.origin+'/tour.html?tour=first-flight&ws=ws://elsewhere/ws'}});
      const otherBackend=flight.el.hidden;
      appClosed({payload:{tour:'full-tour',url:location.origin+'/tour.html?tour=full-tour'}});
      const otherTour=flight.el.hidden;
      appClosed({payload:{tour:'first-flight',url:location.origin+'/tour.html?tour=first-flight'}});
      return {...opened,otherBackend,otherTour,back:!flight.el.hidden};
    })()""")
    assert result == {'name': 'open_tour_window', 'tour': 'first-flight', 'size': [360, result['size'][1]],
                      'hidden': True, 'otherBackend': True, 'otherTour': True, 'back': True}


def test_dom_app_tour_window_closes_through_the_app(tour_browser):
    import time
    client, evaluate = tour_browser
    client.call('Page.navigate', url=evaluate.base + '/tour.html?tour=first-flight')
    for _ in range(100):
        if evaluate("document.readyState==='complete'&&Boolean(window.OrreryTour&&OrreryTour.firstFlight)"):
            break
        time.sleep(.1)
    evaluate(FAKE_APP)
    result = evaluate("""(async()=>{
      window.appHasTourWindows=true;
      OrreryTour.firstFlight.el.querySelector('.flight-close').click();
      await new Promise(resolve=>setTimeout(resolve,50));
      return JSON.stringify(appCalls);
    })()""")
    assert json.loads(result) == [['close_tour_window', {'tour': 'first-flight'}]]


@pytest.mark.parametrize('case', [
    {'listenMs': 40, 'closeAfterMs': 5},      # review of #15: closed before the subscription was ready
    {'listenMs': 0, 'closeDuringOpen': True},  # closed before open_tour_window resolved
])
def test_dom_app_window_closing_early_still_brings_the_panel_back(tour_browser, case):
    _, evaluate = tour_browser
    evaluate(FAKE_APP)
    result = evaluate("""(async()=>{
      window.appHasTourWindows=true;Object.assign(appKnobs,%s);
      const flight=OrreryTour.firstFlight;flight.reset();
      flight.el.querySelector('.flight-popout').click();
      await new Promise(resolve=>setTimeout(resolve,150));
      return {opened:appCalls.some(c=>c[0]==='open_tour_window'),panel:!flight.el.hidden};
    })()""" % json.dumps(case))
    assert result == {'opened': True, 'panel': True}


def test_dom_app_without_a_close_subscription_does_not_open(tour_browser):
    _, evaluate = tour_browser
    evaluate(FAKE_APP)
    result = evaluate("""(async()=>{
      window.appHasTourWindows=true;appKnobs.listenFails=true;
      const flight=OrreryTour.firstFlight;flight.reset();
      flight.el.querySelector('.flight-popout').click();
      await new Promise(resolve=>setTimeout(resolve,50));
      return {calls:appCalls.map(c=>c[0]),panel:!flight.el.hidden,offered:!flight.el.querySelector('.flight-popout').hidden};
    })()""")
    assert result == {'calls': [], 'panel': True, 'offered': False}


def test_dom_app_window_gone_without_a_notice_is_noticed(tour_browser):
    _, evaluate = tour_browser
    evaluate(FAKE_APP)
    result = evaluate("""(async()=>{
      window.appHasTourWindows=true;
      const flight=OrreryTour.firstFlight;flight.reset();
      flight.el.querySelector('.flight-popout').click();
      await new Promise(resolve=>setTimeout(resolve,50));
      const out=flight.el.hidden;
      appKnobs.windowExists=false; // the window went away and no notice came
      await new Promise(resolve=>setTimeout(resolve,2300));
      return {out,asked:appCalls.filter(c=>c[0]==='tour_window_exists').length>0,panel:!flight.el.hidden};
    })()""")
    assert result == {'out': True, 'asked': True, 'panel': True}

