"""Explicit image delivery grants its recorded path, across native readers only."""
import base64
import io
import json
import os
import subprocess

import pytest
from PIL import Image, PngImagePlugin

from test_conversation_preview import call, setup, preview
from test_conversation_providers import claude, dsh, history, line, make_db, row
from conversation_preview import PreviewUnavailable, ReferenceStore


def completed_call(paths, server='orrery-mail'):
    # Codex 0.163 code mode's native event, with generated IDs and paths.
    return dict(type='event_msg', timestamp='2026-11-10T06:00:00Z', payload=dict(
        type='item_completed', thread_id='fixture-thread', turn_id='fixture-turn',
        started_at_ms=1794290400000, completed_at_ms=1794290400010,
        item=dict(type='McpToolCall', id='exec-fixture-call', server=server,
                  tool='show_files', arguments=dict(paths=paths), status='completed',
                  result=dict(content=[]), duration=dict(secs=0,nanos=10000000))))


def legacy_completed_call(paths, server='orrery-mail'):
    # McpToolCallEndEvent has a Rust Result and camelCase CallToolResult.
    return dict(type='event_msg', timestamp='2026-11-10T06:00:00Z', payload=dict(
        type='mcp_tool_call_end', call_id='fixture-call', turn_id='fixture-turn',
        invocation=dict(server=server, tool='show_files', arguments=dict(paths=paths)),
        duration=dict(secs=0, nanos=10000000), result={'Ok': dict(content=[], isError=False)}))


def native_delivery(work, paths, form, server='orrery-mail'):
    """Real reader formats; neither the event nor the browser supplies a grant."""
    name = 'SendUserFile' if form == 'send_user_file' else 'mcp__orrery_mail__show_files'
    if server == 'agentstack':
        name = 'mcp__agentstack__show_files'
    args = {'files' if form == 'send_user_file' else 'paths': paths}
    transcript = work / 'record.jsonl'
    if form in {'send_user_file', 'claude'}:
        if form == 'claude' and server == 'orrery-mail':
            name = 'mcp__orrery-mail__show_files'
        transcript.write_bytes(line(claude('user', 'Generated request', cwd=str(work))) +
            line(claude('assistant', [dict(type='tool_use', id='call', name=name, input=args)])))
        bound = row(transcript, 'claude-code')
    elif form == 'dsh':
        transcript.write_bytes(line(dict(type='session', version=4, id='fixture-session', cwd=str(work))) +
            line(dsh('tool/call', dict(name='mcp__orrery-mail__show_files' if server == 'orrery-mail' else name, arguments=args))))
        bound = row(transcript, 'dsh')
    elif form == 'hermes':
        transcript = work / 'state.db'
        con = make_db(transcript)
        con.execute('UPDATE sessions SET cwd=?', (str(work),))
        tools = [dict(id='call', type='function', function=dict(name=name, arguments=json.dumps(args)))]
        con.execute("INSERT INTO messages(id,session_id,role,tool_calls,timestamp) VALUES(1,'fixture-session','assistant',?,1)",
                    (json.dumps(tools),))
        con.commit()
        con.close()
        bound = row(transcript, 'hermes')
    else:
        item = (call('functions.exec', input='await tools.' + name + '(' + json.dumps(args) + ');')
                if form == 'codex_exec' else call(name, args))
        transcript.write_bytes(line(dict(type='session_meta', payload=dict(cwd=str(work)))) + line(item))
        if form in {'codex', 'codex_exec', 'codex_legacy'}:
            with transcript.open('ab') as stream:
                stream.write(line(legacy_completed_call(paths, server) if form == 'codex_legacy' else completed_call(paths, server)))
        bound = dict(row(transcript, 'codex'), native_session_id='fixture-session')
    store = ReferenceStore()
    with history.open_reader(bound) as reader:
        event = [e for e in reader.read_page()['events'] if e['kind'] == 'tool'][-1]
        store.decorate(bound, reader, event)
    return store, bound, event


FORMS = ['send_user_file', 'claude', 'dsh', 'hermes', 'codex', 'codex_exec', 'codex_legacy']


