import base64
import io
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
import pytest

import orrery_backend as backend


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['image', 'file'])
async def test_attachment_is_written_to_the_selected_workspace(monkeypatch, tmp_path, kind):
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
            body['format'] = 'md'
            data = b'# Fixture text'
        body['data'] = base64.b64encode(data).decode()
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
        if kind == 'image':
            with Image.open(saved) as picture:
                assert picture.size == (2, 2)
                assert picture.getpixel((0, 0)) == (0, 0, 128)
        else:
            assert saved.read_bytes() == data
