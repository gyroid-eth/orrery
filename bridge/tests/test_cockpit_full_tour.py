"""Full-tour order, trusted iframe messages and observed parent/child rounds."""
import hashlib
import json
import re
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


@pytest.mark.parametrize('program', ['claude-code', 'claude', None, 'unknown'])
def test_claude_and_unknown_program_keep_the_original_prompt_bytes(program):
    result = run("console.log(JSON.stringify({prompt:tour.getShiritoriPrompt(PROGRAM),legacy:tour.SHIRITORI_PROMPT}));"
                 .replace('PROGRAM', json.dumps(program)))
    assert result['prompt'] == result['legacy']
    # Digest of the original public prompt before provider selection was added.
    assert hashlib.sha256(result['prompt'].encode()).hexdigest() == 'ffa84516bdb0f17e4995d3679c5821d993a26c3ddc9996175cc0bca3e6851ade'


@pytest.mark.parametrize('program', ['codex', 'codex-cli'])
def test_codex_prompt_uses_the_installed_delegate_skill_without_slash_commands(program):
    prompt = run("console.log(JSON.stringify(tour.getShiritoriPrompt(PROGRAM)));"
                 .replace('PROGRAM', json.dumps(program)))
    assert prompt.startswith('$delegate ')
    assert '/delegate' not in prompt
    assert 'Use the $delegate skill (the installed ORRERY delegate skill)' in prompt
    original = run('console.log(JSON.stringify(tour.SHIRITORI_PROMPT));')
    assert prompt == original.replace('/delegate ', '$delegate ', 1).replace(
        'Use /delegate to create the child',
        'Use the $delegate skill (the installed ORRERY delegate skill) to create the child')


def test_only_both_exact_workshop_prompts_are_replaceable_drafts():
    assert run("""
      const claude=tour.SHIRITORI_PROMPT,codex=tour.getShiritoriPrompt('codex');
      console.log(JSON.stringify([claude,codex,'custom draft',claude+' edited',codex+' edited']
        .map(tour.isShiritoriPrompt)));
    """) == [True, True, False, False, False]


@pytest.mark.parametrize('program', ['claude-code', 'codex', 'codex-cli'])
def test_dom_workshop_button_uses_context_parent_and_preserves_custom_drafts(tour_browser, program):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      currentAgents=[{name:'Parent',program:PROGRAM},{name:'Other',program:'claude-code'}];
      activeId='parent';panes.set('parent',{session:'Parent'});
      const full=OrreryFullTour.checklist;full.reset();full.show();
      full.state.goTo('full-shiritori');full.show();
      const button=full.el.querySelector('[data-step="full-shiritori"] button.flight-read');
      const input=document.getElementById('promptInput'),expected=OrreryFullTour.getShiritoriPrompt(PROGRAM);
      const replaced=['', '  ', OrreryFullTour.SHIRITORI_PROMPT, OrreryFullTour.getShiritoriPrompt('codex')].map(draft=>{
        input.value=draft;button.click();return input.value===expected;
      });
      input.value='my unsent draft';button.click();const preserved=input.value;
      activeId='other';panes.set('other',{session:'Other'});input.value='';button.click();
      return {replaced,preserved,otherInput:input.value,
        saved:JSON.parse(localStorage.getItem('oc-full-tour-shiritori-v1')).program};
    })()""".replace('PROGRAM', json.dumps(program)))
    assert result == {'replaced': [True]*4, 'preserved': 'my unsent draft',
                      'otherInput': '', 'saved': program}


@pytest.mark.parametrize('program,label,prefix', [('codex', 'Codex', '$delegate '),
    ('codex-cli', 'Codex', '$delegate '), ('claude-code', 'Claude', '/delegate '),
    (None, 'Claude', '/delegate ')])
def test_dom_solo_copy_uses_saved_parent_program_or_labelled_claude_default(tour_browser, program, label, prefix):
    import time
    client, evaluate = tour_browser
    evaluate("localStorage.setItem('oc-full-tour-shiritori-v1',JSON.stringify({parent:'Parent',since:Date.now(),program:PROGRAM}))"
             .replace('PROGRAM', json.dumps(program)))
    client.call('Page.navigate', url=evaluate.base+'/tour.html?tour=full-tour')
    for _ in range(100):
        if evaluate('Boolean(window.OrreryFullTour?.checklist?.solo)'):
            break
        time.sleep(.1)
    result = evaluate("""(async()=>{
      const full=OrreryFullTour.checklist;full.show();
      full.state.goTo('full-shiritori');full.show();
      const button=full.el.querySelector('[data-step="full-shiritori"] button.flight-read');
      const label=button.textContent;let copied=null;
      Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{copied=text;}}});
      button.click();await new Promise(r=>setTimeout(r,0));
      return {label,copied,noCockpit:typeof OC==='undefined'};
    })()""")
    assert result['label'] == 'Copy workshop prompt · '+label
    assert result['copied'].startswith(prefix)
    assert result['noCockpit']


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
      const ready={id:1,ts:1001,sender:'Child',recipient:'Parent',subject:'shiritori ready',body:'Ready'};
      const out={id:2,ts:1002,sender:'Parent',recipient:'Child',subject:'shiritori round 1'};
      const reply={id:3,ts:1003,sender:'Child',recipients:[{name:'Parent'}],subject:'Re: shiritori round 1'};
      const unrelated={...reply,id:4,sender:'Other'};
      const progress=[t.add([ready],agents),t.add([out],agents),t.add([unrelated],agents),
        t.add([reply],agents),t.add([out,reply],agents)];
      console.log(JSON.stringify(progress));
    """) == [False, False, False, True, True]


