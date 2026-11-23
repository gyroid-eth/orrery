"""Bound Markdown image IDs from synthetic native history, never a phone path."""
import asyncio
import base64
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from test_conversation_providers import claude, dsh, line, make_db, row
from conversation_history import open_reader
from conversation_markdown_images import markdown_image_targets
from conversation_preview import MAX_IMAGE, PreviewUnavailable, ReferenceStore


def picture(path, color='#61c1ab'):
    Image.new('RGB', (640, 400), color).save(path, format='PNG')
    return path


def markdown(target):
    return f'![Fixture chart](<{target}>)'


def codex_message(text, *, role='assistant', phase=None):
    payload = dict(type='message', role=role, content=[dict(type='output_text', text=text)])
    if phase:
        payload['phase'] = phase
    return dict(type='response_item', payload=payload)


def codex_history(workspace, *items):
    transcript = workspace / 'fixture.jsonl'
    transcript.write_bytes(line(dict(type='session_meta', payload=dict(cwd=str(workspace)))) + b''.join(map(line, items)))
    return row(transcript, 'codex')


def history_with_images(bound, store):
    with open_reader(bound) as reader:
        events = reader.read_page()['events']
        store.decorate_all(bound, reader, events)
    return events


def test_targets_keep_exact_spelling_and_exclude_examples_and_badges():
    targets = ['~/図 (draft).PNG', '/fixture/plot.jpg', '/fixture/chart.gif', '/fixture/out.webp']
    source = f'''---
example: ![front](/fixture/front.png)
---

{markdown(targets[0])}, {markdown(targets[0])}, {markdown(targets[1])}

- {markdown(targets[2])}
> {markdown(targets[3])}

\\![escaped](/fixture/escaped.png)
`![in code](/fixture/code.png)`
`multi-line
![still code](/fixture/code2.png)`

    ![indented](/fixture/indented.png)

> ```md
> ![quoted code](/fixture/quoted.png)
> ```

- ~~~md
  ![listed code](/fixture/listed.png)
  ~~~

[![badge](/fixture/badge.png)](https://example.test/)
[prefix ![banner](/fixture/prefixed-badge.png)](https://example.test/)
<img alt="![tag](/fixture/tag.png)">
<img alt="![tag](</fixture/tag-angle.png>)">
![external](https://example.test/remote.png)
![relative](fixture.png)
![protocol relative](//fixture.invalid/remote.png)
![text](/fixture/caption.md)
'''
    event = dict(kind='text', role='assistant', text=source)
    assert markdown_image_targets(event) == targets
    assert markdown_image_targets(dict(event, role='user')) == []
    assert markdown_image_targets(dict(event, variant='update')) == []
    assert markdown_image_targets(dict(event, kind='tool_result')) == []


def test_first_eight_distinct_targets_are_shared_between_event_and_mail():
    targets = [f'/fixture/{i}.png' for i in range(12)]
    event = dict(kind='text', role='assistant', text=' '.join(map(markdown, targets[:3])),
                 mail=[{'body': ' '.join(map(markdown, targets[i:]))} for i in (1, 7)])
    assert markdown_image_targets(event) == targets[:8]


@pytest.mark.parametrize('program', ['codex', 'claude-code', 'dsh', 'hermes'])
def test_native_assistant_can_show_a_verified_image_outside_workspace(tmp_path, monkeypatch, program):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    monkeypatch.setenv('HOME', str(tmp_path))
    target = '~/公開 (draft).PNG'
    picture(tmp_path / '公開 (draft).PNG')
    text = markdown(target)
    transcript = workspace / 'fixture.jsonl'
    if program == 'codex':
        bound = codex_history(workspace, codex_message(text))
    elif program == 'claude-code':
        transcript.write_bytes(line(claude('assistant', [dict(type='text', text=text)], cwd=str(workspace))))
        bound = row(transcript, program)
    elif program == 'dsh':
        transcript.write_bytes(line(dict(type='session', version=4, id='fixture-session', cwd=str(workspace))) +
                               line(dsh('assistant/message', {'message': {'content': [{'type': 'text', 'text': text}]}}, seq=2)))
        bound = row(transcript, program)
    else:
        transcript = workspace / 'state.db'
        with make_db(transcript) as connection:
            connection.execute("UPDATE sessions SET cwd=? WHERE id='fixture-session'", (str(workspace),))
            connection.execute('INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(1,?,?,?,1)',
                               ('fixture-session', 'assistant', text))
        bound = row(transcript, program)
    store = ReferenceStore()
    events = history_with_images(bound, store)
    event = next(event for event in events if event.get('role') == 'assistant')
    item, = event['markdown_images']
    assert item.keys() == {'target', 'id'} and item['target'] == target
    assert len(item['id']) == 32 and str(tmp_path) not in repr(item)
    assert next(event for event in history_with_images(bound, store) if event.get('role') == 'assistant')['markdown_images'] == [item]
    result = store.read(item['id'], bound, thumbnail=True, mobile=True)
    with Image.open(BytesIO(base64.b64decode(result['data']))) as image:
        assert image.format == 'PNG' and image.size == (320, 200)
    assert (result['width'], result['height']) == (320, 200)
    assert store.read(item['id'], bound, mobile=True)['width'] == 640
    with pytest.raises(PreviewUnavailable, match='preview_unavailable'):
        store.read(item['id'], bound, reveal=True)


