"""Find supported image targets in the public Markdown projected into history."""
import re
from pathlib import PurePath

from conversation_mail import received

IMAGE_EXT = frozenset({'.png', '.jpg', '.jpeg', '.gif', '.webp'})
MAX_MARKDOWN_IMAGES = 8
TARGET = r'\]\((?:<(?P<angle>[^<>\r\n]{0,2000})>|(?P<bare>[^()\s]{0,2000}))(?:[ \t]+"[^"\n]{0,500}")?\)'
INLINE = re.compile(
    r'(?P<escape>\\[\\`!\[\]])|(?P<ticks>`+)|(?P<tag></?[A-Za-z][^<>\n]*>)'
    r'|(?P<tag_open></?[A-Za-z]|<!--)|!\[[^\]\n]{0,500}' + TARGET + r'|(?P<bracket>[\[\]])'
)
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')
CONTAINER = re.compile(r'^ {0,3}(?:> ?|(?:[-+*]|\d{1,9}[.)])[ \t]+)')
CONTROL = re.compile(r'[\x00-\x1f\x7f]')


def local_image_target(target):
    return (target.startswith(('/', '~/')) and not target.startswith('//') and
            len(target) <= 2000 and not CONTROL.search(target) and
            PurePath(target).suffix.lower() in IMAGE_EXT)


def _images(text):
    if '![' not in text:
        return
    lines = text.split('\n')
    if lines[0].rstrip('\r') == '---':
        end = next((i for i, line in enumerate(lines[1:201], 1) if line.rstrip('\r') == '---'), None)
        if end is not None:
            lines = lines[end+1:]
    fence = None
    code = 0
    for source in lines:
        line = source.rstrip('\r')
        for _ in range(8):
            prefix = CONTAINER.match(line)
            if not prefix:
                break
            line = line[prefix.end():]
        mark = FENCE.match(line)
        if fence:
            if mark and mark[1][0] == fence[0] and len(mark[1]) >= len(fence) and not mark[2].strip():
                fence = None
            continue
        if mark:
            fence = mark[1]
            code = 0
            continue
        if not line.strip():
            code = 0
            continue
        if line.startswith(('    ', '\t')):
            continue
        brackets = 0
        for match in INLINE.finditer(line):
            if match['ticks']:
                count = len(match['ticks'])
                if not code or code == count:
                    code = count if not code else 0
            elif not code and not match['escape'] and not match['tag']:
                if match['tag_open']:
                    break  # Ambiguous HTML attributes are not image declarations.
                if match['bracket']:
                    brackets = brackets+1 if match['bracket'] == '[' else max(0, brackets-1)
                    continue
                if brackets:
                    continue
                target = match['angle'] if match['angle'] is not None else match['bare']
                if local_image_target(target):
                    yield target


def markdown_image_targets(event):
    if not event:
        return []
    event = received(event)
    texts = []
    if event.get('kind') == 'text' and event.get('role') == 'assistant' and event.get('variant') != 'update':
        texts.append(event.get('text'))
    texts.extend(item.get('body') for item in event.get('mail', ()) if isinstance(item, dict))
    targets = {}
    for text in texts:
        if isinstance(text, str):
            for target in _images(text):
                targets.setdefault(target, None)
                if len(targets) == MAX_MARKDOWN_IMAGES:
                    return list(targets)
    return list(targets)
