"""Pane input protocol shared with ORRERY Telemetry's pane_submission.py.

Use the live tmux socket's inode and pane ID, independently of the client,
working directory, or provider. The lock can retain a digest of our pending
notice when the editor shows only its length, without storing its text.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, replace
from unicodedata import category, east_asian_width


METADATA = ('#{socket_path}\t#{pid}\t#{pane_id}\t#{pane_pid}\t#{cursor_y}\t#{pane_in_mode}'
            '\t#{cursor_x}\t#{bracket_paste_flag}\t#{pane_current_command}')
POLL = .06
TIMEOUT = 5.0
REDRAW_GRACE = 1.0
SLASH_MENU_WAIT = .30
SUBMISSION_CLEAR_GRACE = .25
SHELLS = frozenset({
    'ash', 'bash', 'busybox', 'cmd', 'csh', 'dash', 'elvish', 'fish', 'hush',
    'ksh', 'ksh93', 'mksh', 'nu', 'nushell', 'pdksh', 'powershell', 'pwsh',
    'sh', 'tcsh', 'xonsh', 'yash', 'zsh',
})
CONTROL_BYTES = re.compile(r'[\x00-\x1f\x7f-\x9f]')
MULTILINE_CONTROLS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]')
EDITOR_EXECUTABLES = {
    'agy': {'agy', 'gemini'},
    'claude': {'claude'},
    'codex': {'codex'},
    'dsh': {'dsh'},
    'hermes': {'hermes'},
}
PROMPT = re.compile(r'^(\s*(?:(?:[⌸│☤]|[\w.-]+)\s+)?)([❯›>⌘☤])(?:[ \u00a0]+|$)(.*)')
BORDER = re.compile(r'^[╭╰]?[─━]{8,}[╮╯]?$')
CLAUDE_NAMED_BORDER = re.compile(r'^[─━]{8,}[ \t]+\S(?:.*\S)?[ \t]+[─━]+$')
CLAUDE_SCROLLED_BORDER = re.compile(
    r'^[─━]{2,}[ \t]+[↑↓][ \t]+\d+[ \t]+more(?:[ \t]+[─━]+(?:[ \t]+\S(?:.*\S)?[ \t]+[─━]+)?)?$')
SGR = re.compile(r'\x1b\[[0-9;:]*m')
OSC8 = re.compile(r'\x1b\]8;[^;\x1b\x07]*;[^\x1b\x07]*(?:\x1b\\|\x07)')
DIM = re.compile(r'\x1b\[(?:[0-9]+;)*2(?:;[0-9]+)*m')
CLAUDE_QUEUE_HINT = 'Press up to edit queued messages'
CLAUDE_SUGGESTION = re.compile(r'^[  ]*\x1b\[(?:[0-9]+;)*2(?:;[0-9]+)*m[^\x1b]+(?:\x1b\[(?:0|22)?m[  ]*)?$')
CLAUDE_ARGUMENT_HINT = re.compile(r'\x1b\[(?:38;5;246|(?:0;)?2)m[^\x1b]+'
                                  r'(?:\x1b\[(?:0|22|39)?m)?[ \t]*$')
COLLAPSED = re.compile(r'\[Pasted text #\d+(?: \+(\d+) lines?)?\]')
HERMES_PASTE = re.compile(r'\[Pastedtext#(\d+):(\d+)lines→/.+/pastes/paste_\1_\d{6}\.txt\]')
HERMES_HINT = re.compile(r'^(?:msg=[\w-]+ · /queue · /bg · /steer · Ctrl\+C cancel|cli\.tui\.placeholder_busy)$')
HERMES_STATUS = re.compile(r'^(?:[^│]+ │ )?☤ \S')
HERMES_EDITOR_ROWS = 8
ITALIC_CHANGE = re.compile(r'\x1b\[(0|3|23)m')
HERMES_TOOL_PROGRESS = re.compile(
    r'^  [^ \t┊│].* {2}\(\s*(?:\d+\.\ds|\d+m[0-5]\ds|cli\.shared\.duration_(?:s|ms_compact))'
    r'(?: · ↓ \d+(?:\.\d+)?[kM]? tok)?\)$')
HERMES_GHOST = re.compile(r'\x1b\[38;5;241m[^\x1b]+\x1b\[39m[ \t]*$')
HERMES_MENU_STYLING = re.compile(r'\x1b\[(?:[0-9]+;)*48;[25];[0-9;]+m')
PASTING = re.compile(r'^\s*(?:Pasting(?:…|\.\.\.)|Waiting for startup\b)', re.I)
AGY_MODE = re.compile(
    r'^(?:(?:\? for shortcuts|esc to cancel)\s{2,})?(?:auto|plan|accept[- ]edits)\s+·\s+', re.I)
AGY_MODE_ONLY = re.compile(r'^(?:(?:\? for shortcuts|esc to cancel)\s{2,})?(?:auto|plan|accept[- ]edits)$', re.I)
AGY_MODEL_FOOTER = re.compile(
    r'^(?:(?:\? for shortcuts|esc to cancel)\s{2,})?Gemini(?:[ -][^·]+)?\s+·\s+(?:low|medium|high|xhigh|max)$',
    re.I)
AGY_SCROLL_MARKER = re.compile(
    rf'(?:{SGR.pattern}|[ \t])*\x1b\[90m↑ [1-9]\d* more lines?(?:{SGR.pattern})*[ \t]*')
AGY_PASTE = re.compile(r'\[Pasted\s+text\s+#[1-9]\d*\s+([1-9][0-9]{0,8})\s+chars\]')
AGY_PLACEHOLDER = {
    'Auto mode: edits & safe commands auto-approved (shift+tab to cycle)',
    'Accept-edits mode: file edits auto-approved (shift+tab to cycle)',
    'Plan mode: research & plan only (shift+tab to cycle)',
    'Best-of-N mode: parallel arms, /model to pick models (shift+tab to cycle)',
}
DSH_PLACEHOLDER = 'Say something, or type / for commands…'
DSH_COMPACT_WELCOME_PROMPT = re.compile(r'^(\s*│ )(❯)(\S.*)$')
DSH_PASTE = re.compile(r'▸ (\d+) lines?・(\d+) chars?・(.+?)・hover to peek')
DSH_PASTE_COUNTS = re.compile(r'▸ ([1-9][0-9]{0,8}) lines?・([1-9][0-9]{0,8}) chars?・hover to peek')
DSH_PASTE_STYLE = re.compile(r'\x1b\[38;5;145m(?=▸ )')
SLASH_NAME = re.compile(r'/[\w.:-]+')
SLASH_OPTION = re.compile(r'^[ \t]{2,}' + SLASH_NAME.pattern + r'(?=[ \t]|$)')
CLAUDE_SLASH_SELECTION = re.compile(r'^[ \t]+❯[ \t]+(' + SLASH_NAME.pattern + r')(?=[ \t]|$)')
CODEX_SLASH_SELECTION = re.compile(r'^›[ \t]+(' + SLASH_NAME.pattern + r')(?=[ \t]|$)')
SLASH_CONTINUATION = re.compile(r'^[ \t]{8,}[^ \t/❯]')
REVERSE_VIDEO = re.compile(r'\x1b\[(?:[0-9]+;)*7(?:;[0-9]+)*m')
CODEX_PICKER_BACKGROUND = re.compile(r'\x1b\[48;2;(?:[0-9]{1,3};){2}[0-9]{1,3}m\Z')
DSH_COMMAND_MENU = re.compile(r'^\s*╭─ commands · \d+ items? ─+╮$')
DSH_COMMAND_SELECTED = re.compile(r'^\s*│\s+❯\s+([\w.:-]+)(?=\s|│|$)')
AGY_COMMAND_SELECTED = re.compile(r'^>\s+(' + SLASH_NAME.pattern + r')(?=[ \t]|$)')
AGY_COMMAND_HELP = '↑/↓ Navigate · enter Select · tab Complete'
AGY_WORKING = re.compile(r'^[\u2800-\u28ff]\s+Working(?:…|\.\.\.)$')
CODEX_WORKING = re.compile(r'^• (?:Working|Compacting context) \(.*\besc to interrupt\b')
CODEX_PASTE = re.compile(r'\[PastedContent([1-9][0-9]{0,8})chars\]')
CODEX_PASTE_STYLE = re.compile(r'\x1b\[(?:36|38;5;6)m(?=\[Pasted)')
CODEX_QUEUE_HINT = 'tab to queue message'
# Codex marks the viewport edge with a dim arrow, even flush against the text.
CODEX_SCROLL_ARROW = re.compile(rf'{DIM.pattern}([↑↓])(?:{SGR.pattern})*[ \t]*$')
NOTICE_TRAILER = re.compile(r'\s*(?:\.{3}\s+)?(?:Fetch inbox to read the rest\.|Please call fetch_inbox to read it\.)$')


@dataclass(frozen=True)
class Frame:
    socket: Path
    server: int
    pane: str
    process: int
    draft: str | None
    waiting: bool
    selected: bool = False
    hermes: bool = False
    dsh: bool = False
    bracketed: bool | None = None
    foreground_command: str = ''
    slash_picker: bool = False
    selected_command: str | None = None
    scrolled: bool = False
    dsh_clipped: bool = False
    hermes_busy: bool = False
    editor: str | None = None
    running: bool = False
    slash_view: tuple[str, str] | None = None
    redrawing: bool = False
    draft_continues: bool = False
    wrapped_editor: bool = False
    paste_chars: int | None = None
    codex_queue_hint: bool = False
    paste_lines: int | None = None
    command_ends_at_cursor: bool = False

    @property
    def identity(self):
        return self.socket, self.server, self.pane, self.process

    @property
    def empty(self):
        return self.draft == '' and not self.waiting and not self.selected

    def allows_paste(self, text, *, operator=False):
        if self.hermes_busy and not operator and not SLASH_NAME.fullmatch(text):
            # Hermes dispatches slash commands locally. Other input can
            # interrupt a running turn, depending on its busy input mode.
            return False
        if self.bracketed is not None:
            return self.bracketed
        # Before tmux 3.7, paste-buffer -p can see the mode but formats
        # cannot. Preserve TUI paste on those releases. In a shell, LF and
        # other control characters may be acted on before the draft is visible.
        return bool(self.foreground_command) and (
            self.foreground_command not in SHELLS
            or not CONTROL_BYTES.search(text)
            or self.wrapped_editor and not MULTILINE_CONTROLS.search(text))


def needs_wrapped_editor(view, text):
    return (text is not None and view is not None and view.bracketed is None
            and view.foreground_command in SHELLS and view.editor in EDITOR_EXECUTABLES
            and CONTROL_BYTES.search(text) is not None and not MULTILINE_CONTROLS.search(text))


def _process_columns(*args):
    try:
        result = subprocess.run(['ps', *args], capture_output=True, text=True, errors='replace',
                                timeout=.5, check=True)
    except (OSError, subprocess.SubprocessError):
        return ''
    return result.stdout


def _process_argv(pid):
    try:
        if sys.platform == 'linux':
            with open(f'/proc/{pid}/cmdline', 'rb') as source:
                data = source.read(16384)
            return [os.fsdecode(part) for part in data[:-1].split(b'\0')] if data.endswith(b'\0') else []
        return shlex.split(_process_columns('-ww', '-p', str(pid), '-o', 'args='))
    except (OSError, ValueError):
        return []


def _editor_process(editor, pid, executable):
    if executable in EDITOR_EXECUTABLES[editor]:
        return True
    if editor == 'codex' and re.fullmatch(r'codex-(?:aarch64|x86_64)-[\w-]+', executable):
        return True
    if editor == 'agy' and sys.platform == 'linux':
        try:
            if os.readlink(f'/proc/{pid}/exe').endswith('/agy'):
                return True
        except OSError:
            pass
    node = executable in {'node', 'nodejs', 'mainthread'}
    python = re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', executable)
    claude_version = editor == 'claude' and re.fullmatch(r'\d+\.\d+\.\d+', executable)
    if not (node or claude_version or editor == 'agy' or editor == 'hermes' and python):
        return False
    if claude_version:
        if sys.platform == 'linux':
            try:
                return os.readlink(f'/proc/{pid}/exe').endswith('/claude/versions/' + executable)
            except OSError:
                return False
        argv = _process_argv(pid)
        return bool(argv and argv[0].endswith('/claude/versions/' + executable))
    argv = _process_argv(pid)
    if editor == 'agy':
        if argv and argv[0].endswith('/agy'):
            return True
        if not node:
            return False
    if len(argv) < 2:
        return False
    script = argv[1]
    if python:
        return (argv[1:3] == ['-m', 'hermes_cli.main']
                or script.endswith(('/bin/hermes', '/hermes_cli/main.py')))
    return script.endswith({
        'agy': ('/node_modules/@google/gemini-cli/dist/index.js', '/bin/gemini'),
        'claude': ('/node_modules/@anthropic-ai/claude-code/cli.js', '/bin/claude'),
        'codex': ('/node_modules/@openai/codex/bin/codex.js', '/bin/codex'),
        'dsh': ('/node_modules/@deepseek-ai/dsh/lib/bin.js', '/bin/dsh'),
        'hermes': (),
    }[editor])


def _editor_has_terminal_input(pid, terminal):
    if sys.platform != 'linux':
        return True
    # A background child of a noninteractive shell can share its group, but
    # Bash normally redirects that child's stdin away from the pane.
    try:
        stdin = os.stat(f'/proc/{pid}/fd/0')
        tty = os.stat('/dev/' + terminal)
    except OSError:
        return False
    return stat.S_ISCHR(stdin.st_mode) and stdin.st_rdev == tty.st_rdev


def confirm_wrapped_editor(view):
    # WSL can report the shell as the foreground group leader even while its
    # agent is reading. Require that editor in this pane's live foreground group.
    processes = {}
    children = {}
    for line in _process_columns('-axo', 'pid=,ppid=,pgid=,tpgid=,tty=,stat=,comm=').splitlines():
        parts = line.split(None, 6)
        if len(parts) != 7:
            continue
        try:
            pid, parent, group, foreground = map(int, parts[:4])
        except ValueError:
            continue
        tty, state, command = parts[4:]
        processes[pid] = (group, foreground, tty, state, Path(command).name.lower())
        children.setdefault(parent, []).append(pid)
    if view.process not in processes:
        return view
    _, foreground, tty, _, _ = processes[view.process]
    if foreground <= 0 or tty == '?':
        return view
    pending = children.get(view.process, [])[:]
    seen = {view.process}
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        pending.extend(children.get(pid, ()))
        group, active, terminal, state, executable = processes[pid]
        if (group == foreground == active and terminal == tty and state[0] not in 'TtXZ'
                and _editor_process(view.editor, pid, executable)
                and _editor_has_terminal_input(pid, tty)):
            return replace(view, wrapped_editor=True)
    return view


def _slash_selection(lines, plain, start, *, codex):
    """Read the picker directly above the editor and identify its active row."""
    selection = CODEX_SLASH_SELECTION if codex else CLAUDE_SLASH_SELECTION
    # Codex separates the inline picker from the editor with a blank row.
    # Claude uses the top border and can show options below the selected row.
    # In a narrow pane Claude wraps a long description onto indented rows
    # that carry no command name; they belong to the option above them.
    present = False
    for index in range(start - 2, max(-1, start - 24), -1):
        row = plain[index]
        match = selection.match(row)
        if match:
            highlight = lines[index].partition('›')[0]
            # Codex can draw the active row with an RGB background instead
            # of reverse video. In both cases the style precedes its marker.
            if not codex or REVERSE_VIDEO.search(highlight) or CODEX_PICKER_BACKGROUND.search(highlight):
                return True, match[1]
            return True, None
        if SLASH_OPTION.match(row):
            present = True
        elif codex or not SLASH_CONTINUATION.match(row):
            break
    return present, None


def _claude_slash_menu(lines, plain, start, cursor):
    border = plain[start - 1].strip() if start else ''
    if start < 2 or not (BORDER.fullmatch(border) or CLAUDE_NAMED_BORDER.fullmatch(border)):
        return False, None
    return _slash_selection(lines, plain, start, codex=False)


def _codex_slash_menu(lines, plain, start, cursor):
    if start < 2 or plain[start - 1].strip():
        return False, None
    return _slash_selection(lines, plain, start, codex=True)


def _dsh_slash_menu(lines, plain, start, cursor):
    # The command box ends immediately above the editor's top border.
    if start < 3 or not BORDER.fullmatch(plain[start - 2].strip()):
        return False, None
    selected = []
    for row in reversed(plain[max(0, start - 24):start - 2]):
        if DSH_COMMAND_MENU.fullmatch(row.rstrip()):
            return True, selected[0] if len(selected) == 1 else None
        if not row.strip().startswith('│'):
            break
        if match := DSH_COMMAND_SELECTED.match(row):
            selected.append('/' + match[1])
    return bool(selected), None


def _hermes_framed_top(plain, start):
    return (start >= 2 and BORDER.fullmatch(plain[start-1].strip())
            and HERMES_STATUS.match(plain[start-2].strip()))


def _hermes_slash_menu(lines, plain, start, cursor):
    """The compact menu sits directly below the composer without a rule."""
    first = cursor + 1
    lower_rule = first < len(plain) and BORDER.fullmatch(plain[first].strip())
    if lower_rule:
        first += 1
    elif not _hermes_framed_top(plain, start):
        return False, None
    if first >= len(lines) or not HERMES_MENU_STYLING.search(lines[first]):
        return False, None
    matches = []
    for row, styled in zip(plain[first:first + 12], lines[first:first + 12]):
        if not row.strip() or not HERMES_MENU_STYLING.search(styled):
            break
        matches.append(re.match(SLASH_NAME.pattern + r'(?=[ \t]|$)', row.strip()))
    if not lower_rule and (not matches or not matches[0]):
        return False, None
    # Native themes vary the highlight colors. A multi-row picker is
    # ambiguous without a proven highlight, so leave it in the terminal.
    return True, matches[0][0] if len(matches) == 1 and matches[0] else None


def _agy_slash_menu(lines, plain, start, cursor):
    rows = [row for row in plain[cursor + 2:cursor + 20] if row.strip()]
    if [row.strip() for row in rows[:2]] == ['No matches', AGY_COMMAND_HELP]:
        return False, None
    picked = []
    for row in rows:
        if row.strip() == AGY_COMMAND_HELP:
            return True, picked[0] if len(picked) == 1 else None
        if match := AGY_COMMAND_SELECTED.match(row):
            picked.append(match[1])
    return bool(picked), None


SLASH_PICKERS = {
    'claude': _claude_slash_menu,
    'codex': _codex_slash_menu,
    'dsh': _dsh_slash_menu,
    'hermes': _hermes_slash_menu,
    'agy': _agy_slash_menu,
}

def _slash_view(lines):
    """Identify a command's native view by its title and controls together."""
    rows = [row.strip() for row in lines if row.strip()]
    if not rows:
        return None
    footer = rows[-1]
    if footer == '←/→ to switch · Esc to close' and any(
            re.fullmatch(r'Help\s+General\s+Commands\s+Custom commands', row) for row in rows):
        return 'claude', '/help'
    if footer.endswith('Enter to save · Esc to cancel') and 'Select model' in rows:
        return 'claude', '/model'
    if footer == '↓ to navigate · ↑ to switch tabs · Esc to go back' and any(
            row.startswith('│ ⌕ Search settings…') for row in rows):
        return 'claude', '/config'
    if footer == 'enter select · esc back' and 'Select Model and Effort' in rows:
        return 'codex', '/model'
    if AGY_MODE.match(footer) or AGY_MODEL_FOOTER.fullmatch(footer) or AGY_MODE_ONLY.fullmatch(footer):
        controls = ' '.join(' '.join(rows[-3:-1]).split())
        if controls.endswith('Keyboard: ↑/↓ Navigate ←/→ Switch View esc Close') and any(
                re.fullmatch(r'Antigravity CLI\s+general\s+commands\s+shortcuts', row) for row in rows):
            return 'agy', '/help'
        if controls.endswith('Keyboard: ↑/↓ Navigate ←/→ Effort enter Select esc Go Back') and 'Switch Model' in rows:
            return 'agy', '/model'
        if controls.endswith('Keyboard: ↑/↓ Navigate enter Actions esc Exit') and 'MCP Servers' in rows:
            return 'agy', '/mcp'
    for index, title in enumerate(rows):
        if title == 'Model' and index + 1 < len(rows) and rows[index+1].startswith(
                'Tab / Shift+Tab providers · ↑/↓ model · Enter select · Esc cancel'):
            return 'dsh', '/model'
        if title.startswith('╭─ cli.tui.picker_title_provider ─') and any(
                row.startswith('│ cli.tui.picker_current_hint') for row in rows[index+1:index+4]):
            return 'hermes', '/model'
    return None


