"""Run the cockpit WebSocket and watcher against terminal editors in isolated tmux."""

import asyncio
import json
import os
from pathlib import Path
import select
import shlex
import shutil
import subprocess
import sys
import tempfile

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
import pytest

import orrery_backend as backend
import pane_submission as submission


COMMANDS = {
    'claude': ('/log', '/compact', '/help', '/model', '/config'),
    'codex': ('/status', '/model'),
    'dsh': ('/help', '/model'),
    'hermes': ('/help', '/model'),
    'agy': ('/help', '/model'),
}
PLAIN = 'ORRERY Mail notification: synthetic check.'
SLASH_VIEWS = {
    ('claude', '/help'): ['Help  General   Commands   Custom commands', '←/→ to switch · Esc to close'],
    ('claude', '/model'): ['Select model', 's to use this session only · Enter to save · Esc to cancel'],
    ('claude', '/config'): ['│ ⌕ Search settings… │', '↓ to navigate · ↑ to switch tabs · Esc to go back'],
    ('codex', '/model'): ['Select Model and Effort', '› 1. GPT-6.1-Sol', 'enter select · esc back'],
    ('dsh', '/model'): ['Model', 'Tab / Shift+Tab providers · ↑/↓ model · Enter select · Esc cancel'],
    ('hermes', '/model'): ['╭─ cli.tui.picker_title_provider ─╮', '│ │', '│ cli.tui.picker_current_hint │'],
    ('agy', '/help'): ['Antigravity CLI   general    commands    shortcuts',
                       'Keyboard: ↑/↓ Navigate  ←/→ Switch View  esc Close', 'auto · Gemini 3.8 Flash (Low) · low'],
    ('agy', '/model'): ['Switch Model', 'Keyboard: ↑/↓ Navigate  ←/→ Effort  enter Select',
                        'esc Go Back', 'auto · Gemini 3.8 Flash (Low) · low'],
}


def run_editor(harness, state, width, entered):
    """Draw each native prompt and picker with a raw bracketed-paste receiver."""
    import tty

    tty.setraw(0)
    border = '─' * width
    busy = state == 'busy'

    def show(text=''):
        selected = text if text in COMMANDS[harness] else None
        if harness == 'claude' and text == '/lo':
            selected = '/login'
        if harness == 'claude' and busy and text == '/compact':
            selected = None
        before = ['', '']
        hint = ''
        if harness == 'claude':
            if selected:
                before += [f'  ❯ {selected}  Fixture command']
                if selected == '/log':
                    before += ['    /login  Sign in', '    /logout  Sign out']
            if text == '/log ':
                hint = ' \x1b[38;5;246m<テーマ名> [プロジェクト]\x1b[39m'
            before += [border]
            prompt = '❯\xa0'
            after = [border, '  Fixture status | Opus | ctx: 22% used', '  ⏵⏵ auto mode on']
            if busy:
                after[-1] += ' · esc to interrupt'
        elif harness == 'codex':
            if busy:
                before = ['• Working (1s • esc to interrupt)', '']
            if selected:
                before += [f'\x1b[1;7m› {selected}  Fixture command\x1b[0m', '']
            prompt = '› '
            after = ['', '  gpt-fixture default · Context 100% left']
        elif harness == 'dsh':
            if selected:
                before += ['╭─ commands · 1 item ─╮', f'│ ❯ {selected[1:]}  Fixture │', '╰' + '─' * 22 + '╯']
            before += [border]
            prompt = '⌸ ❯ '
            after = [border, '  dsh · Fixture']
            if busy:
                after += ['   esc to interrupt']
        elif harness == 'hermes':
            before += ['  ☤ model │ 0/128K │ ⏱ 3s' if busy else '  ☤ Hermes', border]
            prompt = '☤ ❯ ' if busy else '❯ '
            after = [border]
            if selected:
                after += [f'\x1b[48;5;237m{selected}  Fixture command\x1b[0m']
        else:
            before += [border]
            prompt = '> '
            after = [border]
            if selected:
                after += [f'> {selected}  Fixture command', '↑/↓ Navigate · enter Select · tab Complete']
            after += ['esc to cancel  plan · Fixture' if busy else '  plan · Fixture']
        rows = [*before, prompt + text + hint, *after]
        cursor = f'\x1b[{len(before) + 1};{len(prompt) + len(text) + 1}H'
        os.write(1, ('\x1b[2J\x1b[H' + '\r\n'.join(rows) + cursor).encode())

    os.write(1, b'\x1b[?2004h')
    show()
    start, end = b'\x1b[200~', b'\x1b[201~'
    while True:
        first = os.read(0, 1)
        if not first:
            return
        if first == b'\x03' or (first == b'\x1b' and not select.select([0], [], [], .05)[0]):
            expected_key = b'\x03' if harness == 'hermes' else b'\x1b'
            assert first == expected_key and (busy or harness != 'hermes')
            with entered.open('a') as output:
                output.write(json.dumps('interrupt:' + first.hex()) + '\n')
            busy = False
            show()
            continue
        assert first + bytes(os.read(0, 1)[0] for _ in start[1:]) == start
        raw = bytearray()
        while not raw.endswith(end):
            char = os.read(0, 1)
            if not char:
                return
            raw.extend(char)
        draft = raw[:-len(end)].decode()
        show(draft)
        assert os.read(0, 1) == b'\r'
        with entered.open('a') as output:
            output.write(json.dumps(draft) + '\n')
        modal_command = '/model' if state == 'wrong-modal' else draft
        if modal := SLASH_VIEWS.get((harness, modal_command)):
            os.write(1, ('\x1b[?2004l\x1b[2J\x1b[H' + '\r\n'.join(modal)).encode())
            assert os.read(0, 1) == b'\x1b'
            os.write(1, b'\x1b[?2004h')
        show()


