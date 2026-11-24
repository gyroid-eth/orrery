"""Diffs from known, completed native edits. Never read the edited file."""
from dataclasses import dataclass
from difflib import unified_diff
import json
import re

from conversation_steps import filename


CLAUDE_EDIT_TOOLS = frozenset({'Edit', 'MultiEdit', 'Write'})
MAX_LINES = 400
MAX_BYTES = 64 * 1024
MAX_COMPARE_LINES = 1000
MAX_REPLACEMENT_CHARS = 1024 * 1024
HUNK_HEADER = re.compile(r'^@@ -[0-9]+(?:,[0-9]+)? \+[0-9]+(?:,[0-9]+)? @@')


def encode(value):
    return json.dumps(value, separators=(',', ':'))


@dataclass
class Hunk:
    header: str
    lines: list[str]


@dataclass
class FileDiff:
    path: str
    new_file: bool
    hunks: list[Hunk]


def _lines(value):
    # Split on file newlines, not Unicode separators embedded in a line.
    return value.removesuffix('\n').split('\n') if value else []


def _range(start, count):
    return f'{start if count else start - 1},{count}'


def _hunk(old, new, *, start=1):
    return Hunk(f'@@ -{_range(start, len(old))} +{_range(start, len(new))} @@',
                ['-' + line for line in old] + ['+' + line for line in new])


def _parse_unified(lines):
    hunks = []
    for line in lines:
        if HUNK_HEADER.match(line):
            hunks.append(Hunk(line[:240], []))
        elif hunks and line[:1] in {' ', '+', '-'}:
            hunks[-1].lines.append(line)
        elif hunks and not line.startswith('\\ No newline at end of file'):
            return []
    return [hunk for hunk in hunks if hunk.lines]


def _replacement(old, new):
    if not isinstance(old, str) or not isinstance(new, str) or old == new:
        return []
    before, after = _lines(old), _lines(new)
    if before == after:
        return [_hunk(before[-1:], after[-1:], start=len(before))]
    if len(before) + len(after) <= MAX_COMPARE_LINES:
        return _parse_unified(unified_diff(before, after, n=3, lineterm=''))
    # Bound the work on large fallback records. This is a replacement hunk
    # over the recorded range, with shared leading/trailing lines left out.
    first, last_before, last_after = 0, len(before), len(after)
    while first < min(last_before, last_after) and before[first] == after[first]:
        first += 1
    while first < min(last_before, last_after) and before[last_before-1] == after[last_after-1]:
        last_before -= 1
        last_after -= 1
    return [_hunk(before[first:last_before], after[first:last_after], start=first+1)]


def _structured(hunks):
    if not isinstance(hunks, list):
        return []
    out = []
    for value in hunks:
        if not isinstance(value, dict):
            return []
        numbers = [value.get(key) for key in ('oldStart', 'oldLines', 'newStart', 'newLines')]
        lines = value.get('lines')
        if (any(type(n) is not int or not 0 <= n <= 10**9 for n in numbers)
                or not isinstance(lines, list)
                or any(not isinstance(line, str) or
                       (line[:1] not in {' ', '+', '-'} and not line.startswith('\\ No newline at end of file'))
                       for line in lines)):
            return []
        old_start, old_lines, new_start, new_lines = numbers
        body = [line for line in lines if line[:1] in {' ', '+', '-'}]
        out.append(Hunk(f'@@ -{old_start},{old_lines} +{new_start},{new_lines} @@', body))
    return out


