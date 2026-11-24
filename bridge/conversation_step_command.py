"""Render text from completed native shell records, without running a command."""
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
import shlex

from conversation_steps import codex_completed_item

CLAUDE_COMMAND_TOOLS = frozenset({'Bash'})
MAX_LINES = 400
MAX_OUTPUT_BYTES = 64 * 1024
MAX_COMMAND_BYTES = 8 * 1024
ANSI = re.compile(
    r'(?:\x1b\]|\x9d)[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c|$)'
    r'|(?:\x1b[P^_X]|[\x90\x98\x9e\x9f])[^\x1b\x9c]*(?:\x1b\\|\x9c|$)'
    r'|(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]'
    r'|\x1b[ -/]*[0-~]|[\x00-\x08\x0b-\x1f\x7f-\x9f]'
)
CLAUDE_EXIT = re.compile(r'\AExit code (-?\d{1,10})(?:\r?\n|\Z)')
CLAUDE_INTERRUPTED = '[Request interrupted by user for tool use]'


@dataclass
class Command:
    command: str | list[str]
    output: str | list[str]
    exit_code: int | None
    interrupted: bool = False
    truncated: bool = False


def _exit_code(value):
    return value if type(value) is int and -(2**31) <= value < 2**31 else None


def claude_command(call, result, metadata):
    if (call.get('type') != 'tool_use' or call.get('name') not in CLAUDE_COMMAND_TOOLS
            or result.get('type') != 'tool_result' or call.get('id') != result.get('tool_use_id')):
        return None
    args = call.get('input')
    command = args.get('command') if isinstance(args, dict) else None
    if not isinstance(command, str) or not command:
        return None
    metadata = metadata if isinstance(metadata, dict) else {}
    output = result.get('content')
    interrupted = metadata.get('interrupted') is True or (
        isinstance(output, str) and output.strip() == CLAUDE_INTERRUPTED)
    exit_code = _exit_code(metadata.get('exitCode'))
    if exit_code is None and result.get('is_error') is True and isinstance(output, str):
        # Claude places the native exit code on the first line of a failed
        # Bash result. A successful command's stdout cannot set this field.
        match = CLAUDE_EXIT.match(output)
        if match:
            exit_code = _exit_code(int(match[1]))
            output = output[match.end():].lstrip('\n')
    if metadata.get('isImage') is True:
        output = ''
    elif any(isinstance(metadata.get(key), str) for key in ('stdout', 'stderr')):
        output = [metadata[key] for key in ('stdout', 'stderr') if isinstance(metadata.get(key), str)]
    elif isinstance(output, list):
        output = [block['text'] for block in output if isinstance(block, dict)
                  and block.get('type') == 'text' and isinstance(block.get('text'), str)]
    elif not isinstance(output, str):
        output = ''
    if interrupted:
        exit_code = None
    elif (exit_code is None and result.get('is_error') is False and metadata.get('interrupted') is False
            and not any(key in metadata for key in ('backgroundTaskId', 'timedOutAfterMs', 'returnCodeInterpretation'))):
        exit_code = 0
    return Command(command, output, exit_code, interrupted, bool(metadata.get('persistedOutputPath')))


def codex_command(raw):
    item = codex_completed_item(raw)
    if not item or item.get('type') != 'CommandExecution':
        return None
    command = item.get('command')
    if not (isinstance(command, str) and command or isinstance(command, list) and command
            and all(isinstance(part, str) for part in command)):
        return None
    output = item.get('aggregated_output')
    return Command(command, output if isinstance(output, str) else '', _exit_code(item.get('exit_code')))


def _shell_text(command):
    if isinstance(command, str):
        return command
    if (len(command) == 3 and PurePosixPath(command[0]).name in {'sh', 'bash', 'zsh', 'dash', 'ksh', 'fish'}
            and command[1] in {'-c', '-lc'}):
        return command[2]
    return shlex.join(command)


def _clean(text):
    return ANSI.sub('', text.replace('\r\n', '\n').replace('\r', '\n'))


def _cap_bytes(text, limit):
    raw = text.encode('utf-8', errors='replace')
    return raw[:limit].decode('utf-8', errors='ignore'), len(raw) > limit


def detail(record):
    command, command_cut = _cap_bytes(_clean(_shell_text(record.command)), MAX_COMMAND_BYTES)
    output = record.output
    if isinstance(output, list):
        output = '\n'.join(value.removesuffix('\n') for value in output if value)
    output = _clean(output)
    lines = output.split('\n', MAX_LINES)
    lines_cut = len(lines) > MAX_LINES and bool(lines[-1])
    if lines_cut:
        output = '\n'.join(lines[:MAX_LINES])
    output, bytes_cut = _cap_bytes(output, MAX_OUTPUT_BYTES)
    return dict(ok=True, kind='command', command=command, output=output, exit_code=record.exit_code,
                truncated=record.truncated or command_cut or lines_cut or bytes_cut)
