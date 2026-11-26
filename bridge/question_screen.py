"""Bounded views of live question panels and their answer editors."""

import re


SGR = re.compile(r'\x1b\[[0-9;:]*m')
ITALIC = re.compile(r'\x1b\[(?:[012];)*3m')
TITLE = re.compile(r'^╭─ (.{1,80}(?: needs your input| が入力を求めています)) ─+╮$')
RULE = re.compile(r'^─{8,}$')
COUNT = re.compile(r'^([1-9][0-9]?) (?:questions?|件の質問)$')
OPTION = re.compile(r'^ *(❯ )?(?:\[([ x])\] )?([1-9])\. (\S.*)$')
CODEX_HEADER = re.compile(r'^  Question ([1-9][0-9]?)/([1-9][0-9]?) \([1-9][0-9]? unanswered\)$')
CODEX_OPTION = re.compile(r'^  (› |  )([1-9])\. (.+)$')
CODEX_CHOICE = re.compile(
    r'^tab to add notes \| enter to submit (?:answer|all)(?: \| ←/→ to navigate questions)?(?: \|)? esc to interrupt$')
CODEX_OTHER = re.compile(r'^tab or esc to clear notes \| enter to submit (?:answer|all)$')
CODEX_NONE = 'None of the above'
DSH_HEADER = re.compile(r'^─{8,}▾ +📋 (?:Question ([1-9][0-9]?)/([1-9][0-9]?)|提问 · 第 ([1-9][0-9]?)/([1-9][0-9]?) 题)(?: +· +[^─]+)? +─{8,}$')
DSH_OPTION = re.compile(r'^    (❯| )([○◉●]) (\S.*)$')
DSH_EDITOR = re.compile(r'^    (❯| )✎ (Custom answer|自定义回答)[:：](.*)$')
DSH_SCROLL = re.compile(r'^    [↑↓][○◉●] ')
DSH_CHOICE = ('↑/↓ select', '↑/↓ 选择')
DSH_OTHER = ('Type answer', '输入回答')
AGY_HEADER = re.compile(r'^Question ([1-9][0-9]?)/([1-9][0-9]?): (.+)$')
AGY_OPTION = re.compile(r'^(> |  )([1-9])\. (?:\[([ x])\] )?(.+)$')
AGY_STATUS = re.compile(r'^esc to cancel(?: +(?:plan|auto|accept-edits) · [^·]+ · [a-z]+)?$')
AGY_SINGLE = '↑/↓ Navigate · enter Select · esc Skip'
AGY_MULTIPLE = '↑/↓ Navigate · space Toggle · enter Submit · esc Skip'
AGY_EDITOR = 'enter Submit · esc Back'
STATUS = re.compile(r'^(?:[^│]+ │ )?☤ \S')
SINGLE = ('↑/↓ to select, Enter to lock, Tab next question',
          '↑/↓ で選択、Enter で確定、Tab で次の質問')
FREE = ('type your answer and press Enter', '回答を入力して Enter を押してください')
OTHER = ('Other (type your answer)', 'その他 (回答を入力)')
OTHER_FREE = ('Other (type below)', 'その他 (下に入力)')
PLACEHOLDER = ('type your answer here and press Enter', 'ここに回答を入力して Enter を押してください')
COUNTDOWN = re.compile(r'^(?:\s+\(\d{0,6}(?:s\)?)?)?$')


def _panel_body(rows):
    """Coalesce terminal wraps that split off the right edge of a panel row."""
    body = []
    for row in rows:
        if row.startswith('│'):
            if body and not body[-1].endswith('│'):
                return None
            body.append(row[1:])
        elif body and not body[-1].endswith('│'):
            body[-1] += ' ' + row.lstrip()
        else:
            return None
    if not body or not body[-1].endswith('│'):
        return None
    return [row[:-1].rstrip() for row in body]


