import argparse
import asyncio
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

from aiohttp import web

parser = argparse.ArgumentParser()
parser.add_argument("snapshot", type=Path)
parser.add_argument("--guide-board", type=Path)
parser.add_argument("--team-hero", choices=("ja", "en"))
parser.add_argument("--reader-demo", choices=("ja", "en"))
parser.add_argument("--readme-phone", action="store_true")
args = parser.parse_args()
base = args.snapshot
bridge = base / "app/bridge"
dash = base / "tel/dashboard"
sys.path.insert(0, str(base / "tel"))
from dashboard.mobile_relay import static_assets

mobile_assets = static_assets(dash)
network_css = re.search(
    r'<style id="agentstack-dashboard-styles">(.*?)</style>',
    (dash / "index.html").read_text(),
    re.S,
)[1]
identity = dict(
    home="/DemoVault" if args.guide_board else "/Users/demo",
    users=["demo"],
    hosts=["demo-studio"],
    words=["demo-studio"],
    mask_locations=True,
)
names = [
    "AmberCurie",
    "PatientFaraday",
    "NimbleTuring",
    "CalmGauss",
    "SageNoether",
    "BrightHopper",
    "SwiftBell",
]
modelids = [
    "claude-opus-5-5",
    "gpt-6.2-sol",
    "gemini-3.8-flash-high",
    "deepseek-v4-pro",
    "qwen3.6",
    "gpt-6.2-sol",
    "claude-sonnet-5",
]
programs = [
    "claude-code",
    "codex-cli",
    "antigravity",
    "hermes",
    "dsh",
    "codex-cli",
    "claude-code",
]
providers = ["anthropic", "openai", "google", "deepseek", "qwen", "openai", "anthropic"]
now = time.time()
agents = [
    dict(
        name=n,
        program=programs[i],
        provider=providers[i],
        model=modelids[i],
        model_id=modelids[i],
        running=True,
        category="agent",
        state="run",
        act_state=["work", "question", "ask", "wait"][i % 4],
        task=[
            "Coordinate the release review",
            "Check keyboard shortcuts",
            "Review the screenshots",
            "Verify the changelog",
            "Compare the build reports",
            "Check the navigation",
            "Review the examples",
        ][i],
        cwd=identity["home"] if args.guide_board else "/demo-workspace/release-review",
        created=int(now) - 600,
        ctx_used=44 + i * 6,
        ctx_window_tokens=200000,
        harness_kind={"claude-code": "claude", "codex-cli": "codex"}.get(
            programs[i], programs[i]
        ),
        history_binding="bound",
        history_session_id="fixture-" + str(i),
        computer_use="view" if i == 1 else "off",
        browser_use=i == 0,
        computer_use_source="launch",
        browser_use_source="launch",
        permission_resume_supported=True,
        permission_source="process" if i == 2 else "launch",
        parent_state="top" if i in (0, 2) else "child",
        parent_agent=names[0] if i not in (0, 2) else None,
        deliv=i % 4,
        annot=dict(
            role=[
                "Orchestrator",
                "Keyboard review",
                "Visual review",
                "Release notes",
                "Build reports",
                "Navigation",
                "Examples",
            ][i]
        ),
    )
    for i, n in enumerate(names)
]
for row in agents:
    row["act_state"] = "work" if row["name"] == names[0] else "wait"
agents[1]["act_state"] = "question"
agents[2]["act_state"] = "work"
agents[5]["act_state"] = "ask"


def guide_permissions(agent, action):
    mode = agent.get("browser_mode", "personal") if agent["browser_use"] else "off"
    agent["permission_controls"] = {
        "computer_use": dict(value=agent["computer_use"], source="launch", can_change=True, action=action),
        "browser_use": dict(value=agent["browser_use"], mode=mode, options=["off", "temporary", "personal"],
                            source="launch", can_change=True, action=action),
    }


if args.guide_board:
    for agent in agents:
        guide_permissions(agent, "restart")
