"""Native edit results, opaque references, and a lazy Reader response."""
import asyncio
import json
from pathlib import Path
import re
import sys

from aiohttp import ClientSession, web
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import conversation_step_diff as diff
import orrery_backend as backend
from conversation_history import open_reader
from conversation_preview import PreviewUnavailable, ReferenceStore
from test_conversation_history import start
from test_conversation_steps import c, line, native


PATH = '/fixture/cache.py'


def claude_records(tool='Edit', args=None, metadata=None, *, failed=False):
    if args is None:
        args = dict(old_string='before', new_string='after', replace_all=False)
    return [
        c('user', 'Update the cache.'),
        c('assistant', [dict(type='tool_use', name=tool, id='edit-fixture',
                             input=dict(file_path=PATH, **args))]),
        c('user', [dict(type='tool_result', tool_use_id='edit-fixture', content='Applied', is_error=failed)],
          toolUseResult=dict(filePath=PATH, **metadata) if metadata is not None else None),
    ]


def codex_record(changes, **options):
    return native('FileChange', status=options.get('status', 'completed'), changes=changes)


def responses(records):
    call, result = [row['message']['content'][0] for row in records[1:]]
    return diff.claude_diff(call, result, records[2]['toolUseResult'])


def lines(files):
    return [(item['op'], item['text']) for hunk in diff.detail(files)['hunks'] for item in hunk['lines']]


def test_claude_edit_uses_changed_hunks_from_result_before_requested_text():
    patch = dict(oldStart=41, oldLines=2, newStart=41, newLines=3,
                 lines=[' unchanged', '-before', '+USER_CHANGED', '+added'])
    files = responses(claude_records(metadata=dict(structuredPatch=[patch])))
    assert diff.stat(files) == dict(added=2, removed=1, new_file=False)
    assert diff.detail(files)['hunks'][0]['header'] == '@@ -41,2 +41,3 @@'
    assert lines(files) == [(' ', 'unchanged'), ('-', 'before'), ('+', 'USER_CHANGED'), ('+', 'added')]


def test_claude_edit_falls_back_to_the_matched_request():
    files = responses(claude_records())
    assert diff.stat(files) == dict(added=1, removed=1, new_file=False)
    assert lines(files) == [('-', 'before'), ('+', 'after')]


def test_claude_edit_replace_all_can_use_the_recorded_original():
    files = responses(claude_records(args=dict(old_string='x', new_string='y', replace_all=True),
                                     metadata=dict(originalFile='x\nunchanged\nx')))
    assert diff.stat(files) == dict(added=2, removed=2, new_file=False)


def test_claude_multiedit_keeps_the_original_order():
    files = responses(claude_records('MultiEdit', dict(edits=[
        dict(old_string='begin()', new_string='begin(use_cache=True)'),
        dict(old_string='close()', new_string='flush()\nclose()', replace_all=False),
    ])))
    assert diff.stat(files) == dict(added=2, removed=1, new_file=False)
    assert len(diff.detail(files)['hunks']) == 2
    assert lines(files) == [('-', 'begin()'), ('+', 'begin(use_cache=True)'), ('+', 'flush()'), (' ', 'close()')]


@pytest.mark.parametrize('metadata,new_file,removed', [
    (dict(type='create', originalFile=None), True, 0),
    (dict(type='update', originalFile='before\n'), False, 1),
])
def test_claude_write_uses_creation_and_overwrite_evidence(metadata, new_file, removed):
    files = responses(claude_records('Write', dict(content='after\nextra\n'), metadata=metadata))
    assert diff.stat(files) == dict(added=2, removed=removed, new_file=new_file)
    assert diff.detail(files)['new_file'] is new_file
    assert lines(files)[-2:] == [('+', 'after'), ('+', 'extra')]


@pytest.mark.parametrize('tool,args,metadata,failed', [
    ('Write', dict(content='unknown prior body'), None, False),
    ('Read', {}, None, False),
    ('Bash', dict(command='pytest'), None, False),
    ('Edit', dict(old_string='a', new_string='b'), None, True),
])
def test_claude_omits_stats_for_unconfirmed_or_non_edit_records(tool, args, metadata, failed):
    assert diff.stat(responses(claude_records(tool, args, metadata, failed=failed))) is None


def test_codex_counts_a_completed_update_and_add_without_diff_headers():
    patch = '--- a/cache.py\n+++ b/cache.py\n@@ -1,2 +1,2 @@\n context\n---before\n+++after\n'
    changes = {PATH: dict(type='update', unified_diff=patch, move_path=None),
               '/fixture/check.json': dict(type='add', content='{}\n')}
    files = diff.codex_diff(codex_record(changes))
    assert diff.stat(files) == dict(added=2, removed=1, new_file=False)
    detail = diff.detail(files)
    assert detail['path'] == '2 files'
    assert detail['hunks'][0]['header'].endswith('cache.py')
    assert detail['hunks'][1]['header'].endswith('check.json')
    assert lines(files) == [(' ', 'context'), ('-', '--before'), ('+', '++after'), ('+', '{}')]
    added = diff.codex_diff(codex_record({PATH: changes['/fixture/check.json']}))
    assert diff.stat(added) == dict(added=1, removed=0, new_file=True)
    assert diff.stat(diff.codex_diff(codex_record(changes, status='failed'))) is None


