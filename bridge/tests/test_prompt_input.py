import asyncio
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import control_server as control
import orrery_backend as backend
import pane_submission as submission


NATIVE_PROMPTS = json.loads(
    (Path(__file__).parent / 'fixtures/pane_slash_harnesses.json').read_text(encoding='utf-8'))


def native_meta(snapshot):
    return '\t'.join(['/tmp/fixture.sock', '100', '%1', '200', *snapshot['meta']])


def native_frame(snapshot):
    return submission.frame(native_meta(snapshot), snapshot['lines'], '%1')


NATIVE_CASES = [pytest.param(harness, case, id=f'{harness}-{case["case"]}')
                for harness, fixture in NATIVE_PROMPTS.items() for case in fixture['cases']]


def test_each_native_slash_picker_has_notice_and_slash_fixtures():
    assert set(NATIVE_PROMPTS) == set(submission.SLASH_PICKERS)
    for fixture in NATIVE_PROMPTS.values():
        cases = {case['case'] for case in fixture['cases']}
        assert {'slash-exact', 'slash-prefix', 'slash-idle', 'slash-busy', 'notice-short'} <= cases
        assert any(case.startswith('notice-long') for case in cases)


@pytest.mark.parametrize('harness,case', NATIVE_CASES)
def test_native_prompt_fixture(harness, case):
    assert native_frame(case.get('before', NATIVE_PROMPTS[harness]['before'])).empty
    observed = native_frame(case['view'])
    assert observed.selected_command == case['selected']
    assert submission.ready(observed, case['text']) is case['ready']
    if after := case.get('after'):
        assert native_frame(after).empty is case.get('accepted', case['ready'])
    if observed.dsh_clipped:
        # A different text ending cannot justify Enter with a clipped draft.
        assert not submission.ready(observed, case['text'] + ' another sentence')


@pytest.mark.parametrize('harness,case', NATIVE_CASES)
def test_watcher_enters_only_the_verified_native_draft(monkeypatch, harness, case):
    before = case.get('before', NATIVE_PROMPTS[harness]['before'])
    accepted = case.get('accepted', case['ready'])
    should_enter = case.get('enter', accepted)
    stage = before
    entered = []
    reasons = []
    elapsed = 0.0

    def tick(seconds):
        nonlocal elapsed
        elapsed += seconds

    def tmux(*args, input=None):
        nonlocal stage
        output = ''
        if args[0] == 'display-message':
            output = '\n'.join([native_meta(stage), *stage['lines'], ''])
        elif args[0] == 'load-buffer':
            assert input == case['text']
        elif args[0] == 'paste-buffer':
            stage = case['view']
        elif args[0] == 'send-keys':
            entered.append(args[-1])
            stage = case.get('after', before)
        else:
            assert args[0] == 'delete-buffer'
        return subprocess.CompletedProcess(args, 0, output, '')

    monkeypatch.setattr(submission, 'time', SimpleNamespace(monotonic=lambda: elapsed, sleep=tick))
    monkeypatch.setattr(submission, 'try_lock', lambda _: os.open(os.devnull, os.O_RDONLY))
    result = submission.submit(tmux, lambda: True, '%1', case['text'], on_wait=reasons.append)
    assert entered == (['C-m'] if should_enter else [])
    assert result == ('accepted' if accepted else 'unknown')
    if accepted:
        assert not reasons
    elif should_enter:
        assert reasons == ['enter_not_confirmed']
    else:
        assert reasons == (['completion_mismatch'] if case['selected'] else ['completion_unverified'])


