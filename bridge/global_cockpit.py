"""Opt-in cockpit adapter. Telemetry owns admission, Mail and client contracts."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import runpy
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientTimeout, WSMsgType, web
from yarl import URL

CAPABILITIES = dict(operator_http_admission=1, global_mail_bridge=1,
                    instruction_migration=1, websocket_first_frame_auth=1,
                    global_runtime_observation=1)
API_GENERATION = 1
FIXTURE = json.loads((Path(__file__).parent/'global_cockpit_contract.json').read_text())


class Headers:
    """Only adapt aiohttp's multidict; the installed helper owns policy."""
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)

    def get_all(self, key, default=None):
        return self.values.getall(key, default)


class GlobalCockpit:
    def __init__(self, backend):
        if os.name != "posix":
            raise RuntimeError("GLOBAL_UNIX_REQUIRED")
        self.backend = backend
        self.home = Path(os.environ.get('AGENTSTACK_HOME', '')).expanduser()
        self.config = os.environ.get('AGENTSTACK_GLOBAL_SERVER_CONFIG', '')
        if not os.environ.get('AGENTSTACK_HOME') or not self.config:
            raise RuntimeError('COCKPIT_GLOBAL_CONFIG_REQUIRED')
        self.dashboard = self.home/'dashboard'
        try:
            self.helper = runpy.run_path(str(self.dashboard/'http_operator.py'))
            for name in ('Admission', 'AdmissionError', 'read_capability', 'probe'):
                if not callable(self.helper.get(name)):
                    raise ValueError(name)
            self.helper['Admission'](self.home, backend.DASHBOARD_URL)
        except (OSError, ValueError, KeyError) as exc:
            raise RuntimeError('COCKPIT_GLOBAL_CAPABILITY_REQUIRED') from exc
        self.proof = None
        self._manager = None
        self._manager_lock = asyncio.Lock()
        self.api_routes = {(method, path): target for method, path, target, _ in FIXTURE['proxy_map']}
        self.query_keys = FIXTURE['query_keys']
        # Public files only: source, tests, config and directory listings are excluded.
        self.static = {'/'+name:backend.HERE/name for name in FIXTURE['cockpit_assets']}
        self.static['/'] = backend.HERE/'cockpit.html'
        for name in ('anthropic.svg', 'openai.svg'):
            self.static['/assets/'+name] = backend.HERE/'assets'/name
        self.network_assets = set(FIXTURE['network_assets'])

    def admission(self, request):
        # A configured port cannot be inferred from an untrusted Host header.
        sock = request.transport.get_extra_info('sockname')
        return self.helper['Admission'](self.home, 'http://127.0.0.1:'+str(sock[1]))

    def public_static(self, request):
        if request.method not in ('GET', 'HEAD'):
            return False
        return (request.path in self.static or request.path in ('/network', '/network/')
                or request.path.removeprefix('/network/') in self.network_assets
                and request.path.startswith('/network/'))

    @web.middleware
    async def admission_middleware(self, request, handler):
        try:
            if not self.public_static(request):
                admission = self.admission(request)
                peer = request.transport.get_extra_info('peername')[0]
                if request.path == '/ws':
                    admission.network(Headers(request.headers), peer, websocket=True)
                else:
                    admission.http(Headers(request.headers), peer)
            return await handler(request)
        except self.helper['AdmissionError'] as exc:
            return web.json_response(dict(ok=False, reason=str(exc)), status=exc.status)

    async def probe(self):
        return await asyncio.to_thread(self.helper['probe'], self.home, service='telemetry',
                                       telemetry_url=self.backend.DASHBOARD_URL,
                                       cockpit_port=0, config_path=self.config)

    async def startup(self, app):
        self.proof = await self.probe()

    async def health(self, request):
        try:
            proof = await self.probe()
        except self.helper['AdmissionError']:
            raise
        except Exception:
            return web.json_response(dict(ok=False, reason='COCKPIT_GLOBAL_CAPABILITY_REQUIRED'), status=503)
        if self.proof is None or proof['binding'] != self.proof['binding']:
            return web.json_response(dict(ok=False, reason='MANAGEMENT_BINDING_MISMATCH'), status=503)
        return web.json_response(dict(backend='ok', boot=self.backend.BACKEND_BOOT_ID,
            root=self.backend.BACKEND_ROOT, commit=self.backend.BACKEND_COMMIT,
            dashboard=True, runtime_mode='global', api=API_GENERATION,
            capabilities=CAPABILITIES,
            upstream=dict(binding=proof['binding'], api=proof['telemetry_api'],
                          capabilities=proof['capabilities'])))

    async def proxy(self, request):
        method = 'GET' if request.method == 'HEAD' else request.method
        target = self.api_routes.get((method, request.path))
        if target is None:
            return await self.unavailable(request)
        allowed = self.query_keys.get(request.path, [])
        if any(key not in allowed or len(request.query.getall(key)) != 1 for key in request.query):
            return web.json_response(dict(ok=False, reason='QUERY_INVALID'), status=400)
        return await self.forward(request, target)

    async def forward(self, request, target):
        token = self.helper['read_capability'](self.home)
        upstream = self.backend.DASHBOARD_URL
        headers = {'Authorization':'Bearer '+token, 'Origin':upstream}
        if request.method == 'POST':headers['Content-Type'] = 'application/json'
        query = request.rel_url.raw_query_string
        url = upstream+target+('?' + query if query else '')
        session = request.app[self.backend.HTTP_SESSION_KEY]
        try:
            async with session.request(request.method, URL(url, encoded=True), headers=headers,
                    data=await request.read() if request.can_read_body else None,
                    allow_redirects=False, timeout=ClientTimeout(total=6)) as response:
                if 300 <= response.status < 400:
                    return web.json_response(dict(ok=False, reason='UPSTREAM_REDIRECT_REFUSED'), status=502)
                body = await response.read()
                return web.Response(body=body, status=response.status,
                    headers={'Content-Type':response.headers.get('Content-Type', 'application/octet-stream')})
        except (ClientError, asyncio.TimeoutError):
            return web.json_response(dict(ok=False, reason='GLOBAL_UPSTREAM_UNAVAILABLE'), status=503)

    async def static_file(self, request):
        path = self.static.get(request.path)
        if request.method not in ('GET', 'HEAD') or path is None:
            return await self.unavailable(request)
        if path.name == 'cockpit.html':
            payload = path.read_text()
            payload = payload.replace('<head>', '<head><script>window.ORRERY_GLOBAL_MODE=true;</script>', 1)
            for name in ('prefs_sync.js', 'orrery_view.js', 'mail_view.js'):
                payload = payload.replace('<script src="'+name+'"></script>', '')
            assets = ''.join('<script src="/network/'+name+'.js"></script>' for name in
                ('operator_session', 'mail_flow', 'mail_controller', 'operation_controller', 'runtime_node'))
            assets += '<script src="/global_cockpit.js"></script><link rel="stylesheet" href="/network/mail_flow.css"><link rel="stylesheet" href="/global_cockpit.css">'
            payload = payload.replace('</head>', assets+'</head>', 1)
            return web.Response(text=payload, content_type='text/html')
        return web.FileResponse(path)

    async def network(self, request):
        name = request.path.removeprefix('/network/').removeprefix('/network')
        if request.method not in ('GET', 'HEAD') or name not in self.network_assets | {''}:
            return await self.unavailable(request)
        return await self.forward(request, '/'+name)

    async def unavailable(self, request):
        return web.json_response(dict(ok=False, reason='GLOBAL_ROUTE_UNAVAILABLE'), status=404)

    async def manager(self):
        # No manager/client membership exists before first-frame admission.
        async with self._manager_lock:
            if self._manager is None:
                manager = self.backend.SessionBridgeManager(self.tmux_bin)
                await manager.start()
                self._manager = manager
            return self._manager

    async def close(self):
        if self._manager is not None:
            await self._manager.close()

    async def authenticate_socket(self, request, response):
        try:
            message = await response.receive(timeout=FIXTURE['websocket']['deadline_seconds'])
            if message.type != WSMsgType.TEXT or len(message.data.encode('utf-8')) > 1024:
                raise ValueError
            payload = json.loads(message.data)
            if (not isinstance(payload, dict) or set(payload) != {'type', 'version', 'capability'}
                    or payload['type'] != 'authenticate' or type(payload['version']) is not int
                    or payload['version'] != 1):
                raise ValueError
            self.admission(request).authenticate(payload['capability'])
        except (ValueError, asyncio.TimeoutError, self.helper['AdmissionError']):
            await response.close(code=4401, message=b'Authentication required')
            return False
        await response.send_json(dict(type='authenticated', version=1))
        return True