def test_old_missing_time_reverse_order_and_different_children_do_not_count():
    assert run("""
      const agents=[{name:'C1',parent:'P'},{name:'C2',parent:'P'}];
      const out={id:1,ts:1001,sender:'P',recipient:'C1',subject:'shiritori round 1'};
      const reply={id:2,ts:1002,sender:'C1',recipient:'P',subject:'shiritori round 1'};
      const results=[];
      for(const bad of [{...reply,ts:999},{...reply,ts:null},
        {...reply,ts:1000.5},{...reply,sender:'C2'}, {...reply,id:1}]){
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


@pytest.mark.parametrize('native,success,expected', [(True, True, 1), (True, False, 0),
                                                   (False, True, 1), (False, False, 0)])
def test_drag_window_completion_waits_for_successful_creation(native, success, expected):
    html = (MODULE.parent / 'cockpit.html').read_text()
    function = re.search(r'function openPaneWindow\(.*?(?=\nfunction popSessionToWindow)', html, re.S).group()
    native_handler = '()=>Promise.resolve()' if success else '()=>Promise.reject(Error("refused"))'
    script = """
      let calls=0;
      const screen={},paneScope='test',location={href:'http://local'};
      globalThis.window={open:()=>WINDOW_RESULT};
      const paneWindowGeometry=()=>({}),paneWindowUrl=()=>'',paneWindowName=()=>'';
      const paneWindows=new Map(),showToast=()=>{},returnPaneSession=()=>{};
    """.replace('WINDOW_RESULT', '({})' if success else 'null')
    script += 'const appInvoke=()=>'+('('+native_handler+')' if native else 'null')+';'
    script += function + """
      openPaneWindow('Pilot',{onOpened:()=>calls++});
      setTimeout(()=>console.log(JSON.stringify(calls)),0);
    """
    assert run(script) == expected


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


def test_dom_telemetry_steps_tell_the_embedded_page_which_control_to_ring(tour_browser):
    """The cockpit cannot ring a control inside the embedded Telemetry; it
    sends the step (orrery-telemetry dashboard/tour_cue.js draws the ring),
    only while a Telemetry step is current and the overlay is open."""
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      const full=OrreryFullTour.checklist;document.getElementById('fullTourBtn').click();
      full.state.reset();full.show();full.state.goTo('full-exit');full.show();
      openNetwork({focus:''});
      const sent=[],frame=document.getElementById('networkFrame').contentWindow;
      frame.postMessage=(message,origin)=>sent.push({...message,origin});
      OrreryFullTour.sendCue(true);
      full.state.goTo('full-telemetry');full.show();
      full.state.goTo('full-edge');full.show();
      // Closing is seen by a MutationObserver; ask for the same check now.
      closeNetwork();OrreryFullTour.sendCue();
      // The page also gets its other messages (net-pause, the theme); keep the cue.
      return sent.filter(m=>m&&m.type==='orrery-tour-cue').map(m=>({type:m.type,version:m.version,step:m.step,origin:m.origin===location.origin,
        avoid:m.avoid.length,avoidOk:m.avoid.every(a=>a.r>a.l&&a.b>a.t)}));
    })()""")
    assert [r['step'] for r in result] == ['full-exit', None, 'full-edge', None], result
    assert all(r['type'] == 'orrery-tour-cue' and r['version'] == 1 and r['origin'] for r in result)
    # The checklist over the page is passed on, so the tag keeps clear of it.
    assert result[0]['avoid'] == 1 and result[0]['avoidOk'] and result[1]['avoid'] == 0


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


