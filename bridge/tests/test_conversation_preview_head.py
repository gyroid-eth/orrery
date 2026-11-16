"""The preview heading: icon-only buttons in one row, names in aria-label/title.

Needs ORRERY_CDP_URL (see test_conversation_review_regressions). Real cockpit.html
and conversation_preview.js; only the history read and the reference fetch are replaced.
"""
import base64
import io
import json
import os
import time
from pathlib import Path

import pytest
from PIL import Image

from test_conversation_review_regressions import cockpit, stable_roster  # noqa: F401

LONG = 'tm3000-psds-trial-overview-20261116.png'
IMAGE, NOTE = 'a' * 32, 'd' * 32


def image_data():
    output = io.BytesIO()
    Image.new('RGB', (1800, 476), '#548eae').save(output, 'PNG')
    return dict(ok=True, kind='image', mime='image/png', width=1800, height=476, data=base64.b64encode(output.getvalue()).decode())


def prepare(cockpit, width=1100):
    js, wait, client, _, enable = cockpit
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=800, deviceScaleFactor=1, mobile=False)
    stable_roster(js)
    enable(count=1)
    js('conversationView.close()')
    rows = [dict(id='e0', kind='text', role='assistant', text='Files', ts='2026-11-01T04:00:00Z',
                 references=[dict(id=IMAGE, kind='image', label=LONG), dict(id=NOTE, kind='file', label='notes.md')])]
    data = {IMAGE: image_data(), NOTE: dict(ok=True, kind='text', text='# Note\n\nSome **text** here.\n')}
    js('window.hdEvents=%s;window.hdData=%s;' % (json.dumps(rows), json.dumps(data)) + """
      OrreryConversationSource.Source.prototype.read=async()=>({events:hdEvents,before:'start',after:'end'});
      OrreryConversationSource.Source.prototype.reference=(id)=>Promise.resolve(hdData[id]);
      conversationView.open();""")
    wait("document.querySelectorAll('.conversation-event').length===1")
    wait("document.querySelector('.conversation-panel').dataset.conversationLayout==='settled'")
    return js, wait, client


def open_ref(js, wait, index):
    js("document.querySelectorAll('.conversation-file')[%d].click()" % index)
    wait("document.querySelector('.conversation-preview-content')&&!document.querySelector('.conversation-preview-content').textContent.startsWith('Loading')")
    time.sleep(.2)


HEAD = """(()=>[...document.querySelectorAll('.conversation-preview-head > button')].map(b=>{
  const r=b.getBoundingClientRect();return {cls:b.className.split(' ').pop(),text:b.textContent.trim(),label:b.getAttribute('aria-label'),title:b.title,
    top:Math.round(r.top),w:Math.round(r.width),h:Math.round(r.height),svg:b.querySelectorAll('svg').length,pressed:b.getAttribute('aria-pressed')}}))()"""


def test_image_heading_is_one_row_of_square_icon_buttons(cockpit):
    js, wait, client = prepare(cockpit)
    open_ref(js, wait, 0)
    buttons = js(HEAD)
    assert [b['label'] for b in buttons] == ['Reply with reference', 'Full screen', 'Reveal in file manager', 'Close preview']
    assert all(b['text'] == '' and b['svg'] == 1 for b in buttons)
    assert all(b['title'] == b['label'] for b in buttons)
    assert len({b['top'] for b in buttons}) == 1
    assert all(b['w'] == b['h'] for b in buttons)
    assert js("document.querySelector('.conversation-preview-title').getBoundingClientRect().height") > 20  # the long name wraps


def test_markdown_heading_keeps_reply_and_source_in_the_same_row(cockpit):
    js, wait, client = prepare(cockpit)
    open_ref(js, wait, 1)
    buttons = js(HEAD)
    labels = [b['label'] for b in buttons]
    assert labels[0] == 'Reply with reference' and 'Source' in labels and labels[-1] == 'Close preview'
    assert len({b['top'] for b in buttons}) == 1
    source = [b for b in buttons if b['label'] == 'Source'][0]
    assert source['pressed'] == 'false'
    js("document.querySelector('.conversation-preview-source').click()")
    assert js("document.querySelector('.conversation-preview-source').getAttribute('aria-pressed')") == 'true'


def test_narrow_pane_keeps_one_row(cockpit):
    js, wait, client = prepare(cockpit, width=760)
    open_ref(js, wait, 1)
    assert len({b['top'] for b in js(HEAD)}) == 1
    open_ref(js, wait, 0)
    assert len({b['top'] for b in js(HEAD)}) == 1


@pytest.mark.skipif(not os.environ.get('ORRERY_HEAD_SHOTS'), reason='set ORRERY_HEAD_SHOTS=<dir>')
@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_screenshots(cockpit, theme):
    folder = Path(os.environ['ORRERY_HEAD_SHOTS'])
    folder.mkdir(parents=True, exist_ok=True)
    js, wait, client = prepare(cockpit)
    if theme == 'light':
        js("OrreryColorTheme.setPreference('light')")
    def shot(name):
        time.sleep(.4)
        rect = js("(()=>{const r=document.querySelector('.conversation-preview').getBoundingClientRect();return [r.left,r.top,r.width]})()")
        clip = dict(x=rect[0], y=rect[1], width=rect[2], height=150, scale=2)
        (folder / ('%s-%s.png' % (theme, name))).write_bytes(base64.b64decode(client.call('Page.captureScreenshot', format='png', clip=clip)['data']))
    client.call('Emulation.setDeviceMetricsOverride', width=1600, height=800, deviceScaleFactor=2, mobile=False)
    time.sleep(.4)
    open_ref(js, wait, 0)
    shot('image-wide')
    open_ref(js, wait, 1)
    shot('markdown-wide')
    client.call('Emulation.setDeviceMetricsOverride', width=1100, height=800, deviceScaleFactor=2, mobile=False)
    time.sleep(.4)
    open_ref(js, wait, 0)
    shot('image')
    open_ref(js, wait, 1)
    shot('markdown')