def parse_hermes_question(text):
    """Trust the complete current box, operation hint and input mode together."""
    if not isinstance(text, str) or len(text) > 65536:
        return None
    raw = text.splitlines()[-96:]
    rows = [SGR.sub('', row).rstrip() for row in raw]
    while rows and not rows[-1]:
        rows.pop()
    for index in range(len(rows) - 1, max(-1, len(rows) - 16), -1):
        if match := re.fullmatch(r'(\?|✎)(?: +❯)?(?: +(.*))?', rows[index].strip()):
            if index and RULE.fullmatch(rows[index - 1]):
                break
    else:
        return None
    compact = not any(RULE.fullmatch(row) for row in rows[index + 1:])
    if compact and (index < 2 or not STATUS.match(rows[index - 2].strip())):
        return None
    end = len(rows) if compact else len(rows) - 1
    if not compact and rows[-1] != rows[index - 1]:
        return None
    mode = 'other' if match[1] == '✎' else 'choice'
    suffix = rows[index + 1:end]
    if mode == 'choice' and (match[2] or any(suffix)):
        return None
    draft = '\n'.join([(match[2] or ''), *suffix]).strip()
    if (mode == 'other' and not any(suffix) and draft in PLACEHOLDER and ITALIC.search(raw[index])):
        draft = ''

    heading = next((i for i in range(index - 2, -1, -1) if TITLE.fullmatch(rows[i])), None)
    if heading is None:
        return None
    border = '╰' + '─' * (len(rows[heading]) - 2) + '╯'
    try:
        bottom = rows.index(border, heading + 1, index - 1)
    except ValueError:
        return None
    controls = [hint for hint in (FREE if mode == 'other' else SINGLE)
                if any(row.strip().startswith(hint) and COUNTDOWN.fullmatch(row.strip()[len(hint):])
                       for row in rows[bottom + 1:index - 1])]
    if len(controls) != 1:
        return None
    body = _panel_body(rows[heading + 1:bottom])
    count = COUNT.fullmatch(body[0].strip()) if body else None
    if not count:
        return None
    questions = []
    for row in body[1:]:
        line = row.strip()
        if line.startswith(('▸ ', '· ', '✓ ')):
            questions.append((line[0], [line[2:]]))
        elif questions:
            questions[-1][1].append(row)
        else:
            return None
    if len(questions) != int(count[1]):
        return None
    active = [(position, lines) for position, (marker, lines) in enumerate(questions)
              if marker == '▸' or any(OPTION.fullmatch(row) for row in lines[1:])]
    if len(active) != 1:
        return None
    position, lines = active[0]
    body_lines = [lines[0]]
    options = []
    selected = None
    for line in lines[1:]:
        if option := OPTION.fullmatch(line):
            option_id = int(option[3])
            if option_id != len(options) + 1 or option[1] and selected is not None:
                return None
            if option[1]:
                selected = option_id
            item = dict(id=option_id, label=option[4])
            if option[2] is not None:
                item['checked'] = option[2] == 'x'
            options.append(item)
        elif options and line.startswith('      ') and line.strip():
            options[-1]['label'] += ' ' + line.strip()
        elif not options:
            body_lines.append(line.strip())
        elif line.strip():
            return None
    prompt = ' '.join(filter(None, body_lines))
    if (not prompt or len(prompt) > 1000 or any(len(option['label']) > 400 for option in options)):
        return None
    if options:
        if options[-1]['label'] not in (OTHER_FREE if mode == 'other' else OTHER) or selected is None:
            return None
        options[-1]['other'] = True
        if mode == 'other' and selected != options[-1]['id']:
            return None
    elif mode == 'choice':
        return None
    multiple = bool(options and all('checked' in option for option in options))
    if options and any('checked' in option for option in options) != multiple:
        return None
    return dict(kind='question', harness='hermes', mode=mode, body=prompt, choices=options,
                multiple=multiple,
                selected=selected, position=position, count=int(count[1]), draft=draft, control=controls[0])


def parse_codex_question(text):
    """Read a Codex option list only when its live keyboard guide is visible."""
    if not isinstance(text, str) or len(text) > 65536 or 'Question ' not in text:
        return None
    raw = text.splitlines()[-96:]
    rows = [(line, SGR.sub('', line).rstrip()) for line in raw]
    rows = [(line, plain) for line, plain in rows if plain]
    if not rows:
        return None
    control = rows[-1][1].strip()
    footer_size = 1
    if (control == 'esc to interrupt' and len(rows) >= 2
            and rows[-2][1].strip().startswith('tab to add notes | enter to submit ')):
        control = rows[-2][1].strip() + ' ' + control
        footer_size = 2
    mode = 'other' if CODEX_OTHER.fullmatch(control) else 'choice'
    if mode == 'choice' and not CODEX_CHOICE.fullmatch(control):
        return None
    start = next((i for i in range(len(rows)-1-footer_size, -1, -1) if CODEX_HEADER.fullmatch(rows[i][1])), None)
    if start is None:
        return None
    position, count = map(int, CODEX_HEADER.fullmatch(rows[start][1]).groups())
    if position > count:
        return None
    content = rows[start + 1:-footer_size]
    draft = ''
    if mode == 'other':
        editor = next((i for i, (_, line) in enumerate(content) if re.match(r'^  ›(?: |$)(?![1-9]\.)', line)), None)
        if editor is None:
            return None
        style, field = content[editor]
        field = field[3:].lstrip(' ')
        tail = [line for _, line in content[editor + 1:]]
        if field != 'Add notes' or not re.search(r'\x1b\[(?:[01];)*2m', style) or tail:
            draft = '\n'.join([field, *tail]).strip()
        content = content[:editor]
    body = []
    options = []
    selected = None
    for _, line in content:
        if option := CODEX_OPTION.fullmatch(line):
            option_id = int(option[2])
            if option_id != len(options) + 1:
                return None
            if option[1] == '› ':
                if selected is not None:
                    return None
                selected = option_id
            label, *description = re.split(r' {2,}', option[3], maxsplit=1)
            item = dict(id=option_id, label=label)
            if description:
                item['description'] = description[0]
            options.append(item)
        elif options and line.startswith('       ') and options[-1].get('description'):
            options[-1]['description'] += ' ' + line.strip()
        elif not options and line.startswith('  '):
            body.append(line.strip())
        else:
            return None
    prompt = ' '.join(body)
    if not prompt or len(prompt) > 1000 or any(c in prompt for c in ('…', '\ufffd')):
        return None
    if options:
        if (not selected or options[-1]['label'] != CODEX_NONE
                or options[-1].get('description') != 'Optionally, add details in notes (tab)'
                or any(not x['label'] or len(x['label']) > 400 or '…' in x['label'] for x in options)):
            return None
        options[-1]['other'] = True
    elif mode != 'other':
        return None
    return dict(kind='question', harness='codex', mode=mode, body=prompt, choices=options,
                selected=selected, position=position - 1, count=count, multiple=False,
                draft=draft, control=control)


