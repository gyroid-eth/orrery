"""The real private app admits JSON writes before dispatch."""
import asyncio

from aiohttp import web

from test_static_assets import private_app


def test_write_routes_require_json(monkeypatch, tmp_path):
    calls = []
    async def accepted(request):
        calls.append((request.method, request.path, await request.json()))
        return web.json_response({'ok': True})

    def configure(ob):
        for handler in ('proxy_spawn', 'open_ghostty', 'open_url', 'reveal_path',
                        'path_probe', 'update_prefs', 'proxy_dashboard_passthrough'):
            monkeypatch.setattr(ob, handler, accepted)

    async def scenario():
        async with private_app(monkeypatch, tmp_path, configure) as (_, client, base):
            routes = [('POST', '/telemetry/' + route) for route in
                      ('spawn', 'open-ghostty', 'open-url', 'reveal-path', 'path-probe')]
            routes += [('PUT', '/telemetry/prefs'), ('POST', '/api/exit'),
                       ('PATCH', '/api/future'), ('DELETE', '/api/future')]
            for method, path in routes:
                for content_type in ('text/plain', 'application/x-www-form-urlencoded',
                                     'multipart/form-data', 'application/octet-stream'):
                    async with client.request(method, base + path, data='{}',
                                              headers={'Content-Type': content_type}) as response:
                        assert response.status == 415
                for content_type in ('application/json', 'application/json; charset=utf-8'):
                    async with client.request(method, base + path, data='{}',
                                              headers={'Content-Type': content_type}) as response:
                        assert response.status == 200
            assert len(calls) == 2 * len(routes)
    asyncio.run(scenario())
