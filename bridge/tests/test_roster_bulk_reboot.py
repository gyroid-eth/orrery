"""Exercise roster restarts in the browser against a disposable HTTP API."""

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


def agent(name, category='agent', **options):
    return {'name': name, 'category': category, 'running': category == 'agent',
            'task': 'Preview task', 'act_state': 'wait', **options}


CHILD = dict(harness_kind='codex', parent_state='child', history_binding='bound',
             computer_use='off', browser_use=False)
SID = '01234567-1234-1234-1234-012345678901'
ACTIVE_SID = '11234567-1234-1234-1234-012345678901'
ACTIVE = agent('CopperFixture', **CHILD, created=123456, history_session_id=ACTIVE_SID,
               resume_capability='not_required')
HUSK = ACTIVE | {'category': 'finished', 'running': False, 'resume_capability': 'ready'}
EXITED = HUSK | {'category': 'gone', 'created': 0}
STOPPED = agent('QuartzFixture', 'finished', **CHILD, history_session_id=SID, resume_capability='ready')
RETIRED = agent('SlateFixture', 'retired', **CHILD, history_session_id=SID, resume_capability='ready')
PERSISTENT = agent('BeaconFixture', **CHILD, lifecycle='persistent')
CONVERSATION = agent('AmberFixture', mail_status='unavailable', browser_use=True, computer_use='off')
TOP_SID = '21234567-1234-1234-1234-012345678901'
TOP_RETIRED_SID = '31234567-1234-1234-1234-012345678901'
TOP = ACTIVE | {'name': 'IndigoFixture', 'parent_state': 'top', 'history_session_id': TOP_SID,
                'permission_resume_supported': True}
TOP_EXITED = TOP | {'category': 'gone', 'running': False, 'created': 0, 'resume_capability': 'ready'}
TOP_RETIRED = TOP_EXITED | {'name': 'JadeFixture', 'category': 'retired', 'history_session_id': TOP_RETIRED_SID}
TOP_DIRECT = TOP | {'name': 'OpalFixture', 'permission_resume_supported': False,
                    'permission_resume_reason': 'No saved launch settings; use Resume'}


