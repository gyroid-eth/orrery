"""Read-only setup crosses the actual installed proof, without providers."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys

import pytest
from test_global_cockpit_integration import installed, server, TELEMETRY
import orrery_backend as backend

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('flag',['--check','--dry-run'])
def test_global_setup_plan_uses_instruction_resolver_without_project_writes(installed,tmp_path,flag):
    state,home,_=installed
    user=tmp_path/'user';user.mkdir()
    executable=home/'bin/agentstack-claude-setup'
    shutil.copy2(TELEMETRY/'bin/agentstack-claude-setup',executable)
    executable.chmod(0o700)
    (home/'claude').mkdir(mode=0o700)
    shutil.copy2(TELEMETRY/'claude/CLAUDE.md',home/'claude/CLAUDE.md')
    old=user/'work/CLAUDE.md';old.parent.mkdir();old.write_text('Keep this project file.\n')
    before={str(p.relative_to(user)):p.read_bytes() for p in user.rglob('*') if p.is_file()}
    result=subprocess.run(['/bin/bash',str(ROOT/'scripts/setup.sh'),flag],env={**os.environ,
        'HOME':str(user),'AGENTSTACK_HOME':str(home),'AGENTSTACK_RUNTIME_MODE':'global',
        'AGENTSTACK_GLOBAL_SERVER_CONFIG':str(state['config_path']),'ORRERY_DASHBOARD_URL':backend.DASHBOARD_URL,
        'ORRERY_PYTHON':sys.executable,'AGENTSTACK_PYTHON':sys.executable},capture_output=True,text=True,timeout=25)
    assert result.returncode==0,result.stdout+result.stderr
    assert '"action": "plan"' in result.stdout and str(user/'.claude/CLAUDE.md') in result.stdout
    assert {str(p.relative_to(user)):p.read_bytes() for p in user.rglob('*') if p.is_file()}==before
    assert not (user/'.orrery-install').exists()
    assert 'Cutover' not in result.stderr


@pytest.mark.parametrize('mode,config,reason',[('global','','COCKPIT_GLOBAL_CONFIG_REQUIRED'),('wrong','','RUNTIME_MODE_INVALID')])
def test_global_runtime_config_missing_or_invalid_never_falls_back(tmp_path,mode,config,reason):
    env={k:v for k,v in os.environ.items() if not k.startswith(('AGENTSTACK_','ORRERY_'))}
    env.update(HOME=str(tmp_path),AGENTSTACK_RUNTIME_MODE=mode,AGENTSTACK_GLOBAL_SERVER_CONFIG=config)
    result=subprocess.run(['/bin/bash',str(ROOT/'scripts/start-cockpit.sh'),'--check'],env=env,capture_output=True,text=True,timeout=10)
    assert result.returncode!=0 and reason in result.stderr
    assert not list(tmp_path.iterdir())


def test_gui_and_browser_launch_share_generated_runtime_reader(tmp_path):
    home=tmp_path/'home';home.mkdir();stack=home/'.agentstack';stack.mkdir()
    config=tmp_path/'server config.json'
    (stack/'env.sh').write_text("export AGENTSTACK_RUNTIME_MODE=global\nexport AGENTSTACK_GLOBAL_SERVER_CONFIG='"+str(config)+"'\n")
    env={k:v for k,v in os.environ.items() if not k.startswith(('AGENTSTACK_','ORRERY_'))}
    result=subprocess.run(['/bin/bash','-c','. "$1"; orrery_load_runtime; printf "%s\\n%s\\n" "$AGENTSTACK_RUNTIME_MODE" "$AGENTSTACK_GLOBAL_SERVER_CONFIG"','-',str(ROOT/'scripts/lib/runtime-mode.sh')],env={**env,'HOME':str(home)},capture_output=True,text=True,timeout=10)
    assert result.returncode==0 and result.stdout=='global\n'+str(config)+'\n'
    native=(ROOT/'app/src-tauri/src/lib.rs').read_text()
    assert 'scripts/start-cockpit.sh' in native and 'COCKPIT_START_WRAPPER_REQUIRED' in native


def test_bootstrap_reexecs_before_loading_new_setup_dependencies():
    source=(ROOT/'scripts/get.sh').read_text()
    assert 'get_version=3' in source
    start=source.index('newer_get "$cockpit" "$newest" "$@"')
    assert start<source.index('for payload in lib/runtime-mode.sh global-probe.py; do')
    assert '"${newest}:scripts/${payload}"' in source
    assert '. "${SCRIPT_DIR}/lib/runtime-mode.sh"' in (ROOT/'scripts/setup.sh').read_text()