spawn = [
    dict(source=names[0], target=a["name"], ts=int(now) - 500)
    for a in agents
    if a["parent_agent"]
]
edges = [
    dict(source=names[i], target=names[0], count=i % 3 + 1, last=int(now) - 25)
    for i in [1, 3, 4, 5, 6]
]
messages = [
    dict(
        id=101 + i,
        from_agent=n,
        to_agent=names[0],
        sender=n,
        recipient=names[0],
        source=n,
        target=names[0],
        subject=s,
        body=t,
        body_md=t,
        ts=int(now) - 15 - i * 23,
        sent_at=int(now) - 15 - i * 23,
        importance="normal",
        ack_required=False,
    )
    for i, (n, s, t) in enumerate(
        zip(
            names[1:],
            [
                "Keyboard review",
                "Screenshot notes",
                "Release draft",
                "Build comparison",
                "Navigation checks",
                "Examples reviewed",
            ],
            [
                "The shortcuts are consistent in both layouts.",
                "The latest captures are ready for review.",
                "The draft is ready for a final pass.",
                "The build output matches the baseline.",
                "The navigation labels match the controls.",
                "The examples are ready.",
            ],
        )
    )
]
fake_stamp = "2026-01-01T09:40:00Z"
preview_text = """# Release checklist

- Verify keyboard controls.
- Check the light and dark layouts.
- Confirm captions match the visible controls.
"""
table = """### Review results

| Area | Status | Next step |
| --- | --- | --- |
| Keyboard | Verified | Check the mobile layout |
| Appearance | Ready | Capture both themes |
| Documentation | In progress | Review captions |
"""
events = [
    dict(
        id="intro",
        kind="text",
        role="user",
        text="Please prepare the release review.",
        ts=fake_stamp,
    ),
    dict(
        id="plan",
        kind="text",
        role="assistant",
        text="I will verify the keyboard shortcuts and compare both themes before preparing the final screenshots.",
        ts=fake_stamp,
    ),
    dict(
        id="result",
        kind="text",
        role="assistant",
        text=table,
        ts=fake_stamp,
        references=[
            dict(id="a" * 32, label="release-checklist.md", kind="file"),
            dict(id="b" * 32, label="review-chart.png", kind="file"),
        ],
    ),
    dict(
        id="mail",
        kind="tool",
        role="assistant",
        text="ORRERY Mail",
        ts=fake_stamp,
        mail=[
            dict(
                direction="received",
                sender=names[1],
                recipients=[names[0]],
                subject="Keyboard review",
                body=messages[0]["body"],
                coverage="request",
            )
        ],
    ),
    dict(
        id="ready",
        kind="text",
        role="assistant",
        text="The review is ready. Would you like me to check the mobile layout next?",
        ts=fake_stamp,
    ),
]
if args.guide_board:
    preview_text = args.guide_board.read_text(encoding="utf-8")
    preview_text = re.sub(r"\A---\n.*?\n---\n", "", preview_text, count=1, flags=re.S)
    preview_text = "# Task board\n\n" + preview_text.split("%%", 1)[0].strip()
    events = [
        dict(id="request", kind="text", role="user", text="What should we work on next?", ts=fake_stamp),
        dict(
            id="result", kind="text", role="assistant", ts=fake_stamp,
            text="I checked the task board. Start by organizing the experiment notes.",
            references=[dict(id="a" * 32, label=args.guide_board.name, kind="file")],
        ),
    ]
if args.reader_demo:
    japanese = args.reader_demo == "ja"
    board_sections = re.split(r"^## ", preview_text, flags=re.M)[1:]
    counts = [sum(line.startswith(("- [ ]", "- [x]")) for line in section.splitlines())
              for section in board_sections[1:4]]
    request, plan, result, report, board, labels, next_action = (
        ("タスク板を見て、今日やることを整理して。",
         "タスクを状態ごとに数え、取りかかる順番をまとめます。",
         "まず今日の Daily Note を作り、そのあと ORRERY の導入を確認します。",
         "タスク確認.md", args.guide_board.name, ("状態", "件数", "未着手", "作業中", "完了"),
         ("Daily Note を作る", "Telemetry と cockpit を入れる", "しりとりで通信を確認する"))
        if japanese else
        ("Check the task board and plan today's work.",
         "I'll count the tasks by status and put the next steps in order.",
         "Start with today's Daily Note, then check the ORRERY installation.",
         "task-review.md", "tasks.md", ("Status", "Count", "To do", "In progress", "Done"),
         ("Create today's Daily Note", "Install Telemetry and the cockpit", "Test agent messaging"))
    )
    table = [f"| {labels[0]} | {labels[1]} |", "| --- | ---: |"] + [
        f"| {label} | {count} |" for label, count in zip(labels[2:], counts, strict=True)
    ]
    preview_text = "# " + report.removesuffix(".md") + "\n\n" + "\n".join(
        [result, "", *table, "", "## " + ("今日の順番" if japanese else "Today's plan"), ""]
        + [f"{number}. {item}" for number, item in enumerate(next_action, 1)]
    )
    events = [
        dict(id="reader-request", kind="text", role="user", ts=fake_stamp, text=request),
        dict(id="reader-plan", kind="text", role="assistant", ts=fake_stamp, text=plan),
    ]
    for i, (tool, detail) in enumerate((("Read", board), ("Bash", "rg -n '^##' " + board), ("Write", report)), 1):
        step_id = f"{i:032x}"
        events.extend([
            dict(id=f"reader-call-{i}", kind="tool", role="assistant", text=tool, ts=fake_stamp,
                 step=dict(id=step_id, phase="call", tool=tool, title=detail, started=i * 1000)),
            dict(id=f"reader-result-{i}", kind="tool_result", role="assistant", text=detail, ts=fake_stamp,
                 step=dict(id=step_id, phase="result", status="success", ended=(i + 1) * 1000)),
        ])
    events.append(dict(
        id="reader-summary", kind="text", role="assistant", ts=fake_stamp, step_boundary=True,
        text=result + "\n\n" + "\n".join(table),
        references=[dict(id="a" * 32, label=report, kind="file")],
    ))
    section_lines = [[line for line in section.splitlines() if line] for section in board_sections]
    if not japanese:
        section_lines = [
            ["Ideas", "- [ ] Try digest-paper on another paper", "- [ ] Save frequent requests as skills"],
            ["To do", *[f"- [ ] {item}" for item in next_action], "- [ ] Convert a paper to Markdown",
             "- [ ] Generate reading notes", "- [ ] Record work in the Daily Note"],
            ["In progress"], ["Done", "- [x] Set up the demo vault"],
        ]
    reader_terminal = [f"\x1b[1m● Read({board})\x1b[0m"] + [
        f"\x1b[90m{line:2} │\x1b[0m {value}"
        for line, value in enumerate(["## " + part[0] if index == 0 else part[index]
                                     for part in section_lines for index in range(len(part))], 1)
    ] + [
        f"\x1b[1m● Bash(rg -n '^##' {board})\x1b[0m",
        *[f"  {label}: {count}" for label, count in zip(labels[2:], counts, strict=True)],
        f"\x1b[1m● Write({report})\x1b[0m",
        *[f"\x1b[32m+ {line}\x1b[0m" for line in preview_text.splitlines() if line],
        f"\x1b[37m● {result}\x1b[0m",
    ]
    agents[0]["act_state"] = "wait"
