"""Full-tour order, trusted iframe messages and observed parent/child rounds."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / 'cockpit_full_tour.js'


def run(script):
    if not shutil.which('node'):
        pytest.skip('node unavailable')
    result = subprocess.run(['node', '-e', f'const tour=require({json.dumps(str(MODULE))});' + script],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_selected_order_and_exact_workshop_rules_are_present():
    result = run("console.log(JSON.stringify({ids:tour.STEPS.map(s=>s.id),prompt:tour.SHIRITORI_PROMPT}));")
    assert result['ids'] == ['full-start', 'full-choose', 'full-talk', 'full-shiritori',
                             'full-split', 'full-drag', 'full-planetarium', 'full-usage',
                             'full-telemetry', 'full-exit', 'full-edge', 'full-select',
                             'full-replay', 'full-resume', 'full-network-settings', 'full-return']
    for requirement in ['/delegate', 'ORRERY Mail (send_message)', 'exactly three round trips',
                        'shiritori ready', 'りんご', 'never Haiku', 'Do not use --worktree',
                        'Do not use Claude Code\'s built-in Agent or SendMessage',
                        'observed Mail ID', 'no new game']:
        assert requirement in result['prompt']


def test_telemetry_messages_require_owned_frame_origin_version_and_action():
    assert run("""
      const frame={},other={},origin='http://local:9876';
      const event={source:frame,origin,data:{type:'orrery-tour-action',version:1,action:'exit'}};
      const values=[tour.telemetryAction(event,origin,frame),
        tour.telemetryAction({...event,source:other},origin,frame),
        tour.telemetryAction({...event,origin:'https://elsewhere'},origin,frame),
        tour.telemetryAction({...event,data:{...event.data,version:2}},origin,frame),
        tour.telemetryAction({...event,data:{...event.data,action:'__proto__'}},origin,frame),
        tour.telemetryAction(event,origin,null)];
      console.log(JSON.stringify(values));
    """) == ['full-exit', None, None, None, None, None]


def test_first_actual_round_must_be_between_parent_and_same_child():
    assert run("""
      const t=tour.createShiritoriTracker('Parent',1000000);
      const agents=[{name:'Child',parent:'Parent'},{name:'Other',parent:'Someone'}];
      const ready={id:1,ts:1001,sender:'Child',recipient:'Parent',subject:'shiritori ready'};
      const out={id:2,ts:1002,sender:'Parent',recipient:'Child',subject:'shiritori round 1'};
      const reply={id:3,ts:1003,sender:'Child',recipients:[{name:'Parent'}],subject:'Re: shiritori round 1'};
      const unrelated={...reply,id:4,sender:'Other'};
      const progress=[t.add([ready],agents),t.add([out],agents),t.add([unrelated],agents),
        t.add([reply],agents),t.add([out,reply],agents)];
      console.log(JSON.stringify(progress));
    """) == [False, False, False, True, True]


def test_old_missing_time_wrong_round_and_different_children_do_not_count():
    assert run("""
      const agents=[{name:'C1',parent:'P'},{name:'C2',parent:'P'}];
      const out={id:1,ts:1001,sender:'P',recipient:'C1',subject:'shiritori round 1'};
      const reply={id:2,ts:1002,sender:'C1',recipient:'P',subject:'shiritori round 1'};
      const results=[];
      for(const bad of [{...reply,ts:999},{...reply,ts:null},
        {...reply,subject:'shiritori round 2'},{...reply,sender:'C2'}, {...reply,id:1}]){
        const t=tour.createShiritoriTracker('P',1000000);
        results.push(t.add([out,bad],agents));
      }
      console.log(JSON.stringify(results));
    """) == [False, False, False, False, False]


def test_observation_accepts_iso_time_and_delayed_lineage():
    assert run("""
      const t=tour.createShiritoriTracker('P',Date.parse('2026-10-04T00:00:00Z'));
      const mails=[{id:1,created_ts:'2026-10-04T00:00:02Z',sender:'P',recipient:'C',subject:'shiritori round 1'},
        {id:2,created_ts:'2026-10-04T00:00:03Z',sender:'C',recipient:'P',subject:'shiritori round 1'}];
      console.log(JSON.stringify([t.add(mails,[]),t.add(mails,[{name:'C',parent:'P'}])]));
    """) == [False, True]
