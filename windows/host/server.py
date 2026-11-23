"""The Windows host: agent terminals over WebSocket plus a small JSON API.

    python windows/host/server.py [--port 8791] [--open]

windows/start.cmd runs this with --open. If a host is already listening on
the port, a second start only opens the page.

Listens on 127.0.0.1 only. A web page from another site must not be able to
type into an agent's terminal, so every request must carry this host as its
Host header (no DNS rebinding), any Origin must be this host's own page,
and state-changing requests must carry the custom ``X-Orrery`` header,
which a cross-site form or simple request cannot send.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from aiohttp import WSMsgType, web

WINDOWS = Path(__file__).resolve().parent.parent
REPO = WINDOWS.parent
sys.path.insert(0, str(WINDOWS))
from hub.db import HubError  # noqa: E402
from host import folders, portraits, programs  # noqa: E402
from host.dispatcher import Dispatcher  # noqa: E402
from host.sessions import Manager  # noqa: E402

WEB = WINDOWS / "web"
VENDOR = REPO / "bridge" / "vendor"
ICONS = REPO / "bridge" / "assets"
PORTRAITS = portraits.PORTRAITS  # Public-domain portraits, see CREDITS.md.
# Files of the original cockpit (bridge/) that this page loads unchanged.
# Only these: bridge/ also holds the macOS backend's Python sources.
BRIDGE = REPO / "bridge"
BRIDGE_FILES = frozenset({"orrery_view.js", "orrery_view.css"})
MANAGER = web.AppKey("manager", Manager)
SETTINGS = web.AppKey("settings", dict)


def allowed(app) -> tuple[set[str], set[str]]:
    port = app[SETTINGS]["port"]
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    return hosts, {f"http://{h}" for h in hosts}


@web.middleware
async def guard(request: web.Request, handler):
    hosts, origins = allowed(request.app)
    if request.host not in hosts:
        return web.json_response(dict(error="host_not_allowed"), status=403)
    origin = request.headers.get("Origin")
    if origin is not None and origin not in origins:
        return web.json_response(dict(error="origin_not_allowed"), status=403)
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-Orrery") != "1":
        return web.json_response(dict(error="missing_x_orrery_header"), status=403)
    response = await handler(request)
    if isinstance(response, web.StreamResponse) and not isinstance(response, web.WebSocketResponse):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def error(message: str, status: int = 400) -> web.Response:
    return web.json_response(dict(error=message), status=status)


async def body(request: web.Request) -> dict:
    try:
        value = await request.json()
    except (ValueError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


async def index(request):
    return web.FileResponse(WEB / "index.html")


async def state(request):
    app = request.app
    agents = [dict(a, portrait=portraits.portrait_stem(a["name"])) for a in app[MANAGER].snapshot()]
    return web.json_response(dict(
        agents=agents,
        agy_hub=app[SETTINGS].get("agy_hub"),
        programs={p: programs.find_executable(p) is not None for p in programs.PROGRAMS},
        # xterm.js leaves reflow to ConPTY when it knows the Windows build.
        windows_build=sys.getwindowsversion().build if sys.platform == "win32" else None,
        hub_db=str(app[MANAGER].hub.path)))


def unused_name(manager) -> str:
    """A scientist's name for an agent created without one.

    Names the hub already knows are skipped too: a removed agent's mail
    stays in hub.db, and a newcomer must not inherit it.
    """
    taken = set(manager.agents) | {a["name"] for a in manager.hub.agents()}
    return portraits.random_name(taken)


async def create_agent(request):
    data = await body(request)
    manager = request.app[MANAGER]
    name = str(data.get("name") or "").strip() or unused_name(manager)
    try:
        agent = manager.create(name, str(data.get("program", "")), str(data.get("cwd", "")))
        if data.get("start", True):
            manager.start(agent.name, resume=bool(data.get("resume")),
                          rows=int(data.get("rows") or 30), cols=int(data.get("cols") or 120))
    except (HubError, FileNotFoundError, ValueError) as exc:
        return error(str(exc))
    except OSError as exc:
        return error(f"could not start: {exc}", 500)
    return web.json_response(dict(ok=True, name=agent.name))


async def pick_folder(request):
    """Open Windows' folder dialog on this desktop; answer with the chosen path or null."""
    settings = request.app[SETTINGS]
    if settings["picking"]:
        return error("a folder dialog is already open", 409)
    data = await body(request)
    initial = str(data.get("initial") or "")
    settings["picking"] = True
    try:
        path = await asyncio.get_running_loop().run_in_executor(None, settings["picker"], initial)
    except Exception as exc:  # Tk missing or the dialog failing must not take the host down.
        return error(f"could not open the folder dialog: {exc}", 500)
    finally:
        settings["picking"] = False
    return web.json_response(dict(ok=True, path=path))