@pytest.fixture
def roster(request):
    cdp = os.environ.get('ORRERY_CDP_URL')
    if not cdp:
        pytest.skip('set ORRERY_CDP_URL to an existing test browser')
    live = [ACTIVE, PERSISTENT, CONVERSATION, TOP, TOP_DIRECT]
    state = {'trace': [], 'checks': [], 'stop_checks': [], 'failures': {},
             'api': getattr(request, 'param', 45)}

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT / 'bridge'), **kwargs)

        def log_message(self, *_):
            pass

        def answer(self, data, status=200):
            raw = json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urlsplit(self.path)
            if path.path == '/telemetry/agents':
                if path.query != 'scope=live':
                    if self.headers.get('X-Fixture-Stop-Check') == '1':
                        row = state['stop_checks'].pop(0) if state['stop_checks'] else EXITED
                        state['trace'].append(('history', row['category']))
                        self.answer({'agents': [row, STOPPED, RETIRED, TOP_RETIRED]})
                        return
                    self.answer({'agents': [*live, STOPPED, RETIRED, TOP_RETIRED]})
                    return
                status, rows = state['checks'].pop(0) if state['checks'] else (200, live)
                state['trace'].append(('roster', status, [row['category'] for row in rows]))
                self.answer({'agents': rows} if status == 200 else {'error': 'busy'}, status)
            elif path.path == '/api/version':
                self.answer({'api': state['api']})
            elif path.path.startswith(('/api/', '/telemetry/')):
                self.answer({'prefs': {}, 'messages': [], 'spawn': []})
            else:
                super().do_GET()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['trace'].append((self.path, body))
            action = '/api/jump:check' if body.get('check_only') else self.path
            error = state['failures'].get((action, body['session']))
            if error:
                details = error if isinstance(error, dict) else {'error': error}
                self.answer({'ok': False, **details}, 400)
            elif body.get('check_only'):
                self.answer({'ok': True, 'action': 'validated'})
            elif self.path == '/api/jump' and 'permission' in body:
                self.answer({'ok': True, 'action': 'resumed', 'tools_changed': True})
            else:
                self.answer({'ok': True})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = urllib.request.Request(cdp + '/json/new?about:blank', method='PUT')
    with urllib.request.urlopen(request) as response:
        tab = json.load(response)
    client = _WebSocket(tab['webSocketDebuggerUrl'])
    client.call('Page.enable')
    client.call('Runtime.enable')
    client.call('Emulation.setFocusEmulationEnabled', enabled=True)
    client.call('Emulation.setDeviceMetricsOverride', width=1200, height=800, deviceScaleFactor=1, mobile=False)
    client.call('Page.addScriptToEvaluateOnNewDocument', source="""
        localStorage.setItem('oc-first-flight-v1', JSON.stringify({seen:true,open:false}));
    """)

    def js(expression):
        result = client.call('Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=True)
        assert not result.get('exceptionDetails'), result.get('exceptionDetails')
        return result.get('result', {}).get('value')

    def wait(expression):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if js(expression):
                return
            time.sleep(.03)
        raise AssertionError(expression)

    js.client = client

    try:
        client.call('Page.navigate', url=f'http://127.0.0.1:{server.server_port}/cockpit.html')
        wait("typeof tiles!=='undefined'&&tiles.has('CopperFixture')")
        assert not js("tiles.has('QuartzFixture')")
        # Keep the incidental roster poll out of the trace. Reboot's reads carry an abort signal.
        js("""const fixtureFetch=window.fetch;
            window.fetch=(url,options)=>{
                if(url==='/telemetry/agents?scope=live'&&!options?.signal)return new Promise(()=>{});
                if(url==='/telemetry/agents'&&options?.signal&&permissionChangeBusy){
                    options={...options,headers:{'X-Fixture-Stop-Check':'1'}};
                }
                return fixtureFetch(url,options);
            };
            const waitForExit=waitForBulkRebootExit;
            waitForBulkRebootExit=(name,timeout,poll,confirm)=>waitForExit(name,1200,35,confirm);
            rosterSelectBtn.click();""")
        wait("tiles.has('QuartzFixture')")
        state['trace'].clear()
        yield js, wait, state
    finally:
        urllib.request.urlopen(cdp + '/json/close/' + tab['id']).close()
        client.socket.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def jump(name):
    return '/api/jump', {'session': name, 'open_terminal': False, 'open': False}


@pytest.mark.parametrize('stopped_row', [[], [agent('CopperFixture', 'finished')]],
                         ids=['live scope omits stopped rows', 'full roster reports finished'])
def test_confirmed_reboot_checks_exit_then_resumes_each_agent_in_order(roster, stopped_row):
    js, wait, state = roster
    state['checks'] = [(503, []), (200, [ACTIVE]), (200, stopped_row)]
    js("tiles.get('CopperFixture').click();tiles.get('QuartzFixture').click();rosterBulkReboot.click()")
    assert js("rosterBulkReboot.getAttribute('aria-label')") == 'Confirm Reboot (2)'
    assert state['trace'] == []

    js("rosterBulkReboot.click()")
    wait("!rosterSelectMode")
    assert state['trace'] == [
        ('/api/exit', {'session': 'CopperFixture'}),
        ('roster', 503, []), ('roster', 200, ['agent']),
        ('roster', 200, [row['category'] for row in stopped_row]),
        jump('CopperFixture'), jump('QuartzFixture'),
    ]
    assert js("toastEl.textContent") == 'Reboot · 2 succeeded'
    assert not js("tiles.has('QuartzFixture')")


def test_protection_and_action_specific_confirmation(roster):
    js, wait, state = roster
    js("tiles.get('BeaconFixture').click()")
    assert js("tiles.get('BeaconFixture').getAttribute('aria-disabled')") == 'true'
    assert js("rosterBulkBar.hidden")

    js("tiles.get('QuartzFixture').click();rosterBulkExit.click();rosterBulkReboot.click()")
    assert js("rosterBulkReboot.getAttribute('aria-label')") == 'Confirm Reboot (1)'
    assert state['trace'] == []
    js("rosterBulkReboot.click()")
    wait("!rosterSelectMode")
    assert state['trace'] == [jump('QuartzFixture')]


def test_a_timeout_and_resume_failure_each_get_a_line_and_do_not_stop_the_queue(roster):
    js, wait, state = roster
    state['failures'][('/api/jump', 'QuartzFixture')] = 'Resume unavailable\nCheck session history'
    js("tiles.get('CopperFixture').click();tiles.get('QuartzFixture').click();"
       "rosterBulkReboot.click();rosterBulkReboot.click()")
    wait("!rosterSelectMode")
    assert state['trace'][0] == ('/api/exit', {'session': 'CopperFixture'})
    assert state['trace'][-1] == jump('QuartzFixture')
    assert all(entry[0] == 'roster' for entry in state['trace'][1:-1])
    assert len(state['trace']) > 2
    assert js("toastEl.textContent").splitlines() == [
        'Reboot · 0 succeeded · 2 failed',
        'CopperFixture: timed out waiting for exit',
        'QuartzFixture: Resume unavailable Check session history',
    ]


def open_permissions(js, name, selector):
    js(f"showAgentDetail(tiles.get({json.dumps(name)}));agentDetail.querySelector({json.dumps(selector)}).click()")


def assert_read_only_permissions(js, name, reason):
    js(f"showAgentDetail(tiles.get({json.dumps(name)}))")
    assert js("agentDetail.querySelector('[data-browser],[data-computer]')===null")
    assert reason in js("agentDetail.innerText")
    assert not js("permissionConfirm.open")


def permission_jump(name='SlateFixture', sid=SID, **permission):
    return '/api/jump', {'session': name, 'open': False, 'open_terminal': False,
                         'permission': {'history_session_id': sid, **permission}}


def test_permission_resume_sends_only_one_change_from_the_keyboard(roster):
    js, wait, state = roster
    js("tiles.get('SlateFixture').focus()")
    assert js("""(()=>{
      const button=agentDetail.querySelector('[data-browser]');
      const box=button.getBoundingClientRect();
      return button.contains(document.elementFromPoint(box.x+box.width/2,box.y+box.height/2));
    })()""")
    # Natural tab order reaches the permission buttons from the roster tile.
    for _ in range(10):
        js.client.call('Input.dispatchKeyEvent', type='keyDown', key='Tab', code='Tab', windowsVirtualKeyCode=9)
        js.client.call('Input.dispatchKeyEvent', type='keyUp', key='Tab', code='Tab', windowsVirtualKeyCode=9)
        if js("document.activeElement.matches('[data-browser]')"):
            break
    assert js("document.activeElement.matches('[data-browser]')")
    js.client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13, text='\r')
    js.client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    assert js('permissionConfirm.open')
    assert 'same conversation' in js('permissionConfirm.textContent')
    assert js('permissionComputer.disabled')
    assert state['trace'] == []
    js("permissionApply.click()")
    wait("toastEl.textContent.startsWith('Resume accepted')")
    assert state['trace'] == [permission_jump(browser_use=True)]


