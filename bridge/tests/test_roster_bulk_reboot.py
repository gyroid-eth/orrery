"""Exercise Select/Reboot in the browser against a disposable HTTP API."""

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


ACTIVE = agent('CopperFixture')
STOPPED = agent('QuartzFixture', 'finished')
PERSISTENT = agent('BeaconFixture', lifecycle='persistent')


@pytest.fixture
def roster():
    cdp = os.environ.get('ORRERY_CDP_URL')
    if not cdp:
        pytest.skip('set ORRERY_CDP_URL to an existing test browser')
    live = [ACTIVE, PERSISTENT]
    state = {'trace': [], 'checks': [], 'failures': {}}

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
                    self.answer({'agents': [*live, STOPPED]})
                    return
                status, rows = state['checks'].pop(0) if state['checks'] else (200, live)
                state['trace'].append(('roster', status, [row['category'] for row in rows]))
                self.answer({'agents': rows} if status == 200 else {'error': 'busy'}, status)
            elif path.path.startswith(('/api/', '/telemetry/')):
                self.answer({'prefs': {}, 'messages': [], 'spawn': []})
            else:
                super().do_GET()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['trace'].append((self.path, body))
            error = state['failures'].get((self.path, body['session']))
            self.answer({'ok': False, 'error': error} if error else {'ok': True})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    request = urllib.request.Request(cdp + '/json/new?about:blank', method='PUT')
    with urllib.request.urlopen(request) as response:
        tab = json.load(response)
    client = _WebSocket(tab['webSocketDebuggerUrl'])
    client.call('Page.enable')
    client.call('Runtime.enable')
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