if args.team_hero:
    # The cockpit consumes the same roster, Mail and Reader responses as it
    # normally does. The exercise itself is deterministic and starts no CLI.
    hero = {"accepted": False, "size": 1}
    agents[0]["act_state"] = "wait"
    for agent, role in zip(agents[1:5], ("件数確認", "作業順", "導入手順", "通信の確認"), strict=True):
        agent.update(parent_agent=names[0], parent_state="child", act_state="work",
                     annot={"role": role})
    spawn = [dict(source=names[0], target=agent["name"], ts=int(now)) for agent in agents[1:5]]
    messages = []
    pending = re.search(r"^## 未着手\s*\n(.*?)(?=^## |\Z)", preview_text, re.M | re.S)
    pending_count = len(re.findall(r"^- \[ \]", pending.group(1), re.M))
    hero_reports = [
        (f"未着手は {pending_count} 件", f"タスク板の未着手は {pending_count} 件です。"),
        ("Daily Note から", "まず今日の Daily Note を作ります。"),
        ("ORRERY の導入", "Telemetry と cockpit を入れる手順を確認しました。"),
        ("通信をしりとりで確認", "しりとりで agent 間のやり取りを確認できます。"),
    ]
    events = [
        dict(id="hero-request", kind="text", role="user", ts=fake_stamp, text="今日のタスクを整理して"),
        dict(id="hero-summary", kind="text", role="assistant", ts=fake_stamp, text=(
            "4 体の報告をまとめました。\n\n"
            "| 担当 | 結果 |\n| --- | --- |\n"
            f"| Codex | 未着手は {pending_count} 件 |\n"
            "| Gemini | 今日の Daily Note を作る |\n"
            "| DeepSeek | Telemetry と cockpit を入れる |\n"
            "| Local LLM の Qwen | しりとりで通信を確認 |"
        )),
    ]
    if args.team_hero == "en":
        for agent, role in zip(agents[1:5], ("Task count", "Work order", "Installation", "Messaging"), strict=True):
            agent["annot"]["role"] = role
        hero_reports = [
            (f"{pending_count} open tasks", f"The board has {pending_count} open tasks."),
            ("Start with the Daily Note", "Create today's Daily Note first."),
            ("ORRERY setup", "I checked the steps for installing Telemetry and the cockpit."),
            ("Test agent messaging", "Use a word game to test agent-to-agent messages."),
        ]
        events[0]["text"] = "Plan today's tasks"
        events[1]["text"] = (
            "Here are the four reports.\n\n"
            "| Agent | Result |\n| --- | --- |\n"
            f"| Codex | {pending_count} open tasks |\n"
            "| Gemini | Create today's Daily Note |\n"
            "| DeepSeek | Install Telemetry and the cockpit |\n"
            "| Qwen (local LLM) | Test agent messaging |"
        )