async def start_agent(request):
    data = await body(request)
    try:
        request.app[MANAGER].start(request.match_info["name"], resume=bool(data.get("resume")),
                                   rows=int(data.get("rows") or 30), cols=int(data.get("cols") or 120))
    except KeyError:
        return error("no such agent", 404)
    except (FileNotFoundError, ValueError) as exc:
        return error(str(exc))
    except OSError as exc:
        return error(f"could not start: {exc}", 500)
    return web.json_response(dict(ok=True))


async def stop_agent(request):
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, request.app[MANAGER].stop, request.match_info["name"])
    except KeyError:
        return error("no such agent", 404)
    return web.json_response(dict(ok=True))


async def remove_agent(request):
    manager = request.app[MANAGER]
    try:
        # Terminating blocks briefly; the roster itself changes on the loop.
        await asyncio.get_running_loop().run_in_executor(None, manager.stop, request.match_info["name"])
        manager.remove(request.match_info["name"])
    except KeyError:
        return error("no such agent", 404)
    return web.json_response(dict(ok=True))


async def screen(request):
    """The host's rendering of an agent's screen as plain text rows."""
    try:
        session = request.app[MANAGER].session(request.match_info["name"])
    except KeyError:
        return error("no such agent", 404)
    return web.json_response(dict(rows=session.screen_rows(), size=[session.rows, session.cols],
                                  activity=session.activity, hook=session.hook_state))


async def hook(request):
    """Claude hooks (host/hook.py): SessionStart, UserPromptSubmit, Stop."""
    data = await body(request)
    manager = request.app[MANAGER]
    session = manager.sessions.get(str(data.get("agent", "")).lower())
    if session is None:
        return error("no such session", 404)
    session.hook(str(data.get("event", "")))
    manager.conversation_seen(session.name, str(data.get("session_id") or ""))
    return web.json_response(dict(ok=True, activity=session.activity))


async def mail_recent(request):
    try:
        limit = int(request.query.get("limit", "50"))
    except ValueError:
        return error("limit must be an integer")
    return web.json_response(dict(messages=request.app[MANAGER].hub.recent(limit=limit)))


# The original cockpit's view modules (bridge/orrery_view.js) ask the macOS
# backend for these /telemetry/ paths. The host answers the few they read,
# in the shapes they expect.

async def telemetry_mail_recent(request):
    """Recent mail as orrery_view.js reads it: recipients as a list, ``now`` in ms."""
    try:
        limit = int(request.query.get("limit", "40"))
    except ValueError:
        return error("limit must be an integer")
    messages = [dict(m, recipients=[r for r in (m["recipients"] or "").split(", ") if r])
                for m in request.app[MANAGER].hub.recent(limit=limit)]
    return web.json_response(dict(ok=True, now=int(time.time() * 1000), messages=messages))


async def telemetry_portrait(request):
    name = request.query.get("name", "")
    try:
        agent = request.app[MANAGER].get(name)
    except KeyError:
        return error("no such agent", 404)
    stem = portraits.portrait_stem(agent.name)
    if stem is None:
        return error("no portraits", 404)
    return web.FileResponse(PORTRAITS / f"{stem}.png")


