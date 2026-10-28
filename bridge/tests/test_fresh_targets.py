"""Fresh per-target bridge over real private ORM; OS/PTY are synthetic.

The catalog uses the real installed wrapper entry. Inspection delegates to
the actual Telemetry host function in-process so synthetic OS facts stay in
this process. This is not real tmux/native/control-client acceptance.
"""
import asyncio
import contextvars
import hashlib
from contextlib import asynccontextmanager
import importlib.util
import json
import math
import os
from pathlib import Path
import shlex
import re
import runpy
import statistics
import subprocess
import sys
import shutil
import socket as network_socket
import tempfile
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aiohttp import ClientSession, web, WSMsgType

BRIDGE=Path(__file__).resolve().parents[1]
T=Path(os.environ['ORRERY_TEST_TELEMETRY_ROOT']).resolve()
sys.path[:0]=[str(BRIDGE),str(T),str(T/'packages/agentstack_mail/src'),str(T/'packages/agentstack_mail/tests'),str(T/'tests')]
import orrery_backend as ob
import control_server as control
import runtime_target as boundary
from agentstack_mail.fresh_client import FreshBoundClient
from agentstack_mail.fresh_runtime import _read_private,_write_private
from agentstack_mail.fresh_targets import execute
from agentstack_mail.storage_origin_contract import B1Error
from dashboard.fresh_backend import Backend
from dashboard.fresh_host import Host

spec=importlib.util.spec_from_file_location('telemetry_target_fixture',T/'packages/agentstack_mail/tests/test_fresh_targets.py')
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)


class Peer:
    def __init__(self):self.messages=[]
    async def send(self,data):self.messages.append(json.loads(data))
    async def send_json(self,value):self.messages.append(value)


async def ended_cleanup_roundtrip(manager,peer,attached,targets,query):
    """Shared mock/external assertion: stop owned observers before one effect."""
    from agentstack_mail.fresh_targets import Targets
    await manager.detach(peer,attached,'Alpha')
    await manager._reconcile_fresh()
    assert not any(s.bridge.config.tmux_bin.ref==query for s in manager.states.values())
    deadline=time.monotonic()+10
    while True:
        selected=await targets.select_managed(query)
        try:
            _,view=await asyncio.to_thread(targets.cleanup_status,selected)
            if not view['attached']:break
        except B1Error as exc:
            if exc.code not in {'FRESH_CLEANUP_PROCESS_PRESENT','FRESH_CLEANUP_TARGET_CHANGED'}:raise
        assert time.monotonic()<deadline,'owned cleanup target did not become stopped'
        await asyncio.sleep(.05)
    result=await targets.cleanup(query)
    assert result['ok'] and result['effects']['retire']=='retired'
    assert result['effects']['tmux'] in {'pane_removed','already_absent'}
    with pytest.raises(B1Error,match='TARGET_RETIRED'):await targets.select(query)
    return dict(same_identity=all(result[k]==v for k,v in query.items()),
                owned_consumers_stopped=True,retired=True,tmux=result['effects']['tmux'],ordinary_retired_refused=True)


def test_external_cleanup_assertions_replay_real_targets_before_fixed_run(tmp_path,monkeypatch):
    async def scenario():
        from agentstack_mail.fresh_targets import Targets
        from types import SimpleNamespace
        async with helpers.cleanup_fixture(tmp_path,monkeypatch) as (runtime,people,client,operator,run,row,calls,tmux,processes,state):
            query=dict(mail_instance_id=runtime.config['instance_id'],mail_agent_id=people[0]['agent_id'])
            state['attached']=True;order=[]
            async def detach(*args):state['attached']=False;order.append('detach')
            async def reconcile():order.append('reconcile')
            manager=SimpleNamespace(detach=detach,_reconcile_fresh=reconcile,states={})
            proof=await ended_cleanup_roundtrip(manager,Peer(),set(),Targets(operator,T),query)
            assert order==['detach','reconcile'] and proof['same_identity'] and proof['ordinary_retired_refused']
            assert sum(a[0]=='kill-pane' for a,k in calls)==1
    asyncio.run(scenario())


@pytest.mark.parametrize('ended',[True,False])
def test_manager_stops_only_ended_unviewed_consumers_and_allows_explicit_reattach(tmp_path,monkeypatch,ended):
    async def scenario():
        target=object.__new__(boundary.FreshPaneBoundary)
        target.pane_id='%1';target.wire_pane='fresh-fixture-1';target.history_key='fresh-fixture'
        target.ref={'mail_instance_id':'0'*32,'mail_agent_id':1};target.name='Alpha';target.key='key'
        target.proof=dict(ended=ended,current='run',route={},**target.ref)
        root=object.__new__(boundary.FreshTargetBoundary)
        root.resolve=lambda *args:target;root.catalog=lambda:[dict(session='Alpha',**target.ref)];root.truncated=False
        manager=ob.SessionBridgeManager(root,history_dir=tmp_path)
        starts=[];stops=[]
        async def start(bridge):starts.append(bridge)
        original_stop=ob.SessionTmuxBridge.stop
        async def stop(bridge):
            await original_stop(bridge);stops.append(bridge)
        async def snapshot(bridge,peer,*,attach_generation=None):
            await bridge.send_json(peer,dict(type='reset',attachGeneration=attach_generation),attach_generation=attach_generation)
        monkeypatch.setattr(ob.SessionTmuxBridge,'start',start)
        monkeypatch.setattr(ob.SessionTmuxBridge,'stop',stop)
        monkeypatch.setattr(ob.SessionTmuxBridge,'send_snapshot',snapshot)
        p,q=Peer(),Peer();pa,qa=set(),set()
        try:
            await manager._reconcile_fresh()
            assert len(manager.states)==(0 if ended else 1)
            await manager._attach_fresh(p,pa,'Alpha')
            await manager._attach_fresh(q,qa,'Alpha')
            old=manager.states['key'].bridge
            await manager.detach(p,pa,'Alpha')
            assert 'key' in manager.states and q in old.clients and not old._closed
            await manager.detach(q,qa,'Alpha')
            assert (old in stops)==ended
            assert ('key' in manager.states)==(not ended)
            await manager._reconcile_fresh()
            assert ('key' in manager.states)==(not ended)
            await manager._attach_fresh(p,pa,'Alpha')
            assert 'key' in manager.states
            if ended:assert manager.states['key'].bridge is not old
        finally:await manager.close()
    asyncio.run(scenario())


def test_manager_stop_serializes_late_attach_and_preserves_other_state(tmp_path,monkeypatch):
    async def scenario():
        target=object.__new__(boundary.FreshPaneBoundary)
        target.pane_id='%1';target.wire_pane='fresh-fixture-1';target.history_key='fresh-fixture'
        target.ref={'mail_instance_id':'0'*32,'mail_agent_id':1};target.name='Alpha';target.key='key'
        target.proof=dict(ended=True,current='run',route={},**target.ref)
        root=object.__new__(boundary.FreshTargetBoundary);root.resolve=lambda *a:target
        manager=ob.SessionBridgeManager(root,history_dir=tmp_path)
        bridge=ob.SessionTmuxBridge(control.ControlConfig('127.0.0.1',0,'Alpha',target,history_dir=tmp_path))
        state=ob.SessionState(bridge=bridge);manager.states['key']=state
        entered=asyncio.Event();release=asyncio.Event();attached={'key'};peer=Peer()
        await bridge.attach_fresh_peer(peer)
        original_stop=manager._stop_bridge
        async def slow_stop(value):
            entered.set();await release.wait();await original_stop(value)
        monkeypatch.setattr(manager,'_stop_bridge',slow_stop)
        async def stale_ensure(value):return state
        monkeypatch.setattr(manager,'_ensure_fresh_bridge',stale_ensure)
        detached=asyncio.create_task(manager.detach(peer,attached,'Alpha'))
        await entered.wait()
        incoming=Peer();joining=asyncio.create_task(manager._attach_fresh(incoming,set(),'Alpha'))
        await asyncio.sleep(0);assert not joining.done()
        release.set();await detached
        with pytest.raises(boundary.TargetRefused,match='FRESH_TARGET_VIEW_CHANGED'):await joining
        assert bridge._closed and incoming not in bridge.clients
        await manager.close()
    asyncio.run(scenario())


def test_effect_proofs_are_independent_expire_and_refuse_after_close(monkeypatch):
    async def scenario():
        now=[100.0];calls=[];failure=[False]
        monkeypatch.setattr(boundary.time,'monotonic',lambda:now[0])
        class Target:
            pane_id='%1'
            def admit(self,purpose,**kwargs):calls.append(('full',purpose))
            def membership(self):
                calls.append(('member',))
                if failure[0]:raise boundary.TargetRefused('FRESH_TMUX_TARGET_CHANGED')
        target=Target()
        peer1=boundary.FreshEffectProof(target,'input')
        peer2=boundary.FreshEffectProof(target,'capture')
        recorder=boundary.FreshEffectProof(target,'capture')
        await peer1.check();await peer1.check();await peer2.check();await recorder.check()
        assert calls.count(('full','input'))==1 and calls.count(('full','capture'))==2
        peer1.close()
        with pytest.raises(boundary.TargetRefused):await peer1.check()
        failure[0]=True
        with pytest.raises(boundary.TargetRefused):await peer2.check()
        assert recorder.expires==105.0
        failure[0]=False;now[0]=105.0
        await recorder.check()
        assert calls.count(('full','capture'))==3
    asyncio.run(scenario())


def test_output_recorder_and_two_peer_admissions_are_independent(tmp_path):
    async def scenario():
        target=object.__new__(boundary.FreshPaneBoundary)
        target.pane_id='%1';target.wire_pane='fresh-fixture-1';target.history_key='fresh-fixture'
        target.ref={'mail_instance_id':'0'*32,'mail_agent_id':1}
        bridge=ob.SessionTmuxBridge(control.ControlConfig('127.0.0.1',0,'Alpha',target,history_dir=tmp_path))
        class Proof:
            def __init__(self,ok):self.ok=ok;self.closed=False
            async def check(self):
                if not self.ok:raise boundary.TargetRefused('FRESH_TARGET_PROOF_EXPIRED')
            def close(self):self.closed=True
        class Recorder:
            def __init__(self):self.values=[]
            def feed(self,value):self.values.append(value)
        good,bad=Peer(),Peer();recorder=Recorder()
        bridge.clients.update((good,bad))
        bridge._fresh_peer_proofs={good:(Proof(True),Proof(True)),bad:(Proof(True),Proof(False))}
        bridge._fresh_recorder_proof=Proof(False);bridge._pane_recorders['%1']=recorder
        bridge._fresh_output=['selected-output']
        await bridge._publish_fresh_output()
        await asyncio.gather(*list(bridge._fresh_sink_tasks))
        if bridge._fresh_sink_tasks:await asyncio.gather(*list(bridge._fresh_sink_tasks))
        assert recorder.values==[] and all(row.get('type')=='error' for row in bad.messages)
        assert len(good.messages)==1 and good.messages[0]['data']=='selected-output'
    asyncio.run(scenario())


def test_slow_peer_does_not_block_other_peer_or_change_order(tmp_path):
    async def scenario():
        target=object.__new__(boundary.FreshPaneBoundary)
        target.pane_id='%1';target.wire_pane='fresh-fixture-1';target.history_key='fresh-fixture'
        target.ref={'mail_instance_id':'0'*32,'mail_agent_id':1}
        bridge=ob.SessionTmuxBridge(control.ControlConfig('127.0.0.1',0,'Alpha',target,history_dir=tmp_path))
        release=asyncio.Event()
        class Proof:
            def __init__(self,slow=False):self.slow=slow;self.closed=False
            async def check(self):
                if self.slow:await release.wait()
            def close(self):self.closed=True
        fast,slow=Peer(),Peer();bridge.clients.update((fast,slow))
        bridge._fresh_peer_proofs={fast:(Proof(),Proof()),slow:(Proof(),Proof(True))}
        for value in ('first','second'):
            bridge._fresh_output=[value];await bridge._publish_fresh_output()
        for _ in range(100):
            if len(fast.messages)==2:break
            await asyncio.sleep(0)
        assert [row['data'] for row in fast.messages]==['first','second'] and slow.messages==[]
        release.set();await asyncio.gather(*list(bridge._fresh_sink_tasks))
        assert [row['data'] for row in slow.messages]==['first','second']
        assert not bridge._fresh_sink_bytes
    asyncio.run(scenario())


