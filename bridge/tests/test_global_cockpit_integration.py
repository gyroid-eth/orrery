"""Cockpit → installed shared HTTP contract → real isolated S2c socket."""
import asyncio
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import threading
from http.server import ThreadingHTTPServer

from aiohttp import ClientSession
import pytest
import orrery_backend as backend
from test_global_cockpit import TELEMETRY, serving

# Consume the canonical synthetic fixture, rather than creating a second DB
# schema or server in this repository. This checkout is pinned in CI.
sys.path.insert(0,str(TELEMETRY))
sys.path.insert(0,str(TELEMETRY/'tests'))
from test_global_child_client import server
from _installed_client_payload import copy_client_library
from dashboard import server as telemetry_http
from dashboard.http_operator import configure, read_capability


@pytest.fixture
def installed(server,monkeypatch):
    home=server['root']/'agentstack'
    home.mkdir(mode=0o700,exist_ok=True)
    copy_client_library(home)
    (home/'dashboard').mkdir(exist_ok=True)
    shutil.copy2(TELEMETRY/'dashboard/http_operator.py',home/'dashboard/http_operator.py')
    configure(home)
    monkeypatch.setenv('AGENTSTACK_HOME',str(home))
    monkeypatch.setenv('AGENTSTACK_RUNTIME_MODE','global')
    monkeypatch.setenv('AGENTSTACK_GLOBAL_SERVER_CONFIG',str(server['config_path']))
    monkeypatch.setenv('AGENTSTACK_MCP_URL',server['url'])
    monkeypatch.setenv('AGENTSTACK_LABEL_PREFIX','org.agentstack.test.cockpit-global')
    monkeypatch.setattr(telemetry_http,'GLOBAL_MODE',True)
    monkeypatch.setattr(telemetry_http,'BIND_HOST','127.0.0.1')
    http=ThreadingHTTPServer(('127.0.0.1',0),telemetry_http.Handler)
    worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    origin='http://127.0.0.1:'+str(http.server_port)
    monkeypatch.setattr(backend,'DASHBOARD_URL',origin)
    monkeypatch.setenv('ORRERY_DASHBOARD_URL',origin)
    # No tmux or provider is needed to validate the HTTP bridge.
    monkeypatch.setattr(backend,'list_tmux_sessions',lambda *a:[])
    def forbidden(*a,**kw):raise AssertionError('cockpit SQLite opened')
    # Telemetry and S2c share sqlite3 in-process; guard the cockpit's reference
    # rather than replacing the process-wide sqlite3 module.
    class NoSQLite:
        connect=staticmethod(forbidden)
    monkeypatch.setattr(backend,'sqlite3',NoSQLite)
    monkeypatch.setattr(backend,'MAIL_DB',server['root']/'not-a-database')
    try:yield server,home,read_capability(home)
    finally:http.shutdown();http.server_close();worker.join(timeout=5)


def test_real_shared_proof_mail_bridge_assets_and_operator_status(installed):
    state,home,token=installed
    async def scenario():
        async with serving(backend.create_app()) as origin,ClientSession() as client:
            headers={'Authorization':'Bearer '+token,'Origin':origin}
            async def get(path):
                async with client.get(origin+path,headers=headers) as response:
                    raw=await response.read();assert response.status==200,(path,response.status,raw)
                    return json.loads(raw)
            health=await get('/telemetry/health')
            assert health['runtime_mode']=='global' and health['api']==1
            assert health['upstream']['binding']=={'expected_server_instance_id':state['config']['mail_instance_id'], 'candidate_generation':state['config']['candidate_generation'], 'authority_epoch':state['config']['authority_epoch']}
            assert health['capabilities']==dict(operator_http_admission=1,global_mail_bridge=1,
                instruction_migration=1,websocket_first_frame_auth=1,global_runtime_observation=1)
            proof=await asyncio.to_thread(runpy.run_path(str(home/'dashboard/http_operator.py'))['probe'],home,
                service='cockpit',telemetry_url=backend.DASHBOARD_URL,cockpit_port=int(origin.rsplit(':',1)[1]),config_path=str(state['config_path']))
            assert proof['cockpit_ready'] is True and proof['cutover_ready'] is False
            page=await get('/api/mail/recent?view_as_agent_id=2&limit=1')
            mid=page['data']['items'][0]['id']
            message=await get('/api/mail/message?view_as_agent_id=2&id='+str(mid))
            assert isinstance(message['data']['body_md'],str)
            assert (await get('/api/agents?limit=1'))['data']['items']
            assert (await get('/api/global/spawn-status?client_name=missing'))['stage']=='absent'
            for asset in ('operator_session.js','mail_controller.js','operation_controller.js','mail_flow.js','mail_flow.css','runtime_node.js'):
                async with client.get(origin+'/network/'+asset) as response:
                    assert response.status==200
                    assert await response.read()==(TELEMETRY/'dashboard'/asset).read_bytes()
            async with client.get(origin+'/api/mail/recent',headers=headers) as response:
                assert response.status==400 and (await response.json())['reason']=='UI_VIEWPOINT_REQUIRED'
            async with client.post(origin+'/api/global/registration-abandon',headers=headers,json={'client_name':'missing','expected_digest':'0'*64}) as response:
                assert response.status in (404,409)
                assert (await response.json())['reason']=='TARGET_UNAVAILABLE'
    asyncio.run(scenario())
