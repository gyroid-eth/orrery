"""Synthetic compaction records never become human messages."""
import json
import pytest

from test_conversation_providers import claude, dsh, line, make_db, page, row
from conversation_history import MAX_TEXT, codex_event
from conversation_readers import normalize

PREFIX = ('This session is being continued from a previous conversation that ran out of context. '
          'The summary below covers generated fixture history.')


@pytest.mark.parametrize('blocks', [False, True])
def test_verified_human_queued_prompt_does_not_become_a_compaction(blocks):
    prompt = [dict(type='text', text=PREFIX)] if blocks else PREFIX
    item = dict(type='attachment', sessionId='synthetic-session', attachment=dict(
        type='queued_command', commandMode='prompt', isMeta=False,
        origin={'kind': 'human'}, prompt=prompt))
    out = normalize(item, 'claude', 'synthetic-session')
    assert len(out) == 1
    _, event = out[0]
    assert (event['kind'], event['role'], event['text']) == ('text', 'user', PREFIX)


@pytest.mark.parametrize('meta', [False, True])
@pytest.mark.parametrize('blocks', [False, True])
def test_claude_summary_flag_uses_a_system_row(tmp_path, meta, blocks):
    path = tmp_path / 'fixture.jsonl'
    text = 'Generated summary without any recognizable prefix.'
    content = [dict(type='text', text=text)] if blocks else text
    path.write_bytes(line(claude('user', content, isCompactSummary=True, isMeta=meta,
                                 isVisibleInTranscriptOnly=True)))
    event = page(row(path, 'claude-code'))['events'][0]
    assert (event['kind'], event['role'], event['text']) == ('system', 'system', 'Context compacted')
    assert event['system_detail'] == text


def test_only_unmarked_legacy_prefix_is_a_fallback(tmp_path):
    path = tmp_path / 'fixture.jsonl'
    values = [claude('user', PREFIX), claude('user', PREFIX, origin={'kind': 'human'}),
              claude('user', PREFIX, isCompactSummary=False),
              claude('user', PREFIX, isCompactSummary='true'), claude('user', 'Ordinary request.'),
              claude('user', 'Please quote this: ' + PREFIX)]
    path.write_bytes(b''.join(line(v) for v in values))
    events = page(row(path, 'claude-code'))['events']
    assert [e['role'] for e in events] == ['system', 'user', 'user', 'user', 'user', 'user']
    assert events[0]['system_detail'] == PREFIX


@pytest.mark.parametrize('blocks', [False, True])
def test_summary_keeps_size_limits_and_session_sidechain_boundaries(tmp_path, blocks):
    path = tmp_path / 'fixture.jsonl'
    text = 'x' * (MAX_TEXT + 1)
    content = [dict(type='text', text=text)] if blocks else text
    path.write_bytes(line(claude('user', content, isCompactSummary=True)) +
                     line(claude('user', 'Hidden sidechain', isCompactSummary=True, isSidechain=True)) +
                     line(claude('assistant', 'Hidden metadata', isCompactSummary=True, isMeta=True)) +
                     line(dict(claude('user', 'Hidden other session', isCompactSummary=True), sessionId='foreign')))
    events = page(row(path, 'claude-code'))['events']
    assert len(events) == 1 and events[0]['truncated']
    assert len(events[0]['system_detail']) == MAX_TEXT


def test_multiple_summary_blocks_still_make_one_system_row(tmp_path):
    path = tmp_path / 'fixture.jsonl'
    path.write_bytes(line(claude('user', [dict(type='text', text='Generated first section.'),
                                         dict(type='text', text='Generated second section.')], isCompactSummary=True)))
    events = page(row(path, 'claude-code'))['events']
    assert len(events) == 1 and events[0]['role'] == 'system'
    assert events[0]['system_detail'] == 'Generated first section.\nGenerated second section.'


@pytest.mark.parametrize('message', ['Generated readable summary.', ''])
def test_codex_compacted_marker_has_only_readable_summary(tmp_path, message):
    path = tmp_path / 'rollout.jsonl'
    path.write_bytes(line(dict(type='compacted', timestamp='2026-11-09T00:00:00Z', payload=dict(
        message=message, replacement_history=[dict(type='compaction', encrypted_content='HIDDEN_ENCRYPTED'),
                                             dict(type='message', role='user', content='HIDDEN_REPLACEMENT')]))))
    event = page(row(path, 'codex-cli'))['events'][0]
    assert (event['kind'], event['role'], event['text']) == ('system', 'system', 'Context compacted')
    assert event['system_detail'] == (message or 'The provider did not record a readable compaction summary.')
    assert 'HIDDEN' not in str(event)


