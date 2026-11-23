"""Use hub.db by hand: list agents, send and read mail, read and post to the board.

    python windows/hub/cli.py agents
    python windows/hub/cli.py send --as me --to alice "Subject" "Body"
    python windows/hub/cli.py inbox --as me
    python windows/hub/cli.py thread 12
    python windows/hub/cli.py board [TOPIC]
    python windows/hub/cli.py post --as me TOPIC "text"

``--as`` registers that name if it is new, so a person can take part too.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hub.db import Hub, HubError, IMPORTANCE  # noqa: E402
from hub.mcp_server import format_messages  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--db", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("agents")
    send = sub.add_parser("send")
    send.add_argument("--as", dest="me", required=True)
    send.add_argument("--to", required=True, help="comma-separated names")
    send.add_argument("--importance", choices=IMPORTANCE, default="normal")
    send.add_argument("--reply-to", type=int)
    send.add_argument("subject")
    send.add_argument("body", help="'-' reads stdin")
    inbox = sub.add_parser("inbox")
    inbox.add_argument("--as", dest="me", required=True)
    inbox.add_argument("--all", action="store_true", help="include read messages")
    inbox.add_argument("--peek", action="store_true", help="do not mark as read")
    thread = sub.add_parser("thread")
    thread.add_argument("thread_id")
    board = sub.add_parser("board")
    board.add_argument("topic", nargs="?")
    post = sub.add_parser("post")
    post.add_argument("--as", dest="me", required=True)
    post.add_argument("topic")
    post.add_argument("text", help="'-' reads stdin")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    hub = Hub(args.db)
    try:
        if getattr(args, "me", None):
            hub.register(args.me, program="human")
        if args.command == "agents":
            for a in hub.agents():
                print(f"{a['name']:<24} {a['program'] or '?':<8} unread {a['unread']:<3} "
                      f"last {a['last_seen_ts']}  {a['cwd'] or ''}")
        elif args.command == "send":
            body = sys.stdin.read() if args.body == "-" else args.body
            r = hub.send(args.me, [n.strip() for n in args.to.split(",") if n.strip()],
                         args.subject, body, importance=args.importance, reply_to=args.reply_to)
            print(f"sent {r['id']} (thread {r['thread_id']}) to {', '.join(r['to'])}")
        elif args.command == "inbox":
            messages = hub.inbox(args.me, unread_only=not args.all, mark_read=not args.peek)
            print(format_messages(messages) if messages else "(no mail)")
        elif args.command == "thread":
            print(format_messages(hub.thread(args.thread_id)) or "(no such thread)")
        elif args.command == "board":
            if args.topic:
                for p in hub.board_read(args.topic):
                    print(f"--- {p['id']} · {p['author']} · {p['ts']}\n{p['text']}\n")
            else:
                for t in hub.board_read():
                    print(f"{t['topic']:<32} {t['posts']} post(s)  last {t['last_ts']}")
        elif args.command == "post":
            text = sys.stdin.read() if args.text == "-" else args.text
            r = hub.board_write(args.me, args.topic, text)
            print(f"posted {r['id']} to {r['topic']}")
    except HubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        hub.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
