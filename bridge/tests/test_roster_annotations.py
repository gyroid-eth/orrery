"""Public task annotations survive the legacy bridge compatibility layer."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys

from aiohttp import ClientSession, ClientTimeout, web
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orrery_backend as ob
from orrery_backend import normalize_annotations, prepare_agents_payload


def test_task_only_annotation_survives_normalization():
    assert normalize_annotations({'annotations': {'BuilderFixture': {'task': ' User summary '}}}) == {
        'BuilderFixture': {'role': '', 'emoji': '', 'group': '', 'task': 'User summary'},
    }


def test_authoritative_roster_annotation_wins_over_cached_compatibility_labels():
    labels = {'BuilderFixture': {'role': 'stale', 'task': 'Stale summary'}}
    for annotation in (None, {'role': 'reviewer', 'task': 'New summary'}):
        payload = json.dumps({'agents': [{'name': 'BuilderFixture', 'annot': annotation}]}).encode()
        row = json.loads(prepare_agents_payload(payload, labels))['agents'][0]
        assert row['annot'] == annotation


def test_old_roster_still_uses_compatibility_annotations():
    label = {'role': 'builder', 'emoji': '', 'group': 'fixtures'}
    payload = json.dumps({'agents': [{'name': 'BuilderFixture'}]}).encode()
    assert json.loads(prepare_agents_payload(payload, {'BuilderFixture': label}))['agents'][0]['annot'] == label


@asynccontextmanager
async def legacy_annotation_proxy(monkeypatch, *, hold_first_read=False, status=200):
    """API 37 rows omit annot; annotation reads may capture a delayed snapshot."""
    state = {'role': 'builder', 'annotation_reads': 0}
    started, release, joined = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def upstream(request):
        if request.path == '/api/agents':
            return web.json_response({'agents': [{'name': 'BuilderFixture', 'category': 'agent'}]})
        if request.path == '/api/annotations':
            state['annotation_reads'] += 1
            role = state['role']
            if hold_first_read and state['annotation_reads'] == 1:
                started.set()
                await release.wait()
            return web.json_response({'annotations': {'BuilderFixture': {
                'role': role, 'emoji': '✳', 'group': 'fixtures',
            }}})
        if request.path == '/api/annotate':
            if status >= 400:
                return web.json_response({'ok': False}, status=status)
            state['role'] = (await request.json())['role']
            if status == 204:
                return web.Response(status=status)
            return web.json_response({'ok': True}, status=status)
        return web.json_response({'api': 37})

    async def start(app):
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        return runner, f'http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}'

    app = web.Application()
    app.router.add_route('*', '/{tail:.*}', upstream)
    upstream_runner, upstream_url = await start(app)
    monkeypatch.setattr(ob, 'DASHBOARD_URL', upstream_url)
    monkeypatch.setattr(ob, '_annotations_cache', (0.0, {}))
    monkeypatch.setattr(ob, '_annotations_generation', 0, raising=False)
    bridge = web.Application()
    session = ClientSession(timeout=ClientTimeout(total=3))
    bridge[ob.HTTP_SESSION_KEY] = session
    bridge[ob.TMUX_BIN_KEY] = ob.LegacyTargetBoundary('tmux')
    bridge[ob.PROXY_INFLIGHT_KEY] = {}
    roster_reads = 0
    async def bridge_roster(request):
        nonlocal roster_reads
        roster_reads += 1
        if roster_reads == 2:
            joined.set()
        return await ob.proxy_dashboard(request)
    bridge.router.add_get('/telemetry/agents', bridge_roster)
    bridge.router.add_post('/api/annotate', ob.proxy_dashboard_passthrough)
    runner, base = await start(bridge)
    try:
        async with ClientSession(timeout=ClientTimeout(total=3)) as client:
            async def roster():
                async with client.get(base + '/telemetry/agents') as response:
                    assert response.status == 200
                    return (await response.json())['agents'][0]
            async def save():
                async with client.post(base + '/api/annotate', json={
                    'name': 'BuilderFixture', 'role': 'reviewer', 'emoji': '✳', 'group': 'fixtures',
                }) as response:
                    await response.read()
                    return response.status
            yield roster, save, state, started, release, joined
    finally:
        release.set()
        await runner.cleanup()
        await session.close()
        await upstream_runner.cleanup()


@pytest.mark.parametrize('status', [200, 204, 400])
def test_legacy_roster_after_annotation_save_uses_current_role(monkeypatch, status):
    async def scenario():
        async with legacy_annotation_proxy(monkeypatch, status=status) as (roster, save, state, _, __, ___):
            assert (await roster())['annot']['role'] == 'builder'
            assert await save() == status
            after = await roster()
            expected = 'reviewer' if status < 300 else 'builder'
            assert after['annot']['role'] == expected
            assert state['annotation_reads'] == (2 if status < 300 else 1)
    asyncio.run(scenario())


def test_old_annotation_read_cannot_restore_stale_cache_after_save(monkeypatch):
    async def scenario():
        async with legacy_annotation_proxy(monkeypatch, hold_first_read=True) as (roster, save, state, started, release, joined):
            old = asyncio.create_task(roster())
            await asyncio.wait_for(started.wait(), 2)
            assert await save() == 200
            # A post-save poll can join the old in-flight roster request.
            current = asyncio.create_task(roster())
            await asyncio.wait_for(joined.wait(), 2)
            release.set()
            _, after = await asyncio.gather(old, current)
            assert after['annot']['role'] == 'reviewer'
            # The delayed snapshot must not poison the next cache hit either.
            assert (await roster())['annot']['role'] == 'reviewer'
            assert state['annotation_reads'] == 2
    asyncio.run(scenario())
