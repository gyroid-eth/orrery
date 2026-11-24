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


METADATA = '#{socket_path}\t#{pid}\t#{pane_id}\t#{pane_pid}\t#{cursor_y}\t#{pane_in_mode}\t#{cursor_x}\t#{bracket_paste_flag}'
POLL = .06
TIMEOUT = 5.0
PROMPT = re.compile(r'^(\s*(?:(?:[⌸│]|[\w.-]+)\s+)?)([❯›>])(?:[ \u00a0]+|$)(.*)')
BORDER = re.compile(r'^[╭╰]?[─━]{8,}[╮╯]?$')
SGR = re.compile(r'\x1b\[[0-9;:]*m')
COLLAPSED = re.compile(r'\[Pasted text #\d+(?: \+\d+ lines?)?\]')
HERMES_PASTE = re.compile(r'\[Pasted text #(\d+): (\d+) lines → /.+/pastes/paste_\1_\d{6}\.txt\]')
PASTING = re.compile(r'^\s*(?:Pasting(?:…|\.\.\.)|Waiting for startup\b)', re.I)
AGY_MODE = re.compile(r'^(?:auto|plan|accept[- ]edits)\s+·\s+', re.I)
AGY_PLACEHOLDER = {
    'Auto mode: edits & safe commands auto-approved (shift+tab to cycle)',
}
DSH_PLACEHOLDER = 'Say something, or type / for commands…'
DSH_PASTE = re.compile(r'▸ (\d+) lines?・(\d+) chars?・(.+?)・hover to peek')



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

    @property
    def identity(self):
        return self.socket, self.server, self.pane, self.process

    @property
    def empty(self):
        return self.draft == '' and not self.waiting and not self.selected


def frame(metadata, lines, pane):
    fields = metadata.split('\t')
    if (len(fields)!=8 or fields[2]!=pane or not re.fullmatch(r'%[0-9]+',pane)
            or not all(fields[i].isdigit() for i in (1,3,4,5,6,7))):
        return None
    path=Path(fields[0])
    if not path.is_absolute():
        return None
    server,process,cursor,mode,column,bracketed=map(int,(fields[1],*fields[3:]))
    if not server or not process:
        return None
    base=(path,server,pane,process)
    if mode or bracketed!=1 or cursor>=len(lines):
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
        upper=start>0 and bool(BORDER.fullmatch(plain[start-1].strip()))
        tail=[row.strip() for row in plain[cursor+1:] if row.strip()]
        lower=bool(tail and BORDER.fullmatch(tail[0]))
        framed=upper and lower
        agy=glyph=='>' and framed and len(tail)>1 and bool(AGY_MODE.match(tail[1]))
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
            if (glyph=='›' and draft=='Ask Codex to do anything' and '\x1b[2m' in styled
                    or glyph=='❯' and framed and not boxed and '\x1b[3m' in styled
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
        return Frame(*base,draft,waiting,menu,bool(hermes),boxed)
    return Frame(*base,None,False)


def ready(observed, text):
    if observed is None or observed.draft is None or observed.waiting or observed.selected:
        return False
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
        if not before or before.identity!=current.identity or not before.empty:
            return 'refused'
        name='orrery-submit-'+uuid.uuid4().hex
        try:
            if command('load-buffer','-b',name,'-',input=text).returncode:
                return 'refused'
            if time.monotonic()>=end or not admit():
                return 'refused'
            current=capture(command,pane)
            if not current or current.identity!=before.identity or not current.empty:
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

