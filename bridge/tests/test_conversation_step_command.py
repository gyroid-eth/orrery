"""Native command records and the bound, on-demand Reader endpoint."""
import asyncio
import json
from pathlib import Path
import re

from aiohttp import ClientSession, web
import pytest

from test_conversation_history import start
from test_conversation_step_diff import bound, codex_record as codex_edit, PATH
import conversation_step_command as command
from conversation_history import open_reader
from conversation_preview import PreviewUnavailable, ReferenceStore
import orrery_backend as backend


def claude_records(content, metadata=None, *, tool='Bash', error=False, cmd='printf SHELL_INPUT'):
    return [
        dict(type='assistant', sessionId='synthetic', message=dict(role='assistant', content=[
            dict(type='tool_use', name=tool, id='shell-call', input=dict(command=cmd))
        ])),
        dict(type='user', sessionId='synthetic', toolUseResult=metadata, message=dict(role='user', content=[
            dict(type='tool_result', tool_use_id='shell-call', is_error=error, content=content)
        ])),
    ]


def codex_record(exit_code, output, cmd=None, *, ident='shell-one', source='unified_exec_startup'):
    return dict(type='event_msg', payload=dict(type='item_completed', item=dict(
        type='CommandExecution', id=ident, status='failed' if exit_code else 'completed',
        command=['/bin/zsh', '-lc', 'printf SHELL_INPUT'] if cmd is None else cmd,
        aggregated_output=output, exit_code=exit_code, source=source)))


def projection(tmp_path, provider, records, **page):
    row = bound(tmp_path, provider, records)
    store = ReferenceStore()
    with open_reader(row) as stream:
        events = stream.read_page(**page)['events']
        store.decorate_all(row, stream, events)
    return row, store, events


@pytest.mark.parametrize('content,metadata,error,code,output,status', [
    ('SHELL_OUTPUT', dict(stdout='SHELL_OUTPUT', stderr='diagnostic', interrupted=False),
     False, 0, 'SHELL_OUTPUT\ndiagnostic', 'done'),
    ('Exit code 23\n\nSHELL_OUTPUT', 'native error', True, 23, 'SHELL_OUTPUT', 'failed'),
    ('SHELL_OUTPUT', dict(stdout='SHELL_OUTPUT', stderr='', interrupted=True),
     False, None, 'SHELL_OUTPUT', 'failed'),
    ('[Request interrupted by user for tool use]', None, True, None,
     '[Request interrupted by user for tool use]', 'failed'),
    ('Exit code 23\nSHELL_OUTPUT', None, False, None, 'Exit code 23\nSHELL_OUTPUT', 'done'),
    ('SHELL_OUTPUT', dict(stdout='SHELL_OUTPUT', stderr='', interrupted=False, backgroundTaskId='fixture'),
     False, None, 'SHELL_OUTPUT', 'done'),
])
def test_claude_native_result_even_when_call_is_on_an_older_page(
        tmp_path, content, metadata, error, code, output, status):
    row, store, events = projection(tmp_path, 'claude', claude_records(content, metadata, error=error), limit=1)
    step = events[0]['step']
    assert (step['phase'], step['status']) == ('result', status)
    assert step.get('exit_code') == code
    assert ('exit_code' in step) == (code is not None)
    assert 'SHELL_' not in json.dumps(events)
    assert store.read_step_command(step['detail_ref'], row) == dict(
        ok=True, kind='command', command='printf SHELL_INPUT', output=output, exit_code=code, truncated=False)


@pytest.mark.parametrize('tool', ['BashOutput', 'KillShell', 'Read'])
def test_other_claude_tools_have_no_command_reference(tmp_path, tool):
    _, _, events = projection(tmp_path, 'claude', claude_records('example', tool=tool))
    assert all('detail_ref' not in event.get('step', {}) for event in events)


@pytest.mark.parametrize('code,cmd,expected,summary,source', [
    (0, ['/bin/bash', '-lc', 'pytest -k SHELL_INPUT'], 'pytest -k SHELL_INPUT', 'pytest', 'unified_exec_startup'),
    (7, ['printf', 'SHELL INPUT'], "printf 'SHELL INPUT'", 'printf', 'user_shell'),
    (None, 'printf SHELL_INPUT', 'printf SHELL_INPUT', '', 'unified_exec_startup'),
])
def test_codex_completion_publishes_only_an_executable_summary_and_exit_status(
        tmp_path, code, cmd, expected, summary, source):
    row, store, events = projection(tmp_path, 'codex', [codex_record(code, 'SHELL_OUTPUT', cmd, source=source)])
    step = events[0]['step']
    assert step['tool'] == 'Shell' and step['detail'] == summary
    assert step.get('exit_code') == code
    assert re.fullmatch(r'[A-Za-z0-9_-]{32}', step['detail_ref'])
    assert 'SHELL' not in json.dumps(events)
    detail = store.read_step_command(step['detail_ref'], row)
    assert (detail['command'], detail['output'], detail['exit_code']) == (expected, 'SHELL_OUTPUT', code)


