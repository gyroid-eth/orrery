"""Run the cockpit WebSocket and watcher against terminal editors in isolated tmux."""

import asyncio
import contextlib
import json
import os
from pathlib import Path
import select
import shlex
import shutil
import subprocess
import sys
import tempfile
from unicodedata import east_asian_width

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
import pytest

import mobile_access
import mobile_input
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
LINK = 'https://example.com'
BUSY_STATES = {'busy', 'tool', 'starting'}
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


def notice_text(size):
    body = ('第3ターン「みかん」は「み」で始まっているので、しりとりとしては成立しています。 ⏎ '
            'ただし「ん」で終わるため、通常ルールでは負けになります。 ⏎ ')
    return ('ORRERY Mail notification: message from Tester [normal]: しりとり. '
            'Body (complete; no inbox fetch needed): ' + body * 30)[:size]


def wrap_notice(prompt, text, width):
    rows = ['']
    column = 0
    for char in prompt + text:
        cells = 2 if east_asian_width(char) in ('F', 'W') else 1
        if column + cells > width:
            rows.append('')
            column = 0
        rows[-1] += char
        column += cells
    if column == width:
        rows.append('')
        column = 0
    return rows, column


def notice_rows(harness, prompt, text, width):
    if harness == 'dsh' and len(text) >= 900:
        chars = len(text.encode('utf-16-le')) // 2
        pill = f'\x1b[38;5;145m▸ 1 lines・{chars} chars・hover to peek\x1b[39m'
        return [prompt + ' ' * (width - len(prompt) - 1) + '⛶', '    ' + pill, ''], len(prompt)
    if len(text) >= 900:
        summary = {
            'claude': '[Pasted text #1]',
            'codex': f'[Pasted Content {len(text)} chars]',
            'agy': f'[Pasted text #1 {len(text)} chars]',
        }.get(harness)
        if summary is not None:
            styled = f'\x1b[38;5;6m{summary}\x1b[39m' if harness == 'codex' else summary
            return [prompt + styled], len(prompt) + len(summary)
    if harness == 'dsh':
        rows, column = wrap_notice('', text, width - len(prompt))
        return [prompt + rows[0], *rows[1:]], column if len(rows) > 1 else column + len(prompt)
    rows, column = wrap_notice(prompt, text, width)
    return rows[-8:] if harness == 'hermes' else rows, column


def run_editor(harness, state, width, entered):
    """Draw each native prompt and picker with a raw bracketed-paste receiver."""
    import tty

    tty.setraw(0)
    border = '─' * width
    busy = state in BUSY_STATES

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
            if busy and state in ('tool', 'starting'):
                before += ['\x1b[3m\x1b[38;5;136m  💻 sleep 90 + 1 command  ( 23.1s)\x1b[0m', '']
                if state == 'starting':
                    before += ['Initializing agent…']
                before += [' ☤ model │ 0/128K │ ◷ 2.0s', border]
            else:
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
        if state == 'narrow-mail':
            draft, column = notice_rows(harness, prompt, text, width)
            if harness == 'hermes' and width < 60:
                after = []
        else:
            draft = (prompt + text + hint).split('\n')
            column = len(draft[-1]) - len(hint)
            if state == 'links':
                linked = f'\x1b]8;;{LINK}\x1b\\{LINK}\x1b]8;;\x1b\\'
                draft = [row.replace(LINK, linked) for row in draft]
        rows = [*before, *draft, *after]
        cursor = f'\x1b[{len(before) + len(draft)};{column + 1}H'
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
        if state == 'mobile' and harness == 'hermes':
            # Hermes may still be processing the paste when Enter is already
            # readable. Hold back its redraw and consume an early Enter.
            if select.select([0], [], [], .15)[0]:
                assert os.read(0, 1) == b'\r'
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


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['tool', 'starting'])
async def test_hermes_interrupt_requires_current_activity(monkeypatch, state):
    await check_routes(monkeypatch, 'hermes', state, 110)


