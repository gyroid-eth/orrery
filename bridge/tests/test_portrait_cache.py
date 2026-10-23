"""A missing portrait must not hide a subsequently configured portrait."""
import asyncio
from pathlib import Path
import sys

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestClient, TestServer
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orrery_backend as ob


@pytest.mark.parametrize("query", ["", "&hi=1", "&style=pixel"])
def test_fallback_does_not_cache_away_a_later_custom_portrait(tmp_path, monkeypatch, query):
    for key in ("PORTRAIT_DIR", "PORTRAIT_DIR_HI", "PORTRAIT_DIR_PX"):
        monkeypatch.setattr(ob, key, tmp_path)

    async def exercise():
        available = False
        calls = []
        png = b"\x89PNG\r\n\x1a\ncustom portrait"

        async def portrait(request):
            calls.append(request.query["name"])
            if available:
                return web.Response(body=png, content_type="image/png")
            return web.Response(text="<svg/>", content_type="image/svg+xml")

        upstream = web.Application()
        upstream.router.add_get("/portrait", portrait)
        async with TestServer(upstream) as server:
            monkeypatch.setattr(ob, "DASHBOARD_URL", str(server.make_url("")).rstrip("/"))
            async with ClientSession() as session:
                app = web.Application()
                app[ob.HTTP_SESSION_KEY] = session
                app.router.add_get("/telemetry/portrait", ob.serve_portrait)
                async with TestClient(TestServer(app)) as client:
                    url = "/telemetry/portrait?name=CustomAgent" + query
                    async with client.get(url) as response:
                        assert response.status == 200
                        assert response.content_type == "image/svg+xml"
                        assert response.headers["Cache-Control"] == "no-store"
                        assert b">CU</text>" in await response.read()
                    available = True
                    async with client.get(url) as response:
                        assert response.status == 200
                        assert response.content_type == "image/png"
                        assert await response.read() == png
                        assert response.headers["Cache-Control"] == "public, max-age=3600"
        assert calls == ["CustomAgent", "CustomAgent"]

    asyncio.run(exercise())


def test_bundled_portrait_keeps_its_image_cache_policy(tmp_path, monkeypatch):
    png = b"\x89PNG\r\n\x1a\nbundled portrait"
    (tmp_path / "CustomAgent.png").write_bytes(png)
    monkeypatch.setattr(ob, "PORTRAIT_DIR", tmp_path)

    async def exercise():
        app = web.Application()
        app.router.add_get("/telemetry/portrait", ob.serve_portrait)
        async with TestClient(TestServer(app)) as client:
            async with client.get("/telemetry/portrait?name=CustomAgent") as response:
                assert response.status == 200
                assert response.content_type == "image/png"
                assert await response.read() == png
                assert response.headers["Cache-Control"] == "public, max-age=3600"

    asyncio.run(exercise())