def test_ansi_color_terminal_links_and_control_strings_are_removed():
    raw = ('\x1b[32mgreen\x1b[0m\r\n\x9b31mnext\x9b0m\t'
           '\x1b]8;;https://fixture.test\x1b\\click\x1b]8;;\x07'
           '\x1bPdiscard\x1b\\\x1b(0\x00')
    payload = command.detail(command.Command('printf a', raw, 0))
    assert payload['output'] == 'green\nnext\tclick'
    assert payload['truncated'] is False


def test_command_and_output_limits_are_independent_utf8_bounds():
    limited = command.detail(command.Command('€' * 4000, 'あ' * 25000, 0))
    assert limited['truncated']
    assert len(limited['command'].encode()) == 8190
    assert len(limited['output'].encode()) == 65535
    limited = command.detail(command.Command('true', 'row\n' * 401, 0))
    assert limited['truncated'] and len(limited['output'].splitlines()) == 400
    exact = command.detail(command.Command('true', 'row\n' * 400, 0))
    assert not exact['truncated'] and len(exact['output'].splitlines()) == 400


def test_no_persisted_output_path_is_read_and_image_data_is_omitted(tmp_path):
    path = tmp_path / 'persisted'
    path.write_text('MUST_NOT_READ')
    row, store, events = projection(tmp_path, 'claude', claude_records('IMAGE_BYTES', dict(isImage=True)))
    assert store.read_step_command(events[-1]['step']['detail_ref'], row)['output'] == ''
    row, store, events = projection(tmp_path, 'claude', claude_records('recorded sample', dict(
        stdout='recorded sample', interrupted=False, persistedOutputPath=str(path))))
    payload = store.read_step_command(events[-1]['step']['detail_ref'], row)
    assert payload['truncated'] and payload['output'] == 'recorded sample'


@pytest.mark.parametrize('changed', ['call', 'result', 'owner', 'inode'])
def test_reference_is_tied_to_its_agent_and_the_two_claude_records(tmp_path, changed):
    row, store, events = projection(tmp_path, 'claude', claude_records('SHELL_OUTPUT'))
    ref = events[-1]['step']['detail_ref']
    path = Path(row['transcript_path'])
    if changed == 'owner':
        row = dict(row, name='OtherFixture')
    elif changed == 'inode':
        replacement = tmp_path / 'replacement'
        replacement.write_bytes(path.read_bytes())
        replacement.replace(path)
    else:
        needle = b'SHELL_INPUT' if changed == 'call' else b'SHELL_OUTPUT'
        path.write_bytes(path.read_bytes().replace(needle, b'x' * len(needle)))
    with pytest.raises(PreviewUnavailable, match='reference_expired'):
        store.read_step_command(ref, row)


def test_detail_endpoint_returns_only_the_requested_command_and_checks_reference_type(tmp_path, monkeypatch):
    row = bound(tmp_path, 'codex', [
        codex_record(1, 'SHELL_OUTPUT'),
        codex_record(0, 'OTHER_OUTPUT', ident='shell-two'),
        codex_edit({PATH: dict(type='add', content='DIFF_OUTPUT')}),
    ])

    async def bound_row(_request, name, not_before=None):
        assert name == row['name']
        return row

    monkeypatch.setattr(backend, 'conversation_bound_row', bound_row)

    async def main():
        app = web.Application(middlewares=[backend.own_page_only])
        app[backend.HTTP_SESSION_KEY] = object()
        app[backend.TMUX_BIN_KEY] = object()
        app[backend.CONVERSATION_REFERENCES_KEY] = ReferenceStore()
        app.router.add_get('/telemetry/conversation', backend.serve_conversation)
        app.router.add_get('/telemetry/conversation/detail', backend.serve_conversation_detail)
        app.router.add_get('/telemetry/conversation/diff', backend.serve_conversation_diff)
        app.router.add_get('/telemetry/conversation/preview', backend.serve_conversation_preview)
        runner, origin = await start(app)
        try:
            async with ClientSession() as browser:
                async with browser.get(origin + '/telemetry/conversation?agent=BoundAgent') as response:
                    assert response.status == 200
                    page = await response.json()
                assert not any(value in json.dumps(page) for value in ('SHELL_INPUT','SHELL_OUTPUT','OTHER_OUTPUT','DIFF_OUTPUT'))
                first, _, edit = [event['step'] for event in page['events']]
                assert first['exit_code'] == 1
                ref = first['detail_ref']
                base = origin + '/telemetry/conversation/'
                async with browser.get(base + 'detail', params={'ref': ref}) as response:
                    assert response.status == 200 and response.headers['Cache-Control'] == 'no-store'
                    assert await response.json() == dict(ok=True, kind='command', command='printf SHELL_INPUT',
                                                        output='SHELL_OUTPUT', exit_code=1, truncated=False)
                for path, bad_ref in [('preview', ref), ('diff', ref), ('detail', edit['diff_ref']), ('detail', 'z' * 32)]:
                    async with browser.get(base + path, params={'ref': bad_ref}) as response:
                        assert response.status == 400 and (await response.json())['error'] == 'reference_expired'
                async with browser.get(base + 'detail', params={'ref': ref, 'path': '/fixture/file'}) as response:
                    assert response.status == 400 and (await response.json())['error'] == 'invalid_query'
                async with browser.get(base + 'detail', params={'ref': ref}, headers={'Origin': 'https://fixture.test'}) as response:
                    assert response.status == 403
        finally:
            await runner.cleanup()

    asyncio.run(main())
