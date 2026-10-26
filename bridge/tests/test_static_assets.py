"""The real private app serves only its fixed UI assets."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from aiohttp import ClientSession, web

BRIDGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRIDGE))


@asynccontextmanager
async def private_app(monkeypatch, tmp_path, configure=None):
    import orrery_backend as ob

    class Boundary:
        shared = None
        transport = None
        home = tmp_path

    monkeypatch.setattr(ob, 'LegacyTargetBoundary', Boundary)
    if configure:
        configure(ob)
    app = ob.create_app(Boundary())
    app.cleanup_ctx.clear()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        async with ClientSession() as client:
            yield ob, client, f'http://127.0.0.1:{port}'
    finally:
        await runner.cleanup()


def test_fixed_ui_files_and_headers(monkeypatch, tmp_path):
    async def scenario():
        async with private_app(monkeypatch, tmp_path) as (ob, client, base):
            for path, relative in ob.PUBLIC_FILES.items():
                async with client.get(base + path) as response:
                    assert response.status == 200, path
                    assert await response.read() == (BRIDGE / relative).read_bytes()
                    assert response.headers['Cache-Control'] == 'no-cache'
                async with client.head(base + path) as response:
                    assert response.status == 200, path
    asyncio.run(scenario())


def test_unlisted_files_and_directories_are_absent(monkeypatch, tmp_path):
    async def scenario():
        async with private_app(monkeypatch, tmp_path) as (_, client, base):
            for path in ('/', '/orrery_backend.py', '/requirements.txt', '/.venv/pyvenv.cfg',
                         '/tests/mock_backend.py', '/spawn_catalog.json', '/cockpit-assets/',
                         '/cockpit-assets/README.md', '/vendor/', '/vendor/manifest.json',
                         '/missing.js', '/%2e%2e/CREDITS.md'):
                async with client.get(base + path) as response:
                    assert response.status in (403, 404), path
    asyncio.run(scenario())


def test_pages_reference_only_allowed_local_assets():
    import orrery_backend as ob

    class References(HTMLParser):
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag in ('link', 'script', 'img'):
                value = values.get('src') or values.get('href', '')
                if value and not urlsplit(value).scheme:
                    path = '/' + value.lstrip('/')
                    assert path in ob.PUBLIC_FILES or path in {
                        '/assets/anthropic.svg', '/assets/openai.svg'}, value

    for page in ('cockpit.html', 'tour.html'):
        References().feed((BRIDGE / page).read_text())
    assert 'cdn.jsdelivr.net' not in (BRIDGE / 'cockpit.html').read_text()


def test_vendor_bytes_match_recorded_hashes_and_licenses():
    entries = json.loads((BRIDGE / 'vendor/manifest.json').read_text())
    assert len(entries) == 7
    credits = (BRIDGE.parent / 'CREDITS.md').read_text()
    for entry in entries:
        data = (BRIDGE / entry['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry['sha256']
        assert len(data) == entry['bytes']
        assert entry['license'] == 'MIT'
        assert entry['sha256'] in credits
        license_path = (BRIDGE / entry['path']).parent / 'LICENSE'
        assert 'Permission is hereby granted' in license_path.read_text()
