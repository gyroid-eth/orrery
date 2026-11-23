"""Claude Code hook: tell the host this agent started, took a prompt, or stopped.

Claude runs it for SessionStart, UserPromptSubmit and Stop (see
programs.build). It must never slow or change the agent: it prints nothing
(Stop and SessionStart output would reach the model), gives up after a
moment, and always exits 0.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request


def main() -> None:
    url, agent = os.environ.get("ORRERY_HOST_URL"), os.environ.get("ORRERY_AGENT")
    if not url or not agent:
        return
    try:
        event = json.loads(sys.stdin.read() or "{}").get("hook_event_name", "")
    except (ValueError, AttributeError, OSError):
        return
    request = urllib.request.Request(
        url.rstrip("/") + "/api/hook", method="POST",
        data=json.dumps(dict(agent=agent, event=str(event)[:64])).encode(),
        headers={"Content-Type": "application/json", "X-Orrery": "1"})
    # The host is on 127.0.0.1: never route through a system proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open(request, timeout=2).close()
    except OSError:
        pass


if __name__ == "__main__":
    try:
        main()
    finally:
        sys.exit(0)