def test_output_overflow_reports_gap_only_to_affected_sink(tmp_path,capsys):
    async def scenario():
        target=object.__new__(boundary.FreshPaneBoundary)
        target.pane_id='%1';target.wire_pane='fresh-fixture-1';target.history_key='fresh-fixture'
        target.ref={'mail_instance_id':'0'*32,'mail_agent_id':1}
        bridge=ob.SessionTmuxBridge(control.ControlConfig('127.0.0.1',0,'Alpha',target,history_dir=tmp_path))
        class Proof:
            closed=False
            def close(self):self.closed=True
        peer=Peer();other=Peer();count_peer=Peer();proof=Proof();recorder=object();recordproof=Proof();count_proof=Proof()
        bridge.clients.update((peer,other,count_peer));bridge._fresh_peer_proofs={peer:(Proof(),proof),other:(Proof(),Proof()),count_peer:(Proof(),count_proof)}
        bridge._schedule_fresh_sink(proof,'x'*262145,peer=peer)
        bridge._schedule_fresh_sink(recordproof,'x'*262145,recorder=recorder)
        bridge._fresh_sink_counts[count_proof]=256
        bridge._schedule_fresh_sink(count_proof,'x',peer=count_peer)
        await asyncio.gather(*list(bridge._fresh_sink_tasks))
        assert proof.closed and recordproof.closed and count_proof.closed and peer not in bridge.clients and count_peer not in bridge.clients and other in bridge.clients
        assert peer.messages[0]['type']=='error' and peer.messages[0]['code']=='FRESH_OUTPUT_INCOMPLETE'
        assert 'history may have a gap' in capsys.readouterr().err
    asyncio.run(scenario())


def test_bridge_stop_cancels_pending_sink_tasks(tmp_path):
    async def scenario():
        target=object.__new__(boundary.FreshPaneBoundary)
        target.pane_id='%1';target.wire_pane='fresh-fixture-1';target.history_key='fresh-fixture'
        target.ref={'mail_instance_id':'0'*32,'mail_agent_id':1}
        bridge=ob.SessionTmuxBridge(control.ControlConfig('127.0.0.1',0,'Alpha',target,history_dir=tmp_path))
        entered=asyncio.Event();release=asyncio.Event()
        class Proof:
            closed=False
            async def check(self):entered.set();await release.wait()
            def close(self):self.closed=True
        peer=Peer();input_proof=Proof();output_proof=Proof()
        bridge.clients.add(peer);bridge._fresh_peer_proofs={peer:(input_proof,output_proof)}
        bridge._schedule_fresh_sink(output_proof,'pending',peer=peer)
        await entered.wait();await bridge.stop()
        assert input_proof.closed and output_proof.closed and not bridge._fresh_sink_tasks
        assert not bridge._fresh_sink_bytes and not bridge._fresh_sink_counts and peer.messages==[]
    asyncio.run(scenario())


def test_old_sink_failure_does_not_remove_new_peer_proof(tmp_path):
    async def scenario():
        target=object.__new__(boundary.FreshPaneBoundary)
        target.pane_id='%1';target.wire_pane='fresh-fixture-1';target.history_key='fresh-fixture'
        target.ref={'mail_instance_id':'0'*32,'mail_agent_id':1}
        bridge=ob.SessionTmuxBridge(control.ControlConfig('127.0.0.1',0,'Alpha',target,history_dir=tmp_path))
        peer=Peer();await bridge.attach_fresh_peer(peer);old=bridge._fresh_peer_proofs[peer]
        # Queue the failure, then let the actual attach boundary win before
        # the notification task takes the send lock.
        bridge._fail_fresh_sink(old[1],peer=peer)
        generation=await bridge.attach_fresh_peer(peer);new=bridge._fresh_peer_proofs[peer]
        await bridge.send_json(peer,dict(type='reset',attachGeneration=generation),attach_generation=generation)
        await asyncio.gather(*list(bridge._fresh_sink_tasks))
        assert old[0].closed and old[1].closed and bridge._fresh_peer_proofs[peer] is new
        assert not new[0].closed and not new[1].closed and peer in bridge.clients
        assert [row['type'] for row in peer.messages]==['reset']
    asyncio.run(scenario())


def test_manager_reattach_orders_old_gap_before_new_reset_and_detach_invalidates(tmp_path,monkeypatch):
    async def scenario():
        target=object.__new__(boundary.FreshPaneBoundary)
        target.pane_id='%1';target.wire_pane='fresh-fixture-1';target.history_key='fresh-fixture'
        target.ref={'mail_instance_id':'0'*32,'mail_agent_id':1};target.name='Alpha';target.key='key'
        bridge=ob.SessionTmuxBridge(control.ControlConfig('127.0.0.1',0,'Alpha',target,history_dir=tmp_path))
        root=object.__new__(boundary.FreshTargetBoundary);root.resolve=lambda *args:target
        manager=ob.SessionBridgeManager(root,history_dir=tmp_path)
        state=ob.SessionState(bridge=bridge);manager.states[target.key]=state
        async def ensure(value):return state
        monkeypatch.setattr(manager,'_ensure_fresh_bridge',ensure)
        async def snapshot(peer,*,attach_generation=None):
            await bridge.send_json(peer,dict(type='reset',attachGeneration=attach_generation),attach_generation=attach_generation)
        monkeypatch.setattr(bridge,'send_snapshot',snapshot)
        entered=asyncio.Event();release=asyncio.Event()
        class SlowPeer(Peer):
            async def send(self,data):
                if json.loads(data).get('code')=='FRESH_OUTPUT_INCOMPLETE':
                    entered.set();await release.wait()
                await super().send(data)
        peer=SlowPeer();other=Peer();attached=set();other_attached=set()
        await manager._attach_fresh(peer,attached,'Alpha')
        await manager._attach_fresh(other,other_attached,'Alpha')
        old_generation=bridge._fresh_peer_generations[peer];other_proofs=bridge._fresh_peer_proofs[other]
        bridge._fail_fresh_sink(bridge._fresh_peer_proofs[peer][1],peer=peer)
        await entered.wait()
        reattach=asyncio.create_task(manager._attach_fresh(peer,attached,'Alpha'))
        await asyncio.sleep(0)
        assert not reattach.done()
        release.set();await reattach
        await asyncio.gather(*list(bridge._fresh_sink_tasks))
        assert [row['type'] for row in peer.messages]==['reset','error','reset']
        assert peer.messages[1]['attachGeneration']==old_generation
        assert peer.messages[-1]['attachGeneration']!=old_generation
        assert bridge._fresh_peer_proofs[other] is other_proofs and len(other.messages)==1
        await manager.detach(peer,attached,target.key)
        assert peer not in bridge.clients and peer not in bridge._fresh_peer_generations
        assert not attached and other in bridge.clients
    asyncio.run(scenario())


def test_sink_error_send_failure_closes_only_affected_websocket(tmp_path):
    async def scenario():
        target=object.__new__(boundary.FreshPaneBoundary)
        target.pane_id='%1';target.wire_pane='fresh-fixture-1';target.history_key='fresh-fixture'
        target.ref={'mail_instance_id':'0'*32,'mail_agent_id':1}
        bridge=ob.SessionTmuxBridge(control.ControlConfig('127.0.0.1',0,'Alpha',target,history_dir=tmp_path))
        class Response:
            def __init__(self):self.closed=[]
            async def send_str(self,data):raise OSError('synthetic transport failure')
            async def close(self,**kwargs):self.closed.append(kwargs)
        response=Response();peer=ob.WebSocketPeer(response);other=Peer()
        await bridge.attach_fresh_peer(peer);await bridge.attach_fresh_peer(other)
        bridge._fail_fresh_sink(bridge._fresh_peer_proofs[peer][1],peer=peer)
        await asyncio.gather(*list(bridge._fresh_sink_tasks))
        assert len(response.closed)==1 and response.closed[0]['code']==1011
        assert peer not in bridge.clients and other in bridge.clients and other.messages==[]
    asyncio.run(scenario())


def test_detach_during_refresh_cannot_revive_proof():
    async def scenario():
        entered=threading.Event();release=threading.Event()
        class Target:
            pane_id='%1'
            def admit(self,*args,**kwargs):entered.set();release.wait(3)
            def membership(self):raise AssertionError('closed proof reached membership')
        proof=boundary.FreshEffectProof(Target(),'input')
        task=asyncio.create_task(proof.check())
        assert await asyncio.to_thread(entered.wait,3)
        proof.close();release.set()
        with pytest.raises(boundary.TargetRefused):await task
        assert proof.closed and proof.expires==0
    asyncio.run(scenario())


def test_full_confirmation_that_takes_five_seconds_never_becomes_a_proof(monkeypatch):
    async def scenario():
        now=[100.0];monkeypatch.setattr(boundary.time,'monotonic',lambda:now[0])
        class Target:
            pane_id='%1'
            def admit(self,*args,**kwargs):now[0]=105.0
            def membership(self):raise AssertionError('expired proof reached membership')
        proof=boundary.FreshEffectProof(Target(),'input')
        with pytest.raises(boundary.TargetRefused,match='FRESH_TARGET_PROOF_EXPIRED'):await proof.check()
        assert proof.expires==0
    asyncio.run(scenario())


def test_background_refresh_uses_old_proof_only_until_expiry_and_close(monkeypatch):
    async def scenario():
        now=[100.0];monkeypatch.setattr(boundary.time,'monotonic',lambda:now[0])
        entered=threading.Event();release=threading.Event();calls=[]
        class Target:
            pane_id='%1'
            def admit(self,*args,**kwargs):
                calls.append('full')
                if len(calls)>1:entered.set();release.wait(3)
            def membership(self):calls.append('member')
        proof=boundary.FreshEffectProof(Target(),'input')
        await proof.check();assert proof.expires==105.0
        now[0]=103.1
        await proof.check()
        assert await asyncio.to_thread(entered.wait,3)
        assert proof.expires==105.0
        proof.close();release.set()
        if proof.refresh is not None:await proof.refresh
        assert proof.closed and proof.expires==0
        with pytest.raises(boundary.TargetRefused):await proof.check()
    asyncio.run(scenario())


def test_expired_proof_waits_for_refresh_and_never_replays_after_failure(monkeypatch):
    async def scenario():
        now=[100.0];monkeypatch.setattr(boundary.time,'monotonic',lambda:now[0])
        entered=threading.Event();release=threading.Event();calls=[]
        class Target:
            pane_id='%1'
            def admit(self,*args,**kwargs):
                calls.append('full')
                if calls.count('full')>1:
                    entered.set();release.wait(3);raise boundary.TargetRefused('FRESH_TMUX_TARGET_CHANGED')
            def membership(self):calls.append('member')
        proof=boundary.FreshEffectProof(Target(),'capture')
        await proof.check();now[0]=103.1;await proof.check()
        assert await asyncio.to_thread(entered.wait,3)
        now[0]=105.1;pending=asyncio.create_task(proof.check());await asyncio.sleep(0)
        assert not pending.done()
        release.set()
        with pytest.raises(boundary.TargetRefused,match='FRESH_TMUX_TARGET_CHANGED'):await pending
        before=len(calls)
        with pytest.raises(boundary.TargetRefused):await proof.check()
        assert len(calls)==before and proof.expires==0
    asyncio.run(scenario())


@pytest.mark.parametrize('damage',['none','host_before','host_after','socket','pane','pid','unavailable'])
def test_local_membership_checks_fixed_host_socket_pane_and_pid(damage):
    calls=[];identity=(1,2,3,4)
    def host_identity(path):
        calls.append(True)
        return (9,9,9,9) if damage=='host_before' or damage=='host_after' and len(calls)>1 else identity
    class Transport:
        def __init__(self,path,**kwargs):self.identity=(99,99) if damage=='socket' else (11,22)
    def panes(transport,**kwargs):
        if damage=='unavailable':raise RuntimeError('unavailable')
        return [dict(session_id='$1',pane_id='%9' if damage=='pane' else '%2',pid=999 if damage=='pid' else 100)]
    target=object.__new__(boundary.FreshPaneBoundary)
    target.parent=SimpleNamespace(host_api=dict(fresh_host_identity=host_identity,Transport=Transport,panes=panes),host_path=Path('/fixture/host'),host_socket=identity)
    target.pane_id='%2';target.binary='/fixture/tmux'
    target.proof=dict(route=dict(socket_path='/fixture/socket',socket_identity=[11,22],pane=dict(session_id='$1',pane_id='%2',pid=100)))
    if damage=='none':
        target.membership();assert len(calls)==2
    else:
        with pytest.raises(boundary.TargetRefused):target.membership()


