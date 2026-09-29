#!/usr/bin/env python3
"""Pure aiohttp mock for cockpit development; it never invokes tmux.

Run from the repository root:

    python3 bridge/tests/mock_backend.py

Then open http://127.0.0.1:8803/cockpit.html.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import time
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web


HOST = "127.0.0.1"
PORT = 8803
BRIDGE_DIR = Path(__file__).resolve().parents[1]
CREATED = int(time.time()) - 1800

SESSIONS = [
    {"session": "AmberNode", "attached": True, "windows": 1, "created": CREATED},
    {"session": "CobaltRelay", "attached": False, "windows": 1, "created": CREATED + 300},
    {"session": "SpareSession", "attached": False, "windows": 1, "created": CREATED + 600},
    {"session": "BronzeSignal", "attached": False, "windows": 1, "created": CREATED + 720},
    {"session": "SilverBeacon", "attached": False, "windows": 1, "created": CREATED + 840},
    {"session": "QuartzNode", "attached": False, "windows": 1, "created": CREATED + 960},
    {"session": "CopperRelay", "attached": False, "windows": 1, "created": CREATED + 1080},
    {"session": "SlateSignal", "attached": False, "windows": 1, "created": CREATED + 1200},
]

PANES: dict[str, list[dict[str, Any]]] = {
    "AmberNode": [
        {
            "paneId": "%101",
            "windowId": "@101",
            "sessionId": "$101",
            "windowIndex": "0",
            "paneIndex": "0",
            "width": 160,
            "height": 48,
            "active": True,
            "windowName": "orchestrator",
            "currentCommand": "zsh",
        }
    ],
    "CobaltRelay": [
        {
            "paneId": "%201",
            "windowId": "@201",
            "sessionId": "$201",
            "windowIndex": "0",
            "paneIndex": "0",
            "width": 120,
            "height": 42,
            "active": True,
            "windowName": "frontend",
            "currentCommand": "codex",
        },
        {
            "paneId": "%202",
            "windowId": "@201",
            "sessionId": "$201",
            "windowIndex": "0",
            "paneIndex": "1",
            "width": 120,
            "height": 42,
            "active": False,
            "windowName": "checks",
            "currentCommand": "zsh",
        },
    ],
    "SpareSession": [
        {
            "paneId": "%301",
            "windowId": "@301",
            "sessionId": "$301",
            "windowIndex": "0",
            "paneIndex": "0",
            "width": 100,
            "height": 32,
            "active": True,
            "windowName": "scratch",
            "currentCommand": "zsh",
        }
    ],
}
for fixture_index, fixture_session in enumerate(
    ("BronzeSignal", "SilverBeacon", "QuartzNode", "CopperRelay", "SlateSignal"),
    start=4,
):
    PANES[fixture_session] = [
        {
            "paneId": f"%{fixture_index}01",
            "windowId": f"@{fixture_index}01",
            "sessionId": f"${fixture_index}01",
            "windowIndex": "0",
            "paneIndex": "0",
            "width": 120,
            "height": 42,
            "active": True,
            "windowName": "fixture",
            "currentCommand": "zsh",
        }
    ]

AGENTS = [
    {
        "name": "AmberNode",
        "provider": "anthropic",
        "model": "opus-4.6",
        "ctx_window": "200k",
        "ctx_used": 44,
        "running": True,
        "category": "agent",
        "act_state": "work",
        "live": "coordinating ORRERY",
        "task": "unified backend integration",
    },
    {
        "name": "CobaltRelay",
        "provider": "openai",
        "model": "gpt-5",
        "ctx_window": "256k",
        "ctx_used": 27,
        "running": True,
        "category": "agent",
        "act_state": "work",
        "live": "wiring cockpit jump",
        "task": "multi-session cockpit",
    },
    {
        "name": "IndigoBeacon",
        "provider": "openai",
        "model": "gpt-5",
        "ctx_window": "256k",
        "ctx_used": 12,
        "running": False,
        "category": "agent",
        "act_state": "wait",
        "live": "",
        "task": "offline jump fallback",
    },
]

MESSAGES = [
    {
        "id": 1,
        "sender": "AmberNode",
        "recipient": "CobaltRelay",
        "subject": "Wire roster jump to the active pane",
        "importance": "high",
        "ts": int(time.time()) - 75,
    },
    {
        "id": 2,
        "sender": "CobaltRelay",
        "recipient": "AmberNode",
        "subject": "WS v2 mock is online",
        "importance": "normal",
        "ts": int(time.time()) - 20,
    },
]

MAIL_MESSAGES = [
    {
        "id": 101,
        "ts": int(time.time()) - 840,
        "sender": "AmberNode",
        "recipients": [
            {"name": "CobaltRelay", "kind": "to"},
            {"name": "SilverBeacon", "kind": "cc"},
        ],
        "subject": "Cycle 4 cockpit kickoff",
        "excerpt": "Please wire the readable mail rail.",
        "body_md": (
            "## Cycle 4\n\nPlease wire the **readable mail rail** and keep raw "
            "HTML escaped.\n\n- backfill recent mail\n- open full messages"
        ),
        "importance": "high",
        "thread_id": "mock-cycle-4",
    },
    {
        "id": 102,
        "ts": int(time.time()) - 480,
        "sender": "CobaltRelay",
        "recipients": [{"name": "AmberNode", "kind": "to"}],
        "subject": "Mail drawer implementation ready",
        "excerpt": "Drawer and agent filters are ready for review.",
        "body_md": (
            "Drawer and agent filters are ready for review.\n\n"
            "The renderer is escape-first and links remain plain text."
        ),
        "importance": "normal",
        "thread_id": "mock-cycle-4",
    },
    {
        "id": 103,
        "ts": int(time.time()) - 120,
        "sender": "SilverBeacon",
        "recipients": [{"name": "AmberNode", "kind": "to"}],
        "subject": "Portrait QA complete",
        "excerpt": "The black-and-white medallions passed the visual check.",
        "body_md": (
            "The black-and-white medallions passed the visual check.\n\n"
            "`64px` and `256px` outputs are both present."
        ),
        "importance": "normal",
        "thread_id": None,
    },
]


def session_name_for_pane(pane_id: str) -> str | None:
    for session, panes in PANES.items():
        if any(pane["paneId"] == pane_id for pane in panes):
            return session
    return None


async def cockpit(_: web.Request) -> web.StreamResponse:
    return web.FileResponse(BRIDGE_DIR / "cockpit.html")


async def telemetry_agents(_: web.Request) -> web.Response:
    return web.json_response({"agents": AGENTS})


async def telemetry_messages(request: web.Request) -> web.Response:
    try:
        since = int(request.query.get("since", "0"))
        limit = max(1, min(100, int(request.query.get("limit", "40"))))
    except ValueError:
        return web.json_response({"error": "invalid since or limit"}, status=400)
    now = int(time.time())
    return web.json_response(
        {"ok": True, "now": now, "messages": [m for m in MESSAGES if m["ts"] > since][-limit:]}
    )


async def telemetry_graph(_: web.Request) -> web.Response:
    return web.json_response(
        {
            "spawn": [
                {"source": "AmberNode", "target": "CobaltRelay"},
                {"source": "AmberNode", "target": "IndigoBeacon"},
            ]
        }
    )


async def telemetry_sessions(_: web.Request) -> web.Response:
    return web.json_response(SESSIONS)


async def telemetry_health(_: web.Request) -> web.Response:
    return web.json_response({"backend": "ok", "dashboard": True})


def mail_meta(message: dict[str, Any]) -> dict[str, Any]:
    return {
        key: message[key]
        for key in (
            "id",
            "ts",
            "sender",
            "recipients",
            "subject",
            "excerpt",
            "importance",
            "thread_id",
        )
    }


def mail_limit(request: web.Request, default: int) -> int | None:
    try:
        return max(1, min(100, int(request.query.get("limit", str(default)))))
    except ValueError:
        return None


async def telemetry_mail_recent(request: web.Request) -> web.Response:
    limit = mail_limit(request, 40)
    if limit is None:
        return web.json_response({"ok": False, "error": "invalid limit"}, status=400)
    agent = request.query.get("agent")
    messages = MAIL_MESSAGES
    if agent:
        messages = [
            message
            for message in messages
            if message["sender"] == agent
            or any(recipient["name"] == agent for recipient in message["recipients"])
        ]
    recent = sorted(messages, key=lambda message: message["ts"], reverse=True)[:limit]
    return web.json_response(
        {"ok": True, "now": int(time.time()), "messages": [mail_meta(m) for m in recent]}
    )


async def telemetry_mail_message(request: web.Request) -> web.Response:
    try:
        message_id = int(request.query.get("id", ""))
    except ValueError:
        return web.json_response({"ok": False, "error": "invalid id"}, status=400)
    message = next(
        (item for item in MAIL_MESSAGES if item["id"] == message_id),
        None,
    )
    if message is None:
        return web.json_response({"ok": False, "error": "not found"}, status=404)
    full = {
        key: message[key]
        for key in (
            "id",
            "ts",
            "sender",
            "recipients",
            "subject",
            "body_md",
            "importance",
            "thread_id",
        )
    }
    return web.json_response({"ok": True, "message": full})


async def telemetry_mail_thread(request: web.Request) -> web.Response:
    thread_id = request.query.get("thread_id")
    limit = mail_limit(request, 50)
    if not thread_id or limit is None:
        return web.json_response(
            {"ok": False, "error": "invalid thread_id or limit"},
            status=400,
        )
    messages = sorted(
        (message for message in MAIL_MESSAGES if message["thread_id"] == thread_id),
        key=lambda message: message["ts"],
    )[:limit]
    return web.json_response(
        {"ok": True, "now": int(time.time()), "messages": [mail_meta(m) for m in messages]}
    )


async def telemetry_spawn(request: web.Request) -> web.Response:
    """Return deterministic fake spawn responses without launching a process.

    A task equal to ``__mock_fail__`` exercises the dashboard-error path.
    Successful children are added only to AGENTS, so the cockpit discovers them
    on its ordinary roster poll rather than through a spawn-specific refresh.
    """
    try:
        payload = await request.json()
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "invalid JSON body"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"ok": False, "error": "JSON body must be an object"}, status=400)
    if payload.get("task") == "__mock_fail__":
        return web.json_response(
            {"ok": False, "error": "mock dashboard rejected spawn"}, status=422
        )
    if not payload.get("parent") or not payload.get("task"):
        return web.json_response(
            {"ok": False, "error": "parent and task are required"}, status=422
        )
    if payload.get("model") not in {"claude-opus-4-7", "claude-sonnet-4-6"}:
        return web.json_response({"ok": False, "error": "model not allowed"}, status=422)

    child_name = "MockFaraday"
    if not any(agent["name"] == child_name for agent in AGENTS):
        AGENTS.append(
            {
                "name": child_name,
                "provider": "anthropic",
                "model": payload["model"],
                "ctx_window": "200k",
                "ctx_used": 1,
                "running": True,
                "category": "agent",
                "act_state": "work",
                "live": "starting mock child",
                "task": payload["task"],
                "last_active": int(time.time()),
            }
        )
    return web.json_response(
        {
            "ok": True,
            "child_name": child_name,
            "tmux_session": child_name,
            "worktree": bool(payload.get("worktree")),
            "mock": True,
        }
    )


async def telemetry_portrait(request: web.Request) -> web.Response:
    name = html.escape(request.query.get("name", "?")[:40])
    initial = html.escape(name[:1].upper() or "?")
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
        '<rect width="64" height="64" rx="32" fill="#5f6d72"/>'
        f'<text x="32" y="41" text-anchor="middle" font-size="28" fill="#ece5d6" '
        f'font-family="serif" aria-label="{name}">{initial}</text></svg>'
    )
    return web.Response(text=svg, content_type="image/svg+xml")


async def send_reset(ws: web.WebSocketResponse, session: str) -> None:
    await ws.send_json({"type": "reset", "session": session, "panes": PANES[session]})


async def scripted_output(ws: web.WebSocketResponse, session: str) -> None:
    await asyncio.sleep(0.04)
    for pane in PANES[session]:
        with contextlib.suppress(ConnectionResetError, RuntimeError):
            await ws.send_json(
                {
                    "type": "output",
                    "session": session,
                    "paneId": pane["paneId"],
                    "data": f"\r\n[mock] {session}/{pane['windowName']} attached\r\n$ ",
                }
            )


async def websocket(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    attached: set[str] = set()
    output_tasks: dict[str, asyncio.Task[None]] = {}
    await ws.send_json({"type": "sessions", "sessions": SESSIONS})

    try:
        async for incoming in ws:
            if incoming.type != WSMsgType.TEXT:
                if incoming.type == WSMsgType.ERROR:
                    break
                continue
            try:
                message = incoming.json()
            except (TypeError, ValueError):
                await ws.send_json({"type": "error", "message": "invalid JSON"})
                continue
            if not isinstance(message, dict):
                await ws.send_json({"type": "error", "message": "JSON message must be an object"})
                continue

            kind = message.get("type")
            session = message.get("session")
            if kind == "attach":
                if session not in PANES:
                    await ws.send_json(
                        {"type": "error", "session": session, "message": "session does not exist"}
                    )
                    continue
                if session not in attached and len(attached) >= 12:
                    await ws.send_json(
                        {"type": "error", "session": session, "message": "attach limit reached"}
                    )
                    continue
                attached.add(session)
                await send_reset(ws, session)
                previous = output_tasks.pop(session, None)
                if previous is not None:
                    previous.cancel()
                task = asyncio.create_task(scripted_output(ws, session))
                output_tasks[session] = task
                task.add_done_callback(
                    lambda done, name=session: output_tasks.pop(name, None)
                    if output_tasks.get(name) is done
                    else None
                )
            elif kind == "detach":
                attached.discard(session)
                task = output_tasks.pop(session, None)
                if task is not None:
                    task.cancel()
            elif kind == "refresh":
                if session in attached:
                    await send_reset(ws, session)
                else:
                    await ws.send_json(
                        {"type": "error", "session": session, "message": "session is not attached"}
                    )
            elif kind == "input":
                pane_id = message.get("paneId")
                pane_session = session_name_for_pane(pane_id)
                if pane_session is None or pane_session not in attached:
                    await ws.send_json(
                        {
                            "type": "error",
                            "session": pane_session,
                            "message": "pane is not attached",
                        }
                    )
                    continue
                await ws.send_json(
                    {
                        "type": "output",
                        "session": pane_session,
                        "paneId": pane_id,
                        "data": str(message.get("data", "")),
                    }
                )
            elif kind == "resize":
                pane_session = session_name_for_pane(message.get("paneId"))
                if pane_session not in attached:
                    await ws.send_json(
                        {
                            "type": "error",
                            "session": pane_session,
                            "message": "pane is not attached",
                        }
                    )
            elif kind in {"split", "close"}:
                pane_session = session_name_for_pane(message.get("paneId"))
                await ws.send_json(
                    {
                        "type": "error",
                        "session": pane_session,
                        "message": "refusing destructive op on non-test session",
                    }
                )
            else:
                await ws.send_json(
                    {
                        "type": "error",
                        "session": session,
                        "message": f"unknown message type: {kind}",
                    }
                )
    finally:
        tasks = list(output_tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    return ws


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", cockpit)
    app.router.add_get("/cockpit.html", cockpit)
    app.router.add_get("/telemetry/agents", telemetry_agents)
    app.router.add_get("/telemetry/messages", telemetry_messages)
    app.router.add_get("/telemetry/graph", telemetry_graph)
    app.router.add_get("/telemetry/sessions", telemetry_sessions)
    app.router.add_get("/telemetry/health", telemetry_health)
    app.router.add_get("/telemetry/mail/recent", telemetry_mail_recent)
    app.router.add_get("/telemetry/mail/message", telemetry_mail_message)
    app.router.add_get("/telemetry/mail/thread", telemetry_mail_thread)
    app.router.add_get("/telemetry/portrait", telemetry_portrait)
    app.router.add_post("/telemetry/spawn", telemetry_spawn)
    app.router.add_get("/ws", websocket)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host=HOST, port=PORT)