def claude_diff(call, result, metadata):
    if (call.get('type') != 'tool_use' or result.get('type') != 'tool_result'
            or not call.get('id') or call['id'] != result.get('tool_use_id')
            or result.get('is_error') is True):
        return []
    name, args = call.get('name'), call.get('input')
    if not isinstance(name, str) or name not in CLAUDE_EDIT_TOOLS or not isinstance(args, dict):
        return []
    path = filename(args.get('file_path'))
    if not path:
        return []
    if not isinstance(metadata, dict) or metadata.get('filePath') != args['file_path']:
        metadata = {}
    recorded = _structured(metadata.get('structuredPatch'))
    new_file = False
    if name == 'Edit':
        old, new = metadata.get('oldString', args.get('old_string')), metadata.get('newString', args.get('new_string'))
        original = metadata.get('originalFile')
        if (not recorded and metadata.get('replaceAll', args.get('replace_all')) is True and
                isinstance(original, str) and isinstance(old, str) and old and isinstance(new, str) and old in original):
            if len(original) + original.count(old) * (len(new) - len(old)) > MAX_REPLACEMENT_CHARS:
                return []
            hunks = _replacement(original, original.replace(old, new))
        else:
            hunks = recorded or _replacement(old, new)
    elif name == 'MultiEdit':
        edits = args.get('edits')
        if not isinstance(edits, list) or any(not isinstance(edit, dict) for edit in edits):
            return []
        hunks = [hunk for edit in edits
                 for hunk in _replacement(edit.get('old_string'), edit.get('new_string'))]
    else:
        content = metadata.get('content', args.get('content'))
        original = metadata.get('originalFile')
        new_file = metadata.get('type') == 'create' or (
            'originalFile' in metadata and original is None and metadata.get('type') != 'update')
        if new_file and isinstance(content, str):
            hunks = [_hunk([], _lines(content))]
        elif isinstance(original, str):
            hunks = recorded or _replacement(original, content)
        else:
            hunks = recorded
    return [FileDiff(path, new_file, hunks)] if hunks else []


def codex_diff(item):
    if not isinstance(item, dict) or item.get('type') != 'event_msg':
        return []
    payload = item.get('payload')
    if not isinstance(payload, dict) or payload.get('type') != 'item_completed':
        return []
    entry = payload.get('item')
    if not isinstance(entry, dict) or entry.get('type') != 'FileChange' or entry.get('status') != 'completed':
        return []
    changes = entry.get('changes')
    if not isinstance(changes, dict) or not changes:
        return []
    files = []
    for name, change in changes.items():
        if not isinstance(change, dict) or not filename(name):
            return []
        kind = change.get('type')
        if kind == 'update' and isinstance(change.get('unified_diff'), str):
            hunks = _parse_unified(_lines(change['unified_diff']))
        elif kind in ('add', 'delete') and isinstance(change.get('content'), str):
            lines = _lines(change['content'])
            hunks = [_hunk(lines, []) if kind == 'delete' else _hunk([], lines)]
        else:
            # Partial totals would silently omit changes from the operation.
            return []
        if not hunks:
            return []
        files.append(FileDiff(filename(change.get('move_path')) or filename(name), kind == 'add', hunks))
    return files


def stat(files):
    if not files:
        return None
    added = removed = 0
    new_file = all(file.new_file for file in files)
    for file in files:
        for hunk in file.hunks:
            for line in hunk.lines:
                added += line.startswith('+')
                removed += line.startswith('-')
    if not (new_file or added or removed):
        return None
    return dict(added=added, removed=removed, new_file=new_file)


def detail(files):
    separate = len(files) > 1
    hunks = []
    result = dict(ok=True, path=f'{len(files)} files' if separate else files[0].path,
                  new_file=all(file.new_file for file in files), hunks=hunks, truncated=False)
    # Measure the actual compact JSON response, including JSON escaping.
    size = len(encode(result))
    lines = 0
    for file in files:
        for hunk in file.hunks:
            header = f'{hunk.header} {file.path}' if separate else hunk.header
            value = dict(header=header, lines=[])
            overhead = len(encode(value)) + bool(hunks)
            for line in hunk.lines:
                value_line = dict(op=line[0], text=line[1:])
                increment = len(encode(value_line)) + bool(value['lines'])
                if lines >= MAX_LINES or size + overhead + increment > MAX_BYTES:
                    result['truncated'] = True
                    return result
                if not value['lines']:
                    hunks.append(value)
                    size += overhead
                    overhead = 0
                value['lines'].append(value_line)
                size += increment
                lines += 1
    return result