@pytest.mark.parametrize('form', FORMS[1:])
def test_agentstack_alias_uses_canonical_image_event_and_preview(tmp_path, form):
    work = tmp_path / 'work'
    work.mkdir()
    image = tmp_path / 'shown.png'
    Image.new('RGB', (24, 16), 'teal').save(image)
    store, bound, event = native_delivery(work, [str(image)], form, 'agentstack')
    assert event['text'] == 'mcp__orrery_mail__show_files'
    assert [ref['label'] for ref in event.get('references', [])] == ['shown.png']
    assert preview(store, bound, event)['kind'] == 'image'


@pytest.mark.parametrize('legacy', [False, True])
def test_agentstack_alias_never_grants_external_text(tmp_path, legacy):
    work = tmp_path / 'work'
    work.mkdir()
    note = tmp_path / 'note.txt'
    note.write_text('Outside the working folder')
    _, _, event = native_delivery(work, [str(note)], 'codex_legacy' if legacy else 'codex', 'agentstack')
    assert not event.get('references')


@pytest.mark.parametrize('form', FORMS)
def test_shown_external_png_opens_through_native_reader(tmp_path, form):
    work = tmp_path / 'work'
    work.mkdir()
    image = tmp_path / 'shown.png'
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('comment', 'Generated metadata is not delivered')
    Image.new('RGB', (24, 16), 'teal').save(image, pnginfo=metadata)
    store, bound, event = native_delivery(work, [str(image)], form)
    assert [r['label'] for r in event.get('references', [])] == ['shown.png']
    assert str(tmp_path) not in json.dumps(event)
    result = preview(store, bound, event)
    assert (result['kind'], result['mime'], result['width'], result['height']) == ('image', 'image/png', 24, 16)
    clean = Image.open(io.BytesIO(base64.b64decode(result['data'])))
    assert clean.getpixel((0, 0)) == (0, 128, 128, 255)
    assert not clean.info


@pytest.mark.parametrize('name', ['Read', 'view_image', 'Edit', 'mcp__other__show_files'])
def test_other_tools_do_not_grant_external_images(tmp_path, name):
    work = tmp_path / 'work'
    work.mkdir()
    image = tmp_path / 'read.png'
    Image.new('RGB', (8, 6)).save(image)
    _, _, event = setup(work, call(name, dict(path=str(image), file_path=str(image), paths=[str(image)])))
    assert not event.get('references')


@pytest.mark.parametrize('form', FORMS)
def test_delivery_never_grants_external_text_or_svg(tmp_path, form):
    work = tmp_path / 'work'
    work.mkdir()
    text, svg = tmp_path / 'note.txt', tmp_path / 'vector.svg'
    text.write_text('Generated text')
    svg.write_text('<svg/>')
    _, _, event = native_delivery(work, [str(text), str(svg)], form)
    assert not event.get('references')


@pytest.mark.parametrize('case', ['file_symlink', 'directory_symlink', 'traversal', 'control'])
def test_shown_external_path_guards_are_unchanged(tmp_path, case):
    work = tmp_path / 'work'
    work.mkdir()
    folder = tmp_path / 'images'
    folder.mkdir()
    image = folder / 'shown.png'
    Image.new('RGB', (8, 6)).save(image)
    if case == 'file_symlink':
        alias = tmp_path / 'alias.png'
        alias.symlink_to(image)
        value = str(alias)
    elif case == 'directory_symlink':
        alias = tmp_path / 'alias'
        alias.symlink_to(folder, target_is_directory=True)
        value = str(alias / image.name)
    elif case == 'traversal':
        value = '../images/shown.png'
    else:
        value = str(image) + '\n'
    _, _, event = setup(work, call('SendUserFile', dict(files=[value])))
    assert not event.get('references')