@pytest.mark.asyncio
@pytest.mark.parametrize('harness,case', NATIVE_CASES)
async def test_cockpit_enters_only_the_verified_native_draft(monkeypatch, tmp_path, harness, case):
    bridge = control.TmuxControlBridge(control.ControlConfig('127.0.0.1', 0, 'Fixture', 'tmux',
                                                            history_dir=tmp_path))
    bridge.master_fd = 100
    monkeypatch.setattr(control, 'admit_command', lambda *args, **kwargs: None)
    monkeypatch.setattr(submission, 'try_lock', lambda _: os.open(os.devnull, os.O_RDONLY))
    monkeypatch.setattr(submission, 'POLL', .001)
    monkeypatch.setattr(submission, 'TIMEOUT', 1)
    before = case.get('before', NATIVE_PROMPTS[harness]['before'])
    accepted = case.get('accepted', case['ready'])
    should_enter = case.get('enter', accepted)
    stage = before
    entered = []

    async def write(data):
        nonlocal stage
        args = shlex.split(data.decode())
        rows = []
        if args[0] == 'display-message':
            rows = [native_meta(stage)]
        elif args[0] == 'capture-pane':
            rows = stage['lines']
        elif args[0] == 'load-buffer':
            assert Path(args[-1]).read_text() == case['text']
        elif args[0] == 'paste-buffer':
            stage = case['view']
        else:
            assert args[0] == 'send-keys'
            entered.append(args[-1])
            stage = case.get('after', before)
        pending = bridge._pending_blocks.popleft()
        pending.set_result(control.CommandResult(ok=True, lines=rows))

    monkeypatch.setattr(bridge, '_write_master', write)
    result = await bridge.submit_prompt('%1', case['text'])
    assert entered == (['C-m'] if should_enter else [])
    if accepted:
        assert result == 'accepted'
    elif should_enter:
        assert result == 'unknown'
    else:
        assert result == ('completion-mismatch' if case['selected'] else 'completion-unverified')


def test_slash_grace_does_not_treat_an_unreadable_picker_as_absent(monkeypatch):
    now = 0
    monkeypatch.setattr(submission, 'time', SimpleNamespace(monotonic=lambda: now))
    wait = submission.SlashMenuWait('/log')
    border = '─' * 32
    metadata = '/tmp/fixture.sock\t100\t%1\t200\t1\t0\t6\t1\tclaude'
    literal = submission.frame(metadata, [border, '❯ /log', border], '%1')
    unreadable = submission.frame(metadata.replace('\t1\t0\t6', '\t2\t0\t6'),
                                  ['    /login  Switch accounts', border, '❯ /log', border], '%1')
    assert unreadable.selected and unreadable.selected_command is None
    assert not wait.ready(literal)
    now = submission.SLASH_MENU_WAIT
    assert wait.ready(literal)
    assert not wait.ready(unreadable)
    now *= 3
    assert not wait.ready(literal)


@pytest.mark.asyncio
@pytest.mark.parametrize('successful', [True, False])
async def test_confirmed_input_uses_the_result_of_each_chunk(monkeypatch, tmp_path, successful):
    bridge = control.TmuxControlBridge(control.ControlConfig('127.0.0.1', 0, 'Fixture', 'tmux',
                                                            history_dir=tmp_path))
    bridge.master_fd = 100
    monkeypatch.setattr(control, 'admit_command', lambda *args, **kwargs: None)
    chunks = []

    async def write(data):
        chunks.append(data)
        pending = bridge._pending_blocks.popleft()
        asyncio.get_running_loop().call_soon(pending.set_result, control.CommandResult(
            ok=successful or len(chunks) == 1, lines=[]))

    monkeypatch.setattr(bridge, '_write_master', write)
    assert await bridge.send_input('%9', 'x' * 66, acknowledge=True) == ('accepted' if successful else 'unknown')
    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_receipt_is_bound_to_pane_session_and_bridge_incarnation(tmp_path):
    sent = []

    async def record(*args, **kwargs):
        sent.append((args, kwargs))
        return 'accepted'

    bridge = SimpleNamespace(panes={'%1': object()}, send_input=record, submit_prompt=record,
                             _incarnation='a' * 32, config=SimpleNamespace(session='Fixture', tmux_bin='tmux'))
    manager = backend.SessionBridgeManager('tmux', history_dir=tmp_path)
    manager.states['Fixture'] = SimpleNamespace(bridge=bridge)
    replies = []

    async def reply(value):
        replies.append(value)

    peer = SimpleNamespace(send_json=reply)
    packet = dict(type='input', session='Fixture', paneId='%1', incarnation='a' * 32, inputAck='1:1', data='\r')
    await manager.handle_message(peer, {'Fixture'}, dict(packet, incarnation='b' * 32))
    await manager.handle_message(peer, set(), packet)
    await manager.handle_message(peer, {'Fixture'}, packet)
    await manager.handle_message(peer, {'Fixture'}, dict(packet,type='submit-prompt',data='First\nSecond'))
    assert [entry['status'] for entry in replies] == ['refused', 'refused', 'accepted', 'accepted']
    assert sent == [(('%1', '\r'), {'acknowledge': True}), (('%1','First\nSecond'), {})]



