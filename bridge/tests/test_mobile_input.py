"""Pane-scoped mobile terminal: private control fixtures, no live tmux/agents."""
import asyncio
from collections import deque
import contextlib
import importlib
import fcntl
import threading
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest

BRIDGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BRIDGE))
from control_server import ControlConfig, TmuxControlBridge, PaneInfo


def bridge_fixture(tmp_path):
    bridge=TmuxControlBridge(ControlConfig('127.0.0.1',0,'FixtureCurie','tmux',history_dir=tmp_path))
    bridge.master_fd=99  # Synthetic writer owns no actual host descriptor.
    bridge.panes={'%3':PaneInfo('%3','@1','$2','0','0',80,24,True,'Main','fixture')}
    return bridge


@pytest.mark.parametrize('case',['accepted','overflow','timeout','ack_error'])
def test_bounded_capture_uses_real_parser_and_keeps_next_ack_aligned(tmp_path,monkeypatch,case):
    async def scenario():
        bridge=bridge_fixture(tmp_path)
        assert hasattr(bridge,'capture_mobile_preview'),'bounded pane capture is absent'
        import control_server
        monkeypatch.setattr(control_server,'admit_command',lambda *a,**kw:None)
        writes=[];aborts=[]
        bridge._abort_mobile_stream=lambda:aborts.append(True)
        async def writer(payload):writes.append(payload)
        bridge._write_master=writer
        async def no_history(*a,**kw):raise AssertionError('recorder/history capture must not be used')
        bridge.capture_pane=no_history
        task=asyncio.create_task(bridge.capture_mobile_preview('%3',24,deadline=time.monotonic()+(.05 if case=='timeout' else 1)))
        while not writes:await asyncio.sleep(0)
        assert b'capture-pane' in writes[0] and b'-S -16' in writes[0] and b'-E 23' in writes[0]
        if case=='timeout':
            with pytest.raises(Exception):await task
            assert aborts==[True]
            return
        bridge._handle_line('%begin 10 4 0')
        if case=='overflow':
            for _ in range(5):bridge._handle_line('x'*20000)
            assert sum(len(x) for x in bridge._current_block)<=65536
        else:
            bridge._handle_line('literal <img src=x onerror=alert(1)>')
            bridge._handle_line('%end this is pane text, not a matching terminator')
        bridge._handle_line('%error 10 4 0' if case=='ack_error' else '%end 10 4 0')
        if case in {'overflow','ack_error'}:
            with pytest.raises(Exception):await task
        else:
            result=await task
            assert result.lines==['literal <img src=x onerror=alert(1)>','%end this is pane text, not a matching terminator']
        assert not bridge._pending_blocks and not aborts
        next_future=asyncio.get_running_loop().create_future();bridge._pending_blocks.append(next_future)
        bridge._handle_line('%begin 11 5 0');bridge._handle_line('next');bridge._handle_line('%end 11 5 0')
        assert (await next_future).lines==['next']
    asyncio.run(scenario())


def test_terminal_literal_filter_and_serialized_cap_are_separate():
    assert (BRIDGE/'mobile_input.py').is_file(),'mobile pane primitives are absent'
    mobile=importlib.import_module('mobile_input')
    text,shortened,removed=mobile.terminal_text(['\x1b[31mred\x1b[0m\x1b]0;bad\x07\u202eevil','<script>literal</script>'])
    assert text=='redevil\n<script>literal</script>' and removed and not shortened
    text,shortened,removed=mobile.terminal_text(['界'*6000]*50)
    assert len(text.encode())<=6144 and len(text.splitlines())<=40 and shortened
    with pytest.raises(mobile.InputRefused):mobile.encode_json({'text':'"'*16384})
    assert len(mobile.encode_json({'text':'"'*4096}))<=16384


