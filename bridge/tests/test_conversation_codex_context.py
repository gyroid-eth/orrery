"""Native Codex context markers must not impersonate the human speaker."""
import pytest

from test_conversation_providers import line, page, row
import conversation_history as history


ENVIRONMENT = '<environment_context>\n<cwd>/workspace/project</cwd>\n</environment_context>'
INSTRUCTIONS = '# AGENTS.md instructions\n\n<INSTRUCTIONS>\nUse the project guide.\n</INSTRUCTIONS>'


def message(texts, kinds=None, role='user'):
    payload = dict(type='message', role=role,
                   content=[dict(type='input_text', text=text) for text in texts])
    if kinds is not None:
        payload['internal_chat_message_metadata_passthrough'] = dict(content_item_kinds=kinds)
    return dict(type='response_item', timestamp='2026-11-11T01:00:00Z', payload=payload)


@pytest.mark.parametrize('texts,kinds', [
    ([ENVIRONMENT], ['environments.environment_context']),
    ([INSTRUCTIONS], ['agents_md.instructions']),
    ([INSTRUCTIONS, ENVIRONMENT], ['agents_md.instructions', 'environments.environment_context']),
    (['Generated workspace permissions.'], ['environments.environment_context']),
])
def test_native_injected_context_is_one_expandable_system_notice(tmp_path, texts, kinds):
    path = tmp_path / 'rollout.jsonl'
    path.write_bytes(line(message(texts, kinds)))
    event, = page(row(path, 'codex'))['events']
    assert (event['kind'], event['role'], event['text']) == ('system', 'system', 'System notice')
    assert event['system_detail'] == '\n'.join(texts)


@pytest.mark.parametrize('text', [ENVIRONMENT, INSTRUCTIONS,
                                      '<user_instructions>Literal instructions</user_instructions>'])
def test_native_human_marker_keeps_the_same_literal_context_text(tmp_path, text):
    path = tmp_path / 'rollout.jsonl'
    path.write_bytes(line(message([text], ['user.text'])))
    event, = page(row(path, 'codex'))['events']
    assert (event['kind'], event['role'], event['text']) == ('text', 'user', text)
    assert 'system_detail' not in event


@pytest.mark.parametrize('text', [ENVIRONMENT, INSTRUCTIONS,
                                      '<user_instructions>Generated instructions</user_instructions>'])
def test_older_rollout_uses_only_a_complete_leading_context_wrapper(tmp_path, text):
    path = tmp_path / 'rollout.jsonl'
    path.write_bytes(line(message([text])))
    event, = page(row(path, 'codex'))['events']
    assert (event['kind'], event['role']) == ('system', 'system')
    assert event['system_detail'] == text


@pytest.mark.parametrize('text', [
    'Please explain ' + ENVIRONMENT,
    '```xml\n' + ENVIRONMENT + '\n```',
    ENVIRONMENT + '\nPlease explain this example.',
    '<environment_context>an incomplete example',
    '# AGENTS.md instructions are useful. Please explain them.',
])
def test_context_examples_in_ordinary_unmarked_prompts_stay_human(tmp_path, text):
    path = tmp_path / 'rollout.jsonl'
    path.write_bytes(line(message([text])))
    event, = page(row(path, 'codex'))['events']
    assert (event['kind'], event['role'], event['text']) == ('text', 'user', text)


def test_mixed_native_blocks_leave_only_the_human_input_in_the_user_event(tmp_path):
    path = tmp_path / 'rollout.jsonl'
    path.write_bytes(line(message([ENVIRONMENT, 'Please check the build.', INSTRUCTIONS],
                                 ['environments.environment_context', 'user.text', 'agents_md.instructions'])))
    event, = page(row(path, 'codex'))['events']
    assert (event['kind'], event['role'], event['text']) == ('text', 'user', 'Please check the build.')


def test_unknown_native_source_is_not_guessed_to_be_injected(tmp_path):
    path = tmp_path / 'rollout.jsonl'
    path.write_bytes(line(message([ENVIRONMENT], ['new-source.text'])))
    event, = page(row(path, 'codex'))['events']
    assert (event['kind'], event['role'], event['text']) == ('text', 'user', ENVIRONMENT)


@pytest.mark.parametrize('kinds', [['user.text', 'user.text'], 'user.text', [None]])
def test_malformed_native_source_mapping_does_not_hide_a_literal_prompt(tmp_path, kinds):
    path = tmp_path / 'rollout.jsonl'
    path.write_bytes(line(message([ENVIRONMENT], kinds)))
    event, = page(row(path, 'codex'))['events']
    assert (event['kind'], event['role'], event['text']) == ('text', 'user', ENVIRONMENT)


def test_assistant_context_examples_are_not_reclassified(tmp_path):
    path = tmp_path / 'rollout.jsonl'
    path.write_bytes(line(message([ENVIRONMENT], role='assistant')))
    event, = page(row(path, 'codex'))['events']
    assert (event['kind'], event['role'], event['text']) == ('text', 'assistant', ENVIRONMENT)


def test_context_details_are_bounded_and_page_cursors_remain_record_based(tmp_path):
    path = tmp_path / 'rollout.jsonl'
    text = '<environment_context>' + 'x' * history.MAX_TEXT + '</environment_context>'
    path.write_bytes(line(message([text], ['environments.environment_context'])) +
                     line(message(['A real request.'], ['user.text'])))
    latest = page(row(path, 'codex'), limit=1)
    assert latest['events'][0]['text'] == 'A real request.'
    older = page(row(path, 'codex'), before=latest['before'], limit=1)
    event, = older['events']
    assert event['kind'] == 'system' and event['truncated']
    assert len(event['system_detail']) == history.MAX_TEXT
    assert event['id'] != latest['events'][0]['id']
    assert not older['has_older']
    assert page(row(path, 'codex'), after=latest['after'])['events'] == []


def test_conversation_http_api_keeps_the_system_kind_and_literal_human_text(tmp_path, monkeypatch):
    from test_conversation_unchanged import run

    path = tmp_path / 'rollout.jsonl'
    path.write_bytes(line(message([ENVIRONMENT], ['environments.environment_context'])) +
                     line(message([ENVIRONMENT], ['user.text'])))

    async def scenario(get, calls, reads):
        status, payload = await get()
        assert status == 200
        assert [(e['kind'], e['role']) for e in payload['events']] == [('system', 'system'), ('text', 'user')]
        assert payload['events'][0]['system_detail'] == ENVIRONMENT
        assert payload['events'][1]['text'] == ENVIRONMENT

    run(monkeypatch, row(path, 'codex'), scenario)