harness = lambda a, default: dict(
    id=a,
    label={"dsh": "dsh", "hermes": "Hermes", "antigravity": "Antigravity"}[a],
    available=True,
    default=default,
)
pick = lambda id, label, program, models, **extra: dict(
    id=id,
    label=label,
    program=program,
    models=[dict(id=m, label=m, default=i == 0) for i, m in enumerate(models)],
    available=True,
    **extra,
)
catalog = dict(
    runtime_mode="legacy",
    supports_browser_off=True,
    computer_modes=["off", "view", "control"],
    browser_modes={
        key: ["off", "temporary", "personal"]
        for key in ("claude-code", "codex", "hermes", "dsh", "antigravity")
    },
    providers=[
        pick(
            "claude",
            "Claude",
            "claude-code",
            ["claude-opus-5-5", "claude-sonnet-5"],
            efforts=["low", "medium", "high", "max"],
        ),
        pick(
            "codex",
            "Codex",
            "codex-cli",
            ["gpt-6.2-sol", "gpt-6.2-astra", "gpt-6.1-terra", "gpt-6-luna"],
            efforts=["low", "medium", "high", "xhigh"],
        ),
        pick(
            "gemini",
            "Antigravity",
            "antigravity",
            [
                "gemini-3.8-flash-high",
                "gemini-3.8-flash-medium",
                "gemini-3.8-flash-low",
            ],
            efforts=["low", "medium", "high"],
            harnesses=[harness("antigravity", True)],
            capabilities=dict(
                standalone=True,
                effort_required=True,
                worktree_required=True,
                resources_required=True,
            ),
        ),
        pick(
            "deepseek",
            "DeepSeek",
            "dsh",
            ["deepseek-v4-pro", "deepseek-v4-flash"],
            harnesses=[harness("dsh", True), harness("hermes", False)],
        ),
        pick(
            "local-qwen",
            "Local Qwen",
            "dsh",
            ["qwen3.6"],
            locality="local",
            harnesses=[harness("dsh", True), harness("hermes", False)],
        ),
    ],
    naming=dict(
        adjectives=["Amber", "Patient", "Nimble", "Calm", "Sage", "Bright", "Swift"],
        scientists=["Curie", "Faraday", "Turing", "Gauss", "Noether", "Hopper", "Bell"],
    ),
    dirs=[
        dict(path=agents[0]["cwd"], label="Demo vault" if args.guide_board else "Release review", exists=True)
    ],
)
usage = dict(
    ok=True,
    providers=[
        dict(
            provider=p,
            status="ok",
            observed_at=int(now),
            windows=[
                dict(label="5H", remaining_percent=a, resets_at=int(now) + 8200),
                dict(label="7D", remaining_percent=b, resets_at=int(now) + 18200),
            ],
        )
        for p, a, b in [("claude", 64, 41), ("codex", 88, 47)]
    ],
)
graph = dict(
    nodes=agents, edges=edges, spawn=spawn, degraded=False, unrepresented_edges=0
)
prefs = {}
J = web.json_response


def portrait(name):
    stem = next(
        (
            p.stem
            for p in (dash / "portraits_64").glob("*.png")
            if name.endswith(p.stem)
        ),
        None,
    )
    return (
        web.FileResponse(dash / "portraits_64" / f"{stem}.png")
        if stem
        else web.Response(status=404)
    )


def preview(ref):
    if ref == "b" * 32:
        import base64

        encoded = base64.b64encode((base / "sample-chart.png").read_bytes()).decode()
        return dict(
            ok=True,
            kind="image",
            data=encoded,
            base64=encoded,
            mime="image/png",
            image_base64=encoded,
            notice="Current file · demo chart",
        )
    return dict(
        ok=True,
        kind="text",
        text=preview_text,
        syntax="markdown",
        notice="Current file",
    )


TERMINAL_OUTPUT = {
    "AmberCurie": (
        "❯ Review the release notes.\r\n\r\n"
        "● Three checks in progress.\r\n"
        "  ✓ Keyboard tests passed\r\n"
        "  ✓ Both themes reviewed\r\n"
        "  ↳ Mobile layout pending\r\n\r\n"
        "  Mail  Keyboard review received\r\n"
        "  Mail  Mobile captures received\r\n\r\n"
        "● Writing the checklist…"
    ),
    "PatientFaraday": (
        "❯ Check keyboard shortcuts.\r\n\r\n"
        "• Tab → composer\r\n"
        "• Enter → send\r\n"
        "• Esc → stop\r\n\r\n"
        "\x1b[36m? Include the shortcuts?\x1b[0m\r\n"
        "  1. Add to the release notes\r\n"
        "  2. Keep in the usage guide\r\n\r\n"
        "Waiting for your answer…"
    ),
    "NimbleTuring": (
        "❯ Verify the phone experience.\r\n\r\n"
        "✓ Opened the agent from Graph\r\n"
        "✓ Switched to the terminal\r\n"
        "✓ Checked the conversation layout\r\n"
        "↳ Comparing light and dark captures\r\n\r\n"
        "● Preparing the mobile screenshots…"
    ),
    "WarmLovelace": (
        "❯ Check the release.\r\n\r\n"
        "● I am reading the checklist.\r\n"
        "  Keyboard navigation: verified\r\n"
        "  Mobile layout: reviewed\r\n"
        "  Remaining task: summarize changes"
    ),
}
if args.guide_board:
    TERMINAL_OUTPUT.update({
        "AmberCurie": "❯ What should we work on next?\r\n\r\n● Reading the demo task board…\r\n",
        "WarmLovelace": "● Ready to review the task board.\r\n",
    })
if args.team_hero:
    TERMINAL_OUTPUT[names[0]] = ("● チームへの依頼を待っています。\r\n" if args.team_hero == "ja"
                                 else "● Waiting for the team's request.\r\n")
if args.reader_demo:
    TERMINAL_OUTPUT[names[0]] = f"❯ {request}\r\n\r\n● {plan}\r\n\r\n"
PAUSED_REVIEW = (
    "Paused the review. The keyboard checklist and mobile captures are ready."
)
stopped_review = False
connections = set()