def _hermes_compact_hint(styled, draft):
    # The busy prompt itself may be italic. Check the style at the first
    # character of the placeholder, after any reset between glyph and text.
    if not draft:
        return False
    prefix, found, _ = styled.partition(draft)
    changes = ITALIC_CHANGE.findall(prefix)
    return bool(found and changes and changes[-1] == '3')


def _hermes_running(lines, plain, start):
    index = start - 2
    if index < 0:
        return False
    if HERMES_STATUS.match(plain[index].strip()):
        if '│ ⏱ ' in plain[index] or '· ⏱ ' in plain[index]:
            return True
        index -= 1
    # Hermes puts the live hint directly above its status bar and optional spacer.
    if index >= 0 and not plain[index].strip():
        index -= 1
    return (index >= 0 and '\x1b[3m' in lines[index]
            and HERMES_TOOL_PROGRESS.fullmatch(plain[index].rstrip()) is not None)


def _row_width(row):
    return sum(2 if east_asian_width(c) in ('F', 'W') else 1
               for c in row.rstrip() if category(c) not in ('Mn', 'Me', 'Cf'))


def _hermes_scrolled_draft(lines, plain, cursor, column):
    # Hermes keeps eight composer rows after scrolling the prompt out. The
    # compact layout omits the lower rule, leaving the status and upper rule.
    top = cursor - HERMES_EDITOR_ROWS
    if top < 1 or not HERMES_STATUS.match(plain[top-1].strip()) or not BORDER.fullmatch(plain[top].strip()):
        return None
    below = [row.strip() for row in plain[cursor+1:] if row.strip()]
    if (below and (len(below) != 1 or not BORDER.fullmatch(below[0]))
            or PROMPT.match(plain[top+1].rstrip())):
        return None
    if not plain[cursor].strip():
        # Prompt Toolkit can leave the caret on a new visual row when the
        # draft ends exactly at the right edge of the preceding row.
        if column or _row_width(plain[cursor-1]) != len(plain[top].strip()):
            return None
    draft = '\n'.join(row.strip() for row in plain[top+1:cursor+1]).strip()
    if draft:
        return draft, _hermes_running(lines, plain, top+1)
    return None


