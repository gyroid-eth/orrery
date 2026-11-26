"""Store the original bytes of a selected non-image attachment."""

import base64
import binascii
from mobile_attachment_store import store, valid_extension


MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_FILE_BASE64 = 4 * ((MAX_FILE_BYTES + 2) // 3)
MAX_FILE_JSON = MAX_FILE_BASE64 + 16384


def save_file(workspace, upload, *, label=None):
    if not isinstance(upload, dict) or set(upload) != {'format', 'data'}:
        raise ValueError('file_invalid')
    extension, encoded = upload['format'], upload['data']
    if not valid_extension('file', extension):
        raise ValueError('file_format_invalid')
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
    return store(workspace, 'file', extension, raw, label=label)
