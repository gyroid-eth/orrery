"""Bound native records -> inert steps; no live provider/runtime/network."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from conversation_history import codex_event, read_codex_page, open_reader
from conversation_readers import normalize
from conversation_steps import codex_completed, command_summary, filename, opaque, summary

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


def segmented_records(provider, separator='assistant'):
    notice = ('ORRERY Mail notification: message from PeerFixture [normal]: Review ready. '
              'Body (complete; no inbox fetch needed): The fixture is ready.')
    role, text = {
        'assistant': ('assistant', 'The first checks passed. I will verify the output.'),
        'user': ('user', 'Please verify the output as well.'),
        'mail': ('user', notice),
    }.get(separator, ('assistant', ''))
    if provider == 'claude':
        def tools(names):
            return [record for name in names for record in (
                c('assistant', [dict(type='tool_use', id=name, name='Read',
                                     input={'file_path': f'/fixture/{name}.txt'})]),
                c('user', [dict(type='tool_result', tool_use_id=name)]))]

        first = [c('assistant', 'I will check the generated files.')] + tools(['input', 'config', 'schema'])
        return first, [c(role, text)], tools(['output', 'report'])

    def message(role, text):
        return dict(type='response_item', timestamp='2026-11-15T01:00:01Z',
                    payload=dict(type='message', role=role, content=text))

    def tools(names):
        return [native('CommandExecution', ident=name, command=[name], status='completed') for name in names]

    first = [dict(type='event_msg', payload=dict(type='task_started', turn_id='turn-one')),
             message('assistant', 'I will check the generated files.')] + tools(['input', 'config', 'schema'])
    boundary = message(role, text)
    if separator == 'mail-sent':
        args = dict(to=['PeerFixture'], subject='Review ready', body_md='The fixture is ready.')
        boundary = dict(type='response_item', payload=dict(type='custom_tool_call', name='exec',
                        input='await tools.mcp__orrery_mail__send_message('+json.dumps(args)+');'))
    return first, [boundary], tools(['output', 'report'])


@pytest.mark.parametrize('provider,separator', [('claude', 'assistant'), ('codex', 'assistant'),
                                               ('claude', 'mail'), ('codex', 'user'), ('codex', 'mail-sent')])
def test_visible_output_splits_native_steps_in_reload_and_delta(tmp_path, provider, separator):
    first, boundary, last = segmented_records(provider, separator)
    path = tmp_path / 'synthetic.jsonl'
    path.write_bytes(b''.join(map(line, first)))
    row = dict(program='claude-code' if provider == 'claude' else 'codex', history_binding='bound',
               transcript_path=str(path), history_session_id='synthetic', history_receipt_ts='fixture')
    with open_reader(row) as reader:
        initial = reader.read_page()
    with path.open('ab') as transcript:
        transcript.write(b''.join(map(line, boundary + last)))
    with open_reader(row) as reader:
        delta = reader.read_page(after=initial['after'])
        full = reader.read_page()

    live = model(initial['events'] + delta['events'], provider.title())
    assert live == model(full['events'], provider.title())
    assert [len(run['steps']) for run in live['groups']] == [3, 2]
    first_run, second_run = live['groups']
    assert first_run['closed'] and not second_run['closed']
    for run, events in ((first_run, initial['events']), (second_run, delta['events'][1:])):
        assert any(event['id'] == run['anchor'] for event in events)


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
    assert [e['kind'] for e in events if e.get('step_boundary')] == ['text']


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


def test_consecutive_claude_outputs_do_not_create_empty_intermediate_runs():
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
    assert [e['kind'] for e in events if e.get('step_boundary')] == ['text', 'mail', 'system', 'text', 'text']
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


URL = 'https://example.invalid/report?token=SECRET_VALUE#private'
URL_TARGETS = [URL, 's:/report?token=SECRET_VALUE#private',
              's://user:password@host/report?token=SECRET_VALUE#private',
              r's:\report?token=SECRET_VALUE#private']


@pytest.mark.parametrize('value,expected', [
    (URL, 'report'),
    ('https://SECRET_VALUE:password@example.invalid/report?other=value#SECRET_VALUE', 'report'),
    ('//example.invalid/report?token=SECRET_VALUE#private', 'report'),
    ('https://SECRET_VALUE@example.invalid?token=SECRET_VALUE', ''),
    ('https://[invalid/report?token=SECRET_VALUE', ''),
    ('notes/report.md', 'report.md'),
    ('C:\\notes\\report.md', 'report.md'),
    ('s:/report?token=SECRET_VALUE#private', 'report'),
    ('s://user:password@host/report?token=SECRET_VALUE#private', 'report'),
    (r's:\report?token=SECRET_VALUE#private', 'report'),
    (r's:\\report?token=SECRET_VALUE#private', ''),
    ('file:/report?token=SECRET_VALUE#private', 'report'),
    ('file:report?token=SECRET_VALUE#private', ''),
    ('notes:/report?token=SECRET_VALUE#private', 'report'),
    ('notes:report?token=SECRET_VALUE#private', ''),
    ('C:/notes/report.md', 'report.md'),
])
def test_target_filename_uses_only_url_path_and_preserves_local_paths(value, expected):
    assert filename(value) == expected
    assert command_summary([value]) == expected


@pytest.mark.parametrize('failed', [False, True], ids=['success', 'failed'])
@pytest.mark.parametrize('form', ['claude', 'mcp', 'image', 'change', 'parsed-command', 'executable'])
@pytest.mark.parametrize('target', URL_TARGETS)
def test_every_basename_projection_strips_url_secrets(form, failed, target):
    if form == 'claude':
        events = claude_events([
            c('assistant', [dict(type='tool_use', id='url', name='Read', input={'file_path': target})]),
            c('user', [dict(type='tool_result', tool_use_id='url', is_error=failed)])])
        assert events[0]['step']['detail'] == 'report'
    else:
        kind, fields = {
            'mcp': ('McpToolCall', dict(tool='read_file', arguments={'path': target}, result={'isError': failed})),
            'image': ('ImageView', dict(path=target)),
            'change': ('FileChange', dict(changes={target: {}})),
            'parsed-command': ('CommandExecution', dict(command=['pytest'], parsed_cmd=[{'path': target}])),
            'executable': ('CommandExecution', dict(command=[target])),
        }[form]
        events = [project(native(kind, status='failed' if failed else 'completed', **fields))]
        assert events[0]['step']['detail'].endswith('report')
    assert 'SECRET_VALUE' not in json.dumps(events) and '?token=' not in json.dumps(events)


@pytest.mark.parametrize('failed', [False, True], ids=['success', 'failed'])
@pytest.mark.parametrize('form', ['claude', 'mcp', 'image', 'executable'])
@pytest.mark.parametrize('target', URL_TARGETS)
def test_http_response_does_not_publish_url_query_in_target(tmp_path, monkeypatch, form, failed, target):
    import test_conversation_history as api
    async def current_api(*args, **kwargs):
        return 35
    monkeypatch.setattr(api.backend, 'conversation_api_version', current_api)
    if form == 'claude':
        records = [c('assistant', [dict(type='tool_use', id='url', name='Read', input={'file_path': target})]),
                   c('user', [dict(type='tool_result', tool_use_id='url', is_error=failed)])]
    else:
        kind, fields = {
            'mcp': ('McpToolCall', dict(tool='read_file', arguments={'path': target}, result={'isError': failed})),
            'image': ('ImageView', dict(path=target)),
            'executable': ('CommandExecution', dict(command=[target])),
        }[form]
        records = [native(kind, status='failed' if failed else 'completed', **fields)]
    monkeypatch.setattr(api, 'record', lambda *a, **kw: b''.join(line(r) for r in records))
    async def scenario(client, base, reads):
        async with client.get(base+'/telemetry/conversation?agent=BoundAgent') as response:
            data = await response.json()
            assert response.status == 200
            assert 'SECRET_VALUE' not in json.dumps(data) and '?token=' not in json.dumps(data)
            assert data['events'][0]['step']['detail'] == 'report'
        assert len(reads) == 2
    row = (dict(program='claude-code', history_session_id='synthetic', history_receipt_ts='fixture')
           if form == 'claude' else {})
    api.run_api(tmp_path, monkeypatch, scenario, row_update=row)


@pytest.mark.parametrize('other', ['no-completion', 'unknown-completion', 'retained-without-completion'])
def test_codex_unmatched_tool_stays_unconsumed(other):
    start = project(dict(type='event_msg', payload=dict(type='task_started', turn_id='turn-one')), 0)
    tool = project(dict(type='response_item', payload=dict(type='function_call', name='old_server_tool',
                                                         call_id='old-call', arguments='{}')), 1)
    rows = [start, tool]
    if other == 'unknown-completion':
        assert project(native('Extension', kind='unknown'), 2) is None
    if other == 'retained-without-completion':
        done = project(native('CommandExecution', command=['pytest'], status='completed'), 3)
        assert tool['id'] not in model(rows+[done], 'Codex')['consumed']
    out = model(rows, 'Codex')
    assert tool['id'] not in out['consumed'] and not any(g['steps'] for g in out['groups'])


def test_steps_public_instance_has_reset_without_unused_dispose():
    result = subprocess.run(['node', '-e',
        "const instance=require(process.argv[1]).mount({host:{}});instance.reset();console.log('dispose' in instance)",
        str(JS)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and result.stdout.strip() == 'false'


@pytest.mark.parametrize('later_prompt', [False, True])
def test_unpaired_claude_call_is_consumed_only_after_its_matching_result(later_prompt):
    events=claude_events([c('user','Inspect the report'),
        c('assistant',[dict(type='tool_use',id='pending',name='Read',input={'file_path':'/fixture/report.md'})])])
    call=next(e for e in events if e.get('step',{}).get('phase')=='call')
    if later_prompt:
        events.append(dict(id='later-prompt',kind='text',role='user',text='Another task',step_boundary=True))
    pending=model(events,'Claude')
    assert call['id'] not in pending['consumed']
    assert sum(len(g['steps']) for g in pending['groups'])==0
    assert sum(g['orphans'] for g in pending['groups'])==0
    result=claude_events([c('user',[dict(type='tool_result',tool_use_id='pending')])])[0]
    result['id']='late-result';events.append(result)
    paired=model(events,'Claude')
    assert {call['id'],result['id']}<=set(paired['consumed'])
    assert len(paired['groups'][0]['steps'])==1
    assert sum(len(g['steps']) for g in paired['groups'])==1