def test_cancel_and_disabled_permissions_send_no_actions(roster):
    js, wait, state = roster
    assert_read_only_permissions(js, 'BeaconFixture', 'Persistent agent')
    open_permissions(js, 'SlateFixture', '[data-computer="control"]')
    assert js("document.activeElement.value") == 'cancel'
    js.client.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    js.client.call('Input.dispatchKeyEvent', type='keyUp', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    wait('!permissionConfirm.open&&!pendingPermissionChange')
    assert js('rosterSelectMode')
    assert state['trace'] == []


def test_finished_husk_and_conversation_only_controls_are_disabled(roster):
    js, wait, state = roster
    for name, reason in [('QuartzFixture', 'Exit this agent first'),
                         ('AmberFixture', 'Conversation-only resume has no saved permissions')]:
        assert_read_only_permissions(js, name, reason)
    assert state['trace'] == []


def test_stopped_agent_view_resumes_directly_and_reports_api_refusal(roster):
    js, wait, state = roster
    state['failures'][('/api/jump', 'SlateFixture')] = 'Screen relay unavailable'
    open_permissions(js, 'SlateFixture', '[data-computer="view"]')
    assert js('permissionApply.textContent') == 'Resume'
    js('permissionApply.click()')
    wait("toastEl.textContent.includes('Screen relay unavailable')")
    assert state['trace'] == [permission_jump(computer_use='view')]


@pytest.mark.parametrize('roster', [44], indirect=True)
def test_older_telemetry_does_not_offer_historical_permission_targets(roster):
    js, wait, state = roster
    assert js('permissionApi===44')
    assert not js("tiles.has('SlateFixture')")
    assert state['trace'] == []


def test_unknown_browser_requires_an_explicit_choice(roster):
    js, wait, state = roster
    js("currentAgentNamed('SlateFixture').browser_use=null")
    open_permissions(js, 'SlateFixture', '[data-browser]')
    js('permissionApply.click()')
    assert js("permissionConfirm.open&&permissionBrowser.value===''&&!permissionBrowser.validity.valid")
    assert state['trace'] == []
    js("permissionBrowser.value='on';permissionApply.click()")
    wait("toastEl.textContent.startsWith('Resume accepted')")
    assert state['trace'] == [permission_jump(browser_use=True)]


def test_permission_confirmation_rechecks_a_new_live_row(roster):
    js, wait, state = roster
    open_permissions(js, 'SlateFixture', '[data-computer="control"]')
    js("currentAgents=currentAgents.map(a=>a.name==='SlateFixture'?{...a,category:'agent',running:true}:a);")
    js('permissionApply.click()')
    wait("toastEl.textContent.includes('The agent changed')")
    assert state['trace'] == []


def test_permission_confirmation_checks_the_current_api_generation(roster):
    js, wait, state = roster
    open_permissions(js, 'SlateFixture', '[data-computer="control"]')
    state['api'] = 44
    js('permissionApply.click()')
    wait("toastEl.textContent.includes('Requires Telemetry API 45')")
    assert state['trace'] == []


def test_permission_restarts_only_after_the_same_conversation_is_stopped(roster):
    js, wait, state = roster
    state['checks'] = [(200, [ACTIVE]), (503, []), (200, []), (200, [])]
    state['stop_checks'] = [HUSK, EXITED]
    open_permissions(js, 'CopperFixture', '[data-computer="view"]')
    assert js('permissionApply.textContent') == 'Restart'
    assert 'Any work in progress will be interrupted.' in js('permissionConfirm.textContent')
    assert state['trace'] == []

    js('permissionApply.click()')
    wait("toastEl.textContent.startsWith('Resume accepted')")
    assert state['trace'] == [
        ('roster', 200, ['agent']),
        ('/api/exit', {'session': 'CopperFixture'}),
        ('roster', 503, []), ('roster', 200, []), ('history', 'finished'),
        ('roster', 200, []), ('history', 'gone'),
        permission_jump('CopperFixture', ACTIVE_SID, computer_use='view'),
    ]


def test_permission_restart_checks_current_conversation_before_exit(roster):
    js, wait, state = roster
    state['checks'] = [(200, [ACTIVE | {'history_session_id': SID}])]
    open_permissions(js, 'CopperFixture', '[data-browser]')
    js('permissionApply.click()')
    wait("toastEl.textContent.includes('The agent changed')")
    assert state['trace'] == [('roster', 200, ['agent'])]


def test_failed_permission_exit_never_resumes(roster):
    js, wait, state = roster
    state['checks'] = [(200, [ACTIVE])]
    state['failures'][('/api/exit', 'CopperFixture')] = 'Exit command refused'
    open_permissions(js, 'CopperFixture', '[data-browser]')
    js('permissionApply.click()')
    wait("toastEl.textContent.startsWith('Exit request failed')")
    assert 'Exit command refused' in js('toastEl.textContent')
    assert state['trace'] == [('roster', 200, ['agent']), ('/api/exit', {'session': 'CopperFixture'})]


def test_permission_exit_timeout_displays_progress_and_never_resumes(roster):
    js, wait, state = roster
    open_permissions(js, 'CopperFixture', '[data-browser]')
    js('permissionApply.click()')
    wait("permissionChangeBusy&&toastEl.textContent.startsWith('Waiting for')")
    assert js('rosterBulkReboot.disabled')
    wait("toastEl.textContent.includes('timed out waiting for exit')")
    assert not js('permissionChangeBusy')
    assert all(entry[0] == 'roster' for entry in state['trace'][2:])


def test_permission_resume_rejection_reports_the_stop_and_recovery(roster):
    js, wait, state = roster
    state['checks'] = [(200, [ACTIVE]), (200, [])]
    state['failures'][('/api/jump', 'CopperFixture')] = 'Screen relay unavailable'
    open_permissions(js, 'CopperFixture', '[data-computer="view"]')
    js('permissionApply.click()')
    wait("toastEl.textContent.includes('Screen relay unavailable')")
    assert js('toastEl.textContent').splitlines() == [
        'CopperFixture stopped. Resume failed · Screen relay unavailable',
        'Use Resume in Network if the agent is stopped.',
    ]
    assert state['trace'][-1] == permission_jump('CopperFixture', ACTIVE_SID, computer_use='view')


def test_permission_restart_does_not_resume_a_replacement_conversation(roster):
    js, wait, state = roster
    state['checks'] = [(200, [ACTIVE]), (200, [])]
    state['stop_checks'] = [EXITED | {'history_session_id': SID}]
    open_permissions(js, 'CopperFixture', '[data-browser]')
    js('permissionApply.click()')
    wait("toastEl.textContent.includes('The stopped conversation changed')")
    assert state['trace'][-1] == ('history', 'gone')
    assert not any(path == '/api/jump' for path, *_ in state['trace'])


def test_older_api_keeps_standalone_permissions_disabled(roster):
    js, wait, state = roster
    assert_read_only_permissions(js, 'IndigoFixture', 'Standalone agent')
    assert not js("tiles.has('JadeFixture')")
    assert state['trace'] == []

    state['api'] = 46
    js("permissionApiCheckedAt=-Infinity;showAgentDetail(tiles.get('IndigoFixture'))")
    wait("agentDetail.querySelector('[data-browser]')?.disabled===false")
    assert state['trace'] == []


@pytest.mark.parametrize('roster', [46], indirect=True)
def test_api46_enables_stopped_standalone_and_shows_direct_launch_reason(roster):
    js, wait, state = roster
    assert_read_only_permissions(js, 'OpalFixture', 'No saved launch settings; use Resume')
    open_permissions(js, 'JadeFixture', '[data-browser]')
    assert js('permissionApply.textContent') == 'Resume'
    js('permissionApply.click()')
    wait("toastEl.textContent.startsWith('Resume accepted')")
    assert state['trace'] == [permission_jump('JadeFixture', TOP_RETIRED_SID, browser_use=True)]


@pytest.mark.parametrize('roster', [46], indirect=True)
@pytest.mark.parametrize(('active', 'stopped'), [(ACTIVE, EXITED), (TOP, TOP_EXITED)], ids=['child', 'standalone'])
def test_api46_validates_restart_and_sends_the_same_conversation_to_exit(roster, active, stopped):
    js, wait, state = roster
    name, sid = active['name'], active['history_session_id']
    state['checks'] = [(200, [active]), (200, [])]
    state['stop_checks'] = [stopped]
    open_permissions(js, name, '[data-browser]')
    js('permissionApply.click()')
    wait("toastEl.textContent.startsWith('Resume accepted')")
    path, jump = permission_jump(name, sid, browser_use=True)
    assert state['trace'] == [
        ('roster', 200, ['agent']),
        (path, jump | {'check_only': True}),
        ('/api/exit', {'session': name, 'history_session_id': sid}),
        ('roster', 200, []), ('history', 'gone'), (path, jump),
    ]


@pytest.mark.parametrize('roster', [54], indirect=True)
def test_api54_browser_mode_restart_validates_and_resumes_the_same_conversation(roster):
    js, wait, state = roster
    browser = {'value': False, 'mode': 'off', 'options': ['off', 'temporary', 'personal'], 'can_change': True}
    controls = {'browser_use': browser | {'action': 'restart'}}
    active = ACTIVE | {'permission_controls': controls}
    stopped = EXITED | {'permission_controls': {'browser_use': browser | {'action': 'resume'}}}
    state['checks'] = [(200, [active]), (200, [])]
    state['stop_checks'] = [stopped]
    js(f"currentAgentNamed('CopperFixture').permission_controls={json.dumps(controls)}")
    open_permissions(js, 'CopperFixture', '[data-browser]')
    assert js("permissionApply.textContent") == "Restart"
    assert js("!permissionBrowser.validity.valid")
    js("permissionBrowser.value='temporary';permissionApply.click()")
    wait("toastEl.textContent.startsWith('Resume accepted')")
    path, jump = permission_jump('CopperFixture', ACTIVE_SID, browser_mode='temporary')
    assert state['trace'] == [
        ('roster', 200, ['agent']),
        (path, jump | {'check_only': True}),
        ('/api/exit', {'session': 'CopperFixture', 'history_session_id': ACTIVE_SID}),
        ('roster', 200, []), ('history', 'gone'), (path, jump),
    ]


@pytest.mark.parametrize('roster', [55], indirect=True)
@pytest.mark.parametrize(('close_order', 'stay'), [
    ('status', True), ('list', False), ('pane', True), ('manual', False),
])
def test_permission_restart_reattaches_the_open_tab_to_the_new_pane(roster, close_order, stay):
    js, wait, state = roster
    controls = {'computer_use': {'value': 'off', 'can_change': True, 'action': 'restart'}}
    active = ACTIVE | {'permission_controls': controls}
    stopped = EXITED | {'permission_controls': {'computer_use': controls['computer_use'] | {'action': 'resume'}}}
    state['checks'] = [(200, [active]), (200, [])]
    state['stop_checks'] = [stopped]
    js(f"currentAgentNamed('CopperFixture').permission_controls={json.dumps(controls)}")
    js("""
      socket=null;clearTimeout(reconnectTimer);
      window.sentFrames=[];send=frame=>{sentFrames.push(frame);return true;};
      handle({type:'sessions',sessions:['CopperFixture','IndigoFixture']});
      handle({type:'reset',session:'CopperFixture',incarnation:'old',panes:[
        {paneId:'%141',width:80,height:24,currentCommand:'codex',active:true}]});
      handle({type:'reset',session:'IndigoFixture',incarnation:'other',panes:[
        {paneId:'%142',width:80,height:24,currentCommand:'zsh',active:true}]});
      setActive('%141');
      window.originalGroup=sessionGroups.get('CopperFixture').el;
      const beforeRestartFetch=window.fetch;
      window.fetch=async (url,opts)=>{
        const reply=await beforeRestartFetch(url,opts);
        if(url==='/api/jump'&&!JSON.parse(opts.body).check_only){
          await new Promise(resolve=>{window.allowRestartJump=resolve;});
        }
        return reply;
      };
    """)
    open_permissions(js, 'CopperFixture', '[data-computer="view"]')
    js('permissionApply.click()')
    wait("typeof allowRestartJump==='function'")
    assert js("sessionGroups.get('CopperFixture').state.textContent==='Restarting'")
    assert js("stageEl.querySelector('.terminal-action-notice').ariaLabel==='Restarting CopperFixture…'")
    letters = "tiles.get('CopperFixture').querySelectorAll('.cname > span')"
    assert js(f"getComputedStyle({letters}[0]).animationDuration") == '1.6s'
    assert js(f"getComputedStyle({letters}[1]).animationDelay") == '0.07s'
    js.client.call('Emulation.setEmulatedMedia', features=[{'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    assert js(f"getComputedStyle({letters}[0]).animationName") == 'none'
    js.client.call('Emulation.setEmulatedMedia', features=[])
    if close_order == 'list':
        js("handle({type:'sessions',sessions:['IndigoFixture']})")
    elif close_order in ('pane', 'manual'):
        js("handle({type:'close',session:'CopperFixture',paneId:'%141'})")
    js("handle({type:'status',state:'closed',session:'CopperFixture',sessionGone:true,incarnation:'old'})")
    assert js("sessionGroups.get('CopperFixture').el===originalGroup && activeId===null && !panes.has('%141')")
    js("window.restartLiveFixture=liveRosterAgents;liveRosterAgents=liveRosterAgents.filter(a=>a.name!=='CopperFixture');"
       "renderRoster();showAgentDetail(tiles.get('CopperFixture'))")
    assert js("tiles.get('CopperFixture').querySelector('.cname').textContent==='CopperFixture'")
    assert js("agentDetail.querySelector('.agent-detail-pending-action').textContent==='Restarting'")
    if not stay:
        js("setActive('%142')")
    if close_order == 'manual':
        js("sessionGroups.get('CopperFixture').detach.click()")
    js('allowRestartJump()')
    wait("toastEl.textContent.startsWith('Resume accepted')")
    js("handle({type:'sessions',sessions:['CopperFixture','IndigoFixture']})")
    if close_order == 'manual':
        assert js("!sessionGroups.has('CopperFixture') && activeId==='%142'")
        assert js("!sentFrames.some(frame=>frame.type==='attach'&&frame.session==='CopperFixture')")
        return
    wait("sentFrames.some(frame=>frame.type==='attach'&&frame.session==='CopperFixture')")
    js("""
      handle({type:'reset',session:'CopperFixture',incarnation:'old',panes:[
        {paneId:'%141',width:80,height:24,currentCommand:'codex',active:true}]});
      handle({type:'status',state:'closed',session:'CopperFixture',sessionGone:true,incarnation:'old'});
    """)
    assert js("!panes.has('%141') && sessionGroups.get('CopperFixture').el===originalGroup")
    wait("requestedSessions.has('CopperFixture')")
    js("""
      liveRosterAgents=restartLiveFixture;renderRoster();
      handle({type:'reset',session:'CopperFixture',incarnation:'new',panes:[
        {paneId:'%143',width:80,height:24,currentCommand:'codex',active:true}]});
      handle({type:'output',session:'CopperFixture',paneId:'%143',snapshot:true,data:'› '});
      handle({type:'status',state:'closed',session:'CopperFixture',sessionGone:true,incarnation:'old'});
    """)
    wait("!permissionRestarts.has('CopperFixture')")
    assert js("sessionGroups.get('CopperFixture').el===originalGroup && panes.has('%143')")
    assert js('activeId') == ('%143' if stay else '%142')
    assert js("!stageEl.querySelector('.terminal-action-notice')&&!tiles.get('CopperFixture').querySelector('.terminal-action-wave')")


def test_confirmed_bulk_exit_marks_each_agent_until_disappearance_or_failure(roster):
    js, wait, state = roster
    state['failures'][('/api/exit', 'IndigoFixture')] = 'Exit was refused'
    js("""
      socket=null;clearTimeout(reconnectTimer);
      send=()=>true;
      handle({type:'sessions',sessions:['CopperFixture','IndigoFixture']});
      handle({type:'reset',session:'CopperFixture',incarnation:'old',panes:[
       {paneId:'%141',width:80,height:24,currentCommand:'codex',active:true}]});
      setActive('%141');
      const exitFetch=window.fetch;
      window.fetch=async (url,opts)=>{
        if(url==='/api/exit'&&JSON.parse(opts.body).session==='CopperFixture')
          await new Promise(resolve=>{window.allowBulkExit=resolve;});
        return exitFetch(url,opts);
      };
      tiles.get('CopperFixture').click();tiles.get('IndigoFixture').click();rosterBulkExit.click();
    """)
    assert js("pendingAgentExits.size") == 0
    js("rosterBulkExit.click()")
    wait("typeof allowBulkExit==='function'")
    assert js("Array.from(pendingAgentExits.keys())") == ['CopperFixture', 'IndigoFixture']
    assert js("stageEl.querySelector('.terminal-action-notice').ariaLabel") == 'Exiting CopperFixture…'
    assert js("tiles.get('IndigoFixture').querySelector('.cname.terminal-action-wave').textContent") == 'Exiting IndigoFixture…'
    js("allowBulkExit()")
    wait("toastEl.textContent.includes('Exit was refused')")
    assert js("Array.from(pendingAgentExits.keys())") == ['CopperFixture']
    assert js("!tiles.get('IndigoFixture').querySelector('.terminal-action-wave')")
    js("""
      const rosterFetch=window.fetch;
      window.fetch=(url,opts)=>url==='/telemetry/agents?scope=live'?
        Promise.resolve(new Response(JSON.stringify({agents:liveRosterAgents.filter(a=>a.name!=='CopperFixture')}))):
        rosterFetch(url,opts);
      pollAgents();
    """)
    wait("!tiles.has('CopperFixture')")
    assert js("pendingAgentExits.size===0&&!stageEl.querySelector('.terminal-action-notice')")


@pytest.mark.parametrize("response", ['refused', 'cancelled', 'accepted'])
def test_embedded_exit_updates_the_parent_without_consuming_its_response(roster, response):
    js, wait, _state = roster
    js("""
      window.exitFrame=new EventTarget();exitFrame.location=location;
      window.frameExit=observeNetworkExits(exitFrame,()=>new Promise(resolve=>{window.resolveFrameExit=resolve;}));
      window.exitResult=frameExit('/api/exit',{method:'POST',body:JSON.stringify({session:'CopperFixture'})})
        .then(r=>r.json());
      true;
    """)
    assert js("pendingAgentAction('CopperFixture')") == 'Exiting'
    if response == 'cancelled':
        js("exitFrame.dispatchEvent(new Event('pagehide'))")
        assert js("toastEl.textContent.includes('The request was cancelled')")
    ok = response != 'refused'
    payload = {'ok': ok} if ok else {'ok': False, 'error': 'Shell rejected Exit'}
    js(f"resolveFrameExit(new Response({json.dumps(json.dumps(payload))},{{status:{200 if ok else 400}}}))")
    assert js("exitResult") == payload
    if response == 'accepted':
        assert js("pendingAgentAction('CopperFixture')") == 'Exiting'
    else:
        assert js("!pendingAgentAction('CopperFixture')")
        if response == 'refused':
            assert js("toastEl.textContent.includes('Shell rejected Exit')")


@pytest.mark.parametrize(('depart_first', 'reduced', 'accepted'), [
    (True, False, True), (False, False, True), (False, True, True), (True, False, False),
])
def test_exit_dust_waits_for_success_and_departure_and_releases_the_tab(
    roster, depart_first, reduced, accepted,
):
    js, wait, _state = roster
    js.client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce' if reduced else 'no-preference'},
    ])
    js("""
      setRosterSelectMode(false);
      socket=null;clearTimeout(reconnectTimer);send=()=>true;
      handle({type:'sessions',sessions:['CopperFixture','IndigoFixture']});
      handle({type:'reset',session:'CopperFixture',incarnation:'old',panes:[
        {paneId:'%141',width:80,height:24,currentCommand:'codex',active:true}]});
      handle({type:'reset',session:'IndigoFixture',incarnation:'other',panes:[
        {paneId:'%142',width:80,height:24,currentCommand:'zsh',active:true}]});
      setActive('%141');selectAgent('CopperFixture');
      window.exitFrame=new EventTarget();exitFrame.location=location;
      const frameExit=observeNetworkExits(exitFrame,()=>new Promise(resolve=>{window.resolveExit=resolve;}));
      frameExit('/api/exit',{method:'POST',body:JSON.stringify({session:'CopperFixture'})});
      const originalDustFetch=window.fetch;
      window.fetch=(url,opts)=>url==='/telemetry/agents?scope=live'?
        Promise.resolve(new Response(JSON.stringify({agents:liveRosterAgents.filter(a=>a.name!=='CopperFixture')}))):
        originalDustFetch(url,opts);
      const previousFrame=window.requestAnimationFrame;
      window.requestAnimationFrame=callback=>{
        if(callback.name==='animateDust'){window.advanceDust=callback;return 0;}
        return previousFrame(callback);
      };
      true;
    """)
    if depart_first:
        js("""
          handle({type:'status',state:'closed',session:'CopperFixture',sessionGone:true,incarnation:'old'});
          pollAgents();
        """)
        wait("pendingAgentExits.get('CopperFixture').departed")
        assert js("tiles.has('CopperFixture')&&sessionGroups.has('CopperFixture')")
    assert js("!document.querySelector('canvas.exit-dust')")
    body = {"ok": True} if accepted else {"ok": False, "error": "Exit refused"}
    js(f"resolveExit(new Response({json.dumps(json.dumps(body))},{{status:{200 if accepted else 400}}}))")
    if not depart_first:
        wait("pendingAgentExits.get('CopperFixture')?.accepted")
        assert js("tiles.has('CopperFixture')&&sessionGroups.has('CopperFixture')&&!document.querySelector('canvas.exit-dust')")
        js("pollAgents()")
    wait("!pendingAgentExits.has('CopperFixture')&&!tiles.has('CopperFixture')")
    if not accepted:
        assert js("toastEl.textContent.includes('Exit refused')&&!document.querySelector('canvas.exit-dust')")
        return
    assert js("!sessionGroups.has('CopperFixture') && activeId==='%142'")
    assert js("document.querySelectorAll('canvas.exit-dust').length") == (0 if reduced else 2)
    if not reduced:
        assert js("Array.from(document.querySelectorAll('canvas.exit-dust')).every(canvas=>canvas.getAttribute('aria-hidden')==='true')")
        js("advanceDust(performance.now()+2000)")
        assert js("!document.querySelector('canvas.exit-dust')")


@pytest.mark.parametrize('roster', [55], indirect=True)
def test_direct_launch_confirms_adoption_and_allows_stopped_shell(roster):
    js, wait, state = roster
    computer = {'value': 'off', 'can_change': True, 'action': 'restart'}
    active = TOP_DIRECT | {'permission_managed_launch': True, 'permission_controls': {'computer_use': computer}}
    stopped = active | {'category': 'finished', 'running': False,
                       'permission_controls': {'computer_use': computer | {'action': 'resume'}}}
    name = active['name']
    js(f"Object.assign(currentAgentNamed({json.dumps(name)}),{json.dumps(active)})")
    state['checks'] = [(200, [active]), (200, [])]
    state['stop_checks'] = [stopped]
    open_permissions(js, name, '[data-computer="view"]')
    assert 'managed launch' in js('permissionConfirm.textContent')
    assert state['trace'] == []
    js('permissionApply.click()')
    wait("toastEl.textContent.startsWith('Resume accepted')")
    path, jump = permission_jump(name, TOP_SID, computer_use='view', adopt=True)
    assert state['trace'] == [
        ('roster', 200, ['agent']), (path, jump | {'check_only': True}),
        ('/api/exit', {'session': name, 'history_session_id': TOP_SID}),
        ('roster', 200, []), ('history', 'finished'), (path, jump),
    ]


@pytest.mark.parametrize('roster', [46], indirect=True)
def test_api46_preflight_failure_leaves_the_standalone_running(roster):
    js, wait, state = roster
    state['checks'] = [(200, [TOP])]
    state['failures'][('/api/jump:check', 'IndigoFixture')] = 'Saved settings could not be restored'
    open_permissions(js, 'IndigoFixture', '[data-browser]')
    js('permissionApply.click()')
    wait("toastEl.textContent.includes('Saved settings could not be restored')")
    path, jump = permission_jump('IndigoFixture', TOP_SID, browser_use=True)
    assert state['trace'] == [('roster', 200, ['agent']), (path, jump | {'check_only': True})]


@pytest.mark.parametrize('roster', [46], indirect=True)
@pytest.mark.parametrize('active', [True, False], ids=['restart', 'resume'])
def test_api46_pending_codex_resume_displays_the_api_instructions(roster, active):
    js, wait, state = roster
    target = TOP if active else TOP_RETIRED
    name, sid = target['name'], target['history_session_id']
    if active:
        state['checks'] = [(200, [TOP]), (200, [])]
        state['stop_checks'] = [TOP_EXITED]
    error = 'Could not confirm Codex resumed or stopped; check its session'
    state['failures'][('/api/jump', name)] = {'error': error, 'resume_confirmation_pending': True}
    open_permissions(js, name, '[data-browser]')
    js('permissionApply.click()')
    wait("!permissionChangeBusy&&toastEl.textContent.includes('check its session')")
    assert js('toastEl.textContent') == f'{name} · {error}'
    assert state['trace'][-1] == permission_jump(name, sid, browser_use=True)