def conversation_event(id, role, text):
    return dict(id=id, kind="text", role=role, text=text, ts=fake_stamp)


async def ws_handle(req):
    global stopped_review
    ws = web.WebSocketResponse()
    await ws.prepare(req)
    connections.add(ws)
    await ws.send_json(dict(type="sessions", sessions=names[:hero["size"]] if args.team_hero else names))
    async for msg in ws:
        if msg.type.name != "TEXT":
            continue
        p = json.loads(msg.data)
        typ = p.get("type")
        if typ == "attach" and p.get("session") in names:
            n = p["session"]
            i = names.index(n)
            s = (
                "\x1b[1;36m"
                + programs[i].upper()
                + "\x1b[0m  ·  "
                + modelids[i]
                + "\r\n\r\n"
            )
            s += TERMINAL_OUTPUT.get(
                n, "Review the release notes and report any changes."
            )
            meta = dict(
                paneId=f"%{100 + i}",
                windowId=f"@{100 + i}",
                width=85,
                height=24,
                command=programs[i],
                cwd=agents[i]["cwd"],
                cols=85,
                rows=24,
            )
            await ws.send_json(
                dict(type="reset", session=n, incarnation="fixture", panes=[meta])
            )
            await ws.send_json(
                dict(type="output", session=n, paneId=meta["paneId"], data=s)
            )
        if p.get("inputAck"):
            await ws.send_json(
                dict(
                    type="input-ack",
                    id=p["inputAck"],
                    paneId=p.get("paneId"),
                    status="accepted",
                )
            )
            if args.team_hero and typ == "submit-prompt" and p.get("session") == names[0]:
                hero["accepted"] = True
            if typ in ("interrupt", "submit-prompt") and p.get("session") in names:
                row = agents[names.index(p["session"])]
                row["act_state"] = "wait"
                if typ == "interrupt" and row["name"] == "AmberCurie":
                    stopped_review = True
                replies = {
                    "PatientFaraday": "\r\n❯ 1\r\n\x1b[32m✓ Added the shortcuts to the release notes.\x1b[0m",
                    "WarmLovelace": "\r\n\r\n❯ What changed?\r\n\x1b[32m✓ Added keyboard shortcuts and verified the mobile layout.\x1b[0m",
                }
                if args.guide_board:
                    replies["WarmLovelace"] = (
                        "\r\n❯ What should we work on next?\r\n"
                        "● Start by organizing the experiment notes.\r\n"
                    )
                if typ == "submit-prompt" and row["name"] in replies:
                    await ws.send_json(
                        dict(
                            type="output",
                            session=row["name"],
                            paneId=p["paneId"],
                            data=replies[row["name"]],
                        )
                    )
    connections.discard(ws)
    return ws


def reel_story():
    # Reuse the public demo's fictional names, timeline and messages without
    # starting its optional tmux printers or opening a Mail database.
    path = base / "tel/scripts/dashboard-demo-reel.py"
    spec = importlib.util.spec_from_file_location("docs_reel", path)
    reel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reel)
    cast, script, lineage = {}, [], {}
    for event in reel.TIMELINE:
        at, kind = event["at"], event["type"]
        if kind == "spawn":
            lineage[event["child"]] = event["parent"]
        if kind == "mail":
            script.append(
                dict(
                    at=at,
                    from_=event["sender"],
                    to=event["recipient"],
                    subject=event["subject"],
                    body=event["body"],
                )
            )
        if kind == "agent_add":
            name = event["agent"]
            data = reel.AGENTS[name]
            provider = "openai" if data["program"] == "codex-cli" else "anthropic"
            cast[name] = dict(
                name=name,
                born=at,
                dies=None,
                ctx0=20 + data["id"] * 3,
                ctxRate=0.2,
                model=modelids[1 if provider == "openai" else 0],
                program=data["program"],
                provider=provider,
                task=data["task"],
                role=data["role"],
                group=data["group"],
                states=[],
            )
    for name, row in cast.items():
        row["parent"] = lineage.get(name)
    cast["Bright-Curie"]["states"] = [[35, 48, "question"]]
    cast["Swift-Noether"]["states"] = [[35, 48, "ask"]]
    for row in script:
        row["from"] = row.pop("from_")
    frequent = max(
        {(msg["from"], msg["to"]) for msg in script},
        key=lambda pair: sum((msg["from"], msg["to"]) == pair for msg in script),
    )
    for index, (subject, body) in enumerate(
        [
            ("Keyboard result", "All shortcuts passed in the compact layout."),
            ("Mobile check", "The Focus view and send confirmation are ready."),
            ("Ready for review", "The checklist and both theme captures are attached."),
        ]
    ):
        script.append(
            {
                "at": 38 + index,
                "from": frequent[index % 2],
                "to": frequent[1 - index % 2],
                "subject": subject,
                "body": body,
            }
        )
    script.sort(key=lambda msg: msg["at"])
    transcripts = {
        n: [
            [1, "user", "text", a["task"]],
            [
                2,
                "assistant",
                "text",
                "I will check the initial observations and send the results.",
            ],
        ]
        for n, a in cast.items()
    }
    return dict(
        id="docs-reel",
        loop=60,
        opensAt=4,
        cast=list(cast.values()),
        script=script,
        past=[],
        transcripts=transcripts,
        deliverables={},
        beats=[],
        ja={},
    )