def test_shown_external_reference_rechecks_record_and_late_symlinks(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    image = tmp_path / 'shown.png'
    Image.new('RGB', (8, 6)).save(image)
    store, bound, event = setup(work, call('SendUserFile', dict(files=[str(image)])))
    assert event.get('references'), 'delivery must issue an external image reference'
    original = image.read_bytes()
    image.unlink()
    target = tmp_path / 'other.png'
    target.write_bytes(original)
    image.symlink_to(target)
    with pytest.raises(PreviewUnavailable):
        preview(store, bound, event)
    image.unlink()
    image.write_bytes(original)
    transcript = work / 'bound.jsonl'
    transcript.write_bytes(transcript.read_bytes().replace(b'SendUserFile', b'OtherTool___'))
    with pytest.raises(PreviewUnavailable, match='reference_expired'):
        preview(store, bound, event)


def test_static_wrapper_paths_keep_roots_and_deduplication(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    shown, read = work / 'shown.png', tmp_path / 'read.png'
    for image in (shown, read):
        Image.new('RGB', (8, 6)).save(image)
    js = ('tools.view_image(' + json.dumps(dict(path=str(read))) + ');' +
          'tools.view_image(' + json.dumps(dict(path=str(shown))) + ');' +
          'tools.mcp__orrery_mail__show_files(' + json.dumps(dict(paths=[str(shown)])) + ');')
    store, bound, event = setup(work, call('functions.exec', input=js))
    from conversation_artifacts import extract_artifacts
    assert not extract_artifacts(call('functions.exec', input=js))['shown_paths']
    assert [r['label'] for r in event.get('references', [])] == ['shown.png']
    assert preview(store, bound, event)['kind'] == 'image'


@pytest.mark.parametrize('case', ['pixels', 'bytes', 'invalid', 'hardlink'])
def test_shown_external_image_keeps_read_limits(tmp_path, case):
    work = tmp_path / 'work'
    work.mkdir()
    image = tmp_path / 'shown.png'
    Image.new('RGB', (8, 6)).save(image)
    if case == 'bytes':
        image.write_bytes(b'\0' * (8 * 1024 * 1024 + 1))
    elif case == 'invalid':
        image.write_text('<svg/>')
    elif case == 'hardlink':
        os.link(image, tmp_path / 'alias.png')
    store, bound, event = setup(work, call('SendUserFile', dict(files=[str(image)])),
                                max_pixels=10 if case == 'pixels' else 16_000_000)
    assert event.get('references')
    with pytest.raises(PreviewUnavailable):
        preview(store, bound, event)


@pytest.mark.parametrize('item', [
    call('SendUserFile', dict(files=[], caption='outside.png', paths=['outside.png'])),
    dict(type='response_item', payload=dict(type='function_call_output', name='SendUserFile',
         output='{"files":["outside.png"]}')),
    call('functions.exec', input='"tools.SendUserFile({files:[\'outside.png\']})";'),
])
def test_caption_result_and_quoted_call_cannot_grant(item):
    from conversation_artifacts import extract_artifacts
    result = extract_artifacts(item)
    assert not result['paths']
    assert not result.get('shown_paths')


@pytest.mark.parametrize('form', ['dead_branch', 'uncalled_function', 'html_comment'])
def test_unexecuted_wrapper_cannot_grant_external_image(tmp_path, form):
    work = tmp_path / 'work'
    work.mkdir()
    image = tmp_path / 'unshown.png'
    Image.new('RGB', (8, 6), 'teal').save(image)
    invocation = 'tools.mcp__orrery_mail__show_files(' + json.dumps(dict(paths=[str(image)])) + ');'
    source = {'dead_branch': 'if(false){' + invocation + '}',
              'uncalled_function': 'function example(){' + invocation + '}',
              'html_comment': '<!-- ' + invocation + '\n'}[form]
    program = ('let calls=0;const tools={mcp__orrery_mail__show_files:()=>{calls++}};\n' +
               source + '\nconsole.log(calls);')
    result = subprocess.run(['node', '-e', program], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == '0'
    _, _, event = setup(work, call('functions.exec', input=source))
    assert not event.get('references'), 'unexecuted source must not grant an external image'


@pytest.mark.parametrize('change', [dict(server='other'), dict(tool='send_message'),
    dict(type='AgentMessage'), dict(status='failed'), dict(status='in_progress'),
    dict(arguments='not structured'), dict(arguments=None)])
def test_only_known_completed_mcp_call_grants_paths(change):
    from conversation_artifacts import extract_artifacts
    event = completed_call(['outside.png'])
    event['payload']['item'].update(change)
    assert not extract_artifacts(event)['paths']
    assert history.codex_event(line(event), 0) is None


@pytest.mark.parametrize('legacy', [False, True])
def test_completed_call_grants_only_its_arguments_not_wrapper_or_result(tmp_path, legacy):
    work = tmp_path / 'work'
    work.mkdir()
    shown, unshown = tmp_path / 'shown.png', tmp_path / 'unshown.png'
    for image in [shown, unshown]:
        Image.new('RGB', (8, 6)).save(image)
    source = 'await tools.mcp__orrery_mail__show_files(' + json.dumps(dict(paths=[str(shown)])) + ');'
    source += 'if(false){tools.mcp__orrery_mail__show_files(' + json.dumps(dict(paths=[str(unshown)])) + ');}'
    completed = legacy_completed_call([str(shown)]) if legacy else completed_call([str(shown)])
    result = (completed['payload']['result']['Ok'] if legacy else completed['payload']['item']['result'])
    result.update(paths=[str(unshown)], secret='RESULT_MUST_STAY_HIDDEN')
    transcript = work / 'record.jsonl'
    header = dict(type='session_meta', payload=dict(cwd=str(work)))
    transcript.write_bytes(line(header) + line(call('functions.exec', input=source)) + line(completed))
    bound = dict(row(transcript, 'codex'), native_session_id='fixture-session')
    store = ReferenceStore()
    with history.open_reader(bound) as reader:
        events = reader.read_page()['events']
        store.decorate_all(bound, reader, events)
    assert len(events) == 2
    assert not events[0].get('references'), 'wrapper source is never external-image evidence'
    assert [r['label'] for r in events[1]['references']] == ['shown.png']
    assert store.read(events[1]['references'][0]['id'], bound)['kind'] == 'image'
    assert str(tmp_path) not in json.dumps(events) and 'RESULT_MUST_STAY_HIDDEN' not in json.dumps(events)
    # Incremental paging reaches the completion exactly once, independently
    # of whether the wrapper and the completion share a loaded page.
    first = history.read_codex_page(str(transcript), after=None, limit=1)
    previous = history.read_codex_page(str(transcript), before=first['before'], limit=1)
    forward = history.read_codex_page(str(transcript), after=previous['after'])
    assert [e['id'] for e in forward['events']] == [events[1]['id']]
    original = transcript.read_bytes()
    transcript.write_bytes(original.replace(b'"isError": false', b'"isError": true') if legacy else
        original.replace(b'"status": "completed"', b'"status": "failed___"'))
    with pytest.raises(PreviewUnavailable, match='reference_expired'):
        store.read(events[1]['references'][0]['id'], bound)


@pytest.mark.parametrize('server', ['orrery-mail', 'agentstack'])
@pytest.mark.parametrize('legacy', [False, True])
def test_native_call_and_completion_render_one_row_and_chip_across_polls(tmp_path, legacy, server):
    work = tmp_path / 'work'
    work.mkdir()
    image = tmp_path / 'shown.png'
    Image.new('RGB', (8, 6)).save(image)
    transcript = work / 'record.jsonl'
    native = call('mcp__' + server.replace('-', '_') + '__show_files', dict(paths=[str(image)]))
    native['payload']['call_id'] = 'fixture-call'
    completed = legacy_completed_call([str(image)], server) if legacy else completed_call([str(image)], server)
    if not legacy:
        completed['payload']['item']['id'] = 'fixture-call'
    transcript.write_bytes(line(dict(type='session_meta', payload=dict(cwd=str(work)))) + line(native))
    before = history.read_codex_page(str(transcript))
    with transcript.open('ab') as stream:
        stream.write(line(completed))
    bound = dict(row(transcript, 'codex'), native_session_id='fixture-session')
    store = ReferenceStore()
    with history.open_reader(bound) as reader:
        events = reader.read_page()['events']
        store.decorate_all(bound, reader, events)
    assert len(events) == 1, 'one native call must not also render its completion as a second row'
    assert [r['label'] for r in events[0]['references']] == ['shown.png']
    assert store.read(events[0]['references'][0]['id'], bound)['kind'] == 'image'
    after = history.read_codex_page(str(transcript), after=before['after'])
    assert len(before['events']) + len(after['events']) == 1
    assert after['events'][0]['id'] == events[0]['id']


@pytest.mark.parametrize('legacy', [False, True])
def test_same_arguments_in_two_native_calls_remain_two_deliveries(tmp_path, legacy):
    work = tmp_path / 'work'
    work.mkdir()
    image = tmp_path / 'shown.png'
    Image.new('RGB', (8, 6)).save(image)
    transcript = work / 'record.jsonl'
    records = [dict(type='session_meta', payload=dict(cwd=str(work)))]
    for call_id in ['first-call', 'second-call']:
        native = call('mcp__orrery_mail__show_files', dict(paths=[str(image)]))
        native['payload']['call_id'] = call_id
        completed = legacy_completed_call([str(image)]) if legacy else completed_call([str(image)])
        if legacy:
            completed['payload']['call_id'] = call_id
        else:
            completed['payload']['item']['id'] = call_id
        records.extend([native, completed])
    transcript.write_bytes(b''.join(line(item) for item in records))
    events = history.read_codex_page(str(transcript))['events']
    assert len(events) == 2
    assert len({e['id'] for e in events}) == 2


@pytest.mark.parametrize('server', ['orrery-mail', 'agentstack'])
def test_codex_delivery_without_completion_has_no_chip(tmp_path, server):
    work = tmp_path / 'work'
    work.mkdir()
    Image.new('RGB', (8, 6)).save(work / 'shown.png')
    transcript = work / 'record.jsonl'
    transcript.write_bytes(line(dict(type='session_meta', payload=dict(cwd=str(work)))) +
        line(call('mcp__' + server.replace('-', '_') + '__show_files', dict(paths=['shown.png']))))
    assert not history.read_codex_page(str(transcript))['events']


@pytest.mark.parametrize('server', ['orrery-mail', 'agentstack'])
@pytest.mark.parametrize('result', [
    {'Err': 'Failed'}, {'Ok': {'content': [], 'isError': True}},
    {'Ok': {'content': [], 'isError': 'false'}}, {'Ok': {'content': [], 'isError': 0}},
    {'Ok': {'content': [], 'is_error': True}}, {'Ok': {}}, {'Ok': None},
    {'Ok': {'content': []}, 'Err': 'ambiguous'}, {'content': [], 'isError': False},
    'tool result prose', None,
])
def test_legacy_failure_or_malformed_result_never_grants(result, server):
    from conversation_artifacts import extract_artifacts
    event = legacy_completed_call(['outside.png'], server)
    event['payload']['result'] = result
    assert not extract_artifacts(event)['paths']
    assert history.codex_event(line(event), 0) is None


@pytest.mark.parametrize('change', [dict(server='other'), dict(tool='send_message'),
    dict(arguments='{"paths":["outside.png"]}'), dict(arguments=None)])
def test_legacy_other_server_tool_or_nonstructured_args_never_grant(change):
    from conversation_artifacts import extract_artifacts
    event = legacy_completed_call(['outside.png'])
    event['payload']['invocation'].update(change)
    assert not extract_artifacts(event)['paths']
    assert history.codex_event(line(event), 0) is None


@pytest.mark.parametrize('flag', ['absent', None])
def test_legacy_optional_error_flag_matches_protocol_success(flag):
    from conversation_artifacts import extract_artifacts
    event = legacy_completed_call(['outside.png'])
    result = event['payload']['result']['Ok']
    if flag == 'absent':
        result.pop('isError')
    else:
        result['isError'] = None
    assert extract_artifacts(event)['shown_paths'] == ['outside.png']


def test_legacy_keeps_workspace_text_preview(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    note = work / 'note.txt'
    note.write_text('Generated local note')
    store, bound, event = native_delivery(work, [str(note)], 'codex_legacy')
    assert [r['label'] for r in event['references']] == ['note.txt']
    assert preview(store, bound, event)['text'] == 'Generated local note'
