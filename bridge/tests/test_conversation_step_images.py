"""Image steps use the same record-bound preview as show_files."""

import json
from contextlib import closing

import pytest
from PIL import Image

from conversation_preview import PreviewUnavailable, ReferenceStore
from test_conversation_antigravity import SID, step as agy_step
from test_conversation_providers import claude, dsh, history, line, make_db, row
from test_conversation_steps import native


def recorded_image(tmp_path, provider, value, *, failed=False):
    cwd = tmp_path / 'workspace'
    cwd.mkdir(exist_ok=True)
    transcript = cwd / 'record.jsonl'
    if provider == 'codex':
        transcript.write_bytes(
            line(dict(type='session_meta', payload=dict(cwd=str(cwd))))
            + line(native('ImageView', path=value, status='failed' if failed else 'completed')))
    elif provider == 'claude-code':
        transcript.write_bytes(line(claude('user', 'Inspect the fixture.', cwd=str(cwd)))
            + line(claude('assistant', [dict(type='tool_use', name='Read', id='call', input={'file_path': value})]))
            + line(claude('user', [dict(type='tool_result', tool_use_id='call', is_error=failed)])))
    elif provider == 'dsh':
        transcript.write_bytes(line(dict(type='session', version=4, id='fixture-session', cwd=str(cwd)))
            + line(dsh('tool/call', dict(name='read_image', callId='call', arguments={'file_path': value})))
            + line(dsh('tool/result', dict(message=dict(toolCallId='call', isError=failed)), seq=2)))
    elif provider == 'hermes':
        transcript = cwd / 'state.db'
        with closing(make_db(transcript)) as db, db:
            db.execute('UPDATE sessions SET cwd=?', (str(cwd),))
            calls = [dict(id='call', function=dict(name='vision_analyze', arguments=json.dumps({'image_url': value})))]
            db.execute("INSERT INTO messages(id,session_id,role,tool_calls,timestamp) VALUES(1,'fixture-session','assistant',?,1)",
                       (json.dumps(calls),))
            db.execute("INSERT INTO messages(id,session_id,role,tool_call_id,tool_name,content,timestamp) VALUES(2,'fixture-session','tool','call','vision_analyze',?,2)",
                       (json.dumps({'success': not failed}),))
    elif provider == 'antigravity':
        transcript = cwd / 'antigravity-cli' / 'brain' / SID / '.system_generated/logs/transcript.jsonl'
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_bytes(line(agy_step(0, 'PLANNER_RESPONSE', 'MODEL',
            tool_calls=[dict(name='view_file', args={'AbsolutePath': value})])))
        return dict(row(transcript, provider, SID), history_workspace=str(cwd))
    return row(transcript, provider)


def decorate(bound):
    store = ReferenceStore()
    with history.open_reader(bound) as reader:
        events = reader.read_page()['events']
        store.decorate_all(bound, reader, events)
    return store, events


@pytest.mark.parametrize('provider', ['codex', 'claude-code', 'dsh', 'hermes', 'antigravity'])
@pytest.mark.parametrize('absolute', [False, True], ids=['relative-to-cwd', 'absolute-outside-cwd'])
def test_native_image_step_opens_in_the_existing_preview(tmp_path, provider, absolute):
    image = tmp_path / ('' if absolute else 'workspace') / 'diagram.png'
    image.parent.mkdir(exist_ok=True)
    Image.new('RGB', (32, 18), 'teal').save(image)
    value = str(image) if absolute else './diagram.png'
    bound = recorded_image(tmp_path, provider, value)
    store, events = decorate(bound)
    call = next(event for event in events if event['kind'] == 'tool')
    preview = call['step']['image']
    assert preview == {'id': preview['id'], 'label': 'diagram.png', 'kind': 'image'}
    assert call['step']['detail'] == 'diagram.png'
    assert str(image.parent) not in json.dumps(call)
    result = store.read(preview['id'], bound, mobile=True)
    assert (result['kind'], result['width'], result['height']) == ('image', 32, 18)
    with pytest.raises(PreviewUnavailable, match='reference_expired'):
        store.read(preview['id'], dict(bound, name='OtherAgent'))


@pytest.mark.parametrize('value', ['notes.txt', 'https://example.invalid/diagram.png',
                                  'data:image/png;base64,diagram.png', '../diagram.png', './link.png'])
def test_preview_grants_only_local_supported_regular_image_paths(tmp_path, value):
    bound = recorded_image(tmp_path, 'codex', value)
    image = tmp_path / 'diagram.png'
    Image.new('RGB', (32, 18), 'teal').save(image)
    (tmp_path / 'workspace' / 'link.png').symlink_to(image)
    _, events = decorate(bound)
    assert 'image' not in events[0]['step']


def test_failed_codex_image_has_no_preview_and_editing_the_record_expires_the_reference(tmp_path):
    bound = recorded_image(tmp_path, 'codex', './diagram.png', failed=True)
    _, events = decorate(bound)
    assert 'image' not in events[0]['step']
    Image.new('RGB', (32, 18), 'teal').save(tmp_path / 'workspace' / 'diagram.png')
    bound = recorded_image(tmp_path, 'codex', './diagram.png')
    store, events = decorate(bound)
    ref = events[0]['step']['image']['id']
    recorded_image(tmp_path, 'codex', './another.png')
    with pytest.raises(PreviewUnavailable, match='reference_expired'):
        store.read(ref, bound)
