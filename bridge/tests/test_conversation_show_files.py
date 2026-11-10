"""ORRERY Mail's show_files call becomes preview chips, in each harness's recorded form."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from conversation_artifacts import extract_artifacts  # noqa: E402
from conversation_readers import artifact_item  # noqa: E402
from test_conversation_preview import call, setup  # noqa: E402

PATHS = ['docs/report.md', 'figure.png']


def claude(name='mcp__orrery-mail__show_files', value=None):
    item = {'message': {'content': [{'type': 'tool_use', 'name': name, 'input': value or {'paths': PATHS}}]}}
    return extract_artifacts(artifact_item(item, 'claude', 0))


# The recorded names follow each harness's own naming code:
# - dsh (@deepseek-ai/dsh-mcp-client 0.2.1-rc.2, publicToolName): mcp__<server>__<tool>,
#   with characters outside [A-Za-z0-9_-] replaced, so ORRERY's server "orrery-mail"
#   keeps its hyphen: mcp__orrery-mail__show_files.
# - Hermes (tools/mcp_tool_schema.py, mcp_prefixed_tool_name): the server is cut to
#   [A-Za-z0-9_], so mcp__orrery_mail__show_files.
# - Codex: the recorded exec calls tools.mcp__orrery_mail__<tool>(...).
def dsh(name='mcp__orrery-mail__show_files', value=None):
    item = {'type': 'tool/call', 'data': {'name': name, 'arguments': value or {'paths': PATHS}}}
    return extract_artifacts(artifact_item(item, 'dsh', 0))


def hermes(name='mcp__orrery_mail__show_files', value=None):
    item = {'tool_calls': [{'function': {'name': name, 'arguments': json.dumps(value or {'paths': PATHS})}}]}
    return extract_artifacts(artifact_item(item, 'hermes', 1))


def codex_function(name='mcp__orrery_mail__show_files', value=None):
    return extract_artifacts(call(name, value or {'paths': PATHS}))


def codex_exec(name='mcp__orrery_mail__show_files', value=None):
    return extract_artifacts(call('exec', input='await tools.' + name + '(' + json.dumps(value or {'paths': PATHS}) + ');'))


FORMS = [claude, dsh, hermes, codex_function, codex_exec]


@pytest.mark.parametrize('form', FORMS, ids=lambda form: form.__name__)
def test_each_recorded_form_names_the_paths(form):
    assert form()['paths'] == PATHS
    assert form()['shown_paths'] == ([] if form is codex_exec else PATHS)


@pytest.mark.parametrize('form', FORMS, ids=lambda form: form.__name__)
@pytest.mark.parametrize('name', ['mcp__other__show_files', 'show_files', 'mcp__orrery-mail__show_filesx',
                                  'mcp__orrery_mail__send_message'])
def test_another_tool_or_server_grants_nothing(form, name):
    if form is codex_exec and not name.startswith('mcp__orrery'):
        return  # an unknown tools.X is not parsed at all
    assert form(name=name)['paths'] == []


@pytest.mark.parametrize('value', [{'paths': 'docs/report.md'}, {'paths': [7, None]}, {'path': 'a.md'},
                                   {'paths': ['https://example.com/x.png', '~/a.md', 'a\nb']}])
def test_malformed_paths_grant_nothing(value):
    assert claude(value=value)['paths'] == []


def test_at_most_24_paths():
    assert len(claude(value={'paths': [f'f{n}.md' for n in range(40)]})['paths']) == 24


def test_a_shown_text_file_opens_only_inside_the_working_folder(tmp_path):
    (tmp_path / 'report.md').write_text('# Report\n')
    outside = tmp_path.parent / (tmp_path.name + '-outside.md')
    outside.write_text('# Elsewhere\n')
    store, row, event = setup(tmp_path, call('mcp__orrery_mail__show_files', {'paths': ['report.md', str(outside)]}))
    assert [ref['label'] for ref in event['references']] == ['report.md']
    assert store.read(event['references'][0]['id'], row)['text'] == '# Report\n'
