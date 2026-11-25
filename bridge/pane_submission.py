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
PROMPT = re.compile(r'^(\s*(?:(?:[⌸│]|[\w.-]+)\s+)?)([❯›>])(?:[ \u00a0]+|$)(.*)')
BORDER = re.compile(r'^[╭╰]?[─━]{8,}[╮╯]?$')
CLAUDE_NAMED_BORDER = re.compile(r'^[─━]{8,}[ \t]+\S(?:.*\S)?[ \t]+[─━]+$')
SGR = re.compile(r'\x1b\[[0-9;:]*m')
DIM = re.compile(r'\x1b\[(?:[0-9]+;)*2(?:;[0-9]+)*m')
CLAUDE_QUEUE_HINT = 'Press up to edit queued messages'
COLLAPSED = re.compile(r'\[Pasted text #\d+(?: \+\d+ lines?)?\]')
HERMES_PASTE = re.compile(r'\[Pasted text #(\d+): (\d+) lines → /.+/pastes/paste_\1_\d{6}\.txt\]')
PASTING = re.compile(r'^\s*(?:Pasting(?:…|\.\.\.)|Waiting for startup\b)', re.I)
AGY_MODE = re.compile(r'^(?:auto|plan|accept[- ]edits)\s+·\s+', re.I)
AGY_MODEL_FOOTER = re.compile(r'^Gemini(?:[ -][^·]+)?\s+·\s+(?:low|medium|high)$', re.I)
AGY_PLACEHOLDER = {
    'Auto mode: edits & safe commands auto-approved (shift+tab to cycle)',
}
DSH_PLACEHOLDER = 'Say something, or type / for commands…'
DSH_PASTE = re.compile(r'▸ (\d+) lines?・(\d+) chars?・(.+?)・hover to peek')
SLASH_NAME = re.compile(r'/[\w.:-]+')
SLASH_OPTION = re.compile(r'^[ \t]{2,}' + SLASH_NAME.pattern + r'(?=[ \t]|$)')
CLAUDE_SLASH_SELECTION = re.compile(r'^[ \t]+❯[ \t]+(' + SLASH_NAME.pattern + r')(?=[ \t]|$)')
CODEX_SLASH_SELECTION = re.compile(r'^›[ \t]+(' + SLASH_NAME.pattern + r')(?=[ \t]|$)')
REVERSE_VIDEO = re.compile(r'\x1b\[(?:[0-9]+;)*7(?:;[0-9]+)*m')


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

    @property
    def identity(self):
        return self.socket, self.server, self.pane, self.process

    @property
    def empty(self):
        return self.draft == '' and not self.waiting and not self.selected

    def allows_paste(self, text):
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
    for index in range(start - 2, max(-1, start - 12), -1):
        row = plain[index]
        match = selection.match(row)
        if match:
            if not codex or REVERSE_VIDEO.search(lines[index].partition('›')[0]):
                return match[1]
            break
        if not SLASH_OPTION.match(row):
            break
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
    if mode or bracketed is False or cursor>=len(lines):
        return Frame(*base,None,False)
    plain=[SGR.sub('',line) for line in lines]
    for start in range(cursor,-1,-1):
        line=plain[start].rstrip()
        if BORDER.fullmatch(line.strip()):
            break
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
        # Antigravity can omit cycle_mode from its status-line payload, leaving
        # the model and effort under the same framed editor.
        agy = glyph == '>' and framed and len(tail) > 1 and bool(
            AGY_MODE.match(tail[1]) or AGY_MODEL_FOOTER.fullmatch(tail[1]))
        boxed=glyph=='❯' and left in ('⌸','│') and upper
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
        waiting=any(PASTING.match(row) for row in around)
        # Recognize native hints only at the starting caret. Style matters for
        # rotating Hermes suggestions and distinguishes Codex hints from drafts.
        if cursor==start and column<=len(prefix)+2:
            styled=lines[start]
            # A queued turn leaves an empty Claude editor that draws this
            # dim hint, with the caret possibly styling its first letter.
            claude_hint=(glyph=='❯' and framed and not boxed and
                         ('\x1b[3m' in styled or (draft==CLAUDE_QUEUE_HINT and DIM.search(styled))))
            if (glyph=='›' and draft=='Ask Codex to do anything' and '\x1b[2m' in styled
                    or claude_hint
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
        hermes=glyph=='❯' and framed and not boxed and (left or any('☤' in row for row in around))
        codex = glyph == '›'
        slash_picker = codex or (glyph == '❯' and not boxed and not hermes
                                 and (upper or command == 'claude'))
        selected_command = None
        if draft.startswith('/') and slash_picker and start >= 2:
            if (codex and not plain[start-1].strip()) or (not codex and upper):
                selected_command = _slash_selection(lines, plain, start, codex=codex)
        return Frame(*base, draft, waiting, menu or selected_command is not None,
                     bool(hermes), boxed, bracketed, command,
                     slash_picker=slash_picker, selected_command=selected_command)
    return Frame(*base,None,False)


def mismatched_command(observed, text):
    command = text.strip()
    return bool(observed and not observed.waiting and observed.allows_paste(text)
                and observed.draft == command and observed.selected_command
                and SLASH_NAME.fullmatch(command) and observed.selected_command != command)


def ready(observed, text):
    if (observed is None or observed.draft is None or observed.waiting
            or not observed.allows_paste(text)):
        return False
    if observed.selected or (observed.slash_picker and (text == '/' or SLASH_NAME.fullmatch(text))):
        # A bare slash command can open its picker after the text itself
        # appears. Require a named selection and compare the full draft.
        command = text.strip()
        return (observed.selected_command == command == observed.draft
                and SLASH_NAME.fullmatch(command) is not None)
    if ''.join(observed.draft.split())==''.join(text.split()):
        return True
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


def submit(command,admit,pane,text,*,deadline=None):
    """Watcher path. Refused means a prompt was never pasted."""
    end=time.monotonic()+TIMEOUT if deadline is None else deadline
    fd=None
    pasted=False
    try:
        current=capture(command,pane)
        if current is None:
            return 'refused'
        fd=try_lock(current)
        if fd is None or not admit():
            return 'refused'
        before=capture(command,pane)
        if not before or before.identity!=current.identity or not before.empty or not before.allows_paste(text):
            return 'refused'
        name='orrery-submit-'+uuid.uuid4().hex
        try:
            if command('load-buffer','-b',name,'-',input=text).returncode:
                return 'refused'
            if time.monotonic()>=end or not admit():
                return 'refused'
            current=capture(command,pane)
            if not current or current.identity!=before.identity or not current.empty or not current.allows_paste(text):
                return 'refused'
            pasted=True  # A timeout after the command starts cannot prove absence.
            if command('paste-buffer','-r','-p','-d','-b',name,'-t',pane).returncode:
                return 'unknown'
            previous=None
            while time.monotonic()<end:
                view=capture(command,pane)
                if not view or view.identity!=before.identity:return 'unknown'
                draft=view.draft if ready(view,text) else None
                if draft is not None and draft==previous:
                    if not admit() or time.monotonic()>=end:return 'unknown'
                    view=capture(command,pane)
                    if view and view.identity==before.identity and ready(view,text):
                        if command('send-keys','-t',pane,'C-m').returncode:
                            return 'unknown'
                        break
                previous=draft
                time.sleep(POLL)
            else:return 'unknown'
            while time.monotonic()<end:
                view=capture(command,pane)
                if not view or view.identity!=before.identity:return 'unknown'
                if view.empty:return 'accepted'
                time.sleep(POLL)
            return 'unknown'
        finally:
            try:command('delete-buffer','-b',name)
            except (OSError,RuntimeError,subprocess.TimeoutExpired):pass
    except (OSError,RuntimeError,subprocess.TimeoutExpired):
        return 'unknown' if pasted else 'refused'
    finally:
        if fd is not None:os.close(fd)

