"""Write private, bounded phone attachments inside an already bound workspace."""

import fcntl
import os
from pathlib import Path
import re
import secrets
import stat
import time


FORMATS = {
    'image': frozenset({'jpg', 'png'}),
    'file': frozenset({'pdf', 'txt', 'md', 'csv', 'json'}),
}
DIRECTORIES = {'image': '.orrery-input-images', 'file': '.orrery-input-files'}
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


def store(workspace, kind, extension, data):
    root = Path(workspace)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError(kind + '_workspace_unavailable')
    if extension not in FORMATS[kind]:
        raise ValueError(kind + '_format_unsupported')
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
            count = 0
            for name in os.listdir(directory):
                stem, dot, suffix = name.rpartition('.')
                if not dot or suffix not in FORMATS[kind] or not re.fullmatch(r'[a-f0-9]{32}', stem):
                    continue
                try:
                    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        continue
                    if info.st_mtime < cutoff:
                        os.unlink(name, dir_fd=directory)
                    else:
                        count += 1
                except FileNotFoundError:
                    continue
            if count >= 50:
                raise ValueError(kind + '_folder_full')
            name = secrets.token_hex(16) + '.' + extension
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NO_FOLLOW, 0o600, dir_fd=directory)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
            except BaseException:
                os.unlink(name, dir_fd=directory)
                raise
            return str(root / folder / name)
        finally:
            os.close(lock)
    finally:
        os.close(directory)