def test_preview_change_discards_body_and_prepared_send_is_once(tmp_path):
    assert (BRIDGE/'mobile_input.py').is_file(),'mobile pane coordinator is absent'
    mobile=importlib.import_module('mobile_input')
    async def scenario():
        bridge=bridge_fixture(tmp_path);facts={'version':1};sent=[]
        class Resolver:
            def read(self,b,p,deadline):
                assert b is bridge and p=='%3'
                return {'session':'FixtureCurie','pane_id':'%3','incarnation':bridge._incarnation,'version':facts['version'],'height':24}
            @contextlib.contextmanager
            def admission(self,row,deadline):
                assert self.read(row['bridge'],row['pane_id'],deadline)==row['proof']
                yield row['proof']
        async def capture(*a,**kw):
            if facts.get('swap'):facts['version']+=1
            return SimpleNamespace(lines=['hello <script>literal</script>'])
        bridge.capture_mobile_preview=capture
        async def send(p,text,**kw):
            if not kw['valid']() or not kw['claim']():return 'refused'
            with kw['admission'](time.monotonic()+1):pass
            sent.append((p,text));await asyncio.sleep(0);return 'accepted'
        bridge.send_confirmed_input=send
        async def get_bridge(name):return bridge if name=='FixtureCurie' else None
        c=mobile.InputCoordinator(Resolver(),get_bridge,enabled=True)
        scope={'contract':mobile.CONTRACT,'owner':'fixture@example.invalid','reader_epoch':'b'*32}
        cap=await c.request('capability',scope);scope['epoch']=cap['epoch']
        listed=await c.request('targets',dict(scope,name='FixtureCurie'))
        assert len(listed['targets'])==1
        choice=listed['targets'][0]['choice']
        preview=await c.request('preview',dict(scope,choice=choice))
        assert preview['text']=='hello <script>literal</script>'
        prepared=await c.request('prepare',dict(scope,choice=choice,revision=preview['target']['revision'],text='hello'))
        commit=dict(scope,intent=prepared['intent'],confirmation=prepared['confirmation'])
        a,b=await asyncio.gather(c.request('commit',commit),c.request('commit',commit))
        assert a['state']=='accepted' and b['state'] in {'pending','accepted'} and sent==[('%3','hello')]
        assert c.intents[prepared['intent']]['text'] is None
        facts['swap']=True
        with pytest.raises(mobile.InputRefused):await c.request('preview',dict(scope,choice=choice))
        with pytest.raises(mobile.InputRefused):await c.request('preview',dict(scope,choice=choice,reader_epoch='c'*32))
        c.close()
    asyncio.run(scenario())


make_bridge=bridge_fixture

@pytest.mark.parametrize('case',['accepted','replaced','cancelled','expired','claim_lost','partial','ack_timeout','ack_error'])
def test_confirmed_batch_is_one_locked_intent_with_ack_after_release(tmp_path,case):
    async def scenario():
        bridge=make_bridge(tmp_path)
        assert hasattr(bridge,'send_confirmed_input'), 'finite confirmed-input batch is absent'
        writes=[]; claimed=[]; held=threading.Event(); valid=[True]; aborted=[]
        lock_path=tmp_path/'proof-context.lock'; fd=os.open(lock_path,os.O_CREAT|os.O_RDWR,0o600)
        other=os.open(lock_path,os.O_RDWR)
        @contextlib.contextmanager
        def admission(deadline):
            fcntl.flock(fd,fcntl.LOCK_EX); held.set()
            try:
                yield {'session':'FixtureCurie','pane_id':'%3','incarnation':bridge._incarnation}
            finally:
                held.clear(); fcntl.flock(fd,fcntl.LOCK_UN)
        async def writer(payload):
            assert held.is_set()
            with pytest.raises(BlockingIOError): fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
            writes.append(payload)
            if case=='partial': raise OSError('synthetic partial stream')
            if case=='cancelled': valid[0]=False
        bridge._write_master=writer
        bridge._abort_mobile_stream=lambda: aborted.append(True)
        def claim():
            claimed.append(True)
            return case!='claim_lost'
        if case=='replaced':
            @contextlib.contextmanager
            def admission(deadline): raise RuntimeError('replaced'); yield
        if case=='cancelled': valid[0]=False
        if case=='expired': deadline=time.monotonic()-.1
        else: deadline=time.monotonic()+(.1 if case=='ack_timeout' else 1)
        task=asyncio.create_task(bridge.send_confirmed_input('%3','hello',admission=admission,
            valid=lambda:valid[0],claim=claim,deadline=deadline))
        try:
            if case in {'accepted','ack_error'}:
                for _ in range(100):
                    if writes and not held.is_set(): break
                    await asyncio.sleep(.001)
                assert writes and not held.is_set() and not task.done()
                fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB); fcntl.flock(other,fcntl.LOCK_UN)
                for _ in tuple(bridge._pending_blocks):
                    bridge._handle_line('%begin 0 1 0')
                    bridge._handle_line('%error 0 1 0' if case=='ack_error' else '%end 0 1 0')
            outcome=await task
            assert outcome==('accepted' if case=='accepted' else 'unknown' if case in {'partial','ack_timeout','ack_error'} else 'refused')
            assert not held.is_set() and not bridge._write_lock.locked()
            if case in {'replaced','cancelled','expired','claim_lost'}: assert writes==[]
            else:
                assert len(claimed)==1 and writes
                if case=='accepted':
                    assert len(writes)==3  # Bracketed paste start/text/end+Enter, one intent.
                    assert writes[-1].endswith(b'\n')
            if case=='partial': assert aborted==[True] and len(writes)==1
        finally:
            if not task.done(): task.cancel(); await task
            os.close(fd); os.close(other)
    asyncio.run(scenario())

