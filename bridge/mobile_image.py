"""Small local image store for confirmed phone input, shared by macOS/Linux."""
from __future__ import annotations

import base64
import binascii
import io
import os
from pathlib import Path
import re
import secrets
import stat
import time
import warnings

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = ImageOps = None

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_JSON = 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 16384
IMAGE_NAME = re.compile(r'[a-f0-9]{32}\.(?:png|jpg)\Z')


def available():
    return Image is not None


def save_image(workspace, encoded):
    """Re-encode pixels, strip metadata, and return a random absolute path.

    No subprocess, registry, client filename, or caller-selected destination.
    DrvFS may inherit Windows ACLs instead of honoring POSIX mode bits; never
    claim that chmod makes a Windows-shared directory private.
    """
    if not available():
        raise ValueError('image_decoder_unavailable')
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError('image_too_large')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('image_invalid') from None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('image_too_large')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as original:
                if original.format not in {'JPEG', 'PNG', 'WEBP'} or getattr(original, 'n_frames', 1) != 1:
                    raise ValueError('image_format_unsupported')
                if original.width * original.height > 24_000_000:
                    raise ValueError('image_pixels_too_large')
                original.load()
                oriented = ImageOps.exif_transpose(original)
                mode = 'RGBA' if 'A' in oriented.getbands() or 'transparency' in original.info else 'RGB'
                pixels = oriented.convert(mode)
                clean = Image.frombytes(mode, pixels.size, pixels.tobytes())
                extension = 'jpg' if original.format == 'JPEG' else 'png'
                output = io.BytesIO()
                clean.save(output, 'JPEG' if extension == 'jpg' else 'PNG', **({'quality': 90} if extension == 'jpg' else {}))
    except ValueError:
        raise
    except Exception:
        raise ValueError('image_invalid') from None
    root = Path(workspace)
    if not root.is_absolute() or not root.is_dir():
        raise ValueError('image_workspace_unavailable')
    folder = root / '.orrery-input-images'
    folder.mkdir(mode=0o700, exist_ok=True)
    directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            ignore = os.open('.gitignore', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        except FileExistsError:
            ignore = os.open('.gitignore', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(ignore, 'rb') as stream:
                if stream.read(3) != b'*\n':
                    raise ValueError('image_folder_unavailable')
        else:
            with os.fdopen(ignore, 'wb') as stream:
                stream.write(b'*\n')
        count = 0
        for name in os.listdir(directory):
            if not IMAGE_NAME.fullmatch(name):
                continue
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                continue
            if info.st_mtime < time.time() - 7 * 86400:
                os.unlink(name, dir_fd=directory)
            else:
                count += 1
        if count >= 50:
            raise ValueError('image_folder_full')
        name = secrets.token_hex(16) + '.' + extension
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(output.getvalue())
        except BaseException:
            os.unlink(name, dir_fd=directory)
            raise
        return str(folder / name)
    finally:
        os.close(directory)
