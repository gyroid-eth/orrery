import asyncio

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from codex_skill_catalog import codex_home, enabled_skills
import codex_skill_catalog
import orrery_backend as backend


def test_skill_scope_and_native_enabled_entries(tmp_path):
    home = tmp_path / 'profile'
    assert codex_home(str(home / 'sessions/2026/01/05/rollout-test.jsonl')) == home
    assert codex_home(str(home / 'wrong/2026/01/05/rollout-test.jsonl')) is None
    workspace = tmp_path / 'workspace'
    native = {'data': [
        {'cwd': '/', 'skills': [{'name': 'wrong', 'enabled': True}]},
        {'cwd': str(workspace), 'skills': [
            {'name': 'fixture-check', 'enabled': True, 'path': '/private/example', 'description': 'Check a fixture'},
            {'name': 'disabled', 'enabled': False},
            {'name': 'bad name', 'enabled': True},
        ]},
    ]}
    assert enabled_skills(native, workspace) == [
        {'name': 'fixture-check', 'kind': 'skill', 'description': 'Check a fixture'},
    ]


@pytest.mark.asyncio
async def test_native_error_can_retry_and_catalog_is_scoped_by_pane(monkeypatch, tmp_path):
    seen = []

    async def context(request, name, pane, incarnation):
        return 'codex', tmp_path / name, tmp_path / (name + '-profile')

    async def native(binary, cwd, home):
        seen.append((cwd, home))
        if len(seen) == 1:
            raise ValueError('fixture failure')
        return [dict(kind='skill', name=cwd.name + '-check', description='Fixture')]

    monkeypatch.setattr(backend, 'codex_skill_context', context)
    monkeypatch.setattr(codex_skill_catalog, 'list_skills', native)
    app = web.Application()
    app[backend.CODEX_SKILLS_KEY] = {}
    app[backend.CODEX_SKILLS_LIMIT] = asyncio.Semaphore(2)
    app.router.add_get('/telemetry/skills', backend.serve_skills)
    async with TestClient(TestServer(app)) as client:
        query = dict(program='codex', agent='FixtureOne', paneId='%9', incarnation='c' * 32)
        reply = await client.get('/telemetry/skills', params=query)
        assert reply.status == 503
        assert ('status', 'builtin') in [(item['name'], item['kind']) for item in (await reply.json())['skills']]
        for params, expected in [(query, 'FixtureOne-check'), (query, 'FixtureOne-check'),
                                 ({**query, 'agent': 'FixtureTwo'}, 'FixtureTwo-check')]:
            reply = await client.get('/telemetry/skills', params=params)
            assert reply.status == 200
            assert [item['name'] for item in (await reply.json())['skills'] if item['kind'] == 'skill'] == [expected]
    assert len(seen) == 3
