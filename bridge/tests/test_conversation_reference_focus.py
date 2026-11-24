"""Reference selection and the draft use the real cockpit and isolated CDP."""
import base64
import json
import os
from pathlib import Path

import pytest

from test_conversation_inline_images import message, prepare, shown
from test_conversation_review_regressions import cockpit
from test_split_pane_headers import setup


DRAFT = 'A reply to this passage'


def click(client, js, selector):
    point = js('(()=>{const r=document.querySelector('+json.dumps(selector)+
               ').getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()')
    for event in ('mousePressed', 'mouseReleased'):
        client.call('Input.dispatchMouseEvent', type=event, **point, button='left', clickCount=1)


def select_passage(js, wait, selector):
    js('(()=>{const range=document.createRange();range.selectNodeContents(document.querySelector('+
       json.dumps(selector)+'));getSelection().removeAllRanges();getSelection().addRange(range);})()')
    wait("!!document.querySelector('.conversation-selection-reply:not([hidden])')")


def show_preview(js, wait):
    js("document.querySelector('.conversation-inline-image').click()")
    wait("document.querySelector('.conversation-preview-image')?.naturalWidth>0")


def capture(client, name):
    if folder := os.environ.get('REFERENCE_FOCUS_CAPTURE_DIR'):
        data = client.call('Page.captureScreenshot', format='png')['data']
        (Path(folder) / f'{name}.png').write_bytes(base64.b64decode(data))


@pytest.mark.parametrize('entry', ['text', 'preview', 'split'])
def test_reference_moves_caret_to_end_of_the_correct_composer(cockpit, entry):
    if entry == 'split':
        js, wait, client = setup(cockpit, 2)
        js("document.querySelector('.split-cell[data-session=ReviewFixture] .split-history-toggle').click()")
        wait("!!document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-text')")
        js("focusSplitSession('OtherFixture')")
    else:
        js, wait, client = prepare(cockpit, [message('source', 'Use the exact number.'), shown()])
    js('promptInput.value='+json.dumps(DRAFT)+';promptInput.setSelectionRange(3,3)')
    if entry == 'preview':
        show_preview(js, wait)
        button = '.conversation-preview-reply'
    else:
        panel = '.split-cell[data-session=ReviewFixture] ' if entry == 'split' else ''
        select_passage(js, wait, panel+'.conversation-event .conversation-text')
        button = '.conversation-selection-reply:not([hidden])'
    click(client, js, button)
    wait("!document.querySelector('.conversation-reply-reference').hidden")
    before = js("[document.activeElement.id,promptInput.selectionStart,promptInput.selectionEnd,activeSession()]")
    assert before == ['promptInput', len(DRAFT), len(DRAFT), 'ReviewFixture']
    assert js("getSelection().isCollapsed")
    if entry == 'preview':
        assert js("document.querySelector('.conversation-preview').hidden")
    capture(client, 'desktop-caret-'+entry)
    client.call('Input.insertText', text='!')
    assert js("promptInput.value") == DRAFT+'!'
    assert js("packets.filter(p=>p.type==='input').length") == 0


def test_stale_reference_keeps_focus_and_selection(cockpit):
    js, wait, client = prepare(cockpit, [message('source', 'Use the exact number.')])
    js("document.querySelector('.conversation-scroll').focus()")
    select_passage(js, wait, '[data-event-id=source] .conversation-text')
    js("window.beforeFocus=document.activeElement;currentAgents[0].transcript_path='/fixture/replaced.jsonl'")
    click(client, js, '.conversation-selection-reply:not([hidden])')
    assert js("document.activeElement===beforeFocus")
    assert js("getSelection().toString()") == 'Use the exact number.'
    assert js("document.querySelector('.conversation-reply-reference').hidden")