def test_cancel_while_proof_worker_waits_never_dispatches_later(tmp_path):
    async def scenario():
        bridge=make_bridge(tmp_path)
        assert hasattr(bridge,'send_confirmed_input'), 'finite confirmed-input batch is absent'
        ready=threading.Event(); release=threading.Event(); closed=threading.Event(); writes=[]
        @contextlib.contextmanager
        def admission(deadline):
            ready.set(); release.wait(1)
            try: yield {'session':'FixtureCurie','pane_id':'%3','incarnation':bridge._incarnation}
            finally: closed.set()
        async def writer(payload): writes.append(payload)
        bridge._write_master=writer
        task=asyncio.create_task(bridge.send_confirmed_input('%3','hello',admission=admission,
            valid=lambda:True,claim=lambda:True,deadline=time.monotonic()+2))
        while not ready.is_set(): await asyncio.sleep(.001)
        task.cancel(); release.set()
        assert await task=='refused'
        assert closed.is_set() and writes==[] and not bridge._write_lock.locked()
    asyncio.run(scenario())

@pytest.mark.parametrize('case',['valid','origin_missing','origin_other','origin_duplicate','host_other',
    'contract_missing','method_override','duplicate_field','wrong_method','encoded_path'])
def test_finite_loopback_http_adapter_refuses_before_coordinator(case):
    import json
    import mobile_input as mobile
    from aiohttp import ClientSession,web
    from yarl import URL
    assert hasattr(mobile,'install_routes'), 'finite loopback HTTP adapter is absent'
    async def scenario():
        calls=[]
        class Coordinator:
            async def request(self,operation,payload):
                calls.append((operation,payload))
                return dict(contract=mobile.CONTRACT,enabled=False)
        app=web.Application(); mobile.install_routes(app,Coordinator())
        runner=web.AppRunner(app,access_log=None); await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0); await site.start()
        port=site._server.sockets[0].getsockname()[1]
        try:
            headers=[('Origin',f'http://127.0.0.1:{port}'),('X-ORRERY-Mobile-Contract',mobile.CONTRACT),
                     ('Content-Type','application/json')]
            if case=='origin_missing': headers=[h for h in headers if h[0]!='Origin']
            elif case=='origin_other': headers[0]=('Origin','https://other.example.invalid')
            elif case=='origin_duplicate': headers.append(headers[0])
            elif case=='host_other': headers.append(('Host','other.example.invalid'))
            elif case=='contract_missing': headers=[h for h in headers if h[0]!='X-ORRERY-Mobile-Contract']
            elif case=='method_override': headers.append(('X-HTTP-Method-Override','POST'))
            body=json.dumps({'contract':mobile.CONTRACT,'owner':'fixture@example.invalid','reader_epoch':'a'*32}).encode()
            if case=='duplicate_field': body=b'{"contract":"a","contract":"b"}'
            path='/_mobile/terminal/capability' if case!='encoded_path' else '/_mobile/terminal/%63apability'
            async with ClientSession() as client:
                async with client.request('GET' if case=='wrong_method' else 'POST',URL(f'http://127.0.0.1:{port}'+path,encoded=True),
                                          data=body,headers=headers) as response:
                    assert response.status==(200 if case=='valid' else 400 if case=='duplicate_field' else 403)
                    assert response.headers['Cache-Control']=='no-store'
                    await response.read()
            assert len(calls)==(1 if case=='valid' else 0)
        finally: await runner.cleanup()
    asyncio.run(scenario())

