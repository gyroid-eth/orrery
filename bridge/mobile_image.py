"""Small local image store for confirmed phone input, shared by macOS/Linux."""
from __future__ import annotations

import base64
import binascii
import io
import warnings
from conversation_images import remember_saved
from mobile_attachment_store import store

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = ImageOps = None

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_JSON = 4 * ((MAX_IMAGE_BYTES + 2) // 3) + 16384


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
    path = store(workspace, 'image', extension, output.getvalue())
    remember_saved(path)
    return path