@pytest.mark.asyncio
@pytest.mark.parametrize('legacy', ['wrapper', 'shell'])
async def test_multiline_submission_without_tmux_paste_flag(monkeypatch, legacy):
    await check_routes(monkeypatch, 'hermes', 'idle', 110, legacy=legacy)


@pytest.mark.asyncio
@pytest.mark.parametrize('harness', COMMANDS)
async def test_mobile_input_and_shared_multiline_composer_in_private_tmux(monkeypatch, harness):
    await check_routes(monkeypatch, harness, 'mobile', 80, mobile=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('harness', COMMANDS)
@pytest.mark.parametrize('width', [40, 46, 90])
async def test_narrow_mail_submission(monkeypatch, harness, width):
    await check_routes(monkeypatch, harness, 'narrow-mail', width, notices=(150, 300, 900))


@pytest.mark.asyncio
@pytest.mark.parametrize('harness', COMMANDS)
async def test_link_uses_real_tmux_control_capture_to_confirm_submit(monkeypatch, harness):
    await check_routes(monkeypatch, harness, 'links', 81)


async def check_routes(monkeypatch, harness, state, width, *, rejected=None, legacy=None, mobile=False, notices=()):
    tmux = shutil.which('tmux')
    if tmux is None:
        pytest.skip('tmux unavailable')
    with tempfile.TemporaryDirectory(prefix='oc-submit-', dir='/tmp') as directory:
        root = Path(directory).resolve()
        entered = root / 'entered.jsonl'
        env = {key: os.environ[key] for key in ('PATH', 'LANG', 'USER', 'LOGNAME') if key in os.environ}
        env.update(HOME=str(root), TMUX_TMPDIR=str(root), LC_CTYPE='C.UTF-8',
                   PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        if legacy:
            # Keep tmux's real bracketed paste behaviour but hide its format,
            # as on tmux 3.6. Both routes issue commands to the real private tmux.
            monkeypatch.setattr(submission, 'METADATA', submission.METADATA.replace(
                '#{bracket_paste_flag}', '#{orrery_test_unavailable_flag}'))
            env.update(PS1='❯ ', INPUTRC='/dev/null')
        argv = [tmux, '-L', 'submission', '-f', '/dev/null']
        wrapper = root / 'tmux'
        wrapper.write_text('#!/bin/sh\nexec ' + shlex.join(
            ['env', '-i', *(key + '=' + value for key, value in env.items()), *argv]) + ' "$@"\n')
        wrapper.chmod(0o700)

        def call(*args, input=None):
            return subprocess.run([*argv, *args], cwd=root, env=env, input=input,
                                  text=True, capture_output=True, timeout=5)

        fixture = __file__
        if legacy == 'wrapper':
            fixture = root / 'bin' / 'hermes'
            fixture.parent.mkdir()
            fixture.write_text(f'import runpy\nrunpy.run_path({__file__!r}, run_name="__main__")\n')
        editor = shlex.join([sys.executable, str(fixture), harness, state, str(width), str(entered)])
        if legacy == 'wrapper':
            launch_args = ['/bin/bash', '-c', editor + '; :']
        elif legacy == 'shell':
            launch_args = ['/bin/bash', '--noprofile', '--norc', '-i']
        else:
            launch_args = [editor]
        launch = call('new-session', '-d', '-s', 'Fixture', '-x', str(width),
                      '-y', '27' if notices else '32', *launch_args)
        assert launch.returncode == 0, launch.stderr
        try:
            # Keep startup's catalog and recorder traffic inside the fixture.
            monkeypatch.setattr(backend, 'DASHBOARD_URL', 'http://127.0.0.1:1')
            monkeypatch.setenv('ORRERY_HISTORY_DIR', str(root / 'history'))
            app = backend.create_app(backend.LegacyTargetBoundary(str(wrapper), home=root, environ=env),
                                     mobile_input_enabled=mobile)
            if mobile:
                class Resolver:
                    def read(self, bridge, pane_id, deadline):
                        view = submission.capture(call, pane_id)
                        assert view is not None and view.pane == pane_id
                        info = bridge.panes[pane_id]
                        return dict(session=bridge.config.session, pane_id=pane_id, incarnation=bridge._incarnation,
                                    identity=[str(view.socket), view.server, view.pane, view.process], height=info.height)

                    @contextlib.contextmanager
                    def admission(self, row, deadline):
                        proof = self.read(row['bridge'], row['pane_id'], deadline)
                        if proof != row['proof']:
                            raise mobile_input.InputRefused('input_target_changed')
                        yield proof

                app[mobile_access.INPUT_KEY].resolver = Resolver()
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
                    if legacy:
                        view = await get_view()
                        assert view.bracketed is None and view.foreground_command == 'bash'
                    seen = []
                    if mobile:
                        scope = dict(contract=mobile_input.CONTRACT, owner='fixture@example.invalid', reader_epoch='1' * 32)

                        async def phone(operation, **values):
                            origin = str(server.make_url('/')).rstrip('/')
                            headers = {'Origin': origin, 'X-ORRERY-Mobile-Contract': mobile_input.CONTRACT}
                            async with client.post(server.make_url('/_mobile/terminal/' + operation),
                                                   json={**scope, **values}, headers=headers) as response:
                                payload = await response.json()
                                assert response.status == 200, payload
                                return payload

                        scope['epoch'] = (await phone('capability'))['epoch']
                        targets = await phone('targets', name='Fixture')
                        choice = targets['targets'][0]['choice']
                        for text in ('English input from the phone.', 'スマホから日本語を送ります。'):
                            preview = await phone('preview', choice=choice)
                            prepared = await phone('prepare', choice=choice, revision=preview['target']['revision'], text=text)
                            receipt = dict(intent=prepared['intent'], confirmation=prepared['confirmation'])
                            sent = await phone('commit', **receipt)
                            assert sent['state'] == 'accepted', (harness, sent)
                            assert await phone('commit', **receipt) == sent
                            seen.append(text)
                            assert [json.loads(line) for line in entered.read_text().splitlines()] == seen
                            assert (await get_view()).empty

                        # The phone keeps its one-line review contract. Exercise
                        # multiline through the same shared desktop compositor.
                        text = 'A multiline prompt.\n日本語を含む二行目です。'
                        await ws.send_json(dict(type='submit-prompt', paneId=pane, session='Fixture',
                                                incarnation=reset['incarnation'], inputAck='1:1', data=text))
                        assert (await receive(ws, 'input-ack'))['status'] == 'accepted'
                        seen.append(text)
                        assert [json.loads(line) for line in entered.read_text().splitlines()] == seen
                        assert (await get_view()).empty
                        return

                    routes = ('cockpit',) if rejected else ('cockpit', 'watcher')
                    for route in routes:
                        texts = (rejected[0],) if rejected else (*COMMANDS[harness], PLAIN)
                        if notices:
                            texts = tuple(notice_text(size) for size in notices)
                        if state == 'wrong-modal':
                            texts = ('/help',)
                        if state == 'links':
                            texts = ('Plain control message.', LINK, f'Open this test page.\n{LINK}')
                        if legacy:
                            texts = ('> Earlier message\n\nHere is my reply.',) if legacy == 'wrapper' else (
                                f'printf touched > {entered}\n:',)
                        for text in texts:
                            expected = 'accepted'
                            if rejected:
                                expected = rejected[1]
                            elif route == 'watcher' and harness == 'hermes' and state in BUSY_STATES and text == PLAIN:
                                expected = 'refused'
                            elif state == 'wrong-modal':
                                expected = 'unknown'
                            elif legacy == 'shell':
                                expected = 'paste-unavailable' if route == 'cockpit' else 'refused'

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

                    if not rejected and not legacy and not notices and state != 'wrong-modal':
                        await ws.send_json(dict(type='interrupt', paneId=pane, session='Fixture',
                                                incarnation=reset['incarnation'], inputAck='1:2'))
                        status = (await receive(ws, 'input-ack'))['status']
                        if state in ('busy', 'tool'):
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
                        assert view.hermes_busy == (state == 'starting')
        finally:
            call('kill-server')


if __name__ == '__main__':
    run_editor(*sys.argv[1:3], int(sys.argv[3]), Path(sys.argv[4]))
