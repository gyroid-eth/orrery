"""Small public operation summaries from bound native records, never raw bodies.

Pairing is by opaque native call ID in the bounded Reader window. This module
does not open files, discover agents, execute code, or grant preview access.
"""
import hashlib
import math
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit


def label(value, limit=160):
    return re.sub(r'[\x00-\x1f\x7f]', ' ', value)[:limit] if isinstance(value, str) else ''


def opaque(value):
    if not isinstance(value, str) or not 0 < len(value) <= 256:
        return None
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def millis(value):
    return value if type(value) in (int, float) and math.isfinite(value) and 0 <= value < 1e15 else None


def filename(value, limit=160):
    if not isinstance(value, str):
        return ''
    value = value.replace('\\', '/')
    try:
        url = urlsplit(value)
    except ValueError:
        return ''
    if url.scheme or url.netloc:
        # Only a URL's path can name a target; never its authority,
        # credentials, query or fragment. No path means no summary.
        value = url.path if url.path.startswith('/') else ''
    return label(PurePosixPath(value).name, limit) if value else ''


def filenames(values):
    names = [filename(value) for value in values[:3]]
    return ' · '.join(filter(None, names))[:240]


def summary(name, args):
    if not isinstance(args, dict):
        return ''
    short = name.split('__')[-1].split('.')[-1].lower()
    if short in {'read', 'edit', 'write', 'read_file', 'write_file', 'view_image'}:
        return filenames([args.get('file_path') or args.get('path')])
    if short in {'show_files', 'senduserfile'}:
        paths = args.get('paths', args.get('files'))
        return filenames(paths) if isinstance(paths, list) else ''
    if short == 'send_message':
        # Same recipient fields as the existing recorded-Mail projection.
        names = []
        for key in ('to', 'to_agent_ids', 'recipients'):
            values = args.get(key)
            if isinstance(values, list):
                names.extend(label(v, 96) for v in values[:3] if isinstance(v, str))
        return ('To ' + ', '.join(names[:3]))[:240] if names else ''
    if short in {'bash', 'shell', 'exec_command'}:
        return command_summary(args.get('command', args.get('cmd')))
    return ''


def command_summary(command):
    # Reveal the executable, not shell source, switches, environment or values.
    if isinstance(command, list):
        if not command or not isinstance(command[0], str):
            return ''
        head = filename(command[0], 48)
        if head in {'bash', 'sh', 'zsh'} and len(command) >= 3 and command[1] in {'-c', '-lc'}:
            return command_summary(command[2]) or head
        return head
    if isinstance(command, str):
        match = re.match(r'\s*(pytest|python3?|node|rg|git|npm|uv|curl|bash|zsh|sh)(?=\s|$)', command[:4096])
        return match[1] if match else ''
    return ''


def claude_call(block, ts):
    key = opaque(block.get('id'))
    name = label(block.get('name'))
    return dict(id=key, phase='call', tool=name, detail=summary(name, block.get('input')),
                started=ts) if key and name else None


def claude_result(block, ts):
    key = opaque(block.get('tool_use_id'))
    return dict(id=key, phase='result', ended=ts,
                status='failed' if block.get('is_error') is True else 'done') if key else None


def codex_completed(raw):
    if not isinstance(raw, dict) or raw.get('type') != 'event_msg':
        return None
    p = raw.get('payload')
    if not isinstance(p, dict) or p.get('type') != 'item_completed':
        return None
    item = p.get('item')
    if not isinstance(item, dict):
        return None
    key = opaque(item.get('id'))
    if not key:
        return None
    kind = item.get('type')
    name, detail = '', ''
    if kind == 'CommandExecution':
        name, detail = 'Shell', command_summary(item.get('command'))
        parsed = item.get('parsed_cmd')
        if isinstance(parsed, list):
            files = filenames([part.get('path') for part in parsed[:3] if isinstance(part, dict)])
            detail = ' · '.join(filter(None, (detail, files)))
    elif kind == 'McpToolCall':
        name = label(item.get('tool'))
        detail = summary(name, item.get('arguments'))
    elif kind == 'FileChange':
        name = 'apply_patch'
        changes = item.get('changes')
        detail = filenames(list(changes)[:3]) if isinstance(changes, dict) else ''
    elif kind == 'ImageView':
        name, detail = 'view_image', filenames([item.get('path')])
    elif kind in {'WebSearch', 'Extension'} and (kind == 'WebSearch' or item.get('kind') == 'web.search'):
        name = 'web_search'
    if not name:
        return None
    result = item.get('result')
    failed = (item.get('status') == 'failed' or
              type(item.get('exit_code')) is int and item['exit_code'] != 0 or
              isinstance(result, dict) and result.get('isError') is True)
    status = ('failed' if failed else 'observed' if kind in {'ImageView', 'WebSearch', 'Extension'} else
              'done' if item.get('status') == 'completed' else 'observed')
    step = dict(id=key, phase='complete', tool=name, detail=detail, status=status)
    for source, target in [('started_at_ms', 'started'), ('completed_at_ms', 'ended')]:
        value = millis(p.get(source))
        if value is not None:
            step[target] = value
    turn = opaque(p.get('turn_id'))
    if turn:
        step['turn'] = turn
    return step


def codex_turn(raw):
    if not isinstance(raw, dict) or raw.get('type') != 'event_msg':
        return None
    p = raw.get('payload')
    if not isinstance(p, dict) or p.get('type') not in {'task_started', 'task_complete', 'turn_aborted'}:
        return None
    key = opaque(p.get('turn_id'))
    if not key:
        return None
    result = dict(id=key, phase='start' if p['type'] == 'task_started' else 'end')
    for source, target in [('started_at', 'started'), ('completed_at', 'ended')]:
        value = p.get(source)
        value = millis(value * 1000) if type(value) in (int, float) else None
        if value is not None:
            result[target] = value
    duration = millis(p.get('duration_ms'))
    if duration is not None:
        result['duration'] = duration
    return result
