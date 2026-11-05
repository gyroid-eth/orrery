"""Repeated polls of an unchanged record: no record read, no dashboard, no content.

Synthetic records only; a private aiohttp dashboard stand-in counts requests.
"""
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

import collections

import pytest
from aiohttp import ClientSession, ClientTimeout, web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orrery_backend as backend
from conversation_history import UnchangedPolls
from conversation_preview import ReferenceStore
from test_conversation_providers import claude, line, make_db, row


async def start(app):
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0); await site.start()
    return runner, 'http://127.0.0.1:' + str(site._server.sockets[0].getsockname()[1])


def run(monkeypatch, current, scenario, *, clock=None, dashboard_delay=0.0, api=35, route=None, events=None, before_upstream=None):
    calls = dict(agents=0, version=0, route=0)
    async def upstream(request):
        if dashboard_delay:
            await asyncio.sleep(dashboard_delay)
        if before_upstream is not None:
            await before_upstream(request)
        if events is not None:
            events.append(request.path)
        if request.path == '/api/version':
            calls['version'] += 1; return web.json_response(dict(api=api))
        if request.path.endswith('/history-binding'):
            calls['route'] += 1
            if route is not None:
                return await route(request)
            return web.json_response(dict(ok=True, agent=dict(current)))
        calls['agents'] += 1
        return web.json_response(dict(agents=[dict(current)]))
    reads = []
    real_open = backend.open_reader
    def counting_open(value, **kwargs):
        reads.append(value['transcript_path'])
        if events is not None:
            events.append('open')
        return real_open(value, **kwargs)
    monkeypatch.setattr(backend, 'open_reader', counting_open)
    async def main():
        up_app = web.Application(); up_app.router.add_get('/{tail:.*}', upstream)
        up, url = await start(up_app); monkeypatch.setattr(backend, 'DASHBOARD_URL', url)
        try:
            async with ClientSession() as client:
                app = web.Application()
                app[backend.HTTP_SESSION_KEY] = client; app[backend.TMUX_BIN_KEY] = 'fixture-unused'
                app[backend.CONVERSATION_REFERENCES_KEY] = ReferenceStore()
                app[backend.CONVERSATION_DASHBOARD_KEY] = {}
                app[backend.CONVERSATION_UNCHANGED_KEY] = UnchangedPolls(**({'clock': clock} if clock else {}))
                app[backend.CONVERSATION_STATS_KEY] = collections.Counter()
                app.router.add_get('/telemetry/conversation', backend.serve_conversation)
                app.router.add_get('/telemetry/conversation/stats', backend.serve_conversation_stats)
                runner, base = await start(app)
                async def get(_path='/telemetry/conversation', _timeout=None, **params):
                    if _path == '/telemetry/conversation':
                        params = dict(agent='FixtureAgent', **params)
                    options = {'timeout': ClientTimeout(total=_timeout)} if _timeout else {}
                    async with client.get(base + _path, params=params, **options) as response:
                        return response.status, (await response.json() if response.status != 204 else None)
                try:
                    await scenario(get, calls, reads)
                finally:
                    await runner.cleanup()
        finally:
            await up.cleanup()
    asyncio.run(main())