def test_input_readiness_uses_the_editor_and_rejects_selected_completions():
    def observe(lines, cursor, column):
        return submission.frame(f'/tmp/fixture.sock\t100\t%1\t200\t{cursor}\t0\t{column}\t1\tclaude',
                                lines, '%1')

    assert observe(['› \x1b[2mAsk Codex to do anything\x1b[0m'], 0, 2).empty
    assert not observe(['› \x1b[2mAsk Codex to do anything\x1b[0m'], 0, 27).empty
    assert not observe(['❯ ', '  unsent continuation'], 0, 2).empty
    assert not observe(['❯ human draft'], 0, 13).empty
    assert observe(['────────', '❯ \x1b[3mTry something\x1b[0m', '────────'], 1, 2).empty
    assert not observe(['────────', '❯ Try something', '────────'], 1, 2).empty
    assert observe(['────────', 'deepseek ❯', '────────'], 1, 11).empty
    assert not observe(['>', ''], 0, 2).empty
    assert not submission.frame('/tmp/fixture.sock\t100\t%1\t200\t0\t0\t2\t0\tclaude',
                                ['❯ '], '%1').empty
    assert observe(['────────', '> Auto mode: edits & safe commands auto-approved (shift+tab to cycle)',
                    '────────', 'auto · Gemini 4 Neon · low'], 1, 2).empty
    assert submission.ready(observe(['────────', '> first', '  second', '────────', 'auto · Gemini'], 2, 8),
                            'first\nsecond')
    assert not submission.ready(observe(['❯ ', 'fixture text'], 0, 2), 'fixture text')
    assert not submission.ready(observe(['Pasting…', '❯ fixture text'], 1, 14), 'fixture text')
    assert submission.ready(observe(['❯ first', 'Pasting…'], 1, 8), 'first\nPasting…')
    assert not submission.ready(observe(['enter/tab insert · esc close', '', '› @fixture.png'],
                                        2, 14), '@fixture.png')
    assert not submission.ready(observe(['enter insert · esc close', '', '› $fixture-skill'],
                                        2, 16), '$fixture-skill')
    assert not submission.ready(observe(['  ❯ picture.png', '────────', '❯ @picture.png'], 2, 14), '@picture.png')
    assert submission.ready(observe(['❯ check', '  @picture.png'], 1, 14), 'check\n\n@picture.png ')
    assert submission.ready(observe(['❯ [Pasted text #1 +3 lines]'], 0, 26), 'four\nposted\nfixture\nlines')


def test_named_claude_editor_distinguishes_queue_hint_from_an_unsent_draft():
    notice = '        ✔ Update installed · Restart to update'
    name = '──────────────────────── Fixture Agent ─'
    lower = '─────────────────────────────────────────'
    hint = 'Press up to edit queued messages'
    styled = '❯\xa0\x1b[7mP\x1b[0;2mress up to edit queued messages\x1b[0m'

    def observe(editor, column=2, upper=name):
        return submission.frame(
            f'/tmp/fixture.sock\t100\t%1\t200\t3\t0\t{column}\t1\t2.1.331',
            ['✻ Enchanting…', notice, upper, editor, lower, 'Context 35% used'], '%1',
        )

    assert observe(styled).empty
    assert not observe(styled, column=3).empty
    assert not observe(styled, upper='unframed output').empty
    assert observe(f'❯ {hint}').draft == hint
    assert submission.ready(observe(f'❯ {hint}'), hint)


