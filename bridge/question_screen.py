"""Bounded view of the current Hermes question panel and its answer editor."""

import re


SGR = re.compile(r'\x1b\[[0-9;:]*m')
ITALIC = re.compile(r'\x1b\[(?:[012];)*3m')
TITLE = re.compile(r'^╭─ (.{1,80}(?: needs your input| が入力を求めています)) ─+╮$')
RULE = re.compile(r'^─{8,}$')
COUNT = re.compile(r'^([1-9][0-9]?) (?:questions?|件の質問)$')
OPTION = re.compile(r'^ *(❯ )?([1-9])\. (\S.*)$')
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
            option_id = int(option[2])
            if option_id != len(options) + 1 or option[1] and selected is not None:
                return None
            if option[1]:
                selected = option_id
            options.append(dict(id=option_id, label=option[3]))
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
    return dict(kind='question', harness='hermes', mode=mode, body=prompt, choices=options,
                selected=selected, position=position, count=int(count[1]), draft=draft, control=controls[0])


def same_question(before, after):
    """Compare the logical question across the choice-to-free-text transition."""
    return after is not None and all(before[key] == after[key] for key in ('harness', 'body', 'position', 'count')) and [
        option['label'] for option in before['choices'] if not option.get('other')
    ] == [option['label'] for option in after['choices'] if not option.get('other')]