async def bridge_file(request):
    name = request.match_info["name"]
    if name not in BRIDGE_FILES:
        return error("not found", 404)
    return web.FileResponse(BRIDGE / name)


async def register_agy(request):
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, programs.register_agy_hub)
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        return error(str(exc), 500)
    request.app[SETTINGS]["agy_hub"] = await loop.run_in_executor(None, programs.agy_hub_registered)
    return web.json_response(dict(ok=True, agy_hub=request.app[SETTINGS]["agy_hub"]))


async def terminal(request):
    """Replay, then live output; input and resize come back as JSON messages."""
    try:
        session = request.app[MANAGER].session(request.match_info["name"])
    except KeyError:
        return error("no such agent", 404)
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=1 << 20)
    await ws.prepare(request)
    queue: asyncio.Queue = asyncio.Queue()
    session.viewers.add(queue)

    async def pump():
        replay = session.replay()
        await ws.send_json(dict(type="hello", status=session.status, exit_code=session.exit_code,
                                rows=session.rows, cols=session.cols, replay=bool(replay)))
        if replay:
            await ws.send_json(dict(type="output", data=replay))
        while True:
            events = [await queue.get()]
            while not queue.empty():
                events.append(queue.get_nowait())
            pending: list[str] = []  # Consecutive output becomes one frame.
            for kind, value in events + [("flush", None)]:
                if kind == "output":
                    pending.append(value)
                    continue
                if pending:
                    await ws.send_json(dict(type="output", data="".join(pending)))
                    pending = []
                if kind == "reset":
                    await ws.send_json(dict(type="reset"))
                elif kind == "exit":
                    await ws.send_json(dict(type="exit", exit_code=value))

    sender = asyncio.create_task(pump())
    submits: set[asyncio.Task] = set()
    try:
        async for message in ws:
            if message.type != WSMsgType.TEXT:
                continue
            try:
                data = json.loads(message.data)
            except ValueError:
                continue
            if data.get("type") == "input" and isinstance(data.get("data"), str):
                session.viewer_input(queue, data["data"])
            elif data.get("type") == "interrupt":
                session.owner = queue
                session.write("\x1b", user=False)  # Esc: both CLIs stop the current turn.
            elif data.get("type") == "submit" and isinstance(data.get("text"), str):
                submits.add(asyncio.create_task(session.submit(queue, data["text"][:65536])))
                for done in [task for task in submits if task.done()]:
                    submits.discard(done)
            elif data.get("type") == "resize":
                try:
                    session.viewer_resize(queue, int(data.get("rows")), int(data.get("cols")))
                except (TypeError, ValueError):
                    pass
    finally:
        session.viewers.discard(queue)
        if session.owner is queue:
            session.owner = None
        sender.cancel()
    return ws


async def on_startup(app):
    loop = asyncio.get_running_loop()
    settings = app[SETTINGS]
    app[MANAGER] = Manager(loop, hub_db=settings.get("hub_db"),
                           host_url=f"http://127.0.0.1:{settings['port']}",
                           builder=settings.get("builder"))
    dispatcher = Dispatcher(app[MANAGER], **settings.get("dispatcher", {}))
    settings["dispatcher_task"] = loop.create_task(dispatcher.run())
    settings["tracker_task"] = loop.create_task(track_conversations(app[MANAGER]))
    if settings.get("check_agy", True):
        settings["agy_hub"] = await loop.run_in_executor(None, programs.agy_hub_registered)


async def track_conversations(manager, interval: float = 3.0):
    """Keep each Antigravity agent's conversation id current (Manager.track_agy)."""
    loop = asyncio.get_running_loop()
    while True:
        try:
            await loop.run_in_executor(None, manager.track_agy)
        except Exception as exc:  # A bad scan must not stop the next one.
            print(f"conversation tracker: {exc!r}", file=sys.stderr, flush=True)
        await asyncio.sleep(interval)