@pytest.mark.parametrize('flag,command,text,allowed', [
    ('', 'claude', 'first\nsecond', True),
    ('', 'codex', 'first\nsecond', True),
    ('', 'bash', 'one line', True),
    ('', 'bash', 'first\nsecond', False),
    ('', '/bin/-zsh', 'first\rsecond', False),
    ('', 'fish', 'first\tsecond', False),
    ('', 'sh', 'a\x1b[A', False),
    ('', '', 'first line', False),
    ('0', 'claude', 'one line', False),
    ('1', 'claude', 'first\nsecond', True),
])
def test_paste_mode_uses_tmux_flag_when_available(flag, command, text, allowed):
    metadata = f'/tmp/fixture.sock\t100\t%1\t200\t0\t0\t2\t{flag}\t{command}'
    empty = submission.frame(metadata, ['❯ '], '%1')
    assert (empty.empty and empty.allows_paste(text)) == allowed
    pasted = submission.frame(metadata, ['❯ [Pasted text #1 +1 line]'], '%1')
    assert submission.ready(pasted, text) == allowed


@pytest.mark.parametrize('initial,expected', [('❯ ', 'unknown'), ('❯ Human draft', 'refused')])
def test_watcher_never_sends_enter_without_visible_paste(monkeypatch, initial, expected):
    commands=[]
    def command(*args,input=None):
        commands.append(args[0])
        screen='/tmp/fixture.sock\t100\t%1\t200\t0\t0\t2\t1\tclaude\n'+initial+'\n'
        return subprocess.CompletedProcess(args,0,screen,'')
    monkeypatch.setattr(submission,'try_lock',lambda _:os.open(os.devnull,os.O_RDONLY))
    assert submission.submit(command,lambda:True,'%1','Hidden fixture',deadline=time.monotonic()+.15)==expected
    assert ('paste-buffer' in commands)==(expected=='unknown')
    assert 'send-keys' not in commands