async def app_handle(req):
    path = req.path
    q = req.query
    if path == "/ws":
        return await ws_handle(req)
    if path.rstrip("/") in ("/network", "/dashboard", "/deck"):
        if path.endswith("/"):
            contents = (
                (base / "demo/index.html")
                .read_text()
                .replace("<head>", '<head><base href="/">', 1)
            )
            return web.Response(text=contents, content_type="text/html")
        return web.FileResponse(base / "demo/index.html")
    if path in ("/", "/cockpit"):
        return web.FileResponse(bridge / "cockpit.html")
    if path.startswith("/portraits_64/"):
        return portrait(Path(path).stem)
    if path.startswith("/portrait"):
        return portrait(q.get("name", path.rsplit("/", 1)[-1].removesuffix(".png")))
    if path.startswith("/telemetry/portrait"):
        return portrait(q.get("name", path.rsplit("/", 1)[-1]))
    if path == "/telemetry/prefs":
        if req.method == "PUT":
            upd = await req.json()
            prefs.update(upd.get("set", {}))
        return J(dict(ok=True, rev=1, prefs=prefs))
    if path == "/telemetry/identity":
        return J(identity)
    if path == "/telemetry/platform":
        return J(dict(host="mac", home_dir=identity["home"], file_paste=True))
    if args.reader_demo and path == "/fixture-reader-output" and req.method == "POST":
        for line in reader_terminal:
            for socket in tuple(connections):
                await socket.send_json(dict(type="output", session=names[0], paneId="%100", data=line + "\r\n"))
            await asyncio.sleep(.063)
        return J(dict(ok=True))
    if args.team_hero and path == "/fixture-team" and req.method == "POST":
        if not hero["accepted"]:
            return J(dict(ok=False), status=409)
        hero["size"] = min(5, hero["size"] + 1)
        for socket in tuple(connections):
            await socket.send_json(dict(type="sessions", sessions=names[:hero["size"]]))
        return J(dict(ok=True))
    if args.team_hero and path == "/fixture-team-report" and req.method == "POST":
        index = len(messages)
        if hero["size"] != 5 or index >= len(hero_reports):
            return J(dict(ok=False), status=409)
        subject, body = hero_reports[index]
        messages.append(dict(id=501+index, sender=names[index+1], recipient=names[0],
                             ts=int(time.time()), subject=subject, body_md=body))
        agents[index+1]["act_state"] = "wait"
        return J(dict(ok=True))
    if path == "/telemetry/agents":
        rows = [a for a in agents if a["running"]] if args.guide_board and q.get("scope") == "live" else agents
        return J(dict(agents=rows[:hero["size"]] if args.team_hero else rows))
    if path == "/telemetry/messages":
        return J(dict(ok=True, messages=messages, now=int(now)))
    if args.guide_board and path == "/fixture-guide-mail" and req.method == "POST":
        message_id = max(message["id"] for message in messages) + 1
        messages.append(dict(
            id=message_id, sender="BrightHopper", recipient="AmberCurie", ts=int(time.time()),
            subject="Task board reviewed", body_md="Start by organizing the experiment notes.\n\nThe open tasks are in the demo vault.",
        ))
        return J(dict(ok=True))
    if path == "/telemetry/graph":
        if args.team_hero:
            return J(dict(nodes=agents[:hero["size"]], edges=[], spawn=spawn[:hero["size"]-1],
                          degraded=False, unrepresented_edges=0))
        return J(graph)
    if path == "/telemetry/mail/recent":
        return J(dict(ok=True, messages=messages))
    if args.guide_board and req.method == "POST" and path in ("/api/exit", "/api/jump"):
        payload = await req.json()
        agent = next((a for a in agents if a["name"] == payload.get("session")), None)
        if agent is None:
            return J(dict(ok=False, error="Unknown demo agent"), status=404)
        permission = payload.get("permission") or {}
        if payload.get("check_only"):
            return J(dict(ok=True, action="validated"))
        if path == "/api/exit":
            await asyncio.sleep(.9)
            agent.update(running=False, category="gone", state="gone", resume_capability="ready")
            guide_permissions(agent, "resume")
            return J(dict(ok=True))
        await asyncio.sleep(1.1)
        if "computer_use" in permission:
            agent["computer_use"] = permission["computer_use"]
        if "browser_mode" in permission:
            agent["browser_mode"] = permission["browser_mode"]
            agent["browser_use"] = permission["browser_mode"] != "off"
        agent.update(running=True, category="agent", state="run", act_state="work" if permission else "wait")
        guide_permissions(agent, "restart")
        return J(dict(ok=True, action="resumed", tools_changed=bool(permission)))
    if path in ("/telemetry/spawn-catalog", "/fixture-catalog"):
        return J(catalog)
    if path == "/telemetry/spawn" and req.method == "POST":
        name = "WarmLovelace"
        if name not in names:
            names.append(name)
            modelids.append(modelids[0])
            programs.append(programs[0])
            providers.append(providers[0])
            agents.append(
                dict(
                    agents[0],
                    name=name,
                    task="Review the task board" if args.guide_board else "Check the release",
                    annot=dict(role="Task reviewer" if args.guide_board else "Release reviewer"),
                    parent_agent=None,
                    history_session_id="fixture-tour-launch",
                    act_state="work",
                )
            )
            for socket in tuple(connections):
                await socket.send_json(dict(type="sessions", sessions=names))
        return J(dict(ok=True, child_name=name))
    if path == "/telemetry/fs/dirs":
        return J(
            dict(
                path=identity["home"],
                dirs=[dict(name=catalog["dirs"][0]["label"], path=catalog["dirs"][0]["path"])],
            )
        )
    if path == "/fixture-reel":
        return J(reel_story())
    if path == "/telemetry/skills":
        return J(
            dict(
                ok=True,
                prefix="$",
                skills=[
                    dict(
                        name="review-pr",
                        kind="skill",
                        description="Review a pull request",
                    ),
                    dict(
                        name="delegate", kind="skill", description="Start a child agent"
                    ),
                    dict(
                        name="approvals",
                        kind="builtin",
                        description="View approval settings",
                    ),
                ],
            )
        )
    if path == "/telemetry/conversation":
        if args.reader_demo:
            if q.get("after"):
                await asyncio.sleep(.5)
            return J(dict(ok=True, agent=q.get("agent"), events=[] if q.get("after") else events,
                          provider="claude", mode="cursor", after="reader:1", has_older=False))
        if args.team_hero:
            selected = events[:1] if hero["accepted"] else []
            if len(messages) == len(hero_reports):
                message = messages[-1]
                selected = [events[0], dict(
                    id="hero-mail", kind="tool", role="assistant", ts=fake_stamp, text="ORRERY Mail",
                    mail=[dict(direction="received", sender=message["sender"], recipients=[names[0]],
                               subject=message["subject"], body=message["body_md"], coverage="request")],
                ), events[1]]
            return J(dict(ok=True, agent=q.get("agent"), events=selected, provider="claude",
                          mode="snapshot", has_older=False))
        tail = q.get("after")
        paused = q.get("agent") == "AmberCurie" and stopped_review
        update = (
            [conversation_event("paused-review", "assistant", PAUSED_REVIEW)]
            if paused
            else []
        )
        if not tail:
            selected = events + update
        else:
            await asyncio.sleep(0.8)
            selected = update if tail == "fixture:1" else []
        return J(
            dict(
                ok=True,
                agent=q.get("agent"),
                events=selected,
                provider="codex",
                mode="cursor",
                after="fixture:2" if paused else "fixture:1",
                has_older=False,
            )
        )
    if path == "/telemetry/conversation/preview":
        return J(preview(q.get("ref")))
    if path in ("/telemetry/usage", "/api/usage"):
        return J(usage)
    if path == "/api/version":
        return J(dict(api=71, runtime_mode="legacy"))
    if path.startswith(("/telemetry/", "/api/")):
        return J(dict(ok=True), status=404)
    if path.startswith("/cockpit-assets/"):
        f = bridge / "assets" / Path(path).name
    else:
        f = bridge / path[1:]
        if not f.is_file():
            f = base / "demo" / path[1:]
        if not f.is_file() and path.startswith("/assets/"):
            f = dash / path[1:]
    if f.resolve().is_relative_to(base.resolve()) and f.is_file():
        return web.FileResponse(f)
    return web.Response(status=404)