def frame(metadata, lines, pane):
    fields = metadata.split('\t')
    if (len(fields)!=9 or fields[2]!=pane or not re.fullmatch(r'%[0-9]+',pane)
            or not all(fields[i].isdigit() for i in (1,3,4,5,6))
            or fields[7] not in ('', '0', '1')):
        return None
    path=Path(fields[0])
    if not path.is_absolute():
        return None
    server,process,cursor,mode,column=map(int,(fields[1],*fields[3:7]))
    if not server or not process:
        return None
    base=(path,server,pane,process)
    bracketed = fields[7] == '1' if fields[7] else None
    command = fields[8].rsplit('/', 1)[-1].lower().lstrip('-').removesuffix('.exe')
    unavailable = Frame(*base, None, False, bracketed=bracketed, foreground_command=command)
    if mode or cursor>=len(lines):
        return unavailable
    # tmux adds a link target to the styled capture, separate from its visible text.
    lines=[OSC8.sub('',line) for line in lines]
    plain=[SGR.sub('',line) for line in lines]
    slash_view = _slash_view(plain)
    if bracketed is False:
        return replace(unavailable, slash_view=slash_view)
    if (cursor==0 and column==2 and plain[0].startswith('❯ ')
            and not any(row.strip() for row in plain[1:])
            and _hermes_compact_hint(lines[0], plain[0][2:].strip())):
        # During a Hermes resize the status and rules can disappear for a redraw.
        # Treat this as a reason to read again, without admitting input.
        return Frame(*base,None,False,redrawing=True)
    if scrolled_hermes := _hermes_scrolled_draft(lines, plain, cursor, column):
        draft, busy = scrolled_hermes
        return Frame(*base, draft, False, hermes=True, bracketed=bracketed,
                     foreground_command=command, scrolled=True, editor='hermes',
                     hermes_busy=busy, running=busy,
                     draft_continues=column < _row_width(plain[cursor]),
                     slash_view=slash_view)
    for start in range(cursor,-1,-1):
        line=plain[start].rstrip()
        if BORDER.fullmatch(line.strip()):
            break
        if CLAUDE_SCROLLED_BORDER.fullmatch(line.strip()):
            # A tall Claude draft scrolls inside its frame: the prompt glyph
            # and the first rows are hidden above this marker.
            tail=[row.strip() for row in plain[cursor+1:] if row.strip()]
            if start==cursor or '↑' not in line or not tail or not (
                    BORDER.fullmatch(tail[0]) or CLAUDE_SCROLLED_BORDER.fullmatch(tail[0])):
                break
            draft='\n'.join(row.strip() for row in plain[start+1:cursor+1]).strip()
            return Frame(*base, draft, False, bracketed=bracketed,
                         foreground_command=command, editor='claude', scrolled=True, slash_view=slash_view,
                         draft_continues='↓' in tail[0])
        match=PROMPT.match(line)
        if not match and '\x1b[38;5;145m' in lines[start].partition('❯')[2]:
            # The narrow dsh welcome screen can draw its hint flush against the glyph.
            match=DSH_COMPACT_WELCOME_PROMPT.match(line)
        if not match:
            continue
        prefix,glyph,first=match.groups()
        left=prefix.strip()
        top=plain[start-1].strip() if start>0 else ''
        upper=bool(BORDER.fullmatch(top) or
                   (glyph=='❯' and not left and CLAUDE_NAMED_BORDER.fullmatch(top)))
        tail=[row.strip() for row in plain[cursor+1:] if row.strip()]
        lower=bool(tail and BORDER.fullmatch(tail[0]))
        framed=upper and lower
        # Narrow Hermes hides the lower rule. Its status bar still sits
        # directly above the top rule, and its busy glyph stands alone.
        compact_hermes = (not lower and _hermes_framed_top(plain, start)
                          and (glyph == '❯' and left not in ('⌸', '│') or glyph == '☤' and not left)
                          and (not tail or _hermes_slash_menu(lines, plain, start, cursor)[0]))
        if glyph == '☤' and not compact_hermes:
            continue
        # The picker can be between the border and the status line. Offline
        # Antigravity can show the mode alone before it has loaded its model.
        agy = glyph == '>' and framed and any(
            AGY_MODE.match(row) or AGY_MODEL_FOOTER.fullmatch(row) or AGY_MODE_ONLY.fullmatch(row)
            for row in tail[1:20])
        boxed=glyph in ('❯','⌘') and left in ('⌸','│') and upper and (glyph!='⌘' or framed)
        if glyph=='⌘' and not boxed:
            continue
        if (glyph=='>' and not agy) or (left and not boxed and not compact_hermes and (glyph!='❯' or not framed)):
            continue
        if prefix and not left and glyph=='❯':
            # Claude indents its selected completion row above the editor.
            continue
        body=[first,*plain[start+1:cursor+1]]
        scrolled = False
        more_below = False
        if agy and not left and start < cursor and AGY_SCROLL_MARKER.fullmatch(lines[start].partition('>')[2]):
            # Antigravity draws the scroll indicator in place of the first row.
            body.pop(0)
            scrolled = True
            more_below = column < _row_width(plain[cursor])
        if glyph == '›':
            top_arrow = CODEX_SCROLL_ARROW.search(lines[start])
            last_arrow = CODEX_SCROLL_ARROW.search(lines[cursor])
            if top_arrow:
                body[0] = body[0].removesuffix(top_arrow[1]).rstrip()
                scrolled = top_arrow[1] == '↑'
                more_below = top_arrow[1] == '↓'
            if last_arrow and last_arrow[1] == '↓':
                body[-1] = body[-1].rstrip().removesuffix('↓').rstrip()
                more_below = True
        if boxed:
            body=[part.rstrip().removesuffix('⛶').removesuffix('│').rstrip() for part in body]
        draft='\n'.join(body).strip()
        if agy and scrolled and not draft:
            return replace(unavailable, slash_view=slash_view)
        if boxed and start==cursor and column<=len(prefix)+2:
            placeholder=draft.removesuffix('…')
            if (placeholder and DSH_PLACEHOLDER.startswith(placeholder)
                    and '\x1b[38;5;145m' in lines[start].partition('❯')[2]):
                draft=''
        above=plain[max(0,start-7):start]
        around=[*above,*plain[cursor+1:cursor+9]]
        hermes = compact_hermes or (glyph=='❯' and framed and not boxed and (
            left=='☤' or bool(left) or any('☤' in row for row in around)))
        hermes_busy = hermes and (left=='☤' or glyph=='☤')
        waiting=any(PASTING.match(row) for row in around)
        if glyph=='❯' and framed and not boxed and not hermes and cursor==start and draft.startswith('/'):
            # Claude renders an argument hint one cell after the caret when
            # a space follows the command. Only strip that styled suffix.
            if hint := CLAUDE_ARGUMENT_HINT.search(lines[start]):
                visible = SGR.sub('', lines[start][:hint.start()])
                if len(visible) == column + 1 and visible.endswith('  '):
                    typed = PROMPT.fullmatch(visible.rstrip())
                    if typed and SLASH_NAME.fullmatch(typed[3]):
                        draft = typed[3]
        # Recognize native hints only at the starting caret. Style matters for
        # rotating Hermes suggestions and distinguishes Codex hints from drafts.
        if cursor==start and column<=len(prefix)+2:
            styled=lines[start]
            # A queued turn leaves an empty Claude editor that draws this
            # dim hint, with the caret possibly styling its first letter.
            # After a turn Claude can also suggest a next prompt, drawn
            # entirely dim; a typed draft is never dim.
            claude_hint=(glyph=='❯' and framed and not boxed and not hermes and
                         ('\x1b[3m' in styled or (draft==CLAUDE_QUEUE_HINT and DIM.search(styled))
                          or bool(CLAUDE_SUGGESTION.match(styled.partition('❯')[2]))))
            hermes_hint = hermes and (not hermes_busy or HERMES_HINT.fullmatch(draft)) and (
                _hermes_compact_hint(styled, draft) if compact_hermes else '\x1b[3m' in styled)
            if (glyph=='›' and draft=='Ask Codex to do anything' and '\x1b[2m' in styled
                    or claude_hint or hermes_hint
                    or agy and draft in AGY_PLACEHOLDER):
                draft=''
        # A caret at the beginning of a multiline draft isn't an empty editor.
        # Check the lower edge or a recognized footer before accepting it.
        codex_queue_hint = glyph == '›' and bool(tail and tail[0].startswith(CODEX_QUEUE_HINT))
        footer=tail and (codex_queue_hint or tail[0].startswith(('? for shortcuts','← for agents','⏵','⏸','% context left','Context '))
                or re.match(r'gpt-\S+\s+(?:default|low|medium|high|xhigh|max|ultra)\b',tail[0],re.I))
        if not draft and tail and not (lower or footer or waiting):
            return replace(unavailable, slash_view=slash_view)
        menu=(start>=2 and upper and bool(re.match(r'^[ \t]+❯[ \t]+\S',plain[start-2])))
        if glyph=='›':
            previous_row=next((row.strip().lower() for row in reversed(above) if row.strip()), '')
            menu=previous_row.startswith(('enter/tab insert · esc close','enter insert · esc close'))
        editor = ('dsh' if boxed else 'hermes' if hermes else 'agy' if agy else
                  'codex' if glyph == '›' else 'claude' if upper or command=='claude' else None)
        sized_paste = None
        dsh_paste = None
        if editor == 'codex' and CODEX_PASTE_STYLE.search(lines[start]):
            sized_paste = CODEX_PASTE.fullmatch(''.join(draft.split()))
        elif editor == 'agy':
            sized_paste = AGY_PASTE.fullmatch(draft)
        elif editor == 'dsh' and framed and left == '⌸' and glyph == '❯' and first.strip() in ('', '⛶'):
            # Narrow dsh omits the preview but keeps the native styled pill
            # on its own row, directly above the otherwise empty caret row.
            if (cursor == start+2 and not plain[cursor].strip()
                    and DSH_PASTE_STYLE.search(lines[start+1])):
                dsh_paste = DSH_PASTE_COUNTS.fullmatch(draft)
        paste_chars = int(sized_paste[1]) if sized_paste else None
        paste_lines = None
        if dsh_paste:
            paste_lines, paste_chars = map(int, dsh_paste.groups())
        selected_command = None
        if editor is not None and (draft.startswith('/') or hermes):
            near_menu, selected_command = SLASH_PICKERS[editor](lines, plain, start, cursor)
            menu = menu or near_menu
            footer = footer or (compact_hermes and near_menu)
        if hermes and draft.startswith('/') and start == cursor:
            clean = SGR.sub('', HERMES_GHOST.sub('', lines[start]))
            if len(clean) == column and (typed := PROMPT.match(clean)):
                draft = typed[3].strip()
        # The welcome editor shows a single horizontal slice, and the main
        # editor shows at most five rows. Both can hide the start of a paste.
        dsh_clipped = boxed and framed and glyph=='❯' and (
            (left=='│' and start==cursor and line.endswith('  │')) or
            (left=='⌸' and cursor-start==4))
        running = (
            (hermes_busy and _hermes_running(lines, plain, start))
            or (editor == 'claude' and any(' · esc to interrupt' in row for row in tail[1:]))
            or (editor == 'codex' and any(CODEX_WORKING.match(row.strip()) for row in plain[max(0,start-16):start]))
            or (editor == 'dsh' and 'esc to interrupt' in tail[1:])
            or (editor == 'agy' and (
                any(AGY_WORKING.fullmatch(row.strip()) for row in above[-3:])
                or (not menu and any(row.startswith('esc to cancel') and
                    (AGY_MODE.match(row) or AGY_MODE_ONLY.fullmatch(row)) for row in tail[1:]))))
        )
        return Frame(*base, draft, waiting, menu or selected_command is not None,
                     bool(hermes), boxed, bracketed, command,
                     slash_picker=editor is not None, selected_command=selected_command,
                     dsh_clipped=dsh_clipped, hermes_busy=hermes_busy, editor=editor,
                     running=running, slash_view=slash_view, scrolled=scrolled,
                     draft_continues=more_below or bool(tail and not (lower or footer)),
                     paste_chars=paste_chars, codex_queue_hint=codex_queue_hint, paste_lines=paste_lines,
                     command_ends_at_cursor=(cursor == start and SLASH_NAME.fullmatch(draft) is not None
                                             and column == _row_width(line[:match.start(3)] + draft)))
    return replace(unavailable, slash_view=slash_view)


