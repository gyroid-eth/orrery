"""Accept selected documents without opening or interpreting their contents."""

import base64
import binascii
import re

from mobile_attachment_store import FORMATS, store


MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILE_BASE64 = 4 * ((MAX_FILE_BYTES + 2) // 3)
MAX_FILE_JSON = MAX_FILE_BASE64 + 16384


def save_file(workspace, upload):
    if not isinstance(upload, dict) or set(upload) != {'format', 'data'}:
        raise ValueError('file_invalid')
    extension, encoded = upload['format'], upload['data']
    if not isinstance(extension, str) or extension not in FORMATS['file']:
        raise ValueError('file_format_unsupported')
    if not isinstance(encoded, str):
        raise ValueError('file_invalid')
    if len(encoded) > MAX_FILE_BASE64:
        raise ValueError('file_too_large')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('file_invalid') from None
    if not raw:
        raise ValueError('file_empty')
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError('file_too_large')
    if extension == 'pdf':
        if not re.match(br'%PDF-(1\.[0-7]|2\.0)(?:\r|\n)', raw):
            raise ValueError('file_format_unsupported')
    else:
        try:
            raw.decode('utf-8')
        except UnicodeDecodeError:
            raise ValueError('file_format_unsupported') from None
        if re.search(br'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', raw):
            raise ValueError('file_format_unsupported')
    return store(workspace, 'file', extension, raw)
