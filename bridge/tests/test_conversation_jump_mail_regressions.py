"""Independent J1/M1 review probes. Synthetic records and private HTTP only."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bridge'))
sys.path.insert(0, str(ROOT / 'bridge/tests'))
from test_conversation_mail import native


def test_search_budget_cannot_turn_duplicate_into_unique():
    script = r"""
const {find}=require(process.argv[1]);
const marker='GENERATED DUPLICATE MARKER';
const rows=Array.from({length:6000},()=> 'f'.repeat(400));
rows[0]=marker;rows[5999]=marker;
const buffer={type:'normal',length:rows.length,getLine:i=>i>=0&&i<rows.length?{isWrapped:false,translateToString:()=>rows[i]}:undefined};
console.log(JSON.stringify({fullBufferMatches:rows.filter(r=>r===marker).length,result:find(buffer,marker)}));
"""
    result = subprocess.run(['node', '-e', script, str(ROOT / 'bridge/conversation_terminal.js')], capture_output=True, text=True, check=True)
    observed = json.loads(result.stdout)
    print(observed)
    assert observed['fullBufferMatches'] == 2
    assert observed['result']['state'] != 'unique'


@pytest.mark.parametrize('provider', ['codex', 'claude', 'dsh', 'hermes'])
def test_bound_orrery_proxy_alias_is_mail(tmp_path, provider):
    # This session's tool contract describes this exact alias as:
    # "Send an ORRERY Mail message as this bound agent."
    event = native(tmp_path, provider, tool='mcp__agentstack__send_message', args=dict(
        to=['SyntheticParent'], subject='Synthetic subject', body_md='Synthetic body'))[0]
    print(provider, event['kind'])
    assert event['kind'] == 'mail'


@pytest.mark.parametrize('with_mail', [False, True])
def test_mixed_exec_keeps_existing_recorded_edit_preview(tmp_path, monkeypatch, with_mail):
    from aiohttp import ClientSession, web
    import orrery_backend as backend
    from conversation_preview import ReferenceStore
    from test_conversation_history import start

    workspace = tmp_path.resolve()
    (workspace / 'example.txt').write_text('current file')
    patch = '*** Begin Patch\n*** Update File: ' + str(workspace / 'example.txt') + '\n@@\n-before\n+after\n*** End Patch'
    code = 'await tools.apply_patch(' + json.dumps(patch) + ');'
    if with_mail:
        code += 'await tools.mcp__orrery_mail__send_message(' + json.dumps(dict(to=['SyntheticParent'], subject='Synthetic report', body_md='Synthetic body')) + ');'
    transcript = workspace / 'fixture.jsonl'
    records = [dict(type='session_meta', payload=dict(cwd=str(workspace))),
               dict(type='response_item', payload=dict(type='custom_tool_call', name='functions.exec', input=code))]
    transcript.write_text(''.join(json.dumps(record) + '\n' for record in records))
    row = dict(name='SyntheticAgent', program='codex', history_binding='bound', transcript_path=str(transcript))

    async def bound(*args):
        return dict(row)
    monkeypatch.setattr(backend, 'conversation_bound_row', bound)

    async def scenario():
        app = web.Application()
        app[backend.HTTP_SESSION_KEY] = object()
        app[backend.TMUX_BIN_KEY] = object()
        app[backend.CONVERSATION_REFERENCES_KEY] = ReferenceStore()
        app.router.add_get('/telemetry/conversation', backend.serve_conversation)
        runner, base = await start(app)
        try:
            async with ClientSession() as client:
                async with client.get(base + '/telemetry/conversation?agent=SyntheticAgent') as response:
                    payload = await response.json()
                    assert response.status == 200, payload
                    event = payload['events'][0]
                    print('with_mail', with_mail, 'kind', event['kind'], 'references', event.get('references'), 'diff', event.get('diff'))
                    if with_mail:
                        assert event['kind']=='tool' and event['text']=='functions.exec'
                        assert event['mail'][0]['subject']=='Synthetic report'
                    assert event.get('references'), event
                    assert '-before\n+after' in event.get('diff', ''), event
        finally:
            await runner.cleanup()
    asyncio.run(scenario())
