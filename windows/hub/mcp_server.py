"""MCP stdio server: mail and whiteboard tools backed by hub.db.

No third-party packages: MCP over stdio is newline-delimited JSON-RPC 2.0.
Each agent CLI (Claude Code, Antigravity) starts its own copy of this
process; they all share one hub.db.

Who am I: ``--agent NAME``, else ``ORRERY_AGENT``, else a name made from the
working directory and the MCP client (e.g. ``myproject-claude``). The host
always passes the name; the fallback is for sessions started by hand.

    python windows/hub/mcp_server.py [--agent NAME] [--db PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub.db import Hub, HubError, IMPORTANCE  # noqa: E402

SERVER = dict(name="orrery-hub", version="0.1.0")
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = (
    "ORRERY hub: mail between the agents on this PC, plus a shared whiteboard. "
    "Address other agents by name (list_agents shows them). When you are told "
    "you have mail, call fetch_inbox, act on it, and answer with send_message "
    "using reply_to so the thread stays together. Use the board for notes "
    "several agents should see (plans, decisions, status), not for messages "
    "to one agent.")

# Plain schemas only: Gemini-based clients reject anyOf/oneOf and some
# other JSON Schema keywords. A single recipient may also be a bare string.
TOOLS = [
    dict(name="send_message",
         description="Send mail to one or more agents by name. Returns the message id and thread id.",
         inputSchema=dict(type="object", properties=dict(
             to=dict(type="array", items=dict(type="string"), description="Recipient agent names"),
             subject=dict(type="string", description="Short subject line"),
             body=dict(type="string", description="Message body (Markdown)"),
             importance=dict(type="string", enum=list(IMPORTANCE), description="Defaults to normal"),
             reply_to=dict(type="integer", description="Message id this answers; keeps the thread"),
         ), required=["to", "subject", "body"])),
    dict(name="fetch_inbox",
         description="Read your mail. Unread messages are returned in full and marked read.",
         inputSchema=dict(type="object", properties=dict(
             include_read=dict(type="boolean", description="Also return already-read messages"),
             limit=dict(type="integer", description="Maximum messages (1-100, default 20)"),
         ))),
    dict(name="read_thread",
         description="Read every message of a thread, oldest first.",
         inputSchema=dict(type="object", properties=dict(
             thread_id=dict(type="string", description="Thread id from a message"),
         ), required=["thread_id"])),
    dict(name="list_agents",
         description="List the agents you can write to, and your own name.",
         inputSchema=dict(type="object", properties={})),
    dict(name="board_write",
         description="Append a post to a whiteboard topic that every agent can read.",
         inputSchema=dict(type="object", properties=dict(
             topic=dict(type="string", description="Topic name, e.g. 'plan' or 'api-contract'"),
             text=dict(type="string", description="Post text (Markdown)"),
         ), required=["topic", "text"])),
    dict(name="board_read",
         description="Read a whiteboard topic's latest posts, or list the topics when no topic is given.",
         inputSchema=dict(type="object", properties=dict(
             topic=dict(type="string", description="Topic name; omit to list topics"),
             limit=dict(type="integer", description="Maximum posts or topics (default 30)"),
         ))),
]


def fallback_name(client: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path.cwd().name).strip("-.") or "agent"
    if not base[0].isalpha():
        base = "a-" + base
    return f"{base[:40]}-{program_of(client)}"


def program_of(client: str) -> str:
    client = (client or "").lower()
    if "claude" in client:
        return "claude"
    if any(word in client for word in ("antigravity", "agy", "jetski", "gemini")):
        return "agy"
    return re.sub(r"[^a-z0-9]+", "-", client).strip("-")[:20] or "client"


def format_messages(messages: list[dict]) -> str:
    parts = []
    for m in messages:
        parts.append(
            f"--- message {m['id']} (thread {m['thread_id']}) [{m['importance']}]\n"
            f"from: {m['sender']}\nto: {m['recipients']}\nat: {m['ts']}\n"
            f"subject: {m['subject']}\n\n{m['body']}")
    return "\n\n".join(parts)


class Server:
    def __init__(self, hub: Hub, name: str | None):
        self.hub, self.name, self.error = hub, name, None

    def identify(self, client: str) -> None:
        if not self.name:
            self.name = fallback_name(client)
        try:
            self.hub.register(self.name, program=program_of(client), cwd=os.getcwd())
        except HubError as exc:
            self.error = str(exc)

    def call(self, tool: str, args: dict) -> str:
        if self.error:
            raise HubError(f"this session has no valid agent name: {self.error}")
        me = self.name
        self.hub.register(me)  # Refreshes last_seen; the row already exists.
        if tool == "send_message":
            reply_to = args.get("reply_to")
            result = self.hub.send(me, args.get("to"), args.get("subject"), args.get("body"),
                                   importance=args.get("importance") or "normal",
                                   reply_to=int(reply_to) if reply_to is not None else None)
            return (f"Sent message {result['id']} (thread {result['thread_id']}) "
                    f"to {', '.join(result['to'])}.")
        if tool == "fetch_inbox":
            messages = self.hub.inbox(me, unread_only=not args.get("include_read"),
                                      limit=args.get("limit") or 20)
            if not messages:
                return f"No {'messages' if args.get('include_read') else 'unread mail'} for {me}."
            return f"{len(messages)} message(s) for {me}:\n\n" + format_messages(messages)
        if tool == "read_thread":
            messages = self.hub.thread(str(args.get("thread_id", "")))
            return format_messages(messages) if messages else "No such thread."
        if tool == "list_agents":
            lines = [f"You are {me}.", "Agents:"]
            for agent in self.hub.agents():
                mark = " (you)" if agent["name"].lower() == me.lower() else ""
                lines.append(f"- {agent['name']}{mark} · {agent['program'] or '?'} · "
                             f"{agent['cwd'] or '?'} · last seen {agent['last_seen_ts']}")
            return "\n".join(lines)
        if tool == "board_write":
            result = self.hub.board_write(me, args.get("topic"), args.get("text"))
            return f"Posted {result['id']} to board topic '{result['topic']}'."
        if tool == "board_read":
            topic, limit = args.get("topic"), args.get("limit") or 30
            if not topic:
                topics = self.hub.board_read(limit=limit)
                if not topics:
                    return "The board is empty."
                return "Topics:\n" + "\n".join(
                    f"- {t['topic']} · {t['posts']} post(s) · last {t['last_ts']}" for t in topics)
            posts = self.hub.board_read(topic, limit=limit)
            if not posts:
                return f"No posts in '{topic}'."
            return "\n\n".join(f"--- {p['id']} · {p['author']} · {p['ts']}\n{p['text']}" for p in posts)
        raise HubError(f"unknown tool {tool!r}")

    def handle(self, request: dict) -> dict | None:
        method, rid = request.get("method"), request.get("id")
        params = request.get("params") or {}
        if rid is None:
            return None  # Notifications, e.g. notifications/initialized.
        if method == "initialize":
            self.identify(str((params.get("clientInfo") or {}).get("name") or ""))
            asked = params.get("protocolVersion")
            return result(rid, dict(
                protocolVersion=asked if asked in PROTOCOLS else PROTOCOLS[0],
                capabilities=dict(tools={}), serverInfo=SERVER,
                instructions=INSTRUCTIONS + f" You are '{self.name}'."))
        if method == "ping":
            return result(rid, {})
        if method == "tools/list":
            return result(rid, dict(tools=TOOLS))
        if method == "tools/call":
            args = params.get("arguments") or {}
            try:
                if not isinstance(args, dict):
                    raise HubError("arguments must be an object")
                text, failed = self.call(str(params.get("name")), args), False
            except (HubError, TypeError, ValueError) as exc:
                text, failed = f"Error: {exc}", True
            return result(rid, dict(content=[dict(type="text", text=text)], isError=failed))
        return dict(jsonrpc="2.0", id=rid, error=dict(code=-32601, message=f"method not found: {method}"))


def result(rid, value) -> dict:
    return dict(jsonrpc="2.0", id=rid, result=value)


def serve(server: Server, stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    for raw in stdin:
        if not raw.strip():
            continue
        try:
            request = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            reply = dict(jsonrpc="2.0", id=None, error=dict(code=-32700, message="parse error"))
        else:
            try:
                reply = server.handle(request) if isinstance(request, dict) else dict(
                    jsonrpc="2.0", id=None, error=dict(code=-32600, message="invalid request"))
            except Exception:  # Never let one bad call end the session.
                traceback.print_exc(file=sys.stderr)
                reply = dict(jsonrpc="2.0", id=request.get("id"),
                             error=dict(code=-32603, message="internal error"))
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="ORRERY hub MCP server (stdio)")
    parser.add_argument("--agent", default=os.environ.get("ORRERY_AGENT"))
    parser.add_argument("--db", default=None, help="hub.db path (default: ORRERY_HUB_DB or %%LOCALAPPDATA%%)")
    args = parser.parse_args(argv)
    hub = Hub(args.db)
    try:
        serve(Server(hub, args.agent))
    finally:
        hub.close()


if __name__ == "__main__":
    main()