@pytest.mark.parametrize('text',['\r','a\nb','a\tb','a\x00b','a\x1bb','a\x85b','a\u2028b','a\u202eb','x'*4097,'é'*2049,'\ud800'])
def test_invalid_text_has_no_repair_or_truncation(text):
    import mobile_input as mobile
    with pytest.raises(mobile.InputRefused): mobile.validate_text(text)

def test_exact_utf8_and_escaped_envelope_limits_are_distinct():
    import json
    import mobile_input as mobile
    text='é'*2048
    assert mobile.validate_text(text)==text.encode('utf-8')
    data=json.dumps(dict(contract=mobile.CONTRACT,owner='fixture@example.invalid',reader_epoch='a'*32,
        epoch='b'*32,name='FixtureCurie',revision='c'*64,text=text)).encode()
    assert 4096<len(data)<=mobile.MAX_JSON_BYTES
    assert mobile.decode_json(data)['text']==text

@pytest.mark.parametrize('failure',['cancel','write_error','deadline','zero_write'])
def test_partial_real_control_sink_is_quarantined_without_compensation(tmp_path,monkeypatch,failure):
    async def scenario():
        bridge=make_bridge(tmp_path);read_fd,write_fd=os.pipe();bridge.master_fd=write_fd
        closed=[];bridge._schedule_closed=lambda:closed.append(True)
        held=threading.Event();observed=[]
        @contextlib.contextmanager
        def admission(deadline):
            held.set()
            try:yield {'session':'FixtureCurie','pane_id':'%3','incarnation':bridge._incarnation}
            finally:held.clear()
        original=bridge._write_master
        if failure=='zero_write':
            real_write=os.write
            def zero(fd,data):return 0 if fd==write_fd else real_write(fd,data)
            monkeypatch.setattr(os,'write',zero)
        else:
            async def partial(data):
                assert held.is_set();observed.append(data)
                await original(data[:12])
                if failure=='cancel':raise asyncio.CancelledError
                if failure=='write_error':raise OSError('fixture-write-error')
                await asyncio.sleep(1)
            bridge._write_master=partial
        try:
            outcome=await bridge.send_confirmed_input('%3','hello',admission=admission,
                valid=lambda:True,claim=lambda:True,deadline=time.monotonic()+.05)
            assert outcome=='unknown' and not held.is_set() and not bridge._write_lock.locked()
            assert bridge.master_fd is None and closed==[True] and not bridge._pending_blocks
            data=os.read(read_fd,4096)
            assert data==(b'' if failure=='zero_write' else observed[0][:12])
            assert b'0d' not in data  # No appended Enter or remaining commands.
            with pytest.raises(OSError):os.fstat(write_fd)
        finally:
            os.close(read_fd)
            if bridge.master_fd is not None:os.close(bridge.master_fd)
    asyncio.run(scenario())

def test_cancel_after_first_complete_frame_stops_remaining_text_and_enter(tmp_path):
    async def scenario():
        bridge=make_bridge(tmp_path);writes=[];valid=[True];released=[]
        @contextlib.contextmanager
        def admission(deadline):
            try:yield {'session':'FixtureCurie','pane_id':'%3','incarnation':bridge._incarnation}
            finally:released.append(True)
        async def writer(data):writes.append(data);valid[0]=False
        aborted=[];bridge._write_master=writer;bridge._abort_mobile_stream=lambda:aborted.append(True)
        assert await bridge.send_confirmed_input('%3','hello',admission=admission,
            valid=lambda:valid[0],claim=lambda:True,deadline=time.monotonic()+1)=='unknown'
        assert len(writes)==1 and released==[True] and aborted==[True]
    asyncio.run(scenario())

@pytest.mark.parametrize('reason',['cancel','disable','expire'])
def test_input_invalidated_while_pc_owns_write_lock_never_reaches_admission(tmp_path,reason):
    async def scenario():
        bridge=make_bridge(tmp_path);writes=[];proof_calls=[];valid=[True]
        @contextlib.contextmanager
        def admission(deadline):
            proof_calls.append(True)
            yield {'session':'FixtureCurie','pane_id':'%3','incarnation':bridge._incarnation}
        async def writer(data):writes.append(data)
        bridge._write_master=writer
        await bridge._write_lock.acquire()  # An existing PC intent owns it.
        task=asyncio.create_task(bridge.send_confirmed_input('%3','hello',admission=admission,
            valid=lambda:valid[0],claim=lambda:True,deadline=time.monotonic()+(.03 if reason=='expire' else 1)))
        await asyncio.sleep(0)
        if reason=='cancel':task.cancel()
        elif reason=='disable':valid[0]=False
        if reason=='expire':await asyncio.sleep(.05)
        bridge._write_lock.release()
        assert await task=='refused'
        assert writes==proof_calls==[] and not bridge._write_lock.locked()
    asyncio.run(scenario())

