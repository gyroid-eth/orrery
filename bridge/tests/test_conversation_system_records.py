"""Claude harness records are distinct from human prompts."""
from test_conversation_providers import claude, line, page, row

NOTICE = ('<task-notification><task-id>generated-task</task-id><tool-use-id>generated-call</tool-use-id>'
          '<output-file>/fixture/output.txt</output-file><status>completed</status>'
          '<summary>Background command "check" completed (exit code 0)</summary></task-notification>')


def test_harness_notification_has_a_compact_system_projection(tmp_path):
    path = tmp_path / 'fixture.jsonl'
    path.write_bytes(line(claude('user', NOTICE, promptSource='system', origin={'kind': 'task-notification'})))
    event = page(row(path, 'claude-code'))['events'][0]
    assert event['role'] == 'system'
    assert event['kind'] == 'system'
    assert event['text'] == 'Background task completed · check'
    assert event['system_detail'] == 'Background command "check" completed (exit code 0)\nStatus: completed\nOutput: /fixture/output.txt'
    assert 'generated-task' not in str(event) and 'generated-call' not in str(event)


def test_human_origin_wins_over_a_tag_and_plain_user_is_unchanged(tmp_path):
    path = tmp_path / 'fixture.jsonl'
    path.write_bytes(line(claude('user', NOTICE, origin={'kind': 'human'})) + line(claude('user', '**literal**')))
    events = page(row(path, 'claude-code'))['events']
    assert [e['role'] for e in events] == ['user', 'user']
    assert [e['text'] for e in events] == [NOTICE, '**literal**']


def test_older_notification_without_origin_and_system_reminder(tmp_path):
    path = tmp_path / 'fixture.jsonl'
    path.write_bytes(line(claude('user', NOTICE)) + line(claude('user', '<system-reminder>Generated reminder</system-reminder>')))
    events = page(row(path, 'claude-code'))['events']
    assert [e['role'] for e in events] == ['system', 'system']
    assert events[1]['text'] == 'System notice'
    assert events[1]['system_detail'] == 'Generated reminder'
