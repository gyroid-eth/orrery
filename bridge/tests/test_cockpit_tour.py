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


def test_choosing_a_step_makes_it_current_without_completing_it():
    assert state("""
      let s=tour.createState(storage);const log=[];const now=()=>s.current&&s.current.id;
      log.push(s.goTo('mail'),now(),[...s.done]);
      log.push(s.mark('mail'),now());
      log.push(s.goTo('choose'),now());
      s=tour.createState(storage);log.push(now());
      log.push(s.goTo('mail'),s.goTo('choose'),s.goTo('nowhere'));
      log.push(s.goTo('start'),now());
      s.reset();log.push(now(),JSON.parse(value).focus);
      console.log(JSON.stringify(log));
    """) == [True, 'mail', [],               # ahead: current, still not done
             True, 'telemetry',              # done: on to the next open step after it
             True, 'choose',                 # back to a skipped step
             'choose',                       # remembered
             False, False, False,            # a done step, the current one, an unknown one
             True, 'start',                  # the first open step clears the choice
             'start', None]                  # restart forgets it


def test_marking_another_step_keeps_the_chosen_one_and_the_last_step_ends_the_tour():
    assert state("""
      const s=tour.createState(storage);s.goTo('settings');s.mark('start');
      const kept=s.current.id;s.mark('settings');const after=s.current.id;
      tour.STEPS.forEach(step=>s.mark(step.id));
      console.log(JSON.stringify({kept,after,end:s.current}));
    """) == {'kept': 'settings', 'after': 'choose', 'end': None}


def test_a_saved_choice_that_is_done_or_unknown_is_dropped():
    assert state("""
      value=JSON.stringify({seen:true,open:true,done:['mail'],focus:'mail'});
      const a=tour.createState(storage).current.id;
      value=JSON.stringify({seen:true,open:true,done:[],focus:'injected'});
      const b=tour.createState(storage).current.id;
      console.log(JSON.stringify({a,b}));
    """) == {'a': 'start', 'b': 'start'}


def test_here_tag_goes_below_above_or_beside_and_never_over_the_panel():
    """The HERE tag beside the tour's ring: below first, then above, right,
    left; inside the view and clear of the panel, or not shown at all."""
    assert node(f"""const t=require({json.dumps(str(BRIDGE / 'cockpit_tour.js'))});
      const size={{w:60,h:20}},view={{w:1000,h:600}};
      const r=(l,tp,rr,b)=>({{l,t:tp,r:rr,b}});
      console.log(JSON.stringify([
        t.placeHereTag(r(100,100,200,140),size,view),
        t.placeHereTag(r(100,560,200,590),size,view),
        t.placeHereTag(r(100,100,200,140),size,view,[r(80,140,300,600)]),
        t.placeHereTag(r(100,100,200,140),size,view,[r(80,140,300,600),r(80,0,300,100)]),
        t.placeHereTag(r(0,0,1000,600),size,view),
        t.placeHereTag(r(900,10,990,30),size,view).x+size.w<=view.w-6]));""") == [
        {'x': 120, 'y': 148, 'side': 'below'},
        {'x': 120, 'y': 532, 'side': 'above'},
        {'x': 120, 'y': 72, 'side': 'above'},
        {'x': 208, 'y': 110, 'side': 'right'},
        None,
        True]