def bare_slash(text):
    value = text.strip()
    return value if value == '/' or SLASH_NAME.fullmatch(value) else None


def accepted_after_enter(before, after, text):
    if after.identity != before.identity:
        return False
    if after.slash_view is None or after.slash_view == before.slash_view:
        return (after.empty and after.editor == before.editor
                and not (after.redrawing or after.scrolled or after.draft_continues))
    return after.slash_view == (before.editor, bare_slash(text))


class SubmissionConfirmation:
    """Wait for the same editor to stay empty after Enter or Tab."""

    def __init__(self, before, text):
        self.before = before
        self.text = text
        self.clear_since = None

    def accepted(self, after):
        if not accepted_after_enter(self.before, after, self.text):
            self.clear_since = None
            return False
        if after.slash_view is not None and after.slash_view != self.before.slash_view:
            return True
        now = time.monotonic()
        if self.clear_since is None:
            self.clear_since = now
        # Some TUIs briefly clear the composer during a redraw and then
        # repaint the same unsent draft.
        return now - self.clear_since >= SUBMISSION_CLEAR_GRACE


def completion_problem(observed, text, *, operator=False):
    command = bare_slash(text)
    if (command is None or observed is None or observed.waiting
            or not observed.allows_paste(text, operator=operator) or observed.draft != command):
        return None
    if observed.selected_command is None:
        return 'completion-unverified'
    if command != observed.selected_command:
        return 'completion-mismatch'
    return None


