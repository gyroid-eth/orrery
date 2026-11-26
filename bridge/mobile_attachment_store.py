"""Write private, bounded phone attachments inside an already bound workspace."""

import fcntl
import logging
import os
from pathlib import Path
import re
import secrets
import stat
import time


IMAGE_FORMATS = frozenset({'jpg', 'png'})
FILE_SUFFIX = r'[a-z0-9]{1,32}'
FILE_FORMAT = re.compile(rf'(?:{FILE_SUFFIX})?\Z')
ATTACHMENT_NAME = re.compile(rf'[a-f0-9]{{32}}(?:\.({FILE_SUFFIX}))?\Z')
DIRECTORIES = {'image': '.orrery-input-images', 'file': '.orrery-input-files'}
MAX_STORED_ATTACHMENTS = 1000
NO_FOLLOW = os.O_NOFOLLOW | os.O_NONBLOCK


def _ignore(directory, kind):
    try:
        fd = os.open('.gitignore', os.O_WRONLY | os.O_CREAT | os.O_EXCL | NO_FOLLOW,
                     0o600, dir_fd=directory)
    except FileExistsError:
        fd = os.open('.gitignore', os.O_RDONLY | NO_FOLLOW, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or stream.read(3) != b'*\n':
                raise ValueError(kind + '_folder_unavailable')
    else:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(b'*\n')


def attachment_label(value):
    if not isinstance(value, str):
        return ''
    return re.sub(r'[\x00-\x1f\x7f-\x9f]', ' ', value.replace('\\', '/').rsplit('/', 1)[-1]).strip()[:160]


def valid_extension(kind, extension):
    return isinstance(extension, str) and (
        extension in IMAGE_FORMATS if kind == 'image' else FILE_FORMAT.fullmatch(extension) is not None
    )


def _remove_stored(directory, names):
    removed = 0
    for name in names:
        try:
            if not stat.S_ISREG(os.stat(name, dir_fd=directory, follow_symlinks=False).st_mode):
                continue
            os.unlink(name, dir_fd=directory)
        except FileNotFoundError:
            continue
        removed += 1
        label = name + '.label'
        try:
            if stat.S_ISREG(os.stat(label, dir_fd=directory, follow_symlinks=False).st_mode):
                os.unlink(label, dir_fd=directory)
        except FileNotFoundError:
            pass
    return removed


def store(workspace, kind, extension, data, *, label=None):
    root = Path(workspace)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError(kind + '_workspace_unavailable')
    if not valid_extension(kind, extension):
        raise ValueError(kind + '_format_invalid')
    folder = DIRECTORIES[kind]
    workspace_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            os.mkdir(folder, mode=0o700, dir_fd=workspace_fd)
        except FileExistsError:
            pass
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=workspace_fd)
    finally:
        os.close(workspace_fd)
    try:
        lock = os.open('.lock', os.O_RDWR | os.O_CREAT | NO_FOLLOW, 0o600, dir_fd=directory)
        try:
            if not stat.S_ISREG(os.fstat(lock).st_mode):
                raise ValueError(kind + '_folder_unavailable')
            fcntl.flock(lock, fcntl.LOCK_EX)
            _ignore(directory, kind)
            cutoff = time.time() - 7 * 86400
            expired, recent = [], []
            for name in os.listdir(directory):
                match = ATTACHMENT_NAME.fullmatch(name)
                if not match or not valid_extension(kind, match[1] or ''):
                    continue
                try:
                    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        continue
                    if info.st_mtime < cutoff:
                        expired.append(name)
                    else:
                        recent.append((info.st_mtime_ns, name))
                except FileNotFoundError:
                    continue
            name = secrets.token_hex(16) + ('.' + extension if extension else '')
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NO_FOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                if cleaned := attachment_label(label):
                    label_fd = os.open(name+'.label', os.O_WRONLY | os.O_CREAT | os.O_EXCL | NO_FOLLOW,
                                       0o600, dir_fd=directory)
                    with os.fdopen(label_fd, 'w', encoding='utf-8') as stream:
                        stream.write(cleaned)
                # Save the new input before deleting old ones. The lock keeps
                # concurrent uploads within the same retention limit.
                excess = len(recent) + 1 - MAX_STORED_ATTACHMENTS
                oldest = (name for _, name in sorted(recent)[:excess]) if excess > 0 else ()
                expired_count = _remove_stored(directory, expired)
                evicted_count = _remove_stored(directory, oldest)
                if expired_count or evicted_count:
                    logging.warning("ORRERY attachment retention: kind=%s expired=%d evicted=%d",
                                    kind, expired_count, evicted_count)
            except BaseException:
                os.unlink(name, dir_fd=directory)
                try:
                    os.unlink(name+'.label', dir_fd=directory)
                except FileNotFoundError:
                    pass
                raise
            return str(root / folder / name)
        finally:
            os.close(lock)
    finally:
        os.close(directory)