def test_here_tag_skips_a_side_that_would_cover_something():
    """A spot that would cover a control, the brand, the clock or a terminal
    is skipped like one off the view; with every side covered only the ring
    shows."""
    assert node(f"""const t=require({json.dumps(str(BRIDGE / 'cockpit_tour.js'))});
      const size={{w:60,h:20}},view={{w:1000,h:600}};
      const r=(l,tp,rr,b)=>({{l,t:tp,r:rr,b}});
      const below=box=>box.t>=140;
      console.log(JSON.stringify([
        t.placeHereTag(r(100,100,200,140),size,view,[],8,6,below),
        t.placeHereTag(r(100,100,200,140),size,view,[],8,6,()=>true)]));""") == [
        {'x': 120, 'y': 72, 'side': 'above'},
        None]


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
             'saved': ['seen', 'open', 'folded', 'done', 'focus']}


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
      const step=OrreryTour.MAP_NOTES.find(s=>s.id===path.dataset.step);
      const r=document.querySelector(step.target).getBoundingClientRect();
      const n=document.querySelector('.flight-map-note[data-step="'+step.id+'"]').getBoundingClientRect();
      const pts=path.getAttribute('d').match(/-?[0-9.]+/g).map(Number);
      // The path starts on its control and its last point sits beside its own note.
      const [x0,y0]=pts;const end=path.getPointAtLength(path.getTotalLength());
      return {id:step.id,
        fromTarget:x0>=r.left-6&&x0<=r.right+6&&y0>=r.top-6&&y0<=r.bottom+6,
        toNote:end.y>=n.top&&end.y<=n.bottom&&Math.min(Math.abs(end.x-n.left),Math.abs(end.x-n.right))<=14};
    });
    // Leaders are runs of horizontal and vertical segments; no two leaders may
    // cross or run along each other.
    const segments=[...document.querySelectorAll('.flight-map-leader')].map(path=>{
      const parts=path.getAttribute('d').match(/[MHV][^MHV]*/g);let x=0,y=0;const out=[];
      parts.forEach(part=>{const n=part.slice(1).split(',').map(Number);
        if(part[0]==='M'){x=n[0];y=n[1];}
        else if(part[0]==='H'){out.push([x,y,n[0],y]);x=n[0];}
        else{out.push([x,y,x,n[0]]);y=n[0];}});
      return out;
    });
    const within=(a,lo,hi)=>a>Math.min(lo,hi)+.5&&a<Math.max(lo,hi)-.5;
    const meets=(a,b)=>{
      const ah=a[1]===a[3],bh=b[1]===b[3];
      if(ah&&!bh)return within(b[0],a[0],a[2])&&within(a[1],b[1],b[3]);
      if(!ah&&bh)return within(a[0],b[0],b[2])&&within(b[1],a[1],a[3]);
      if(ah&&bh)return Math.abs(a[1]-b[1])<1.5&&Math.min(Math.max(a[0],a[2]),Math.max(b[0],b[2]))-Math.max(Math.min(a[0],a[2]),Math.min(b[0],b[2]))>.5;
      return Math.abs(a[0]-b[0])<1.5&&Math.min(Math.max(a[1],a[3]),Math.max(b[1],b[3]))-Math.max(Math.min(a[1],a[3]),Math.min(b[1],b[3]))>.5;
    };
    const crossings=[];
    segments.forEach((one,i)=>segments.slice(i+1).forEach((other,j)=>{
      if(one.some(a=>other.some(b=>meets(a,b))))crossings.push([leaders[i].id,leaders[i+1+j].id]);
    }));
    resolve({count:notes.length,compact:map.classList.contains('compact'),overlap,leaders,crossings,
      scale:map.dataset.scale||'0',
      smallest:Math.min(...notes.map(n=>parseFloat(getComputedStyle(n.querySelector('p')).fontSize))),
      frames:document.querySelectorAll('.flight-map-frame').length,
      within:boxes.every(r=>r.left>=0&&r.right<=innerWidth),
      vertically:map.classList.contains('compact')||boxes.every(r=>r.top>=0&&r.bottom<=innerHeight),
      copy:notes.every(n=>n.querySelector('p').textContent===OrreryTour.MAP_NOTES.find(s=>s.id===n.dataset.step).copy)});
  }));
})"""


# A smaller window keeps the leaders and sets the notes smaller, in steps; the
# smallest step's text is 9px (1200x680 needs it).
@pytest.mark.parametrize('width,height,scale,text', [
    (1920, 1080, '0', 12), (1600, 1000, '0', 12), (1440, 900, '0', 12),
    (1400, 860, '1', 10.5), (1280, 800, '1', 10.5), (1200, 680, '3', 9)])
def test_dom_map_annotates_every_control_with_a_leader(tour_browser, width, height, scale, text):
    client, evaluate = tour_browser
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
    result = evaluate(MAP_LAYOUT)
    assert result['compact'] is False, result
    assert (result['scale'], result['smallest']) == (scale, text)
    assert (result['count'], result['frames'], result['overlap'], result['within'], result['vertically'], result['copy']) == (10, 10, False, True, True, True)
    assert sorted(l['id'] for l in result['leaders']) == sorted(['start', 'select', 'choose', 'talk', 'mail', 'crew', 'usage', 'telemetry', 'planetarium', 'settings'])
    assert all(l['fromTarget'] and l['toNote'] for l in result['leaders']), result['leaders']
    assert result['crossings'] == [], result['crossings']


def test_dom_map_never_draws_crossing_leaders_while_the_window_changes(tour_browser):
    """Review of #25: at 1160px the header's Settings wraps onto two lines and
    its leader's track passed its neighbour's, so two leaders crossed at the
    smallest step. A layout whose leaders cross is not used; the sweep covers
    1160 and the steps on either side of it."""
    client, evaluate = tour_browser
    seen, bad = set(), []
    for width in range(1120, 1441, 40):
        for height in (660, 720, 800, 880, 940):
            client.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
            result = evaluate(MAP_LAYOUT)
            seen.add('legend' if result['compact'] else 'scale' + result['scale'])
            ok = not result['crossings'] and (result['compact'] or (
                not result['overlap'] and result['within'] and result['vertically']
                and all(l['fromTarget'] and l['toNote'] for l in result['leaders'])))
            if not ok:
                bad.append((width, height, result['scale'], result['crossings']))
    assert bad == []
    # The sweep passes through every size of the map, and the legend.
    assert seen >= {'scale0', 'scale1', 'scale2', 'scale3', 'legend'}, seen


def test_crossing_leaders_are_told_apart_from_meeting_ones():
    assert node(f"""const t=require({json.dumps(str(BRIDGE / 'cockpit_tour.js'))});
      console.log(JSON.stringify([
        t.leadersCross(['M10,0V50H100','M0,20H150']),
        t.leadersCross(['M10,0V50H100','M110,20H150']),
        t.leadersCross(['M10,10H100','M50,10H150']),
        t.leadersCross(['M10,10H100','M100,10V50'])]));""") == [True, False, True, False]


@pytest.mark.parametrize('width,height', [(1100, 700), (980, 800), (420, 800)])
def test_dom_map_falls_back_to_a_legend_when_leaders_do_not_fit(tour_browser, width, height):
    client, evaluate = tour_browser
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
    result = evaluate(MAP_LAYOUT)
    assert (result['compact'], result['count'], result['leaders'], result['overlap'], result['within'], result['copy']) == (True, 10, [], False, True, True)
    # The legend keeps the full-size notes: no step is left set from the attempts.
    assert result['scale'] == '0'


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


def test_dom_a_step_is_chosen_by_click_or_key_and_only_actions_complete_it(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      const flight=OrreryTour.firstFlight,el=flight.el;flight.reset();
      const line=id=>el.querySelector('li[data-step="'+id+'"] .flight-line');
      const current=()=>el.querySelector('li[aria-current="step"]').dataset.step;
      line('mail').click();
      const clicked={current:current(),done:OrreryTour.state.done.size,
        targeted:document.querySelector('#mail').classList.contains('flight-target'),
        band:el.querySelector('.flight-band .flight-item').textContent};
      line('choose').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
      const keyed=current();
      document.dispatchEvent(new CustomEvent('oc:tour-action',{detail:{id:'start'}}));
      const doneLine=line('start');
      return {clicked,keyed,doneTab:doneLine.tabIndex,doneDisabled:doneLine.getAttribute('aria-disabled'),
        openTab:line('talk').tabIndex,openLabel:line('talk').getAttribute('aria-label'),
        currentDisabled:line('choose').getAttribute('aria-disabled')};
    })()""")
    assert result == {
        'clicked': {'current': 'mail', 'done': 0, 'targeted': True, 'band': 'Read Agent Mail'},
        'keyed': 'choose', 'doneTab': -1, 'doneDisabled': 'true',
        'openTab': 0, 'openLabel': 'Go to step: Talk to it', 'currentDisabled': 'true'}