def test_pc_input_cannot_interleave_inside_confirmed_batch(tmp_path,monkeypatch):
    import control_server
    async def scenario():
        bridge=make_bridge(tmp_path);writes=[];pc_task=[];held=threading.Event()
        @contextlib.contextmanager
        def admission(deadline):
            held.set()
            try:yield {'session':'FixtureCurie','pane_id':'%3','incarnation':bridge._incarnation}
            finally:held.clear()
        monkeypatch.setattr(control_server,'admit_command',lambda *args,**kwargs:None)
        async def writer(data):
            writes.append((data,held.is_set()))
            if len(writes)==1:pc_task.append(asyncio.create_task(bridge.send_input('%3','PC')))
            await asyncio.sleep(0)
        bridge._write_master=writer
        mobile=asyncio.create_task(bridge.send_confirmed_input('%3','mobile',admission=admission,
            valid=lambda:True,claim=lambda:True,deadline=time.monotonic()+1))
        for _ in range(100):
            if len(writes)==4:break
            await asyncio.sleep(.001)
        assert len(writes)==4 and [locked for _,locked in writes]==[True,True,True,False]
        assert b'50 43' in writes[-1][0]  # PC's literal bytes follow the final Enter.
        assert not mobile.done() and not held.is_set()
        for _ in tuple(bridge._pending_blocks):
            bridge._handle_line('%begin 0 1 0');bridge._handle_line('%end 0 1 0')
        assert await mobile=='accepted'
        await pc_task[0]
        assert not bridge._pending_blocks and not bridge._write_lock.locked()
    asyncio.run(scenario())

@pytest.mark.parametrize('case',['valid','helper_missing','wrong_uid','process_unknown','boot_changed','socket_changed','global','session_changed','bridge_changed'])
def test_real_shared_pane_selector_and_kernel_identity_fail_closed(tmp_path,case):
    import runpy
    import mobile_input as mobile
    from test_runtime_target import telemetry_root
    telemetry=telemetry_root()
    shared=runpy.run_path(str(telemetry/'bin/lib/runtime_tmux.py'))
    bridge=bridge_fixture(tmp_path);calls=[];observed={}
    class Transport:
        path=tmp_path/'fixture.sock'
        def public(self):return {'transport':'legacy-default','socket_path':str(self.path),'argv':['fixture-tmux','-S',str(self.path)],'server_pid':44}
        def command(self,*args,**kwargs):
            calls.append(args)
            assert args[:4]==('display-message','-p','-t','%3')
            if case=='bridge_changed' and len(calls)==3:bridge._incarnation='changed'
            session='WrongSession' if case=='session_changed' else 'FixtureCurie'
            return SimpleNamespace(returncode=0,stdout=f'$2\t{session}\t%3\t55\n')
    transport=Transport();original=shared['legacy_admission']
    def admitted(*args,**kwargs):
        # Exercise the real exclusive-selector contract and membership re-read.
        assert kwargs.get('session') is None and kwargs.get('pane')=='%3'
        def global_proofs(*a,**kw):
            if case=='global':raise shared['TargetError']('GLOBAL_TARGET_OWNERSHIP_UNKNOWN')
            return []
        return original(*args,**kwargs,api={'process_start':lambda *a,**kw:'fixture-start'},proof_reader=global_proofs)
    socket_checks=[]
    def socket_identity(path):
        socket_checks.append(path)
        return (1,2+int(case=='socket_changed' and len(socket_checks)>1),os.getuid())
    shared['legacy_admission']=admitted;shared['validate_socket']=socket_identity
    boundary=SimpleNamespace(shared=None if case=='helper_missing' else shared,transport=transport,home=tmp_path,pin=transport.public())
    class Observer:
        def process(self,pid):
            observed[pid]=observed.get(pid,0)+1
            if case=='process_unknown':return None
            return {'pid':pid,'ppid':1,'uid':os.getuid()+int(case=='wrong_uid'),'comm':'fixture',
                    'birth':'fixture:boot:'+str(observed[pid] if case=='boot_changed' else 1)}
    resolver=mobile.PaneResolver(boundary,Observer())
    if case=='valid':
        proof=resolver.read(bridge,'%3',time.monotonic()+1)
        assert proof['pane_id']=='%3' and proof['session_id']=='$2' and proof['height']==24
        assert len(calls)==4 and observed=={44:2,55:2}
    else:
        with pytest.raises(Exception):resolver.read(bridge,'%3',time.monotonic()+1)
        if case=='helper_missing':assert not calls and not observed