def create_app(backend, tmux_bin):
    integration = GlobalCockpit(backend)
    integration.tmux_bin = tmux_bin
    app = web.Application(middlewares=[backend.revalidate_static, integration.admission_middleware])
    app[backend.GLOBAL_COCKPIT_KEY] = integration
    app[backend.TMUX_BIN_KEY] = tmux_bin
    app[backend.PREFS_LOCK_KEY] = asyncio.Lock()
    app.on_startup.append(integration.startup)
    app.cleanup_ctx.append(backend.app_resources)
    local = {
        ('POST','/telemetry/open-ghostty'):backend.open_ghostty,
        ('POST','/telemetry/open-url'):backend.open_url,
        ('POST','/telemetry/reveal-path'):backend.reveal_path,
        ('POST','/telemetry/path-probe'):backend.path_probe,
        ('GET','/telemetry/platform'):backend.serve_platform,
        ('GET','/telemetry/identity'):backend.serve_identity,
        ('GET','/telemetry/sessions'):backend.serve_sessions,
        ('GET','/telemetry/skills'):backend.serve_skills,
        ('GET','/telemetry/clipboard/files'):backend.serve_clipboard_files,
        ('GET','/telemetry/prefs'):backend.serve_prefs,
        ('PUT','/telemetry/prefs'):backend.update_prefs,
    }
    for (method,path), handler in local.items():
        if method == 'GET':app.router.add_get(path, handler)
        else:app.router.add_route(method, path, handler)
    app.router.add_get('/telemetry/health', integration.health)
    app.router.add_get('/ws', backend.websocket_handler)
    for method,path in integration.api_routes:
        if method == 'GET':app.router.add_get(path, integration.proxy)
        else:app.router.add_route(method, path, integration.proxy)
    app.router.add_route('*','/network', integration.network)
    app.router.add_route('*','/network/{tail:.*}', integration.network)
    app.router.add_route('*','/{tail:.*}', integration.static_file)
    return app
