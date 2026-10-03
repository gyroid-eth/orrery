"""Full-tour order, trusted iframe messages and observed parent/child rounds."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_cockpit_tour import tour_browser

MODULE = Path(__file__).resolve().parents[1] / 'cockpit_full_tour.js'


def run(script):
    if not shutil.which('node'):
        pytest.skip('node unavailable')
    result = subprocess.run(['node', '-e', f'const tour=require({json.dumps(str(MODULE))});' + script],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_selected_order_and_exact_workshop_rules_are_present():
    result = run("console.log(JSON.stringify({ids:tour.STEPS.map(s=>s.id),prompt:tour.SHIRITORI_PROMPT}));")
    assert result['ids'] == ['full-start', 'full-choose', 'full-talk', 'full-shiritori',
                             'full-split', 'full-drag', 'full-planetarium', 'full-usage',
                             'full-telemetry', 'full-exit', 'full-edge', 'full-select',
                             'full-replay', 'full-resume', 'full-network-settings', 'full-return']
    for requirement in ['/delegate', 'ORRERY Mail (send_message)', 'exactly three round trips',
                        'shiritori ready', 'りんご', 'never Haiku', 'Do not use --worktree',
                        'Do not use Claude Code\'s built-in Agent or SendMessage',
                        'observed Mail ID', 'no new game']:
        assert requirement in result['prompt']


def test_telemetry_messages_require_owned_frame_origin_version_and_action():
    assert run("""
      const frame={},other={},origin='http://local:9876';
      const event={source:frame,origin,data:{type:'orrery-tour-action',version:1,action:'exit'}};
      const values=[tour.telemetryAction(event,origin,frame),
        tour.telemetryAction({...event,source:other},origin,frame),
        tour.telemetryAction({...event,origin:'https://elsewhere'},origin,frame),
        tour.telemetryAction({...event,data:{...event.data,version:2}},origin,frame),
        tour.telemetryAction({...event,data:{...event.data,action:'__proto__'}},origin,frame),
        tour.telemetryAction(event,origin,null)];
      console.log(JSON.stringify(values));
    """) == ['full-exit', None, None, None, None, None]


def test_first_actual_round_must_be_between_parent_and_same_child():
    assert run("""
      const t=tour.createShiritoriTracker('Parent',1000000);
      const agents=[{name:'Child',parent:'Parent'},{name:'Other',parent:'Someone'}];
      const ready={id:1,ts:1001,sender:'Child',recipient:'Parent',subject:'shiritori ready'};
      const out={id:2,ts:1002,sender:'Parent',recipient:'Child',subject:'shiritori round 1'};
      const reply={id:3,ts:1003,sender:'Child',recipients:[{name:'Parent'}],subject:'Re: shiritori round 1'};
      const unrelated={...reply,id:4,sender:'Other'};
      const progress=[t.add([ready],agents),t.add([out],agents),t.add([unrelated],agents),
        t.add([reply],agents),t.add([out,reply],agents)];
      console.log(JSON.stringify(progress));
    """) == [False, False, False, True, True]


def test_old_missing_time_wrong_round_and_different_children_do_not_count():
    assert run("""
      const agents=[{name:'C1',parent:'P'},{name:'C2',parent:'P'}];
      const out={id:1,ts:1001,sender:'P',recipient:'C1',subject:'shiritori round 1'};
      const reply={id:2,ts:1002,sender:'C1',recipient:'P',subject:'shiritori round 1'};
      const results=[];
      for(const bad of [{...reply,ts:999},{...reply,ts:null},
        {...reply,subject:'shiritori round 2'},{...reply,sender:'C2'}, {...reply,id:1}]){
        const t=tour.createShiritoriTracker('P',1000000);
        results.push(t.add([out,bad],agents));
      }
      console.log(JSON.stringify(results));
    """) == [False, False, False, False, False]


def test_observation_accepts_iso_time_and_delayed_lineage():
    assert run("""
      const t=tour.createShiritoriTracker('P',Date.parse('2026-10-04T00:00:00Z'));
      const mails=[{id:1,created_ts:'2026-10-04T00:00:02Z',sender:'P',recipient:'C',subject:'shiritori round 1'},
        {id:2,created_ts:'2026-10-04T00:00:03Z',sender:'C',recipient:'P',subject:'shiritori round 1'}];
      console.log(JSON.stringify([t.add(mails,[]),t.add(mails,[{name:'C',parent:'P'}])]));
    """) == [False, True]


def test_dom_full_tour_is_separate_and_restart_preserves_first_flight(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      const first=OrreryTour.firstFlight,full=OrreryFullTour.checklist;
      first.mark('start');document.getElementById('fullTourBtn').click();
      full.mark('full-start');full.fold();
      const folded=full.el.classList.contains('folded');
      full.el.querySelector('.flight-band').click();
      const expanded=!full.el.classList.contains('folded');
      full.el.querySelector('.flight-restart').click();
      return {folded,expanded,rows:full.el.querySelectorAll('[data-step]').length,
        first:[...first.state.done],empty:full.state.done.size===0,
        firstClosed:!first.state.open,fullOpen:full.state.open};
    })()""")
    assert result == {'folded': True, 'expanded': True, 'rows': 16, 'first': ['start'],
                      'empty': True, 'firstClosed': True, 'fullOpen': True}


