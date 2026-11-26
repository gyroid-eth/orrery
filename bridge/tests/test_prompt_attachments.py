import base64
import errno
import io
import random
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
import pytest

import orrery_backend as backend


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,format,label', [
    ('image', None, '元の名前.png'),
    ('file', 'mov', 'Screen recording 1.02.mov'),
    ('file', 'zip', 'Archive.zip'),
    ('file', '', 'README'),
])
@pytest.mark.parametrize('path_backed', [False, True])
async def test_attachment_is_written_to_the_selected_workspace(monkeypatch, tmp_path, kind, format, label, path_backed):
    workspace = tmp_path / 'working folder'
    workspace.mkdir()
    incarnation = 'a' * 32
    state = SimpleNamespace(bridge=SimpleNamespace(_incarnation=incarnation))
    monkeypatch.setattr(backend, 'composer_pane_state', lambda app, name, pane: state)

    async def cwd(app, name, pane):
        assert (name, pane) == ('Fixture', '%40')
        return workspace

    monkeypatch.setattr(backend, 'pane_probe_cwd', cwd)
    app = web.Application(middlewares=[backend.own_page_only, backend.json_writes_only])
    app.router.add_post('/telemetry/prompt-attachment', backend.serve_prompt_attachment)
    async with TestClient(TestServer(app)) as client:
        body = dict(session='Fixture', paneId='%40', incarnation=incarnation, kind=kind)
        if kind == 'image':
            pixels = io.BytesIO()
            Image.new('RGB', (2, 2), 'navy').save(pixels, format='PNG')
            data = pixels.getvalue()
        else:
            body['format'] = format
            data = b'\x00\xfffixture\n'
        if path_backed:
            source = tmp_path / label
            source.write_bytes(data)
            body.update(kind='path', sourcePath=str(source))
            body.pop('format', None)
        else:
            body['data'] = base64.b64encode(data).decode()
        body['label'] = label
        missing = await client.post('/telemetry/prompt-attachment', json={**body, 'incarnation': 'b' * 32})
        assert missing.status == 409
        overridden = await client.post('/telemetry/prompt-attachment', json={**body, 'destination': '/tmp'})
        assert overridden.status == 400
        response = await client.post('/telemetry/prompt-attachment', json=body)
        result = await response.json()
        assert response.status == 200, result
        assert result['path'].startswith('./.orrery-input-')
        saved = workspace / result['path']
        assert saved.stat().st_mode & 0o777 == 0o600
        assert (saved.parent / '.gitignore').read_text() == '*\n'
        assert saved.with_name(saved.name+'.label').read_text() == body['label']
        if kind == 'image':
            with Image.open(saved) as picture:
                assert picture.size == (2, 2)
                assert picture.getpixel((0, 0)) == (0, 0, 128)
        else:
            assert saved.suffix == ('.' + format if format else '')
            assert saved.read_bytes() == data


def test_only_a_regular_file_over_the_limit_gets_its_original_path(tmp_path, monkeypatch):
    import mobile_file

    limit = 64
    monkeypatch.setattr(mobile_file, 'MAX_FILE_BYTES', limit)
    source = tmp_path / 'Fixture.zip'
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    source.write_bytes(b'x' * limit)
    saved = backend.stage_prompt_attachment_path(workspace, str(source))
    assert (workspace / saved).read_bytes() == b'x' * limit
    source.write_bytes(b'x' * (limit + 1))
    assert backend.stage_prompt_attachment_path(workspace, str(source)) is None

    link = tmp_path / 'link.zip'
    link.symlink_to(source)
    for path in (link, tmp_path / 'missing.zip', workspace):
        with pytest.raises(ValueError, match='attachment_source_unreadable'):
            backend.stage_prompt_attachment_path(workspace, str(path))


@pytest.mark.asyncio
async def test_selected_image_bytes_save_even_when_the_desktop_path_cannot_be_read(monkeypatch, tmp_path, caplog):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    folder = workspace / '.orrery-input-images'
    folder.mkdir()
    for index in range(50):
        (folder / f'{index:032x}.png').write_bytes(b'previous image')
    source = tmp_path / 'Desktop' / 'Screenshot.png'
    original_open = backend.os.open

    def protected_open(path, *args, **kwargs):
        if str(path) == str(source):
            raise PermissionError(errno.EPERM, 'Protected folder')
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(backend.os, 'open', protected_open)
    state = SimpleNamespace(bridge=SimpleNamespace(_incarnation='a' * 32))
    monkeypatch.setattr(backend, 'composer_pane_state', lambda *args: state)

    async def cwd(*args):
        return workspace

    monkeypatch.setattr(backend, 'pane_probe_cwd', cwd)
    app = web.Application()
    app.router.add_post('/telemetry/prompt-attachment', backend.serve_prompt_attachment)
    raw = io.BytesIO()
    size = (2000, 1800)
    Image.frombytes('RGB', size, random.Random(1).randbytes(size[0] * size[1] * 3)).save(raw, format='PNG')
    assert raw.tell() > 10 * 1024**2
    common = {'session': 'Fixture', 'paneId': '%40', 'incarnation': 'a' * 32, 'label': source.name}
    async with TestClient(TestServer(app)) as client:
        denied = await client.post('/telemetry/prompt-attachment',
                                   json={**common, 'kind': 'path', 'sourcePath': str(source)})
        assert denied.status == 422
        assert (await denied.json())['error'] == 'attachment_source_unreadable'
        assert 'reason=attachment_source_unreadable status=422 errno=1' in caplog.text
        assert str(source) not in caplog.text
        saved = await client.post('/telemetry/prompt-attachment',
                                  json={**common, 'kind': 'image', 'data': base64.b64encode(raw.getvalue()).decode()})
        assert saved.status == 200
        destination = workspace / (await saved.json())['path']
        with Image.open(destination) as image:
            assert image.size == size
        assert len(list(folder.glob('*.png'))) == 51


@pytest.mark.asyncio
async def test_clipboard_snapshot_is_loopback_scoped_and_cannot_accept_paths(monkeypatch):
    calls = []

    async def read(*, snapshot):
        assert snapshot is True
        calls.append(snapshot)
        return {'attachments': [{'name': 'file.md', 'data': 'IyBEcmFmdA=='}]}

    monkeypatch.setattr(backend, 'host_kind', lambda: 'wsl')
    monkeypatch.setattr(backend, 'read_windows_clipboard', read)
    app = web.Application(middlewares=[backend.own_page_only, backend.json_writes_only])
    app.router.add_post('/telemetry/clipboard/attachments', backend.serve_clipboard_attachments)
    async with TestClient(TestServer(app)) as client:
        foreign = await client.post('/telemetry/clipboard/attachments', json={},
                                    headers={'Origin': 'https://elsewhere.invalid'})
        assert foreign.status == 403
        forged = await client.post('/telemetry/clipboard/attachments', json={'path': '/private/file.md'})
        assert forged.status == 400
        result = await client.post('/telemetry/clipboard/attachments', json={})
        assert result.status == 200
        assert result.headers['Cache-Control'] == 'no-store'
        assert (await result.json())['attachments'] == [{'name': 'file.md', 'data': 'IyBEcmFmdA=='}]
        assert calls == [True]
