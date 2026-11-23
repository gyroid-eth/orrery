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
# Claude's prompt box: a horizontal rule, then the prompt mark. Claude Code
# usually draws "❯", but a live agent under the host drew ">" (2.1.330, the
# same version that drew "❯" elsewhere), so either counts.
CLAUDE_RULE = re.compile(r"^\s*─{8,}\s*$")
CLAUDE_PROMPT = ("❯", ">")
AGY_IDLE_FOOTER = re.compile(r"^\s*\? for shortcuts")
AGY_BUSY = re.compile(r"esc to cancel", re.IGNORECASE)


def lines(screen) -> list[str]:
    return [line.rstrip() for line in screen.display]


def dialog(text: str) -> bool:
    return bool(DIALOG.search(text))


def screen_state(program: str, rows: list[str]) -> str:
    """'idle', 'busy' or 'dialog' from the screen alone.

    For Claude, 'unclear' when the screen shows neither its busy marker nor
    its prompt box: then the hooks decide (Session.refresh), since a change
    in how Claude draws itself must not hide a finished turn.
    """
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
    return "idle" if claude_prompt(rows) else "unclear"


def claude_prompt(rows: list[str]) -> bool:
    """Claude's prompt box near the bottom: a rule, then a line opening with the mark.

    Requiring the rule keeps an earlier prompt in the scrollback, or a ">"
    in the agent's own output, from passing for the live prompt.
    """
    tail = rows[-12:]
    return any(CLAUDE_RULE.match(above) and row.lstrip().startswith(CLAUDE_PROMPT)
               for above, row in zip(tail, tail[1:]))
