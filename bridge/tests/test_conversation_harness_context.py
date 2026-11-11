"""Source shapes observed in native dsh timelines and Hermes SQLite records."""
import json
import sqlite3

import pytest

from test_conversation_providers import dsh, line, make_db, page, row

CONTEXT = '<environment_context>Generated workspace context.</environment_context>'
MAIL = ('ORRERY Mail notification: message from FixturePeer [normal]: Check. '
        'Body (complete; no inbox fetch needed): Generated check request.')


def dsh_records(path):
    records = [dict(type='session', version=4, id='fixture-session'),
               dsh('system/message', dict(message=dict(role='system', content='HIDDEN_SYSTEM')))]
    for source in ('agent-instructions', 'runtime-context', 'skill-catalog', 'time-context',
                   'tool-jobs', 'compact-checkpoint', 'skill-invocation'):
        records.append(dsh('user/message', dict(role='user', source=dict(kind=source),
                                               content=[dict(type='text', text='HIDDEN_' + source)])))
    records.extend(dsh('user/message', dict(role='user', source=dict(kind='user'),
                                           content=[dict(type='text', text=text)])) for text in (CONTEXT, MAIL))
    path.write_bytes(b''.join(line(record) for record in records))


def hermes_records(path, kind='process_complete'):
    con = make_db(path)
    for n, role, text, display, metadata in [
        (1, 'system', 'HIDDEN_SYSTEM', None, None),
        (2, 'user', 'HIDDEN_CONTEXT', 'hidden', None),
        (3, 'user', 'HIDDEN_MERGED_CONTEXT', None, dict(model_only=True)),
        (4, 'user', 'Generated native notification.', kind, dict(display_text='Generated update')),
        (5, 'user', CONTEXT, None, None),
        (6, 'user', MAIL, None, None),
    ]:
        con.execute('INSERT INTO messages(id,session_id,role,content,display_kind,display_metadata,timestamp) '
                    'VALUES(?,?,?,?,?,?,1)',
                    (n, 'fixture-session', role, text, display, json.dumps(metadata) if metadata else None))
    con.commit()
    con.close()


def test_dsh_real_injection_sources_are_excluded_but_human_text_and_mail_remain(tmp_path):
    path = tmp_path / 'session.v4.jsonl'
    dsh_records(path)
    events = page(row(path, 'dsh'))['events']
    assert [(e['kind'], e['role']) for e in events] == [('text', 'user'), ('mail', 'user')]
    assert events[0]['text'] == CONTEXT
    assert events[1]['mail'][0]['sender'] == 'FixturePeer'
    assert 'HIDDEN' not in json.dumps(events)


@pytest.mark.parametrize('kind', ['model_switch', 'personality_switch', 'async_delegation_complete',
                                 'process_complete', 'auto_continue'])
def test_hermes_native_timeline_markers_are_system_not_human(tmp_path, kind):
    path = tmp_path / 'state.db'
    hermes_records(path, kind)
    events = page(row(path, 'hermes'))['events']
    assert [(e['kind'], e['role']) for e in events] == [('system', 'system'), ('text', 'user'), ('mail', 'user')]
    assert events[0]['text'] == 'System notice'
    assert events[0]['system_detail'] == 'Generated native notification.'
    assert events[1]['text'] == CONTEXT
    assert 'HIDDEN' not in json.dumps(events)


@pytest.mark.parametrize('kind', ['steer', 'skill_invocation', 'unknown_future_kind', None])
def test_hermes_human_and_unknown_display_kinds_remain_user_input(tmp_path, kind):
    path = tmp_path / 'state.db'
    hermes_records(path, kind)
    event = page(row(path, 'hermes'))['events'][0]
    assert (event['kind'], event['role'], event['text']) == ('text', 'user', 'Generated native notification.')


def test_hermes_marker_only_update_changes_the_snapshot_and_preserves_record_lookup(tmp_path):
    import conversation_history as history

    path = tmp_path / 'state.db'
    hermes_records(path, None)
    bound = row(path, 'hermes')
    first = page(bound)
    with history.open_reader(bound) as reader:
        fingerprint = reader.session_fingerprint()
    con = sqlite3.connect(path)
    con.execute("UPDATE messages SET display_kind='process_complete' WHERE id=4")
    con.commit()
    con.close()
    changed = page(bound, after=first['after'])
    assert changed['events'][0]['kind'] == 'system'
    with history.open_reader(bound) as reader:
        assert reader.session_fingerprint() != fingerprint
        item, _, indexes = reader.record((4, 0))
        assert item['display_kind'] == 'process_complete'
        assert indexes == {0}