def test_watcher_refuses_multiline_in_a_legacy_shell_before_loading_buffer(monkeypatch):
    def command(*args, input=None):
        assert args[0] == 'display-message', args
        screen = '/tmp/fixture.sock\t100\t%1\t200\t0\t0\t2\t\tbash\n❯ \n'
        return subprocess.CompletedProcess(args, 0, screen, '')

    monkeypatch.setattr(submission, 'try_lock', lambda _: os.open(os.devnull, os.O_RDONLY))
    assert submission.submit(command, lambda: True, '%1', 'first\nsecond') == 'refused'


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['cockpit', 'watcher'])
@pytest.mark.parametrize('editor,draft,selected,accepted', [
    ('claude', '/log', '/log', True),
    ('claude', '/log', '/login', False),
    ('claude-queue', 'A second prompt', '', True),
    ('claude-wrapped', '/compact', '/compact', True),
    ('claude-wrapped', '/compact', '/compact-later', False),
    ('codex', '/compact', '/compact', True),
    ('codex', '/comp', '/compact', False),
])
async def test_real_tmux_submission_observes_the_native_editor(
        tmp_path, monkeypatch, path, editor, draft, selected, accepted):
    tmux = shutil.which('tmux')
    if tmux is None:
        pytest.skip('tmux unavailable')
    recorder = tmp_path / 'record.py'
    entered = tmp_path / 'entered'
    recorder.write_text(r"""
import os, sys, tty
from pathlib import Path

tty.setraw(0)
editor, selected, record = sys.argv[1:]
border = '─' * 24
prompt = '›' if editor == 'codex' else '❯'

def show(draft='', menu=False, queued=False):
    if editor == 'claude-queue':
        if queued:
            draft = '\x1b[7mP\x1b[0;2mress up to edit queued messages\x1b[0m'
        rows = ['✻ Enchanting…', '        ✔ Update installed · Restart to update',
                f'{border} FixtureAgent ─', f'{prompt} {draft}', border,
                '  fixture-model | Sonnet | ctx: 35% used']
        caret = 4
    elif editor in ('claude', 'claude-wrapped'):
        rows = ([f'  ❯ {selected}  description'] if menu else [])
        if menu and editor == 'claude-wrapped':
            # A narrow pane wraps long descriptions under their option.
            rows += ['              that continues on the next row',
                     '    /fixture-skill  another long description',
                     '                    that wraps as well']
        rows += [border, f'{prompt} {draft}', border]
        caret = len(rows) - 1
    else:
        rows = ([f'\x1b[1;7m› {selected}  description\x1b[0m', ''] if menu else [])
        rows += [f'{prompt} {draft}', '', '  gpt-fixture default · Context 100% left']
        caret = len(rows) - 2
    column = 3 if queued else len(draft) + 3
    frame = '\x1b[2J\x1b[H' + '\r\n'.join(rows) + f'\x1b[{caret};{column}H'
    os.write(1, frame.encode())

os.write(1, b'\x1b[?2004h')
show()
raw = bytearray()
while not raw.endswith(b'\x1b[201~'):
    raw.extend(os.read(0, 4096))
assert raw.startswith(b'\x1b[200~')
show(raw[6:-6].decode(), menu=True)
assert os.read(0, 1) == b'\r'
Path(record).touch()
show(queued=editor == 'claude-queue')
while os.read(0, 1):
    pass
""")
    monkeypatch.setattr(submission, 'TIMEOUT', 2)
    env = {k: v for k, v in os.environ.items() if k not in ('TMUX', 'TMUX_PANE', 'LC_ALL')}
    env['LC_CTYPE'] = 'C.UTF-8'
    with tempfile.TemporaryDirectory(prefix='orrery-sl-', dir='/tmp') as temp:
        argv = [tmux, '-S', str(Path(temp).resolve() / 'tmux.sock'), '-f', '/dev/null']
        wrapper = tmp_path / 'tmux'
        wrapper.write_text('#!/bin/sh\nexec ' + shlex.join(
            ['env', 'LC_CTYPE=C.UTF-8', *argv]) + ' "$@"\n')
        wrapper.chmod(0o700)

        def call(*args, input=None):
            return subprocess.run([*argv, *args], env=env, timeout=5, input=input,
                                  capture_output=True, text=True)

        cmd = shlex.join([sys.executable, str(recorder), editor, selected, str(entered)])
        assert call('new-session', '-d', '-s', 'Fixture', cmd).returncode == 0
        bridge = control.TmuxControlBridge(control.ControlConfig(
            '127.0.0.1', 0, 'Fixture', str(wrapper), history_dir=tmp_path / 'history'))
        try:
            await bridge.start()
            pane = next(iter(bridge.panes))

            async def wait_for_editor():
                while True:
                    view = await asyncio.to_thread(submission.capture, call, pane)
                    if view and view.empty:
                        return
                    await asyncio.sleep(.025)

            await asyncio.wait_for(wait_for_editor(), timeout=6)
            if path == 'cockpit':
                result = await bridge.submit_prompt(pane, draft)
            else:
                result = await asyncio.to_thread(submission.submit, call, lambda: True, pane, draft)
            rejected = 'completion-mismatch' if path == 'cockpit' else 'unknown'
            assert result == ('accepted' if accepted else rejected)
            assert entered.exists() == accepted
        finally:
            await bridge.stop()
            call('kill-server')