def test_dom_restart_forgets_an_earlier_pending_agent_choice(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      const full=OrreryFullTour.checklist;document.getElementById('fullTourBtn').click();
      full.mark('full-start');
      document.dispatchEvent(new CustomEvent('oc:tour-action',{detail:{id:'choose',name:'OldPending'}}));
      full.reset();full.mark('full-start');
      document.dispatchEvent(new CustomEvent('oc:focus-agent',{detail:{name:'OldPending'}}));
      return full.state.current.id;
    })()""")
    assert result == 'full-choose'


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


@pytest.mark.parametrize('subject', [None, 'ごりら (gorira, gorilla)', 'Re: りんご', 'shiritori round 2'])
def test_free_reply_subject_and_reply_message_metadata_count(subject):
    script = """
      const t=tour.createShiritoriTracker('P',1000000),agents=[{name:'C',parent:'P'}];
      const out={id:10,ts:1001,sender:'P',recipient:'C',body:'りんご'};
      const reply={id:11,ts:1002,sender:'C',recipient:'P',body_md:'Round 1: ごりら',thread_id:'game',reply_to:10,subject:SUBJECT};
      console.log(JSON.stringify(t.add([reply,out],agents)));
    """.replace('SUBJECT', json.dumps(subject))
    assert run(script) is True


def test_the_tracker_names_the_child_that_played_a_full_round():
    # The Network edge step rings that pair's edge, not the first edge drawn.
    assert run("""
      const t=tour.createShiritoriTracker('P',1000000),agents=[{name:'C',parent:'P'},{name:'D',parent:'P'}];
      const before=t.child();
      t.add([{id:10,ts:1001,sender:'P',recipient:'D',body:'りんご'}],agents);
      const half=t.child();
      t.add([{id:11,ts:1002,sender:'P',recipient:'C',body:'りんご'},{id:12,ts:1003,sender:'C',recipient:'P',body:'ごりら'}],agents);
      console.log(JSON.stringify([before,half,t.child()]));
    """) == [None, None, 'C']


@pytest.mark.parametrize('kind,success,expected', [('float', True, 1), ('browser', True, 1),
    ('browser', False, 0), ('native', True, 1), ('native', False, 0)])
def test_owned_pane_focus_notifies_only_after_actual_success(kind, success, expected):
    html = (MODULE.parent / 'cockpit.html').read_text()
    functions = re.search(r'const pendingPaneFocus=new Map\(\);.*?(?=\n/\* own window:)', html, re.S).group()
    script = """
      let events=0,requests=[];
      const paneScope='scope',paneWindows=new Map();
      const document={dispatchEvent:()=>events++};
      class CustomEvent{constructor(type,options){this.detail=options.detail;}}
      const raisePaneFloat=()=>{},paneMessageInScope=(m,s)=>m.scope===s;
      const postPaneMessage=m=>requests.push(m);
      const entry=ENTRY;paneWindows.set('P',entry);
      const appInvoke=()=>INVOKE;
    """.replace('ENTRY', {'float':"{kind:'float',el:{}}", 'browser':
        "{kind:'window',win:{closed:false,focus:()=>FOCUS}}".replace('FOCUS', '{}' if success else "{throw Error('refused')}"),
        'native':"{kind:'window',instance:'child'}"}[kind]).replace('INVOKE',
        ('()=>Promise.resolve()' if success else '()=>Promise.reject(Error("refused"))') if kind == 'native' else 'null')
    script += functions + "focusPaneWindow('P');setTimeout(()=>console.log(JSON.stringify(events)),0);"
    assert run(script) == expected


def test_channel_focus_ack_requires_requested_scope_instance_and_nonce():
    html = (MODULE.parent / 'cockpit.html').read_text()
    functions = re.search(r'const pendingPaneFocus=new Map\(\);.*?(?=\n/\* own window:)', html, re.S).group()
    assert run("""
      let events=0,request;
      const paneScope='ours',paneWindows=new Map([['P',{kind:'window',instance:'child'}]]);
      const document={dispatchEvent:()=>events++};
      class CustomEvent{constructor(type,options){this.detail=options.detail;}}
      const raisePaneFloat=()=>{},appInvoke=()=>null,postPaneMessage=m=>request=m;
      const paneMessageInScope=(m,s)=>m.scope===s;
    """ + functions + """
      focusPaneWindow('P');
      const good={...request,type:'focused',id:'child',scope:'ours'};
      acknowledgePaneFocus({...good,scope:'other'});
      acknowledgePaneFocus({...good,id:'stranger'});
      acknowledgePaneFocus({...good,request:'old'});
      const refused=events;
      acknowledgePaneFocus(good);acknowledgePaneFocus(good);
      console.log(JSON.stringify({refused,accepted:events}));
    """) == {'refused': 0, 'accepted': 1}


@pytest.mark.parametrize('kind', ['browser', 'float'])
def test_dom_return_completes_when_owned_pane_focus_succeeds(tour_browser, kind):
    _, evaluate = tour_browser
    entry = "{kind:'window',win:{closed:false,focus:()=>{window.focusedOwnPane=true;}}}" if kind == 'browser' else "{kind:'float',el:document.createElement('div')}"
    result = evaluate("""(()=>{
      const full=OrreryFullTour.checklist;document.getElementById('fullTourBtn').click();
      full.state.steps.slice(0,15).forEach(s=>full.mark(s.id));
      paneWindows.set('ReviewChild',ENTRY);
      const frame=document.getElementById('networkFrame').contentWindow;
      document.getElementById('networkOverlay').classList.add('on');
      for(const data of [{type:'orrery-tour-action',version:1,action:'return'},{type:'orrery-jump',name:'ReviewChild'}])
        window.dispatchEvent(new MessageEvent('message',{source:frame,origin:location.origin,data}));
      return {overlayClosed:!document.getElementById('networkOverlay').classList.contains('on'),complete:full.state.current===null};
    })()""".replace('ENTRY', entry))
    assert result == {'overlayClosed': True, 'complete': True}


@pytest.mark.parametrize('excerpt', ['ready', 'Ready  ', 'child started'])
def test_real_api_excerpt_and_same_second_preceding_child_mail_do_not_count(excerpt):
    assert run("""
      const t=tour.createShiritoriTracker('P',1000000),agents=[{name:'C',parent:'P'}];
      const before={id:10,ts:1001,sender:'C',recipient:'P',excerpt:EXCERPT,kind:'to',thread_id:null};
      const out={id:11,ts:1001,sender:'P',recipient:'C',excerpt:'りんご',kind:'to',thread_id:null};
      const reply={id:12,ts:1001,sender:'C',recipient:'P',excerpt:'ごりら',subject:'ごりら',kind:'to',thread_id:'game'};
      console.log(JSON.stringify([t.add([before,out],agents),t.add([reply],agents)]));
    """.replace('EXCERPT', json.dumps(excerpt))) == [False, True]


def test_ready_excerpt_after_parent_move_and_start_watermark_do_not_count():
    assert run("""
      const agents=[{name:'C',parent:'P'}],out={id:11,ts:1001,sender:'P',recipient:'C',excerpt:'りんご'};
      const ready={id:12,ts:1001,sender:'C',recipient:'P',excerpt:'ready'};
      const t=tour.createShiritoriTracker('P',1000000);
      const old=tour.createShiritoriTracker('P',1001000,12);
      console.log(JSON.stringify([t.add([out,ready],agents),old.add([out,{...ready,excerpt:'ごりら'}],agents),
        old.add([{...out,id:13},{...ready,id:14,excerpt:'ごりら'}],agents)]));
    """) == [False, False, True]


@pytest.mark.parametrize('kind', ['browser', 'float'])
def test_dom_owned_focus_leaves_pending_returned_draft_with_its_agent(tour_browser, kind):
    _, evaluate = tour_browser
    entry = "{kind:'window',win:{closed:false,focus:()=>{}}}" if kind == 'browser' else "{kind:'float',el:document.createElement('div')}"
    assert evaluate("""(()=>{
      activeId='other';panes.set('other',{session:'OtherAgent'});
      promptInput.value='';availableSessions.set('ReviewChild',{});
      const key=paneDraftKey(paneScope,'ReviewChild');
      localStorage.setItem(key,'ReviewChild unsent draft');takeBackPaneDraft('ReviewChild');
      paneWindows.set('ReviewChild',ENTRY);focusPaneWindow('ReviewChild');
      return {active:OC.activeAgent(),composer:promptInput.value,draft:localStorage.getItem(key),pending:pendingPaneDraft};
    })()""".replace('ENTRY', entry)) == {
        'active':'OtherAgent', 'composer':'', 'draft':'ReviewChild unsent draft', 'pending':'ReviewChild'}


def test_dom_planetarium_and_usage_check_off_when_closed_not_when_opened(tour_browser):
    """The recording checked both off the moment they opened, while the step
    text asks to look and then close the view."""
    _, evaluate = tour_browser
    result = evaluate("""(async()=>{
      const full=OrreryFullTour.checklist;document.getElementById('fullTourBtn').click();
      full.state.reset();full.show();full.state.goTo('full-planetarium');full.show();
      document.getElementById('planetariumBtn').click();
      await new Promise(r=>setTimeout(r,200));
      const planetOpen=full.state.current.id;
      window.OrreryRail.closePlanetarium?window.OrreryRail.closePlanetarium():document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));
      await new Promise(r=>setTimeout(r,200));
      const planetClosed=full.state.current.id;
      const pop=document.getElementById('usagePopover');pop.showPopover();
      await new Promise(r=>setTimeout(r,200));
      const usageOpen=full.state.current.id;
      pop.hidePopover();
      await new Promise(r=>setTimeout(r,200));
      return {planetOpen,planetClosed,usageOpen,usageClosed:full.state.current.id};
    })()""")
    assert result == {'planetOpen': 'full-planetarium', 'planetClosed': 'full-usage',
                      'usageOpen': 'full-usage', 'usageClosed': 'full-telemetry'}