RING_STATE = """(()=>{
  const ring=document.querySelector('.flight-ring:not([hidden])'),here=document.querySelector('.flight-here:not([hidden])');
  if(!ring)return {ring:false,here:!!here};
  const rect=el=>{const r=el.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom};};
  // The ring stays inside the window: compare with the control's visible part.
  const target=document.querySelector('.flight-target'),g=rect(ring),c=rect(target);
  const t={l:Math.max(2,c.l),t:Math.max(2,c.t),r:Math.min(innerWidth-2,c.r),b:Math.min(innerHeight-2,c.b)};
  // The panel's words and buttons; its empty top strip may hold the tag.
  const panels=[...document.querySelectorAll('.flight-guide:not([hidden]) .flight-panel :is(h2,button,.flight-meta,li)')]
    .filter(e=>e.getBoundingClientRect().width>0).map(rect);
  const h=here&&rect(here);
  return {ring:true,target:target.id||target.className,
    around:g.l<=t.l&&g.t<=t.t&&g.r>=t.r&&g.b>=t.b,
    colour:getComputedStyle(ring).borderTopColor,
    pulse:getComputedStyle(ring,'::after').animationName,
    here:!!here,label:here&&here.textContent,
    hereOnScreen:!h||(h.l>=0&&h.t>=0&&h.r<=innerWidth&&h.b<=innerHeight),
    hereClearOfPanel:!h||!panels.some(p=>h.l<p.r&&h.r>p.l&&h.t<p.b&&h.b>p.t)};
})()"""


