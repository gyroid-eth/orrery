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
ACTIVE = agent('CopperFixture', **CHILD)
STOPPED = agent('QuartzFixture', 'finished', **CHILD, resume_capability='ready')
SID = '01234567-1234-1234-1234-012345678901'
RETIRED = agent('SlateFixture', 'retired', **CHILD, history_session_id=SID, resume_capability='ready')
PERSISTENT = agent('BeaconFixture', **CHILD, lifecycle='persistent')
CONVERSATION = agent('AmberFixture', mail_status='unavailable', browser_use=True, computer_use='off')


@pytest.fixture
def roster(request):
    cdp = os.environ.get('ORRERY_CDP_URL')
    if not cdp:
        pytest.skip('set ORRERY_CDP_URL to an existing test browser')
    live = [ACTIVE, PERSISTENT, CONVERSATION]
    state = {'trace': [], 'checks': [], 'failures': {}, 'api': getattr(request, 'param', 45)}

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
                    self.answer({'agents': [*live, STOPPED, RETIRED]})
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
            error = state['failures'].get((self.path, body['session']))
            if error:
                self.answer({'ok': False, 'error': error})
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
            window.fetch=(url,options)=>url==='/telemetry/agents?scope=live'&&!options?.signal
                ?new Promise(()=>{}):fixtureFetch(url,options);
            const waitForExit=waitForBulkRebootExit;
            waitForBulkRebootExit=name=>waitForExit(name,1200,35);
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


def permission_jump(**permission):
    return '/api/jump', {'session': 'SlateFixture', 'open': False,
                         'permission': {'history_session_id': SID, **permission}}


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
    open_permissions(js, 'BeaconFixture', '[data-computer="control"]')
    assert js("agentDetail.querySelector('[data-computer=control]').title").endswith('(Persistent agent)')
    assert not js('permissionConfirm.open')
    open_permissions(js, 'SlateFixture', '[data-computer="control"]')
    assert js("document.activeElement.value") == 'cancel'
    js.client.call('Input.dispatchKeyEvent', type='keyDown', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    js.client.call('Input.dispatchKeyEvent', type='keyUp', key='Escape', code='Escape', windowsVirtualKeyCode=27)
    wait('!permissionConfirm.open&&!pendingPermissionChange')
    assert js('rosterSelectMode')
    assert state['trace'] == []


def test_active_finished_husk_and_conversation_only_controls_are_disabled(roster):
    js, wait, state = roster
    for name, reason in [('CopperFixture', 'Exit this agent first'), ('QuartzFixture', 'Exit this agent first'),
                         ('AmberFixture', 'Conversation-only resume has no saved permissions')]:
        open_permissions(js, name, '[data-computer="control"]')
        assert not js('permissionConfirm.open')
        assert js("agentDetail.querySelector('[data-computer=control]').title").endswith(f'({reason})')
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
    wait("toastEl.textContent.includes('Exit this agent first')")
    assert state['trace'] == []


def test_permission_confirmation_checks_the_current_api_generation(roster):
    js, wait, state = roster
    open_permissions(js, 'SlateFixture', '[data-computer="control"]')
    state['api'] = 44
    js('permissionApply.click()')
    wait("toastEl.textContent.includes('Requires Telemetry API 45')")
    assert state['trace'] == []
