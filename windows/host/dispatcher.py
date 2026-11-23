"""Wake idle agents that have new mail by typing a one-line notice.

This is tmux send-keys done by the terminal's owner: the host holds each
agent's ConPTY, so it types ``[ORRERY] New mail from bob: ...`` and Enter
into the agent's prompt, exactly as a person would. The agent then calls
fetch_inbox itself.

A notice is typed only when the recipient's terminal is safe to type into:
idle at its prompt for a moment, no dialog on screen, and nobody has typed
into it since it became idle (a person's half-written prompt must never
get a notice appended). Otherwise the mail waits; it is never lost, since
it stays unread in hub.db.

Agents answering each other could wake each other forever, so each agent
has a wake budget per hour. When it runs out the agent is paused (shown in
the UI) until the window frees up.
"""
from __future__ import annotations

import asyncio
import re
import sys
import time
from collections import defaultdict, deque

SETTLE = 1.5          # Seconds idle and quiet before a notice may be typed.
ENTER_DELAY = 0.4     # Text and Enter as separate writes, so it is not a paste.
BUDGET = 30           # Notices per agent per window.
WINDOW = 3600.0
CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def clean(text: str, limit: int) -> str:
    text = CONTROL.sub(" ", str(text)).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def notice(messages: list[dict]) -> str:
    """One line, no control characters: it is typed into a prompt."""
    if len(messages) == 1:
        m = messages[0]
        urgent = f" [{m['importance']}]" if m["importance"] in ("high", "urgent") else ""
        return (f"[ORRERY] New mail{urgent} from {clean(m['sender'], 64)}: "
                f"\"{clean(m['subject'], 100)}\". Call fetch_inbox to read it, then act on it.")
    senders = ", ".join(dict.fromkeys(clean(m["sender"], 64) for m in messages))
    return (f"[ORRERY] {len(messages)} new messages (from {senders}). "
            "Call fetch_inbox to read them, then act on them.")


class Dispatcher:
    def __init__(self, manager, *, interval: float = 1.0, settle: float = SETTLE,
                 budget: int = BUDGET, window: float = WINDOW, enter_delay: float = ENTER_DELAY):
        self.manager, self.interval, self.settle = manager, interval, settle
        self.budget, self.window, self.enter_delay = budget, window, enter_delay
        self.sent: dict[str, deque] = defaultdict(deque)  # agent -> notice times
        self.tasks: set[asyncio.Task] = set()

    async def run(self) -> None:
        while True:
            try:
                self.tick()
            except Exception as exc:  # Keep dispatching; one bad tick must not end it.
                print(f"dispatcher: {exc!r}", file=sys.stderr, flush=True)
            await asyncio.sleep(self.interval)

    def hold_reason(self, session, now: float) -> str | None:
        """Why a notice cannot be typed now, or None when it can."""
        if session is None or session.status != "running":
            return "not running"
        if session.injecting:
            return "typing a notice"
        if session.activity != "idle" or session.idle_since is None:
            return {"attention": "needs you", "starting": "starting"}.get(session.activity, "busy")
        if session.last_input > session.idle_since:
            return "you typed in this terminal"
        if now - session.idle_since < self.settle or now - session.last_output < self.settle:
            return "settling"
        return None

    def deliverable(self, session, now: float) -> bool:
        return self.hold_reason(session, now) is None

    def within_budget(self, key: str, now: float) -> bool:
        times = self.sent[key]
        while times and now - times[0] > self.window:
            times.popleft()
        return len(times) < self.budget

    def tick(self, now: float | None = None) -> list[str]:
        """Refresh activity, then type notices; returns the agents notified."""
        now = time.time() if now is None else now
        manager = self.manager
        for session in manager.sessions.values():
            session.refresh(now)
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in manager.hub.pending_notifications():
            groups[row["recipient"].lower()].append(row)
        manager.queued = {key: len(rows) for key, rows in groups.items()}
        manager.waiting = {}
        woken = []
        for key, rows in groups.items():
            session = manager.sessions.get(key)
            reason = self.hold_reason(session, now)
            if reason is not None:
                manager.waiting[key] = reason
                continue
            if not self.within_budget(key, now):
                manager.paused.add(key)
                manager.waiting[key] = "wake limit reached"
                continue
            manager.paused.discard(key)
            self.sent[key].append(now)
            session.injecting = True
            session.notified(now)
            task = asyncio.get_running_loop().create_task(self.type_notice(session, rows))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            woken.append(session.name)
        return woken

    async def type_notice(self, session, rows: list[dict]) -> None:
        try:
            session.write(notice(rows), user=False)
            await asyncio.sleep(self.enter_delay)
            session.write("\r", user=False)
            for row in rows:
                self.manager.hub.mark_notified(row["message_id"], row["recipient"])
        finally:
            session.injecting = False