@pytest.mark.parametrize('value,expected', [('x\n' * 401, 400), ('é' * 20000 + '\nremaining', 0)])
def test_detail_respects_line_and_serialized_byte_caps(value, expected):
    files = diff.codex_diff(codex_record({PATH: dict(type='add', content=value)}))
    result = diff.detail(files)
    assert result['truncated']
    assert sum(len(hunk['lines']) for hunk in result['hunks']) == expected
    assert len(diff.encode(result).encode()) <= diff.MAX_BYTES
    assert diff.stat(files)['added'] == len(value.splitlines())


def bound(tmp_path, provider, records):
    transcript = tmp_path / 'bound.jsonl'
    transcript.write_bytes(b''.join(map(line, records)))
    return dict(name='BoundAgent', program='claude-code' if provider == 'claude' else 'codex',
                history_binding='bound', transcript_path=str(transcript), history_session_id='synthetic')


@pytest.mark.parametrize('changed', ['call', 'result', 'inode', 'binding'])
def test_diff_ref_rechecks_both_records_even_when_the_result_arrives_by_itself(tmp_path, changed):
    records = claude_records()
    row = bound(tmp_path, 'claude', records)
    store = ReferenceStore()
    with open_reader(row) as stream:
        events = stream.read_page(limit=1)['events']
        assert len(events) == 1 and events[0]['step']['phase'] == 'result'
        store.decorate_all(row, stream, events)
    step = events[0]['step']
    assert step['diff_stat'] == dict(added=1, removed=1, new_file=False)
    ref = step['diff_ref']
    assert 'before' not in json.dumps(step) and 'after' not in json.dumps(step)
    assert store.read_step_diff(ref, row)['hunks'][0]['lines'][1]['text'] == 'after'
    with pytest.raises(PreviewUnavailable, match='reference_expired'):
        store.read(ref, row)
    path = Path(row['transcript_path'])
    if changed in {'call', 'result'}:
        anchor = b'before' if changed == 'call' else b'Applied'
        path.write_bytes(path.read_bytes().replace(anchor, b'x' * len(anchor)))
    elif changed == 'inode':
        other = tmp_path / 'replacement.jsonl'
        other.write_bytes(path.read_bytes())
        other.replace(path)
    else:
        row = dict(row, mail_agent_id=17)
    with pytest.raises(PreviewUnavailable, match='reference_expired'):
        store.read_step_diff(ref, row)


def test_lazy_diff_route_exposes_only_the_selected_record(tmp_path, monkeypatch):
    value = '<a onclick="never()">&inert</a>'
    request = dict(type='response_item', payload=dict(type='custom_tool_call', name='apply_patch',
                   input='*** Begin Patch\n*** Add File: cache.py\n+PROPOSED_TEXT\n*** End Patch'))
    row = bound(tmp_path, 'codex', [
        request,
        codex_record({PATH: dict(type='add', content=value)}),
    ])
    calls = []

    async def bound_row(_request, name, not_before=None):
        calls.append(name)
        return row

    monkeypatch.setattr(backend, 'conversation_bound_row', bound_row)

    async def main():
        app = web.Application(middlewares=[backend.own_page_only, backend.json_writes_only])
        app[backend.HTTP_SESSION_KEY] = object()
        app[backend.TMUX_BIN_KEY] = object()
        app[backend.CONVERSATION_REFERENCES_KEY] = ReferenceStore()
        app.router.add_get('/telemetry/conversation', backend.serve_conversation)
        app.router.add_get('/telemetry/conversation/diff', backend.serve_conversation_diff)
        runner, origin = await start(app)
        try:
            async with ClientSession() as browser:
                async with browser.get(origin+'/telemetry/conversation?agent=BoundAgent') as received:
                    assert received.status == 200
                    page = await received.json()
                    assert 'inert' not in json.dumps(page)
                    previews = [event for event in page['events'] if event.get('diff')]
                    assert len(previews) == 1
                    assert '+PROPOSED_TEXT' in previews[0]['diff']
                    assert previews[0]['diff_status'] == 'Recorded edit request · outcome unconfirmed'
                    assert 'diff_ref' not in previews[0].get('step', {})
                    steps = [event['step'] for event in page['events'] if event.get('step')]
                    assert len(steps) == 1
                    assert steps[0]['diff_stat'] == dict(added=1, removed=0, new_file=True)
                    ref = steps[0]['diff_ref']
                    assert re.fullmatch(r'[A-Za-z0-9_-]{32}', ref)
                assert calls == ['BoundAgent'] * 2
                async with browser.get(origin+'/telemetry/conversation/diff?ref='+ref) as received:
                    assert received.status == 200 and received.headers['Cache-Control'] == 'no-store'
                    payload = await received.json()
                    assert set(payload) == {'ok','path','new_file','hunks','truncated'}
                    assert payload['hunks'][0]['lines'] == [dict(op='+', text=value)]
                assert calls == ['BoundAgent'] * 4
                async with browser.get(origin+'/telemetry/conversation/diff?ref='+ref, headers={
                        'Origin': 'https://example.test'}) as received:
                    assert received.status == 403
                async with browser.get(origin+'/telemetry/conversation/diff?ref='+ref+'&path=cache.py') as received:
                    assert received.status == 400
                    assert (await received.json())['error'] == 'invalid_query'
                async with browser.get(origin+'/telemetry/conversation/diff?ref='+'z'*32) as received:
                    assert received.status == 400
                    assert (await received.json())['error'] == 'reference_expired'
        finally:
            await runner.cleanup()

    asyncio.run(main())
