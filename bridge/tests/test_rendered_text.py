"""Free text stays literal across cockpit message and warning renderers."""
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess

import pytest

BRIDGE = Path(__file__).resolve().parents[1]


def run_js(source):
    node = shutil.which('node')
    if not node:
        pytest.skip('node is required for renderer checks')
    result = subprocess.run([node], input=source, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def test_mail_fields_and_markdown_use_only_fixed_markup():
    cockpit = (BRIDGE / 'cockpit.html').read_text()
    mail = (BRIDGE / 'mail_view.js').read_text()
    escape = next(line for line in cockpit.splitlines() if line.startswith('function esc('))
    helpers = mail[mail.index('const icons='):mail.index('function normalizeRecipient(')]
    labels = mail[mail.index('function clock('):mail.index('function directRecipients(')]
    renderer = mail[mail.index('function plainMarkdownLinks('):mail.index('function renderDrawer(')]
    value = '<img src=x onerror="marker()"> & "quoted"'
    script = escape + '\nconst OC={esc};\n' + helpers + labels + renderer
    script += '\nconst value=' + json.dumps(value) + ';'
    script += r"""
const message = {
  key: value, sender: value, recipients: [{name: value, kind: value}],
  subject: value, excerpt: value, ts: 2000000000,
  body_md: "**bold** `code`\n" + value + "\n[label](javascript:marker())"
};
console.log(JSON.stringify([detailHtml(message), replyHtml(message, true), drawerLinkSource({
  request: message, replies: [message], inferred: [], followups: []
})]));
"""
    allowed = {
        'div': {'class'}, 'span': {'class', 'title', 'role', 'aria-label', 'aria-hidden', 'data-mail-peer'},
        'h2': set(), 'p': set(), 'code': set(), 'strong': set(),
        'time': {'title'}, 'button': {'class', 'type', 'data-reply'},
        'svg': {'class', 'viewbox', 'aria-hidden'}, 'path': {'d'}, 'circle': {'cx', 'cy', 'r'},
    }
    details, reply, link = run_js(script)
    for rendered in (details, reply, link):
        parsed = Tags()
        parsed.feed(rendered)
        assert all(tag in allowed and set(attrs) <= allowed[tag] for tag, attrs in parsed.tags)
        assert 'javascript:' not in rendered

    parsed = Tags()
    parsed.feed(details)
    assert ''.join(parsed.text).count(value) == 4  # sender, recipient, subject and body
    assert ('span', {'class': 'mail-peer', 'title': value.upper()}) in parsed.tags
    assert [attrs['data-mail-peer'] for _, attrs in parsed.tags if 'data-mail-peer' in attrs] == [value, value]
    parsed = Tags()
    parsed.feed(reply)
    assert parsed.tags[0] == ('button', {'class': 'thread-item', 'type': 'button', 'data-reply': value})
    assert ''.join(parsed.text).count(value) == 3  # sender, recipient and excerpt


def test_composer_warning_escapes_the_complete_word():
    cockpit = (BRIDGE / 'cockpit.html').read_text()
    escape = next(line for line in cockpit.splitlines() if line.startswith('function esc('))
    inspect = cockpit[cockpit.index('const CODEX_DESTRUCTIVE='):cockpit.index('let guardArmed=null;')]
    script = escape + '\n' + inspect
    script += '\nfunction targetProgram(){return "codex";} const SKILL_PREFIX={codex:"$"}; function skillNamed(){return null;}'
    script += '\nconsole.log(JSON.stringify(inspectPrompt("/exit<img/src=x>").reason));'
    parsed = Tags()
    parsed.feed(run_js(script))
    assert parsed.tags == [('code', {})]
    assert '/exit<img/src=x>' in ''.join(parsed.text)
