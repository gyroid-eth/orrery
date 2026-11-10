"""Approval review regressions using only a private synthetic pane."""
import asyncio
import json
import subprocess

import pytest

from reader_approval import ApprovalCoordinator, parse_screen
from test_reader_approval import Bridge, MCP, READ
from approval_fixture import fake_pane


@pytest.mark.parametrize("command", ["codex", "node"])
def test_quoted_complete_menu_is_not_approval(command):
    # Keep the original unframed reproduction as well as the complete live
    # frame, so rejecting missing guide lines cannot mask the quote guard.
    for menu in (MCP, '\n'.join(MCP.splitlines()[1:-1])):
        text='Example of a previous approval screen; do not answer this example:\n'+menu
        assert parse_screen(text,command,'codex') is None


def test_sent_prompt_cannot_rearm_after_resize(fake_pane,tmp_path):
    from control_server import TmuxControlBridge, ControlConfig
    async def run():
        b=TmuxControlBridge(ControlConfig('127.0.0.1',0,'ApprovalFixture',str(fake_pane.wrapper),history_dir=tmp_path/'history'))
        await b.start()
        try:
            fake_pane.change(MCP,stay=True)
            await asyncio.sleep(.15)
            c=ApprovalCoordinator(b, harness_resolver=fake_pane.harness);owner=object()
            first=await c.inspect(fake_pane.pane,owner)
            assert first['state']=='ready',first
            sent=await c.answer(fake_pane.pane,owner,first['token'],1,'first')
            assert sent['state']=='sent',sent
            await b.send_command(['resize-window','-t','ApprovalFixture:0','-x','179','-y','40'])
            await asyncio.sleep(.15)
            next_=await c.inspect(fake_pane.pane,owner)
            print('AFTER RESIZE',next_)
            if next_['state']=='ready':
                result=await c.answer(fake_pane.pane,owner,next_['token'],1,'second')
                await asyncio.sleep(.1)
                print('SECOND SEND',result,'KEYS',fake_pane.keys.read_text())
            assert next_['state']!='ready','same visible prompt must remain consumed after resize'
        finally:await b.stop()
    asyncio.run(run())


def test_output_during_final_metadata_cannot_authorize_old_capture(fake_pane,tmp_path):
    from control_server import TmuxControlBridge, ControlConfig
    async def run():
        b=TmuxControlBridge(ControlConfig('127.0.0.1',0,'ApprovalFixture',str(fake_pane.wrapper),history_dir=tmp_path/'history'))
        await b.start()
        try:
            await asyncio.sleep(.1)
            c=ApprovalCoordinator(b, harness_resolver=fake_pane.harness);owner=object()
            first=await c.inspect(fake_pane.pane,owner)
            assert first['state']=='ready',first
            original=b._approval_command_locked
            captured=False
            async def command(args,**kw):
                nonlocal captured
                result=await original(args,**kw)
                if args[0]=='capture-pane' and not captured:
                    captured=True
                    fake_pane.change(MCP.replace('message_id: 9','message_id: 999'))
                    for _ in range(100):
                        if 'message_id: 999' in fake_pane.capture():
                            await asyncio.sleep(.03)
                            break
                        await asyncio.sleep(.02)
                return result
            b._approval_command_locked=command
            result=await c.answer(fake_pane.pane,owner,first['token'],1,'race')
            await asyncio.sleep(.1)
            print('RACE RESULT',result,'KEYS',fake_pane.keys.read_text() if fake_pane.keys.exists() else 'none')
            assert not fake_pane.keys.exists(),'new prompt was answered using the old captured screen'
        finally:await b.stop()
    asyncio.run(run())


def test_review_unrelated_pane_output(fake_pane,tmp_path):
    from control_server import TmuxControlBridge,ControlConfig
    from reader_approval import ApprovalCoordinator
    subprocess.run([*fake_pane.prefix,'split-window','-v','-t',fake_pane.pane,'-l','8','node','-e',"setInterval(()=>process.stdout.write('.'),1)"],check=True)
    async def run():
        b=TmuxControlBridge(ControlConfig('127.0.0.1',0,'ApprovalFixture',str(fake_pane.wrapper),history_dir=tmp_path/'history'))
        await b.start()
        try:
            c=ApprovalCoordinator(b, harness_resolver=fake_pane.harness);states=[];changes=[]
            original_record=b._record_and_broadcast;original_capture=b.approval_capture_locked
            b._review_recent=[]
            def record_event(pane_id,data):
                b._review_recent.append(pane_id);original_record(pane_id,data)
            async def capture(pane_id):
                value=await original_capture(pane_id);b._review_recent=[];return value
            b._record_and_broadcast=record_event;b.approval_capture_locked=capture
            for i in range(15):
                text=MCP.replace('message_id: 9','message_id: '+str(i+100))
                fake_pane.change(text,stay=True)
                for _ in range(50):
                    await asyncio.sleep(.025)
                    v=await c.inspect(fake_pane.pane,run)
                    if v.get('text')==text:break
                assert v.get('text')==text,v
                result=await c.answer(fake_pane.pane,run,v['token'],1,'op-'+str(i))
                states.append(result['state']);changes.append((result,list(b._review_recent)))
            print('NOISY_OTHER_PANE',states);print('TARGET',fake_pane.pane,'REFUSAL_CHANGES',[entry for entry in changes if entry[0]['state']=='refused'])
            assert set(states)=={'sent'},states
        finally:await b.stop()
    asyncio.run(run())