def parse_dsh_question(text):
    """Read the complete expanded dsh question, including the native checkmarks."""
    if not isinstance(text, str) or len(text) > 65536:
        return None
    rows = [SGR.sub('', line).rstrip() for line in text.splitlines()[-96:]]
    rows = [line for line in rows if line]
    if not rows or rows[-1].strip() not in ('esc to interrupt', 'esc 中断'):
        return None
    start = next((i for i in range(len(rows) - 1, -1, -1)
                  if DSH_HEADER.fullmatch(rows[i].strip())), None)
    if start is None:
        return None
    position, count = map(int, filter(None, DSH_HEADER.fullmatch(rows[start].strip()).groups()))
    if position > count:
        return None
    content = rows[start + 1:]
    controls = next((i for i, line in enumerate(content)
                     if line.strip().startswith(tuple(hint + ' · ' for hint in DSH_CHOICE + DSH_OTHER))), None)
    if controls is None:
        return None
    hint = ' '.join(line.strip() for line in content[controls:controls + 3])
    if not (re.search(r' · Enter (?:submit|提交) · ', hint)
            and re.search(r' · Esc (?:cancel|previous question|中断|上一题)', hint)
            and ('fold / click the header' in hint or '折叠' in hint)):
        return None
    mode = 'other' if hint.startswith(DSH_OTHER) else 'choice'
    multiple = any(mark in hint for mark in ('Space multi-select', 'Space 多选', ' · Selected '))
    options = []
    body = []
    editor = None
    selected = None
    for line in content[:controls]:
        if DSH_SCROLL.match(line) or '…' in line and not line.rstrip().endswith('Type directly…'):
            return None
        if option := DSH_OPTION.fullmatch(line):
            if editor:
                return None
            focus, marker, label = option.groups()
            item = dict(id=len(options) + 1, label=label)
            if multiple:
                item['checked'] = marker == '◉'
            if marker == '◉' and not multiple or marker == '●' and multiple:
                return None
            if focus == '❯':
                if selected:
                    return None
                selected = item['id']
            options.append(item)
        elif match := DSH_EDITOR.fullmatch(line):
            if editor:
                return None
            editor = match
            if match[1] == '❯':
                if selected:
                    return None
                selected = len(options) + 1
        elif line.strip() in ('✓ Submit selection (Enter)', '✓ 提交选择 (Enter)') and editor:
            continue
        elif line.startswith('       ') and options and not editor:
            options[-1]['description'] = (options[-1].get('description', '') + ' ' + line.strip()).strip()
        elif not options and not editor and line.startswith('    '):
            if not line.strip().startswith('◈ '):
                body.append(line.strip())
        else:
            return None
    if not editor or not body or not selected or (mode == 'other') != (editor[1] == '❯'):
        return None
    raw = editor[3].strip()
    if not options and mode != 'other' or not multiple and any(x.get('checked') for x in options):
        return None
    if mode == 'choice' and raw == 'Type directly…':
        raw = ''
    item = dict(id=len(options) + 1, label=editor[2], other=True)
    if multiple:
        item['checked'] = bool(raw)
    options.append(item)
    prompt = ' '.join(body)
    if len(options) > 9 or len(prompt) > 1000 or any(len(opt['label']) > 400 for opt in options):
        return None
    # Space is only named when the choices have focus. A visible checkmark or
    # the fixed Selected counter keeps the same shape after focusing the editor.
    return dict(kind='question', harness='dsh', mode=mode, body=prompt, choices=options,
                selected=selected, position=position - 1, count=count, multiple=multiple,
                draft=raw, control=DSH_OTHER[0] if mode == 'other' else DSH_CHOICE[0])

