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
base = parser.parse_args().snapshot
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
    home="/Users/demo",
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
    "claude-opus-4-7",
    "gpt-5.6-sol",
    "gemini-3.1-pro-high",
    "deepseek-v4-pro",
    "qwen3.6",
    "gpt-5.6-sol",
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
        cwd="/demo-workspace/release-review",
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
            ["claude-opus-4-7", "claude-sonnet-5"],
            efforts=["low", "medium", "high", "max"],
        ),
        pick(
            "codex",
            "Codex",
            "codex-cli",
            ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-astra", "gpt-5.5"],
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
        dict(path="/demo-workspace/release-review", label="Release review", exists=True)
    ],
)
usage = dict(
    ok=True,
    providers=[
        dict(
            provider=p,
            status="ok",
            windows=[
                dict(label="5H", remaining_percent=a, reset_at=int(now) + 8200),
                dict(label="7D", remaining_percent=b, reset_at=int(now) + 18200),
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
    await ws.send_json(dict(type="sessions", sessions=names))
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
            if typ in ("interrupt", "submit-prompt") and p.get("session") in names:
                row = agents[names.index(p["session"])]
                row["act_state"] = "wait"
                if typ == "interrupt" and row["name"] == "AmberCurie":
                    stopped_review = True
                replies = {
                    "PatientFaraday": "\r\n❯ 1\r\n\x1b[32m✓ Added the shortcuts to the release notes.\x1b[0m",
                    "WarmLovelace": "\r\n\r\n❯ What changed?\r\n\x1b[32m✓ Added keyboard shortcuts and verified the mobile layout.\x1b[0m",
                }
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
                model=data["model"],
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
    if path == "/telemetry/agents":
        return J(dict(agents=agents))
    if path == "/telemetry/messages":
        return J(dict(ok=True, messages=messages, now=int(now)))
    if path == "/telemetry/graph":
        return J(graph)
    if path == "/telemetry/mail/recent":
        return J(dict(ok=True, messages=messages))
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
                    task="Check the release",
                    annot=dict(role="Release reviewer"),
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
                dirs=[dict(name="Release review", path=catalog["dirs"][0]["path"])],
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