def test_dom_telemetry_notifications_require_owned_frame_and_current_step(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      const full=OrreryFullTour.checklist;document.getElementById('fullTourBtn').click();
      full.state.steps.slice(0,9).forEach(s=>full.mark(s.id));
      const frame=document.getElementById('networkFrame').contentWindow;
      function post(action,source=frame,origin=location.origin,version=1){
        window.dispatchEvent(new MessageEvent('message',{source,origin,
          data:{type:'orrery-tour-action',version,action}}));
      }
      post('edge');post('exit',window);post('exit',frame,'https://other.test');post('exit',frame,location.origin,2);
      const rejected=full.state.current.id;
      post('exit');const accepted=full.state.current.id;
      post('settings');post('return');const noSkip=full.state.current.id;
      return {rejected,accepted,noSkip,done:full.state.done.size};
    })()""")
    assert result == {'rejected': 'full-exit', 'accepted': 'full-edge',
                      'noSkip': 'full-edge', 'done': 10}


def test_dom_return_waits_for_handoff_and_matching_terminal_focus(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      const full=OrreryFullTour.checklist;document.getElementById('fullTourBtn').click();
      full.state.steps.slice(0,15).forEach(s=>full.mark(s.id));
      const frame=document.getElementById('networkFrame').contentWindow;
      window.dispatchEvent(new MessageEvent('message',{source:frame,origin:location.origin,
        data:{type:'orrery-tour-action',version:1,action:'return'}}));
      const notificationOnly=full.state.current.id;
      document.dispatchEvent(new CustomEvent('oc:telemetry-return',{detail:{name:'Pilot'}}));
      document.dispatchEvent(new CustomEvent('oc:focus-agent',{detail:{name:'Other'}}));
      const unrelated=full.state.current.id;
      document.getElementById('networkOverlay').classList.add('on');
      document.dispatchEvent(new CustomEvent('oc:focus-agent',{detail:{name:'Pilot'}}));
      const stillInTelemetry=full.state.current.id;
      document.getElementById('networkOverlay').classList.remove('on');
      document.dispatchEvent(new CustomEvent('oc:focus-agent',{detail:{name:'Pilot'}}));
      return {notificationOnly,unrelated,stillInTelemetry,complete:full.state.current===null};
    })()""")
    assert result == {'notificationOnly': 'full-return', 'unrelated': 'full-return',
                      'stillInTelemetry': 'full-return', 'complete': True}


def test_dom_full_popup_loads_current_definition_without_injected_mount(tour_browser):
    import contextlib
    import time
    import urllib.request
    from tools.theme_axis_browser_test import _WebSocket
    client, evaluate = tour_browser
    before = {t['id'] for t in json.load(urllib.request.urlopen(evaluate.endpoint + '/json/list'))}
    evaluate("document.getElementById('fullTourBtn').click();localStorage.setItem('oc-tour-definition:full-tour',JSON.stringify({id:'full-tour',title:'Stale title',steps:[{id:'old',title:'Stale step'}],storageKey:'oc-full-tour-v1'}))")
    client.call('Runtime.evaluate', expression="OrreryFullTour.checklist.el.querySelector('.flight-popout').click()", userGesture=True)
    popup = None
    try:
        for _ in range(50):
            tabs = json.load(urllib.request.urlopen(evaluate.endpoint + '/json/list'))
            popup = next((t for t in tabs if t['id'] not in before and 'tour=full-tour' in t['url']), None)
            if popup:
                break
            time.sleep(.1)
        assert popup, 'the real pop-out control did not open its dedicated page'
        other = _WebSocket(popup['webSocketDebuggerUrl'])

        def read(expression):
            result = other.call('Runtime.evaluate', expression=expression, returnByValue=True)
            assert 'exceptionDetails' not in result, result
            return result.get('result', {}).get('value')

        for _ in range(100):
            if read('Boolean(window.OrreryFullTour?.checklist)'):
                break
            time.sleep(.1)
        assert read("({title:document.querySelector('h2').textContent,rows:document.querySelectorAll('[data-step]').length,solo:OrreryFullTour.checklist.solo,noCockpit:typeof OC==='undefined',guides:document.querySelectorAll('.flight-guide').length})") == {
            'title': 'Full tour', 'rows': 16, 'solo': True, 'noCockpit': True, 'guides': 1}
        evaluate("OrreryFullTour.checklist.mark('full-start')")
        for _ in range(50):
            if read("OrreryFullTour.checklist.state.done.has('full-start')"):
                break
            time.sleep(.1)
        assert read("OrreryFullTour.checklist.state.done.has('full-start')")
        assert evaluate('OrreryFullTour.checklist.el.hidden')
    finally:
        if popup:
            with contextlib.suppress(OSError):
                urllib.request.urlopen(evaluate.endpoint + '/json/close/' + popup['id'])
