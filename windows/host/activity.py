"""Is an agent waiting at its prompt? Read from its rendered screen.

Typing a notice into a terminal is only safe at the agent's empty prompt:
in a dialog, Enter would pick an option (Claude's trust prompt defaults to
"No, exit"). So a dialog on screen always means "not idle", and each CLI's
own busy marker overrides whatever a hook last said.

Markers were read from Claude Code 2.1 and Antigravity CLI 1.5 screens.
"""
from __future__ import annotations

import re

# Selection lists and confirmations of either CLI.
DIALOG = re.compile(
    r"Enter to confirm|enter Confirm|↑/↓ Navigate|Do you want to|Do you trust"
    r"|trust this folder|\(y/n\)|^\s*[❯>]\s*\d+\.\s", re.IGNORECASE | re.MULTILINE)
CLAUDE_BUSY = re.compile(r"esc to interrupt", re.IGNORECASE)
AGY_IDLE_FOOTER = re.compile(r"^\s*\? for shortcuts")
AGY_BUSY = re.compile(r"esc to cancel", re.IGNORECASE)


def lines(screen) -> list[str]:
    return [line.rstrip() for line in screen.display]


def dialog(text: str) -> bool:
    return bool(DIALOG.search(text))


def screen_state(program: str, rows: list[str]) -> str:
    """'idle', 'busy' or 'dialog' from the screen alone."""
    text = "\n".join(rows)
    if dialog(text):
        return "dialog"
    if program == "agy":
        footer = next((row for row in reversed(rows) if row.strip()), "")
        if AGY_BUSY.search(footer):
            return "busy"
        return "idle" if AGY_IDLE_FOOTER.match(footer) else "busy"
    if CLAUDE_BUSY.search(text):
        return "busy"
    # The prompt box: a line starting with the prompt mark near the bottom.
    tail = rows[-12:]
    return "idle" if any(row.lstrip().startswith("❯") for row in tail) else "busy"
