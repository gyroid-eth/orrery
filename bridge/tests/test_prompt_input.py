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
        return submission.frame(f'/tmp/fixture.sock\t100\t%1\t200\t{cursor}\t0\t{column}\t1', lines, '%1')

    assert observe(['› \x1b[2mAsk Codex to do anything\x1b[0m'], 0, 2).empty
    assert not observe(['› \x1b[2mAsk Codex to do anything\x1b[0m'], 0, 27).empty
    assert not observe(['❯ ', '  unsent continuation'], 0, 2).empty
    assert not observe(['❯ human draft'], 0, 13).empty
    assert observe(['────────', '❯ \x1b[3mTry something\x1b[0m', '────────'], 1, 2).empty
    assert not observe(['────────', '❯ Try something', '────────'], 1, 2).empty
    assert observe(['────────', 'deepseek ❯', '────────'], 1, 11).empty
    assert not observe(['>', ''], 0, 2).empty
    assert not submission.frame('/tmp/fixture.sock\t100\t%1\t200\t0\t0\t2\t0',
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


@pytest.mark.parametrize('initial,expected', [('❯ ', 'unknown'), ('❯ Human draft', 'refused')])
def test_watcher_never_sends_enter_without_visible_paste(monkeypatch, initial, expected):
    commands=[]
    def command(*args,input=None):
        commands.append(args[0])
        screen='/tmp/fixture.sock\t100\t%1\t200\t0\t0\t2\t1\n'+initial+'\n'
        return subprocess.CompletedProcess(args,0,screen,'')
    monkeypatch.setattr(submission,'try_lock',lambda _:os.open(os.devnull,os.O_RDONLY))
    assert submission.submit(command,lambda:True,'%1','Hidden fixture',deadline=time.monotonic()+.15)==expected
    assert ('paste-buffer' in commands)==(expected=='unknown')
    assert 'send-keys' not in commands


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
    with tempfile.TemporaryDirectory(prefix='orrery-compose-test-') as temp:
        socket=str(Path(temp).resolve()/'tmux.sock')
        wrapper=tmp_path/'tmux'
        argv=[tmux,'-S',socket,'-f','/dev/null']
        wrapper.write_text('#!/bin/sh\nexec '+shlex.join(argv)+' "$@"\n')
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

            async def wait_for_view(value):
                screen=''

                async def observe():
                    nonlocal screen
                    while True:
                        result=await asyncio.to_thread(call,'capture-pane','-p','-t',pane)
                        assert result.returncode==0,result.stderr
                        screen=result.stdout
                        if value in screen:
                            return
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
                await wait_for_view('Pasting…')
                assert await wake()=='refused'
                await asyncio.wait_for(lock_contended.wait(),timeout=fixture_timeout/2)
                release.touch()
                assert await user=='accepted'
                assert await wake()=='accepted'
                expected=[text,note]
            else:
                mail=asyncio.create_task(wake())
                writers.append(mail)
                await wait_for_view('Pasting…')
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
