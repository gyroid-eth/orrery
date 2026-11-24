"""Read the effective Codex skill catalog using its local App Server."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
import re
import signal

SKILL_NAME = re.compile(r'[A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)*', re.ASCII)
SESSION_DIRS = re.compile(r'[0-9]{4}/[0-9]{2}/[0-9]{2}/rollout-[^/]+\.jsonl', re.ASCII)


def codex_home(transcript):
    path = Path(transcript)
    if not path.is_absolute() or len(path.parts) < 7 or path.parents[3].name != 'sessions':
        return None
    relative = path.relative_to(path.parents[3]).as_posix()
    return path.parents[4] if SESSION_DIRS.fullmatch(relative) else None


def enabled_skills(result, cwd):
    catalogs = result.get('data')
    if not isinstance(catalogs, list):
        raise ValueError('invalid skill catalog')
    selected = next((entry for entry in catalogs
                     if isinstance(entry, dict) and entry.get('cwd') == str(cwd)), None)
    if not selected or not isinstance(selected.get('skills'), list):
        raise ValueError('missing skill catalog')
    skills = {}
    for item in selected['skills']:
        if not isinstance(item, dict) or item.get('enabled') is not True:
            continue
        name = item.get('name')
        if not isinstance(name, str) or len(name) > 128 or not SKILL_NAME.fullmatch(name):
            continue
        description = item.get('description')
        skills.setdefault(name, dict(name=name, kind='skill',
                                     description=description[:512] if isinstance(description, str) else ''))
    return list(skills.values())


async def list_skills(binary, cwd, home, *, timeout=6):
    # Supply the bound session's cwd and CODEX_HOME. Only initialize and
    # skills/list are sent. No thread, prompt, usage, or approval RPC.
    process = await asyncio.create_subprocess_exec(
        binary, 'app-server', cwd=cwd, env={**os.environ, 'CODEX_HOME': str(home)},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True, limit=2**20)
    async def send(message):
        process.stdin.write((json.dumps(message) + '\n').encode('utf-8'))
        await process.stdin.drain()
    async def response(request_id):
        while line := await process.stdout.readline():
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict) or message.get('id') != request_id:
                continue
            result = message.get('result')
            if not isinstance(result, dict):
                raise ValueError('skill request failed')
            return result
        raise ValueError('App Server closed')
    try:
        async with asyncio.timeout(timeout):
            await send(dict(id=1, method='initialize', params=dict(clientInfo=dict(
                name='orrery-cockpit', title='ORRERY', version='1'))))
            await response(1)
            await send(dict(method='initialized'))
            await send(dict(id=2, method='skills/list', params=dict(cwds=[str(cwd)], forceReload=True)))
            return enabled_skills(await response(2), cwd)
    finally:
        process.stdin.close()
        # The path entry can be a launcher. End its session, including children.
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), 1)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
