import asyncio
from types import SimpleNamespace

import pytest

import control_server as control
import orrery_backend as backend


@pytest.mark.asyncio
@pytest.mark.parametrize('successful', [True, False])
async def test_confirmed_input_uses_the_result_of_each_chunk(monkeypatch, tmp_path, successful):
    bridge = control.TmuxControlBridge(control.ControlConfig('127.0.0.1', 0, 'Fixture', 'tmux',
                                                            history_dir=tmp_path))
    bridge.master_fd = 100
    monkeypatch.setattr(control, 'admit_command', lambda *args, **kwargs: None)
    chunks = []

    async def write(data):
        chunks.append(data)
        pending = bridge._pending_blocks.popleft()
        asyncio.get_running_loop().call_soon(pending.set_result, control.CommandResult(
            ok=successful or len(chunks) == 1, lines=[]))

    monkeypatch.setattr(bridge, '_write_master', write)
    assert await bridge.send_input('%9', 'x' * 66, acknowledge=True) == ('accepted' if successful else 'unknown')
    assert len(chunks) == 2


@pytest.mark.asyncio
async def test_receipt_is_bound_to_pane_session_and_bridge_incarnation(tmp_path):
    sent = []

    async def record(*args, **kwargs):
        sent.append((args, kwargs))
        return 'accepted'

    bridge = SimpleNamespace(panes={'%1': object()}, send_input=record,
                             _incarnation='a' * 32, config=SimpleNamespace(session='Fixture', tmux_bin='tmux'))
    manager = backend.SessionBridgeManager('tmux', history_dir=tmp_path)
    manager.states['Fixture'] = SimpleNamespace(bridge=bridge)
    replies = []

    async def reply(value):
        replies.append(value)

    peer = SimpleNamespace(send_json=reply)
    packet = dict(type='input', session='Fixture', paneId='%1', incarnation='a' * 32, inputAck='1:1', data='\r')
    await manager.handle_message(peer, {'Fixture'}, dict(packet, incarnation='b' * 32))
    await manager.handle_message(peer, set(), packet)
    await manager.handle_message(peer, {'Fixture'}, packet)
    assert [entry['status'] for entry in replies] == ['refused', 'refused', 'accepted']
    assert sent == [(('%1', '\r'), {'acknowledge': True})]
