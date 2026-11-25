"""Pane input protocol shared with ORRERY Telemetry's pane_submission.py.

Use the live tmux socket's inode and pane ID, independently of the client,
working directory, or provider. A file contains no text or owner state.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import uuid
from dataclasses import dataclass


METADATA = ('#{socket_path}\t#{pid}\t#{pane_id}\t#{pane_pid}\t#{cursor_y}\t#{pane_in_mode}'
            '\t#{cursor_x}\t#{bracket_paste_flag}\t#{pane_current_command}')
POLL = .06
TIMEOUT = 5.0
SHELLS = frozenset({
    'ash', 'bash', 'busybox', 'cmd', 'csh', 'dash', 'elvish', 'fish', 'hush',
    'ksh', 'ksh93', 'mksh', 'nu', 'nushell', 'pdksh', 'powershell', 'pwsh',
    'sh', 'tcsh', 'xonsh', 'yash', 'zsh',
})
PROMPT = re.compile(r'^(\s*(?:(?:[⌸│☤]|[\w.-]+)\s+)?)([❯›>⌘])(?:[ \u00a0]+|$)(.*)')
BORDER = re.compile(r'^[╭╰]?[─━]{8,}[╮╯]?$')
CLAUDE_NAMED_BORDER = re.compile(r'^[─━]{8,}[ \t]+\S(?:.*\S)?[ \t]+[─━]+$')
CLAUDE_SCROLLED_BORDER = re.compile(
    r'^[─━]{2,}[ \t]+[↑↓][ \t]+\d+[ \t]+more(?:[ \t]+[─━]+(?:[ \t]+\S(?:.*\S)?[ \t]+[─━]+)?)?$')
SGR = re.compile(r'\x1b\[[0-9;:]*m')
DIM = re.compile(r'\x1b\[(?:[0-9]+;)*2(?:;[0-9]+)*m')
CLAUDE_QUEUE_HINT = 'Press up to edit queued messages'
CLAUDE_SUGGESTION = re.compile(r'^[  ]*\x1b\[(?:[0-9]+;)*2(?:;[0-9]+)*m[^\x1b]+(?:\x1b\[(?:0|22)?m[  ]*)?$')
COLLAPSED = re.compile(r'\[Pasted text #\d+(?: \+\d+ lines?)?\]')
HERMES_PASTE = re.compile(r'\[Pasted text #(\d+): (\d+) lines → /.+/pastes/paste_\1_\d{6}\.txt\]')
HERMES_HINT = re.compile(r'^msg=[\w-]+ · /queue · /bg · /steer · Ctrl\+C cancel$')
HERMES_GHOST = re.compile(r'\x1b\[38;5;241m[^\x1b]+\x1b\[39m[ \t]*$')
HERMES_MENU_STYLING = re.compile(r'\x1b\[(?:[0-9]+;)*48;[25];[0-9;]+m')
PASTING = re.compile(r'^\s*(?:Pasting(?:…|\.\.\.)|Waiting for startup\b)', re.I)
AGY_MODE = re.compile(r'^(?:auto|plan|accept[- ]edits)\s+·\s+', re.I)
AGY_MODE_ONLY = re.compile(r'^(?:(?:\? for shortcuts|esc to cancel)\s{2,})?(?:auto|plan|accept[- ]edits)$', re.I)
AGY_MODEL_FOOTER = re.compile(r'^Gemini(?:[ -][^·]+)?\s+·\s+(?:low|medium|high)$', re.I)
AGY_PLACEHOLDER = {
    'Auto mode: edits & safe commands auto-approved (shift+tab to cycle)',
    'Plan mode: research & plan only (shift+tab to cycle)',
}
DSH_PLACEHOLDER = 'Say something, or type / for commands…'
DSH_PASTE = re.compile(r'▸ (\d+) lines?・(\d+) chars?・(.+?)・hover to peek')
SLASH_NAME = re.compile(r'/[\w.:-]+')
SLASH_OPTION = re.compile(r'^[ \t]{2,}' + SLASH_NAME.pattern + r'(?=[ \t]|$)')
CLAUDE_SLASH_SELECTION = re.compile(r'^[ \t]+❯[ \t]+(' + SLASH_NAME.pattern + r')(?=[ \t]|$)')
CODEX_SLASH_SELECTION = re.compile(r'^›[ \t]+(' + SLASH_NAME.pattern + r')(?=[ \t]|$)')
SLASH_CONTINUATION = re.compile(r'^[ \t]{8,}[^ \t/❯]')
REVERSE_VIDEO = re.compile(r'\x1b\[(?:[0-9]+;)*7(?:;[0-9]+)*m')
DSH_COMMAND_MENU = re.compile(r'^\s*╭─ commands · \d+ items? ─+╮$')
DSH_COMMAND_SELECTED = re.compile(r'^\s*│\s+❯\s+([\w.:-]+)(?=\s|│|$)')
AGY_COMMAND_SELECTED = re.compile(r'^>\s+(' + SLASH_NAME.pattern + r')(?=[ \t]|$)')


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

    @property
    def identity(self):
        return self.socket, self.server, self.pane, self.process

    @property
    def empty(self):
        return self.draft == '' and not self.waiting and not self.selected

    def allows_paste(self, text):
        if self.hermes_busy:
            # Enter can interrupt a running turn depending on Hermes's mode.
            # Its idle editor is required before starting a paste.
            return False
        if self.bracketed is not None:
            return self.bracketed
        # Before tmux 3.7, paste-buffer -p can see the mode but formats
        # cannot. Preserve TUI paste on those releases. In a shell, LF and
        # other control characters may be acted on before the draft is visible.
        return bool(self.foreground_command) and (
            self.foreground_command not in SHELLS
            or not re.search(r'[\x00-\x1f\x7f-\x9f]', text))


def _slash_selection(lines, plain, start, *, codex):
    """Read the active row from the picker directly above the editor."""
    selection = CODEX_SLASH_SELECTION if codex else CLAUDE_SLASH_SELECTION
    # Codex separates the inline picker from the editor with a blank row.
    # Claude uses the top border and can show options below the selected row.
    # In a narrow pane Claude wraps a long description onto indented rows
    # that carry no command name; they belong to the option above them.
    for index in range(start - 2, max(-1, start - 24), -1):
        row = plain[index]
        match = selection.match(row)
        if match:
            if not codex or REVERSE_VIDEO.search(lines[index].partition('›')[0]):
                return match[1]
            break
        if not (SLASH_OPTION.match(row) or not codex and SLASH_CONTINUATION.match(row)):
            break
    return None


def _claude_slash_menu(lines, plain, start, cursor):
    border = plain[start - 1].strip() if start else ''
    if start < 2 or not (BORDER.fullmatch(border) or CLAUDE_NAMED_BORDER.fullmatch(border)):
        return False, None
    return False, _slash_selection(lines, plain, start, codex=False)


def _codex_slash_menu(lines, plain, start, cursor):
    if start < 2 or plain[start - 1].strip():
        return False, None
    return False, _slash_selection(lines, plain, start, codex=True)


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
    return False, None


def _hermes_slash_menu(lines, plain, start, cursor):
    """The menu below the lower border shows one completion per row."""
    if cursor + 1 >= len(plain) or not BORDER.fullmatch(plain[cursor + 1].strip()):
        return False, None
    if cursor + 2 >= len(lines) or not HERMES_MENU_STYLING.search(lines[cursor + 2]):
        return False, None
    matches = []
    for row, styled in zip(plain[cursor + 2:cursor + 14], lines[cursor + 2:cursor + 14]):
        if not row.strip() or not HERMES_MENU_STYLING.search(styled):
            break
        matches.append(re.match(SLASH_NAME.pattern + r'(?=[ \t]|$)', row.strip()))
    # Native themes vary the highlight colors. A multi-row picker is
    # ambiguous without a proven highlight, so leave it in the terminal.
    return True, matches[0][0] if len(matches) == 1 and matches[0] else None


def _agy_slash_menu(lines, plain, start, cursor):
    picked = []
    for row in plain[cursor + 2:cursor + 20]:
        if row.strip() == '↑/↓ Navigate · enter Select · tab Complete':
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
    if mode or bracketed is False or cursor>=len(lines):
        return Frame(*base,None,False)
    plain=[SGR.sub('',line) for line in lines]
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
                         foreground_command=command, scrolled=True)
        match=PROMPT.match(line)
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
        # The picker can be between the border and the status line. Offline
        # Antigravity can show the mode alone before it has loaded its model.
        agy = glyph == '>' and framed and any(
            AGY_MODE.match(row) or AGY_MODEL_FOOTER.fullmatch(row) or AGY_MODE_ONLY.fullmatch(row)
            for row in tail[1:20])
        boxed=glyph in ('❯','⌘') and left in ('⌸','│') and upper and (glyph!='⌘' or framed)
        if glyph=='⌘' and not boxed:
            continue
        if (glyph=='>' and not agy) or (left and not boxed and (glyph!='❯' or not framed)):
            continue
        if prefix and not left and glyph=='❯':
            # Claude indents its selected completion row above the editor.
            continue
        body=[first,*plain[start+1:cursor+1]]
        if boxed:
            body=[part.rstrip().removesuffix('⛶').removesuffix('│').rstrip() for part in body]
        draft='\n'.join(body).strip()
        above=plain[max(0,start-7):start]
        around=[*above,*plain[cursor+1:cursor+9]]
        hermes = glyph=='❯' and framed and not boxed and (
            left=='☤' or bool(left) or any('☤' in row for row in around))
        hermes_busy = hermes and left=='☤'
        waiting=any(PASTING.match(row) for row in around)
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
            hermes_hint = hermes and '\x1b[3m' in styled and (
                not hermes_busy or HERMES_HINT.fullmatch(draft))
            if (glyph=='›' and draft=='Ask Codex to do anything' and '\x1b[2m' in styled
                    or claude_hint or hermes_hint
                    or boxed and draft==DSH_PLACEHOLDER and '\x1b[38;5;145m' in styled
                    or agy and draft in AGY_PLACEHOLDER):
                draft=''
        # A caret at the beginning of a multiline draft isn't an empty editor.
        # Check the lower edge or a recognized footer before accepting it.
        footer=tail and (tail[0].startswith(('? for shortcuts','← for agents','⏵','⏸','% context left','Context '))
                or re.match(r'gpt-\S+\s+(?:default|low|medium|high|xhigh|max|ultra)\b',tail[0],re.I))
        if not draft and tail and not (lower or footer or waiting):
            return Frame(*base,None,False)
        menu=(start>=2 and upper and bool(re.match(r'^[ \t]+❯[ \t]+\S',plain[start-2])))
        if glyph=='›':
            previous_row=next((row.strip().lower() for row in reversed(above) if row.strip()), '')
            menu=previous_row.startswith(('enter/tab insert · esc close','enter insert · esc close'))
        editor = ('dsh' if boxed else 'hermes' if hermes else 'agy' if agy else
                  'codex' if glyph == '›' else 'claude' if upper or command=='claude' else None)
        selected_command = None
        if editor is not None and (draft.startswith('/') or hermes):
            near_menu, selected_command = SLASH_PICKERS[editor](lines, plain, start, cursor)
            menu = menu or near_menu
        if hermes and draft.startswith('/') and start == cursor:
            clean = SGR.sub('', HERMES_GHOST.sub('', lines[start]))
            if len(clean) == column and (typed := PROMPT.match(clean)):
                draft = typed[3].strip()
        # The welcome editor shows a single horizontal slice, and the main
        # editor shows at most five rows. Both can hide the start of a paste.
        dsh_clipped = boxed and framed and glyph=='❯' and (
            (left=='│' and start==cursor and line.endswith('  │')) or
            (left=='⌸' and cursor-start==4))
        return Frame(*base, draft, waiting, menu or selected_command is not None,
                     bool(hermes), boxed, bracketed, command,
                     slash_picker=editor is not None, selected_command=selected_command,
                     dsh_clipped=dsh_clipped, hermes_busy=hermes_busy)
    return Frame(*base,None,False)


def bare_slash(text):
    value = text.strip()
    return value if value == '/' or SLASH_NAME.fullmatch(value) else None


def completion_problem(observed, text):
    command = bare_slash(text)
    if (command is None or observed is None or observed.waiting
            or not observed.allows_paste(text) or observed.draft != command):
        return None
    if observed.selected_command is None:
        return 'completion-unverified'
    if command != observed.selected_command:
        return 'completion-mismatch'
    return None


def mismatched_command(observed, text):
    return completion_problem(observed, text) == 'completion-mismatch'


def ready(observed, text):
    if (observed is None or observed.draft is None or observed.waiting
            or not observed.allows_paste(text)):
        return False
    command = bare_slash(text)
    if command is not None or observed.selected:
        # Even without a known picker, the draft can appear before it opens.
        return command is not None and command!='/' and command==observed.draft==observed.selected_command
    if observed.scrolled:
        # Only the end of a tall draft is visible, so it must end the text.
        shown=''.join(observed.draft.split())
        return len(shown)>=16 and ''.join(text.split()).endswith(shown)
    if ''.join(observed.draft.split())==''.join(text.split()):
        return True
    if observed.dsh_clipped and text.startswith('ORRERY Mail notification: '):
        shown = ''.join(observed.draft.split())
        return len(shown) >= 24 and ''.join(text.split()).endswith(shown)
    # Claude represents a pasted multiline or long prompt as this native
    # capsule. The caller required an empty editor before sending the paste.
    if COLLAPSED.fullmatch(observed.draft):
        return True
    compact=' '.join(observed.draft.split())
    if observed.hermes:
        marker=HERMES_PASTE.fullmatch(compact)
        return bool(marker and int(marker[2])==text.count('\n')+1)
    if observed.dsh:
        marker=DSH_PASTE.fullmatch(compact)
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


def submit(command,admit,pane,text,*,deadline=None,on_wait=None):
    """Watcher path. Refused means a prompt was never pasted."""
    end=time.monotonic()+TIMEOUT if deadline is None else deadline
    fd=None
    pasted=False

    def defer(status, reason):
        if on_wait is not None:
            on_wait(reason)
        return status

    try:
        current=capture(command,pane)
        if current is None:
            return defer('refused', 'input_not_found')
        fd=try_lock(current)
        if fd is None:
            return defer('refused', 'pane_locked')
        if not admit():
            return defer('refused', 'pane_changed')
        before=capture(command,pane)
        if not before or before.identity!=current.identity:
            return defer('refused', 'pane_changed')
        if before.draft is None:
            return defer('refused', 'input_not_found')
        if before.waiting:
            return defer('refused', 'editor_waiting')
        if not before.empty:
            return defer('refused', 'editor_not_empty')
        if not before.allows_paste(text):
            return defer('refused', 'paste_unavailable')
        name='orrery-submit-'+uuid.uuid4().hex
        try:
            if command('load-buffer','-b',name,'-',input=text).returncode:
                return defer('refused', 'load_buffer_failed')
            if time.monotonic()>=end:
                return defer('refused', 'submission_deadline')
            if not admit():
                return defer('refused', 'pane_changed')
            current=capture(command,pane)
            if not current or current.identity!=before.identity:
                return defer('refused', 'pane_changed')
            if not current.empty or not current.allows_paste(text):
                return defer('refused', 'editor_changed')
            pasted=True  # A timeout after the command starts cannot prove absence.
            if command('paste-buffer','-r','-p','-d','-b',name,'-t',pane).returncode:
                return defer('unknown', 'paste_failed')
            previous=None
            problem=None
            while time.monotonic()<end:
                view=capture(command,pane)
                if not view or view.identity!=before.identity:return defer('unknown', 'pane_changed')
                problem=completion_problem(view,text)
                choice=(view.draft,view.selected_command) if ready(view,text) or problem=='completion-mismatch' else None
                if choice is not None and choice==previous:
                    if not admit():
                        return defer('unknown', 'pane_changed')
                    if time.monotonic()>=end:
                        return defer('unknown', 'submission_deadline')
                    view=capture(command,pane)
                    if view and view.identity==before.identity and (view.draft,view.selected_command)==choice:
                        if mismatched_command(view,text):
                            return defer('unknown', 'completion_mismatch')
                        if ready(view,text) and time.monotonic()<end:
                            if command('send-keys','-t',pane,'C-m').returncode:
                                return defer('unknown', 'enter_failed')
                            break
                previous=choice
                time.sleep(POLL)
            else:
                reason = 'completion_unverified' if problem=='completion-unverified' else 'draft_not_confirmed'
                return defer('unknown', reason)
            while time.monotonic()<end:
                view=capture(command,pane)
                if not view or view.identity!=before.identity:return defer('unknown', 'pane_changed')
                if view.empty:return 'accepted'
                time.sleep(POLL)
            return defer('unknown', 'enter_not_confirmed')
        finally:
            try:command('delete-buffer','-b',name)
            except (OSError,RuntimeError,subprocess.TimeoutExpired):pass
    except (OSError,RuntimeError,subprocess.TimeoutExpired):
        return defer('unknown' if pasted else 'refused', 'terminal_unavailable')
    finally:
        if fd is not None:os.close(fd)