async def on_shutdown(app):
    for name in ("dispatcher_task", "tracker_task"):
        task = app[SETTINGS].get(name)
        if task is not None:
            task.cancel()
    await asyncio.get_running_loop().run_in_executor(None, app[MANAGER].stop_all)


async def on_cleanup(app):
    app[MANAGER].hub.close()


async def favicon(request):
    return web.FileResponse(REPO / "bridge" / "orbit.svg")


def make_app(port: int, hub_db: str | None = None, *, builder=None,
             check_agy: bool = True, dispatcher: dict | None = None,
             picker=None) -> web.Application:
    """``picker`` stands in for the folder dialog in tests: (initial) -> path or None."""
    app = web.Application(middlewares=[guard], client_max_size=1 << 20)
    app[SETTINGS] = dict(port=port, hub_db=hub_db, builder=builder, check_agy=check_agy,
                         dispatcher=dispatcher or {}, picker=picker or folders.pick_folder,
                         picking=False)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/", index)
    app.router.add_get("/favicon.svg", favicon)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/agents", create_agent)
    app.router.add_post("/api/pick-folder", pick_folder)
    app.router.add_post("/api/agents/{name}/start", start_agent)
    app.router.add_post("/api/agents/{name}/stop", stop_agent)
    app.router.add_delete("/api/agents/{name}", remove_agent)
    app.router.add_get("/api/agents/{name}/screen", screen)
    app.router.add_post("/api/hook", hook)
    app.router.add_get("/api/mail/recent", mail_recent)
    app.router.add_post("/api/agy/register-hub", register_agy)
    app.router.add_get("/ws/{name}", terminal)
    app.router.add_get("/telemetry/mail/recent", telemetry_mail_recent)
    app.router.add_get("/telemetry/portrait", telemetry_portrait)
    app.router.add_get("/bridge/{name}", bridge_file)
    app.router.add_static("/cockpit-assets/", ICONS)  # Provider logos, by orrery_view.js's own path.
    app.router.add_static("/web/", WEB)
    app.router.add_static("/vendor/", VENDOR)
    app.router.add_static("/icons/", ICONS)
    app.router.add_static("/portraits/", PORTRAITS)
    return app


def probe(port: int) -> str:
    """What answers on the port: "free", "orrery" (a host already running) or "other"."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
    except OSError:
        return "free"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/state", timeout=3) as response:
            data = json.load(response)
        return "orrery" if isinstance(data, dict) and "agents" in data and "hub_db" in data else "other"
    except Exception:
        return "other"


def open_when_listening(url: str, port: int, timeout: float = 30) -> None:
    def wait_and_open():
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if probe(port) == "orrery":
                webbrowser.open(url)
                return
            time.sleep(0.3)
    threading.Thread(target=wait_and_open, daemon=True).start()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ORRERY for Windows host")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ORRERY_WIN_PORT", "8791")))
    parser.add_argument("--hub-db", default=os.environ.get("ORRERY_HUB_DB"))
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = parser.parse_args(argv)
    url = f"http://127.0.0.1:{args.port}/"
    found = probe(args.port)
    if found == "orrery":
        # One host per PC owns the terminals; a second one would only fail to bind.
        print(f"ORRERY for Windows is already running: {url}", flush=True)
        if args.open:
            webbrowser.open(url)
        return 0
    if found == "other":
        print(f"Port {args.port} is used by another program. Use --port or ORRERY_WIN_PORT.",
              file=sys.stderr, flush=True)
        return 1
    print(f"ORRERY for Windows: {url}", flush=True)
    print("Closing this window stops the host and every agent it started.", flush=True)
    if args.open:
        open_when_listening(url, args.port)
    web.run_app(make_app(args.port, args.hub_db), host="127.0.0.1", port=args.port, print=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