def test_codex_compaction_preserves_paging_and_normal_human_text(tmp_path):
    path = tmp_path / 'rollout.jsonl'
    def user(text):
        return line(dict(type='response_item', payload=dict(type='message', role='user', content=text)))
    path.write_bytes(user('Before') + line(dict(type='compacted', payload=dict(message='Generated summary'))) + user('After'))
    current = page(row(path, 'codex-cli'), limit=1)
    events = current['events']
    while current['has_older']:
        current = page(row(path, 'codex-cli'), before=current['before'], limit=1)
        events = current['events'] + events
    assert [e['role'] for e in events] == ['user', 'system', 'user']
    assert len({e['id'] for e in events}) == 3


def test_dsh_projects_the_successful_append_end_without_summary_or_failure(tmp_path):
    path = tmp_path / 'fixture.jsonl'
    lifecycle = dict(compactionId='fixture-compaction', turn=None)
    prompt = dsh('user/message', dict(source=dict(kind='user'), content='Generated prompt'))
    path.write_bytes(line(dict(type='session', version=4, id='fixture-session'))+line(prompt))
    binding = row(path, 'dsh')
    before = page(binding)['after']
    records = [dsh('compaction/start', lifecycle, 2), dsh('compaction/summary', dict(lifecycle, summary='PRIVATE_SUMMARY'), 3),
               dict(dsh('user/message', dict(source=dict(kind='compact-checkpoint'), content='PRIVATE_CHECKPOINT'), 4),
                    surfaceOp=dict(op='replace', startSeq=1, endSeq=1)),
               dsh('compaction/end', lifecycle, 5), dsh('compaction/end', dict(lifecycle, error='PRIVATE_ERROR'), 6)]
    for item in records:
        if item['type'].startswith('compaction/'):
            item.pop('surfaceOp')
    with path.open('ab') as f:
        f.write(b''.join(line(item) for item in records))
    event, = page(binding, after=before)['events']
    assert (event['kind'], event['role'], event['text']) == ('system', 'system', 'Context compacted')
    assert page(binding, limit=1)['events'] == [event]
    assert 'PRIVATE_' not in json.dumps(page(binding))


def test_hermes_snapshot_exposes_only_the_bound_active_summary_marker(tmp_path):
    path = tmp_path / 'state.db'
    db = make_db(path)
    rows = [
        (1,'fixture-session','user','PRIVATE_OLD',0,0,None,None),
        (2,'fixture-session','user','PRIVATE_SUMMARY',1,1,'hidden','{"model_only":true}'),
        (3,'fixture-session','assistant','Visible answer',1,0,None,None),
        (4,'fixture-session','user','PRIVATE_OTHER_HIDDEN',1,0,'hidden',None),
        (5,'foreign-session','user','PRIVATE_FOREIGN_SUMMARY',1,1,'hidden','{"model_only":true}'),
    ]
    db.executemany('''INSERT INTO messages
        (id,session_id,role,content,active,_compressed_summary,display_kind,display_metadata) VALUES(?,?,?,?,?,?,?,?)''', rows)
    db.commit();db.close()
    binding = row(path, 'hermes')
    result = page(binding)
    assert [(event['id'],event['kind'],event['text']) for event in result['events']] == [
        ('2:0:0','system','Context compacted'),('3:0:0','text','Visible answer')]
    assert 'PRIVATE_' not in json.dumps(result)
    assert page(binding, after=result['after'])['events'] == result['events']


def test_hermes_rotation_marks_the_bound_parent_without_reading_the_successor(tmp_path):
    path = tmp_path / 'state.db'
    db = make_db(path)
    db.executescript("""ALTER TABLE sessions ADD COLUMN ended_at REAL;
        ALTER TABLE sessions ADD COLUMN end_reason TEXT;
        UPDATE sessions SET ended_at=1793775600,end_reason='compression' WHERE id='fixture-session';
        INSERT INTO messages (id,session_id,role,content) VALUES
            (1,'fixture-session','user','Visible parent prompt'),
            (2,'foreign-session','user','PRIVATE_SUCCESSOR');""")
    db.commit();db.close()
    result = page(row(path, 'hermes'))
    assert [event['text'] for event in result['events']] == ['Visible parent prompt','Context compacted']
    assert result['events'][-1]['ts'] == '2026-11-04T07:00:00Z'


@pytest.mark.parametrize('bad_type', [[], {}])
def test_non_string_native_record_type_is_ignored(tmp_path, bad_type):
    raw = json.dumps(dict(type=bad_type, payload={})).encode()
    assert codex_event(raw, 0) is None
    path = tmp_path / 'rollout.jsonl'
    path.write_bytes(raw + b'\n' + line(dict(type='response_item', payload=dict(
        type='message', role='user', content='Readable after malformed record.'))))
    events = page(row(path, 'codex-cli'))['events']
    assert [(event['role'], event['text']) for event in events] == [('user', 'Readable after malformed record.')]
