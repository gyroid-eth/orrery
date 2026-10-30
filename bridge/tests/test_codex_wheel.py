"""Codex wheel boundaries, using real cockpit helpers and tmux protocol guards."""
from __future__ import annotations

import asyncio
import json
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control_server import CommandResult, ControlConfig, TmuxControlBridge, parse_pane_line
from orrery_backend import SessionBridgeManager, SessionState
from runtime_target import FreshPaneBoundary, TargetRefused


def wheel_source():
    return (ROOT / 'cockpit.html').read_text().split('/* >>> codex-wheel', 1)[1].split('/* <<< codex-wheel */', 1)[0].split('*/', 1)[1]


def js(body):
    result = subprocess.run(['node', '-e', wheel_source() + '\nconsole.log(JSON.stringify((()=>{' + body + '})()));'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_only_verified_codex_active_alternate_mouse_off_is_eligible():
    result = js("""
      const p={meta:{paneId:'%1',currentCommand:'codex'},_wheelAlternate:true,
        _wheelMouse:[false,false,false],term:{modes:{mouseTrackingMode:'none'}}};
      const a={program:'codex-cli',cmd:'node',provider:'openai',category:'agent',running:true};
      const eligible=(q=p,r=a,id='%1')=>codexWheelEligible(q,id,r);
      return [eligible(),eligible(p,a,'%2'),eligible(p,null),eligible(p,{...a,program:undefined}),
        eligible(p,{...a,program:'claude-code'}),eligible(p,{...a,running:false}),
        eligible({...p,meta:{...p.meta,currentCommand:'sh'}}),
        eligible({...p,_wheelAlternate:null}),eligible({...p,_wheelAlternate:false}),
        eligible({...p,_wheelMouse:[false,null,false]}),
        eligible({...p,term:{modes:{mouseTrackingMode:'any'}}})];
    """)
    assert result == [True] + [False] * 10


def test_small_deltas_accumulate_and_gesture_budget_survives_direction_changes():
    result = js("""
      const s={amount:0,pages:0,last:-Infinity,direction:0};
      const page=(delta,t,mode=0)=>codexWheelPages(s,{deltaY:delta,deltaMode:mode},t);
      return [page(-1,0),page(-1,10),page(-94,20),page(120,30),
        page(9000,40),page(-9000,50),page(-120,400),page(6,700,1),page(1,1000,2)];
    """)
    assert result == [0, 0, -1, 1, 1, 0, -1, 1, 1]


def test_continuous_wheel_replenishes_its_budget_without_waiting_for_silence():
    result = js("""
      const s={amount:0,pages:0,last:-Infinity,direction:0};
      return Array.from({length:13},(_,i)=>codexWheelPages(s,
        {deltaY:-96,deltaMode:0},i*80));
    """)
    assert result == [-1] * 13


def test_excess_delta_is_dropped_instead_of_becoming_a_delayed_page():
    result = js("""
      const s={amount:0,pages:0,last:-Infinity,direction:0};
      const page=(delta,t)=>codexWheelPages(s,{deltaY:delta,deltaMode:0},t);
      return [page(-9000,0),page(-9000,80),page(9000,160),
        page(-1,240),page(-95,250),page(96,260)];
    """)
    assert result == [-3, 0, 0, 0, -1, 1]


def test_wheel_hook_sends_only_during_input_and_resets_after_bypass():
    result = js("""
      let now=0,handler;const packets=[];
      globalThis.performance={now:()=>now};
      globalThis.activeId='%1';
      globalThis.currentAgentNamed=()=>({program:'codex',category:'agent',running:true});
      globalThis.send=packet=>packets.push({...packet,at:now});
      globalThis.setTimeout=globalThis.requestAnimationFrame=()=>{throw Error('queued wheel work');};
      const p={meta:{paneId:'%1',currentCommand:'codex'},session:'probe',
        _wheelAlternate:true,_wheelMouse:[false,false,false],
        term:{modes:{mouseTrackingMode:'none'},
          parser:{registerCsiHandler:()=>{}},attachCustomWheelEventHandler:h=>handler=h}};
      installCodexWheel(p);
      const wheel=(delta,t,extras={})=>{now=t;let prevented=false;
        const passed=handler({deltaY:delta,deltaMode:0,
          preventDefault:()=>{prevented=true;},...extras});
        return [passed,prevented];};
      const tiny=wheel(-1,0),first=wheel(-95,16),burst=wheel(-9000,32);
      // No event, no catch-up pages, even with a large discarded delta.
      now=1000;const afterIdle=packets.length;
      const resumed=wheel(-96,1001);
      const bypass=['ctrlKey','metaKey','shiftKey','altKey'].map(key=>{
        wheel(-1,1010);return wheel(-95,1011,{[key]:true});
      });
      const afterBypass=wheel(-1,1012);
      p.term.modes.mouseTrackingMode='any';const mouse=wheel(-120,1013);
      p.term.modes.mouseTrackingMode='none';p._wheelAlternate=false;
      const normal=wheel(-120,1014);
      return {packets,tiny,first,burst,afterIdle,resumed,bypass,afterBypass,mouse,normal};
    """)
    assert result == {
        'packets': [dict(type='codex-page', paneId='%1', direction='up', count=n, at=t)
                    for n, t in [(1, 16), (2, 32), (1, 1001)]],
        'tiny': [False, True], 'first': [False, True], 'burst': [False, True],
        'afterIdle': 2, 'resumed': [False, True],
        'bypass': [[True, False]] * 4, 'afterBypass': [False, True],
        'mouse': [True, False], 'normal': [True, False],
    }


def test_node_wrapper_requires_registered_codex_program_not_provider_guess():
    result = js("""
      const p={meta:{paneId:'%1',currentCommand:'node'},_wheelAlternate:true,
        _wheelMouse:[false,false,false],term:{modes:{mouseTrackingMode:'none'}}};
      const a={provider:'openai',model:'gpt-5.4',category:'agent',running:true};
      return [undefined,'codex','codex-cli','claude-code'].map(program=>
        codexWheelEligible(p,'%1',{...a,program}));
    """)
    assert result == [False, True, True, False]


@pytest.mark.parametrize('mode', [47, 1047, 1049])
def test_scrollbar_follows_remote_snapshot_and_live_modes_for_any_program(mode):
    # A cold viewer can have a normal local buffer for a remote alternate TUI.
    # Scrollbar visibility belongs to that remote mode, not wheel eligibility.
    result = js("""
      const states=[],handlers={};
      const p={host:{classList:{toggle:(name,on)=>states.push([name,on])}},
        term:{buffer:{active:{type:'normal'}},
          parser:{registerCsiHandler:({final},handler)=>{handlers[final]=handler;}},
          attachCustomWheelEventHandler:()=>{}}};
      setCodexWheelModes(p,{alternateOn:true});
      setCodexWheelModes(p,{alternateOn:false});
      setCodexWheelModes(p,{});
      installCodexWheel(p);
      const handled=[handlers.h([MODE]),handlers.l([MODE])];
      handlers.h([1003]); // Mouse tracking must not hide a normal history bar.
      return {states,handled};
    """.replace('MODE', str(mode)))
    assert result == {
        'states': [['app-scroll', value] for value in (True, False, False, True, False)],
        'handled': [False, False],
    }


def pane(state='1\t0\t0\t0'):
    return parse_pane_line('%1\t@1\t$1\t0\t0\t80\t18\t1\tprobe\tcodex\t' + state)


@pytest.mark.parametrize('state,alternate,mouse', [
    ('1\t0\t0\t0', True, False), ('0\t0\t0\t0', False, False),
    ('1\t0\t0\t1', True, True), ('\t0\t0\t0', None, False),
    ('1\t0\t\t0', True, None),
])
def test_pane_modes_distinguish_unknown_from_off(state, alternate, mouse):
    p = pane(state)
    assert p.to_json()['alternateOn'] is alternate
    assert p.to_json()['mouseTracking'] is mouse


def test_older_pane_metadata_is_unknown_not_off():
    p = parse_pane_line('%1\t@1\t$1\t0\t0\t80\t18\t1\tprobe\tcodex')
    assert p.alternate_on is None and p.mouse_tracking is None


class Bridge(TmuxControlBridge):
    def __init__(self, state):
        super().__init__(ControlConfig(host='127.0.0.1', port=0, session='probe', tmux_bin='tmux'))
        self.panes = {'%1': pane()}
        self.state = state
        self.inputs = []

    async def send_command(self, args, **kwargs):
        assert args[:4] == ['display-message', '-p', '-t', '%1']
        return self.state

    async def send_input(self, pane_id, data, **kwargs):
        self.inputs.append((pane_id, data))


@pytest.mark.parametrize('state', [
    None, CommandResult(ok=False, lines=[]), CommandResult(ok=True, lines=[]),
    *[CommandResult(ok=True, lines=[x]) for x in ['sh\t1\t0\t0\t0',
      'claude\t1\t0\t0\t0', 'codex\t0\t0\t0\t0',
      'codex\t1\t1\t0\t0', 'codex\t1\t0\t1\t0',
      'codex\t1\t0\t0\t1', 'codex\t1\t0\t\t0']],
])
def test_live_guard_rejects_stale_or_unknown_modes(state):
    bridge = Bridge(state)
    asyncio.run(bridge.send_codex_page('%1', 'up', 1))
    assert bridge.inputs == []


@pytest.mark.parametrize('direction,count', [('up', True), ('up', 0), ('up', 4), ('up', '1'), ('left', 1)])
def test_page_packet_is_bounded(direction, count):
    bridge = Bridge(CommandResult(ok=True, lines=['codex\t1\t0\t0\t0']))
    asyncio.run(bridge.send_codex_page('%1', direction, count))
    assert bridge.inputs == []


@pytest.mark.parametrize("command", ["codex", "node"])
def test_verified_page_packet_emits_only_the_requested_pages(command):
    bridge = Bridge(CommandResult(ok=True, lines=[command + '\t1\t0\t0\t0']))
    asyncio.run(bridge.send_codex_page('%1', 'up', 2))
    asyncio.run(bridge.send_codex_page('%1', 'down', 1))
    assert bridge.inputs == [('%1', '\x1b[5~' * 2), ('%1', '\x1b[6~')]


def test_websocket_page_dispatch_rejects_missing_and_unknown_panes():
    bridge = Bridge(CommandResult(ok=True, lines=['node\t1\t0\t0\t0']))
    for pane_id in (None, ['%1'], '%2', '%1'):
        asyncio.run(bridge.handle_client_message({
            'type': 'codex-page', 'paneId': pane_id, 'direction': 'up', 'count': 1,
        }))
    assert bridge.inputs == [('%1', '\x1b[5~')]


class Peer:
    def __init__(self):
        self.messages = []

    async def send(self, data):
        self.messages.append(json.loads(data))

    async def send_json(self, data):
        self.messages.append(data)


def test_unified_backend_delivers_pages_only_to_an_attached_pane(tmp_path):
    async def scenario():
        bridge = Bridge(CommandResult(ok=True, lines=['codex\t1\t0\t0\t0']))
        manager = SessionBridgeManager('tmux', history_dir=tmp_path)
        manager.states['probe'] = SessionState(bridge=bridge)
        peer = Peer()
        packet = {'type': 'codex-page', 'paneId': '%1', 'direction': 'up', 'count': 1}
        await manager.handle_message(peer, set(), packet)
        assert bridge.inputs == []
        assert peer.messages[-1]['type'] == 'error'
        peer.messages.clear()
        await manager.handle_message(peer, {'probe'}, packet)
        assert peer.messages == []
        assert bridge.inputs == [('%1', '\x1b[5~')]
    asyncio.run(scenario())


@pytest.mark.parametrize('condition', ['valid', 'detached', 'raw-pane', 'wrong-agent', 'no-proof', 'expired', 'mouse-on'])
def test_fresh_backend_pages_keep_wire_identity_and_input_proof(tmp_path, condition):
    async def scenario():
        target = object.__new__(FreshPaneBoundary)
        target.pane_id = '%1'
        target.wire_pane = 'fresh-wheel-1'
        target.ref = {'mail_instance_id': '0' * 32, 'mail_agent_id': 1}
        bridge = Bridge(CommandResult(ok=True, lines=[
            'codex\t1\t0\t0\t' + ('1' if condition == 'mouse-on' else '0')]))
        bridge.config = ControlConfig('127.0.0.1', 0, 'probe', target)
        bridge.master_fd = 123  # All writes are captured below; no OS fd.
        writes = []
        checks = []

        async def write(data):
            writes.append(shlex.split(data.decode()))

        async def check():
            checks.append('input-proof')
            if condition == 'expired':
                raise TargetRefused('FRESH_TARGET_PROOF_EXPIRED')

        proof = SimpleNamespace(target=target, purpose='input', closed=False, check=check)
        peer = Peer()
        bridge._fresh_peer_proofs = {} if condition == 'no-proof' else {peer: (proof, None)}
        # Exercise the real input proof/lock/encoding, after the fake mode read.
        bridge._write_master = write
        bridge.send_input = TmuxControlBridge.send_input.__get__(bridge)
        manager = SessionBridgeManager('tmux', history_dir=tmp_path)
        manager.states['probe'] = SessionState(bridge=bridge)
        packet = {'type': 'codex-page', 'paneId': target.wire_pane, 'direction': 'down', 'count': 1}
        if condition == 'raw-pane':
            packet['paneId'] = '%1'
        if condition == 'wrong-agent':
            packet['mail_agent_id'] = 2
        attached = set() if condition == 'detached' else {'probe'}
        if condition in {'wrong-agent', 'no-proof', 'expired'}:
            with pytest.raises(TargetRefused):
                await manager.handle_message(peer, attached, packet)
        else:
            await manager.handle_message(peer, attached, packet)
        assert writes == ([['send-keys', '-t', '%1', '-H', '1b', '5b', '36', '7e']]
                          if condition == 'valid' else [])
        assert checks == (['input-proof'] if condition in {'valid', 'expired'} else [])
    asyncio.run(scenario())
