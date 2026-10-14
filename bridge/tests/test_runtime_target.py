"""Legacy consumer protection against actual, installer-declared shared code.

Set ORRERY_TEST_TELEMETRY_ROOT to the pinned Telemetry fixture checkout. CI
checks it out outside this repository; product code is never copied here.
"""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_target import LegacyTargetBoundary, TargetRefused, require_target, tmux_argv, tmux_env
from control_server import ControlConfig, TmuxControlBridge, ensure_tmux_session


@pytest.fixture
def endpoint(monkeypatch):
    real_popen = subprocess.Popen
    binary = shutil.which('tmux')
    if not binary:
        pytest.skip('tmux is not installed')
    base = '/private/tmp' if Path('/private/tmp').is_dir() else tempfile.gettempdir()
    with tempfile.TemporaryDirectory(prefix='ct-', dir=base) as directory:
        home = Path(directory)/'home';home.mkdir(mode=0o700)
        sockets = Path(directory)/'s';sockets.mkdir(mode=0o700)
        for key in list(os.environ):
            if key.startswith(('AGENTSTACK_', 'MCP_AGENT_')) or key in ('TMUX','TMUX_PANE','AGENT_NAME','PARENT_AGENT','CHILD_REGISTRATION_TOKEN'):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv('HOME', str(home))
        monkeypatch.setenv('AGENTSTACK_HOME', str(home))
        monkeypatch.setenv('AGENTSTACK_LABEL_PREFIX','org.agentstack.test.cockpit-target')
        monkeypatch.setenv('TMUX_TMPDIR',str(sockets))
        label = 'fixture-' + uuid.uuid4().hex[:8]
        prefix = [binary,'-L',label]
        subprocess.run([*prefix,'new-session','-d','-s','orrery-normal','sleep','600'], check=True)
        try:
            result = subprocess.run([*prefix,'list-panes','-t','=orrery-normal','-F',
                '#{socket_path}\t#{pid}\t#{pane_id}\t#{pane_pid}'], capture_output=True,text=True,check=True)
            socket,server,pane,pid = result.stdout.strip().split('\t')
            prefix = [binary,'-S',socket]
            audit=os.environ.get('ORRERY_TARGET_FIXTURE_AUDIT')
            if audit:
                with Path(audit).open('a') as out:out.write(json.dumps({'event':'created','label':label,'server_pid':int(server),'socket':socket})+'\n')
            env = {**os.environ,'TMUX':socket+','+server+',0','TMUX_PANE':pane}
            yield {'home':home,'binary':binary,'prefix':prefix,'env':env,'socket':socket,'pane':pane,'pid':int(pid)}
        finally:
            cleanup=real_popen([*prefix,'kill-server'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            cleanup.communicate(timeout=5)
            if os.environ.get('ORRERY_TARGET_FIXTURE_AUDIT'):
                with Path(os.environ['ORRERY_TARGET_FIXTURE_AUDIT']).open('a') as out:
                    out.write(json.dumps({'event':'cleaned','label':label,'cleanup_exit':cleanup.returncode})+'\n')


def telemetry_root():
    value = os.environ.get('ORRERY_TEST_TELEMETRY_ROOT')
    if not value:
        pytest.fail('Set ORRERY_TEST_TELEMETRY_ROOT to the pinned shared-contract fixture checkout')
    root = Path(value).resolve()
    assert (root/'bin/lib/runtime_tmux.py').is_file()
    return root


def deploy(home):
    root = telemetry_root()
    loader = runpy.run_path(str(root/'tests/_installed_client_payload.py'))
    loader['copy_client_library'](home)


@pytest.mark.parametrize('helper',['missing','old','broken','actual'])
def test_pure_legacy_operation_and_explicit_endpoint_are_preserved(endpoint,helper):
    home=endpoint['home'];library=home/'bin/lib'
    if helper=='actual':
        deploy(home)
    elif helper!='missing':
        library.mkdir(parents=True)
        (library/'runtime_tmux.py').write_text('CONTRACT="old"\nCAPABILITIES=[]\n' if helper=='old' else 'raise RuntimeError("fixture")\n')
    boundary=LegacyTargetBoundary(endpoint['binary'],home=home,environ=endpoint['env'])
    if helper=='actual':
        # Schema/consumer test only. The OS process-start proof has its own
        # outside node in the shared contract suite.
        original=boundary.shared['legacy_admission']
        api=runpy.run_path(str(library/'runtime_client.py'))
        api['process_start']=lambda *args,**kwargs:'fixture-start'
        boundary.shared['legacy_admission']=lambda *args,**kwargs:original(*args,**{**kwargs,'api':api})
    require_target(boundary,'split',pane=endpoint['pane'])
    assert tmux_argv(boundary,'display-message') == ([endpoint['binary'],'-S',endpoint['socket'],'display-message'] if helper=='actual' else [endpoint['binary'],'display-message'])
    if helper=='actual':
        assert 'TMUX' not in tmux_env(boundary)['env']
        assert 'TMUX_PANE' not in tmux_env(boundary)['env']
    else:
        assert tmux_env(boundary)['env']['TMUX']==endpoint['env']['TMUX']


@pytest.mark.parametrize('helper',['missing','old','broken','actual'])
def test_partial_global_root_refuses_input_without_hiding_roster(endpoint,helper):
    home=endpoint['home'];(home/'clients/partial').mkdir(parents=True,mode=0o700)
    (home/'clients').chmod(0o700)
    library=home/'bin/lib'
    if helper=='actual':deploy(home)
    elif helper!='missing':
        library.mkdir(parents=True)
        (library/'runtime_tmux.py').write_text('CONTRACT="old"\nCAPABILITIES=[]\n' if helper=='old' else 'raise RuntimeError("fixture")\n')
    boundary=LegacyTargetBoundary(endpoint['binary'],home=home,environ=endpoint['env'])
    with pytest.raises(TargetRefused,match='GLOBAL_TARGET_(HELPER_UNAVAILABLE|OWNERSHIP_UNKNOWN)'):
        boundary.admit('input',pane=endpoint['pane'])
    result=subprocess.run(tmux_argv(boundary,'list-sessions','-F','#{session_name}'),
        capture_output=True,text=True,check=True,**tmux_env(boundary))
    assert result.stdout.strip()=='orrery-normal'


def test_control_write_refusal_precedes_pty_bytes(endpoint,monkeypatch):
    (endpoint['home']/'clients').mkdir(mode=0o700)
    boundary=LegacyTargetBoundary(endpoint['binary'],home=endpoint['home'],environ=endpoint['env'])
    bridge=TmuxControlBridge(ControlConfig('127.0.0.1',0,'orrery-normal',boundary))
    bridge.master_fd=123  # no OS fd is opened or written in this test
    writes=[]
    async def write(payload):writes.append(payload)
    monkeypatch.setattr(bridge,'_write_master',write)
    with pytest.raises(TargetRefused,match='GLOBAL_TARGET_HELPER_UNAVAILABLE'):
        asyncio.run(bridge.send_command(['kill-pane','-t',endpoint['pane']],wait=False))
    assert writes==[] and not bridge._pending_blocks


def test_global_standalone_is_refused_and_normal_legacy_continues(endpoint,monkeypatch):
    root=telemetry_root()
    for path in (root/'tests',root/'packages/agentstack_mail/tests',root/'packages/agentstack_mail/src'):
        monkeypatch.syspath_prepend(str(path))
    spec=importlib.util.spec_from_file_location('shared_target_operator_fixture',root/'tests/test_global_operator_client.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    server=fixture.server.__wrapped__(monkeypatch)
    try:
        state=next(server)
        monkeypatch.setenv('AGENTSTACK_MCP_URL',state['url'])
        operator=fixture.api['RuntimeOperator'](state['config_path'])
        operator.create('protected',agent_name='ProtectedFixture',program='daemon',model='deterministic')
        client=operator.client('protected')
        with client.operation_mutex():pass
        lives=client.runtime_dir/'live-sessions';lives.mkdir(mode=0o700,exist_ok=True)
        live={'kind':'orrery-global-live-session-v1',**client.binding,'agent_id':client.identity['agent_id'],
              'session_id':'standalone','pid':endpoint['pid'],'process_start':'fixture-start','pane_id':endpoint['pane']}
        operator.api['atomic_json'](lives/'standalone.json',live)
        home=operator.clients_parent.parent;deploy(home)
        boundary=LegacyTargetBoundary(endpoint['binary'],home=home,environ=endpoint['env'])
        original=boundary.shared['legacy_admission']
        api=operator.api;api['process_start']=lambda *args,**kwargs:'fixture-start'
        boundary.shared['legacy_admission']=lambda *args,**kwargs:original(*args,**{**kwargs,'api':api})
        before=operator.read({'kind':'health'})['as_of_revision']
        for operation in ('attach','input','split','close','kill-session','signal'):
            with pytest.raises(TargetRefused,match='LEGACY_TARGET_IS_GLOBAL'):
                boundary.admit(operation,pane=endpoint['pane'])
        subprocess.run([*endpoint['prefix'],'new-session','-d','-s','normal-other','sleep','600'],check=True,env=boundary.env())
        assert boundary.admit('input',session='normal-other')['allowed'] is True
        assert operator.read({'kind':'health'})['as_of_revision']==before
        assert not client.outputs['launch'].exists()
    finally:
        server.close()


def test_uncertain_placement_refuses_auxiliary_creation_before_new_session(endpoint):
    (endpoint['home']/'clients').mkdir(mode=0o700)
    boundary=LegacyTargetBoundary(endpoint['binary'],home=endpoint['home'],environ=endpoint['env'])
    with pytest.raises(TargetRefused,match='GLOBAL_TARGET_HELPER_UNAVAILABLE'):
        ensure_tmux_session(boundary,'orrery-new-fixture',create=True)
    result=subprocess.run([*endpoint['prefix'],'has-session','-t','=orrery-new-fixture'],capture_output=True)
    assert result.returncode!=0


@pytest.mark.parametrize('partial',[False,True])
def test_internal_helper_failure_uses_negative_admission(endpoint,partial):
    home=endpoint['home'];deploy(home)
    if partial:(home/'clients').mkdir(mode=0o700)
    boundary=LegacyTargetBoundary(endpoint['binary'],home=home,environ=endpoint['env'])
    def broken(*args,**kwargs):raise KeyError('fixture')
    boundary.shared['legacy_admission']=broken
    if partial:
        with pytest.raises(TargetRefused,match='GLOBAL_TARGET_HELPER_UNAVAILABLE'):
            boundary.admit('input',pane=endpoint['pane'])
    else:
        boundary.admit('input',pane=endpoint['pane'])


def test_restarted_server_reply_is_not_accepted_as_the_pinned_server(endpoint):
    deploy(endpoint['home'])
    boundary=LegacyTargetBoundary(endpoint['binary'],home=endpoint['home'],environ=endpoint['env'])
    class Replaced:
        def public(self):return {**boundary.transport.public(),'server_pid':boundary.pin['server_pid']+1}
    boundary.shared['legacy_transport']=lambda **kwargs:Replaced()
    with pytest.raises(TargetRefused,match='TMUX_SOCKET_CHANGED'):
        boundary.admit('input',pane=endpoint['pane'])


@pytest.mark.parametrize('helper',['missing','actual'])
def test_dedicated_socket_is_never_a_legacy_startup(endpoint,helper):
    if helper=='actual':deploy(endpoint['home'])
    socket=Path('/tmp').resolve()/('orrery-tmux-'+str(os.getuid()))/'fixture.sock'
    with pytest.raises(TargetRefused,match='GLOBAL_TMUX_LEGACY_CONSUMER_REFUSED'):
        LegacyTargetBoundary(endpoint['binary'],home=endpoint['home'],
            environ={**endpoint['env'],'TMUX':str(socket)+',123,0'})


def test_closed_probe_uses_one_explicit_transport_for_all_three_queries(endpoint,monkeypatch):
    deploy(endpoint['home'])
    import control_server
    from types import SimpleNamespace
    boundary=LegacyTargetBoundary(endpoint['binary'],home=endpoint['home'],environ=endpoint['env'])
    calls=[]
    def run(argv,**kwargs):
        calls.append((argv,kwargs))
        return SimpleNamespace(returncode=0 if 'show-options' in argv else 1,stdout='')
    monkeypatch.setattr(control_server.subprocess,'run',run)
    assert control_server.tmux_session_gone(boundary,'orrery-normal') is True
    assert [x[0][3] for x in calls]==['has-session','list-sessions','show-options']
    for argv,kwargs in calls:
        assert argv[:3]==[endpoint['binary'],'-S',endpoint['socket']]
        assert 'TMUX' not in kwargs['env'] and 'TMUX_PANE' not in kwargs['env']


def test_attach_refusal_precedes_pty_creation(endpoint,monkeypatch):
    import control_server
    (endpoint['home']/'clients').mkdir(mode=0o700)
    boundary=LegacyTargetBoundary(endpoint['binary'],home=endpoint['home'],environ=endpoint['env'])
    bridge=TmuxControlBridge(ControlConfig('127.0.0.1',0,'orrery-normal',boundary))
    def unexpected():raise AssertionError('refused attach opened a PTY')
    monkeypatch.setattr(control_server.pty,'openpty',unexpected)
    with pytest.raises(TargetRefused,match='GLOBAL_TARGET_HELPER_UNAVAILABLE'):
        asyncio.run(bridge.start())


def test_terminal_argv_carries_the_pinned_linux_socket(endpoint,monkeypatch):
    deploy(endpoint['home'])
    import orrery_backend as backend
    boundary=LegacyTargetBoundary(endpoint['binary'],home=endpoint['home'],environ=endpoint['env'])
    admitted=[];spawned=[];opened=[]
    monkeypatch.setattr(backend,'require_target',lambda value,op,**kw:admitted.append((value,op,kw)))
    monkeypatch.setattr(backend.subprocess,'Popen',lambda argv,**kw:spawned.append((argv,kw)))
    monkeypatch.setattr(backend,'wsl_terminal_problem',lambda:None)
    monkeypatch.setattr(backend,'wsl_distro',lambda:'FixtureLinux')
    monkeypatch.setattr(backend,'run_opener',lambda argv:opened.append(argv))
    backend.launch_ghostty(boundary,'orrery-normal')
    backend.launch_windows_terminal(boundary,'orrery-normal')
    assert spawned[0][0][-6:]==[endpoint['binary'],'-S',endpoint['socket'],'attach','-t','=orrery-normal']
    assert 'TMUX' not in spawned[0][1]['env']
    assert opened[0]==['wt.exe','-w','0','new-tab','--title','orrery-normal','wsl.exe','-d','FixtureLinux',
        '--exec','env','-u','TMUX','-u','TMUX_PANE',endpoint['binary'],'-S',endpoint['socket'],'attach','-t','=orrery-normal']
    assert admitted==[(boundary,'attach',{'session':'orrery-normal'})]*2


@pytest.mark.parametrize('global_hint',[False,True])
def test_released_literal_reader_keeps_legacy_and_refuses_unknown_global(endpoint,global_hint):
    home=endpoint['home'];hooks=home/'hooks';hooks.mkdir(mode=0o700)
    released=subprocess.check_output(['git','show','2026.10.06:hooks/project-context.sh'],cwd=telemetry_root(),text=True)
    (hooks/'project-context.sh').write_text(released)
    sentinel=home/'must-not-source'
    content="export AGENTSTACK_PROJECT_KEY='/fixture/project'\nexport AGENTSTACK_MCP_URL='http://127.0.0.1:1234/mcp'\n"
    content+='export UNRELATED=$(touch '+str(sentinel)+')\n'
    if global_hint:content+='export AGENTSTACK_GLOBAL_SERVER_CONFIG=/fixture/unknown/server-config.json\n'
    (home/'env.sh').write_text(content)
    boundary=LegacyTargetBoundary(endpoint['binary'],home=home,environ=endpoint['env'])
    if global_hint:
        with pytest.raises(TargetRefused,match='GLOBAL_TARGET_HELPER_UNAVAILABLE'):
            boundary.admit('input',pane=endpoint['pane'])
    else:
        boundary.admit('input',pane=endpoint['pane'])
    assert not sentinel.exists()



def test_paste_admission_is_once_per_input_not_per_64_bytes(monkeypatch):
    import control_server
    import time
    bridge=TmuxControlBridge(ControlConfig('127.0.0.1',0,'fixture','tmux'))
    bridge.master_fd=123
    checks=[];writes=[]
    def check(*args,**kwargs):
        checks.append(args)
        time.sleep(.01)  # a cheap stand-in for the real 150–320ms reader
    async def write(payload):writes.append(payload)
    monkeypatch.setattr(control_server,'admit_command',check)
    monkeypatch.setattr(bridge,'_write_master',write)
    start=time.monotonic()
    asyncio.run(bridge.send_input('%1','x'*4096))
    elapsed=time.monotonic()-start
    print('paste_admissions=',len(checks),'elapsed=',elapsed)
    assert len(checks)==1
    assert len(writes)==64 and len(bridge._pending_blocks)==64
    assert elapsed<.4


@pytest.mark.parametrize('installed_env',[False,True])
def test_100_keystrokes_reuse_pane_proof_with_bounded_latency(endpoint,monkeypatch,installed_env):
    import time
    deploy(endpoint['home'])
    if installed_env:
        (endpoint['home']/'env.sh').write_text('export AGENTSTACK_RUNTIME_MODE=legacy\n')
    boundary=LegacyTargetBoundary(endpoint['binary'],home=endpoint['home'],environ=endpoint['env'])
    original=boundary.shared['legacy_admission'];checks=[]
    api=runpy.run_path(str(endpoint['home']/'bin/lib/runtime_client.py'))
    api['process_start']=lambda *a,**kw:'fixture-start'
    def check(*a,**kw):
        checks.append(1)
        kw['api']=api
        return original(*a,**kw)
    boundary.shared['legacy_admission']=check
    bridge=TmuxControlBridge(ControlConfig('127.0.0.1',0,'orrery-normal',boundary))
    bridge.master_fd=123
    async def write(payload):pass
    monkeypatch.setattr(bridge,'_write_master',write)
    async def type_keys():
        for _ in range(100):await bridge.send_input(endpoint['pane'],'x')
    start=time.monotonic();asyncio.run(type_keys());elapsed=time.monotonic()-start
    print('keystroke_admissions=',len(checks),'elapsed=',elapsed)
    assert len(checks)<=2
    assert elapsed<3



def test_cached_input_rechecks_membership_expiry_and_destructive_operations(endpoint,monkeypatch):
    import runtime_target
    from types import SimpleNamespace
    deploy(endpoint['home'])
    boundary=LegacyTargetBoundary(endpoint['binary'],home=endpoint['home'],environ=endpoint['env'])
    original=boundary.shared['legacy_admission'];calls=[];refuse=[False]
    api=runpy.run_path(str(endpoint['home']/'bin/lib/runtime_client.py'))
    api['process_start']=lambda *a,**kw:'fixture-start'
    def check(*a,**kw):
        calls.append(1)
        if refuse[0]:raise boundary.shared['TargetError']('LEGACY_TARGET_IS_GLOBAL')
        return original(*a,**{**kw,'api':api})
    boundary.shared['legacy_admission']=check
    clock=[100.0]
    monkeypatch.setattr(runtime_target,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    boundary.admit('input',pane=endpoint['pane'],reuse=True)
    boundary.admit('capture',pane=endpoint['pane'],reuse=True)
    assert len(calls)==1
    subprocess.run([*endpoint['prefix'],'respawn-pane','-k','-t',endpoint['pane'],'sleep','600'],check=True)
    boundary.admit('input',pane=endpoint['pane'],reuse=True)
    assert len(calls)==2  # same pane ID with a different process is not reused
    refuse[0]=True
    for operation in ('split','close','kill-session','attach'):
        with pytest.raises(TargetRefused,match='LEGACY_TARGET_IS_GLOBAL'):
            boundary.admit(operation,pane=endpoint['pane'],reuse=True)
    assert len(calls)==6
    clock[0]+=5.0
    with pytest.raises(TargetRefused,match='LEGACY_TARGET_IS_GLOBAL'):
        boundary.admit('input',pane=endpoint['pane'],reuse=True)
    assert len(calls)==7



def test_missing_helper_refuses_dedicated_socket_through_temp_alias(endpoint):
    socket=Path('/tmp')/('orrery-tmux-'+str(os.getuid()))/'fixture.sock'
    with pytest.raises(TargetRefused,match='GLOBAL_TMUX_LEGACY_CONSUMER_REFUSED'):
        LegacyTargetBoundary(endpoint['binary'],home=endpoint['home'],
            environ={**endpoint['env'],'TMUX':str(socket)+',123,0'})



@pytest.fixture
def protected_window_client(endpoint,monkeypatch):
    root=telemetry_root()
    for path in (root/'tests',root/'packages/agentstack_mail/tests',root/'packages/agentstack_mail/src'):
        monkeypatch.syspath_prepend(str(path))
    spec=importlib.util.spec_from_file_location('window_operator_fixture',root/'tests/test_global_operator_client.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    server=fixture.server.__wrapped__(monkeypatch)
    try:
        state=next(server);monkeypatch.setenv('AGENTSTACK_MCP_URL',state['url'])
        operator=fixture.api['RuntimeOperator'](state['config_path'])
        operator.create('protected',agent_name='ProtectedWindow',program='daemon',model='deterministic')
        client=operator.client('protected')
        with client.operation_mutex():pass
        home=operator.clients_parent.parent;deploy(home)
        boundary=LegacyTargetBoundary(endpoint['binary'],home=home,environ=endpoint['env'])
        original=boundary.shared['legacy_admission']
        api=operator.api;api['process_start']=lambda *a,**kw:'fixture-start'
        boundary.shared['legacy_admission']=lambda *a,**kw:original(*a,**{**kw,'api':api})
        yield operator,client,boundary
    finally:server.close()


@pytest.mark.parametrize('protected',[False,True])
def test_disconnect_restore_checks_moved_window_actual_panes(endpoint,protected_window_client,protected):
    from orrery_backend import SessionTmuxBridge,SessionState,SessionBridgeManager,WindowSizeSnapshot
    operator,client,boundary=protected_window_client
    def tmux(*args):
        return subprocess.check_output([*endpoint['prefix'],*args],text=True,env=endpoint['env']).strip()
    async def exercise():
        bridge=SessionTmuxBridge(ControlConfig('127.0.0.1',0,'orrery-normal',boundary,history_dir=endpoint['home']/'history'))
        window=tmux('display-message','-p','-t',endpoint['pane'],'#{window_id}')
        tmux('new-window','-d','-t','=orrery-normal','sleep','600')
        await bridge.start()
        try:
            assert await bridge.capture_window_size(window)
            state=SessionState(bridge=bridge,claimed_windows={window:WindowSizeSnapshot('manual',91,29)})
            tmux('new-session','-d','-s','orrery-moved','sleep','600')
            tmux('move-window','-s',window,'-t','=orrery-moved:1')
            tmux('resize-window','-t',window,'-x','141','-y','43')
            if protected:
                lives=client.runtime_dir/'live-sessions';lives.mkdir(mode=0o700,exist_ok=True)
                operator.api['atomic_json'](lives/'standalone.json',{'kind':'orrery-global-live-session-v1',
                    **client.binding,'agent_id':client.identity['agent_id'],'session_id':'standalone',
                    'pid':endpoint['pid'],'process_start':'fixture-start','pane_id':endpoint['pane']})
                with pytest.raises(TargetRefused,match='LEGACY_TARGET_IS_GLOBAL'):
                    boundary.admit('input',pane=endpoint['pane'])
            await bridge.refresh_panes(send_captures=False)
            assert endpoint['pane'] not in bridge.panes
            before=operator.read({'kind':'health'})['as_of_revision']
            await SessionBridgeManager._restore_claimed_windows(state)
            actual=tmux('display-message','-p','-t',window,'#{window_width}x#{window_height}')
            assert actual==('141x43' if protected else '91x29')
            assert (window in state.claimed_windows) is protected
            if protected:
                for command in (
                    ['resize-window','-t',window,'-x','91','-y','29'],
                    ['refresh-client','-C',window+':91x29'],
                    ['set-option','-w','-t',window,'-u','window-size'],
                ):
                    with pytest.raises(TargetRefused,match='LEGACY_TARGET_IS_GLOBAL'):
                        await bridge.send_command(command,wait=True)
                assert tmux('display-message','-p','-t',window,'#{window_width}x#{window_height}')=='141x43'
            assert operator.read({'kind':'health'})['as_of_revision']==before
        finally:await bridge.stop()
    asyncio.run(exercise())
