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
import re
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

import pyte

from hub.db import Hub, HubError, check_name
from host import activity, conversations, programs

REPLAY_CHARS = 400_000
ENTER_DELAY = 0.5  # Between a submitted prompt and its Enter, as two separate writes.
# Escape sequences a viewer sends without anyone typing: the browser
# terminal answers the TUI's queries (device attributes, cursor position)
# and reports focus and the mouse. Arrow keys are CSI too. None of them can
# leave a half-written prompt, so only what remains counts as typing.
ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"
                     r"|\x1b[PX^_][^\x1b]*(?:\x1b\\)?|\x1bO.|\x1b.", re.DOTALL)


def typed(data: str) -> bool:
    return bool(ESCAPES.sub("", data))


# Queries a TUI sends its terminal (cursor position, device attributes,
# colours, window size). Antigravity asks for the cursor position before
# every redraw. A late viewer replaying old output must not answer old
# queries: the stale answers would reach the live program as input and it
# would draw at the wrong place.
QUERIES = re.compile(r"\x1b\[[?>=]?\d*[nc]|\x1b\[\??u|\x1b\[1[48]t"
                     r"|\x1b\][0-9]+;\?(?:\x07|\x1b\\)", re.DOTALL)


def without_queries(data: str) -> str:
    return QUERIES.sub("", data)
HOOK_GRACE = 15.0  # Claude without any hook by then: fall back to the screen.
STUCK_BUSY = 30.0  # Claude busy by hook but quiet at its prompt this long: idle.


@dataclass
class Agent:
    name: str
    program: str
    cwd: str
    conversation: str | None = None  # Its own conversation, which RESUME reopens.


