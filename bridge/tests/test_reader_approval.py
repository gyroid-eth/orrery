"""Approval parsing and delivery: synthetic prompts, never a live agent."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from reader_approval import ApprovalCoordinator, parse_screen

MCP = '''Field 1/1
Allow the orrery-mail MCP server to run tool "acknowledge_message"?
message_id: 9
› 1. Allow
  2. Allow for this session
  3. Always allow
  4. Cancel
enter to submit | esc to cancel'''
COMMAND = '''Would you like to run the following command?
Environment: local
Reason: Read a generated fixture outside the sandbox.
$ /bin/bash ~/fixture/run.sh
› 1. Yes, proceed (y)
  2. Yes, and don't ask again for commands that start with `/bin/bash ~/fixture/run.sh` (p)
  3. No, and tell Codex what to do differently (esc)
Press enter to confirm or esc to cancel'''
READ = '''────────────────────
Read outside the working directories
Read(~/fixture/PUBLIC.json)
Allow this read outside the working directories?
❯ 1. Yes, and keep allowing any reads outside the working directories
  2. No, and block reads outside the working directories from now on
  3. No, and ask again next time
  4. Yes, but ask again next time
Esc to cancel · Tab to amend'''


@pytest.mark.parametrize('text,command,kind,default',[(MCP,'codex','mcp',1),(COMMAND,'codex','command',1),(READ,'claude','read',4)])
def test_complete_prompts(text,command,kind,default):
    value=parse_screen(text,command)
    assert value['kind']==kind and value['default']==default
    assert value['text']==text and value['selected']==1


@pytest.mark.parametrize('text,command',[
    (MCP,'zsh'),(READ,'codex'),(MCP.replace('message_id: 9','message_id: …'),'codex'),
    (MCP.split('\n',1)[1],'codex'),(MCP.rsplit('\n',1)[0],'codex'),
    (MCP.replace('Always allow','Always approve'),'codex'),(MCP+'\n❯ write here','codex'),
    ('    '+MCP.replace('\n','\n    '),'codex'),(MCP+'\n'+MCP,'codex'),
    (READ.replace('❯ ','  '),'claude'),(MCP.replace('message_id: 9','message_id: {"partial":'),'codex'),
    (COMMAND.replace('~/fixture/run.sh`','…`'),'codex'),('x'*65537,'codex'),
])
def test_incomplete_or_ambiguous_has_no_choices(text,command):
    assert parse_screen(text,command) is None


class Bridge:
    def __init__(self,tmp_path):
        self.config=SimpleNamespace(session='Fixture',session_created=1,history_dir=tmp_path)
        self._incarnation='bridge-one';self._write_lock=asyncio.Lock();self._closed=False;self.master_fd=1
        self.panes={'%1':True};self.screen=MCP;self.command='codex';self.writes=[];self.unknown=False
    async def approval_capture_locked(self,pane):
        return {'text':self.screen,'command':self.command,'identity':['$1','%1','123','80','24','0','1']}
    async def approval_keys_locked(self,pane,keys,proof=None):
        self.writes.append(keys)
        if self.unknown:raise TimeoutError()


def test_recheck_deduplicate_and_log(tmp_path):
    async def run():
        b=Bridge(tmp_path);c=ApprovalCoordinator(b)
        first=await c.inspect('%1','peer')
        assert first['state']=='ready'
        result=await c.answer('%1','peer',first['token'],2,'operation-one')
        assert result['state']=='sent' and b.writes==[['Down','Enter']]
        assert await c.answer('%1','peer',first['token'],2,'operation-one')==result
        assert (await c.inspect('%1','other'))['state']=='sent'
        assert (await c.answer('%1','other',first['token'],1,'operation-two'))['state']=='refused'
        rows=[json.loads(s) for s in (tmp_path/'approval-actions.jsonl').read_text().splitlines()]
        assert rows[-1]['state']=='sent' and rows[-1]['keys']==['Down','Enter']
        assert 'message_id' not in json.dumps(rows)
    asyncio.run(run())


@pytest.mark.parametrize('change',['text','selection','pane','owner','identity'])
def test_changed_target_sends_no_keys(tmp_path,change):
    async def run():
        b=Bridge(tmp_path);c=ApprovalCoordinator(b);first=await c.inspect('%1','peer')
        if change=='text':b.screen=MCP.replace('9','10')
        if change=='selection':b.screen=MCP.replace('› 1.','  1.').replace('  2.','› 2.')
        if change=='pane':b.panes.clear()
        if change=='identity':b._incarnation='new-bridge'
        result=await c.answer('%1','different' if change=='owner' else 'peer',first['token'],1,'operation')
        assert result['state'] in {'changed','refused','unavailable'} and not b.writes
    asyncio.run(run())


@pytest.mark.parametrize('text,command,choice,keys',[(MCP,'codex',4,['Down']*3+['Enter']),
    (READ,'claude',4,['Down']*3+['Enter']),(COMMAND,'codex',1,['y']),
    (COMMAND,'codex',2,['p']),(COMMAND,'codex',3,['Escape'])])
def test_key_mapping(tmp_path,text,command,choice,keys):
    async def run():
        b=Bridge(tmp_path);b.screen=text;b.command=command;c=ApprovalCoordinator(b)
        first=await c.inspect('%1','peer')
        assert (await c.answer('%1','peer',first['token'],choice,'operation'))['state']=='sent'
        assert b.writes==[keys]
    asyncio.run(run())


def test_log_failure_does_not_block_and_unknown_never_retries(tmp_path):
    async def run():
        b=Bridge(tmp_path);c=ApprovalCoordinator(b);first=await c.inspect('%1','peer')
        (tmp_path/'approval-actions.jsonl').mkdir();b.unknown=True
        result=await c.answer('%1','peer',first['token'],1,'operation')
        assert result['state']=='unknown' and result['logWarning']
        await c.answer('%1','peer',first['token'],1,'another-operation')
        assert len(b.writes)==1 and (await c.inspect('%1','peer'))['state']=='unknown'
    asyncio.run(run())


from approval_fixture import fake_pane


@pytest.mark.parametrize('text,choice,selected,key',[(MCP,i,i,'\r') for i in range(1,5)]+[(READ,i,i,'\r') for i in range(1,5)]+[
    (COMMAND,1,1,'y'),(COMMAND,2,1,'p'),(COMMAND,3,1,'\x1b'),
    (COMMAND.replace('Read a generated fixture outside the sandbox.','生成した検証用ファイルを読み取ります。'*30),1,1,'y')])
def test_real_control_bridge_keys(fake_pane,tmp_path,text,choice,selected,key):
    from control_server import TmuxControlBridge,ControlConfig
    async def run():
        b=TmuxControlBridge(ControlConfig('127.0.0.1',0,'ApprovalFixture',str(fake_pane.wrapper),history_dir=tmp_path/'history'))
        await b.start()
        try:
            fake_pane.change(text)
            # Let the fake TUI finish its initial control-client resize redraw.
            await asyncio.sleep(.1)
            c=ApprovalCoordinator(b, harness_resolver=fake_pane.harness)
            for _ in range(80):
                value=await c.inspect(fake_pane.pane,run)
                if value.get('text')==text.replace('❯','›'):break
                await asyncio.sleep(.025)
            assert value['state']=='ready',value
            result=await c.answer(fake_pane.pane,run,value['token'],choice,'real-keys')
            assert result['state']=='sent',result
            for _ in range(80):
                if fake_pane.result.exists():break
                await asyncio.sleep(.025)
            actual=json.loads(fake_pane.result.read_text())
            assert actual==dict(selected=selected,key=key)
            raw=b''.join(bytes(json.loads(line)) for line in fake_pane.keys.read_text().splitlines())
            if key!='\r':assert raw==key.encode()
            else:assert b'[200~' not in raw and raw.endswith(b'\r')
        finally:await b.stop()
    asyncio.run(run())


def test_real_bridge_rechecks_changed_screen(fake_pane,tmp_path):
    from control_server import TmuxControlBridge,ControlConfig
    async def run():
        b=TmuxControlBridge(ControlConfig('127.0.0.1',0,'ApprovalFixture',str(fake_pane.wrapper),history_dir=tmp_path/'history'))
        await b.start()
        try:
            c=ApprovalCoordinator(b, harness_resolver=fake_pane.harness);value=await c.inspect(fake_pane.pane,run)
            assert value['state']=='ready',value
            fake_pane.change(MCP.replace('message_id: 9','message_id: 10'))
            for _ in range(80):
                if 'message_id: 10' in fake_pane.capture():break
                await asyncio.sleep(.025)
            result=await c.answer(fake_pane.pane,run,value['token'],1,'stale-screen')
            assert result['state']=='changed',result
            assert not fake_pane.keys.exists()
            fake_pane.change(MCP.replace('  4. Cancel\n',''))
            for _ in range(80):
                if '4. Cancel' not in fake_pane.capture():break
                await asyncio.sleep(.025)
            value=await c.inspect(fake_pane.pane,run)
            assert value['state']=='terminal' and 'choices' not in value
        finally:await b.stop()
    asyncio.run(run())


def test_identical_prompt_after_observed_close_is_a_new_approval(tmp_path):
    async def run():
        b=Bridge(tmp_path);c=ApprovalCoordinator(b)
        first=await c.inspect('%1',run)
        assert (await c.answer('%1',run,first['token'],1,'first'))['state']=='sent'
        b.screen='Response received\nWaiting.'
        assert (await c.inspect('%1',run))['state']=='none'
        b.screen=MCP
        next_=await c.inspect('%1',run)
        assert next_['state']=='ready' and next_['token']!=first['token']
        assert (await c.answer('%1',run,next_['token'],1,'second'))['state']=='sent'
        assert b.writes==[['Enter'],['Enter']]
    asyncio.run(run())


def test_two_tabs_racing_can_only_send_once(tmp_path):
    async def run():
        b=Bridge(tmp_path);c=ApprovalCoordinator(b);a=object();z=object()
        first=await c.inspect('%1',a);second=await c.inspect('%1',z)
        results=await asyncio.gather(c.answer('%1',a,first['token'],1,'first'),c.answer('%1',z,second['token'],4,'second'))
        assert sorted(r['state'] for r in results)==['refused','sent']
        assert b.writes==[['Enter']]
    asyncio.run(run())


def test_input_refused_before_first_byte_is_reported_as_unsent(tmp_path):
    from reader_approval import ApprovalNotSent
    async def run():
        b=Bridge(tmp_path);c=ApprovalCoordinator(b);value=await c.inspect('%1',run)
        async def refused(*args,**kwargs):raise ApprovalNotSent('input refused')
        b.approval_keys_locked=refused
        result=await c.answer('%1',run,value['token'],1,'refused')
        assert result['state']=='refused' and not b.writes
    asyncio.run(run())


@pytest.mark.parametrize('text,command',[(MCP,'codex'),(COMMAND,'codex'),(READ,'claude')])
def test_known_two_column_screen_gutter(text,command):
    padded='\n'.join('  '+line for line in text.splitlines())
    assert parse_screen(padded,command)['default']==(4 if command=='claude' else 1)


def test_selection_can_move_up_to_once(tmp_path):
    async def run():
        b=Bridge(tmp_path);b.screen=MCP.replace('› 1.','  1.').replace('  4.','› 4.')
        c=ApprovalCoordinator(b);value=await c.inspect('%1',run)
        assert (await c.answer('%1',run,value['token'],1,'move-up'))['state']=='sent'
        assert b.writes==[['Up','Up','Up','Enter']]
    asyncio.run(run())


def test_unattached_approval_gets_an_explicit_unsent_reply(tmp_path):
    from orrery_backend import SessionBridgeManager
    async def run():
        class Peer:
            def __init__(self):self.frames=[]
            async def send_json(self,value):self.frames.append(value)
        manager=SessionBridgeManager('unused-fixture',history_dir=tmp_path);peer=Peer()
        await manager.handle_message(peer,set(),dict(type='approval-answer',paneId='%1',session='Fixture',requestId='request'))
        assert peer.frames==[dict(type='approval',paneId='%1',session='Fixture',requestId='request',state='unavailable',message='Pane unavailable')]
    asyncio.run(run())