def test_bounded_parser_drops_one_overlong_line_before_newline_without_moving_ack(tmp_path,monkeypatch):
    async def scenario():
        bridge=bridge_fixture(tmp_path);future=asyncio.get_running_loop().create_future()
        bridge._pending_blocks.append(future);bridge._bounded_blocks[future]=65536
        chunks=deque([b'%begin 1 2 0\n']+[b'x'*8192]*10+[b'\n%end 1 2 0\n'])
        def read(fd,amount):
            if chunks:return chunks.popleft()
            raise BlockingIOError
        monkeypatch.setattr(os,'read',read)
        bridge._read_ready()
        result=await future
        assert result.ok and result.overflow and result.lines==[]
        assert bridge._buffer==b'' and not bridge._pending_blocks and not bridge._bounded_blocks
    asyncio.run(scenario())


@pytest.mark.parametrize('case',['cancel','expiry','wrong_scope','wrong_confirmation','disable','revision','rate','capacity','retention'])
def test_pane_confirmation_boundaries_and_memory_limits(tmp_path,case):
    import mobile_input as mobile
    async def scenario():
        bridge=bridge_fixture(tmp_path);clock=[100.0];sent=[]
        class Resolver:
            def read(self,b,p,deadline):return {'session':'FixtureCurie','pane_id':'%3','incarnation':bridge._incarnation,'height':24}
            @contextlib.contextmanager
            def admission(self,row,deadline):yield self.read(bridge,'%3',deadline)
        async def capture(*args,**kw):return SimpleNamespace(lines=['fixture only'])
        bridge.capture_mobile_preview=capture
        async def send(p,text,**kw):
            if not kw['valid']() or not kw['claim']():return 'refused'
            sent.append(text);return 'accepted'
        bridge.send_confirmed_input=send
        async def get_bridge(name):return bridge
        coordinator=mobile.InputCoordinator(Resolver(),get_bridge,enabled=True,clock=lambda:clock[0])
        base=dict(contract=mobile.CONTRACT,owner='fixture@example.invalid',reader_epoch='b'*32,epoch=coordinator.epoch)
        listed=await coordinator.request('targets',dict(base,name='FixtureCurie'));choice=listed['targets'][0]['choice']
        preview=await coordinator.request('preview',dict(base,choice=choice))
        async def prepare():return await coordinator.request('prepare',dict(base,choice=choice,revision=preview['target']['revision'],text='hello'))
        async def commit(row,**overrides):return await coordinator.request('commit',dict(base,intent=row['intent'],confirmation=row['confirmation'],**overrides))
        try:
            if case=='rate':
                outcomes=[(await commit(await prepare()))['state'] for _ in range(7)]
                assert outcomes==['accepted']*6+['refused'] and len(sent)==6
                return
            if case=='capacity':
                rows=[await prepare() for _ in range(16)]
                with pytest.raises(mobile.InputRefused):await prepare()
                coordinator.close()
                assert all(r['text'] is None and r['descriptor'] is None for r in coordinator.intents.values())
                return
            if case=='revision':
                with pytest.raises(mobile.InputRefused):await coordinator.request('prepare',dict(base,choice=choice,revision='f'*64,text='hello'))
                return
            row=await prepare()
            if case=='cancel':await coordinator.request('cancel',dict(base,intent=row['intent']))
            elif case=='expiry':clock[0]+=31
            elif case=='disable':coordinator.enabled=False
            elif case=='wrong_scope':
                with pytest.raises(mobile.InputRefused):await commit(row,reader_epoch='c'*32)
                assert not sent;return
            elif case=='wrong_confirmation':
                value=dict(base,intent=row['intent'],confirmation='c'*64)
                with pytest.raises(mobile.InputRefused):await coordinator.request('commit',value)
                assert not sent;return
            if case=='retention':
                assert (await commit(row))['state']=='accepted';clock[0]+=601
                await coordinator.request('capability',{k:v for k,v in base.items() if k!='epoch'})
                assert not coordinator.intents and not coordinator.choices and not coordinator.rates
                return
            assert (await commit(row))['state']=={'cancel':'cancelled','expiry':'expired','disable':'refused'}[case]
            assert not sent and coordinator.intents[row['intent']]['text'] is None
        finally:coordinator.close()
    asyncio.run(scenario())


