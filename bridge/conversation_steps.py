"""Small public operation summaries from bound native records, never raw bodies.

Pairing is by opaque native call ID in the bounded Reader window. This module
does not open files, discover agents, execute code, or grant preview access.
"""
import hashlib
import json
import math
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit
from conversation_markdown_images import IMAGE_EXT

IMAGE_READ_TOOLS = frozenset({'Read', 'read', 'read_file', 'read_image', 'view_image', 'view_file'})


def mark_step_boundary(event):
    """Use the visible Reader projection to delimit native operation runs."""
    if event and not event.get('step_turn') and (
            event.get('mail') or event['kind'] not in {'tool', 'tool_result'}):
        event['step_boundary'] = True
    return event


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


def local_step_image(path):
    if (isinstance(path, str) and 0 < len(path) < 4096
            and not re.search(r'[\x00-\x1f\x7f]|^(?:~|//|[a-zA-Z][\w+.-]*:)|://', path)
            and PurePosixPath(path).suffix.lower() in IMAGE_EXT):
        return path
    return None


def image_read_path(name, args):
    if not isinstance(name, str) or not isinstance(args, dict):
        return None
    if name in IMAGE_READ_TOOLS:
        return local_step_image(args.get('file_path') or args.get('path'))
    if name == 'vision_analyze':
        return local_step_image(args.get('image_url'))
    return None


def step_image_path(record):
    """Recognize only native image reads and structured file-tool input."""
    if not isinstance(record, dict):
        return None
    if (item := codex_completed_item(record)) is not None:
        if item.get('type') == 'ImageView':
            return local_step_image(item.get('path'))
        if item.get('type') == 'McpToolCall':
            return image_read_path(item.get('tool'), item.get('arguments'))
        return None
    if record.get('type') == 'recorded_image_read':
        return local_step_image(record.get('path'))
    call = record.get('payload')
    if (record.get('type') == 'response_item' and isinstance(call, dict)
            and call.get('type') == 'function_call'):
        args = call.get('arguments')
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (ValueError, RecursionError):
                return None
        return image_read_path(call.get('name'), args)
    return None


def summary(name, args):
    if not isinstance(args, dict):
        return ''
    if image := image_read_path(name, args):
        return filename(image)
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


def tool_call(call_id, name, args, ts):
    key = opaque(call_id)
    name = label(name)
    return dict(id=key, phase='call', tool=name, detail=summary(name, args),
                started=ts) if key and name else None


def tool_result(call_id, ts, *, failed=False):
    key = opaque(call_id)
    return dict(id=key, phase='result', ended=ts,
                status='failed' if failed else 'done') if key else None


def claude_call(block, ts):
    return tool_call(block.get('id'), block.get('name'), block.get('input'), ts)


def claude_result(block, ts):
    return tool_result(block.get('tool_use_id'), ts, failed=block.get('is_error') is True)


def codex_completed_item(raw):
    if not isinstance(raw, dict) or raw.get('type') != 'event_msg':
        return None
    p = raw.get('payload')
    if not isinstance(p, dict) or p.get('type') != 'item_completed':
        return None
    item = p.get('item')
    return item if isinstance(item, dict) else None


def codex_completed(raw):
    item = codex_completed_item(raw)
    if item is None:
        return None
    p = raw['payload']
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
    elif kind == 'Extension' and item.get('kind') == 'clock.sleep':
        name = 'sleep'
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
