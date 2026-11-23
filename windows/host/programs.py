"""How to start each supported agent CLI on Windows.

Each launch joins the hub as ``name``: the hub's MCP server gets the name
both as ``--agent`` (Claude, per-launch MCP config) and as ``ORRERY_AGENT``
(Antigravity, whose MCP servers are registered globally and inherit the
CLI's environment). Per-agent files live under the host's state directory.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

WINDOWS = Path(__file__).resolve().parent.parent
MCP_SERVER = WINDOWS / "hub" / "mcp_server.py"
MCP_NAME = "orrery-hub"
PROGRAMS = ("claude", "agy")


def state_dir() -> Path:
    configured = os.environ.get("ORRERY_WIN_STATE")
    if configured:
        return Path(configured).expanduser()
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
    return Path(base) / "orrery-win"


def resolve_launcher(path: str) -> str:
    """npm's ``.cmd`` shims only forward to a native exe; start that exe directly.

    ConPTY needs a real executable: a batch file would put cmd.exe between
    the terminal and the agent.
    """
    if not path.lower().endswith((".cmd", ".bat")):
        return path
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return path
    match = re.search(r'"%dp0%\\?([^"%]+?\.exe)"', text, re.IGNORECASE)
    if match:
        target = Path(path).parent / match[1]
        if target.is_file():
            return str(target)
    return path


def find_executable(program: str) -> str | None:
    override = os.environ.get({"claude": "ORRERY_CLAUDE", "agy": "ORRERY_AGY"}[program])
    if override:
        return override if Path(override).is_file() else None
    found = shutil.which(program)
    if found:
        return resolve_launcher(found)
    if program == "agy":
        default = Path.home() / ".gemini" / "bin" / "agy.exe"
        if default.is_file():
            return str(default)
    return None


# Markers a running Claude Code session sets for its own children. A host
# started from inside Claude Code (e.g. the VS Code panel) must not pass
# them on: the agent would think it is a child session (no transcript, the
# parent's session id and messaging socket). User configuration such as
# CLAUDE_CODE_GIT_BASH_PATH is kept.
SESSION_MARKERS = re.compile(
    r"CLAUDECODE|CLAUDE_PID|CLAUDE_EFFORT|CLAUDE_AGENT_SDK_VERSION|MCP_CONNECTION_NONBLOCKING"
    r"|CLAUDE_CODE_(?:\w*(?:CHILD|SESSION|MESSAGING|ENTRYPOINT|EXECPATH|SDK|STARTUP)\w*"
    r"|QUESTION_PREVIEW_FORMAT|ENABLE_TASKS)", re.IGNORECASE)


def clean_environment(env: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if not SESSION_MARKERS.fullmatch(k)}


@dataclass
class Launch:
    argv: list[str]
    env: dict[str, str]


def build(program: str, name: str, *, resume: bool = False, hub_db: str | None = None,
          host_url: str | None = None, extra_args: list[str] | None = None) -> Launch:
    if program not in PROGRAMS:
        raise ValueError(f"unsupported program {program!r}")
    exe = find_executable(program)
    if exe is None:
        raise FileNotFoundError(f"{program} was not found (set ORRERY_{program.upper()} to its path)")
    folder = state_dir() / "agents" / name
    folder.mkdir(parents=True, exist_ok=True)
    env = clean_environment(dict(os.environ))
    env["ORRERY_AGENT"] = name
    if hub_db:
        env["ORRERY_HUB_DB"] = hub_db
    if host_url:
        env["ORRERY_HOST_URL"] = host_url
    server_args = [str(MCP_SERVER), "--agent", name] + (["--db", hub_db] if hub_db else [])
    if program == "claude":
        mcp = folder / "mcp.json"
        mcp.write_text(json.dumps({"mcpServers": {MCP_NAME: {
            "type": "stdio", "command": sys.executable, "args": server_args}}}), encoding="utf-8")
        argv = [exe, "--mcp-config", str(mcp), "--allowedTools", f"mcp__{MCP_NAME}"]
        if resume:
            argv.append("--continue")
    else:
        settings = folder / "agy-settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": [f"mcp({MCP_NAME}/*)"]}}),
                            encoding="utf-8")
        argv = [exe, "--settings", str(settings)]
        if resume:
            argv.append("--continue")
    return Launch(argv=argv + list(extra_args or []), env=env)


def agy_hub_registered() -> bool | None:
    """Whether Antigravity has the hub MCP server; None when agy is missing or fails."""
    exe = find_executable("agy")
    if exe is None:
        return None
    try:
        out = subprocess.run([exe, "mcp", "list"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return any(line.split()[:1] == [MCP_NAME] for line in out.splitlines())


def register_agy_hub() -> str:
    exe = find_executable("agy")
    if exe is None:
        raise FileNotFoundError("agy was not found")
    done = subprocess.run([exe, "mcp", "add", MCP_NAME, sys.executable, str(MCP_SERVER)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=30)
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout).strip()[:500])
    return done.stdout.strip()