fixture = json.loads((base / "tel/tests/fixtures/mobile_snapshot.json").read_text())
# A short synthetic name fits the product's existing mobile Reader bar.
PHONE_TERMINAL_NAME = "Turing"


def phone_name(name):
    return PHONE_TERMINAL_NAME if name == "NimbleTuring" else name


phone_agents = [
    dict(
        row,
        name=phone_name(row["name"]),
        last_active=int(now) - row.get("last_active_age", 60),
    )
    for row in fixture["agents"][:8]
]
terminal_agent = next(row for row in phone_agents if row["name"] == PHONE_TERMINAL_NAME)
terminal_agent.update(
    computer_use="view",
    computer_use_source="launch",
    browser_use=False,
    browser_use_source="launch",
)
if args.readme_phone:
    terminal_agent["act_state"] = "question"
phone_agent_names = {row["name"] for row in phone_agents}


def phone_connections(kind):
    return [
        dict(edge, source=phone_name(edge["source"]), target=phone_name(edge["target"]))
        for edge in fixture.get(kind, [])
        if {phone_name(edge["source"]), phone_name(edge["target"])} <= phone_agent_names
    ]


phone_events = [
    dict(
        key="demo-review",
        source="AmberCurie",
        target="PatientFaraday",
        kind="to",
        sender="AmberCurie",
        recipient="PatientFaraday",
        subject="Release review",
        event_at=now - 80,
        importance="normal",
        direction="to",
        body="The mobile review is ready.\n\n• Focus opens the selected agent.\n• Terminal shows the latest output.\n• Review input displays the exact line before sending.",
        id=701,
    )
]
source = dict(status="available", observed_at=now, age_seconds=0)
snapshot = dict(
    schema=1,
    window="day",
    observed_at=now,
    sources=dict.fromkeys(["agents", "graph", "mail"], source),
    agents=phone_agents,
    period=dict(seconds=86400, activity_unknown=0),
    graph=dict(
        nodes=phone_agents,
        edges=phone_connections("edges"),
        spawn=phone_connections("spawn"),
        degraded=False,
        unrepresented_edges=0,
    ),
    timeline=dict(
        scope="0" * 32,
        mail=phone_events,
        states=[],
        events_truncated=False,
        edges_truncated=False,
        states_truncated=False,
    ),
)


