"""Outside-sandbox check: only a dedicated tmux server and synthetic shell."""
import asyncio
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import tempfile

from aiohttp import ClientSession
import pytest
import orrery_backend as backend
from test_global_cockpit import global_setup, serving

REAL_MANAGER=backend.SessionBridgeManager
REAL_LIST=backend.list_tmux_sessions


@pytest.mark.skipif(not shutil.which('tmux'),reason='tmux required')
def test_authenticated_socket_uses_own_tmux_and_detaches(global_setup,tmp_path,monkeypatch):
    tmux=shutil.which('tmux');label='orrery-global-test-'+secrets.token_hex(6)
    # UNIX socket paths stay short even with a deep TMPDIR on WSL.
    socket_root=Path(tempfile.mkdtemp(prefix='oc-',dir='/tmp'));socket_root.chmod(0o700)
    monkeypatch.setenv('TMUX_TMPDIR',str(socket_root))
    monkeypatch.setenv('ORRERY_HISTORY_DIR',str(tmp_path/'history'))
    monkeypatch.delenv('TMUX',raising=False)
    wrapper=tmp_path/'tmux';wrapper.write_text('#!/bin/sh\nexec '+shlex.quote(tmux)+' -L '+shlex.quote(label)+' "$@"\n');wrapper.chmod(0o700)
    monkeypatch.setattr(backend,'SessionBridgeManager',REAL_MANAGER)
    monkeypatch.setattr(backend,'list_tmux_sessions',REAL_LIST)
    subprocess.run([str(wrapper),'new-session','-d','-s','SyntheticTerminal','/bin/sh'],check=True,capture_output=True)
    async def scenario():
        app=backend.create_app(str(wrapper))
        async with serving(app) as origin,ClientSession() as client:
            assert app[backend.GLOBAL_COCKPIT_KEY]._manager is None
            async with client.ws_connect(origin+'/ws',headers={'Origin':origin}) as ws:
                await ws.send_json(dict(type='authenticate',version=1,capability=global_setup[0]))
                assert (await ws.receive_json(timeout=15))['type']=='authenticated'
                sessions=await ws.receive_json(timeout=15)
                assert [item['session'] for item in sessions['sessions']]==['SyntheticTerminal']
                await ws.send_json(dict(type='attach',session='SyntheticTerminal'))
                async with asyncio.timeout(15):
                    while True:
                        reply=await ws.receive_json()
                        if reply['type']=='reset':
                            assert reply['panes'],reply
                            break
                        assert reply['type']!='error',reply
                await ws.send_json(dict(type='detach',session='SyntheticTerminal'))
    try:asyncio.run(scenario())
    finally:
        subprocess.run([str(wrapper),'kill-server'],capture_output=True)
        shutil.rmtree(socket_root)
