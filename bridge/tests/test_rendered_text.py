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
    helpers = mail[mail.index('function E('):mail.index('function keyOf(')]
    renderer = mail[mail.index('function plainMarkdownLinks('):mail.index('function threadHtml(')]
    value = '<img src=x onerror="marker()"> & "quoted"'
    script = escape + '\nconst OC={esc};\n' + helpers + '\n' + renderer
    script += '\nfunction exactTime(){return "time";} function relativeLabel(){return "time";}'
    script += '\nfunction highImportance(value){return value==="high"||value==="urgent";}'
    script += '\nconst value=' + json.dumps(value) + ';'
    script += '\nconsole.log(JSON.stringify(detailHtml({sender:value,recipients:[{name:value,kind:value}],subject:value,importance:value,body_md:"**bold** `code`\\n"+value+"\\n[label](javascript:marker())"})));'
    rendered = run_js(script)
    parsed = Tags()
    parsed.feed(rendered)
    assert {tag for tag, _ in parsed.tags} <= {'div', 'span', 'h2', 'p', 'code', 'strong'}
    assert all(set(attrs) <= {'class'} for _, attrs in parsed.tags)
    assert value in ''.join(parsed.text)
    assert 'javascript:' not in rendered


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
