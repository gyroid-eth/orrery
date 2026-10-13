"""Real control clients must leave when their backend dies, on macOS too."""
import asyncio
import errno
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid

import pytest

BRIDGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRIDGE))
from control_server import ControlConfig, TmuxControlBridge

BACKEND = """
import asyncio, signal, subprocess, sys
from pathlib import Path
from control_server import ControlConfig, TmuxControlBridge
async def main():
    # A backend launched under nohup passes ignored SIGHUP to its children.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    bridge = TmuxControlBridge(ControlConfig('127.0.0.1', 0, 'probe', sys.argv[1],
                                            history_dir=Path(sys.argv[2])))
    if sys.argv[3] == 'during-start':
        async def pending(**kwargs):
            print('ready 0', flush=True)
            await asyncio.Event().wait()
        bridge._resolve_session_created = pending
    await bridge.start()
    holder = None
    if sys.argv[3] == 'inherited-master':
        holder = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                  pass_fds=(bridge.master_fd,), start_new_session=True,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
    print('ready ' + str(holder.pid if holder else 0), flush=True)
    await asyncio.to_thread(sys.stdin.readline)
    await bridge.stop()
asyncio.run(main())
"""


def eventually(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def isolated_tmux(tmp_path):
    tmux = shutil.which('tmux')
    if not tmux:
        pytest.skip('tmux is required')
    command = [tmux, '-L', 'occ-' + uuid.uuid4().hex[:8]]
    wrapper = tmp_path / 'tmux'
    wrapper.write_text('#!/bin/sh\nexec ' + shlex.join(command) + ' "$@"\n')
    wrapper.chmod(0o700)
    subprocess.run(command + ['-f', '/dev/null', 'new-session', '-d', '-s', 'probe',
                              '-e', 'CLAUDECODE=1'], check=True)
    try:
        yield command, wrapper, tmp_path
    finally:
        subprocess.run(command + ['kill-server'], check=False, capture_output=True)


def client_pids(command):
    result = subprocess.run(command + ['list-clients', '-F', '#{client_pid}'],
                            check=True, capture_output=True, text=True)
    return {int(pid) for pid in result.stdout.split()}


@pytest.mark.parametrize('shutdown', ['kill', 'kill-group', 'stalled-server',
                                    'inherited-master', 'during-start', 'terminate', 'stop'])
def test_backend_death_removes_only_its_control_client(isolated_tmux, shutdown):
    command, wrapper, tmp_path = isolated_tmux
    master, slave = pty.openpty()
    # Another user's control client on the very same session must survive.
    foreign = subprocess.Popen(command + ['-CC', 'attach', '-t', 'probe'],
                               stdin=slave, stdout=slave, stderr=slave,
                               start_new_session=True)
    os.close(slave)
    backend = None
    holder_pid = 0
    server_pid = int(subprocess.check_output(
        command + ['display-message', '-p', '#{pid}'], text=True).strip())
    try:
        assert eventually(lambda: foreign.pid in client_pids(command))
        for restart in range(3):
            backend = subprocess.Popen(
                [sys.executable, '-u', '-c', BACKEND, str(wrapper), str(tmp_path / 'history'), shutdown],
                cwd=BRIDGE, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, start_new_session=True,
            )
            # communicate with a timeout rather than hanging on a failed startup.
            assert select.select([backend.stdout], [], [], 10)[0], 'backend did not start'
            ready, holder = backend.stdout.readline().split()
            assert ready == 'ready'
            holder_pid = int(holder)
            assert eventually(lambda: len(client_pids(command) - {foreign.pid}) == 1)
            if shutdown == 'stop':
                backend.stdin.write('\n')
                backend.stdin.flush()
            elif shutdown == 'kill-group':
                os.killpg(backend.pid, signal.SIGKILL)
            elif shutdown == 'stalled-server':
                os.kill(server_pid, signal.SIGSTOP)
                try:
                    backend.kill()
                    backend.wait(timeout=5)
                finally:
                    os.kill(server_pid, signal.SIGCONT)
            else:
                backend.send_signal(signal.SIGTERM if shutdown in ('terminate', 'during-start')
                                    else signal.SIGKILL)
            backend.wait(timeout=5)
            backend.communicate(timeout=5)
            assert eventually(lambda: client_pids(command) == {foreign.pid}), (
                f'{shutdown}, restart {restart}: orphan control clients {client_pids(command) - {foreign.pid}}'
            )
            if holder_pid:
                # The independent lifetime channel works even with a live
                # holder of the PTY master; it did not merely time out.
                os.kill(holder_pid, 0)
                os.kill(holder_pid, signal.SIGKILL)
                holder_pid = 0
    finally:
        if backend is not None:
            if backend.poll() is None:
                backend.kill()
            backend.communicate(timeout=5)
        foreign.kill()
        foreign.wait(timeout=5)
        os.close(master)
        if holder_pid:
            os.kill(holder_pid, signal.SIGKILL)


@pytest.mark.parametrize('failure', ['pipe', 'popen'])
def test_startup_failure_closes_pty_and_lifetime_descriptors(monkeypatch, tmp_path, failure):
    descriptors = []
    openpty, pipe = pty.openpty, os.pipe

    def allocate_pty():
        pair = openpty()
        descriptors.extend(pair)
        return pair

    def allocate_pipe():
        if failure == 'pipe':
            raise OSError(errno.EMFILE, 'descriptor limit')
        pair = pipe()
        descriptors.extend(pair)
        return pair

    def fail_spawn(*args, **kwargs):
        raise OSError(errno.EMFILE, 'descriptor limit')

    monkeypatch.setattr(pty, 'openpty', allocate_pty)
    monkeypatch.setattr(os, 'pipe', allocate_pipe)
    monkeypatch.setattr(subprocess, 'Popen', fail_spawn)
    bridge = TmuxControlBridge(ControlConfig('127.0.0.1', 0, 'probe', 'tmux',
                                            history_dir=tmp_path))
    with pytest.raises(OSError, match='descriptor limit'):
        asyncio.run(bridge.start())
    assert bridge.master_fd is None and bridge._lifetime_fd is None
    for fd in descriptors:
        with pytest.raises(OSError) as error:
            os.fstat(fd)
        assert error.value.errno == errno.EBADF


def test_session_death_closes_guard_and_emits_one_incarnation_status(isolated_tmux):
    command, wrapper, tmp_path = isolated_tmux
    # Keep a queryable current session after probe dies; list-clients otherwise
    # reports "no current session" even when an empty server remains alive.
    subprocess.run(command + ['new-session', '-d', '-s', 'keeper',
                              '-e', 'CLAUDECODE=1', 'sleep 60'], check=True)

    async def scenario():
        bridge = TmuxControlBridge(ControlConfig('127.0.0.1', 0, 'probe', str(wrapper),
                                                history_dir=tmp_path / 'history'))
        events = []
        closed = asyncio.Event()

        async def broadcast(payload):
            if payload.get('state') == 'closed':
                events.append(payload)
                closed.set()

        bridge.broadcast = broadcast
        try:
            await bridge.start()
            assert len(client_pids(command)) == 1
            subprocess.run(command + ['kill-session', '-t', '=probe'], check=True)
            await asyncio.wait_for(closed.wait(), 5)
            assert events == [{
                'type': 'status', 'state': 'closed', 'session': 'probe',
                'incarnation': bridge._incarnation, 'sessionGone': True,
            }]
            assert asyncio.get_running_loop().remove_reader(bridge.master_fd) is False
            bridge._schedule_closed()
            await asyncio.sleep(0)
            assert len(events) == 1
            assert await asyncio.to_thread(eventually, lambda: bridge.process.poll() is not None)
            assert client_pids(command) == set()
        finally:
            await bridge.stop()
        assert bridge._lifetime_fd is None

    asyncio.run(scenario())
