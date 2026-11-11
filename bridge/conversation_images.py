"""人の入力の画像だけを、固定済みの記録から既存 preview へ渡す。"""
from __future__ import annotations

from collections import OrderedDict
import json
import os
from pathlib import Path
import re
import shlex
import threading

_saved = OrderedDict()
_lock = threading.RLock()


def signature(path):
    st = os.stat(path, follow_symlinks=False)
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def remember_saved(path):
    """保存成功後だけ呼ぶ。再起動前の画像を推測して登録しない。"""
    try:
        physical = str(Path(path).resolve(strict=True))
        entry = physical, signature(physical)
    except (OSError, ValueError):
        return
    with _lock:
        _saved[str(path)] = entry
        _saved.move_to_end(str(path))
        while len(_saved) > 1024:
            _saved.popitem(last=False)


def saved_path(value):
    with _lock:
        entry = _saved.get(value)
    try:
        if entry and signature(entry[0]) == entry[1]:
            return Path(entry[0])
    except OSError:
        pass
    return None


def hermes_content(value):
    if isinstance(value, str) and value.startswith('\x00json:'):
        try:
            return json.loads(value[6:])
        except (ValueError, TypeError):
            # 既存の読取上限を超えた画像は表示しない。base64 本文も出さない。
            return '[attachment unavailable]'
    return value


def input_content(item):
    """通常の文や tool の引数を、native 添付の形と解釈しない。"""
    if item.get('type') == 'recorded_user_input':
        return item.get('content'), item.get('provider')
    payload = item.get('payload')
    if (item.get('type') == 'response_item' and isinstance(payload, dict)
            and payload.get('type') == 'message' and payload.get('role') == 'user'):
        return payload.get('content'), 'codex'
    return None, None


def input_images(item):
    content, provider = input_content(item)
    if provider is None:
        return []
    blocks = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
    if not isinstance(blocks, list):
        return []
    found = []
    for block in blocks[:64]:
        if not isinstance(block, dict):
            continue
        kind, url = block.get('type'), None
        if kind == 'image' and provider == 'claude':
            source = block.get('source')
            if isinstance(source, dict) and source.get('type') == 'base64':
                mime, data = source.get('media_type'), source.get('data')
                if isinstance(mime, str) and isinstance(data, str):
                    url = 'data:' + mime + ';base64,' + data
        elif kind in {'input_image', 'image_url'} and provider in {'codex', 'hermes'}:
            image = block.get('image_url')
            url = image.get('url') if isinstance(image, dict) else image
        elif kind == 'image' and provider == 'dsh':
            attachment = block.get('attachment')
            if isinstance(attachment, dict) and re.fullmatch(r'sha256:[a-f0-9]{64}', str(attachment.get('attachmentId', ''))):
                found.append(dict(kind='dsh', digest=attachment['attachmentId'][7:]))
        if isinstance(url, str) and re.fullmatch(r'data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/]+={0,2}', url):
            found.append(dict(kind='data', url=url))
        if kind in {'text', 'input_text'} and isinstance(block.get('text'), str):
            text = block['text']
            with _lock:
                paths = tuple(_saved)
            for path in paths:
                values={path,shlex.quote(path)}
                if any(value in text and re.search(r'(?<![^\s\'"`\[(])' + re.escape(value) + r'(?=$|[\s\'"`\])])', text) for value in values) and saved_path(path):
                    found.append(dict(kind='saved', path=path))
        if len(found) >= 8:
            break
    return found[:8]


def dsh_image_path(transcript, digest):
    """dsh-attachment-local 0.2.1-rc.2 の content-addressed store。"""
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        return None
    for parent in Path(transcript).parents:
        if parent.name == 'sessions':
            return parent.parent / 'attachments' / 'v1' / 'objects' / digest[:2] / digest
    return None
