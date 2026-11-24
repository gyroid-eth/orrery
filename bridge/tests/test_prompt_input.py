import asyncio
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import control_server as control
import orrery_backend as backend


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


@pytest.mark.asyncio
async def test_real_tmux_prompt_keeps_the_entire_paste_with_its_enter(tmp_path):
    tmux=shutil.which('tmux')
    if tmux is None:
        pytest.skip('tmux unavailable')
    log=tmp_path/'typed'
    recorder=tmp_path/'record.py'
    recorder.write_text(
        "import os,sys,tty\n"
        "tty.setraw(0)\n"
        "os.write(1,b'\\x1b[?2004h')\n"
        "with open(sys.argv[1], 'wb', buffering=0) as out:\n"
        "    while chunk:=os.read(0,4096):out.write(chunk)\n")
    env={k:v for k,v in os.environ.items() if k not in ('TMUX','TMUX_PANE')}
    with tempfile.TemporaryDirectory(prefix='orrery-compose-test-') as temp:
        socket=str(Path(temp).resolve()/'tmux.sock')
        wrapper=tmp_path/'tmux'
        argv=[tmux,'-S',socket,'-f','/dev/null']
        wrapper.write_text('#!/bin/sh\nexec '+shlex.join(argv)+' "$@"\n')
        wrapper.chmod(0o700)
        def call(*args, **kwargs):
            return subprocess.run([*argv,*args],env=env,capture_output=True,timeout=5,check=True,**kwargs)
        call('new-session','-d','-s','Fixture',shlex.join([sys.executable,str(recorder),str(log)]))
        bridge=control.TmuxControlBridge(control.ControlConfig('127.0.0.1',0,'Fixture',str(wrapper),history_dir=tmp_path/'history'))
        try:
            await bridge.start()
            pane=next(iter(bridge.panes))
            text='Aだね\n'+'second line '*2500
            note='Synthetic Mail notice'
            def wake():
                call('load-buffer','-b','wake','-',input=note.encode())
                call('paste-buffer','-pd','-b','wake','-t',pane,';','send-keys','-t',pane,'C-m')
            assert (await asyncio.gather(bridge.submit_prompt(pane,text),asyncio.to_thread(wake)))[0]=='accepted'
            def frame(value):
                return b'\x1b[200~'+value.encode()+b'\x1b[201~\r'
            expected=[frame(text)+frame(note),frame(note)+frame(text)]
            for _ in range(100):
                if log.exists() and log.stat().st_size>=len(expected[0]):break
                await asyncio.sleep(.01)
            assert log.read_bytes() in expected
        finally:
            await bridge.stop()
            call('kill-server')