def test_dom_the_next_control_gets_a_cyan_ring_and_a_here_tag(tour_browser):
    client, evaluate = tour_browser
    evaluate("OrreryTour.firstFlight.reset();OrreryTour.firstFlight.show()")
    shown = evaluate(RING_STATE)
    # Below NEW AGENT is the roster filter, which the tag must not cover.
    assert shown == {'ring': True, 'target': 'newAgentBtn', 'around': True, 'colour': 'rgb(63, 210, 230)',
                     'pulse': 'flight-ring-pulse', 'here': True, 'label': '◀ HERE',
                     'hereOnScreen': True, 'hereClearOfPanel': True}
    # Light theme: a darker cyan that holds on paper.
    light = evaluate("document.documentElement.dataset.colorTheme='light';" + RING_STATE)
    evaluate("delete document.documentElement.dataset.colorTheme")
    assert light['colour'] == 'rgb(10, 143, 163)'
    # Reduced motion: the ring stays, without the pulse.
    client.call('Emulation.setEmulatedMedia', features=[{'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    try:
        still = evaluate(RING_STATE)
    finally:
        client.call('Emulation.setEmulatedMedia', features=[])
    assert (still['ring'], still['pulse']) == (True, 'none')


def test_dom_the_here_arrow_always_matches_the_side_it_is_on(tour_browser):
    """Review of #26: the tag was placed by its empty size ("below", ▲), moved
    above once measured with its text, and kept ▲ until the next check. A
    checklist whose panel sits just below and right of NEW AGENT shows it at
    once."""
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      OrreryTour.firstFlight.el.querySelector('.flight-close').click();
      const t=document.getElementById('newAgentBtn').getBoundingClientRect();
      localStorage.setItem('oc-review-pointer-pos',JSON.stringify({left:(t.left+t.right)/2+22,top:t.bottom+12}));
      const qa=OrreryTour.mountChecklist({id:'qa-pointer',title:'QA',storageKey:'oc-review-pointer',autoOpen:true,
        steps:[{id:'start',title:'Start',target:'#newAgentBtn',copy:'Test'}]});
      const ring=document.querySelector('.flight-ring:not([hidden])').getBoundingClientRect();
      const here=[...document.querySelectorAll('.flight-here:not([hidden])')].pop(),b=here.getBoundingClientRect();
      const actual=b.bottom<=ring.top?'above':b.top>=ring.bottom?'below':b.left>=ring.right?'right':'left';
      const out={label:here.textContent,side:here.dataset.side,actual};
      qa.destroy();localStorage.removeItem('oc-review-pointer-pos');localStorage.removeItem('oc-review-pointer');
      return out;
    })()""")
    arrow = {'below': '▲ HERE', 'above': '▼ HERE', 'right': '◀ HERE', 'left': 'HERE ▶'}
    assert result['side'] == result['actual'], result
    assert result['label'] == arrow[result['actual']], result


def test_dom_the_ring_leaves_a_covered_or_folded_control(tour_browser):
    _, evaluate = tour_browser
    evaluate("OrreryTour.firstFlight.reset();OrreryTour.firstFlight.show()")
    covered = evaluate("openSpawnModal();OrreryTour.firstFlight.el.dispatchEvent(new Event('x'));" + RING_STATE.replace("(()=>{", "(()=>{document.dispatchEvent(new Event('scroll'));", 1))
    evaluate("closeSpawnModal(true)")
    folded = evaluate("OrreryTour.firstFlight.el.querySelector('.flight-fold').click();" + RING_STATE)
    evaluate("OrreryTour.firstFlight.el.querySelector('.flight-band').click()")
    assert covered == {'ring': False, 'here': False}
    assert folded == {'ring': False, 'here': False}


def test_dom_a_control_under_the_tour_panel_keeps_its_ring(tour_browser):
    # Agent Mail sits under the panel; the panel is the tour's, not a dialog.
    _, evaluate = tour_browser
    state = evaluate("(()=>{const f=OrreryTour.firstFlight;f.reset();f.show();f.state.goTo('mail');f.show();})();" + RING_STATE)
    assert (state['ring'], state['target'], state['around'], state['hereClearOfPanel']) == (True, 'mail', True, True)


def test_dom_a_control_under_the_tour_panel_gets_no_here_tag(tour_browser):
    # The recording showed the tag for Agent Mail on the terminal's input line.
    _, evaluate = tour_browser
    state = evaluate("(()=>{const f=OrreryTour.firstFlight;f.reset();f.show();f.state.goTo('mail');f.show();})();" + RING_STATE)
    assert (state['ring'], state['here']) == (True, False)


@pytest.mark.parametrize('step', ['full-planetarium', 'full-telemetry', 'full-split', 'full-usage'])
def test_dom_the_here_tag_covers_no_control_brand_clock_or_terminal(tour_browser, step):
    # The recording showed it on the brand, the clock and the next button.
    _, evaluate = tour_browser
    covered = evaluate("""(()=>{OrreryTour.firstFlight.el.querySelector('.flight-close').click();
      const t=OrreryFullTour.checklist;t.state.reset();t.show();t.state.goTo(%s);t.show();
      const here=document.querySelector('.flight-here:not([hidden])');
      if(!here)return [];
      const b=here.getBoundingClientRect(),hits=new Set();
      for(const x of [b.left+2,(b.left+b.right)/2,b.right-2])for(const y of [b.top+2,(b.top+b.bottom)/2,b.bottom-2]){
        const e=document.elementFromPoint(x,y);
        const c=e&&e.closest('button,a[href],input,textarea,select,[role="button"],.brand,.clock,.topstat,.termhost');
        if(c)hits.add(c.id||c.className);
      }
      return [...hits];})()""" % json.dumps(step))
    assert covered == []


@pytest.mark.parametrize('step,target', [('full-planetarium', 'planetariumBtn'), ('full-telemetry', 'networkBtn')])
def test_dom_a_small_header_button_still_gets_its_tag(tour_browser, step, target):
    # Its neighbours are buttons and the clock, and below it is the panel:
    # the tag goes in the panel's empty top strip, clear of its words.
    _, evaluate = tour_browser
    state = evaluate("""(()=>{OrreryTour.firstFlight.el.querySelector('.flight-close').click();
      const t=OrreryFullTour.checklist;t.state.reset();t.show();t.state.goTo(%s);t.show();})();""" % json.dumps(step) + RING_STATE)
    assert (state['target'], state['here'], state['label'], state['hereClearOfPanel']) == (target, True, '▲ HERE', True)


def test_dom_the_shiritori_step_rings_where_the_prompt_is_sent(tour_browser):
    # Agent Mail lies under the panel; the step's action is sending the prompt.
    _, evaluate = tour_browser
    state = evaluate("""(()=>{OrreryTour.firstFlight.el.querySelector('.flight-close').click();
      const t=OrreryFullTour.checklist;t.state.reset();t.show();t.state.goTo('full-shiritori');t.show();})();""" + RING_STATE)
    assert (state['ring'], state['target'], state['around']) == (True, 'promptInput', True)


def test_dom_a_target_that_fills_the_window_gets_no_ring(tour_browser):
    # The Telemetry steps point at the whole overlay: nothing to ring.
    _, evaluate = tour_browser
    state = evaluate("""(()=>{OrreryTour.firstFlight.el.querySelector('.flight-close').click();
      const t=OrreryFullTour.checklist;t.state.reset();t.show();t.state.goTo('full-exit');t.show();
      openNetwork({focus:''});t.show();})();""" + RING_STATE)
    evaluate("closeNetwork()")
    assert state == {'ring': False, 'here': False}


def test_dom_the_full_tour_points_the_same_way(tour_browser):
    _, evaluate = tour_browser
    state = evaluate("""(()=>{OrreryTour.firstFlight.el.querySelector('.flight-close').click();
      const t=OrreryFullTour.checklist;t.state.reset();t.show();t.state.goTo('full-telemetry');t.show();})();""" + RING_STATE)
    assert (state['ring'], state['target'], state['around'], state['hereOnScreen'], state['hereClearOfPanel']) == (
        True, 'networkBtn', True, True, True)


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
    client.call('Page.navigate', url=evaluate.base + '/tour.html?tour=review-later-tour')
    for _ in range(100):
        if evaluate("Boolean(window.OrreryTour&&OrreryTour.mountChecklist&&document.readyState==='complete')"):
            break
        time.sleep(.1)
    result = evaluate("""(()=>{
      const before=document.querySelectorAll('.flight-guide').length;
      const later=OrreryTour.mountChecklist({id:'review-later-tour',title:'Later tour',storageKey:'oc-test-review-later-tour',
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
  window.appCalls=[];window.appClosed=null;window.appKnobs={listenMs:0,listenFails:false,closeAfterMs:null,closeDuringOpen:false,windowExists:true,existsMs:0};
  const closeNotice={payload:{tour:'first-flight',url:location.origin+'/tour.html?tour=first-flight'}};
  let handler=null;
  const emit=()=>{if(handler)handler(closeNotice);};
  window.appEmitClose=emit;
  window.__TAURI__={core:{invoke:(name,args)=>{appCalls.push([name,args]);
      if(!window.appHasTourWindows)return Promise.reject('Command '+name+' not found');
      if(name==='open_tour_window'&&appKnobs.closeDuringOpen)emit();
      if(name==='open_tour_window'&&appKnobs.closeAfterMs!==null)setTimeout(emit,appKnobs.closeAfterMs);
      if(name==='tour_window_exists'){const answer=appKnobs.windowExists;return new Promise(r=>setTimeout(()=>r(answer),appKnobs.existsMs));}
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


def test_dom_stale_window_answer_does_not_undo_a_reopened_window(tour_browser):
    """Review of #15 (P3): a slow "no window" answer from before a reopen."""
    _, evaluate = tour_browser
    evaluate(FAKE_APP)
    result = evaluate("""(async()=>{
      window.appHasTourWindows=true;
      const flight=OrreryTour.firstFlight,wait=ms=>new Promise(r=>setTimeout(r,ms));flight.reset();
      flight.el.querySelector('.flight-popout').click();
      await wait(50);
      appKnobs.windowExists=false;appKnobs.existsMs=600;   // the next check answers late, about the old window
      await wait(2100);
      appEmitClose();appKnobs.windowExists=true;          // closed, then opened again before that answer
      flight.el.querySelector('.flight-popout').click();
      await wait(100);
      const reopened=flight.el.hidden;
      await wait(700);                                     // the stale "no window" answer has arrived
      return {reopened,stillOut:flight.el.hidden};
    })()""")
    assert result == {'reopened': True, 'stillOut': True}