def test_unterminated_capture_quarantines_private_stream_and_rejects_next_command(tmp_path,monkeypatch):
    import control_server
    async def scenario():
        bridge=bridge_fixture(tmp_path);read_fd,write_fd=os.pipe();bridge.master_fd=write_fd;closed=[]
        bridge._schedule_closed=lambda:closed.append(True)
        monkeypatch.setattr(control_server,'admit_command',lambda *a,**kw:None)
        try:
            with pytest.raises(Exception):await bridge.capture_mobile_preview('%3',24,deadline=time.monotonic()+.04)
            assert closed==[True] and bridge.master_fd is None and not bridge._pending_blocks and not bridge._bounded_blocks
            data=os.read(read_fd,4096);assert b'capture-pane' in data
            with pytest.raises(RuntimeError):await bridge.send_command(['display-message','-p','literal'])
            assert os.read(read_fd,4096)==b''
        finally:
            os.close(read_fd)
            if bridge.master_fd is not None:os.close(bridge.master_fd)
    asyncio.run(scenario())


@pytest.mark.parametrize('source,expected',[('hello\x1b]secret\x1bXhidden\x07world','helloworld'),('hello\x1b]unterminated\nprivate','hello'),('a\x1b(0b','ab'),('a\x9b31mb\x9b0mc','abc'),('a\x90hidden\x9cb','ab')])
def test_preview_strips_complete_and_unterminated_controls(source,expected):
    import mobile_input as mobile
    text,truncated,removed=mobile.terminal_text([source])
    assert text==expected and removed and not truncated


@pytest.mark.parametrize('case',['valid','sysctl_refused','short_uuid','bad_uuid','short_proc','wrong_pid','bad_usec','stopped'])
def test_kernel_birth_abi_with_injected_native_calls_only(monkeypatch,case):
    import ctypes as c
    import mobile_input as mobile
    calls=[];boot=b'12345678-1234-1234-1234-123456789abc'
    class Function:
        def __init__(self,fn):self.fn=fn;self.argtypes=None;self.restype=None
        def __call__(self,*args):return self.fn(*args)
    def sysctl(name,buffer,size,old,new):
        calls.append('sysctl');assert name==b'kern.bootsessionuuid'
        if case=='sysctl_refused':return -1
        value=b'not-a-uuid' if case=='bad_uuid' else boot
        c.memmove(buffer,value+b'\0',len(value)+1);size._obj.value=36 if case=='short_uuid' else 37;return 0
    def proc(pid,flavor,arg,buffer,size):
        calls.append('proc');info=buffer._obj
        assert flavor==3 and arg==0 and size==136 and type(info).sec.offset==120 and type(info).usec.offset==128
        info.pid=pid+int(case=='wrong_pid');info.ppid=1;info.uid=os.getuid();info.status=4 if case=='stopped' else 2
        info.sec=123;info.usec=1000000 if case=='bad_usec' else 456;info.comm=b'fixture'
        return size-1 if case=='short_proc' else size
    system=SimpleNamespace(sysctlbyname=Function(sysctl));library=SimpleNamespace(proc_pidinfo=Function(proc))
    def load(path,**kwargs):
        assert kwargs=={'use_errno':True}
        if path=='/usr/lib/libSystem.B.dylib':return system
        assert path=='/usr/lib/libproc.dylib';return library
    monkeypatch.setattr(c,'CDLL',load)
    monkeypatch.setattr(mobile.sys,'platform','darwin')
    result=mobile.OSObserver().process(9876)
    if case=='valid':
        assert result['pid']==9876 and result['birth']=='darwin:'+boot.decode()+':123:456'
        assert system.sysctlbyname.restype is c.c_int and library.proc_pidinfo.restype is c.c_int
    else:assert result is None
    if case in {'sysctl_refused','short_uuid','bad_uuid'}:assert calls==['sysctl']


