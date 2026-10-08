"""Codex wheel boundaries, using real cockpit helpers and tmux protocol guards."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from control_server import CommandResult, ControlConfig, TmuxControlBridge, parse_pane_line


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


def test_node_wrapper_requires_registered_codex_program_not_provider_guess():
    result = js("""
      const p={meta:{paneId:'%1',currentCommand:'node'},_wheelAlternate:true,
        _wheelMouse:[false,false,false],term:{modes:{mouseTrackingMode:'none'}}};
      const a={provider:'openai',model:'gpt-5.4',category:'agent',running:true};
      return [undefined,'codex','codex-cli','claude-code'].map(program=>
        codexWheelEligible(p,'%1',{...a,program}));
    """)
    assert result == [False, True, True, False]


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
