"""Phone documents use the same verified workspace and confirmation as images."""
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import contextlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mobile_file import MAX_FILE_BYTES, save_file


def document(kind, data):
    return dict(format=kind, data=base64.b64encode(data).decode())


@pytest.mark.parametrize('kind,body', [
    ('pdf', b'%PDF-1.7\n%fixture\n%%EOF\n'),
    ('txt', 'A note\n'.encode()),
    ('md', '# A note\n'.encode()),
    ('csv', b'a,b\r\n1,2\r\n'),
    ('json', b'{"artifact":1}\n'),
])
def test_document_bytes_are_preserved_in_a_private_workspace_file(tmp_path, kind, body):
    path = Path(save_file(tmp_path, document(kind, body)))
    assert path.parent == tmp_path / '.orrery-input-files'
    assert path.suffix == '.' + kind and len(path.stem) == 32
    assert path.read_bytes() == body
    assert path.stat().st_mode & 0o777 == 0o600
    assert (path.parent / '.gitignore').read_bytes() == b'*\n'


@pytest.mark.parametrize('upload,reason', [
    (document('html', b'<p>note</p>'), 'file_format_unsupported'),
    (document('../pdf', b'%PDF-1.7\n'), 'file_format_unsupported'),
    (document('pdf', b'just text'), 'file_format_unsupported'),
    (document('txt', b'\0a'), 'file_format_unsupported'),
    (document('md', b'\xff'), 'file_format_unsupported'),
    (document('json', b''), 'file_empty'),
    (dict(format='txt', data='not valid base64'), 'file_invalid'),
    (dict(format='txt', data='YQ==', path='elsewhere'), 'file_invalid'),
])
def test_bad_documents_never_create_the_attachment_folder(tmp_path, upload, reason):
    with pytest.raises(ValueError, match=reason):
        save_file(tmp_path, upload)
    assert not (tmp_path / '.orrery-input-files').exists()


def test_document_size_limit_and_symlink_rejection(tmp_path):
    with pytest.raises(ValueError, match='file_too_large'):
        save_file(tmp_path, document('txt', b'x' * (MAX_FILE_BYTES + 1)))
    other = tmp_path / 'other'
    other.mkdir()
    (tmp_path / '.orrery-input-files').symlink_to(other, target_is_directory=True)
    with pytest.raises(OSError):
        save_file(tmp_path, document('txt', b'unchanged bytes'))
    assert not list(other.iterdir())


def test_parallel_uploads_share_the_folder_cap(tmp_path):
    upload = document('txt', b'fixture')
    for _ in range(49):
        save_file(tmp_path, upload)

    def save(_):
        try:
            return Path(save_file(tmp_path, upload))
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as workers:
        a, b = workers.map(save, range(2))
    assert [item for item in (a,b) if isinstance(item,str)] == ['file_folder_full']
    assert len(list((tmp_path / '.orrery-input-files').glob('*.txt'))) == 50


def test_file_route_needs_the_verified_pane_and_never_sends_on_upload(tmp_path):
    from aiohttp import ClientSession, web
    import mobile_input as mobile
    from test_mobile_input import bridge_fixture

    async def scenario():
        bridge = bridge_fixture(tmp_path)
        proof_version = 1
        sent = []

        class Resolver:
            def read(self, current, pane, deadline):
                return dict(session=current.config.session, pane_id=pane, incarnation=current._incarnation,
                            height=24, version=proof_version)

            @contextlib.contextmanager
            def admission(self, row, deadline):
                yield self.read(row['bridge'], row['pane_id'], deadline)

        async def get_bridge(name):
            return bridge if name == bridge.config.session else None

        async def workspace(row):
            return tmp_path

        async def preview(*args, **kwargs):
            return SimpleNamespace(lines=['fixture only'])

        async def send(pane, text, **options):
            assert options['valid']() and options['claim']()
            sent.append((pane,text))
            return 'accepted'

        bridge.capture_mobile_preview = preview
        bridge.send_confirmed_input = send
        coordinator = mobile.InputCoordinator(Resolver(), get_bridge, enabled=True, image_workspace=workspace)
        app = web.Application()
        mobile.install_routes(app, coordinator)
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with ClientSession() as client:
                scope = dict(contract=mobile.CONTRACT, owner='fixture@example.invalid', reader_epoch='a'*32)
                headers = {'Origin':f'http://127.0.0.1:{port}', 'Content-Type':'application/json',
                           'X-ORRERY-Mobile-Contract':mobile.CONTRACT}

                async def post(operation, **fields):
                    async with client.post(f'http://127.0.0.1:{port}/_mobile/terminal/{operation}',
                                           data=json.dumps({**scope,**fields}), headers=headers) as response:
                        return response.status, await response.json()

                _, cap = await post('capability')
                scope['epoch'] = cap['epoch']
                _, catalog = await post('targets', name=bridge.config.session)
                choice = catalog['targets'][0]['choice']
                _, observed = await post('preview', choice=choice)
                revision = observed['target']['revision']
                _, probe = await post('file', choice=choice, revision=revision, file=None)
                assert probe['enabled'] and 'path' not in probe
                assert not (tmp_path / '.orrery-input-files').exists()
                content = b'Read the attached data.\n'
                assert (await post('file', choice=choice, revision='0'*64, file=document('txt', content)))[0] == 403
                assert not (tmp_path / '.orrery-input-files').exists()
                status, attached = await post('file', choice=choice, revision=revision, file=document('txt', content))
                assert status == 200 and Path(attached['path']).read_bytes() == content and not sent
                text = f"Review [file: '{attached['path']}']"
                _, prepared = await post('prepare', choice=choice, revision=revision, text=text)
                assert prepared['text'] == text and not sent
                keys = dict(intent=prepared['intent'], confirmation=prepared['confirmation'])
                assert (await post('commit', **keys))[1]['state'] == 'accepted'
                assert (await post('commit', **keys))[1]['state'] == 'accepted'
                assert sent == [('%3', text)]
                proof_version += 1
                assert (await post('file', choice=choice, revision=revision, file=document('txt', content)))[0] == 403
                assert len(list((tmp_path / '.orrery-input-files').glob('*.txt'))) == 1
        finally:
            await runner.cleanup()

    asyncio.run(scenario())
