"""Consumed Claude prompts use native attachments, ordinary turns use user rows."""
import asyncio
import json
import queue
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_conversation_providers import claude, line, page, row
from test_conversation_submissions import cockpit, prepare
from conversation_readers import normalize


@contextmanager
def native_bridge(path, monkeypatch):
    """The real read-only HTTP handler with a synthetic authoritative binding."""
    from aiohttp import ClientSession, web
    import orrery_backend as backend
    from conversation_preview import ReferenceStore
    binding = dict(row(path, 'claude-code'), name='ReviewFixture')
    calls = []
    async def bound(*args):
        calls.append(1)
        return binding
    monkeypatch.setattr(backend, 'conversation_bound_row', bound)
    ready = queue.Queue()
    loop = asyncio.new_event_loop()
    stop = asyncio.Event()
    async def run():
        @web.middleware
        async def cors(request, handler):
            response = await handler(request)
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response
        async with ClientSession() as client:
            app = web.Application(middlewares=[cors])
            app[backend.HTTP_SESSION_KEY] = client
            app[backend.TMUX_BIN_KEY] = object()
            app[backend.CONVERSATION_REFERENCES_KEY] = ReferenceStore()
            app.router.add_get('/telemetry/conversation', backend.serve_conversation)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '127.0.0.1', 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            ready.put('http://127.0.0.1:' + str(port))
            try:
                await stop.wait()
            finally:
                await runner.cleanup()
    def worker():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        yield ready.get(timeout=10), calls
    finally:
        loop.call_soon_threadsafe(stop.set)
        thread.join(timeout=10)
        assert not thread.is_alive()


def queued(prompt='Generated mid-turn instruction', **extra):
    attachment = dict(type='queued_command', prompt=prompt, commandMode='prompt',
                      origin=dict(kind='human'), timestamp='2026-11-04T07:00:01.125Z',
                      source_uuid='queued-source', delivery_id='queued-delivery', humanTurn=True)
    attachment.update(extra)
    return dict(type='attachment', sessionId='fixture-session',
                timestamp='2026-11-04T07:00:02Z', attachment=attachment)


def test_consumed_prompt_uses_attachment_timestamp_and_literal_text():
    text = 'Generated  instruction\n\twith <markup>'
    event = normalize(queued(text), 'claude', 'fixture-session')
    assert len(event) == 1 and event[0][0] == 0
    assert event[0][1] == dict(kind='text', role='user', text=text,
                             ts='2026-11-04T07:00:01.125Z', truncated=False)


@pytest.mark.parametrize('stamp', [None, ''])
def test_consumed_prompt_falls_back_to_line_timestamp(stamp):
    event = normalize(queued(timestamp=stamp), 'claude', 'fixture-session')[0][1]
    assert event['ts'] == '2026-11-04T07:00:02Z'


@pytest.mark.parametrize('extra', [dict(commandMode='task-notification'), dict(commandMode='bash'),
    dict(origin=dict(kind='task-notification')), dict(origin=dict(kind='peer')),
    dict(origin=None), dict(isMeta=True), dict(type='other'), dict(prompt=None)])
def test_non_human_prompt_attachments_are_not_user_records(extra):
    assert normalize(queued(**extra), 'claude', 'fixture-session') == []


@pytest.mark.parametrize('flag', ['isSidechain', 'isMeta', 'sessionId'])
def test_queued_prompt_keeps_existing_session_and_visibility_rules(flag):
    item = queued()
    item[flag] = 'another-session' if flag == 'sessionId' else True
    assert normalize(item, 'claude', 'fixture-session') == []


def test_queued_images_keep_normal_user_block_indexes_and_attachment_display():
    content = [dict(type='text', text='Generated image instruction'),
               dict(type='image', source=dict(type='base64', data='unused'))]
    assert normalize(queued(content), 'claude', 'fixture-session') == normalize(
        dict(claude('user', content), timestamp='2026-11-04T07:00:01.125Z'), 'claude', 'fixture-session')
    assert [i for i, _ in normalize(queued(content), 'claude', 'fixture-session')] == [0, 1]