def test_preview_single_inflight_and_expired_choice_never_prepares(tmp_path):
    import mobile_input as mobile
    async def scenario():
        bridge=bridge_fixture(tmp_path);entered=threading.Event();release=threading.Event();clock=[100.0]
        class Resolver:
            def read(self,b,p,deadline):
                entered.set();release.wait(1)
                return {'session':'FixtureCurie','pane_id':'%3','incarnation':bridge._incarnation,'height':24}
        async def capture(*a,**kw):return SimpleNamespace(lines=['fixture'])
        bridge.capture_mobile_preview=capture
        async def get_bridge(name):return bridge
        coordinator=mobile.InputCoordinator(Resolver(),get_bridge,enabled=True,clock=lambda:clock[0])
        base=dict(contract=mobile.CONTRACT,owner='fixture@example.invalid',reader_epoch='b'*32,epoch=coordinator.epoch)
        listed=await coordinator.request('targets',dict(base,name='FixtureCurie'));choice=listed['targets'][0]['choice']
        task=asyncio.create_task(coordinator.request('preview',dict(base,choice=choice)))
        while not entered.is_set():await asyncio.sleep(.001)
        with pytest.raises(mobile.InputRefused,match='preview_busy'):await coordinator.request('preview',dict(base,choice=choice))
        clock[0]+=31;release.set()
        with pytest.raises(mobile.InputRefused):await task
        assert not coordinator.previews and not coordinator.intents
        coordinator.close()
    asyncio.run(scenario())


def test_catalog_size_is_serialized_and_no_more_than_128_handles(tmp_path):
    import mobile_input as mobile
    async def scenario():
        bridge=bridge_fixture(tmp_path);bridge.panes={f'%{i}':PaneInfo(f'%{i}','@1','$2','0',str(i),80,24,True,'Fixture','fixture') for i in range(200)}
        async def get_bridge(name):return bridge
        coordinator=mobile.InputCoordinator(None,get_bridge,enabled=True)
        base=dict(contract=mobile.CONTRACT,owner='fixture@example.invalid',reader_epoch='b'*32,epoch=coordinator.epoch)
        result=await coordinator.request('targets',dict(base,name='FixtureCurie'))
        assert result['truncated'] is True and 1<=len(result['targets'])<=128
        assert len(mobile.encode_json(result))<=16384 and len(coordinator.choices)==len(result['targets'])
        coordinator.close();assert not coordinator.choices
    asyncio.run(scenario())


@pytest.mark.parametrize('enabled',[False,True])
def test_real_create_app_routes_existing_manager_only_without_starting_recorders(tmp_path,monkeypatch,enabled):
    import json
    import orrery_backend as ob
    import mobile_input as mobile
    from aiohttp import ClientSession,web
    class Boundary:
        shared=None;transport=None;home=tmp_path
    monkeypatch.setattr(ob,'LegacyTargetBoundary',Boundary)
    async def scenario():
        bridge=bridge_fixture(tmp_path)
        app=ob.create_app(Boundary(),mobile_input_enabled=enabled)
        # Product startup would attach to tmux. This HTTP fixture intentionally
        # supplies the already-managed state and never starts those resources.
        app.cleanup_ctx.clear();app[ob.BRIDGE_MANAGER_KEY]=SimpleNamespace(states={'FixtureCurie':SimpleNamespace(bridge=bridge)})
        runner=web.AppRunner(app,access_log=None);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
        try:
            headers={'Origin':f'http://127.0.0.1:{port}','Content-Type':'application/json','X-ORRERY-Mobile-Contract':mobile.CONTRACT}
            payload=dict(contract=mobile.CONTRACT,owner='fixture@example.invalid',reader_epoch='a'*32)
            async with ClientSession() as client:
                async with client.post(f'http://127.0.0.1:{port}/_mobile/terminal/capability',data=json.dumps(payload),headers=headers) as response:
                    assert response.status==200;cap=await response.json();assert cap['enabled'] is enabled and cap['api']==31
                payload.update(epoch=cap['epoch'],name='FixtureCurie')
                async with client.post(f'http://127.0.0.1:{port}/_mobile/terminal/targets',data=json.dumps(payload),headers=headers) as response:
                    assert response.status==(200 if enabled else 403)
                    if enabled:assert (await response.json())['targets'][0]['name']=='FixtureCurie'
                payload['name']='UnknownAlias'
                async with client.post(f'http://127.0.0.1:{port}/_mobile/terminal/targets',data=json.dumps(payload),headers=headers) as response:assert response.status==403
        finally:await runner.cleanup()
    asyncio.run(scenario())
