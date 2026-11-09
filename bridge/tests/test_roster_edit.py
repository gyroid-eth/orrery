"""Edit the real cockpit roster against a disposable fake dashboard."""
import base64
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
AGENTS = [{
    'name': 'BuilderFixture', 'task': 'Build generated preview fixtures',
    'running': True, 'category': 'agent', 'program': 'codex', 'provider': 'openai',
    'model': 'gpt-6', 'act_state': 'wait',
    'annot': {'role': 'builder', 'emoji': '✳', 'group': 'fixtures'},
}, {
    'name': 'ReviewFixture', 'task': 'Review generated preview fixtures',
    'running': True, 'category': 'agent', 'program': 'codex', 'provider': 'openai',
    'model': 'gpt-6', 'act_state': 'wait', 'annot': None,
}]


@pytest.fixture
def editor(request):
    if not CDP:
        pytest.skip('set ORRERY_CDP_URL to an existing test browser')
    state = {'api': getattr(request, 'param', 38), 'agents': copy.deepcopy(AGENTS),
             'writes': [], 'fail': False}

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
            path = urlsplit(self.path).path
            if path == '/api/version':
                self.answer({'api': state['api']})
            elif path == '/telemetry/agents':
                self.answer({'agents': state['agents']})
            elif path.startswith(('/api/', '/telemetry/')):
                self.answer({'agents': [], 'prefs': {}, 'messages': [], 'spawn': []})
            else:
                super().do_GET()
        def do_POST(self):
            assert self.path == '/api/annotate'
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['writes'].append(body)
            if state['fail']:
                self.answer({'ok': False, 'error': 'Generated save failure'}, 503)
                return
            agent = next(a for a in state['agents'] if a['name'] == body['name'])
            annotation = dict(agent.get('annot') or {}) if state['api'] >= 38 else {}
            for field in ('role', 'emoji', 'group', 'task'):
                if field in body:
                    annotation[field] = body[field].strip()
            agent['annot'] = annotation if any(annotation.values()) else None
            self.answer({'ok': True, 'annot': agent['annot']})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    tab = json.load(urllib.request.urlopen(urllib.request.Request(CDP + '/json/new?about:blank', method='PUT')))
    client = _WebSocket(tab['webSocketDebuggerUrl'])
    client.call('Page.enable')
    client.call('Runtime.enable')
    client.call('Emulation.setFocusEmulationEnabled', enabled=True)
    client.call('Emulation.setDeviceMetricsOverride', width=1600, height=1000, deviceScaleFactor=1, mobile=False)
    client.call('Page.addScriptToEvaluateOnNewDocument', source="localStorage.clear();localStorage.setItem('oc-term-conversation-enabled','0');localStorage.setItem('oc-first-flight-v1',JSON.stringify({seen:true,open:false}));")

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
        wait("typeof currentAgents!=='undefined'&&currentAgents.length===2")
        js("""clearTimeout(reconnectTimer);scheduleReconnect=()=>{};send=()=>true;
          window.rosterFetch=window.fetch;window.fetch=(url,...args)=>String(url).startsWith('/telemetry/agents')
            ?new Promise(()=>{}):rosterFetch(url,...args);""")
        yield js, wait, client, state
    finally:
        urllib.request.urlopen(CDP + '/json/close/' + tab['id']).close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def open_editor(js, wait):
    assert js("Boolean(tiles.get('BuilderFixture').querySelector('.roster-edit-toggle'))")
    js("tiles.get('BuilderFixture').querySelector('.roster-edit-toggle').click()")
    wait("Boolean(document.querySelector('.roster-edit'))")


def test_editor_saves_role_and_task_without_changing_other_annotations(editor):
    js, wait, client, state = editor
    open_editor(js, wait)
    js("document.querySelector('.roster-edit-role').value='reviewer';document.querySelector('.roster-edit-task').value='Review generated fixtures';document.querySelector('.roster-edit-save').click()")
    wait("!document.querySelector('.roster-edit')")
    assert state['agents'][0]['annot'] == {
        'role': 'reviewer', 'task': 'Review generated fixtures', 'emoji': '✳', 'group': 'fixtures',
    }
    assert js("tiles.get('BuilderFixture').querySelector('.pill.role').textContent") == 'reviewer'
    assert js("tiles.get('BuilderFixture').querySelector('.statetext').textContent") == 'Review generated fixtures'
    assert js("tiles.get('BuilderFixture').querySelector('.statetext').title") == 'Edited in cockpit · registered: Build generated preview fixtures'


def key(client, name, code):
    for kind in ('keyDown', 'keyUp'):
        text = {'text': '\r'} if kind == 'keyDown' and name == 'Enter' else {}
        client.call('Input.dispatchKeyEvent', type=kind, key=name, windowsVirtualKeyCode=code, **text)


def test_keyboard_open_save_cancel_and_ime_do_not_select_the_agent(editor):
    js, wait, client, state = editor
    js("tiles.get('BuilderFixture').querySelector('.roster-edit-toggle').focus()")
    key(client, 'Enter', 13)
    wait("Boolean(document.querySelector('.roster-edit'))")
    assert js('selectedAgent') is None
    js("document.querySelector('.roster-edit-role').value='reviewer'")
    key(client, 'Escape', 27)
    assert js("Boolean(document.querySelector('.roster-edit'))") is False
    assert state['writes'] == []
    assert js("document.activeElement.classList.contains('roster-edit-toggle')")
    key(client, 'Enter', 13)
    wait("Boolean(document.querySelector('.roster-edit'))")
    js("document.querySelector('.roster-edit-task').focus();document.querySelector('.roster-edit-task').value='Review generated fixtures';document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true}))")
    assert state['writes'] == []
    key(client, 'Enter', 13)
    wait("!document.querySelector('.roster-edit')")
    assert len(state['writes']) == 1
    assert js('selectedAgent') is None
    # Clicking the card itself still selects that agent in one click.
    js("tiles.get('BuilderFixture').click()")
    assert js('selectedAgent') == 'BuilderFixture'


