"""Synthetic compaction records never become human messages."""
import pytest

from test_conversation_providers import claude, line, page, row
from conversation_history import MAX_TEXT

PREFIX = ('This session is being continued from a previous conversation that ran out of context. '
          'The summary below covers generated fixture history.')


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
