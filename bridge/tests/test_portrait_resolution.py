"""All cockpit views share custom portraits, retaining bundled pixel artwork."""
import asyncio
import base64
import sys
from pathlib import Path

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orrery_backend as ob

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6i8sAAAAASUVORK5CYII=")


def fetch_portraits(tmp_path, monkeypatch, *, local=(), remote="png"):
    for attr in ("PORTRAIT_DIR", "PORTRAIT_DIR_HI", "PORTRAIT_DIR_PX"):
        directory = tmp_path / attr
        directory.mkdir()
        monkeypatch.setattr(ob, attr, directory)
    for directory, name, marker in local:
        (getattr(ob, directory) / (name + ".png")).write_bytes(PNG + marker)
    received = []

    async def run():
        async def portrait(request):
            received.append(dict(request.query))
            if remote == "offline":
                return web.Response(status=503)
            return web.Response(body=PNG + b"custom" if remote == "png" else b"<svg/>",
                                content_type="image/png" if remote == "png" else "image/svg+xml")
        upstream = web.Application()
        upstream.router.add_get("/portrait", portrait)
        async with TestServer(upstream) as source, ClientSession() as session:
            monkeypatch.setattr(ob, "DASHBOARD_URL", str(source.make_url("")))
            app = web.Application()
            app[ob.HTTP_SESSION_KEY] = session
            app.router.add_get("/telemetry/portrait", ob.serve_portrait)
            async with TestClient(TestServer(app)) as client:
                results = []
                for query in ({"name": "ResidentBot", "hi": "1"},
                              {"name": "ResidentBot", "style": "pixel"},
                              {"name": "ResidentBot", "style": "pixel", "hi": "1"}):
                    async with client.get("/telemetry/portrait", params=query) as response:
                        results.append((response.status, response.content_type, await response.read()))
                return results
    return asyncio.run(run()), received


def test_custom_dashboard_portrait_is_shared_by_roster_mini_and_planet(tmp_path, monkeypatch):
    results, received = fetch_portraits(tmp_path, monkeypatch)
    assert results == [(200, "image/png", PNG + b"custom")] * 3
    assert received == [{"name": "ResidentBot", "hi": "1"}, {"name": "ResidentBot"}, {"name": "ResidentBot"}]


@pytest.mark.parametrize("directory", ["PORTRAIT_DIR", "PORTRAIT_DIR_HI"])
def test_pixel_without_variant_uses_local_custom_face(tmp_path, monkeypatch, directory):
    results, _ = fetch_portraits(tmp_path, monkeypatch,
        local=[(directory, "residentbot", b"local")])
    assert results[1:] == [(200, "image/png", PNG + b"local")] * 2


def test_bundled_pixel_face_keeps_priority_over_regular_and_remote(tmp_path, monkeypatch):
    results, received = fetch_portraits(tmp_path, monkeypatch, local=[
        ("PORTRAIT_DIR_PX", "ResidentBot", b"pixel"),
        ("PORTRAIT_DIR", "ResidentBot", b"normal")])
    assert results[1:] == [(200, "image/png", PNG + b"pixel")] * 2
    assert len(received) == 1


@pytest.mark.parametrize("remote", ["svg", "offline"])
def test_unknown_or_unavailable_portrait_keeps_64px_pixel_initials(tmp_path, monkeypatch, remote):
    results, _ = fetch_portraits(tmp_path, monkeypatch, remote=remote)
    for status, content_type, body in results[1:]:
        assert status == 200 and content_type == "image/svg+xml"
        assert b'width="64"' in body and b">RE</text>" in body