def parse_agy_question(text):
    """Antigravity's question selector and write-in field have distinct footers."""
    if not isinstance(text, str) or len(text) > 65536 or 'Question ' not in text:
        return None
    rows = [SGR.sub('', line).rstrip() for line in text.splitlines()[-96:]]
    rows = [line for line in rows if line]
    if len(rows) < 5 or not AGY_STATUS.fullmatch(rows[-1]):
        return None
    control = rows[-2].strip()
    if control not in (AGY_SINGLE, AGY_MULTIPLE, AGY_EDITOR):
        return None
    heading = next((i for i in range(len(rows) - 3, 1, -1)
                    if AGY_HEADER.fullmatch(rows[i]) and RULE.fullmatch(rows[i - 1]) and rows[i - 2] == 'Question'), None)
    if heading is None:
        return None
    position, count, title = AGY_HEADER.fullmatch(rows[heading]).groups()
    if int(position) > int(count):
        return None
    mode = 'other' if control == AGY_EDITOR else 'choice'
    content = rows[heading + 1:-2]
    draft = ''
    if mode == 'other':
        if '  Your answer:' not in content:
            return None
        editor = content.index('  Your answer:')
        if any(not row.startswith('  ') for row in content[editor + 1:]):
            return None
        draft = '\n'.join(row[2:] for row in content[editor + 1:]).strip()
        content = content[:editor]
    options = []
    selected = None
    body = [title]
    for line in content:
        if option := AGY_OPTION.fullmatch(line):
            focus, number, checkbox, label = option.groups()
            option_id = int(number)
            if option_id != len(options) + 1 or selected is not None and focus == '> ':
                return None
            if focus == '> ':
                selected = option_id
            item = dict(id=option_id, label=label)
            if checkbox is not None:
                item['checked'] = checkbox == 'x'
            options.append(item)
        elif not options and not line.startswith(('> ', '  Your answer:')):
            body.append(line.strip())
        else:
            return None
    if not options or not selected or options[-1]['label'] != 'Write-in...' or 'checked' in options[-1]:
        return None
    multiple = bool(options[:-1]) and all('checked' in item for item in options[:-1])
    if any(('checked' in item) != multiple for item in options[:-1]):
        return None
    if mode == 'choice' and multiple != (control == AGY_MULTIPLE):
        return None
    if mode == 'other' and selected != options[-1]['id']:
        return None
    options[-1]['other'] = True
    if multiple:
        options[-1]['checked'] = bool(draft)
    prompt = ' '.join(body)
    if len(prompt) > 1000 or any(len(option['label']) > 400 or '…' in option['label'] for option in options):
        return None
    return dict(kind='question', harness='agy', mode=mode, body=prompt, choices=options,
                selected=selected, position=int(position) - 1, count=int(count), multiple=multiple,
                draft=draft, control=control)

def question_candidate(text):
    text = SGR.sub('', text)
    return (' needs your input' in text or ' が入力を求めています' in text
            or 'to submit answer' in text or 'tab to add notes | enter to' in text
            or 'tab or esc to clear notes | enter to' in text
            or '📋 Question ' in text or '📋 提问 · 第 ' in text
            or 'Navigate · enter Select · esc Skip' in text or 'space Toggle · enter Submit · esc Skip' in text
            or 'enter Submit · esc Back' in text)


def parse_question(text, harness):
    parser = {'hermes': parse_hermes_question, 'codex': parse_codex_question, 'dsh': parse_dsh_question, 'agy': parse_agy_question}.get(harness)
    return parser(text) if parser else None

def valid_choice(choice):
    if type(choice) is int:
        return 0 <= choice <= 9
    return (isinstance(choice, list) and 1 <= len(choice) <= 9
            and all(type(item) is int and 1 <= item <= 9 for item in choice)
            and choice == sorted(set(choice)))


def same_question(before, after):
    """Compare the logical question across the choice-to-free-text transition."""
    if after is None:
        return False
    fields = ('harness', 'body', 'position', 'count')
    if before['multiple'] != after['multiple']:
        # dsh omits the multi-select hint in an empty write-in editor. With
        # no options checked, that editor looks the same in both modes.
        if not (before['harness'] == 'dsh' and before['multiple']
                and before['mode'] == 'choice' and after['mode'] == 'other'):
            return False

    def options(view):
        return [(option['id'], option['label'], option.get('description'))
                for option in view['choices'] if not option.get('other')]
    return all(before[key] == after[key] for key in fields) and options(before) == options(after)
