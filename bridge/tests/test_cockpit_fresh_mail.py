"""Fresh cockpit Mail consumes the pinned Telemetry reader, never SQLite."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
from uuid import uuid4

import pytest
from aiohttp import ClientSession, ClientTimeout, web

BRIDGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BRIDGE))
import orrery_backend as ob


def test_real_telemetry_handler_to_cockpit_mail_shape_and_no_legacy_fallback(tmp_path,monkeypatch):
    telemetry=Path(os.environ['ORRERY_TEST_TELEMETRY_ROOT']).resolve()
    sys.path[:0]=[str(telemetry),str(telemetry/'packages/agentstack_mail/src')]
    from agentstack_mail.fresh_runtime import FreshRuntime, _read_private
    from agentstack_mail.fresh_client import FreshBoundClient
    from dashboard.fresh_backend import Backend

    async def run():
        runtime=await FreshRuntime.initialize(tmp_path/'fresh')
        server=thread=None;runner=None;session=None
        try:
            people=[await runtime.register_local(request_id=str(uuid4()),name=name,
                       program='fixture',model='fixture') for name in ('Alpha','Beta')]
            async def dispatch(endpoint,tool,args):
                assert tool=='reconnect'
                return await runtime.core.owner('reconnect',**args)
            parent=await FreshBoundClient.prepare(runtime.root/'config.json',people[0]['binding_path'],
                'http://127.0.0.1:18766/mcp',client_id=str(uuid4()),dispatch=dispatch)
            proof=_read_private(Path(people[0]['binding_path']))
            await runtime.core.write_message('send',expected_server_instance_id=runtime.config['instance_id'],
                auth=dict(actor_agent_id=proof['mail_agent_id'],registration_token=proof['registration_token'],
                          expected_credential_generation=proof['credential_generation']),
                request_id=str(uuid4()),recipients=[{'target_name':'Beta'}],subject='cockpit fixture',
                body_md='Visible private fixture body',thread_id='fixture-thread')
            monkeypatch.setenv('AGENTSTACK_RUNTIME_MODE','fresh')
            monkeypatch.setenv('AGENTSTACK_FRESH_CLIENT_CONTEXT',str(parent.path))
            monkeypatch.setenv('AGENTSTACK_HOME',str(tmp_path/'no-live-stack'))
            monkeypatch.delenv('AGENTSTACK_CLIENT_CONFIG',raising=False)
            monkeypatch.delenv('AGENTSTACK_GLOBAL_SERVER_CONFIG',raising=False)
            spec=importlib.util.spec_from_file_location('private_reader_server_'+uuid4().hex,telemetry/'dashboard/server.py')
            module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
            spec.loader.exec_module(module)
            module._FRESH_BACKEND=Backend(parent.path,telemetry)
            assert module.DB_PATH==''
            server=module.ThreadingHTTPServer(('127.0.0.1',0),module.Handler)
            assert server.server_port not in {8765,8770,8781,8791}
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            monkeypatch.setenv('ORRERY_DASHBOARD_URL','http://127.0.0.1:'+str(server.server_port))
            monkeypatch.setenv('ORRERY_FRESH_MAIL_INSTANCE_ID',runtime.config['instance_id'])
            def forbidden(*args,**kwargs):pytest.fail('fresh reader entered legacy SQLite')
            for name in ('mail_connection','query_mail_recent','query_mail_message','query_mail_thread'):
                monkeypatch.setattr(ob,name,forbidden)
            app=web.Application()
            session=ClientSession(timeout=ClientTimeout(total=5));app[ob.HTTP_SESSION_KEY]=session
            app.router.add_get('/recent',ob.serve_mail_recent)
            app.router.add_get('/message',ob.serve_mail_message)
            app.router.add_get('/thread',ob.serve_mail_thread)
            runner=web.AppRunner(app);await runner.setup()
            site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
            base='http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])
            async with ClientSession() as browser:
                async with browser.get(base+'/recent?agent=Beta') as response:
                    assert response.status==200
                    recent=await response.json()
                item=recent['messages'][0]
                assert item['sender']=='Alpha' and item['recipients'][0]['name']=='Beta'
                assert item['excerpt']=='Visible private fixture body' and 'body_md' not in item
                assert item['mail_instance_id']==runtime.config['instance_id'] and type(item['sender_agent_id']) is int
                async with browser.get(base+'/message?id='+str(item['id'])) as response:
                    assert response.status==200
                    detail=await response.json()
                assert detail['message']['body_md']=='Visible private fixture body'
                async with browser.get(base+'/thread?thread_id=fixture-thread') as response:
                    assert response.status==200 and (await response.json())['messages']==recent['messages']
                for path in ('/recent?endpoint=http://evil.invalid','/recent?mail_instance_id='+'0'*32):
                    async with browser.get(base+path) as response:assert response.status==400
                for path in ('/recent?limit=101','/thread','/message?id=invalid'):
                    async with browser.get(base+path) as response:assert response.status==400
                async with browser.get(base+'/message?id=999999') as response:assert response.status==404
                monkeypatch.setenv('ORRERY_FRESH_MAIL_INSTANCE_ID','0'*32)
                async with browser.get(base+'/recent') as response:assert response.status==409
                monkeypatch.delenv('ORRERY_FRESH_MAIL_INSTANCE_ID')
                async with browser.get(base+'/recent') as response:assert response.status==503
                assert 'registration_token' not in json.dumps([recent,detail])
            await app[ob.HTTP_SESSION_KEY].close()
        finally:
            if session:await session.close()
            if runner:await runner.cleanup()
            if server:
                server.shutdown();server.server_close();thread.join(timeout=5)
                assert not thread.is_alive()
            await runtime.close()
    asyncio.run(run())