@pytest.mark.asyncio
@pytest.mark.parametrize('composer_first', [True, False])
async def test_real_tmux_prompt_keeps_the_entire_paste_with_its_enter(tmp_path, monkeypatch, composer_first):
    tmux=shutil.which('tmux')
    if tmux is None:
        pytest.skip('tmux unavailable')
    log=tmp_path/'typed'
    release=tmp_path/'release-first-paste'
    recorder=tmp_path/'record.py'
    recorder.write_text(r"""
import json,os,select,sys,tty
from pathlib import Path

tty.setraw(0)
os.write(1,b'\x1b[?2004h'+ '❯ '.encode())
start,end=b'\x1b[200~',b'\x1b[201~'
release=Path(sys.argv[2])
first=True
with open(sys.argv[1], 'w', buffering=1) as out:
    while True:
        raw=bytearray()
        while end not in raw:
            chunk=os.read(0,4096)
            if not chunk:
                sys.exit(0)
            raw.extend(chunk)
        framed,_,early=raw.partition(end)
        assert framed.startswith(start) and not early, 'Input arrived before the editor rendered the paste'
        text=framed[len(start):].decode()
        os.write(1,'\r\x1b[2KPasting…'.encode())
        if first:
            # Keep the first draft unrendered until the competing sender has
            # reached the actual pane lock. Any key in this phase is premature.
            while not release.exists():
                readable,_,_=select.select([0],[],[],.02)
                assert not readable, 'Input arrived while the editor was still pasting'
            first=False
        view='[Pasted text #1 +3 lines]' if '\n' in text else text
        os.write(1,('\r\x1b[2K❯ '+view).encode())
        assert os.read(0,1)==b'\r'
        print(json.dumps(text),file=out)
        os.write(1,'\r\x1b[2K❯ '.encode())
""")
    # This deliberately stalls the editor for the test coordinator. The live
    # submission timeout is exercised separately, without a competing writer.
    fixture_timeout=20
    monkeypatch.setattr(submission,'TIMEOUT',fixture_timeout)
    loop=asyncio.get_running_loop()
    lock_contended=asyncio.Event()
    try_lock=submission.try_lock

    def observe_lock(frame):
        lock=try_lock(frame)
        if lock is None:
            loop.call_soon_threadsafe(lock_contended.set)
        return lock

    monkeypatch.setattr(submission,'try_lock',observe_lock)
    env={k:v for k,v in os.environ.items() if k not in ('TMUX','TMUX_PANE')}
    env['LC_CTYPE']='C.UTF-8'
    env.pop('LC_ALL',None)
    with tempfile.TemporaryDirectory(prefix='orrery-ct-', dir='/tmp') as temp:
        wrapper=tmp_path/'tmux'
        env['TMUX_TMPDIR']=str(Path(temp).resolve())
        argv=[tmux,'-L','orrery-compose-test','-f','/dev/null']
        wrapper.write_text('#!/bin/sh\nexec '+shlex.join(
            ['env','TMUX_TMPDIR='+env['TMUX_TMPDIR'],*argv])+' "$@"\n')
        wrapper.chmod(0o700)

        def call(*args, input=None):
            return subprocess.run([*argv,*args],env=env,capture_output=True,text=True,timeout=5,input=input)

        editor=shlex.join([sys.executable,str(recorder),str(log),str(release)])
        assert call('new-session','-d','-s','Fixture',editor).returncode==0
        bridge=control.TmuxControlBridge(control.ControlConfig('127.0.0.1',0,'Fixture',str(wrapper),history_dir=tmp_path/'history'))
        writers=[]
        try:
            await bridge.start()
            pane=next(iter(bridge.panes))
            text='Aだね\n'+'second line '*2500
            note='Synthetic Mail notice'

            async def wait_for_view(value, writer=None):
                screen=''

                async def observe():
                    nonlocal screen
                    while True:
                        result=await asyncio.to_thread(call,'capture-pane','-p','-t',pane)
                        assert result.returncode==0,result.stderr
                        screen=result.stdout
                        if value in screen:
                            return
                        if writer is not None and writer.done():
                            pytest.fail(f'Writer returned {writer.result()!r} before {value!r}: {screen!r}')
                        await asyncio.sleep(.02)

                try:
                    await asyncio.wait_for(observe(),timeout=fixture_timeout/2)
                except asyncio.TimeoutError:
                    pytest.fail(f'Terminal did not show {value!r}. Last capture: {screen!r}')

            async def wake():
                return await asyncio.to_thread(submission.submit,call,lambda:True,pane,note)

            await wait_for_view('❯')
            if composer_first:
                user=asyncio.create_task(bridge.submit_prompt(pane,text))
                writers.append(user)
                await wait_for_view('Pasting…', user)
                assert await wake()=='refused'
                await asyncio.wait_for(lock_contended.wait(),timeout=fixture_timeout/2)
                release.touch()
                assert await user=='accepted'
                assert await wake()=='accepted'
                expected=[text,note]
            else:
                mail=asyncio.create_task(wake())
                writers.append(mail)
                await wait_for_view('Pasting…', mail)
                user=asyncio.create_task(bridge.submit_prompt(pane,text))
                writers.append(user)
                await asyncio.wait_for(lock_contended.wait(),timeout=fixture_timeout/2)
                release.touch()
                assert await mail=='accepted'
                assert await user=='accepted'
                expected=[note,text]
            assert [json.loads(line) for line in log.read_text().splitlines()]==expected
        finally:
            release.touch(exist_ok=True)
            await asyncio.gather(*writers,return_exceptions=True)
            await bridge.stop()
            call('kill-server')