async def receive(ws, kind):
    while True:
        message = await ws.receive_json(timeout=9)
        assert message['type'] != 'error', message
        if message['type'] == kind:
            return message


@pytest.mark.asyncio
@pytest.mark.parametrize('harness', COMMANDS)
@pytest.mark.parametrize('state', ['idle', 'busy'])
@pytest.mark.parametrize('width', [80, 110])
async def test_prompt_submission_routes(monkeypatch, harness, state, width):
    await check_routes(monkeypatch, harness, state, width)


@pytest.mark.asyncio
@pytest.mark.parametrize('text,status,draft', [
    ('/lo', 'completion-mismatch', '/lo'),
    ('/log ', 'completion-unverified', '/log'),
])
async def test_claude_control_mode_does_not_enter_unverified_slash(monkeypatch, text, status, draft):
    await check_routes(monkeypatch, 'claude', 'busy', 110, rejected=(text, status, draft))


@pytest.mark.asyncio
async def test_unrelated_slash_view_does_not_confirm_submission(monkeypatch):
    await check_routes(monkeypatch, 'claude', 'wrong-modal', 110)


async def check_routes(monkeypatch, harness, state, width, *, rejected=None):
    tmux = shutil.which('tmux')
    if tmux is None:
        pytest.skip('tmux unavailable')
    with tempfile.TemporaryDirectory(prefix='oc-submit-', dir='/tmp') as directory:
        root = Path(directory).resolve()
        entered = root / 'entered.jsonl'
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'USER', 'LOGNAME') if key in os.environ}
        env.update(HOME=str(root), TMUX_TMPDIR=str(root), LC_CTYPE='C.UTF-8',
                   PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        argv = [tmux, '-L', 'submission', '-f', '/dev/null']
        wrapper = root / 'tmux'
        wrapper.write_text('#!/bin/sh\nexec ' + shlex.join(
            ['env', '-i', *(key + '=' + value for key, value in env.items()), *argv]) + ' "$@"\n')
        wrapper.chmod(0o700)

        def call(*args, input=None):
            return subprocess.run([*argv, *args], cwd=root, env=env, input=input,
                                  text=True, capture_output=True, timeout=5)

        editor = shlex.join([sys.executable, __file__, harness, state, str(width), str(entered)])
        launch = call('new-session', '-d', '-s', 'Fixture', '-x', str(width), '-y', '32', editor)
        assert launch.returncode == 0, launch.stderr
        try:
            # Keep startup's catalog and recorder traffic inside the fixture.
            monkeypatch.setattr(backend, 'DASHBOARD_URL', 'http://127.0.0.1:1')
            monkeypatch.setenv('ORRERY_HISTORY_DIR', str(root / 'history'))
            app = backend.create_app(backend.LegacyTargetBoundary(str(wrapper), home=root, environ=env))
            async with TestServer(app, host='127.0.0.1') as server, ClientSession() as client:
                async with client.ws_connect(server.make_url('/ws')) as ws:
                    await ws.send_json({'type': 'attach', 'session': 'Fixture'})
                    reset = await receive(ws, 'reset')
                    pane = reset['panes'][0]['paneId']

                    async def get_view():
                        return await asyncio.to_thread(submission.capture, call, pane)

                    async def wait_for_editor():
                        while not ((view := await get_view()) and view.empty):
                            await asyncio.sleep(.025)

                    await asyncio.wait_for(wait_for_editor(), timeout=5)
                    seen = []
                    routes = ('cockpit',) if rejected else ('cockpit', 'watcher')
                    for route in routes:
                        texts = (rejected[0],) if rejected else (*COMMANDS[harness], PLAIN)
                        if state == 'wrong-modal':
                            texts = ('/help',)
                        for text in texts:
                            expected = 'accepted'
                            if rejected:
                                expected = rejected[1]
                            elif route == 'watcher' and harness == 'hermes' and state == 'busy' and text == PLAIN:
                                expected = 'refused'
                            elif state == 'wrong-modal':
                                expected = 'unknown'

                            if route == 'cockpit':
                                await ws.send_json(dict(type='submit-prompt', paneId=pane, session='Fixture',
                                                        incarnation=reset['incarnation'], inputAck='1:1', data=text))
                                status = (await receive(ws, 'input-ack'))['status']
                            else:
                                status = await asyncio.to_thread(submission.submit, call, lambda: True, pane, text)

                            view = await get_view()
                            if expected == 'accepted' or state == 'wrong-modal':
                                seen.append(text)
                            actual = [json.loads(line) for line in entered.read_text().splitlines()] if entered.exists() else []
                            assert status == expected, (harness, state, width, route, text, view, actual)
                            assert actual == seen
                            if rejected:
                                assert view.draft == rejected[2]
                            elif (harness, text) in SLASH_VIEWS:
                                assert view.slash_view == (harness, '/model' if state == 'wrong-modal' else text)
                                resume = call('send-keys', '-t', pane, 'Escape')
                                assert resume.returncode == 0, resume.stderr
                                await asyncio.wait_for(wait_for_editor(), timeout=5)
                            else:
                                assert view.empty

                    if not rejected and state != 'wrong-modal':
                        await ws.send_json(dict(type='interrupt', paneId=pane, session='Fixture',
                                                incarnation=reset['incarnation'], inputAck='1:2'))
                        status = (await receive(ws, 'input-ack'))['status']
                        if state == 'busy':
                            assert status == 'accepted'
                            seen.append('interrupt:03' if harness == 'hermes' else 'interrupt:1b')
                        elif harness == 'hermes':
                            assert status == 'refused'
                        else:
                            assert status == 'sent'
                            # A tmux acknowledgement can precede the editor's read.
                            for _ in range(40):
                                if len(entered.read_text().splitlines()) > len(seen):
                                    break
                                await asyncio.sleep(.025)
                            seen.append('interrupt:1b')
                        assert [json.loads(line) for line in entered.read_text().splitlines()] == seen
                        view = await get_view()
                        assert view.empty and not view.running
        finally:
            call('kill-server')


if __name__ == '__main__':
    run_editor(*sys.argv[1:3], int(sys.argv[3]), Path(sys.argv[4]))