def test_empty_fields_restore_registered_task_and_leave_emoji_and_group(editor):
    js, wait, client, state = editor
    test_editor_saves_role_and_task_without_changing_other_annotations(editor)
    open_editor(js, wait)
    js("document.querySelector('.roster-edit-role').value='';document.querySelector('.roster-edit-task').value='';document.querySelector('.roster-edit-save').click()")
    wait("!document.querySelector('.roster-edit')")
    assert js("currentAgentNamed('BuilderFixture').task") == AGENTS[0]['task']
    assert js("tiles.get('BuilderFixture').querySelector('.statetext').title") == ''
    assert state['agents'][0]['annot']['emoji'] == '✳'
    assert state['agents'][0]['annot']['group'] == 'fixtures'


@pytest.mark.parametrize('editor', [37], indirect=True)
def test_old_dashboard_offers_role_only_and_preserves_legacy_annotations(editor):
    js, wait, client, state = editor
    open_editor(js, wait)
    assert js("document.querySelector('.roster-edit-task').getClientRects().length") == 0
    js("document.querySelector('.roster-edit-role').value='reviewer';document.querySelector('.roster-edit-save').click()")
    wait("!document.querySelector('.roster-edit')")
    assert state['writes'] == [{'name': 'BuilderFixture', 'role': 'reviewer', 'emoji': '✳', 'group': 'fixtures'}]
    assert state['agents'][0]['annot']['emoji'] == '✳'
    assert state['agents'][0]['annot']['group'] == 'fixtures'


def test_failed_save_preserves_draft_and_cancel_sends_no_second_write(editor):
    js, wait, client, state = editor
    state['fail'] = True
    open_editor(js, wait)
    js("document.querySelector('.roster-edit-role').value='reviewer';document.querySelector('.roster-edit-save').click()")
    wait("document.querySelector('.roster-edit-status')?.textContent==='Generated save failure'")
    assert js("document.querySelector('.roster-edit-role').value") == 'reviewer'
    assert js("tiles.get('BuilderFixture').querySelector('.pill.role').textContent") == 'builder'
    js("document.querySelector('.roster-edit-cancel').click()")
    assert len(state['writes']) == 1


def test_draft_stays_below_card_after_roster_reorder_and_filter(editor):
    js, wait, client, state = editor
    open_editor(js, wait)
    js("document.querySelector('.roster-edit-role').value='reviewer';currentAgents[1].act_state='ask';reorderRoster(currentAgents)")
    assert js("document.querySelector('.roster-edit').previousElementSibling.dataset.agent") == 'BuilderFixture'
    assert js("document.querySelector('.roster-edit-role').value") == 'reviewer'
    assert js("document.activeElement.classList.contains('roster-edit-role')")
    js("rosterFilter.value='ReviewFixture';applyRosterFilter()")
    assert js("document.querySelector('.roster-edit').hidden")
    js("rosterFilter.value='';applyRosterFilter()")
    assert js("document.querySelector('.roster-edit').hidden") is False
    js("setRosterSelectMode(true)")
    assert js("Boolean(document.querySelector('.roster-edit'))") is False


def test_save_updates_split_role_and_planetarium_without_another_roster_poll(editor):
    js, wait, client, state = editor
    js("""createPane('BuilderFixture',{paneId:'%901',windowId:'@901',width:80,height:20});
      createPane('ReviewFixture',{paneId:'%902',windowId:'@902',width:80,height:20});
      replaceSplitSessions(['BuilderFixture','ReviewFixture']);splitVisible=true;focusSplitSession('BuilderFixture');""")
    test_editor_saves_role_and_task_without_changing_other_annotations(editor)
    assert js("splitCells.get('BuilderFixture')._role.textContent") == 'reviewer'
    js("document.getElementById('planetariumBtn').click()")
    wait("[...document.querySelectorAll('.planet-agent-role')].some(el=>el.textContent==='reviewer')")


@pytest.mark.parametrize('width', [1600, 820])
@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_editor_fits_roster_and_capture_states(editor, width, theme):
    js, wait, client, state = editor
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=1000, deviceScaleFactor=1, mobile=False)
    js(f'OrreryColorTheme.setPreference({json.dumps(theme)})')
    output = os.environ.get('ORRERY_ROSTER_EDIT_CAPTURE_DIR')
    def capture(name):
        if output:
            if name == 'before':
                js('new Promise(resolve=>setTimeout(resolve,700))')
            target = Path(output)
            target.mkdir(parents=True, exist_ok=True)
            shot = client.call('Page.captureScreenshot', format='png')
            (target / f'{theme}-{width}-{name}.png').write_bytes(base64.b64decode(shot['data']))
    capture('before')
    open_editor(js, wait)
    js("document.querySelector('.roster-edit-role').value='reviewer';document.querySelector('.roster-edit-task').value='Review generated fixtures and document the results'")
    capture('editing')
    assert js("""(()=>{const form=document.querySelector('.roster-edit'),bounds=rosterEl.getBoundingClientRect();
      return [...form.querySelectorAll('input,textarea,button')].every(el=>{const r=el.getBoundingClientRect();
        return r.left>=bounds.left&&r.right<=bounds.right&&el.scrollWidth<=el.clientWidth;});})()""")
    js("document.querySelector('.roster-edit-save').click()")
    wait("!document.querySelector('.roster-edit')")
    capture('saved')