def test_idle_refresh_timer_is_independent_single_flight_and_cancelled(monkeypatch):
    async def scenario():
        loop=asyncio.get_running_loop();scheduled=[];tasks=[]
        real_later=loop.call_later
        class Handle:
            cancelled=False
            def cancel(self):self.cancelled=True
        def later(delay,callback,*args,**kwargs):
            if args or kwargs:return real_later(delay,callback,*args,**kwargs)
            handle=Handle();scheduled.append((delay,callback,handle));return handle
        monkeypatch.setattr(loop,'call_later',later)
        full=[];entered=threading.Event();release=threading.Event()
        class Target:
            pane_id='%1'
            def admit(self,purpose,**kwargs):
                full.append(purpose)
                if len(full)>2:entered.set();release.wait(2)
            def membership(self):pass
        target=Target();first=boundary.FreshEffectProof(target,'input');other=boundary.FreshEffectProof(target,'capture')
        try:
            await first.check();await other.check()
            assert len(scheduled)==2 and all(0<item[0]<=3 for item in scheduled)
            scheduled[0][1]()
            assert await asyncio.to_thread(entered.wait,2)
            refresh=first.refresh
            scheduled[0][1]();await asyncio.sleep(0)
            assert first.refresh is refresh and full==['input','capture','input']
            first.close();release.set();await refresh
            assert first.closed and first.expires==0 and not other.closed
            other.close();assert scheduled[1][2].cancelled
            count=len(full);scheduled[1][1]();await asyncio.sleep(0)
            assert len(full)==count
        finally:
            release.set();first.close();other.close()
            await asyncio.gather(*(p.refresh for p in (first,other) if p.refresh is not None),return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize('damage',['none','session','pane','pid','rc','format','overflow','host_after','socket_before','socket_after','timeout','expired','proof_close','proof_expiry'])
def test_control_membership_uses_fixed_query_parser_order_and_input_lock(tmp_path,monkeypatch,damage):
    async def scenario():
        after=[False];writes=[];aborted=[];host=(1,2,3,4)
        class Transport:
            def __init__(self,path,**kwargs):self.path=path;self.identity=(33,44) if damage=='socket_before' else (11,22)
        def host_identity(path):return (9,9,9,9) if after[0] and damage=='host_after' else host
        target=object.__new__(boundary.FreshPaneBoundary)
        target.pane_id='%2';target.wire_pane='fresh-fixture';target.history_key='fixture';target.binary='/fixture/tmux'
        target.ref=dict(mail_instance_id='0'*32,mail_agent_id=1)
        target.proof=dict(route=dict(socket_path='/fixture/socket',socket_identity=[11,22],pane=dict(session_id='$1',session='fixture',pane_id='%2',pid=100)))
        target.parent=SimpleNamespace(host_path=Path('/fixture/host'),host_socket=host,
            host_api=dict(Transport=Transport,fresh_host_identity=host_identity,
                validate_socket=lambda path:(33,44) if after[0] and damage=='socket_after' else (11,22)))
        target.admit=lambda *args,**kwargs:None
        bridge=ob.SessionTmuxBridge(control.ControlConfig('127.0.0.1',0,'Alpha',target,history_dir=tmp_path))
        bridge.master_fd=99
        monkeypatch.setattr(bridge,'_abort_mobile_stream',lambda:aborted.append(True))
        async def writer(raw):
            args=shlex.split(raw.decode());writes.append(args)
            if args[0]=='display-message':
                assert args==['display-message','-p','-t','%2','#{session_id}\t#{session_name}\t#{pane_id}\t#{pane_pid}']
                after[0]=True
                if damage=='timeout':return
                fields=['$9' if damage=='session' else '$1','fixture','%9' if damage=='pane' else '%2','999' if damage=='pid' else '100']
                line='x'*16385 if damage=='overflow' else 'malformed' if damage=='format' else '\t'.join(fields)
                if damage=='proof_close':proof.close()
                if damage=='proof_expiry':proof.expires=0
                bridge._handle_line('%begin 1 1 0');bridge._handle_line(line)
                bridge._handle_line('%error 1 1 0' if damage=='rc' else '%end 1 1 0')
            else:
                bridge._handle_line('%begin 1 2 0');bridge._handle_line('%end 1 2 0')
        monkeypatch.setattr(bridge,'_write_master',writer)
        proof=boundary.FreshEffectProof(target,'input',membership=bridge._fresh_control_membership_locked)
        try:
            if damage in {'timeout','expired'}:
                # A prepared proof with a short test-only remaining deadline.
                proof.expires=time.monotonic()+(.015 if damage=='timeout' else -1)
                proof.failed=False
                async with bridge._write_lock:
                    with pytest.raises(boundary.TargetRefused):
                        await bridge._fresh_control_membership_locked(deadline=proof.expires)
            elif damage=='none':
                await asyncio.wait_for(bridge.send_input('%2','literal',proof=proof),2)
                assert [w[0] for w in writes]==['display-message','send-keys'] and not aborted
                # A second consumer queries independently and gets its own ACK.
                await bridge._fresh_control_membership(deadline=time.monotonic()+1)
                assert len([w for w in writes if w[0]=='display-message'])==2
                assert not bridge._pending_blocks and not bridge._bounded_blocks
            else:
                with pytest.raises(boundary.TargetRefused):await bridge.send_input('%2','must not send',proof=proof)
            if damage!='none':assert all(w[0]!='send-keys' for w in writes)
            assert bool(aborted)==(damage=='timeout')
        finally:proof.close();bridge._fresh_recorder_proof.close()
    asyncio.run(scenario())


async def external_dashboard_restart(client, env, tmp_path):
    """SIGTERM the two dashboard children owned by this private fixture."""
    api=runpy.run_path(str(T/'bin/lib/runtime_tmux.py'))
    path=api['fresh_host_path'](client.path)
    identities=[]
    for _ in range(2):
        with network_socket.socket() as port_socket:
            port_socket.bind(('127.0.0.1',0));port=port_socket.getsockname()[1]
        assert port not in {8765,8770,8781,8791}
        child_env=dict(env,AGENTSTACK_PORT=str(port),AGENTSTACK_BIND_HOST='127.0.0.1')
        process=await asyncio.create_subprocess_exec(sys.executable,'-u',str(T/'dashboard/server.py'),
            cwd=str(tmp_path),env=child_env,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+30
            while not path.exists():
                assert process.returncode is None and time.monotonic()<deadline,'private dashboard did not start'
                await asyncio.sleep(.05)
            identity, hello=await asyncio.to_thread(api['fresh_host_call'],path,{'operation':'hello'})
            assert hello['pin']['mail_instance_id']==client.context['mail_instance_id']
            identities.append((identity,hello['pin']['epoch']))
            process.terminate()
            assert await asyncio.wait_for(process.wait(),15)==0
            assert not path.exists()
        finally:
            if process.returncode is None:
                process.kill();await process.wait()
    assert identities[0][1]!=identities[1][1]
    (tmp_path/'dashboard-stop-proof.json').write_text(json.dumps(dict(sigterm_restart=True,epoch_changed=True)))


class FixtureMarkerStream:
    """Private fixture marker parser; keys keep mode/block/receiver streams separate."""
    def __init__(self):self.buffers={}
    def take(self,stream,data):
        value=self.buffers.get(stream,'')+data
        found=list(re.finditer(r'BENCH([0-9]{3})END',value))
        self.buffers[stream]=(value[found[-1].end():] if found else value)[-32:]
        return [int(match.group(1)) for match in found]


def check_fixture_observers(mode,manager,pane,other,record):
    """Legacy records the session; fresh records exactly its selected pane."""
    assert mode in {'L','F'}
    expected={pane,other} if mode=='L' else {pane}
    states=list(manager.states.values())
    bridge=states[0].bridge if len(states)==1 else None
    panes=set(bridge.panes) if bridge is not None else set()
    recorders=set(bridge._pane_recorders) if bridge is not None else set()
    proof=dict(mode=mode,managers=1,bridges=len(states),peers=len(bridge.clients) if bridge is not None else 0,
        panes=len(panes),recorders=len(recorders),expected_panes=len(expected),
        selected_pane=pane in panes,other_pane=other in panes,
        selected_recorder=pane in recorders,other_recorder=other in recorders,
        panes_match=panes==expected,recorders_match=recorders==expected)
    record(proof)  # Preserve actual non-secret counts even when an assertion fails.
    assert len(states)==1,'control fixture did not resolve exactly one target'
    assert proof['peers']==1,'unexpected benchmark peer count'
    assert proof['panes_match'] and proof['recorders_match'],'unexpected benchmark pane/recorder targets'
    return bridge


def test_observer_setup_helper_uses_real_refresh_panes_for_both_modes(tmp_path,monkeypatch):
    async def scenario():
        for mode in ('L','F'):
            target=object.__new__(boundary.FreshPaneBoundary if mode=='F' else boundary.LegacyTargetBoundary)
            if mode=='F':
                target.pane_id='%2';target.wire_pane='fresh-fixture';target.history_key='fixture'
                target.ref=dict(mail_instance_id='0'*32,mail_agent_id=1)
            bridge=ob.SessionTmuxBridge(control.ControlConfig('127.0.0.1',0,'fixture',target,history_dir=tmp_path/mode))
            bridge._session_created=1;peer=Peer();bridge.clients.add(peer)
            lines=['%2\t@2\t$1\t0\t0\t80\t24\t0\tselected\tclaude\t0\t0\t0\t0',
                   '%9\t@9\t$1\t1\t0\t80\t24\t1\tother\tcat\t0\t0\t0\t0']
            async def command(args,**kwargs):
                return control.CommandResult(True,lines if args[0]=='list-panes' else [])
            monkeypatch.setattr(bridge,'send_command',command)
            await bridge.refresh_panes(send_captures=False)
            manager=SimpleNamespace(states={'fixture':SimpleNamespace(bridge=bridge)})
            proofs=[]
            assert check_fixture_observers(mode,manager,'%2','%9',proofs.append) is bridge
            assert proofs[-1]['recorders']==(2 if mode=='L' else 1)
            saved=bridge._pane_recorders.pop('%2')
            with pytest.raises(AssertionError):check_fixture_observers(mode,manager,'%2','%9',proofs.append)
            assert not proofs[-1]['recorders_match']
            bridge._pane_recorders['%2']=saved
            bridge._pane_recorders['%7']=saved
            with pytest.raises(AssertionError):check_fixture_observers(mode,manager,'%2','%9',proofs.append)
            bridge._pane_recorders.pop('%7')
            pane=bridge.panes.pop('%2')
            with pytest.raises(AssertionError):check_fixture_observers(mode,manager,'%2','%9',proofs.append)
            bridge.panes['%2']=pane;bridge.panes['%7']=pane
            with pytest.raises(AssertionError):check_fixture_observers(mode,manager,'%2','%9',proofs.append)
            bridge.panes.pop('%7')
            extra=Peer();bridge.clients.add(extra)
            with pytest.raises(AssertionError):check_fixture_observers(mode,manager,'%2','%9',proofs.append)
            assert proofs[-1]['peers']==2
            bridge.clients.clear()
            with pytest.raises(AssertionError):check_fixture_observers(mode,manager,'%2','%9',proofs.append)
            assert proofs[-1]['peers']==0
            if bridge._fresh_recorder_proof is not None:bridge._fresh_recorder_proof.close()
    asyncio.run(scenario())


def output_chunk_admission_durations(rows,chunks,mode):
    """Require the actual sent chunk's peer proof, never a nearby full inspect."""
    durations=[];sequences=[];peers=set()
    for key,row in rows:
        matches=[chunk for chunk in chunks if chunk['mode']==mode and chunk['active_mode']==mode and key in chunk['events']]
        assert len(matches)==1,'missing or ambiguous output chunk timing'
        chunk=matches[0]
        peers.add(chunk['peer']);sequences.append(chunk['sequence'])
        assert chunk.get('sent') is True,'output chunk did not complete send'
        assert {'proof_begin','proof_end'}<=chunk.keys(),'missing output admission timing'
        assert row['echo']<=chunk['send_begin']<=chunk['proof_begin']<=chunk['proof_end']<=chunk['send_end']
        assert chunk['proof_end']<=row['ws_echo']
        durations.append(1000*(chunk['proof_end']-chunk['proof_begin']))
    assert len(peers)==1 and sequences==sorted(sequences),'output peer or chunk order changed'
    return sorted(durations)


def test_output_chunk_measurement_requires_exact_event_and_completed_proof():
    rows=[('F000',dict(echo=1.,ws_echo=2.)),('F001',dict(echo=1.1,ws_echo=2.))]
    chunk=dict(mode='F',active_mode='F',peer='fixture-peer',sequence=1,events=['F000','F001'],send_begin=1.2,proof_begin=1.3,proof_end=1.4,send_end=1.5,sent=True)
    assert output_chunk_admission_durations(rows,[chunk],'F')==pytest.approx([100.,100.])
    for damaged in ([],[dict(chunk,events=['F000'])],[dict(chunk,sent=False)],[chunk,chunk]):
        with pytest.raises(AssertionError):output_chunk_admission_durations(rows,damaged,'F')
    missing=dict(chunk);missing.pop('proof_begin')
    with pytest.raises(AssertionError,match='missing output admission timing'):
        output_chunk_admission_durations(rows,[missing],'F')
    assert output_chunk_admission_durations(rows,[chunk,dict(chunk,active_mode='L')],'F')==pytest.approx([100.,100.])
    for second in (dict(chunk,events=['F001'],peer='other'),dict(chunk,events=['F001'],sequence=0)):
        with pytest.raises(AssertionError,match='peer or chunk order'):
            output_chunk_admission_durations(rows,[dict(chunk,events=['F000']),second],'F')
    stream=FixtureMarkerStream()
    assert stream.take(('F',0),'BENCH0')==[]
    assert stream.take(('L',0),'00END')==[]
    assert stream.take(('F',0),'00EN')==[]
    assert stream.take(('F',0),'D\r\nBENCH001ENDBENCH002END')==[0,1,2]
    assert stream.take(('F',1),'00END')==[]


async def external_latency_benchmark(tmp_path, monkeypatch, root, tmux, socket, pane, other, command, resident):
    """Compare real guarded WebSocket-to-echo paths; called only by the parent fixture."""
    pid=(await command('display-message','-p','#{pid}')).stdout.strip()
    legacy_home=tmp_path/'legacy-install'
    shutil.copytree(T/'bin/lib',legacy_home/'bin/lib')
    schema_source=T/'packages/agentstack_mail/src/agentstack_mail/schema_contract.py'
    shutil.copy2(schema_source,legacy_home/'bin/lib/schema_contract.py')
    legacy_env=dict(root.environment,TMUX=f'{socket},{pid},0',AGENTSTACK_RUNTIME_MODE='legacy',AGENTSTACK_HOME=str(legacy_home))
    for key in ('AGENTSTACK_FRESH_CLIENT_CONTEXT','AGENTSTACK_CLIENT_CONFIG','AGENTSTACK_GLOBAL_SERVER_CONFIG'):
        legacy_env.pop(key,None)
    legacy_env.pop('LC_ALL',None)
    legacy_env['LC_CTYPE']='C.UTF-8'
    legacy=boundary.LegacyTargetBoundary(tmux,environ=legacy_env)
    assert legacy.shared is not None, 'legacy installed helper not loaded'
    files=('runtime_tmux.py','runtime_tmux_contract.json','schema_contract.py')
    (tmp_path/'legacy-helper-proof.json').write_text(json.dumps(dict(shared_loaded=True,
        files={name:hashlib.sha256((legacy_home/'bin/lib'/name).read_bytes()).hexdigest() for name in files})))
    modes={'L':legacy,'F':root}; records={}; output_admits=[]; markers=FixtureMarkerStream();guard=threading.Lock();active=[None];block=[None]
    inner=[];output_chunks=[];proof_events=[];loop_lags=[];feed_events=[];proof_names={}
    output_chunk=contextvars.ContextVar('fixture_output_chunk',default=None)
    send_diagnostics=[]
    trace_context=contextvars.ContextVar('private_trace_sequence',default=None)
    trace_thread=threading.local();trace_pending=[None];trace_serial=[0];trace_dispatch=[False]
    setup_diagnostics=[]
    def setup_record(row):
        setup_diagnostics.append(row)
        (tmp_path/'pc-setup-diagnostic.json').write_text(json.dumps(setup_diagnostics,indent=2))
    def timed(stage, function):
        def call(*args,**kwargs):
            start=time.monotonic()
            try:return function(*args,**kwargs)
            finally:
                sequence=trace_context.get() or getattr(trace_thread,'sequence',None)
                with guard:inner.append(dict(stage=stage,sequence=sequence,begin=start,end=time.monotonic()))
        return call
    event=contextvars.ContextVar('fixture_event',default=None)
    original_attach=getattr(ob.SessionBridgeManager.attach,'benchmark_original',ob.SessionBridgeManager.attach)
    original_admit=getattr(control.admit_command,'benchmark_original',control.admit_command)
    resources=[]
    observer_proof=[];peer_labels={}
    def mark(ids, name, mode=None):
        now=time.monotonic()
        with guard:
            for item in ids:
                key=f'{mode}{item:03d}' if mode is not None else item
                if key in records and (mode is None or active[0]==mode):records[key][name]=now
    def ids_from(data):return [int(x) for x in re.findall(r'BENCH([0-9]{3})END',data)]
    def stream_ids(stream,data):
        return markers.take((stream,block[0]),data)
    def admitted(*args,**kwargs):
        current=event.get()
        if current is not None:mark([current],'admit_begin')
        try:return original_admit(*args,**kwargs)
        finally:
            if current is not None:mark([current],'admit_end')
    async def setup_mode(mode, target):
        manager=ob.SessionBridgeManager(target,history_dir=tmp_path/('latency-'+mode))
        app=ob.create_app(target);app.cleanup_ctx.clear();app[ob.BRIDGE_MANAGER_KEY]=manager
        runner=web.AppRunner(app,access_log=None);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        port=site._server.sockets[0].getsockname()[1]
        session=ClientSession();ws=await session.ws_connect(f'http://127.0.0.1:{port}/ws')
        await ws.send_json({'type':'attach','session':'Alpha' if mode=='F' else 'fixture'})
        while True:
            msg=await asyncio.wait_for(ws.receive_json(),20)
            if msg.get('type')=='error':raise AssertionError(msg)
            if msg.get('type')=='reset':break
        setup_record(dict(stage='reset',mode=mode,pane_count=len(msg['panes'])))
        states=list(manager.states.values())
        def observer_record(proof):
            observer_proof.append(proof)
            (tmp_path/'pc-observer-proof.json').write_text(json.dumps(observer_proof,indent=2))
        bridge=check_fixture_observers(mode,manager,pane,other,observer_record)
        actual_env=bridge.config.tmux_bin.env()
        locale_result=await asyncio.to_thread(subprocess.run,['locale','charmap'],env=actual_env,
            capture_output=True,text=True,timeout=5)
        setup_record(dict(stage='control_locale',mode=mode,lc_all=actual_env.get('LC_ALL'),
            lc_ctype=actual_env.get('LC_CTYPE'),charmap=locale_result.stdout.strip(),returncode=locale_result.returncode))
        assert actual_env.get('LC_ALL') is None and actual_env.get('LC_CTYPE')=='C.UTF-8'
        assert locale_result.returncode==0 and locale_result.stdout.strip().upper().replace('-','')=='UTF8'
        pane_id=next(row['paneId'] for row in msg['panes'] if row['paneId']==pane or row['paneId'].startswith('fresh-'))
        original_handle=manager.handle_message
        async def handle(peer, attached, payload):
            matches=ids_from(payload.get('data','')) if isinstance(payload.get('data'),str) else []
            token=event.set(f'{mode}{matches[0]:03d}' if len(matches)==1 else None)
            if matches:mark(matches,'ws_received',mode)
            try:return await original_handle(peer,attached,payload)
            finally:event.reset(token)
        manager.handle_message=handle
        original_write=bridge._write_master
        async def write(raw):
            key=event.get()
            if key is not None:mark([key],'pty_begin')
            try:return await original_write(raw)
            finally:
                if key is not None:mark([key],'pty_end')
        bridge._write_master=write
        original_record=bridge._record_and_broadcast
        def record(pane_id,data):
            keys=stream_ids(('echo',mode),data)
            if keys:
                assert pane_id==pane
                mark(keys,'echo',mode)
            return original_record(pane_id,data)
        bridge._record_and_broadcast=record
        for recorder in bridge._pane_recorders.values():
            original_feed=recorder.feed
            def feed(data,original=original_feed):
                started=time.monotonic()
                try:return original(data)
                finally:feed_events.append(dict(mode=mode,begin=started,end=time.monotonic()))
            monkeypatch.setattr(recorder,'feed',feed)
        original_send=bridge.send_json
        async def send(peer,payload,**kwargs):
            keys=stream_ids(('send',mode),payload.get('data','')) if payload.get('type')=='output' else []
            chunk=None;token=None
            if payload.get('type')=='output' and not payload.get('snapshot'):
                peer_label=peer_labels.setdefault(peer,f'{mode}.peer{len(peer_labels)}')
                chunk=dict(mode=mode,active_mode=active[0],measurement_block=block[0],peer=peer_label,sequence=len(output_chunks),
                    events=[f'{mode}{key:03d}' for key in keys if active[0]==mode and f'{mode}{key:03d}' in records],
                    send_begin=time.monotonic(),sent=False)
                output_chunks.append(chunk);token=output_chunk.set(chunk)
            try:
                result=await original_send(peer,payload,**kwargs)
                if chunk is not None:chunk['sent']=True
            except BaseException:
                if keys:send_diagnostics.append(dict(mode=mode,code='SEND_REFUSED'))
                raise
            finally:
                if chunk is not None:
                    chunk['send_end']=time.monotonic();output_chunk.reset(token)
            if keys:mark(keys,'ws_sent',mode)
            return result
        bridge.send_json=send
        if mode=='F':
            for index,proofs in enumerate(bridge._fresh_peer_proofs.values()):
                for proof,kind in zip(proofs,('input','output')):proof_names[proof]=f'F.peer{index}.{kind}'
            proof_names[bridge._fresh_recorder_proof]='F.recorder'
            target_pane=bridge.config.tmux_bin; original_target=target_pane.admit
            def target_admit(operation,**kwargs):
                started=time.monotonic()
                try:return original_target(operation,**kwargs)
                finally:
                    if operation=='capture':
                        with guard:output_admits.append((started,time.monotonic()))
            target_pane.admit=target_admit
        resources.append((runner,session,ws,manager))
        return ws,pane_id
    try:
        with monkeypatch.context() as scoped:
            original_lock=root.host_lock
            class ObservedLock:
                def __enter__(self):
                    started=time.monotonic();original_lock.acquire();acquired=time.monotonic()
                    with guard:
                        trace_serial[0]+=1;self.sequence=trace_serial[0]
                        trace_pending[0]=self.sequence
                        inner.append(dict(stage='host_lock_wait',sequence=self.sequence,begin=started,end=acquired))
                    trace_thread.sequence=self.sequence
                    return self
                def __exit__(self,*args):
                    with guard:trace_pending[0]=None
                    trace_thread.sequence=None;original_lock.release()
            scoped.setattr(root,'host_lock',ObservedLock())
            original_dispatch=resident._dispatch
            async def observed_dispatch(request):
                start=time.monotonic()
                with guard:
                    sequence=trace_pending[0] if not trace_dispatch[0] else None
                    trace_dispatch[0]=True
                token=trace_context.set(sequence)
                try:return await original_dispatch(request)
                finally:
                    trace_context.reset(token)
                    with guard:
                        inner.append(dict(stage='server_dispatch',sequence=sequence,begin=start,end=time.monotonic()))
                        trace_dispatch[0]=False
            scoped.setattr(resident,'_dispatch',observed_dispatch)
            scoped.setitem(root.host_api,'fresh_host_call',timed('ipc_call',root.host_api['fresh_host_call']))
            original_owner=resident.runtime.core.owner_transaction
            @asynccontextmanager
            async def observed_owner(*args,**kwargs):
                start=time.monotonic();sequence=trace_context.get()
                try:
                    async with original_owner(*args,**kwargs) as owner:yield owner
                finally:
                    with guard:inner.append(dict(stage='owner_transaction',sequence=sequence,begin=start,end=time.monotonic()))
            scoped.setattr(resident.runtime.core,'owner_transaction',observed_owner)
            original_command=control.TmuxControlBridge.send_command
            async def diagnostic_command(bridge,args,*rest,**kwargs):
                try:
                    result=await original_command(bridge,args,*rest,**kwargs)
                except BaseException:
                    if args and args[0]=='list-panes':
                        setup_record(dict(stage='list_panes',mode='F' if isinstance(bridge.config.tmux_bin,boundary.FreshPaneBoundary) else 'L',code='QUERY_EXCEPTION'))
                    raise
                if args and args[0]=='list-panes':
                    lines=result.lines if result is not None else []
                    setup_record(dict(stage='list_panes',mode='F' if isinstance(bridge.config.tmux_bin,boundary.FreshPaneBoundary) else 'L',
                        ok=result is not None and result.ok,line_count=len(lines),
                        tab_columns=[len(line.split('\t')) for line in lines],
                        parsed=[control.parse_pane_line(line) is not None for line in lines]))
                return result
            scoped.setattr(control.TmuxControlBridge,'send_command',diagnostic_command)
            from agentstack_mail import fresh_delivery
            original_helpers=fresh_delivery.helpers
            def observed_helpers(path):
                tmux_api,process_api,delivery_api=original_helpers(path)
                tmux_api=dict(tmux_api);process_api=dict(process_api)
                base=tmux_api['Transport']
                class ObservedTransport(base):
                    def command(self,*args,**kwargs):
                        call=super().command
                        return timed('capture' if args and args[0]=='capture-pane' else 'tmux_command',call)(*args,**kwargs)
                tmux_api['Transport']=ObservedTransport
                process_api['process_snapshot']=timed('os_snapshot',process_api['process_snapshot'])
                return tmux_api,process_api,delivery_api
            scoped.setattr(fresh_delivery,'helpers',observed_helpers)
            original_select=resident.targets.select
            async def observed_select(*args,**kwargs):
                start=time.monotonic()
                try:return await original_select(*args,**kwargs)
                finally:
                    with guard:inner.append(dict(stage='owner_select',sequence=trace_context.get(),begin=start,end=time.monotonic()))
            scoped.setattr(resident.targets,'select',observed_select)
            scoped.setattr(root,'call',timed('host_ipc',root.call))
            scoped.setattr(ob.SessionBridgeManager,'attach',original_attach)
            scoped.setattr(control,'admit_command',admitted)
            original_check=boundary.FreshEffectProof.check
            async def observed_check(proof):
                current=event.get() if proof.purpose=='input' else None
                chunk=output_chunk.get() if proof.purpose=='capture' else None
                if chunk is not None:
                    assert 'proof_begin' not in chunk,'duplicate peer proof for output chunk'
                    chunk['proof_begin']=time.monotonic()
                if current is not None:mark([current],'admit_begin')
                try:return await original_check(proof)
                finally:
                    if current is not None:mark([current],'admit_end')
                    if chunk is not None:chunk['proof_end']=time.monotonic()
            scoped.setattr(boundary.FreshEffectProof,'check',observed_check)
            original_refresh=boundary.FreshEffectProof._refresh
            async def observed_refresh(proof,generation):
                started=time.monotonic()
                try:return await original_refresh(proof,generation)
                finally:
                    failure=proof.failure
                    code=str(failure) if isinstance(failure,boundary.TargetRefused) else None
                    if code is not None and not re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}',code):code='REFRESH_REFUSED'
                    proof_events.append(dict(sink=proof_names.get(proof,'setup'),generation=generation,
                        begin=started,end=time.monotonic(),failed=proof.failed,closed=proof.closed,code=code))
            scoped.setattr(boundary.FreshEffectProof,'_refresh',observed_refresh)
            endpoints={mode:await setup_mode(mode,target) for mode,target in modes.items()}
            async def observe_loop():
                while True:
                    expected=time.monotonic()+.01
                    await asyncio.sleep(.01)
                    loop_lags.append(dict(mode=active[0],expected=expected,actual=time.monotonic()))
            monitor=asyncio.create_task(observe_loop())
            async def receive(mode,ws):
                async for frame in ws:
                    if frame.type!=WSMsgType.TEXT:continue
                    payload=json.loads(frame.data)
                    if payload.get('type')=='error':raise AssertionError(payload)
                    if payload.get('type')!='output' or payload.get('snapshot'):continue
                    if mode=='F':assert payload.get('paneId')==endpoints[mode][1], 'other pane output'
                    keys=stream_ids(('receive',mode),payload.get('data',''))
                    for item in keys:
                        key=f'{mode}{item:03d}'
                        if active[0]==mode and key in records:
                            if 'ws_echo' in records[key]:raise AssertionError('duplicate echo')
                            mark([item],'ws_echo',mode)
            tasks=[asyncio.create_task(receive(mode,ws)) for mode,(ws,_) in endpoints.items()]
            try:
                for index,(mode,(ws,pane_id)) in enumerate(endpoints.items()):
                    for warm in range(2):
                        await ws.send_json({'type':'input','paneId':pane_id,'data':f'BENCH{900+index*2+warm:03d}END\r'})
                        await asyncio.sleep(.1)
                await asyncio.sleep(.5)
                counters={'L':0,'F':0}
                for index,mode in enumerate(('L','F','F','L','F','L','L','F')):
                    block[0]=index
                    active[0]=mode
                    ws,pane_id=endpoints[mode]
                    block_keys=[]
                    for offset in range(25):
                        item=counters[mode];counters[mode]+=1;key=f'{mode}{item:03d}';block_keys.append(key)
                        records[key]=dict(mode=mode,ws_start=time.monotonic())
                        await ws.send_json({'type':'input','paneId':pane_id,'data':f'BENCH{item:03d}END\r'})
                        await asyncio.sleep(.1)
                    deadline=time.monotonic()+30
                    while any('ws_echo' not in records[key] for key in block_keys) and time.monotonic()<deadline:
                        await asyncio.sleep(.05)
                    assert all('ws_echo' in records[key] for key in block_keys)
                for task in tasks:
                    if task.done() and task.exception():raise task.exception()
                assert len(records)==200 and all('ws_echo' in row for row in records.values())
                for mode in modes:
                    actual=[key for key,row in sorted(records.items(),key=lambda item:item[1]['ws_echo']) if row['mode']==mode]
                    assert actual==sorted(actual)
                stages={'total':('ws_start','ws_echo'),'ws_receive':('ws_start','ws_received'),
                    'admission_wait':('ws_received','admit_begin'),'admission':('admit_begin','admit_end'),
                    'write_wait':('admit_end','pty_begin'),'pty_write':('pty_begin','pty_end'),
                    'pty_to_echo':('pty_end','echo'),'output_to_ws':('echo','ws_sent'),'ws_delivery':('ws_sent','ws_echo')}
                summary={}
                for mode in modes:
                    rows=[row for _,row in sorted(records.items()) if row['mode']==mode]
                    assert len(rows)==100
                    summary[mode]={}
                    for name,(start,end) in stages.items():
                        assert all(start in row and end in row for row in rows),'missing '+name+' timing'
                        values=sorted((row[end]-row[start])*1000 for row in rows)
                        summary[mode][name]=dict(median_ms=statistics.median(values),p95_ms=values[math.ceil(.95*len(values))-1])
                    if mode=='F':
                        durations=output_chunk_admission_durations([(key,row) for key,row in sorted(records.items()) if row['mode']==mode],output_chunks,mode)
                        summary[mode]['output_admission']=dict(samples=len(durations),median_ms=statistics.median(durations),p95_ms=durations[94])
                    else:
                        summary[mode]['output_admission']=dict(samples=0,median_ms=None,p95_ms=None,
                            note='legacy broadcast has no separate per-output proof check; output-to-WS is measured in both modes')
                payload=dict(records=records,summary=summary,output_admissions=output_admits,output_chunks=output_chunks,
                    same_fixture=True,ws_to_real_pty_echo=True,interval_seconds=.1,other_pane_input=False,
                    warmup_events_per_mode=2,
                    measurement_overhead='same chunk/send/feed timing and 10ms loop monitor in both modes; fresh-only proof/refresh wrappers follow actual fresh calls')
                (tmp_path/'pc-input-latency.json').write_text(json.dumps(payload,indent=2))
                assert 'BENCH' not in (await command('capture-pane','-p','-t',other)).stdout
                assert summary['F']['total']['median_ms']<=50 and summary['F']['total']['p95_ms']<=100
                assert summary['F']['total']['median_ms']-summary['L']['total']['median_ms']<=20
                assert summary['F']['total']['p95_ms']-summary['L']['total']['p95_ms']<=50
            finally:
                (tmp_path/'pc-input-latency-partial.json').write_text(json.dumps(dict(records=records,output_admissions=output_admits,output_chunks=output_chunks),indent=2))
                (tmp_path/'pc-output-stages.json').write_text(json.dumps(dict(chunks=output_chunks,refresh=proof_events,loop_lag=loop_lags,recorder_feed=feed_events,
                    limitations='Same monotonic clock; overlapping intervals are not additive or proof of causation. An event maps to the chunk completing its fixture marker, not a fabricated sum across chunks. No input content or credentials recorded.'),indent=2))
                (tmp_path/'pc-input-inner-stages.json').write_text(json.dumps(inner,indent=2))
                states=[dict(mode=mode,state='cancelled' if task.cancelled() else 'failed' if task.done() and task.exception() is not None else 'completed' if task.done() else 'running') for mode,task in zip(modes,tasks)]
                (tmp_path/'pc-send-diagnostic.json').write_text(json.dumps(dict(sends=send_diagnostics,receivers=states),indent=2))
                correlated=[];incomplete=0
                for seq in sorted({row['sequence'] for row in inner if row.get('sequence') is not None}):
                    events=[row for row in inner if row.get('sequence')==seq]
                    def one(stage):
                        found=[row for row in events if row['stage']==stage]
                        return found[0] if len(found)==1 else None
                    lock,ipc,dispatch=one('host_lock_wait'),one('ipc_call'),one('server_dispatch')
                    if not lock or not ipc or not dispatch or not (lock['end']<=ipc['begin']<=dispatch['begin']<=dispatch['end']<=ipc['end']):
                        incomplete+=1;continue
                    parts=[row for row in events if row['stage'] in {'owner_transaction','os_snapshot','capture'}]
                    parts.sort(key=lambda row:row['begin'])
                    if any(row['begin']<dispatch['begin'] or row['end']>dispatch['end'] for row in parts) or any(a['end']>b['begin'] for a,b in zip(parts,parts[1:])):
                        incomplete+=1;continue
                    totals={stage:sum(row['end']-row['begin'] for row in parts if row['stage']==stage) for stage in ('owner_transaction','os_snapshot','capture')}
                    correlated.append(dict(sequence=seq,lock_ms=1000*(lock['end']-lock['begin']),
                        ipc_other_ms=1000*((ipc['end']-ipc['begin'])-(dispatch['end']-dispatch['begin'])),
                        server_other_ms=1000*((dispatch['end']-dispatch['begin'])-sum(totals.values())),
                        **{key+'_ms':value*1000 for key,value in totals.items()}))
                (tmp_path/'pc-request-stages.json').write_text(json.dumps(dict(requests=correlated,incomplete=incomplete),indent=2))
                for task in tasks:task.cancel()
                await asyncio.gather(*tasks,return_exceptions=True)
                monitor.cancel();await asyncio.gather(monitor,return_exceptions=True)
    finally:
        for runner,session,ws,manager in reversed(resources):
            await ws.close();await manager.close();await session.close();await runner.cleanup()


@asynccontextmanager
async def private_targets(tmp_path,monkeypatch):
    async with helpers.live(tmp_path) as (runtime,people,alpha,_):
        beta=await FreshBoundClient.prepare(runtime.root/'config.json',people[1]['binding_path'],
            alpha.context['endpoint'],client_id=str(uuid4()))
        first=await helpers.setup(alpha,tmp_path,monkeypatch)
        second=await helpers.setup(beta,tmp_path,monkeypatch)
        row=dict(second[1],socket_path='/private/tmp/other-fixture-only.sock')
        helpers.replace(second[0]/'tmux.json',row)
        env=dict(os.environ,AGENTSTACK_RUNTIME_MODE='fresh',AGENTSTACK_HOME=str(T),AGENTSTACK_PYTHON=sys.executable,
            AGENTSTACK_FRESH_CLIENT_CONTEXT=str(alpha.path),ORRERY_FRESH_MAIL_INSTANCE_ID=runtime.config['instance_id'])
        for k in ('AGENTSTACK_CLIENT_CONFIG','AGENTSTACK_GLOBAL_SERVER_CONFIG'):env.pop(k,None)
        root=boundary.FreshTargetBoundary('/fixture/tmux',environ=env)
        resident=Host(Backend(alpha.path,T))
        await asyncio.to_thread(resident.start)
        synthetic_tmux=second[3]
        root.host_api['Transport']=lambda path,**kwargs:synthetic_tmux['Transport'](path)
        root.host_api['panes']=synthetic_tmux['panes']
        root.host_api['validate_socket']=lambda path:synthetic_tmux['Transport'](path).identity
        real_run=subprocess.run;window_rows=['%2\t@2','%9\t@9']
        def process(args,**kwargs):
            if args[0]=='/fixture/tmux':
                assert args[1]=='-S' and args[2] in {'/private/tmp/fixture-only.sock','/private/tmp/other-fixture-only.sock'}
                assert args[3:5]==['list-panes','-s']
                return subprocess.CompletedProcess(args,0,'\n'.join(window_rows)+'\n','')
            return real_run(args,**kwargs)
        monkeypatch.setattr(subprocess,'run',process)
        try:
            yield runtime,people,alpha,beta,root,first,second,window_rows
        finally:
            await asyncio.to_thread(resident.close)


def install_synthetic_control(monkeypatch,writes):
    async def start(self):
        await asyncio.to_thread(boundary.require_target,self.config.tmux_bin,'attach',session=self.config.session)
        self.master_fd=99;self._session_created=1
        async def writer(raw):
            args=shlex.split(raw.decode());writes.append((self.config.tmux_bin.key,args))
            lines=[]
            if args[0]=='list-panes':
                assert args[args.index('-t')+1]=='%2'
                lines=['%2\t@2\t$1\t0\t0\t80\t24\t0\town\tclaude\t0\t0\t0\t0',
                       '%9\t@9\t$1\t1\t0\t80\t24\t1\tother\tother\t0\t0\t0\t0']
            elif args[0]=='capture-pane':lines=['bounded own snapshot']
            elif args[0]=='display-message':
                lines=['$1\tmutable-name\t%2\t100' if args[-1]=='#{session_id}\t#{session_name}\t#{pane_id}\t#{pane_pid}' else '0\t0\t0\t0']
            pending=self._pending_blocks.popleft()
            self._bounded_blocks.pop(pending,None)
            if pending is not None:pending.set_result(control.CommandResult(True,lines))
        self._write_master=writer
        await self.refresh_panes(send_captures=False)
    async def stop(self):
        if self._fresh_recorder_proof is not None:self._fresh_recorder_proof.close()
        for proofs in self._fresh_peer_proofs.values():
            for proof in proofs:proof.close()
        self._closed=True;self.master_fd=None
        if self._fresh_output_task is not None:
            await self._fresh_output_task
        await self.flush_history()
    monkeypatch.setattr(ob.SessionTmuxBridge,'start',start)
    monkeypatch.setattr(ob.SessionTmuxBridge,'stop',stop)


def test_real_wrapper_catalog_current_bridges_wire_panes_history_and_input_do_not_mix(tmp_path,monkeypatch):
    async def run():
        async with private_targets(tmp_path,monkeypatch) as (runtime,people,alpha,beta,root,first,second,_):
            writes=[];install_synthetic_control(monkeypatch,writes)
            # Real wrapper + private DB for catalog, no OS helper needed here.
            rows=await asyncio.to_thread(root.catalog)
            assert [r['session'] for r in rows]==['Alpha','Beta','Gamma']
            manager=ob.SessionBridgeManager(root,history_dir=tmp_path/'history')
            peer=Peer();attached=set()
            try:
                selected=await asyncio.to_thread(root.resolve,'Alpha')
                await manager._ensure_fresh_bridge(selected)
                await manager._reconcile_sessions()
                assert len(manager.states)==2
                await manager.handle_message(peer,attached,dict(type='attach',session='Alpha'))
                await manager.handle_message(peer,attached,dict(type='attach',session='Beta',
                    mail_instance_id=root.instance,mail_agent_id=people[1]['agent_id']))
                a=next(s.bridge for s in manager.states.values() if s.bridge.config.session=='Alpha')
                b=next(s.bridge for s in manager.states.values() if s.bridge.config.session=='Beta')
                assert a.config.tmux_bin.prefix!=b.config.tmux_bin.prefix
                assert a.config.tmux_bin.wire_pane!=b.config.tmux_bin.wire_pane
                assert a._history_dir!=b._history_dir and set(a.panes)==set(b.panes)=={'%2'}
                resets=[m for m in peer.messages if m['type']=='reset']
                assert len(resets)==2 and all(len(m['panes'])==1 and m['panes'][0]['paneId'].startswith('fresh-') for m in resets)
                a._handle_output(b'%output %9 OTHER-OWNER')
                a._handle_extended_output(b'%extended-output %9 1 : OTHER-OWNER')
                a._handle_output(b'%output %2 '+b'ALPHA-ONLY\\015\\012'*30)
                await a._fresh_output_task
                await a.flush_history()
                assert b._read_restored_history('%2')==[]
                assert any('ALPHA-ONLY' in p.read_text() for p in a._history_dir.glob('*.json'))
                before=len([w for w in writes if w[1][0]=='send-keys'])
                await manager.handle_message(peer,attached,dict(type='input',paneId=b.config.tmux_bin.wire_pane,data='literal'))
                sent=[w for w in writes if w[1][0]=='send-keys']
                assert len(sent)==before+1 and sent[-1][0]==b.config.tmux_bin.key and sent[-1][1][2]=='%2'
                await manager.handle_message(peer,attached,dict(type='input',paneId='%2',data='raw rejected'))
                assert len([w for w in writes if w[1][0]=='send-keys'])==len(sent)
                with pytest.raises(boundary.TargetRefused):
                    await manager.handle_message(peer,attached,dict(type='input',paneId=b.config.tmux_bin.wire_pane,
                        mail_agent_id=people[0]['agent_id'],data='wrong owner'))
                wire=json.dumps(peer.messages)
                assert 'OTHER-OWNER' not in wire and 'ALPHA-ONLY' in wire
                assert not any(v in wire for v in ('registration_token','binding_path','context_digest','socket_path',str(alpha.path)))
                # A different current gets a different bridge/history; no state
                # object or private recorder is reassigned to it.
                old=first[0];launch_id=str(uuid4());new=old.parent/launch_id;new.mkdir(mode=0o700)
                for name in ('intent.json','session.json','tmux.json'):
                    _write_private(new/name,dict(_read_private(old/name),launch_id=launch_id))
                helpers.replace(old.parent.parent/'current.json',dict(launch_id=launch_id))
                await manager._reconcile_sessions()
                fresh=next(s.bridge for s in manager.states.values() if s.bridge.config.session=='Alpha')
                assert fresh is not a and a._closed and fresh._history_dir!=a._history_dir
                assert fresh._read_restored_history('%2')==[]
            finally:await manager.close()
    asyncio.run(run())


def ended_husk_driver(entry, cwd, outcome):
    """A launcher child exits before the pane's original PID execs a bare shell."""
    return ('import json,os,pathlib,subprocess\n'
            'rc=subprocess.call('+repr(['/bin/bash',str(entry),str(cwd)])+')\n'
            'pathlib.Path('+repr(str(outcome))+').write_text(json.dumps(dict(launcher_rc=rc,pid=os.getpid())))\n'
            'if rc:raise SystemExit(rc)\n'
            "os.execv('/bin/sh',['sh','-i'])\n")


class EndedHuskClient:
    """Only our guard owns the normal client's lifetime; never detach others."""
    def __init__(self, tmux, socket, session, env):
        self.process=None;self.writer=None
        readfd,writefd=os.pipe()
        try:
            command=[sys.executable,str(BRIDGE/'control_client_guard.py'),str(readfd),
                '/usr/bin/script','-q','/dev/null',tmux,'-u','-S',str(socket),
                'attach-session','-t',session]
            self.process=subprocess.Popen(command,env=env,pass_fds=(readfd,),
                stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                start_new_session=True)
            self.writer=writefd
        except BaseException:
            os.close(writefd);raise
        finally:os.close(readfd)

    def close(self):
        if self.writer is not None:os.close(self.writer);self.writer=None
        if self.process is not None:
            process=self.process
            if process.stdin is not None:process.stdin.close()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Signal only this owned guard, which reaps its own child.
                process.terminate();process.wait(timeout=5)
                raise AssertionError('owned normal client exceeded lifetime deadline')
            self.process=None


@asynccontextmanager
async def ended_husk_private_panes(command, driver, private, control_file, cleanup_file):
    """Share partial-start/finally cleanup with the pre-freeze synthetic setup."""
    state=SimpleNamespace(created=False,guard=None)
    try:
        state.pane=(await command('new-session','-d','-s','fixture','-P','-F','#{pane_id}',
            'exec '+shlex.join([sys.executable,str(driver)]))).stdout.strip()
        state.created=True
        state.other=(await command('new-window','-d','-t','fixture','-P','-F','#{pane_id}',
            'exec /bin/cat')).stdout.strip()
        yield state
    finally:
        control_file.write_text('stop')
        try:
            if state.guard is not None:await asyncio.to_thread(state.guard.close)
        finally:
            if state.created:
                stopped=await command('kill-server',check=False)
                cleanup_file.write_text(json.dumps(dict(stopped=stopped.returncode==0)))
                assert stopped.returncode==0,'private server cleanup failed'
            shutil.rmtree(private)


@pytest.mark.parametrize('fault',['none','new-session','new-window','guard','kill-server'])
def test_ended_husk_private_setup_and_finally_cleanup(tmp_path,fault):
    async def scenario():
        private=tmp_path/'private';private.mkdir();control_file=tmp_path/'control'
        cleanup_file=tmp_path/'cleanup.json';driver=tmp_path/'driver.py';calls=[]
        async def command(*args,check=True):
            calls.append((args,check))
            if fault==args[0] and check:raise AssertionError('synthetic start failure')
            return subprocess.CompletedProcess(args,1 if fault==args[0] else 0,
                '%1\n' if args[0]=='new-session' else '%2\n','')
        def close():
            calls.append(('guard-close',True))
            if fault=='guard':raise AssertionError('synthetic guard failure')
        async def run():
            async with ended_husk_private_panes(command,driver,private,control_file,cleanup_file) as state:
                assert state.pane=='%1' and state.other=='%2'
                state.guard=SimpleNamespace(close=close)
        if fault=='none':await run()
        else:
            with pytest.raises(AssertionError):await run()
        assert control_file.read_text()=='stop'
        assert calls[0]==(('new-session','-d','-s','fixture','-P','-F','#{pane_id}',
            'exec '+shlex.join([sys.executable,str(driver)])),True)
        assert sum(args==('kill-server',) for args,check in calls)==(fault!='new-session')
        if fault!='new-session':assert json.loads(cleanup_file.read_text())==dict(stopped=fault!='kill-server')
        if fault=='kill-server':assert private.exists()  # Preserve failed-cleanup evidence.
        else:assert not private.exists()
    asyncio.run(scenario())


async def ended_husk_cleanup_roundtrip(targets, query, close_client, assert_clients_zero,
                                     observe_other, database_snapshot):
    """The exact new external assertions, also exercised over real private ORM."""
    selected=await targets.select_managed(query)
    _,view=await asyncio.to_thread(targets.cleanup_status,selected)
    assert view==dict(category='finished',running=False,attached=True)
    marker=selected.run/'pc-cleanup-both.json'
    assert not marker.exists()
    other_before=await observe_other();before=await database_snapshot()
    with pytest.raises(B1Error,match='FRESH_CLEANUP_ATTACHED'):
        await targets.cleanup(query)
    assert await database_snapshot()==before
    assert not marker.exists()
    await targets.select(query)  # Refusal must not retire the original identity.
    await close_client()
    await assert_clients_zero()
    selected=await targets.select_managed(query)
    _,view=await asyncio.to_thread(targets.cleanup_status,selected)
    assert view==dict(category='finished',running=False,attached=False)
    result=await targets.cleanup(query)  # One admitted attempt; unknown never resent.
    assert result['ok'] and result['execution']=='completed'
    assert all(result[key]==value for key,value in query.items())
    assert result['effects']==dict(retire='retired',tmux='pane_removed')
    _,after=await asyncio.to_thread(targets.cleanup_status,await targets.select_managed(query))
    assert after['category']=='gone' and not after['attached']
    assert await observe_other()==other_before
    with pytest.raises(B1Error,match='TARGET_RETIRED'):await targets.select(query)
    return dict(same_identity=True,normal_client_refused=True,refusal_no_retire_or_marker=True,
        all_clients_zero_before_effect=True,retired=True,tmux='pane_removed',target_gone=True,
        other_pane_unchanged=True,ordinary_retired_refused=True)


@pytest.mark.parametrize('fault',['none','remaining-client','other-pane','unknown-ack','already-absent'])
def test_ended_husk_assertions_real_targets_with_synthetic_os(tmp_path,monkeypatch,fault):
    async def scenario():
        from agentstack_mail.fresh_targets import Targets
        async with helpers.cleanup_fixture(tmp_path,monkeypatch) as (runtime,people,client,operator,run,row,calls,tmux,processes,state):
            state['attached']=True
            async def close():
                state['attached']=fault=='remaining-client'
                state['failure']=fault=='unknown-ack'
                if fault=='already-absent':state['present']=False
            async def zero():assert not state['attached'],'normal client remains'
            async def other():
                return dict(pane='%9',pid=999,output='changed' if fault=='other-pane' and not state['present'] else 'unchanged')
            async def snapshot():return await helpers.snapshot(runtime)
            query=dict(mail_instance_id=runtime.config['instance_id'],mail_agent_id=people[0]['agent_id'])
            async def run():return await ended_husk_cleanup_roundtrip(Targets(operator,T),query,close,zero,other,snapshot)
            if fault=='none':
                proof=await run();assert proof['tmux']=='pane_removed' and proof['same_identity']
            else:
                with pytest.raises(AssertionError):await run()
            assert sum(a[0]=='kill-pane' for a,k in calls)==(fault in {'none','other-pane','unknown-ack'})
            assert not any(a[0]=='kill-session' for a,k in calls)
    asyncio.run(scenario())


@pytest.mark.parametrize('rc',[0,17])
def test_ended_husk_driver_uses_one_launcher_then_same_pid_exec(tmp_path,monkeypatch,rc):
    calls=[];outcome=tmp_path/'driver-result.json'
    def launch(argv):calls.append(('launch',argv));return rc
    def execute(path,args):calls.append(('exec',path,args,os.getpid()))
    monkeypatch.setattr(subprocess,'call',launch);monkeypatch.setattr(os,'execv',execute)
    code=ended_husk_driver(T/'bin/agent-start',tmp_path,outcome)
    if rc:
        with pytest.raises(SystemExit) as stopped:exec(compile(code,'<husk-driver>','exec'),{})
        assert stopped.value.code==rc
    else:exec(compile(code,'<husk-driver>','exec'),{})
    assert json.loads(outcome.read_text())==dict(launcher_rc=rc,pid=os.getpid())
    assert calls==[('launch',['/bin/bash',str(T/'bin/agent-start'),str(tmp_path)])]+(
        [('exec','/bin/sh',['sh','-i'],os.getpid())] if rc==0 else [])


@pytest.mark.parametrize('fault',['none','popen','wait'])
def test_ended_husk_normal_client_argv_and_owned_lifetime(tmp_path,monkeypatch,fault):
    calls=[];fds=[]
    class Child:
        stdin=SimpleNamespace(close=lambda:calls.append('stdin-close'))
        def wait(self,timeout):
            calls.append(('wait',timeout))
            if fault=='wait' and calls.count(('wait',timeout))==1:
                raise subprocess.TimeoutExpired('owned-guard',timeout)
            assert os.read(fds[0],1)==b''
            return 0
        def terminate(self):calls.append('terminate')
    # Keep a duplicate of the child's read end to observe actual pipe EOF.
    def spawn(argv,**kwargs):
        fds.extend([os.dup(kwargs['pass_fds'][0]),kwargs['pass_fds'][0]])
        calls.append((argv,kwargs))
        if fault=='popen':raise OSError('synthetic spawn failure')
        return Child()
    monkeypatch.setattr(subprocess,'Popen',spawn)
    try:
        if fault=='popen':
            with pytest.raises(OSError):EndedHuskClient('/fixture/tmux',tmp_path/'s.sock','$7',{})
            assert os.read(fds[0],1)==b''
        else:
            guard=EndedHuskClient('/fixture/tmux',tmp_path/'s.sock','$7',{})
            if fault=='wait':
                with pytest.raises(AssertionError,match='lifetime deadline'):guard.close()
                guard.close()
            else:guard.close();guard.close()
        argv,kw=calls[0]
        assert argv==[sys.executable,str(BRIDGE/'control_client_guard.py'),str(fds[1]),
            '/usr/bin/script','-q','/dev/null','/fixture/tmux','-u','-S',str(tmp_path/'s.sock'),
            'attach-session','-t','$7']
        assert kw['pass_fds']==(fds[1],) and kw['start_new_session'] and kw['env']=={}
        assert '-C' not in argv and '-CC' not in argv
        with pytest.raises(OSError):os.fstat(fds[1])
        if fault=='wait':assert 'terminate' in calls
    finally:
        for fd in fds[:1]:os.close(fd)


@pytest.mark.skipif(os.environ.get('ORRERY_EXTERNAL_FRESH_HUSK')!='1',reason='designated external private tmux acceptance only')
def test_external_ended_husk_kill_private(tmp_path):
    """Real PTY/PID/birth first accepted here by the designated outer runner."""
    from agentstack_mail.fresh_targets import Targets
    from test_fresh_delivery import NATIVE
    from test_fresh_proxy import environment
    async def scenario():
        async with helpers.live(tmp_path) as (runtime,people,client,_):
            _,binary=helpers.prepare_provider(client,'claude',tmp_path)
            binary.write_text('#!'+sys.executable+'\n'+NATIVE)
            private=Path(tempfile.mkdtemp(prefix='o213-husk-',dir='/private/tmp'));private.chmod(0o700)
            socket=private/'tmux.sock';tmux=shutil.which('tmux')
            assert tmux and os.access('/usr/bin/script',os.X_OK)
            assert (BRIDGE/'control_client_guard.py').is_file()
            ready=tmp_path/'native.ready';outcome=tmp_path/'driver-result.json';driver=tmp_path/'driver.py'
            control_file=tmp_path/'control';control_file.write_text('idle')
            driver.write_text(ended_husk_driver(T/'bin/agent-start',tmp_path,outcome))
            env=environment(client,AGENTSTACK_RUNTIME_MODE='fresh',AGENTSTACK_HOME=str(T),
                AGENTSTACK_PYTHON=sys.executable,ORRERY_FRESH_MAIL_INSTANCE_ID=runtime.config['instance_id'],
                TEST_PROVIDER='claude',TEST_TRACE=str(tmp_path/'native-trace.json'),TEST_CONTROL=str(control_file),
                TEST_RECEIVED=str(tmp_path/'native-received.jsonl'),TEST_READY=str(ready),
                AGENTSTACK_CLAUDE_BIN=str(binary))
            for key in ('TMUX','TMUX_PANE','AGENTSTACK_CLIENT_CONFIG','AGENTSTACK_GLOBAL_SERVER_CONFIG',
                        'ENV','BASH_ENV','ZDOTDIR'):env.pop(key,None)
            async def command(*args,check=True):
                result=await asyncio.to_thread(subprocess.run,[tmux,'-u','-S',str(socket),*args],
                    env=env,capture_output=True,text=True,timeout=15)
                if check:assert result.returncode==0,'private tmux command failed'
                return result
            async def wait_for(check,label):
                deadline=time.monotonic()+45
                while not await check():
                    assert time.monotonic()<deadline,label;await asyncio.sleep(.05)
            async with ended_husk_private_panes(command,driver,private,control_file,
                    tmp_path/'private-tmux-cleanup.json') as state:
                pane,other=state.pane,state.other
                base=client.path.parent/'launch'
                async def native_ready():return ready.exists() and (base/'current.json').exists()
                await wait_for(native_ready,'fake native did not become ready')
                run=base/'runs'/_read_private(base/'current.json')['launch_id']
                async def route_ready():return (run/'tmux.json').exists() and (run/'session.json').exists()
                await wait_for(route_ready,'normal launcher did not publish native route')
                route_bytes=(run/'tmux.json').read_bytes();route=_read_private(run/'tmux.json')
                assert route['pane']['pane_id']==pane
                control_file.write_text('stop')
                async def ended():return outcome.exists() and (run/'ended.json').exists()
                await wait_for(ended,'normal launcher did not end')
                assert json.loads(outcome.read_text())==dict(launcher_rc=0,pid=route['pane']['pid'])
                operator=await FreshBoundClient.prepare(runtime.root/'config.json',people[1]['binding_path'],
                    client.context['endpoint'],client_id=str(uuid4()))
                targets=Targets(operator,T)
                query=dict(mail_instance_id=runtime.config['instance_id'],mail_agent_id=people[0]['agent_id'])
                async def bare_shell():
                    selected=await targets.select_managed(query)
                    try:_,view=await asyncio.to_thread(targets.cleanup_status,selected)
                    except B1Error as exc:
                        if exc.code not in {'FRESH_CLEANUP_PROCESS_PRESENT','FRESH_CLEANUP_TARGET_CHANGED'}:raise
                        return False
                    return view==dict(category='finished',running=False,attached=False)
                await wait_for(bare_shell,'saved pane did not become the same-birth bare shell')
                assert (run/'tmux.json').read_bytes()==route_bytes
                state.guard=guard=await asyncio.to_thread(EndedHuskClient,tmux,socket,route['pane']['session_id'],env)
                async def attached():
                    assert guard.process.poll() is None,'owned normal client exited before attachment'
                    result=await command('list-clients','-F','#{session_id}')
                    return result.stdout.splitlines()==[route['pane']['session_id']]
                await wait_for(attached,'normal client did not attach')
                async def close_client():await asyncio.to_thread(guard.close)
                async def clients_zero():
                    async def zero():return not (await command('list-clients','-F','#{session_id}')).stdout.strip()
                    await wait_for(zero,'normal client remains after owned guard shutdown')
                async def other_observation():
                    pid=(await command('display-message','-p','-t',other,'#{pane_id}|#{pane_pid}')).stdout.strip()
                    return dict(identity=pid,output=(await command('capture-pane','-p','-J','-t',other)).stdout)
                async def snapshot():return await helpers.snapshot(runtime)
                proof=await ended_husk_cleanup_roundtrip(targets,query,close_client,clients_zero,other_observation,snapshot)
                assert (run/'tmux.json').read_bytes()==route_bytes
                proof.update(regular_launcher=True,same_pid_shell=True,saved_birth_unmodified=True,normal_client_guard_reaped=True)
                (tmp_path/'ended-husk-cleanup-proof.json').write_text(json.dumps(proof))
    asyncio.run(scenario())


def test_resident_ipc_inspect_pins_revision_and_refuses_context_change(tmp_path,monkeypatch):
    async def run():
        async with private_targets(tmp_path,monkeypatch) as (_,people,alpha,_,root,_,_,_):
            call=lambda payload:boundary.FreshTargetBoundary.call(root,payload)
            first=await asyncio.to_thread(call,dict(operation='inspect',session='Alpha'))
            assert first['mail_agent_id']==people[0]['agent_id']
            again=await asyncio.to_thread(call,dict(operation='inspect',session='Alpha',expected=first['revision']))
            assert again==first
            saved=_read_private(alpha.path)
            helpers.replace(alpha.path,dict(saved,credential_generation=saved['credential_generation']+1))
            try:
                with pytest.raises(boundary.TargetRefused,match='FRESH_CLIENT_CONTEXT_CHANGED'):
                    await asyncio.to_thread(call,dict(operation='inspect',session='Alpha'))
            finally:helpers.replace(alpha.path,saved)
    asyncio.run(run())


@pytest.mark.parametrize('damage',['current','native','socket','birth','revoked'])
def test_changed_fresh_target_blocks_input_and_stream_recording(tmp_path,monkeypatch,damage):
    async def run():
        async with private_targets(tmp_path,monkeypatch) as (runtime,people,alpha,_,root,first,second,_):
            target=await asyncio.to_thread(root.resolve,'Alpha')
            writes=[];install_synthetic_control(monkeypatch,writes)
            bridge=ob.SessionTmuxBridge(control.ControlConfig('127.0.0.1',0,'Alpha',target,history_dir=tmp_path/'history'))
            peer=Peer();bridge.clients.add(peer)
            try:
                await bridge.start();before=len(writes);path=first[0]
                if damage=='current':helpers.replace(path.parent.parent/'current.json',dict(launch_id=str(uuid4())))
                elif damage=='native':helpers.replace(path/'session.json',dict(_read_private(path/'session.json'),native_session_id=str(uuid4())))
                elif damage=='socket':helpers.replace(path/'tmux.json',dict(_read_private(path/'tmux.json'),socket_identity=[999,999]))
                elif damage=='birth':second[4]['process_snapshot']=lambda **kw:{100:(1,os.getuid(),'reused')}
                else:await runtime.core.recover(people[0]['agent_id'],expected_generation=people[0]['credential_generation'],new_token='private-cockpit-recovery')
                with pytest.raises(boundary.TargetRefused):await bridge.send_input('%2','must not write')
                assert len(writes)==before
                bridge._handle_output(b'%output %2 CHANGED-RUN-OUTPUT')
                await bridge._fresh_output_task
                await asyncio.gather(*list(bridge._fresh_sink_tasks))
                assert bridge._fresh_recorder_proof.closed and 'CHANGED-RUN-OUTPUT' not in json.dumps(peer.messages)
                assert not any('CHANGED-RUN-OUTPUT' in p.read_text() for p in (tmp_path/'history').rglob('*.json'))
            finally:await bridge.stop()
    asyncio.run(run())


def test_fresh_name_ambiguity_window_membership_and_explicit_ref_keep_legacy_separate(tmp_path,monkeypatch):
    async def run():
        async with private_targets(tmp_path,monkeypatch) as (runtime,people,_,_,root,_,_,window_rows):
            target=await asyncio.to_thread(root.resolve,'Alpha')
            await asyncio.to_thread(target.admit,'window',window='@2')
            window_rows.append('%8\t@2')
            with pytest.raises(boundary.TargetRefused,match='FRESH_WINDOW_TARGET_UNAVAILABLE'):
                await asyncio.to_thread(target.admit,'window',window='@2')
            with pytest.raises(boundary.TargetRefused):await asyncio.to_thread(target.admit,'input',pane='%9')
            alias=await runtime.register_local(request_id=str(uuid4()),name='ALPHA',program='fixture',model='fixture')
            await runtime.core.retire(alias['agent_id'])
            with pytest.raises(boundary.TargetRefused,match='TARGET_NAME_AMBIGUOUS'):await asyncio.to_thread(root.resolve,'Alpha')
            explicit=await asyncio.to_thread(root.resolve,'Alpha',dict(mail_instance_id=root.instance,mail_agent_id=people[0]['agent_id']))
            assert explicit.key==target.key
            with pytest.raises(boundary.TargetRefused):await asyncio.to_thread(root.resolve,'Alpha',dict(mail_instance_id='0'*32,mail_agent_id=people[0]['agent_id']))
            malformed=dict(root.environment);malformed.pop('AGENTSTACK_FRESH_CLIENT_CONTEXT')
            with pytest.raises(boundary.TargetRefused,match='FRESH_CONTEXT_REQUIRED'):boundary.FreshTargetBoundary('tmux',environ=malformed)
            legacy=boundary.LegacyTargetBoundary('tmux',home=tmp_path/'legacy-absent',environ={})
            assert boundary.tmux_argv(legacy,'capture-pane')==['tmux','capture-pane']
            assert boundary.require_target(legacy,'capture',pane='%2') is None
    asyncio.run(run())


@pytest.mark.parametrize('case',['own','other-window','shared-window','changed-current'])
def test_window_claim_rechecks_selected_sole_pane_for_size_query_and_resize(tmp_path,monkeypatch,case):
    async def run():
        async with private_targets(tmp_path,monkeypatch) as (_,_,_,_,root,first,_,window_rows):
            writes=[];install_synthetic_control(monkeypatch,writes)
            manager=ob.SessionBridgeManager(root,history_dir=tmp_path/'history')
            try:
                state=await manager._ensure_bridge('Alpha');bridge=state.bridge
                writes.clear()
                # PTY replies are synthetic; claim/query/command admission are real.
                async def writer(raw):
                    args=shlex.split(raw.decode());writes.append(args)
                    lines=[]
                    if args[0]=='show-window-options':
                        lines=['latest']
                        if case=='changed-current':
                            helpers.replace(first[0].parent.parent/'current.json',dict(launch_id=str(uuid4())))
                    elif args[0]=='display-message':lines=['80\t24']
                    pending=bridge._pending_blocks.popleft()
                    if pending is not None:pending.set_result(control.CommandResult(True,lines))
                bridge._write_master=writer
                bridge._schedule_pane_resync=lambda pane:None
                if case=='shared-window':window_rows.append('%8\t@2')
                window='@9' if case=='other-window' else '@2'
                payload=dict(type='resize',paneId='%2',cols=100,rows=30)
                if case=='own':
                    assert await manager._claim_window(state,payload,window,100,30)
                    assert writes==[
                        ['show-window-options','-v','-t','@2','window-size'],
                        ['display-message','-p','-t','@2','#{window_width}\t#{window_height}'],
                        ['resize-window','-t','@2','-x','100','-y','30'],
                        ['refresh-client','-C','@2:100x30']]
                    assert state.claimed_windows=={'@2':ob.WindowSizeSnapshot('latest',80,24)}
                    # This admission is for the existing exact size query only.
                    with pytest.raises(boundary.TargetRefused):
                        await bridge.send_command(['display-message','-p','-t','@2','#{session_name}'])
                    assert len(writes)==4
                else:
                    with pytest.raises(boundary.TargetRefused):
                        await manager._claim_window(state,payload,window,100,30)
                    assert not any(args[0] in {'display-message','resize-window','refresh-client'} for args in writes)
                    assert state.claimed_windows=={}
            finally:await manager.close()
    asyncio.run(run())


def test_open_terminal_uses_fixed_dashboard_and_selected_reference_only(tmp_path,monkeypatch):
    async def run():
        async with private_targets(tmp_path,monkeypatch) as (_,people,_,_,root,_,_,_):
            calls=[]
            class Response:
                content_type='application/json'
                async def __aenter__(self):return self
                async def __aexit__(self,*args):pass
                @property
                def content(self):return self
                async def read(self,maximum):
                    return json.dumps(dict(ok=True,**calls[-1][1]['json'])).encode()
            class HTTP:
                def post(self,url,**kwargs):calls.append((url,kwargs));return Response()
            async def request(payload):
                async def body():return payload
                return await ob.open_ghostty(SimpleNamespace(json=body,app={ob.TMUX_BIN_KEY:root,ob.HTTP_SESSION_KEY:HTTP()}))
            monkeypatch.setenv('ORRERY_DASHBOARD_URL','http://127.0.0.1:1')
            response=await request(dict(session='Alpha'))
            assert response.status==200 and json.loads(response.text)==dict(ok=True,already=False,
                mail_instance_id=root.instance,mail_agent_id=people[0]['agent_id'])
            assert calls==[('http://127.0.0.1:1/api/jump',dict(json=dict(session='Alpha',open=True,
                mail_instance_id=root.instance,mail_agent_id=people[0]['agent_id']),allow_redirects=False))]
            response=await request(dict(session='Alpha',socket_path='/other'))
            assert response.status==400 and len(calls)==1
            response=await request(dict(session='Alpha',mail_instance_id='0'*32,mail_agent_id=people[0]['agent_id']))
            assert response.status==409 and len(calls)==1
            # No socket opens here; HTTP and terminal provider are synthetic.
    asyncio.run(run())


@pytest.mark.skipif(os.environ.get('ORRERY_EXTERNAL_FRESH_BRIDGE')!='1',reason='Parent-only private ps/tmux acceptance')
@pytest.mark.parametrize('provider',['claude','codex'])
def test_external_control_bridge_and_same_native_resume_gate(tmp_path,monkeypatch,provider):
    """Parent selects this explicitly; author never runs known-denied OS work."""
    from agentstack_mail.fresh_targets import Targets
    from test_fresh_delivery import NATIVE
    from test_fresh_proxy import environment
    async def run():
        async with helpers.live(tmp_path) as (runtime,people,client,_):
            _,binary=helpers.prepare_provider(client,provider,tmp_path)
            native=NATIVE.replace('session=str(uuid.uuid4());transcript=',
                "session=(args[args.index('--resume')+1] if '--resume' in args else args[args.index('resume')+1] if 'resume' in args else str(uuid.uuid4()));transcript=")
            assert native!=NATIVE
            if os.environ.get('ORRERY_EXTERNAL_FRESH_R4')=='1':
                old="   raw=b''"
                replacement="   if raw.startswith(b'BENCH'):sys.stdout.write('\\r\\n'+raw.decode('ascii')+'\\r\\n'+glyph+' ');sys.stdout.flush()\n   raw=b''"
                assert native.count(old)==1
                native=native.replace(old,replacement)
            binary.write_text('#!'+sys.executable+'\n'+native)
            monkeypatch.setenv('AGENTSTACK_'+provider.upper()+'_BIN',str(binary))
            private=Path(tempfile.mkdtemp(prefix='o213-cockpit-target-',dir='/private/tmp'));private.chmod(0o700)
            socket=private/'tmux.sock';tmux=shutil.which('tmux');assert tmux
            control_file=tmp_path/'control';control_file.write_text('idle')
            ready=tmp_path/'native.ready';received=tmp_path/'received.jsonl';ended=tmp_path/'first-ended'
            release=tmp_path/'parent-release';entry=T/('bin/agent-start-codex' if provider=='codex' else 'bin/agent-start')
            driver=tmp_path/'parent.py'
            driver.write_text('import os,pathlib,subprocess,time\n'+
                'rc=subprocess.call('+repr(['/bin/bash',str(entry),str(tmp_path)])+')\n'+
                'pathlib.Path('+repr(str(ended))+').write_text(str(rc))\n'+
                'deadline=time.monotonic()+120\n'+
                'while not pathlib.Path('+repr(str(release))+').exists() and time.monotonic()<deadline: time.sleep(.1)\n')
            env=environment(client,AGENTSTACK_RUNTIME_MODE='fresh',AGENTSTACK_HOME=str(T),AGENTSTACK_PYTHON=sys.executable,
                ORRERY_FRESH_MAIL_INSTANCE_ID=runtime.config['instance_id'],TEST_PROVIDER=provider,
                TEST_TRACE=str(tmp_path/'native-trace.json'),TEST_CONTROL=str(control_file),TEST_RECEIVED=str(received),TEST_READY=str(ready),
                **{'AGENTSTACK_'+provider.upper()+'_BIN':str(binary)})
            for key in ('TMUX','TMUX_PANE','AGENTSTACK_CLIENT_CONFIG','AGENTSTACK_GLOBAL_SERVER_CONFIG'):env.pop(key,None)
            commands=[];manager=None;created=False;resident=None
            async def command(*args,check=True):
                result=await asyncio.to_thread(subprocess.run,[tmux,'-u','-S',str(socket),*args],
                    env=env,capture_output=True,text=True,timeout=15)
                commands.append(dict(args=list(args),returncode=result.returncode,stdout=result.stdout[-16384:],stderr=result.stderr[-2048:]))
                (tmp_path/'private-tmux-commands.json').write_text(json.dumps(commands))
                if check:assert result.returncode==0,result.stderr
                return result
            try:
                result=await command('new-session','-d','-s','fixture','-P','-F','#{pane_id}',
                    shlex.join([sys.executable,str(driver)]));created=True;pane=result.stdout.strip()
                other=(await command('new-window','-d','-t','fixture','-P','-F','#{pane_id}','exec /bin/cat')).stdout.strip()
                await command('select-pane','-t',other)
                await command('select-window','-t',other)
                deadline=time.monotonic()+45;base=client.path.parent/'launch'
                while not ready.exists() or not (base/'current.json').exists():
                    assert time.monotonic()<deadline,'fake native did not become ready';await asyncio.sleep(.1)
                old=_read_private(base/'current.json')['launch_id'];run_path=base/'runs'/old
                while not (run_path/'tmux.json').exists():
                    assert time.monotonic()<deadline;await asyncio.sleep(.1)
                native_id=ready.read_text()
                if os.environ.get('ORRERY_EXTERNAL_FRESH_R4')=='1':
                    await external_dashboard_restart(client,env,tmp_path)
                resident=Host(Backend(client.path,T))
                await asyncio.to_thread(resident.start)
                root=boundary.FreshTargetBoundary(tmux,environ=env)
                manager=ob.SessionBridgeManager(root,history_dir=tmp_path/'history')
                state=await manager._ensure_bridge('Alpha');bridge=state.bridge
                assert set(bridge.panes)=={pane} and other not in bridge.panes
                peer=Peer();attached=set();await manager.attach(peer,attached,'Alpha')
                old_wire=bridge.config.tmux_bin.wire_pane
                if os.environ.get('ORRERY_EXTERNAL_FRESH_R4')=='1':
                    # The acceptance fixture's initial manager is not another
                    # user of the benchmark. Close it through normal cleanup
                    # so both modes have one measured manager/peer/recorder.
                    await manager.close()
                    assert manager._closed and bridge._closed
                    manager=None
                    lifecycle=dict(prior_manager_closed=True,reconstructed=False)
                    (tmp_path/'pc-observer-lifecycle.json').write_text(json.dumps(lifecycle))
                    await external_latency_benchmark(tmp_path,monkeypatch,root,tmux,socket,pane,other,command,resident)
                    manager=ob.SessionBridgeManager(root,history_dir=tmp_path/'history')
                    state=await manager._ensure_bridge('Alpha');bridge=state.bridge
                    peer=Peer();attached=set();await manager.attach(peer,attached,'Alpha')
                    assert bridge.config.tmux_bin.wire_pane==old_wire
                    lifecycle['reconstructed']=True
                    (tmp_path/'pc-observer-lifecycle.json').write_text(json.dumps(lifecycle))
                    if received.exists():received.unlink()
                    deadline=time.monotonic()+45
                await manager.handle_message(peer,attached,dict(type='input',paneId=old_wire,data='owned-cockpit\r'))
                while not received.exists():
                    assert time.monotonic()<deadline,'selected fake provider did not receive input';await asyncio.sleep(.1)
                assert 'owned-cockpit' in received.read_text()
                assert 'owned-cockpit' not in (await command('capture-pane','-p','-t',other)).stdout
                control_file.write_text('stop')
                while not ended.exists() or not (run_path/'ended.json').exists():
                    assert time.monotonic()<deadline,'first native did not end';await asyncio.sleep(.1)
                assert ended.read_text()=='0'
                await manager.close();manager=None
                ready.unlink();control_file.write_text('idle')
                resumed=await Targets(client,T).jump(dict(session='Alpha'),open_terminal=False)
                assert resumed['ok'] and resumed['execution']=='unknown' and not resumed['native_ready']
                deadline=time.monotonic()+45
                while True:
                    current=_read_private(base/'current.json')['launch_id']
                    new_run=base/'runs'/current
                    if current!=old and ready.exists() and (new_run/'session.json').exists() and (new_run/'tmux.json').exists():break
                    assert time.monotonic()<deadline,'gated native resume did not publish receipt';await asyncio.sleep(.1)
                assert ready.read_text()==native_id and _read_private(new_run/'session.json')['native_session_id']==native_id
                manager=ob.SessionBridgeManager(root,history_dir=tmp_path/'history')
                state=await manager._ensure_bridge('Alpha')
                assert set(state.bridge.panes)=={pane} and state.bridge.config.tmux_bin.wire_pane!=old_wire
                (tmp_path/'external-fresh-bridge-proof.json').write_text(json.dumps(dict(provider=provider,
                    mail_instance_id=root.instance,mail_agent_id=people[0]['agent_id'],own_pane_only=True,
                    other_pane_input=False,same_native_resume=True,new_current=True,new_wire_handle=True)))
                if os.environ.get('ORRERY_EXTERNAL_FRESH_CLEANUP')=='1':
                    cleanup_peer=Peer();cleanup_attached=set()
                    await manager.attach(cleanup_peer,cleanup_attached,'Alpha')
                    other_before=(await command('capture-pane','-p','-J','-t',other)).stdout
                    control_file.write_text('stop');deadline=time.monotonic()+45
                    while not (new_run/'ended.json').exists():
                        assert time.monotonic()<deadline,'resumed native did not end';await asyncio.sleep(.1)
                    operator=await FreshBoundClient.prepare(runtime.root/'config.json',people[1]['binding_path'],
                        client.context['endpoint'],client_id=str(uuid4()))
                    query=dict(mail_instance_id=root.instance,mail_agent_id=people[0]['agent_id'])
                    proof=await ended_cleanup_roundtrip(manager,cleanup_peer,cleanup_attached,Targets(operator,T),query)
                    other_after=(await command('capture-pane','-p','-J','-t',other)).stdout
                    assert other_before==other_after
                    proof['other_pane_unchanged']=True
                    (tmp_path/'external-cleanup-proof.json').write_text(json.dumps(proof))
            finally:
                release.touch();control_file.write_text('stop')
                if manager is not None:await manager.close()
                if resident is not None:await asyncio.to_thread(resident.close)
                if created:
                    stopped=await command('kill-server',check=False)
                    (tmp_path/'private-tmux-cleanup.json').write_text(json.dumps(dict(socket=str(socket),stopped=stopped.returncode==0)))
                    assert stopped.returncode==0,stopped.stderr
                shutil.rmtree(private)
    asyncio.run(run())
