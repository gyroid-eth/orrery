"""Global HTTP/WS boundary with the installed Telemetry admission, no live state."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import runpy
import shutil

from aiohttp import ClientSession, WSMsgType, web
from yarl import URL
import pytest
import orrery_backend as backend
from global_cockpit import GlobalCockpit

TELEMETRY = Path(os.environ.get('ORRERY_TEST_TELEMETRY_ROOT', Path(__file__).resolve().parents[2]/'.telemetry'))


@asynccontextmanager
async def serving(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    try:
        yield 'http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
    finally:
        await runner.cleanup()


@pytest.fixture
def global_setup(tmp_path, monkeypatch):
    home = tmp_path/'agentstack'
    home.mkdir(mode=0o700)
    (home/'dashboard').mkdir()
    shutil.copy2(TELEMETRY/'dashboard/http_operator.py', home/'dashboard/http_operator.py')
    helper = runpy.run_path(str(home/'dashboard/http_operator.py'))
    helper['configure'](home)
    token = helper['read_capability'](home)
    monkeypatch.setenv('AGENTSTACK_HOME', str(home))
    monkeypatch.setenv('AGENTSTACK_RUNTIME_MODE', 'global')
    monkeypatch.setenv('AGENTSTACK_GLOBAL_SERVER_CONFIG', str(tmp_path/'server-config.json'))
    calls = []
    proof = dict(binding={'expected_server_instance_id':'fixture', 'candidate_generation':'fixture', 'authority_epoch':'fixture'},
                 telemetry_api=18, capabilities={'global_runtime_observation':1, 'operator_session':1})

    async def probe(self):
        return proof

    class Manager:
        def __init__(self, *args):pass
        async def start(self):pass
        async def close(self):pass
        async def disconnect(self, peer, attached):pass
        async def handle_message(self, peer, attached, payload):calls.append(payload)

    monkeypatch.setattr(GlobalCockpit, 'probe', probe)
    monkeypatch.setattr(backend, 'SessionBridgeManager', Manager)
    monkeypatch.setattr(backend, 'list_tmux_sessions', lambda *args:[])
    monkeypatch.setattr(backend.sqlite3, 'connect', lambda *args, **kwargs:pytest.fail('global SQLite opened'))
    monkeypatch.setattr(backend, 'MAIL_DB', tmp_path/'not-a-database')
    return token, calls, proof


def test_all_nonstatic_routes_use_shared_admission(global_setup):
    async def scenario():
        async with serving(backend.create_app()) as origin, ClientSession() as client:
            paths = [row[1] for row in __import__('global_cockpit').FIXTURE['proxy_map']]
            paths += ['/telemetry/'+x for x in ('open-url','reveal-path','open-ghostty','path-probe','fs/dirs','clipboard/files','sessions','prefs','health')]
            paths += ['/api/exit', '/future-route', '/orrery_backend.py', '/tests/', '/telemetry/mail/recent']
            for method in ('GET','POST','PUT','DELETE','OPTIONS'):
                for path in paths:
                    async with client.request(method, origin+path) as reply:
                        assert reply.status == 403, (method,path,await reply.text())
            async with client.get(origin+'/cockpit.html') as reply:assert reply.status == 200
            for headers in ({'Host':'evil.example'},{'Origin':'http://evil.example'},{'Sec-Fetch-Site':'cross-site'}):
                async with client.get(origin+'/telemetry/health',headers={'Authorization':'Bearer '+global_setup[0],**headers}) as reply:
                    assert reply.status == 403
            for path in ('/orrery_backend.py','/tests/','/global_cockpit_contract.json','/telemetry/mail/recent','/api/exit'):
                async with client.get(origin+path,headers={'Authorization':'Bearer '+global_setup[0]}) as reply:
                    assert reply.status == 404
    asyncio.run(scenario())


@pytest.mark.parametrize('frame', [None, {'type':'attach','session':'fixture'}, {'type':'authenticate','version':1,'capability':'x'}, {'type':'authenticate','version':True,'capability':'x'}, b'bytes'])
def test_socket_has_no_dispatch_before_authentication(global_setup, frame):
    async def scenario():
        app=backend.create_app()
        async with serving(app) as origin, ClientSession() as client:
            async with client.ws_connect(origin+'/ws',headers={'Origin':origin}) as ws:
                if isinstance(frame,bytes):await ws.send_bytes(frame)
                elif frame is not None:await ws.send_json(frame)
                reply = await ws.receive(timeout=7)
                assert reply.type == WSMsgType.CLOSE and ws.close_code == 4401
                assert not global_setup[1]
                assert app[backend.GLOBAL_COCKPIT_KEY]._manager is None
    asyncio.run(scenario())


def test_socket_authentication_precedes_sessions_and_duplicate_auth_closes(global_setup):
    async def scenario():
        async with serving(backend.create_app()) as origin, ClientSession() as client:
            async with client.ws_connect(origin+'/ws',headers={'Origin':origin}) as ws:
                frame=dict(type='authenticate',version=1,capability=global_setup[0])
                await ws.send_json(frame)
                assert await ws.receive_json() == dict(type='authenticated',version=1)
                assert (await ws.receive_json())['type'] == 'sessions'
                await ws.send_json(frame)
                assert (await ws.receive()).type == WSMsgType.CLOSE
                assert not global_setup[1]
    asyncio.run(scenario())


def test_proxy_rebuilds_headers_refuses_redirects_and_preserves_query(global_setup, monkeypatch):
    async def scenario():
        seen=[]
        async def upstream(request):
            seen.append((request.raw_path,dict(request.headers)))
            if request.path == '/api/agents':raise web.HTTPFound('http://invalid.example/')
            return web.json_response(dict(ok=True,fixture=True))
        app=web.Application();app.router.add_route('*','/{tail:.*}',upstream)
        async with serving(app) as upstream_origin:
            monkeypatch.setattr(backend,'DASHBOARD_URL',upstream_origin)
            async with serving(backend.create_app()) as origin, ClientSession() as client:
                headers={'Authorization':'Bearer '+global_setup[0],'Origin':origin,'X-Should-Not-Forward':'private'}
                async with client.get(URL(origin+'/api/mail/recent?view_as_agent_id=2&cursor=a%2Bb%2Fc',encoded=True),headers=headers) as reply:
                    assert reply.status == 200
                assert seen[-1][0].endswith('cursor=a%2Bb%2Fc')
                assert seen[-1][1]['Origin'] == upstream_origin
                assert 'X-Should-Not-Forward' not in seen[-1][1]
                async with client.get(origin+'/api/agents',headers=headers) as reply:assert reply.status == 502
                async with client.get(origin+'/api/mail/recent?view_as_agent_id=2&view_as_agent_id=3',headers=headers) as reply:assert reply.status == 400
                async with client.get(origin+'/telemetry/health',headers=headers) as reply:
                    health=await reply.json();assert health['api']==1 and health['upstream']['binding']==global_setup[2]['binding']
                    assert health['capabilities']['websocket_first_frame_auth']==1
    asyncio.run(scenario())


def test_global_html_uses_installed_controllers_and_only_global_driver(global_setup):
    async def scenario():
        async with serving(backend.create_app()) as origin,ClientSession() as client:
            async with client.get(origin+'/cockpit.html') as reply:
                body=await reply.text()
                assert 'window.ORRERY_GLOBAL_MODE=true' in body
                for name in ('operator_session','mail_controller','operation_controller','runtime_node'):
                    assert 'src="/network/'+name+'.js"' in body
                    assert not (backend.HERE/(name+'.js')).exists()
                for name in ('prefs_sync','mail_view','orrery_view'):
                    assert 'src="'+name+'.js"' not in body
            for asset in ('/global_cockpit.js','/global_cockpit.css'):
                async with client.get(origin+asset) as reply:assert reply.status==200
    asyncio.run(scenario())


@pytest.mark.parametrize('frame',[
    {'type':'authenticate','version':1,'capability':'x'*1100},
    {'type':'authenticate','version':1,'capability':'x','extra':1},
    {'type':'authenticate','version':2,'capability':'x'},
])
def test_socket_rejects_oversize_extra_and_wrong_version(global_setup,frame):
    async def scenario():
        async with serving(backend.create_app()) as origin,ClientSession() as client:
            async with client.ws_connect(origin+'/ws',headers={'Origin':origin}) as ws:
                await ws.send_json(frame)
                assert (await ws.receive()).type==WSMsgType.CLOSE and ws.close_code==4401
                assert not global_setup[1]
    asyncio.run(scenario())


def test_health_fails_closed_when_upstream_proof_changes(global_setup,monkeypatch):
    async def scenario():
        async with serving(backend.create_app()) as origin,ClientSession() as client:
            global_setup[2]['binding']={'expected_server_instance_id':'different'}
            # Replace the startup object, preserving its initial bound evidence.
            integration=__import__('global_cockpit')
            async def bad(self):raise ValueError('unavailable config')
            monkeypatch.setattr(integration.GlobalCockpit,'probe',bad)
            async with client.get(origin+'/telemetry/health',headers={'Authorization':'Bearer '+global_setup[0]}) as reply:
                assert reply.status==503 and (await reply.json())['reason']=='COCKPIT_GLOBAL_CAPABILITY_REQUIRED'
    asyncio.run(scenario())


def test_health_detects_new_binding_without_rebinding(global_setup,monkeypatch):
    async def scenario():
        async with serving(backend.create_app()) as origin,ClientSession() as client:
            async def changed(self):return {**global_setup[2],'binding':{'expected_server_instance_id':'other'}}
            monkeypatch.setattr(GlobalCockpit,'probe',changed)
            async with client.get(origin+'/telemetry/health',headers={'Authorization':'Bearer '+global_setup[0]}) as reply:
                assert reply.status==503 and (await reply.json())['reason']=='MANAGEMENT_BINDING_MISMATCH'
    asyncio.run(scenario())