def test_refuses_non_rasters_and_unverified_events(tmp_path):
    picture(tmp_path / 'chart.png')
    disguised = tmp_path / 'text.png'
    disguised.write_text('This is plain text')
    picture(tmp_path / 'raster.txt')
    oversize = tmp_path / 'huge.png'
    with oversize.open('wb') as output:
        output.truncate(MAX_IMAGE+1)
    refs = [tmp_path / name for name in ('text.png', 'raster.txt', 'huge.png', 'missing.png')]
    user = markdown(tmp_path / 'chart.png')
    bound = codex_history(tmp_path, codex_message(' '.join(map(markdown, refs))),
                          codex_message(user, role='user'), codex_message(user, phase='analysis'))
    store = ReferenceStore()
    events = history_with_images(bound, store)
    assert not any('markdown_images' in event for event in events)
    assert not store.refs
    with open_reader(bound) as reader:
        # Mutating the projected event cannot authorize a target missing from its record.
        forged = dict(events[0], text=user)
        store.decorate(bound, reader, forged)
        assert 'markdown_images' not in forged


def test_markdown_reference_expires_on_binding_alias_and_record_changes(tmp_path):
    link = tmp_path / 'alias.png'
    original = picture(tmp_path / 'original.png')
    substitute = picture(tmp_path / 'substitute.png')
    link.symlink_to(original)
    bound = codex_history(tmp_path, codex_message(markdown(link)))
    clock = [0]
    store = ReferenceStore(clock=lambda: clock[0], ttl=3)
    ref = history_with_images(bound, store)[0]['markdown_images'][0]['id']
    assert store.read(ref, bound)['kind'] == 'image'
    with pytest.raises(PreviewUnavailable, match='reference_expired'):
        store.read(ref, dict(bound, history_session_id='different'))
    link.unlink()
    link.symlink_to(substitute)
    with pytest.raises(PreviewUnavailable, match='reference_expired'):
        store.read(ref, bound)
    link.unlink()
    link.symlink_to(original)
    transcript = Path(bound['transcript_path'])
    saved = transcript.read_bytes()
    transcript.write_bytes(saved.replace(b'Fixture chart', b'Different alt'))
    with pytest.raises(PreviewUnavailable, match='reference_expired'):
        store.read(ref, bound)
    transcript.write_bytes(saved)
    clock[0] = 3
    with pytest.raises(PreviewUnavailable, match='reference_expired'):
        store.read(ref, bound)


def test_history_endpoint_decorates_mail_and_preview_accepts_only_ids(tmp_path, monkeypatch):
    from aiohttp import ClientSession, web
    import orrery_backend as backend
    from test_conversation_history import start

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    image = picture(tmp_path / 'published.png')
    message = markdown(image)
    sent = dict(type='response_item', payload=dict(type='function_call', name='mcp__orrery_mail__send_message',
                arguments=dict(subject='Fixture', to=['FixturePeer'], body_md=message)))
    received = ('ORRERY Mail notification: message from FixturePeer [normal]: '
                'Fixture. Body (complete; no inbox fetch needed): '+message)
    bound = codex_history(workspace, codex_message(message), codex_message(received, role='user'), sent)

    async def scenario():
        async def agents(request):
            return web.json_response({'agents': [bound]})
        upstream = web.Application()
        upstream.router.add_get('/api/agents', agents)
        runner, origin = await start(upstream)
        monkeypatch.setattr(backend, 'DASHBOARD_URL', origin)
        app = web.Application(middlewares=[backend.own_page_only, backend.json_writes_only])
        app[backend.HTTP_SESSION_KEY] = ClientSession()
        app[backend.TMUX_BIN_KEY] = object()
        app[backend.CONVERSATION_REFERENCES_KEY] = ReferenceStore()
        app.router.add_get('/telemetry/conversation', backend.serve_conversation)
        app.router.add_get('/telemetry/conversation/preview', backend.serve_conversation_preview)
        server, url = await start(app)
        try:
            async with ClientSession() as client:
                async with client.get(url+'/telemetry/conversation', params={'agent': 'FixtureAgent'}) as response:
                    assert response.status == 200
                    events = (await response.json())['events']
                assert [event['kind'] for event in events] == ['text', 'mail', 'mail']
                assert [event['mail'][0]['direction'] for event in events[1:]] == ['received', 'sent']
                refs = [event['markdown_images'][0] for event in events]
                assert len({ref['id'] for ref in refs}) == 3
                for ref in refs:
                    assert ref['target'] == str(image)
                    async with client.get(url+'/telemetry/conversation/preview', params={'ref': ref['id'], 'mobile': '1'}) as response:
                        data = await response.json()
                        assert response.status == 200 and data['mime'] == 'image/png'
                        assert (data['width'], data['height']) == (640, 400)
                async with client.get(url+'/telemetry/conversation/preview', params={'ref': refs[0]['id'], 'path': str(image)}) as response:
                    assert response.status == 400
        finally:
            await server.cleanup()
            await app[backend.HTTP_SESSION_KEY].close()
            await runner.cleanup()

    asyncio.run(scenario())