def test_unchanged_poll_reads_nothing_and_returns_no_content(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    current = row(path, 'claude-code')
    async def scenario(get, calls, reads):
        status, first = await get()
        assert status == 200 and first['events'][0]['text'] == 'fixture body'
        assert calls['agents'] == 2 and len(reads) == 1
        for _ in range(3):
            status, quiet = await get(after=first['after'])
            assert status == 200 and quiet['ok'] and quiet['unchanged'] is True
            assert quiet['events'] == [] and quiet['after'] == first['after'] and quiet['provider'] == 'claude'
            assert 'transcript_path' not in quiet and 'fixture body' not in json.dumps(quiet)
        assert calls['agents'] == 2 and len(reads) == 1
        # One appended record: a full, dashboard-checked read again.
        with path.open('ab') as f: f.write(line(claude('assistant', [dict(type='text', text='appended')])))
        status, grown = await get(after=first['after'])
        assert status == 200 and not grown.get('unchanged') and [e['text'] for e in grown['events']] == ['appended']
        # B: a binding confirmed within 30 s stands in for the check before
        # this read; the check after it still runs.
        assert calls['agents'] == 3 and len(reads) == 2
        # A cursor the server never issued is never answered from the cache.
        status, other = await get(after=first['after'][:-1] + '9')
        assert not other.get('unchanged')
    run(monkeypatch, current, scenario)


def test_unchanged_poll_revalidates_binding_after_ttl(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    current = row(path, 'claude-code'); now = [1000.0]
    async def scenario(get, calls, reads):
        _, first = await get()
        _, quiet = await get(after=first['after']); assert quiet['unchanged']
        now[0] += 31
        current.update(history_binding='stale', transcript_path=None, history_binding_reason_code='receipt_predates_session')
        status, stale = await get(after=first['after'])
        assert stale['ok'] is False and stale['error'] == 'history_stale' and 'events' not in stale
    run(monkeypatch, current, scenario, clock=lambda: now[0])


def test_replaced_record_with_same_size_is_not_unchanged(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    current = row(path, 'claude-code')
    async def scenario(get, calls, reads):
        _, first = await get()
        replacement = tmp_path / 'replacement.jsonl'; replacement.write_bytes(line(claude('user', 'fixture BODY')))
        replacement.replace(path)  # same size, new inode
        status, after = await get(after=first['after'])
        # Opened to compare its inode, closed unread, checked, then read.
        assert not after.get('unchanged') and len(reads) == 3
    run(monkeypatch, current, scenario)


def test_hermes_snapshot_unchanged_and_foreign_write_send_no_rows(tmp_path, monkeypatch):
    path = tmp_path / 'state.db'; con = make_db(path)
    con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(1,'fixture-session','user','fixture body',1)"); con.commit(); con.close()
    current = row(path, 'hermes')
    async def scenario(get, calls, reads):
        _, first = await get()
        assert first['mode'] == 'snapshot' and [e['text'] for e in first['events']] == ['fixture body']
        _, quiet = await get(after=first['after'])
        assert quiet['unchanged'] and quiet['events'] == [] and len(reads) == 1
        # Another session writes to the shared DB: the file changes, the bound
        # session's visible snapshot does not, so still no rows are sent.
        db = sqlite3.connect(path); db.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES('foreign-session','user','FOREIGN',2)"); db.commit(); db.close()
        _, foreign = await get(after=first['after'])
        assert foreign['unchanged'] and foreign['events'] == [] and len(reads) == 2
        db = sqlite3.connect(path); db.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES('fixture-session','assistant','new answer',3)"); db.commit(); db.close()
        _, grown = await get(after=first['after'])
        assert not grown.get('unchanged') and [e['text'] for e in grown['events']] == ['fixture body', 'new answer']
        assert 'FOREIGN' not in json.dumps(grown)
    run(monkeypatch, current, scenario)


def test_concurrent_panes_share_the_pre_read_roster_request(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    current = row(path, 'claude-code')
    async def scenario(get, calls, reads):
        results = await asyncio.gather(*(get() for _ in range(4)))
        assert all(status == 200 and payload['events'][0]['text'] == 'fixture body' for status, payload in results)
        # Without sharing: 8 roster requests. Rechecks never join a roster
        # request that started before their own read finished.
        assert calls['agents'] < 8
        assert calls['version'] == 1
    run(monkeypatch, current, scenario, dashboard_delay=0.05)


def test_recheck_never_reuses_a_roster_request_started_before_the_read():
    started = []
    class Response:
        status = 200
        async def json(self): await asyncio.sleep(0.05); return dict(agents=[])
        async def __aenter__(self): return self
        async def __aexit__(self, *exc): return False
    class Session:
        def get(self, url):
            started.append(url); return Response()
    class Request:
        app = {backend.HTTP_SESSION_KEY: Session(), backend.CONVERSATION_DASHBOARD_KEY: {}}
    async def main():
        loop = asyncio.get_running_loop()
        early = asyncio.ensure_future(backend.conversation_live_agents(Request()))
        await asyncio.sleep(0.01)
        joined = asyncio.ensure_future(backend.conversation_live_agents(Request()))
        recheck = asyncio.ensure_future(backend.conversation_live_agents(Request(), not_before=loop.time()))
        await asyncio.gather(early, joined, recheck)
    asyncio.run(main())
    # The second pre-read joined the first; the recheck started its own.
    assert len(started) == 2


def test_hermes_revalidation_after_ttl_asks_dashboard_but_sends_no_rows(tmp_path, monkeypatch):
    path = tmp_path / 'state.db'; con = make_db(path)
    con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(1,'fixture-session','user','fixture body',1)"); con.commit(); con.close()
    current = row(path, 'hermes'); now = [1000.0]
    async def scenario(get, calls, reads):
        _, first = await get()
        before = calls['agents']
        now[0] += 31
        _, again = await get(after=first['after'])
        assert calls['agents'] == before + 1  # the binding was checked again
        assert again['unchanged'] and again['events'] == []
    run(monkeypatch, current, scenario, clock=lambda: now[0])


# --- B: the check before a read may be skipped, never the one after ------

def test_b_skips_only_the_pre_read_check_and_publishes_after_the_recheck(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    current = row(path, 'claude-code'); order = []
    async def scenario(get, calls, reads):
        _, first = await get()
        order.clear()
        with path.open('ab') as f: f.write(line(claude('assistant', [dict(type='text', text='appended')])))
        status, grown = await get(after=first['after'])
        assert status == 200 and [e['text'] for e in grown['events']] == ['appended']
        # Read first, then the dashboard: the content waited for the recheck.
        assert order == ['open', '/api/agents']
    run(monkeypatch, current, scenario, events=order)


def test_b_discards_the_read_when_the_recheck_fails_and_checks_first_next_time(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    current = row(path, 'claude-code'); order = []
    async def scenario(get, calls, reads):
        _, first = await get()
        with path.open('ab') as f: f.write(line(claude('assistant', [dict(type='text', text='SECRET_AFTER_SWITCH')])))
        current['history_session_id'] = 'another-session'  # the binding changed
        order.clear()
        status, changed = await get(after=first['after'])
        assert status == 409 and changed == dict(ok=False, error='history_changed')
        assert 'SECRET_AFTER_SWITCH' not in json.dumps(changed)
        assert order == ['open', '/api/agents']
        # The failed recheck forgot the binding: the next read checks first.
        order.clear()
        await get(after=first['after'])
        assert order[0] == '/api/agents'
    run(monkeypatch, current, scenario, events=order)


def test_b_reads_a_replaced_file_only_after_a_new_check(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    current = row(path, 'claude-code'); order = []
    async def scenario(get, calls, reads):
        _, first = await get()
        replacement = tmp_path / 'replacement.jsonl'
        replacement.write_bytes(line(claude('user', 'fixture body')) + line(claude('assistant', [dict(type='text', text='other file')])))
        replacement.replace(path)  # same path, another (dev, inode)
        order.clear()
        status, page = await get()
        assert status == 200
        # Opened (to compare its inode) and closed unread, then checked, then read.
        assert order == ['open', '/api/agents', 'open', '/api/agents']
        assert [e['text'] for e in page['events']] == ['fixture body', 'other file']
    run(monkeypatch, current, scenario, events=order)


# --- A: a held poll ---------------------------------------------------------

def test_a_held_poll_returns_on_change_or_after_the_wait(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    current = row(path, 'claude-code')
    async def scenario(get, calls, reads):
        _, first = await get()
        agents = calls['agents']
        started = asyncio.get_running_loop().time()
        _, quiet = await get(after=first['after'], wait='1')
        assert quiet['unchanged'] and asyncio.get_running_loop().time() - started >= 0.95
        assert calls['agents'] == agents and len(reads) == 1  # waited on stat only
        async def append_soon():
            await asyncio.sleep(0.4)
            with path.open('ab') as f: f.write(line(claude('assistant', [dict(type='text', text='appended')])))
        started = asyncio.get_running_loop().time()
        (_, grown), _ = await asyncio.gather(get(after=first['after'], wait='5'), append_soon())
        assert [e['text'] for e in grown['events']] == ['appended']
        assert asyncio.get_running_loop().time() - started < 2
    run(monkeypatch, current, scenario)


@pytest.mark.parametrize('query', [dict(wait='1'), dict(after='x', wait='26'), dict(after='x', wait='-1'), dict(after='x', wait='a')])
def test_a_wait_is_bounded_and_only_with_a_cursor(tmp_path, monkeypatch, query):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    async def scenario(get, calls, reads):
        status, payload = await get(**query)
        assert status == 400 and payload['error'] == 'invalid_query' and reads == []
    run(monkeypatch, row(path, 'claude-code'), scenario)


# --- telemetry API 36: one agent's binding without the roster -------------

def test_api_36_uses_the_binding_route_instead_of_the_roster(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    async def scenario(get, calls, reads):
        status, payload = await get()
        assert status == 200 and payload['events'][0]['text'] == 'fixture body'
        assert calls['agents'] == 0 and calls['route'] == 2  # before and after the read
    run(monkeypatch, row(path, 'claude-code'), scenario, api=36)


def test_api_36_route_unavailable_agent_is_agent_unavailable(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    async def route(request):
        return web.json_response(dict(ok=False, error='agent_unavailable'), status=404)
    async def scenario(get, calls, reads):
        status, payload = await get()
        assert payload == dict(ok=False, error='agent_unavailable') and reads == [] and calls['agents'] == 0
    run(monkeypatch, row(path, 'claude-code'), scenario, api=36, route=route)


def test_api_36_route_failure_falls_back_to_the_roster(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    async def route(request):
        return web.Response(status=500, text='oops')
    async def scenario(get, calls, reads):
        status, payload = await get()
        assert status == 200 and payload['events'][0]['text'] == 'fixture body'
        assert calls['agents'] == 2
    run(monkeypatch, row(path, 'claude-code'), scenario, api=36, route=route)


def test_a_polls_beyond_the_held_cap_return_at_once(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    monkeypatch.setattr(backend, 'CONVERSATION_MAX_HELD', 1)
    async def scenario(get, calls, reads):
        _, first = await get()
        loop = asyncio.get_running_loop()
        async def timed():
            started = loop.time(); status, payload = await get(after=first['after'], wait='2')
            return loop.time() - started, payload
        held = asyncio.ensure_future(timed())
        await asyncio.sleep(0.3)  # the first poll holds the only slot
        quick_elapsed, quick = await timed()
        held_elapsed, slow = await held
        assert quick['unchanged'] and 'held' not in quick and quick_elapsed < 0.5
        assert slow['unchanged'] and slow['held'] is True and held_elapsed >= 1.9
        # The slot is returned: a later poll may be held again.
        _, again = await get(after=first['after'], wait='1')
        assert again['held'] is True
    run(monkeypatch, row(path, 'claude-code'), scenario)


# --- r2: reviews of r1 -------------------------------------------------------

def test_b_never_reads_a_replaced_file_before_the_new_check(tmp_path, monkeypatch):
    """Real reads, not just open order: no byte of the replacement before the dashboard."""
    import conversation_readers
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    current = row(path, 'claude-code'); order = []
    replacement_ino = []
    real_pread = conversation_readers.os.pread

    def watched(fd, n, offset):
        if replacement_ino and os.fstat(fd).st_ino == replacement_ino[0]:
            order.append('READ_REPLACEMENT')
        return real_pread(fd, n, offset)
    monkeypatch.setattr(conversation_readers.os, 'pread', watched)
    async def scenario(get, calls, reads):
        _, first = await get()
        replacement = tmp_path / 'replacement.jsonl'
        replacement.write_bytes(line(claude('user', 'REPLACEMENT_NOT_BOUND')))
        replacement_ino.append(replacement.stat().st_ino)
        replacement.replace(path)
        current.update(history_binding='stale', transcript_path=None, history_binding_reason_code='receipt_predates_session')
        order.clear()
        status, page = await get()
        assert page['ok'] is False and page['error'] == 'history_stale'
        assert 'READ_REPLACEMENT' not in order, order
        assert order[:2] == ['open', '/api/agents'], order
    run(monkeypatch, current, scenario, events=order)


def test_a_slot_returns_as_soon_as_its_client_goes_away(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    monkeypatch.setattr(backend, 'CONVERSATION_MAX_HELD', 1)
    async def scenario(get, calls, reads):
        _, first = await get()
        with pytest.raises(asyncio.TimeoutError):
            await get(after=first['after'], wait='25', _timeout=0.3)  # the client aborts
        await asyncio.sleep(0.4)                                      # one step later
        _, stats = await get('/telemetry/conversation/stats')
        assert stats['held_now'] == 0 and stats['held_client_gone'] == 1
        loop = asyncio.get_running_loop(); started = loop.time()
        _, again = await get(after=first['after'], wait='1')
        assert again.get('held') is True and loop.time() - started >= 0.9  # the slot was free
    run(monkeypatch, row(path, 'claude-code'), scenario)


def test_a_changing_record_is_never_answered_as_held(tmp_path, monkeypatch):
    """Only an answer that waited carries held, so a busy record keeps the interval."""
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    async def scenario(get, calls, reads):
        _, page = await get()
        for i in range(6):
            with path.open('ab') as f: f.write(line(claude('assistant', [dict(type='text', text=f'busy {i}')])))
            _, page = await get(after=page['after'], wait='25')
            assert [e['text'] for e in page['events']] == [f'busy {i}'] and 'held' not in page
        # A change found while holding is held: the client may ask again at once.
        async def append_soon():
            await asyncio.sleep(0.4)
            with path.open('ab') as f: f.write(line(claude('assistant', [dict(type='text', text='while held')])))
        (_, woke), _ = await asyncio.gather(get(after=page['after'], wait='5'), append_soon())
        assert [e['text'] for e in woke['events']] == ['while held'] and woke['held'] is True
    run(monkeypatch, row(path, 'claude-code'), scenario)


def test_a_hold_ends_when_its_revalidation_expires(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    current = row(path, 'claude-code'); now = [1000.0]
    async def scenario(get, calls, reads):
        _, first = await get()
        agents = calls['agents']
        async def expire_soon():
            await asyncio.sleep(0.4)
            now[0] += 31
            current.update(history_binding='stale', transcript_path=None, history_binding_reason_code='receipt_predates_session')
        loop = asyncio.get_running_loop(); started = loop.time()
        (_, page), _ = await asyncio.gather(get(after=first['after'], wait='25'), expire_soon())
        assert loop.time() - started < 2                  # not the full 25 s
        assert page['ok'] is False and page['error'] == 'history_stale' and calls['agents'] > agents
    run(monkeypatch, current, scenario, clock=lambda: now[0])


@pytest.mark.parametrize('failure', ['disconnect', 'timeout'])
def test_api_36_route_transport_failures_fall_back_to_the_roster(tmp_path, monkeypatch, failure):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    async def route(request):
        request.transport.close()
        return web.Response(text='never sent')
    if failure == 'timeout':
        async def slow(*_a, **_k):
            raise asyncio.TimeoutError()
        monkeypatch.setattr(backend, 'conversation_binding_route', slow)
    async def scenario(get, calls, reads):
        status, payload = await get()
        assert status == 200 and payload['events'][0]['text'] == 'fixture body'
        assert calls['agents'] == 2
        _, stats = await get('/telemetry/conversation/stats')
        assert stats['binding_route_fallback'] == 2 and stats['roster'] == 2
    run(monkeypatch, row(path, 'claude-code'), scenario, api=36, route=route)


def test_stats_are_counts_only(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    async def scenario(get, calls, reads):
        _, first = await get()
        await get(after=first['after'])
        _, stats = await get('/telemetry/conversation/stats')
        assert stats['full_reads'] == 1 and stats['unchanged'] == 1 and stats['held_cap'] == 4
        assert all(isinstance(value, int) for value in stats.values())
        assert 'FixtureAgent' not in json.dumps(stats) and str(path) not in json.dumps(stats)
    run(monkeypatch, row(path, 'claude-code'), scenario)


# --- r3: a slot holder returns only with new content for this session -------

async def _client(get, after, until, seen, *, wait='25'):
    """The browser's loop (conversation_view.js schedule): a slot answer at once,
    or after 250 ms when it had new rows; a catch-up page at once; else 4 s."""
    loop = asyncio.get_running_loop()
    while loop.time() < until:
        _, page = await get(after=after, wait=wait)
        if not page.get('ok'):
            raise AssertionError(page)
        for event in page.get('events', []):
            seen.setdefault(event['text'], loop.time())
        after = page['after']
        if page.get('has_newer'):
            continue
        if page.get('slot'):
            await asyncio.sleep(0.25 if page.get('events') else 0)  # conversation_view.js CONTENT_GAP_MS
        else:
            await asyncio.sleep(4)
    return after


@pytest.mark.parametrize('api,delay,bound', [(35, 1.3, 3.6), (36, 0.04, 1.0)])
def test_a_written_record_is_followed_within_a_bound(tmp_path, monkeypatch, api, delay, bound):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    async def scenario(get, calls, reads):
        _, first = await get()
        loop = asyncio.get_running_loop(); written, seen = {}, {}
        _, stats0 = await get('/telemetry/conversation/stats')
        async def writer():
            for i in range(8):
                with path.open('ab') as f: f.write(line(claude('assistant', [dict(type='text', text=f'busy {i}')])))
                written[f'busy {i}'] = loop.time(); await asyncio.sleep(0.5)
        until = loop.time() + 4 + 2 * delay + 1.5
        await asyncio.gather(writer(), _client(get, first['after'], until, seen, wait='3'))
        lags = [seen[text] - at for text, at in written.items()]
        assert len(lags) == 8 and max(lags) <= bound, lags
        _, stats1 = await get('/telemetry/conversation/stats')
        assert stats1['full_reads'] - stats0['full_reads'] <= len(written)  # never more than the changes
    run(monkeypatch, row(path, 'claude-code'), scenario, api=api, dashboard_delay=delay)


@pytest.mark.parametrize('api,delay', [(35, 1.3), (36, 0.04)])
def test_other_sessions_writes_keep_the_hold_without_reads(tmp_path, monkeypatch, api, delay):
    path = tmp_path / 'state.db'; con = make_db(path)
    con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(1,'fixture-session','user','fixture body',1)"); con.commit(); con.close()
    async def scenario(get, calls, reads):
        _, first = await get()
        _, stats0 = await get('/telemetry/conversation/stats')
        loop = asyncio.get_running_loop()
        async def foreign():
            for _ in range(6):
                await asyncio.sleep(0.4)
                db = sqlite3.connect(path); db.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES('foreign-session','user','FOREIGN',2)"); db.commit(); db.close()
        started = loop.time()
        (_, quiet), _ = await asyncio.gather(get(after=first['after'], wait='3'), foreign())
        assert quiet['unchanged'] and quiet['slot'] and quiet['held'] and loop.time() - started >= 2.9  # held throughout
        _, stats1 = await get('/telemetry/conversation/stats')
        assert stats1['full_reads'] == stats0['full_reads']               # no full read for others' writes
        assert stats1['other_session_only'] - stats0['other_session_only'] >= 1
        assert 'FOREIGN' not in json.dumps(quiet)
        # This session writes: the held poll answers with the new row promptly.
        async def own():
            await asyncio.sleep(0.4)
            db = sqlite3.connect(path); db.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES('fixture-session','assistant','new answer',3)"); db.commit(); db.close()
        started = loop.time()
        (_, grown), _ = await asyncio.gather(get(after=first['after'], wait='10'), own())
        assert [e['text'] for e in grown['events']][-1] == 'new answer' and loop.time() - started < 0.4 + 0.3 + 2 * delay + 0.5
    run(monkeypatch, row(path, 'hermes'), scenario, api=api, dashboard_delay=delay)


def test_full_reads_count_every_read_page_call(tmp_path, monkeypatch):
    """Including the Hermes read whose snapshot was the same (r2 review)."""
    import conversation_readers
    path = tmp_path / 'state.db'; con = make_db(path)
    con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(1,'fixture-session','user','fixture body',1)"); con.commit(); con.close()
    pages = []
    real = conversation_readers.Reader.read_page
    def counted(self, **kw):
        pages.append(1); return real(self, **kw)
    monkeypatch.setattr(conversation_readers.Reader, 'read_page', counted)
    async def scenario(get, calls, reads):
        _, first = await get()
        db = sqlite3.connect(path); db.execute("UPDATE sessions SET cwd='x' WHERE id='foreign-session'"); db.commit(); db.close()
        monkeypatch.setattr(conversation_readers.Reader, 'session_fingerprint', lambda self: None)  # force the read
        await get(after=first['after'])
        _, stats = await get('/telemetry/conversation/stats')
        assert stats['full_reads'] == len(pages) == 2
    run(monkeypatch, row(path, 'hermes'), scenario)


@pytest.mark.parametrize('delay', [0.0, 0.7])  # 0.7 s: past the reader's 0.5 s SQLite budget
def test_a_long_hermes_session_keeps_its_read_and_fingerprint_within_budget(tmp_path, monkeypatch, delay):
    """The fingerprint covers the snapshot's window, not the whole session
    (a whole-session aggregate exceeded the reader's SQLite step budget)."""
    path = tmp_path / 'state.db'; con = make_db(path)
    con.executemany("INSERT INTO messages(session_id,role,content,timestamp) VALUES('fixture-session',?,?,?)",
                    [('user' if i % 2 else 'assistant', f'message {i} ' + 'x' * 200, i) for i in range(30000)])
    con.commit(); con.close()
    async def scenario(get, calls, reads):
        status, first = await get()
        assert status == 200 and first['ok'] and len(first['events']) == 200
        db = sqlite3.connect(path); db.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES('foreign-session','user','FOREIGN',2)"); db.commit(); db.close()
        _, stats0 = await get('/telemetry/conversation/stats')
        _, quiet = await get(after=first['after'], wait='1')
        _, stats1 = await get('/telemetry/conversation/stats')
        assert quiet['unchanged'] and stats1['full_reads'] == stats0['full_reads'] and stats1['other_session_only'] >= 1
    run(monkeypatch, row(path, 'hermes'), scenario, dashboard_delay=delay)


def test_after_revalidation_other_sessions_writes_again_cost_no_reads(tmp_path, monkeypatch):
    path = tmp_path / 'state.db'; con = make_db(path)
    con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(1,'fixture-session','user','fixture body',1)"); con.commit(); con.close()
    now = [1000.0]
    def foreign():
        db = sqlite3.connect(path); db.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES('foreign-session','user','FOREIGN',2)"); db.commit(); db.close()
    async def scenario(get, calls, reads):
        _, first = await get()
        now[0] += 31                                   # REVALIDATE elapsed
        foreign()
        _, again = await get(after=first['after'])     # one checked read: same snapshot
        assert again['unchanged']
        _, stats0 = await get('/telemetry/conversation/stats')
        for _ in range(3):
            foreign()
            _, quiet = await get(after=first['after'])
            assert quiet['unchanged']
        _, stats1 = await get('/telemetry/conversation/stats')
        assert stats1['full_reads'] == stats0['full_reads'] and stats1['other_session_only'] - stats0['other_session_only'] == 3
    run(monkeypatch, row(path, 'hermes'), scenario, clock=lambda: now[0])


def test_an_expired_api_version_never_delays_a_read(tmp_path, monkeypatch):
    """Past the version cache's minute: the old value answers now, refreshed behind."""
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    async def scenario(get, calls, reads):
        await get()                                         # learns API 36 (the first one waits)
        loop = asyncio.get_running_loop()
        monkeypatch.setattr(backend, 'DASHBOARD_VERSION_SECONDS', 0.0)  # the cached value is now stale
        slow['version'] = 1.3
        started = loop.time(); status, page = await get()
        assert status == 200 and page['events'] and loop.time() - started < 0.6, loop.time() - started
        await asyncio.sleep(1.5)                            # the refresh finished behind
        assert calls['version'] == 2
    slow = {}
    real_sleep = asyncio.sleep
    async def upstream_delay(request):
        if request.path == '/api/version' and slow.get('version'):
            await real_sleep(slow['version'])
    run(monkeypatch, row(path, 'claude-code'), scenario, api=36, before_upstream=upstream_delay)


@pytest.mark.parametrize('change', ['content-same-length', 'role', 'tool-name', 'lengths-cancel'])
def test_any_change_to_a_shown_hermes_row_is_read(tmp_path, monkeypatch, change):
    """The fingerprint digests the shown rows themselves (r3 reviews)."""
    path = tmp_path / 'state.db'; con = make_db(path)
    if change == 'tool-name':
        con.execute("INSERT INTO messages(id,session_id,role,content,tool_name,timestamp) VALUES(1,'fixture-session','tool','{}','BeforeTool',1)")
    else:
        con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(1,'fixture-session','assistant','before',1)")
        con.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(2,'fixture-session','assistant','second',2)")
    con.commit(); con.close()
    async def scenario(get, calls, reads):
        _, first = await get()
        db = sqlite3.connect(path)
        if change == 'content-same-length': db.execute("UPDATE messages SET content='AFTER!' WHERE id=1")
        elif change == 'role': db.execute("UPDATE messages SET role='user' WHERE id=1")
        elif change == 'tool-name': db.execute("UPDATE messages SET tool_name='AfterTool' WHERE id=1")
        else: db.execute("UPDATE messages SET content='befor' WHERE id=1"); db.execute("UPDATE messages SET content='secondd' WHERE id=2")
        db.commit(); db.close()
        _, answer = await get(after=first['after'], wait='1')
        assert not answer.get('unchanged') and answer['events'] and answer['events'] != first['events'], answer
    run(monkeypatch, row(path, 'hermes'), scenario)


# --- r5 -----------------------------------------------------------------------

@pytest.mark.parametrize('version_mode', ['api34', 'malformed'])
def test_an_expired_api_36_never_authorizes_non_codex_content(tmp_path, monkeypatch, version_mode):
    """WintryLovelace r4: the dashboard went back to API 34 (or answers /api/version
    malformed) while an expired API 36 is cached. The expired value may only
    choose the binding source; publishing non-Codex content needs a confirmed one."""
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'Generated API34 must not publish')))
    current = row(path, 'claude-code')
    async def main():
        async def upstream(request):
            if request.path == '/api/version':
                await asyncio.sleep(.6)
                return web.json_response({'api': 34} if version_mode == 'api34' else {})
            if request.path.endswith('/history-binding'):
                return web.json_response({'error': 'route missing'}, status=404)
            return web.json_response({'agents': [current]})
        up = web.Application(); up.router.add_get('/{tail:.*}', upstream); up_runner, url = await start(up)
        monkeypatch.setattr(backend, 'DASHBOARD_URL', url)
        try:
            async with ClientSession() as client:
                app = web.Application(); app[backend.HTTP_SESSION_KEY] = client; app[backend.TMUX_BIN_KEY] = 'unused'
                shared = {'version': (asyncio.get_running_loop().time() - 61, 36)}
                app[backend.CONVERSATION_DASHBOARD_KEY] = shared; app[backend.CONVERSATION_UNCHANGED_KEY] = UnchangedPolls()
                app[backend.CONVERSATION_REFERENCES_KEY] = ReferenceStore(); app[backend.CONVERSATION_STATS_KEY] = collections.Counter()
                app.router.add_get('/telemetry/conversation', backend.serve_conversation)
                runner, base = await start(app)
                try:
                    for i in range(2):
                        async with client.get(base + '/telemetry/conversation?agent=FixtureAgent') as response:
                            body = await response.json()
                        assert body.get('error') == 'dashboard_upgrade_required' and not body.get('events'), body
                        if i == 0:
                            await asyncio.sleep(.75)
                    assert 'version' not in shared or shared['version'][1] == 34  # never extended
                finally:
                    await runner.cleanup()
        finally:
            await up_runner.cleanup()
    asyncio.run(main())


def _big_hermes(path, rows=201, tool_bytes=1048576):
    con = make_db(path)
    payload = '[]' + ' ' * (tool_bytes - 2)
    con.executemany("INSERT INTO messages(session_id,role,content,tool_calls,timestamp) VALUES('fixture-session','assistant',?,?,?)",
                    [(f'Generated bounded {i}', payload, i) for i in range(rows)])
    con.commit(); con.close()


def test_a_snapshot_of_very_large_rows_reads_and_holds(tmp_path, monkeypatch):
    """RockyGuericke r4: 201 rows of ~1 MB tool_calls. The fingerprint stops at
    the snapshot's byte budget instead of reading every row."""
    path = tmp_path / 'state.db'; _big_hermes(path)
    async def scenario(get, calls, reads):
        status, first = await get()
        assert status == 200 and first['events'] and first['limited'], first.get('error')
        db = sqlite3.connect(path); db.execute("INSERT INTO messages(session_id,role,content,timestamp) VALUES('foreign-session','user','FOREIGN',2)"); db.commit(); db.close()
        _, stats0 = await get('/telemetry/conversation/stats')
        status, quiet = await get(after=first['after'], wait='1')
        _, stats1 = await get('/telemetry/conversation/stats')
        assert status == 200 and quiet['unchanged'] and stats1['full_reads'] == stats0['full_reads']
    run(monkeypatch, row(path, 'hermes'), scenario, dashboard_delay=0.7)


def test_a_row_past_the_budget_is_not_shown_and_does_not_change_the_fingerprint(tmp_path):
    import conversation_readers
    path = tmp_path / 'state.db'; _big_hermes(path, rows=8)
    current = row(path, 'hermes')
    def fingerprint():
        with conversation_readers.open_reader(current) as reader:
            return reader.session_fingerprint(), [e['text'] for e in reader.read_page()['events']]
    before, shown = fingerprint()
    assert 'Generated bounded 0' not in shown                              # the oldest row is past the budget
    db = sqlite3.connect(path); db.execute("UPDATE messages SET content='Edited past the budget' WHERE id=1"); db.commit(); db.close()
    after, shown_after = fingerprint()
    assert after == before and shown_after == shown                         # not shown, not counted
    db = sqlite3.connect(path); db.execute("UPDATE messages SET content='Edited and shown' WHERE id=8"); db.commit(); db.close()
    assert fingerprint()[0] != before                                       # a shown row: counted


# --- r7: a reader takes over its own held slot --------------------------------

def test_readers_take_over_their_slots_when_they_ask_again_at_once(tmp_path, monkeypatch):
    """WintryLovelace r6: four held polls, a 4 ms user operation, the same four
    readers ask again before the server notices the old requests' disconnect.
    They must take over their slots, not meet the cap."""
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    readers = [f'reader{i:02d}abcdefghij' for i in range(4)]
    async def scenario(get, calls, reads):
        _, first = await get()
        async def hold(reader, timeout):
            return await get(after=first['after'], wait='25', reader=reader, _timeout=timeout)
        old = [asyncio.ensure_future(hold(r, 0.3)) for r in readers]
        await asyncio.sleep(0.15)
        _, stats = await get('/telemetry/conversation/stats')
        assert stats['held_now'] == 4
        for task in old:                                   # the clients abort (the user operation)
            with pytest.raises(asyncio.TimeoutError):
                await task
        new = [asyncio.ensure_future(get(after=first['after'], wait='5', reader=r)) for r in readers]
        await asyncio.sleep(0.05)                          # well before the 250 ms disconnect check
        with path.open('ab') as f: f.write(line(claude('assistant', [dict(type='text', text='after the operation')])))
        answers = await asyncio.gather(*new)
        for status, page in answers:
            assert status == 200 and page.get('slot') is True and [e['text'] for e in page['events']] == ['after the operation'], page
        _, stats = await get('/telemetry/conversation/stats')
        assert stats['held_cap_reached'] == 0 and stats['held_taken_over'] == 4 and stats['held_now'] == 0
    run(monkeypatch, row(path, 'claude-code'), scenario)


def test_a_taken_over_slot_counts_once_and_others_still_meet_the_cap(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    monkeypatch.setattr(backend, 'CONVERSATION_MAX_HELD', 1)
    async def scenario(get, calls, reads):
        _, first = await get()
        a = asyncio.ensure_future(get(after=first['after'], wait='2', reader='readerAAAAAAAAAAAA'))
        await asyncio.sleep(0.1)
        b = asyncio.ensure_future(get(after=first['after'], wait='1', reader='readerAAAAAAAAAAAA'))  # same reader
        status_a, _ = await a
        assert status_a == 204                                         # replaced at once
        await asyncio.sleep(0.1)
        _, stats = await get('/telemetry/conversation/stats')
        assert stats['held_now'] == 1                                  # counted once
        _, other = await get(after=first['after'], wait='1', reader='readerBBBBBBBBBBBB')
        assert 'slot' not in other and other['unchanged']              # another reader: the cap
        _, mine = await b
        assert mine['slot'] is True
        _, stats = await get('/telemetry/conversation/stats')
        assert stats['held_now'] == 0
    run(monkeypatch, row(path, 'claude-code'), scenario)


@pytest.mark.parametrize('query', [dict(after='x', reader='readerAAAAAAAAAAAA'),          # without wait
                                   dict(after='x', wait='1', reader='short'),
                                   dict(after='x', wait='1', reader='bad/reader/value!!')])
def test_reader_is_bounded_and_only_with_wait(tmp_path, monkeypatch, query):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    async def scenario(get, calls, reads):
        status, payload = await get(**query)
        assert status == 400 and payload['error'] == 'invalid_query' and reads == []
    run(monkeypatch, row(path, 'claude-code'), scenario)


def test_at_the_cap_a_changed_record_takes_a_quiet_readers_slot(tmp_path, monkeypatch):
    """CuriousPauling r6 P3-1: a reader whose record changed does not wait
    4 s behind readers that are holding with nothing new. The quietest one
    answers "unchanged" without a slot (it polls at the plain interval)."""
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    monkeypatch.setattr(backend, 'CONVERSATION_MAX_HELD', 1)
    monkeypatch.setattr(backend, 'CONVERSATION_QUIET_SECONDS', 0.3)
    async def scenario(get, calls, reads):
        _, first = await get()
        with path.open('ab') as f: f.write(line(claude('assistant', [dict(type='text', text='new for B')])))
        _, second = await get(after=first['after'])            # stores the new state under its cursor
        loop = asyncio.get_running_loop()
        quiet = asyncio.ensure_future(get(after=second['after'], wait='10', reader='readerAAAAAAAAAAAA'))
        await asyncio.sleep(0.1)
        # Not yet quiet long enough: the cap, as before.
        _, early = await get(after=first['after'], wait='5', reader='readerBBBBBBBBBBBB')
        assert 'slot' not in early and [e['text'] for e in early['events']] == ['new for B']
        await asyncio.sleep(0.4)
        started = loop.time()
        _, taker = await get(after=first['after'], wait='5', reader='readerBBBBBBBBBBBB')
        assert taker['slot'] is True and [e['text'] for e in taker['events']] == ['new for B']
        status, given = await quiet
        assert status == 200 and given['unchanged'] and given['held'] is True and 'slot' not in given
        assert loop.time() - started < 0.5
        _, stats = await get('/telemetry/conversation/stats')
        assert stats['held_given_up'] == 1 and stats['held_cap_reached'] == 1 and stats['held_now'] == 0
    run(monkeypatch, row(path, 'claude-code'), scenario)


def test_an_unchanged_record_or_an_anonymous_poll_never_takes_a_slot(tmp_path, monkeypatch):
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    monkeypatch.setattr(backend, 'CONVERSATION_MAX_HELD', 1)
    monkeypatch.setattr(backend, 'CONVERSATION_QUIET_SECONDS', 0.1)
    async def scenario(get, calls, reads):
        _, first = await get()
        with path.open('ab') as f: f.write(line(claude('assistant', [dict(type='text', text='x')])))
        _, second = await get(after=first['after'])
        quiet = asyncio.ensure_future(get(after=second['after'], wait='2', reader='readerAAAAAAAAAAAA'))
        await asyncio.sleep(0.4)
        _, same = await get(after=second['after'], wait='5', reader='readerBBBBBBBBBBBB')   # nothing new
        _, anonymous = await get(after=first['after'], wait='5')                           # no reader id
        assert 'slot' not in same and 'slot' not in anonymous
        _, kept = await quiet
        assert kept['slot'] is True
        _, stats = await get('/telemetry/conversation/stats')
        assert stats['held_given_up'] == 0 and stats['held_cap_reached'] == 2
    run(monkeypatch, row(path, 'claude-code'), scenario)


def test_a_reader_giving_up_its_slot_still_gets_its_own_new_content(tmp_path, monkeypatch):
    """RockyGuericke r7: the quiet reader's record is written just before a
    changed reader takes its slot. It must answer with that content, not
    "unchanged" (which would leave it to the next plain poll, about 4 s)."""
    path = tmp_path / 'history.jsonl'; path.write_bytes(line(claude('user', 'fixture body')))
    monkeypatch.setattr(backend, 'CONVERSATION_MAX_HELD', 1)
    monkeypatch.setattr(backend, 'CONVERSATION_QUIET_SECONDS', 0.3)
    # The quiet reader does not look again by itself during the test: only
    # the take-over wakes it, so the write is always seen at that moment.
    monkeypatch.setattr(backend, 'CONVERSATION_WAIT_STEP', 10.0)
    async def scenario(get, calls, reads):
        _, first = await get()
        with path.open('ab') as f: f.write(line(claude('assistant', [dict(type='text', text='one')])))
        _, second = await get(after=first['after'])
        quiet = asyncio.ensure_future(get(after=second['after'], wait='20', reader='readerAAAAAAAAAAAA'))
        await asyncio.sleep(0.5)
        with path.open('ab') as f: f.write(line(claude('assistant', [dict(type='text', text='two')])))
        _, taker = await get(after=first['after'], wait='5', reader='readerBBBBBBBBBBBB')
        assert taker['slot'] is True and [e['text'] for e in taker['events']] == ['one', 'two']
        status, given = await asyncio.wait_for(quiet, 3)
        assert status == 200 and not given.get('unchanged') and 'slot' not in given
        assert [e['text'] for e in given['events']] == ['two']
        _, stats = await get('/telemetry/conversation/stats')
        assert stats['held_given_up'] == 1 and stats['held_now'] == 0
    run(monkeypatch, row(path, 'claude-code'), scenario)
