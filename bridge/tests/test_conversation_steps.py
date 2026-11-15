"""Bound native records -> inert steps; no live provider/runtime/network."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conversation_history import codex_event, read_codex_page, open_reader
from conversation_readers import normalize
from conversation_steps import codex_completed, opaque, summary

JS = Path(__file__).resolve().parents[1] / 'conversation_steps.js'


def native(item_type, ident='operation', turn='turn-one', **fields):
    return dict(type='event_msg', timestamp='2026-11-15T01:00:04Z',
        payload=dict(type='item_completed', turn_id=turn, thread_id='synthetic',
                     started_at_ms=1000, completed_at_ms=4000,
                     item=dict(type=item_type, id=ident, **fields)))


def c(role, blocks, ts='2026-11-15T01:00:01Z', **fields):
    return dict(type=role, sessionId='synthetic', timestamp=ts,
                message=dict(role=role, content=blocks), **fields)


def line(item):
    return (json.dumps(item) + '\n').encode()


def project(item, index=0):
    return codex_event(line(item), index)


def model(events, provider):
    script = """const fs=require('fs'),m=require(process.argv[1]),data=JSON.parse(fs.readFileSync(0,'utf8'));
const out=m.collect(data.events,data.provider);
console.log(JSON.stringify({groups:out.groups,consumed:[...out.consumed]}));"""
    result = subprocess.run(['node', '-e', script, str(JS)],
        input=json.dumps(dict(events=events, provider=provider)), text=True,
        capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def claude_events(records):
    return [dict(event, id=str(n)+':'+str(index)) for n, record in enumerate(records)
            for index, event in normalize(record, 'claude', 'synthetic')]


@pytest.mark.parametrize('kind,fields,tool,status', [
    ('CommandExecution', dict(command=['zsh','-lc','pytest -q SECRET_VALUE'],status='completed',exit_code=0), 'Shell','done'),
    ('CommandExecution', dict(command=['python','SECRET_VALUE'],status='completed',exit_code=1), 'Shell','failed'),
    ('CommandExecution', dict(command=['python'],status='failed',exit_code=0), 'Shell','failed'),
    ('McpToolCall', dict(server='fixture',tool='read_file',arguments={'path':'/fixture/a.py','api_key':'SECRET_VALUE'},result={'isError':False},status='completed'), 'read_file','done'),
    ('McpToolCall', dict(tool='search',result={'isError':True},status='completed'), 'search','failed'),
    ('FileChange', dict(changes={'/fixture/a.py':{'unified_diff':'SECRET_VALUE'}},status='completed',stdout='SECRET_VALUE'), 'apply_patch','done'),
    ('FileChange', dict(changes={},status='failed'), 'apply_patch','failed'),
    ('ImageView', dict(path='/fixture/picture.png'), 'view_image','observed'),
    ('Extension', dict(kind='web.search',query='SECRET_VALUE',results=[{'snippet':'SECRET_VALUE'}]), 'web_search','observed'),
    ('WebSearch', dict(query='SECRET_VALUE'), 'web_search','observed'),
])
def test_codex_typed_completion_is_bounded_summary(kind, fields, tool, status):
    event = project(native(kind, **fields))
    assert event['step']['tool'] == tool
    assert event['step']['status'] == status
    assert event['step']['started'] == 1000 and event['step']['ended'] == 4000
    assert event['step']['id'] == opaque('operation')
    assert 'SECRET_VALUE' not in json.dumps(event)
    assert not {'arguments','result','command','stdout','aggregated_output','changes'} & event.keys()


@pytest.mark.parametrize('item', [
    dict(type='Reasoning', id='secret', raw_content=['SECRET_VALUE']),
    dict(type='Extension', id='secret', kind='unknown', output='SECRET_VALUE'),
    dict(type='McpToolCall', id='secret', arguments={'token':'SECRET_VALUE'}),
    dict(type='CommandExecution', id=None),
])
def test_unknown_or_unidentified_items_do_not_gain_step_data(item):
    raw = native('CommandExecution')
    raw['payload']['item'] = item
    assert codex_completed(raw) is None


def test_no_static_exec_source_is_counted_as_executed_inner_operation():
    wrapper = dict(type='response_item', payload=dict(type='custom_tool_call',name='exec',
        call_id='wrapper', input='await tools.exec_command({cmd:"SECRET_VALUE"})'))
    event = project(wrapper)
    assert event['step_wrapper'] is True and 'step' not in event
    assert 'SECRET_VALUE' not in json.dumps(event)
    start = project(dict(type='event_msg', payload=dict(type='task_started',turn_id='turn-one')), 1)
    done = project(native('CommandExecution',command=['pytest'],status='completed'),2)
    grouped = model([start,event,done], 'Codex')
    assert sum(len(g['steps']) for g in grouped['groups']) == 1
    assert event['id'] in grouped['consumed']


def test_claude_matches_ids_not_result_order_and_never_publishes_bodies():
    events = claude_events([
        c('user','A generated task'),
        c('assistant',[dict(type='tool_use',id='read',name='Read',input={'file_path':'/fixture/a.py','token':'SECRET_VALUE'}),
                       dict(type='tool_use',id='bash',name='Bash',input={'command':'pytest -k SECRET_VALUE'})]),
        c('user',[dict(type='tool_result',tool_use_id='bash',is_error=True,content='SECRET_VALUE')]),
        c('user',[dict(type='tool_result',tool_use_id='read',is_error=False,content='SECRET_VALUE')]),
    ])
    grouped = model(events, 'Claude')
    assert len(grouped['groups']) == 1
    steps = grouped['groups'][0]['steps']
    assert [(s['tool'],s['status']) for s in steps] == [('Read','done'),('Bash','failed')]
    assert steps[0]['detail'] == 'a.py' and steps[1]['detail'] == 'pytest'
    assert 'SECRET_VALUE' not in json.dumps(events)
    assert sum(bool(e.get('step_boundary')) for e in events) == 1


def test_claude_pair_survives_native_page_boundaries_and_earlier_loading(tmp_path):
    path=tmp_path/'synthetic.jsonl'
    path.write_bytes(b''.join(line(r) for r in [
        c('user','A generated task'),
        c('assistant',[dict(type='tool_use',id='read',name='Read',input={'file_path':'a.py'})]),
        c('user',[dict(type='tool_result',tool_use_id='read',content='SECRET_VALUE')])]))
    row=dict(program='claude-code',history_binding='bound',transcript_path=str(path),
             history_session_id='synthetic',history_receipt_ts='fixture',name='Fixture')
    with open_reader(row) as reader:
        newest=reader.read_page(limit=1)
        earlier=reader.read_page(before=newest['before'],limit=2)
    partial=model(newest['events'],'Claude')
    assert partial['groups'][0]['orphans'] == 1
    assert partial['groups'][0]['steps'] == []
    full=model(earlier['events']+newest['events'],'Claude')
    assert len(full['groups']) == 1 and len(full['groups'][0]['steps']) == 1
    assert full['groups'][0]['orphans'] == 0


def test_codex_turn_ids_and_pages_dedup_completed_operation(tmp_path):
    path=tmp_path/'synthetic.jsonl'
    records=[
        dict(type='event_msg',payload=dict(type='task_started',turn_id='one',started_at=1)),
        native('ImageView',ident='image',turn='one',path='/fixture/a.png'),
        dict(type='event_msg',payload=dict(type='task_complete',turn_id='one',started_at=1,completed_at=5,duration_ms=4000)),
        dict(type='event_msg',payload=dict(type='task_started',turn_id='two',started_at=6)),
        native('CommandExecution',ident='shell',turn='two',command=['pytest'],status='completed',exit_code=0),
        native('CommandExecution',ident='shell',turn='two',command=['pytest'],status='completed',exit_code=0),
    ]
    path.write_bytes(b''.join(line(r) for r in records))
    page=read_codex_page(str(path),limit=2);events=page['events']
    while page['has_older']:
        page=read_codex_page(str(path),before=page['before'],limit=2)
        events=page['events']+events
    grouped=model(events,'Codex')
    assert [len(g['steps']) for g in grouped['groups']] == [1,1]
    assert grouped['groups'][0]['duration'] == 4
    assert grouped['groups'][0]['closed'] is True
    assert grouped['groups'][1]['closed'] is False


def test_claude_mid_turn_mail_system_and_queued_prompt_do_not_split_turn():
    events=claude_events([
        c('user','Generated task'),
        c('user','ORRERY Mail notification: message from Fixture [normal]: title. Body (complete; no inbox fetch needed): body'),
        c('user','<system-reminder>Generated notice</system-reminder>'),
        dict(type='attachment',sessionId='synthetic',attachment=dict(type='queued_command',
            commandMode='prompt',origin={'kind':'human'},prompt='Steering in the same turn')),
        c('assistant',[dict(type='tool_use',id='call',name='Read',input={})]),
        c('user',[dict(type='tool_result',tool_use_id='call')]),
        c('user','The next generated task'),
    ])
    grouped=model(events,'Claude')
    assert len(grouped['groups']) == 2
    assert grouped['groups'][0]['closed'] is True
    assert len(grouped['groups'][0]['steps']) == 1


@pytest.mark.parametrize('provider',['dsh','Hermes','unsupported'])
def test_other_providers_keep_existing_tool_groups(provider):
    out=model([dict(id='tool',kind='tool',step={'id':opaque('call'),'phase':'complete'})],provider)
    assert out == {'groups':[], 'consumed':[]}


def test_target_summaries_do_not_copy_raw_arguments_or_commands():
    assert summary('Read',dict(file_path='/fixture/a.py',password='SECRET_VALUE')) == 'a.py'
    assert summary('Bash',dict(command='SECRET_VALUE=one curl https://secret.invalid')) == ''
    assert summary('mcp__orrery_mail__send_message',dict(to=['Fixture'],body_md='SECRET_VALUE')) == 'To Fixture'
    assert summary('unrecognized',dict(path='SECRET_VALUE')) == ''


@pytest.mark.parametrize('provider', ['claude', 'codex'])
@pytest.mark.parametrize('changed', [False, True], ids=['bound', 'binding-changed'])
def test_native_steps_through_api_keep_post_read_binding_check(tmp_path, monkeypatch, provider, changed):
    import test_conversation_history as api
    async def current_api(*args, **kwargs):
        return 35
    monkeypatch.setattr(api.backend, 'conversation_api_version', current_api)
    records = ([c('user', 'Generated task'),
                c('assistant', [dict(type='tool_use', id='call', name='Read',
                                    input={'path': '/fixture/a.py', 'token': 'SECRET_VALUE'})]),
                c('user', [dict(type='tool_result', tool_use_id='call', content='SECRET_VALUE')])]
               if provider == 'claude' else
               [native('CommandExecution', command=['pytest', 'SECRET_VALUE'], status='completed')])
    monkeypatch.setattr(api, 'record', lambda *a, **kw: b''.join(line(r) for r in records))
    async def scenario(client, url, reads):
        async with client.get(url+'/telemetry/conversation?agent=BoundAgent') as response:
            data = await response.json()
            if changed:
                assert response.status == 409 and data == {'ok': False, 'error': 'history_changed'}
            else:
                assert response.status == 200 and response.headers['Cache-Control'] == 'no-store'
                assert sum(len(g['steps']) for g in model(data['events'], provider.title())['groups']) == 1
                assert 'SECRET_VALUE' not in json.dumps(data)
                assert 'transcript_path' not in data
        assert len(reads) == 2
    row = (dict(program='claude-code', history_session_id='synthetic', history_receipt_ts='fixture')
           if provider == 'claude' else {})
    api.run_api(tmp_path, monkeypatch, scenario, row_update=row, change_binding=changed)