@pytest.mark.parametrize('styled,column,empty', [
    # Claude suggests a next prompt after a turn: dim text at the caret.
    ('\x1b[39m❯\xa0\x1b[2mrun the focused tests again\x1b[0m', 2, True),
    # A typed draft is never dim, wherever the caret is.
    ('\x1b[39m❯\xa0run the focused tests again', 2, False),
    ('\x1b[39m❯\xa0run the focused tests again', 29, False),
    # Typed text followed by a dim completion is still a draft.
    ('\x1b[39m❯\xa0run\x1b[2m the focused tests again\x1b[0m', 2, False),
])
def test_claude_prompt_suggestion_is_an_empty_editor(styled, column, empty):
    border = '─' * 24
    lines = [border, styled, border, '  fixture | Opus | ctx: 22% used']
    metadata = f'/tmp/fixture.sock\t100\t%1\t200\t1\t0\t{column}\t1\tclaude'
    assert submission.frame(metadata, lines, '%1').empty is empty


def test_claude_scrolled_draft_shows_only_its_end():
    # A tall draft scrolls inside Claude's frame and hides the prompt glyph.
    rows = ['\x1b[38;5;244m───\x1b[39m \x1b[2m↑ 3 more\x1b[0m \x1b[38;5;244m' + '─' * 20,
            '\x1b[39m  the middle of a long notification that wraps',
            '  and ends here. Fetch inbox to read the rest.',
            '\x1b[38;5;244m' + '─' * 24,
            '  fixture | Opus | ctx: 22% used']
    metadata = '/tmp/fixture.sock\t100\t%1\t200\t2\t0\t48\t1\tclaude'
    view = submission.frame(metadata, rows, '%1')
    assert view.scrolled and not view.empty
    text = ('ORRERY Mail notification: the start is hidden above, then '
            'the middle of a long notification that wraps and ends here. '
            'Fetch inbox to read the rest.')
    assert submission.ready(view, text)
    assert not submission.ready(view, 'A different prompt that ends elsewhere.')


def test_claude_scrolled_draft_with_a_named_border():
    # A named session draws its name at the right of the scrolled border.
    rows = ['─── ↑ 1 more ' + '─' * 20 + ' FixtureAgent ─',
            '  the middle of a long notification that wraps',
            '  and ends here. Fetch inbox to read the rest.',
            '─' * 40,
            '  fixture | Opus | ctx: 22% used']
    metadata = '/tmp/fixture.sock\t100\t%1\t200\t2\t0\t48\t1\tclaude'
    view = submission.frame(metadata, rows, '%1')
    assert view.scrolled and not view.empty
    assert submission.ready(view, 'ORRERY Mail notification: hidden start, then the middle of '
                            'a long notification that wraps and ends here. Fetch inbox to read the rest.')