async def phone_handle(req):
    p = req.path
    q = req.query
    if p == "/view/demo":
        return J(dict(version=1, supported=True, on=True, words=[], identity=identity))
    if p == "/demo-mask.js":
        return web.FileResponse(bridge / "demo_mask.js")
    if p == "/demo-mode.js":
        return web.FileResponse(bridge / "demo_mode.js")
    if p == "/view/snapshot":
        return J(dict(snapshot, window=q.get("window", "day")))
    if p in ("/view/message", "/view/mail"):
        return J(
            dict(
                event=phone_events[0],
                events=phone_events,
                window="day",
                subject="Release review",
                body=phone_events[0]["body"],
            )
        )
    if p == "/view/history":
        return J(dict(enabled=True))
    if p == "/view/conversation":
        history = [
            dict(
                id=f"earlier-{i}",
                kind="text",
                role="assistant",
                text=line,
                ts=fake_stamp,
            )
            for i, line in enumerate(
                [
                    "I checked the release notes and compared the candidate build.",
                    "The keyboard shortcuts are consistent in both layouts.",
                    "The screenshot captions match the visible controls.",
                    "The mobile screen still needs a quick pass.",
                    "I will summarize the remaining preview checks.",
                ]
            )
        ]
        conversation = [
            dict(
                event,
                mail=[dict(mail, recipients=[q.get("name")]) for mail in event["mail"]],
            )
            if "mail" in event
            else event
            for event in events
        ]
        return J(
            dict(
                ok=True,
                agent=q.get("name"),
                provider="codex",
                limited=False,
                tail_only=False,
                events=history + conversation,
            )
        )
    if p == "/view/conversation/preview":
        return J(preview(q.get("ref")))
    if p == "/view/spawn":
        return J(catalog)
    if p == "/view/portrait":
        return portrait(q.get("name", ""))
    if p.startswith("/view/terminal"):
        contract = dict(contract="orrery-mobile-pane-v1", epoch="fixture-epoch")
        target = dict(
            choice="fixture-choice",
            name=PHONE_TERMINAL_NAME,
            pane_label="Window 0 · pane 0",
            revision="fixture-revision",
        )
        if req.method == "GET":
            return J(
                dict(
                    contract,
                    api=31,
                    supported="legacy-managed-pane",
                    enabled=True,
                    ack="tmux-command-accepted",
                )
            )
        if p.endswith("/targets"):
            return J(dict(contract, targets=[target]))
        if p.endswith("/prepare"):
            payload = await req.json()
            return J(
                dict(
                    contract,
                    state="prepared",
                    target=target,
                    text=payload["text"],
                    expires_in=30,
                    intent="demo-intent",
                    confirmation="demo-confirmation",
                )
            )
        if p.endswith("/commit"):
            return J(
                dict(contract, state="accepted", target=target, intent="demo-intent")
            )
        if p.endswith("/preview"):
            return J(
                dict(
                    contract,
                    target=target,
                    text=(
                        "❯ Prepare the release review.\n\n"
                        "Reading the release checklist…\n"
                        "✓ Keyboard shortcuts checked\n"
                        "  Tab     Focus the input\n"
                        "  Enter   Review the message\n"
                        "  Esc     Leave the input\n\n"
                        "✓ Captured both color themes\n"
                        "✓ Compared both window widths\n"
                        "✓ Sent keyboard results by Mail\n\n"
                        "Next: check the mobile layout.\n"
                        "Waiting for your instruction."
                    ),
                    observed_at=time.time(),
                    max_lines=120,
                    max_bytes=12288,
                )
            )
        return J(dict(contract, target=target, enabled=True, ok=True))
    if p == "/network.css":
        return web.Response(text=network_css, content_type="text/css")
    if p in mobile_assets:
        f, mime = mobile_assets[p]
        return web.FileResponse(f, headers={"Content-Type": mime})
    return web.Response(status=404)


app = web.Application()
phoneapp = web.Application()
app.router.add_route("*", "/{path:.*}", app_handle)
phoneapp.router.add_route("*", "/{path:.*}", phone_handle)


async def main():
    for app_to_serve in (app, phoneapp):
        runner = web.AppRunner(app_to_serve)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        print(runner.addresses[0][1], flush=True)
    await asyncio.Future()


asyncio.run(main())
