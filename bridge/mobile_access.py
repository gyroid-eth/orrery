"""Phone access for the Settings panel: GET/PUT /telemetry/mobile.

The phone reader belongs to Telemetry. This module does not write Telemetry's
files or talk to launchd; it runs Telemetry's own ``agentstack-mobile`` command
(a fixed path, an argv list, no shell) and shows what it reports. The only
cockpit-side state is the "Send from phone" adapter: it follows the reader's
effective send switch at once (no backend restart), on every change and each
time Settings is opened, and is saved as ``enable_mobile_terminal`` in
~/.orrery/config.json for the next start. A reader started by hand is left
alone, together with the enable_mobile_terminal its owner set.

The routes sit behind the backend's own-page and JSON-write middlewares; the
phone cannot reach them (the reader's route table is fixed).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import tempfile

from aiohttp import web

HELPER_TIMEOUT = 30
MAX_BODY = 2048
MAX_OUTPUT = 64 * 1024
CODE = re.compile(r'[a-z_]{1,40}')
CHANGE_KEYS = {'access', 'send', 'owner_login', 'public_origin', 'policy_reviewed'}
LOCK_KEY = web.AppKey('mobile_access_lock', asyncio.Lock)
INPUT_KEY = web.AppKey('mobile_access_input', object)
CONFIG_KEY = web.AppKey('mobile_access_config', Path)
HEADERS = {'Cache-Control': 'no-store'}


def helper_path() -> Path:
    override = os.environ.get('ORRERY_MOBILE_HELPER')
    if override:
        return Path(override)
    home = os.environ.get('AGENTSTACK_HOME') or str(Path.home() / '.agentstack')
    return Path(home) / 'bin' / 'agentstack-mobile'


def reply(value: dict, status: int = 200) -> web.Response:
    return web.json_response(value, status=status, headers=HEADERS)


def failure(code: str, status: int = 200) -> web.Response:
    return reply({'ok': False, 'error': code if CODE.fullmatch(code or '') else 'mobile_unavailable'}, status)


async def run_helper(command: str, stdin: bytes | None = None) -> dict:
    helper = helper_path()
    if not helper.is_file() or not os.access(helper, os.X_OK):
        return {'ok': False, 'error': 'telemetry_missing'}
    try:
        process = await asyncio.create_subprocess_exec(
            str(helper), command,
            stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    except OSError:
        return {'ok': False, 'error': 'telemetry_missing'}
    try:
        out, _ = await asyncio.wait_for(process.communicate(stdin), HELPER_TIMEOUT)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return {'ok': False, 'error': 'mobile_slow'}
    try:
        value = json.loads(out[:MAX_OUTPUT])
    except ValueError:
        return {'ok': False, 'error': 'mobile_unavailable'}
    if not isinstance(value, dict):
        return {'ok': False, 'error': 'mobile_unavailable'}
    if value.get('ok') is not True:
        error = value.get('error')
        return {'ok': False, 'error': error if isinstance(error, str) and CODE.fullmatch(error) else 'mobile_unavailable'}
    return value


def save_send(path: Path, enabled: bool) -> None:
    """Set only enable_mobile_terminal, keeping every other key as written."""
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raw = {}
    except (OSError, ValueError):
        raise ValueError('config_invalid') from None
    if not isinstance(raw, dict):
        raise ValueError('config_invalid')
    if raw.get('enable_mobile_terminal') is enabled:
        return
    raw['enable_mobile_terminal'] = enabled
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.config.', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, (json.dumps(raw, indent=2, ensure_ascii=False) + '\n').encode())
        os.close(fd)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def with_cockpit(app: web.Application, value: dict) -> dict:
    coordinator = app[INPUT_KEY]
    return {**value, 'cockpit': {'send': bool(getattr(coordinator, 'enabled', False))}}


def owns_send(value: dict) -> bool:
    """Whether Settings decides the cockpit's Send adapter. Not while a reader
    started by hand holds the port (Settings does not run it; today's Terminal
    users keep enable_mobile_terminal as they set it), and not before Settings
    has ever saved anything."""
    relay = value.get('relay') if isinstance(value.get('relay'), dict) else {}
    return value.get('saved') is True and relay.get('manual') is not True


async def follow_send(app: web.Application, value: dict) -> str | None:
    """Make the cockpit adapter match the reader's effective send switch."""
    if not owns_send(value):
        return None
    effective = value.get('effective')
    wanted = isinstance(effective, dict) and effective.get('send') is True
    coordinator = app[INPUT_KEY]
    if getattr(coordinator, 'enabled', False) != wanted:
        coordinator.set_enabled(wanted)
    try:
        await asyncio.to_thread(save_send, app[CONFIG_KEY], wanted)
    except (OSError, ValueError):
        return 'config_invalid'
    return None


async def get_mobile(request: web.Request) -> web.Response:
    # A change made outside the cockpit (`agentstack-mobile off` in a
    # terminal) reaches the Send adapter the next time Settings is opened.
    async with request.app[LOCK_KEY]:
        value = await run_helper('status')
        if value.get('ok') is not True:
            return failure(value.get('error'))
        problem = await follow_send(request.app, value)
    result = with_cockpit(request.app, value)
    if problem:
        result['warning'] = problem
    return reply(result)


async def put_mobile(request: web.Request) -> web.Response:
    data = await request.content.read(MAX_BODY + 1)
    try:
        change = json.loads(data) if len(data) <= MAX_BODY else None
    except ValueError:
        change = None
    if not isinstance(change, dict) or not change or set(change) - CHANGE_KEYS:
        return failure('change_invalid', 400)
    async with request.app[LOCK_KEY]:
        value = await run_helper('apply', json.dumps(change).encode())
        if value.get('ok') is not True:
            return failure(value.get('error'))
        problem = await follow_send(request.app, value)
    result = with_cockpit(request.app, value)
    if problem:
        result['warning'] = problem
    return reply(result)


def install(app: web.Application, coordinator, *, config_path: Path) -> None:
    app[LOCK_KEY] = asyncio.Lock()
    app[INPUT_KEY] = coordinator
    app[CONFIG_KEY] = config_path
    app.router.add_get('/telemetry/mobile', get_mobile)
    app.router.add_put('/telemetry/mobile', put_mobile)
