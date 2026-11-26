"""Three complete approval menus, observed and answered on the existing bridge."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import time
from pathlib import Path

from question_screen import parse_question, question_candidate, same_question, valid_choice

MAX_BYTES = 65536
HEADINGS = ('Allow the ', 'Would you like to run the following command?', 'Read outside the working directories')
MCP_CHOICES = ['Allow', 'Allow for this session', 'Always allow', 'Cancel']
READ_CHOICES = ['Yes, and keep allowing any reads outside the working directories',
                'No, and block reads outside the working directories from now on',
                'No, and ask again next time', 'Yes, but ask again next time']
COMMAND_CHOICES = ['Yes, proceed (y)', None, 'No, and tell Codex what to do differently (esc)']
OPTION = re.compile(r'^ {0,4}([›❯] )?([1-4])\. (.+)$')


class ApprovalNotSent(RuntimeError):
    """Admission failed before the first possible key byte."""


def parse_screen(text, command, harness=None):
    """Return only complete known menus. Never fill missing text from a template."""
    question = parse_question(text, harness)
    if question:
        question.update(default=question['selected'], summary=question['body'])
        return question
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BYTES:
        return None
    lines = [line.rstrip() for line in text.splitlines()]
    if len(lines) > 256 or any(c in text for c in ('…', '...', '\ufffd', '\x00')):
        return None
    starts = [i for i, line in enumerate(lines) if len(line)-len(line.lstrip(' '))<=2 and line.lstrip(' ').startswith(HEADINGS)]
    if len(starts) != 1:
        return None
    prefix = [line.strip() for line in lines[:starts[0]] if line.strip()]
    lines = lines[starts[0]:]
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        return None
    footer = lines.pop().strip()
    harness = harness or (command if command in ('codex', 'claude') else None)
    if harness not in ('codex', 'claude') or command not in (harness, 'node'):
        return None
    options = [(i, OPTION.fullmatch(line)) for i, line in enumerate(lines)]
    options = [(i, m) for i, m in options if m]
    if len(options) not in (3, 4):
        return None
    if [int(m[2]) for _, m in options] != list(range(1, len(options) + 1)):
        return None
    # Unknown text between or after options may be a hidden item or a new prompt.
    allowed = {i for i, _ in options}
    if any(line and i not in allowed for i, line in enumerate(lines) if i >= options[0][0]):
        return None
    selected = [int(m[2]) for _, m in options if m[1]]
    if len(selected) != 1:
        return None
    labels = [m[3] for _, m in options]
    body = [line.lstrip(' ') for line in lines[:options[0][0]] if line]
    if not body:
        return None
    kind = None
    if (harness == 'codex' and prefix == ['Field 1/1'] and footer == 'enter to submit | esc to cancel'
            and re.fullmatch(r'Allow the [\w.-]+ MCP server to run tool "[\w.-]+"\?', body[0])):
        # Initially accept explicit scalar argument rows; folded/nested displays
        # cannot establish that the argument payload is complete.
        if labels == MCP_CHOICES and len(body) > 1:
            try:
                for line in body[1:]:
                    field, value = line.split(': ', 1)
                    if not re.fullmatch(r'[\w.-]+', field) or isinstance(json.loads(value), (dict, list)):
                        return None
                kind = 'mcp'
            except (ValueError, TypeError):
                return None
    elif (harness == 'codex' and not prefix and footer == 'Press enter to confirm or esc to cancel'
            and body[0] == HEADINGS[1]):
        if (len(body) == 4 and body[1] == 'Environment: local' and body[2].startswith('Reason: ')
                and len(body[2]) > 8 and body[3].startswith('$ ') and len(body[3]) > 2
                and len(labels) == 3 and labels[0] == COMMAND_CHOICES[0] and labels[2] == COMMAND_CHOICES[2]
                and re.fullmatch(r"Yes, and don't ask again for commands that start with `[^`]+` \(p\)", labels[1])):
            kind = 'command'
    elif (harness == 'claude' and len(prefix) == 1 and re.fullmatch(r'─{3,}', prefix[0])
            and footer == 'Esc to cancel · Tab to amend' and body[0] == HEADINGS[2]):
        if (len(body) == 3 and re.fullmatch(r'Read\((?:~/|/)[^\r\n]+\)', body[1])
                and body[2] == 'Allow this read outside the working directories?' and labels == READ_CHOICES):
            kind = 'read'
    if kind is None:
        return None
    return dict(kind=kind, text=text.strip(), body='\n'.join(body), selected=selected[0], default=4 if kind == 'read' else 1,
                summary=body[1] if kind == 'read' else body[3][2:] if kind == 'command' else re.search(r'tool "([^"]+)"', body[0])[1]+'('+', '.join(body[1:])+')',
                choices=[dict(id=i + 1, label=label) for i, label in enumerate(labels)])


class ApprovalCoordinator:
    """Tokens and receipts belong to one bridge incarnation, across its tabs."""
    def __init__(self, bridge, *, harness_resolver=None):
        self.bridge = bridge
        self.harness_resolver = harness_resolver
        self.screens = {}
        self.tokens = {}
        self.receipts = {}
        self.answered = {}

    def _valid(self, pane):
        b = self.bridge
        return pane in b.panes and not b._closed and b.master_fd is not None

    def _digest(self, snapshot):
        b = self.bridge
        fields = snapshot
        if (question := self._parse(snapshot)) and question['kind'] == 'question':
            # The countdown and unrelated history can redraw without changing
            # the current question. The identity, options and draft still bind it.
            fields = [snapshot['identity'], question]
        return hashlib.sha256(json.dumps([b._incarnation, b.config.session_created, fields], sort_keys=True).encode()).hexdigest()

    async def _capture(self, pane):
        harness = (await self.harness_resolver(pane) or 'unknown') if self.harness_resolver else None
        if harness == 'hermes':
            snapshot = await self.bridge.approval_capture_locked(pane, styled=True)
        else:
            snapshot = await self.bridge.approval_capture_locked(pane)
            if harness in ('codex', 'dsh', 'agy', 'claude') and question_candidate(snapshot['text']):
                snapshot = await self.bridge.approval_capture_locked(pane, styled=True)
        return dict(snapshot, harness=harness)

    @staticmethod
    def _parse(snapshot):
        return parse_screen(snapshot['text'], snapshot['command'], snapshot.get('harness'))

    @staticmethod
    def _content(parsed):
        return (parsed['kind'], parsed['body'], tuple(c['label'] for c in parsed['choices']), parsed.get('position'))

    @staticmethod
    def _ready(token, parsed):
        result = dict(state='ready', token=token, **{k: v for k, v in parsed.items() if k != 'draft'})
        if parsed['kind'] == 'question':
            result['draft_empty'] = not parsed['draft']
        return result

    def _view(self, pane, owner, snapshot):
        digest = self._digest(snapshot)
        row = self.screens.get(pane)
        if row is None or row['digest'] != digest:
            row = dict(digest=digest, snapshot=snapshot, used=False, result=None)
            self.screens[pane] = row
        parsed = self._parse(snapshot)
        if not parsed:
            candidate = re.search(r'Allow the |Would you like to run|Read outside|Allow this read outside|Do you want to proceed\?|Allow for this session|Yes, proceed|Yes, but ask again|keep allowing any reads', snapshot['text'])
            candidate = candidate or question_candidate(snapshot['text'])
            if not candidate:
                self.answered.pop(pane, None)
            return dict(state='terminal' if candidate else 'none', message='Approval needs terminal review' if candidate else 'Prompt closed')
        # Geometry and the selection marker can change while an answered menu
        # remains on screen. Neither change makes it a new approval.
        content = self._content(parsed)
        previous = self.answered.get(pane)
        if previous and previous[0] == content:
            return dict(previous[1]['result'] or dict(state='unknown', message='Outcome unknown — check terminal'))
        if row['used']:
            return dict(row['result'] or dict(state='unknown', message='Outcome unknown — check terminal'))
        # Re-inspecting a stable screen must not invalidate another tab's token.
        for token, item in self.tokens.items():
            if item['row'] is row and item['owner'] is owner:
                return self._ready(token, parsed)
        if len(self.tokens) >= 256:
            self.tokens.pop(next(iter(self.tokens)))
        token = secrets.token_urlsafe(24)
        self.tokens[token] = dict(row=row, owner=owner, pane=pane, incarnation=self.bridge._incarnation)
        return self._ready(token, parsed)

    async def inspect(self, pane, owner):
        try:
            async with asyncio.timeout(5):
                async with self.bridge._write_lock:
                    if not self._valid(pane):
                        return dict(state='unavailable', message='Pane unavailable')
                    snapshot = await self._capture(pane)
                    return self._view(pane, owner, snapshot)
        except (Exception, asyncio.CancelledError):
            return dict(state='unavailable', message='Pane unavailable')

    def _log(self, pane, operation, choice, keys, state):
        try:
            folder = self.bridge.config.history_dir
            if folder is None:
                from control_server import history_directory
                folder = history_directory()
            folder = Path(folder);folder.mkdir(parents=True, exist_ok=True)
            row = dict(ts=time.time(), pane=pane, incarnation=self.bridge._incarnation,
                       operation=operation, choice=choice, keys=keys, state=state)
            with (folder / 'approval-actions.jsonl').open('a', encoding='utf-8') as out:
                out.write(json.dumps(row) + '\n')
            return False
        except OSError:
            return True

    @staticmethod
    def _move(selected, target):
        delta = target - selected
        return ['Down' if delta > 0 else 'Up'] * abs(delta)

    @classmethod
    def _answer_plan(cls, question, choice, raw):
        if question['mode'] == 'other':
            return []
        if question['harness'] == 'hermes':
            if question['multiple']:
                wanted = set(choice)
                return [str(option['id']) for option in question['choices']
                        if option['checked'] != (option['id'] in wanted)]
            return [str(choice)]
        if question['harness'] in ('dsh', 'agy'):
            if question['multiple']:
                keys = []
                focus = question['selected']
                for option in question['choices']:
                    option_id = option['id']
                    if not option.get('other') and option['checked'] != (option_id in choice):
                        keys.extend(cls._move(focus, option_id) + ['Space'])
                        focus = option_id
                return keys
            if raw is not None and question['harness'] == 'dsh':
                return ['Tab']
            return cls._move(question['selected'], choice) + ['Enter']
        keys = cls._move(question['selected'], choice)
        return keys + (['Tab'] if raw is not None else ['Enter'])

    async def _question_keys(self, pane, snapshot, question, choice, keys, raw, proof, valid):
        """Validate the active question again after entering an answer editor."""
        async def observe():
            if valid is not None and not valid():
                raise RuntimeError('question answer expired')
            current = await self.bridge.approval_capture_locked(pane, styled=True)
            if current['identity'] != snapshot['identity']:
                raise RuntimeError('question pane changed')
            return parse_screen(current['text'], current['command'], question['harness'])

        async def wait_for(test):
            while True:
                view = await observe()
                if view is not None:
                    if not same_question(question, view):
                        raise RuntimeError('question changed during input')
                    if test(view):
                        return view
                await asyncio.sleep(.06)

        async def write(batch):
            await self.bridge.approval_keys_locked(pane, batch, proof=proof)

        wrote = False
        try:
            if keys:
                await write(keys)
                wrote = True
            if question['multiple'] and question['mode'] == 'choice':
                wanted = {option['id'] for option in question['choices']
                          if option['id'] in choice and (question['harness'] == 'hermes' or not option.get('other'))}
                current = await wait_for(lambda view: view['mode'] == 'choice' and view['multiple'] and
                                         {option['id'] for option in view['choices'] if option['checked']} == wanted)
                commit = ['Enter']
                if raw is not None:
                    if question['harness'] == 'dsh':
                        commit = ['Tab']
                    elif question['harness'] == 'agy':
                        other = next(option['id'] for option in question['choices'] if option.get('other'))
                        commit = self._move(current['selected'], other) + ['Enter']
                await write(commit)
                wrote = True
            if raw is None:
                return
            if question['mode'] == 'choice':
                current = await wait_for(lambda view: view['mode'] == 'other')
                if current['draft'] or (question['harness'] == 'codex' and current['selected'] != choice):
                    raise RuntimeError('Other editor changed or is occupied')
            batch = b'\x1b[200~' + raw + b'\x1b[201~'
            await write(['-H', *(f'{byte:02x}' for byte in batch)])
            wrote = True
            wanted = raw.decode('utf-8').strip()
            previous = None
            def settled(view):
                nonlocal previous
                if view['mode'] != 'other':
                    raise RuntimeError('answer editor closed')
                draft = view['draft']
                stable = draft == previous and draft.replace('\n', '') == wanted
                previous = draft
                return stable
            await asyncio.sleep(.06)
            await wait_for(settled)
            await write(['Enter'])
        except ApprovalNotSent:
            if not wrote:
                raise
            raise RuntimeError('question input already started') from None

    async def answer(self, pane, owner, token, choice, operation, *, proof=None, text=None,
                     check=None, claim=None, valid=None):
        if (not isinstance(operation, str) or not re.fullmatch(r'[\w-]{1,96}', operation)
                or not isinstance(token, str) or not valid_choice(choice)):
            return dict(state='refused', message='Response not sent — invalid request')
        receipt_key = (owner, operation)
        started = False;row = None;keys = []
        try:
            async with asyncio.timeout(5):
                async with self.bridge._write_lock:
                    if receipt_key in self.receipts:
                        return self.receipts[receipt_key]
                    item = self.tokens.get(token)
                    if (not item or item['owner'] is not owner or item['pane'] != pane
                            or item['incarnation'] != self.bridge._incarnation):
                        return dict(state='refused', message='Response not sent — approval expired')
                    row = item['row']
                    if row['used'] or self.screens.get(pane) is not row:
                        return dict(state='refused', message='Response not sent — already answered or changed')
                    if not self._valid(pane):
                        return dict(state='unavailable', message='Pane unavailable')
                    snapshot = await self._capture(pane)
                    if self._digest(snapshot) != row['digest']:
                        self._view(pane, owner, snapshot)
                        return dict(state='changed', message='Approval changed — review again')
                    parsed = self._parse(snapshot)
                    if not parsed:
                        return dict(state='refused', message='Response not sent — panel changed')
                    is_question = parsed['kind'] == 'question'
                    freeform = is_question and parsed['mode'] == 'other'
                    multiple = is_question and parsed['multiple'] and not freeform
                    requested = choice if isinstance(choice, list) else [choice]
                    options = [option for option in parsed['choices'] if option['id'] in requested]
                    if (multiple != isinstance(choice, list) or
                            (choice != 0 if freeform else len(options) != len(requested))):
                        return dict(state='refused', message='Response not sent — invalid choice')
                    raw = None
                    if is_question:
                        if parsed['draft']:
                            return dict(state='refused', message='The answer editor already contains a draft')
                        if freeform or any(option.get('other') for option in options):
                            from mobile_input import InputRefused, validate_text
                            try:
                                raw = validate_text(text)
                            except InputRefused:
                                return dict(state='refused', message='Enter an answer for Other', retryable=True)
                        elif text is not None:
                            return dict(state='refused', message='Choose Other to enter a written answer')
                        keys = self._answer_plan(parsed, choice, raw)
                    elif text is not None:
                        return dict(state='refused', message='This approval only accepts a choice')
                    elif parsed['kind'] == 'command':
                        keys = [['y'], ['p'], ['Escape']][choice - 1]
                    else:
                        keys = self._move(parsed['selected'], choice) + ['Enter']
                    # Consume across tabs before the first possible key write.
                    if check is not None and not await check():
                        return dict(state='refused', message='Pane changed — review again')
                    if claim is not None and not claim():
                        return dict(state='refused', message='Response not sent — input expired')
                    row['used'] = True
                    warning = self._log(pane, operation, choice, keys, 'dispatching')
                    started = True
                    if is_question:
                        await self._question_keys(pane, snapshot, parsed, choice, keys, raw, proof, valid)
                    else:
                        await self.bridge.approval_keys_locked(pane, keys, proof=proof)
                    result = dict(state='sent', message='Response sent · Waiting for terminal', logWarning=warning)
        except ApprovalNotSent:
            # Admission/revision checks failed before any possible key byte.
            # A fresh inspect may offer this unchanged approval again.
            if row is not None:
                row['used'] = False
            result = dict(state='refused', message='Response not sent — terminal changed or input refused', retryable=True)
        except (Exception, asyncio.CancelledError):
            result = dict(state='unknown' if started else 'refused',
                          message='Outcome unknown — check terminal' if started else 'Response not sent', retryable=not started)
        if row is not None and started:
            result['logWarning'] = self._log(pane, operation, choice, keys, result['state']) or result.get('logWarning', False)
        if row is not None and row['used']:
            row['result'] = result
            parsed = self._parse(row['snapshot'])
            content = self._content(parsed)
            self.answered[pane] = (content, row)
        if len(self.receipts) >= 512:
            self.receipts.pop(next(iter(self.receipts)))
        self.receipts[receipt_key] = result
        return result