def mismatched_command(observed, text, *, operator=False):
    return completion_problem(observed, text, operator=operator) == 'completion-mismatch'


def _picker_free_draft(observed, text, *, operator):
    return (observed is not None and observed.slash_picker and not observed.selected
            and not observed.waiting and not observed.scrolled and not observed.dsh_clipped
            and observed.allows_paste(text, operator=operator) and observed.draft == text
            and SLASH_NAME.fullmatch(text) is not None)


class SlashMenuWait:
    """Give the picker time to appear after the editor echoes a slash command."""

    def __init__(self, text, *, operator=False):
        self.text = text
        self.operator = operator
        self.missing_since = None
        self.seen_picker = False

    def ready(self, observed):
        if observed is not None and observed.selected and bare_slash(self.text) is not None:
            self.seen_picker = True
        if self.seen_picker or not _picker_free_draft(observed, self.text, operator=self.operator):
            self.missing_since = None
        else:
            now = time.monotonic()
            if self.missing_since is None:
                self.missing_since = now
            if now - self.missing_since >= SLASH_MENU_WAIT:
                return True
        return ready(observed, self.text, operator=self.operator)


def visible_cells(text):
    return sum(2 if east_asian_width(char) in ('F', 'W') else 1 for char in text if not char.isspace())


def _matches_paste_summary(view, text):
    if view.draft_continues:
        return False
    if view.paste_chars is not None:
        if view.editor == 'dsh':
            return (view.paste_lines == text.count('\n') + 1
                    and view.paste_chars == len(text.encode('utf-16-le')) // 2)
        return view.paste_chars == len(text)
    if view.editor == 'agy' and view.draft:
        # Antigravity reports lines for a paste containing newlines and
        # Unicode code points for a long single-line paste.
        marker = COLLAPSED.fullmatch(' '.join(view.draft.split()))
        return bool(marker and marker[1] and int(marker[1]) == text.count('\n') + 1)
    return False


def ready(observed, text, *, operator=False):
    if (observed is None or observed.draft is None or observed.waiting
            or not observed.allows_paste(text, operator=operator)):
        return False
    command = bare_slash(text)
    if command is not None or observed.selected:
        return command is not None and command!='/' and command==observed.draft==observed.selected_command
    shown = ''.join(observed.draft.split())
    expected = ''.join(text.split())
    if observed.scrolled:
        if observed.hermes or observed.editor == 'agy':
            return same_notice(observed, text)
        # Only the end of a tall draft is visible, so it must end the text.
        return not observed.draft_continues and len(shown)>=16 and expected.endswith(shown)
    if shown == expected:
        return True
    if _matches_paste_summary(observed, text):
        return True
    if observed.dsh_clipped and (operator or text.startswith('ORRERY Mail notification: ')):
        # Fullwidth and wide characters occupy two cells of the visible suffix.
        return visible_cells(shown) >= 24 and expected.endswith(shown)
    # Claude represents a pasted multiline or long prompt as this native
    # capsule. The caller required an empty editor before sending the paste.
    if observed.editor != 'agy' and COLLAPSED.fullmatch(observed.draft):
        return True
    if observed.hermes:
        # A narrow pane can wrap anywhere in the native paste card's path.
        marker=HERMES_PASTE.fullmatch(shown)
        return bool(marker and int(marker[2])==text.count('\n')+1)
    if observed.dsh:
        marker=DSH_PASTE.fullmatch(' '.join(observed.draft.split()))
        if marker:
            preview=marker[3].removesuffix('…').removesuffix('...').rstrip()
            return (bool(preview) and ' '.join(text.split()).startswith(preview)
                    and int(marker[1])==text.count('\n')+1
                    and int(marker[2])==len(text.encode('utf-16-le'))//2)
    return False


def try_lock(observed):
    import fcntl
    path=observed.socket.resolve(strict=True)
    socket=path.lstat()
    directory=path.parent.lstat()
    if (not stat.S_ISSOCK(socket.st_mode) or socket.st_uid!=os.getuid()
            or not stat.S_ISDIR(directory.st_mode) or directory.st_uid!=os.getuid()
            or directory.st_mode&0o077):
        raise OSError('unsafe tmux input lock location')
    key=hashlib.sha256(f'{socket.st_dev}:{socket.st_ino}:{observed.server}:{observed.pane}'.encode()).hexdigest()
    lock=path.parent/('.orrery-input-'+key)
    fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    try:
        info=os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or
                info.st_nlink!=1 or info.st_mode&0o077):
            raise OSError('unsafe tmux input lock')
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return None
        return fd
    except BaseException:
        os.close(fd)
        raise


def metadata_command(pane):
    return ['display-message','-p','-t',pane,METADATA]


def screen_command(pane):
    return ['capture-pane','-e','-p','-t',pane]


def capture(command,pane):
    result=command(*metadata_command(pane),';',*screen_command(pane))
    if result.returncode:
        return None
    metadata,separator,screen=result.stdout.partition('\n')
    return frame(metadata,screen.splitlines(),pane) if separator else None


def _notice_paste_digest(view, text):
    if view.editor in ('agy', 'codex', 'dsh') and text.startswith('ORRERY Mail notification: message from '):
        # Keep existing Codex and Antigravity receipts distinct from dsh.
        provider = '' if view.editor == 'codex' else f'{view.editor}\0'
        return hashlib.sha256(f'{provider}{view.process}\0{text}'.encode()).digest()
    return b''


def same_notice(view,text):
    """Compare an entire notice or a visible tail in a known, clipped editor."""
    if (view.editor not in ('claude','codex','dsh','hermes','agy')
            or view.waiting or view.selected or not view.draft
            or view.draft_continues
            or not text.startswith('ORRERY Mail notification: message from ')):
        return False
    if view.scrolled or view.dsh_clipped:
        remaining=text.rstrip()
        for line in reversed(view.draft.splitlines()):
            line=line.strip()
            if not remaining.endswith(line):
                return False
            remaining=remaining.removesuffix(line).rstrip()
        # The generic inbox hint is shared by many unrelated notifications.
        content_end=len(NOTICE_TRAILER.sub('',text.rstrip()))
        return bool(remaining and visible_cells(text[len(remaining):content_end])>=24)
    remaining=text
    for line in view.draft.splitlines():
        line=line.strip()
        if not remaining.startswith(line):
            return False
        remaining=remaining[len(line):].lstrip()
    return not remaining


def _discard_unsubmitted_slash(command, admit, pane, before, text):
    """Remove an owned slash draft whose full text and caret are still visible."""
    if not SLASH_NAME.fullmatch(text) or not admit():
        return
    view = capture(command, pane)
    if (view is None or view.identity != before.identity or view.editor != before.editor
            or view.draft != text or not view.command_ends_at_cursor or view.waiting
            or view.redrawing or view.running or view.scrolled or view.draft_continues
            or not view.allows_paste(text) or not admit()):
        return
    if command('send-keys', '-t', pane, *('BSpace',) * len(text)).returncode:
        return
    deadline = time.monotonic() + SUBMISSION_CLEAR_GRACE
    while time.monotonic() < deadline:
        view = capture(command, pane)
        if view is None or view.identity != before.identity or view.empty:
            return
        time.sleep(POLL)


def submit(command,admit,pane,text,*,deadline=None,on_wait=None,claim_handoff=None,discard_unsubmitted=False):
    """Watcher path. Refused means a prompt was never pasted."""
    end=time.monotonic()+TIMEOUT if deadline is None else deadline
    fd=None
    pasted=False

    def defer(status, reason):
        if on_wait is not None:
            on_wait(reason)
        return status

    def capture_input():
        view = capture(command,pane)
        return confirm_wrapped_editor(view) if needs_wrapped_editor(view, text) else view

    def capture_draft(identity):
        view = capture_input()
        if view is None or view.identity != identity or not view.redrawing:
            return view
        redraw_deadline = min(end, time.monotonic() + REDRAW_GRACE)
        while time.monotonic() < redraw_deadline:
            time.sleep(POLL)
            view = capture_input()
            if view is not None and view.identity != identity:
                return view
            if view is not None and not view.redrawing:
                return capture_input() if admit() else None
        return view

    try:
        current=capture(command,pane)
        if current is None:
            return defer('refused', 'input_not_found')
        fd=try_lock(current)
        if fd is None:
            return defer('refused', 'pane_locked')
        if not admit():
            return defer('refused', 'pane_changed')
        before=capture_draft(current.identity)
        if not before or before.identity!=current.identity:
            return defer('refused', 'pane_changed')
        if before.draft is None:
            return defer('refused', 'input_not_found')
        if before.waiting:
            return defer('refused', 'editor_waiting')
        resuming=not before.empty
        digest = _notice_paste_digest(before, text)

        def same_draft(view):
            if same_notice(view,text):
                return True
            # The capsule exposes only a count. A retry also needs the
            # digest saved under this pane's lock before our own paste.
            return (bool(digest) and view.editor == before.editor and _matches_paste_summary(view, text)
                    and os.pread(fd, len(digest)+1, 0) == digest)

        if resuming and not same_draft(before):
            return defer('refused', 'editor_not_empty')
        if not before.allows_paste(text):
            return defer('refused', 'paste_unavailable')
        if resuming and claim_handoff is not None and not claim_handoff(resuming=True):
            return defer('refused', 'pane_changed')
        name=None if resuming else 'orrery-submit-'+uuid.uuid4().hex
        pasted=resuming
        submit_key_attempted=False
        try:
            if name is not None:
                if command('load-buffer','-b',name,'-',input=text).returncode:
                    return defer('refused', 'load_buffer_failed')
                if time.monotonic()>=end:
                    return defer('refused', 'submission_deadline')
                if not admit():
                    return defer('refused', 'pane_changed')
                current=capture_draft(before.identity)
                if not current or current.identity!=before.identity:
                    return defer('refused', 'pane_changed')
                if not current.empty or not current.allows_paste(text):
                    return defer('refused', 'editor_changed')
                if claim_handoff is not None and not claim_handoff(resuming=False):
                    return defer('unknown', 'prior_delivery_unconfirmed')
                if digest:
                    os.ftruncate(fd, 0)
                    os.pwrite(fd, digest, 0)
                pasted=True  # A timeout after the command starts cannot prove absence.
                if command('paste-buffer','-r','-p','-d','-b',name,'-t',pane).returncode:
                    return defer('unknown', 'paste_failed')
            previous=None
            problem=None
            menu_wait = SlashMenuWait(text)
            def confirmed_draft(view):
                return (not resuming or same_draft(view)) and menu_wait.ready(view)
            while time.monotonic()<end:
                view=capture_input()
                if not view or view.identity!=before.identity:return defer('unknown', 'pane_changed')
                problem=completion_problem(view,text)
                choice=(view.draft,view.selected_command) if confirmed_draft(view) or problem=='completion-mismatch' else None
                if choice is not None and choice==previous:
                    if not admit():
                        return defer('unknown', 'pane_changed')
                    if time.monotonic()>=end:
                        return defer('unknown', 'submission_deadline')
                    view=capture_input()
                    if not view or view.identity!=before.identity:
                        return defer('unknown', 'pane_changed')
                    confirmed = confirmed_draft(view)
                    if (view.draft,view.selected_command)==choice:
                        if mismatched_command(view,text):
                            return defer('unknown', 'completion_mismatch')
                        if confirmed and time.monotonic()<end:
                            key = 'Tab' if view.codex_queue_hint else 'C-m'
                            submit_key_attempted=True
                            if command('send-keys','-t',pane,key).returncode:
                                return defer('unknown', 'enter_failed')
                            entered_from = view
                            break
                previous=choice
                time.sleep(POLL)
            else:
                reason = 'completion_unverified' if problem=='completion-unverified' else 'draft_not_confirmed'
                return defer('unknown', reason)
            confirmation = SubmissionConfirmation(entered_from, text)
            while time.monotonic()<end:
                view=capture(command,pane)
                if not view or view.identity!=before.identity:return defer('unknown', 'pane_changed')
                if confirmation.accepted(view):
                    if digest:
                        os.ftruncate(fd, 0)
                    return 'accepted'
                time.sleep(POLL)
            return defer('unknown', 'enter_not_confirmed')
        finally:
            if name is not None:
                if discard_unsubmitted and pasted and not submit_key_attempted:
                    try:
                        _discard_unsubmitted_slash(command, admit, pane, before, text)
                    except (OSError, RuntimeError, subprocess.TimeoutExpired):
                        pass
                try:command('delete-buffer','-b',name)
                except (OSError,RuntimeError,subprocess.TimeoutExpired):pass
    except (OSError,RuntimeError,subprocess.TimeoutExpired):
        return defer('unknown' if pasted else 'refused', 'terminal_unavailable')
    finally:
        if fd is not None:os.close(fd)