def test_tail_forward_and_older_pages_have_identical_stable_ids_without_queue_duplicates(tmp_path):
    path = tmp_path / 'history.jsonl'
    ordinary = 'Generated ordinary queued turn'
    records = [claude('user', 'Generated initial turn'),
        dict(type='queue-operation', operation='enqueue', content=ordinary),
        dict(type='queue-operation', operation='dequeue', content=ordinary),
        claude('user', ordinary), queued(),
        dict(type='queue-operation', operation='remove', reason='absorbed_mid_turn',
             content='Generated mid-turn instruction'),
        claude('assistant', 'Generated answer'), queued('Generated mid-turn instruction')]
    path.write_bytes(b''.join(line(x) for x in records))
    binding = row(path, 'claude-code')
    full = page(binding)['events']
    assert [e['text'] for e in full] == ['Generated initial turn', ordinary,
        'Generated mid-turn instruction', 'Generated answer', 'Generated mid-turn instruction']
    assert full == page(binding)['events']
    assert len({e['id'] for e in full}) == len(full)
    tail = page(binding, limit=1)
    backwards = tail['events']
    while tail['has_older']:
        tail = page(binding, before=tail['before'], limit=1)
        backwards = tail['events'] + backwards
    assert backwards == full
    forwards = [full[0]]
    cursor = full[0]['cursor_after']
    while len(forwards) < len(full):
        result = page(binding, after=cursor, limit=1)
        assert result['events']
        forwards.extend(result['events']); cursor = result['after']
    assert forwards == full
    with path.open('ab') as stream:
        stream.write(line(claude('assistant', 'Generated later answer')))
    assert page(binding)['events'][:-1] == full


def test_codex_mid_turn_user_response_item_is_visible_once(tmp_path):
    path = tmp_path / 'rollout.jsonl'
    records = [dict(type='response_item', payload=dict(type='message', role='assistant',
        content=[dict(type='output_text', text='Generated progress')])),
        dict(type='event_msg', payload=dict(type='user_message', message='Generated interruption')),
        dict(type='response_item', timestamp='2026-11-04T07:00:01Z', payload=dict(type='message',
            role='user', content=[dict(type='input_text', text='Generated interruption')])),
        dict(type='response_item', payload=dict(type='message', role='assistant',
            content=[dict(type='output_text', text='Generated continuation')]))]
    path.write_bytes(b''.join(line(x) for x in records))
    events = page(row(path, 'codex'))['events']
    assert [(e['role'], e['text']) for e in events] == [('assistant', 'Generated progress'),
        ('user', 'Generated interruption'), ('assistant', 'Generated continuation')]


def test_consumed_native_record_reconciles_submission_in_real_view(cockpit, tmp_path, monkeypatch):
    js, wait, _client = prepare(cockpit, 'claude')
    js("sentText='Generated mid-turn instruction: continue with the updated requirements.'")
    text = js('sentText')
    timestamp = js('new Date(clock+1000).toISOString()')
    path = tmp_path / 'history.jsonl'
    initial = dict(claude('user', 'Generated initial turn'), timestamp=js('new Date(clock-2000).toISOString()'))
    progress = dict(claude('assistant', 'Generated work in progress'), timestamp=js('new Date(clock-1000).toISOString()'))
    path.write_bytes(line(initial) + line(progress))
    with native_bridge(path, monkeypatch) as (url, calls):
        js('OrreryConversationSource.Source.prototype.read=async()=>{const r=await fetch(' +
           json.dumps(url + '/telemetry/conversation?agent=ReviewFixture') +
           ');return r.json()};currentAgents[0]={...currentAgents[0],program:"claude-code",provider:"anthropic",'
           'history_session_id:"fixture-session",transcript_path:"/fixture/claude.jsonl"};'
           'document.dispatchEvent(new Event("oc:agents"))')
        wait("reader.textContent.includes('Generated work in progress')")
        assert not js("reader.querySelector('[data-event-id=old]')")
        js('promptInput.value=sentText;sendPrompt()')
        wait('receipts.length===1')
        assert js("reader.querySelectorAll('.conversation-submission').length") == 1
        assert js('receipts[0].submittedAt') <= js('Date.parse(' + json.dumps(timestamp) + ')')
        with path.open('ab') as stream:
            stream.write(line(queued(text, timestamp=timestamp)))
            stream.write(line(dict(type='queue-operation', operation='remove', reason='absorbed_mid_turn', content=text)))
            stream.write(line(dict(claude('assistant', 'Generated continuation after the interruption'),
                                   timestamp=js('new Date(clock+2000).toISOString()'))))
        js('conversationView.refresh()')
        wait("reader.querySelectorAll('.conversation-submission').length===0")
        assert calls
        assert js("[...reader.querySelectorAll('.conversation-event')].filter(e=>e.textContent.includes(sentText)).length") == 1
        assert js("[...reader.querySelectorAll('.conversation-byline')].some(e=>e.textContent.toUpperCase().includes('CLAUDE'))")
        js('conversationView.refresh()')
        assert js("reader.querySelectorAll('.conversation-submission').length") == 0
