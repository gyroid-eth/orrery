"""Agent terminals owned by the host: one ConPTY per running agent.

The host, not a browser tab, owns each terminal, so closing or reloading
the page leaves the agents running. A late viewer gets the recent output
replayed, then live output. The roster (name, program, folder) is kept in
agents.json; terminals themselves end with the host.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from hub.db import Hub, HubError, check_name
from host import programs

REPLAY_CHARS = 400_000


@dataclass
class Agent:
    name: str
    program: str
    cwd: str


class Session:
    """One ConPTY child and the viewers attached to it."""

    def __init__(self, name: str, loop: asyncio.AbstractEventLoop):
        self.name, self.loop = name, loop
        self.proc = None
        self.chunks: list[str] = []
        self.chars = 0
        self.viewers: set[asyncio.Queue] = set()
        self.status = "stopped"
        self.exit_code: int | None = None
        self.started_ts: float | None = None
        self.last_output = 0.0
        self.last_input = 0.0
        self.rows, self.cols = 30, 120

    def start(self, launch: programs.Launch, cwd: str, rows: int, cols: int) -> None:
        from winpty import PtyProcess  # Windows only; imported when a terminal starts.

        self.rows, self.cols = rows, cols
        self.proc = PtyProcess.spawn(launch.argv, cwd=cwd, env=launch.env, dimensions=(rows, cols))
        self.status, self.exit_code, self.started_ts = "running", None, time.time()
        self.chunks, self.chars = [], 0
        self.broadcast(("reset", None))
        threading.Thread(target=self._read, args=(self.proc,), daemon=True,
                         name=f"pty-{self.name}").start()

    def _read(self, proc) -> None:
        while True:
            try:
                data = proc.read(65536)
            except (EOFError, OSError):
                break
            if data:
                self.loop.call_soon_threadsafe(self._output, proc, data)
        self.loop.call_soon_threadsafe(self._exited, proc)

    def _output(self, proc, data: str) -> None:
        if proc is not self.proc:
            return
        self.last_output = time.time()
        self.chunks.append(data)
        self.chars += len(data)
        while self.chars > REPLAY_CHARS and len(self.chunks) > 1:
            self.chars -= len(self.chunks.pop(0))
        self.broadcast(("output", data))

    def _exited(self, proc) -> None:
        if proc is not self.proc:
            return
        try:
            proc.isalive()
            self.exit_code = proc.exitstatus
        except Exception:
            self.exit_code = None
        self.status = "exited"
        self.broadcast(("exit", self.exit_code))

    def broadcast(self, event) -> None:
        for queue in list(self.viewers):
            queue.put_nowait(event)

    def replay(self) -> str:
        return "".join(self.chunks)

    def write(self, data: str) -> None:
        if self.status == "running" and self.proc is not None:
            self.last_input = time.time()
            self.proc.write(data)

    def resize(self, rows: int, cols: int) -> None:
        rows, cols = max(5, min(int(rows), 500)), max(20, min(int(cols), 1000))
        if (rows, cols) != (self.rows, self.cols) and self.status == "running":
            self.rows, self.cols = rows, cols
            self.proc.setwinsize(rows, cols)

    def stop(self) -> None:
        proc = self.proc
        if proc is not None and self.status == "running":
            try:
                proc.terminate(force=True)
            except Exception:
                pass


class Manager:
    def __init__(self, loop: asyncio.AbstractEventLoop, *, hub_db: str | None = None,
                 host_url: str | None = None, builder=None):
        self.loop, self.hub_db, self.host_url = loop, hub_db, host_url
        self.builder = builder or programs.build  # Tests launch a stand-in program.
        self.hub = Hub(hub_db)
        self.path = programs.state_dir() / "agents.json"
        self.agents: dict[str, Agent] = {}
        self.sessions: dict[str, Session] = {}
        self.load()

    # Roster -------------------------------------------------------------

    def load(self) -> None:
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rows = []
        for row in rows if isinstance(rows, list) else []:
            try:
                agent = Agent(check_name(row["name"]), row["program"], row["cwd"])
            except (KeyError, TypeError, HubError):
                continue
            if agent.program in programs.PROGRAMS:
                self.agents[agent.name.lower()] = agent

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(a) for a in self.agents.values()], indent=2,
                                  ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, name: str) -> Agent:
        agent = self.agents.get(str(name).lower())
        if agent is None:
            raise KeyError(name)
        return agent

    def create(self, name: str, program: str, cwd: str) -> Agent:
        check_name(name)
        if program not in programs.PROGRAMS:
            raise HubError(f"program must be one of {', '.join(programs.PROGRAMS)}")
        if not isinstance(cwd, str) or not os.path.isabs(cwd) or not os.path.isdir(cwd):
            raise HubError("folder must be an existing absolute path")
        if name.lower() in self.agents:
            raise HubError(f"an agent named {name} already exists")
        agent = Agent(name, program, os.path.normpath(cwd))
        self.hub.register(name, program=program, cwd=agent.cwd)
        self.agents[name.lower()] = agent
        self.save()
        return agent

    def remove(self, name: str) -> None:
        agent = self.get(name)
        self.stop(agent.name)
        self.sessions.pop(agent.name.lower(), None)
        del self.agents[agent.name.lower()]
        self.save()

    # Terminals ----------------------------------------------------------

    def session(self, name: str) -> Session:
        agent = self.get(name)
        key = agent.name.lower()
        if key not in self.sessions:
            self.sessions[key] = Session(agent.name, self.loop)
        return self.sessions[key]

    def start(self, name: str, *, resume: bool = False, rows: int = 30, cols: int = 120) -> Session:
        agent = self.get(name)
        session = self.session(name)
        if session.status == "running":
            return session
        launch = self.builder(agent.program, agent.name, resume=resume, hub_db=self.hub_db,
                              host_url=self.host_url)
        self.hub.register(agent.name, program=agent.program, cwd=agent.cwd)
        session.start(launch, agent.cwd, rows, cols)
        return session

    def stop(self, name: str) -> None:
        session = self.sessions.get(self.get(name).name.lower())
        if session is not None:
            session.stop()

    def stop_all(self) -> None:
        for session in self.sessions.values():
            session.stop()

    def snapshot(self) -> list[dict]:
        unread = {a["name"].lower(): a["unread"] for a in self.hub.agents()}
        out = []
        for key, agent in sorted(self.agents.items()):
            session = self.sessions.get(key)
            out.append(dict(asdict(agent),
                            status=session.status if session else "stopped",
                            exit_code=session.exit_code if session else None,
                            started_ts=session.started_ts if session else None,
                            last_output=session.last_output if session else None,
                            unread=unread.get(key, 0)))
        return out