class Session:
    """One ConPTY child, its rendered screen and the viewers attached to it.

    ``activity`` is what the dispatcher needs: 'starting', 'busy' or 'idle'
    (waiting at its prompt since ``idle_since``). Claude reports it through
    hooks; Antigravity has none, so its screen decides. Either way a dialog
    or a busy marker on screen wins. A Claude screen that shows neither its
    busy marker nor its prompt box does not overrule a Stop hook.
    """

    def __init__(self, name: str, loop: asyncio.AbstractEventLoop, program: str = "claude"):
        self.name, self.loop, self.program = name, loop, program
        self.proc = None
        self.screen = pyte.Screen(120, 30)
        self.stream = pyte.Stream(self.screen)
        self.hook_state: str | None = None  # Last state a Claude hook reported.
        self.activity = "starting"
        self.idle_since: float | None = None
        self.hold_until = 0.0  # After an injected notice: busy until the CLI redraws.
        self.injecting = False
        # The viewer that last typed or resized. Only it may send the
        # terminal's automatic answers, so two open tabs never answer twice.
        self.owner = None
        self.chunks: list[str] = []
        self.chars = 0
        self.viewers: set[asyncio.Queue] = set()
        self.status = "stopped"
        self.exit_code: int | None = None
        self.started_ts: float | None = None
        self.last_output = 0.0
        self.last_input = 0.0
        self.enters: deque[float] = deque(maxlen=20)  # When Enter was typed, by anyone.
        self.rows, self.cols = 30, 120

    def start(self, launch: programs.Launch, cwd: str, rows: int, cols: int) -> None:
        from winpty import PtyProcess  # Windows only; imported when a terminal starts.

        self.rows, self.cols = rows, cols
        self.proc = PtyProcess.spawn(launch.argv, cwd=cwd, env=launch.env, dimensions=(rows, cols))
        self.status, self.exit_code, self.started_ts = "running", None, time.time()
        self.chunks, self.chars = [], 0
        self.screen = pyte.Screen(cols, rows)
        self.stream = pyte.Stream(self.screen)
        self.hook_state, self.activity, self.idle_since, self.hold_until = None, "starting", None, 0.0
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
        try:
            self.stream.feed(data)
        except Exception:  # A sequence pyte cannot parse must not stop the terminal.
            pass
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
        self.status, self.activity, self.idle_since = "exited", "stopped", None
        self.broadcast(("exit", self.exit_code))

    def broadcast(self, event) -> None:
        for queue in list(self.viewers):
            queue.put_nowait(event)

    def replay(self) -> str:
        return without_queries("".join(self.chunks))

    def write(self, data: str, *, user: bool = True) -> None:
        """``user=False`` for the host's own notices: they are not someone typing."""
        if self.status == "running" and self.proc is not None:
            if user and typed(data):
                self.last_input = time.time()
            if "\r" in data:
                self.enters.append(time.time())
            self.proc.write(data)

    def viewer_input(self, viewer, data: str) -> None:
        """Input from a browser view: typing from anyone, answers from the owner only."""
        if typed(data):
            self.owner = viewer
        elif viewer is not self.owner:
            return
        self.write(data)

    def viewer_resize(self, viewer, rows: int, cols: int) -> None:
        self.owner = viewer
        self.resize(rows, cols)

    @property
    def bracketed_paste(self) -> bool:
        """The program turned on bracketed paste (ESC[?2004h); pyte keeps private modes << 5."""
        return (2004 << 5) in self.screen.mode

    def pasted(self, text: str) -> str:
        """Text to write so it lands at the prompt as one piece, without submitting.

        Claude Code takes a fast burst of plain input for a paste and folds an
        Enter that follows soon after into it as a newline, so whenever the
        program understands bracketed paste the text is marked as one.
        Several lines are always bracketed, so their newlines do not submit early.
        """
        if self.bracketed_paste or "\n" in text:
            return "\x1b[200~" + text.replace("\n", "\r") + "\x1b[201~"
        return text

    async def submit(self, viewer, text: str) -> None:
        """A finished prompt from the composer: the text, then Enter.

        The person wrote it outside the terminal, so nothing half-written
        is left at the agent's prompt and notices may follow as usual.
        """
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
        if not text or self.status != "running":
            return
        self.owner = viewer
        self.write(self.pasted(text), user=False)
        await asyncio.sleep(ENTER_DELAY)
        self.write("\r", user=False)

    def resize(self, rows: int, cols: int) -> None:
        rows, cols = max(5, min(int(rows), 500)), max(20, min(int(cols), 1000))
        if (rows, cols) != (self.rows, self.cols) and self.status == "running":
            self.rows, self.cols = rows, cols
            self.proc.setwinsize(rows, cols)
            self.screen.resize(rows, cols)

    # Activity -----------------------------------------------------------

    def screen_rows(self) -> list[str]:
        return activity.lines(self.screen)

    def hook(self, event: str) -> None:
        """A Claude hook: SessionStart/Stop mean idle, UserPromptSubmit busy."""
        if event in ("SessionStart", "Stop"):
            self.hook_state = "idle"
        elif event == "UserPromptSubmit":
            self.hook_state = "busy"
        self.refresh()

    def refresh(self, now: float | None = None) -> str:
        if self.status != "running":
            return self.activity
        now = time.time() if now is None else now
        seen = activity.screen_state(self.program, self.screen_rows())
        quiet = now - self.last_output
        if seen == "dialog":
            state = "attention"  # A question for the person; never type into it.
        elif now < self.hold_until or seen == "busy":
            state = "busy"
        elif self.program == "claude" and self.hook_state == "busy" and quiet < STUCK_BUSY:
            # No Stop yet. An interrupted turn sends none, so a long-quiet
            # prompt counts as idle after STUCK_BUSY seconds.
            state = "busy"
        elif (self.program == "claude" and self.hook_state is None
              and now - (self.started_ts or now) < HOOK_GRACE):
            state = "starting"  # Give SessionStart its chance before trusting the screen.
        elif seen == "unclear" and self.hook_state != "idle":
            # Claude shows neither its busy marker nor its prompt: only a
            # Stop (or SessionStart) hook may call that idle.
            state = "busy"
        else:
            state = "idle"
        if state == "idle" and self.activity != "idle":
            self.idle_since = now
        elif state != "idle":
            self.idle_since = None
        self.activity = state
        return state

    def notified(self, now: float | None = None) -> None:
        """A notice was just typed: busy until the CLI has had time to take it."""
        now = time.time() if now is None else now
        self.hold_until = now + 3.0
        self.hook_state = "busy" if self.hook_state else None
        self.activity, self.idle_since = "busy", None

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
        self.queued: dict[str, int] = {}  # Pending notices per agent, set by the dispatcher.
        self.waiting: dict[str, str] = {}  # Why those notices wait.
        self.paused: set[str] = set()  # Agents whose wake budget ran out.
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
            if conversations.valid(row.get("conversation")):
                agent.conversation = row["conversation"].lower()
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
            self.sessions[key] = Session(agent.name, self.loop, agent.program)
        return self.sessions[key]

    def start(self, name: str, *, resume: bool = False, rows: int = 30, cols: int = 120) -> Session:
        agent = self.get(name)
        session = self.session(name)
        if session.status == "running":
            return session
        launch = self.builder(agent.program, agent.name, resume=resume,
                              conversation=agent.conversation, hub_db=self.hub_db,
                              host_url=self.host_url)
        self.hub.register(agent.name, program=agent.program, cwd=agent.cwd)
        session.start(launch, agent.cwd, rows, cols)
        if launch.conversation != agent.conversation:
            agent.conversation = launch.conversation
            self.save()
        return session

    def conversation_seen(self, name: str, conversation: str) -> None:
        """The agent is now in ``conversation`` (a Claude hook reported it)."""
        agent = self.agents.get(str(name).lower())
        if agent is not None and conversations.valid(conversation):
            conversation = conversation.lower()
            if agent.conversation != conversation:
                agent.conversation = conversation
                self.save()

    def track_agy(self) -> None:
        """Give each running Antigravity agent the conversation it just began.

        Blocking (file and SQLite reads): run it in an executor. A file is
        taken only if it is newer than the agent's current conversation,
        appeared within AFTER_ENTER seconds of an Enter typed into that
        agent, is in the agent's folder, and is nobody else's.
        """
        running = [(self.agents[key], s) for key, s in self.sessions.items()
                   if key in self.agents and s.program == "agy" and s.status == "running"]
        if not running:
            return
        found = conversations.new_agy_conversations(min(s.started_ts or 0 for _, s in running) - 1)
        claimed = {a.conversation for a in self.agents.values() if a.conversation}
        times = {cid: when for cid, when, _ in found}
        for agent, session in running:
            current = times.get(agent.conversation or "", 0.0)
            for cid, when, path in reversed(found):  # Newest first.
                if cid in claimed or when <= current or when < (session.started_ts or 0) - 1:
                    continue
                if not any(-2 <= when - enter <= conversations.AFTER_ENTER for enter in session.enters):
                    continue
                if conversations.agy_workspace_is(path, agent.cwd):
                    self.loop.call_soon_threadsafe(self.conversation_seen, agent.name, cid)
                    claimed.add(cid)
                    break

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
                            activity=session.activity if session else "stopped",
                            unread=unread.get(key, 0), queued=self.queued.get(key, 0),
                            waiting=self.waiting.get(key), paused=key in self.paused))
        return out