def test_review_screen_changes_during_final_capture(fake_pane,tmp_path):
    from control_server import TmuxControlBridge,ControlConfig
    from reader_approval import ApprovalCoordinator
    async def run():
        b=TmuxControlBridge(ControlConfig('127.0.0.1',0,'ApprovalFixture',str(fake_pane.wrapper),history_dir=tmp_path/'history'))
        await b.start()
        try:
            c=ApprovalCoordinator(b, harness_resolver=fake_pane.harness)
            for _ in range(50):
                await asyncio.sleep(.025);first=await c.inspect(fake_pane.pane,run)
                if first.get('state')=='ready':break
            assert first['state']=='ready',first
            original=b._approval_command_locked
            async def command(args,**kwargs):
                value=await original(args,**kwargs)
                if args[0]=='capture-pane':
                    fake_pane.change(MCP.replace('message_id: 9','message_id: 10'),stay=True)
                    for _ in range(50):
                        await asyncio.sleep(.01)
                        if 'message_id: 10' in fake_pane.capture():break
                    # Deliver the target's actual output before the final metadata read.
                    await asyncio.sleep(.03)
                    assert 'message_id: 10' in fake_pane.capture()
                return value
            b._approval_command_locked=command
            result=await c.answer(fake_pane.pane,run,first['token'],1,'changed-during-capture')
            print('CAPTURE_RACE',result,'SCREEN',fake_pane.capture(),'KEYS',fake_pane.keys.read_text() if fake_pane.keys.exists() else 'none')
            assert result['state']!='sent' and not fake_pane.keys.exists(),result
        finally:await b.stop()
    asyncio.run(run())



@pytest.mark.parametrize('text,expected', [(MCP,'codex'), (READ,'claude')])
def test_node_requires_matching_server_harness(text,expected):
    assert parse_screen(text,'node',expected)
    assert parse_screen(text,'node') is None
    assert parse_screen(text,'node','unknown') is None
    assert parse_screen(text,'node','claude' if expected=='codex' else 'codex') is None


@pytest.mark.parametrize('text,command',[(MCP,'codex'),(READ,'claude')])
@pytest.mark.parametrize('change',['missing-prefix','missing-footer','quoted','composer','shortcuts'])
def test_menu_requires_its_complete_live_frame(text,command,change):
    if change=='missing-prefix':text=text.split('\n',1)[1]
    elif change=='missing-footer':text=text.rsplit('\n',1)[0]
    elif change=='quoted':text='> '+text.replace('\n','\n> ')
    elif change=='composer':text+='\n› Type a message'
    else:text+='\n? for shortcuts'
    assert parse_screen(text,command) is None


@pytest.mark.parametrize('unknown',[False,True])
def test_consumed_content_survives_selection_and_geometry_changes(tmp_path,unknown):
    async def run():
        b=Bridge(tmp_path);b.unknown=unknown;c=ApprovalCoordinator(b)
        first=await c.inspect('%1',run)
        expected='unknown' if unknown else 'sent'
        assert (await c.answer('%1',run,first['token'],1,'first'))['state']==expected
        old_capture=b.approval_capture_locked
        async def resized(pane):
            value=await old_capture(pane);value['identity']=['different-geometry'];return value
        b.approval_capture_locked=resized
        b.screen=MCP.replace('› 1.','  1.').replace('  2.','› 2.')
        assert (await c.inspect('%1',run))['state']==expected
        assert len(b.writes)==1
    asyncio.run(run())


def test_unsent_admission_does_not_consume_prompt(tmp_path):
    from reader_approval import ApprovalNotSent
    async def run():
        b=Bridge(tmp_path);c=ApprovalCoordinator(b)
        first=await c.inspect('%1',run);original=b.approval_keys_locked
        async def refuse(*args,**kwargs):raise ApprovalNotSent('changed before first byte')
        b.approval_keys_locked=refuse
        assert (await c.answer('%1',run,first['token'],1,'unsent'))['state']=='refused'
        assert not b.writes
        b.approval_keys_locked=original
        again=await c.inspect('%1',run)
        assert again['state']=='ready'
        assert (await c.answer('%1',run,again['token'],1,'retry-after-review'))['state']=='sent'
        assert b.writes==[['Enter']]
    asyncio.run(run())


def test_harness_resolution_is_exact_and_scoped_to_original_pane(monkeypatch):
    from types import SimpleNamespace
    import orrery_backend as backend
    async def run():
        primary=SimpleNamespace(pane_id='%1',window_index='0',pane_index='0')
        split=SimpleNamespace(pane_id='%2',window_index='0',pane_index='1')
        bridge=SimpleNamespace(config=SimpleNamespace(session='Fixture',tmux_bin='unused'),panes={'%1':primary,'%2':split})
        row=dict(name='Fixture',program='codex-cli',provider='openai',running=True)
        async def roster(request):return dict(agents=rows)
        monkeypatch.setattr(backend,'conversation_live_agents',roster)
        rows=[row]
        assert await backend.approval_harness(object(),bridge,'%1')=='codex'
        assert await backend.approval_harness(object(),bridge,'%2') is None
        for rows in [[], [dict(row,name='Elsewhere')], [dict(row,running=False)], [row,row], [dict(row,provider='anthropic')]]:
            assert await backend.approval_harness(object(),bridge,'%1') is None
    asyncio.run(run())
