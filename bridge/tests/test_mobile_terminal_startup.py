"""Shared startup setting, with private HOME and no backend listener/input."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / 'bridge'
PROBE = f"""import json,sys
sys.path.insert(0,{str(BRIDGE)!r})
import orrery_backend as backend
backend.resolve_tmux_bin=lambda value: 'isolated-unused-tmux'
def app(tmux_bin,*,mobile_input_enabled):
    return {{'enabled':mobile_input_enabled,'project':backend.configured_value((), 'project_key')}}
backend.create_app=app
backend.web.run_app=lambda app,**kwargs: print(json.dumps(app))
raise SystemExit(backend.main(sys.argv[1:]))
"""


def environment(tmp_path, config='{}'):
    home = tmp_path / 'home'
    (home / '.orrery').mkdir(parents=True)
    if config is not None:
        (home / '.orrery/config.json').write_text(config)
    env = {'HOME': str(home), 'PATH': os.environ['PATH'], 'PYTHONDONTWRITEBYTECODE': '1'}
    if os.environ.get('PYTHONPATH'):
        env['PYTHONPATH'] = os.environ['PYTHONPATH']
    return env


def probe(tmp_path, config, *args):
    env = environment(tmp_path, config)
    path = tmp_path / 'probe.py'
    path.write_text(PROBE)
    return subprocess.run([sys.executable, str(path), *args], env=env,
                          capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize('config,expected', [
    (None, False), ('{}', False), ('{broken', False), ('[]', False),
    ('{"enable_mobile_terminal":false}', False), ('{"enable_mobile_terminal":true}', True),
])
def test_common_backend_setting_is_default_off_and_exact_bool(tmp_path, config, expected):
    result = probe(tmp_path, config)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1])['enabled'] is expected


@pytest.mark.parametrize('value', ['true', 'false', 0, 1, None, [], {}])
def test_wrong_type_stops_before_creating_app(tmp_path, value):
    result = probe(tmp_path, json.dumps({'enable_mobile_terminal': value}))
    assert result.returncode == 2
    assert 'enable_mobile_terminal' in result.stderr
    assert result.stdout == ''  # The main -> create_app/run_app sink was not reached.


def test_explicit_cli_opt_in_and_existing_string_keys_are_preserved(tmp_path):
    result = probe(tmp_path, '{"enable_mobile_terminal":false,"project_key":"  ~/work  ","mail_db":7}',
                   '--enable-mobile-terminal')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {'enabled': True, 'project': str(tmp_path / 'home/work')}


@pytest.mark.parametrize('entry', ['start-cockpit', 'get-setup'])
@pytest.mark.parametrize('enabled', [False, True])
def test_existing_shell_launch_blocks_reach_common_setting(tmp_path, entry, enabled):
    """Execute the actual launch block; prerequisites/ownership/tmux are stubs."""
    env = environment(tmp_path, json.dumps({'enable_mobile_terminal': enabled}))
    fixture = tmp_path / 'checkout'
    bridge = fixture / 'bridge'
    scripts = fixture / 'scripts'
    bridge.mkdir(parents=True)
    scripts.mkdir()
    (bridge / 'orrery_backend.py').write_text(PROBE)
    source = (ROOT / 'scripts/start-cockpit.sh').read_text()
    block = source.split('# ---------------------------------------------------------------- start\n', 1)[1].split('backend_pid=$!', 1)[0]
    start = scripts / 'start-cockpit.sh'
    start.write_text('#!/bin/bash\nset -eu\n' + '\n'.join([
        'PORT=${PORT:-18791}', 'dashboard_url=http://127.0.0.1:1', "project_key=''", "mail_db=''",
        'say(){ :; }', 'BRIDGE_DIR=' + shlex.quote(str(bridge)),
        'venv_python=' + shlex.quote(sys.executable),
    ]) + '\n' + block + '\nwait $!\n')
    start.chmod(0o755)
    if entry == 'start-cockpit':
        command = ['/bin/bash', str(start)]
    else:
        setup = (ROOT / 'scripts/setup.sh').read_text()
        function = re.search(r'^start_ours\(\) \{\n.*?^\}\n', setup, re.M | re.S).group()
        # get.sh's noninteractive handoff invokes setup without changing HOME.
        assert 'exec "$setup" "$@"' in (ROOT / 'scripts/get.sh').read_text()
        command = ['/bin/bash', '-c', '\n'.join([
            'set -eu', 'COCKPIT_ROOT=' + shlex.quote(str(fixture)), 'COCKPIT_PORT=18791',
            'SESSION=fixture', 'SOCK=fixture', 'root_real=$COCKPIT_ROOT', 'cockpit_head_full=fixture',
            'cockpit_log=' + shlex.quote(str(tmp_path / 'cockpit.log')),
            'OWNER=' + shlex.quote(str(tmp_path / 'owner')),
            'session_free_or_ours(){ :; }', 'session_identity(){ echo fixture; }',
            'backend_state(){ echo fixture; }', 'is_this_version(){ return 0; }', 'health_boot(){ echo fixture; }',
            'ctmux(){ if [ "$1" = new-session ]; then /bin/bash -c "${!#}"; fi; }',
            'stop(){ echo "$*" >&2; exit 1; }', function, 'start_ours',
        ])]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout.splitlines()[-1])['enabled'] is enabled
