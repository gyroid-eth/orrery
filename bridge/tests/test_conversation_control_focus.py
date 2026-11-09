"""Removing Reader controls must never hand subsequent keys to a terminal."""
import json
import time

import pytest
from test_conversation_review_regressions import cockpit, wait_reading_layout
from test_conversation_submissions import prepare as prepare_submission
from test_conversation_markdown import prepare


def key(client, value):
    code = {'Enter': 13, ' ': 32, 'q': 81}[value]
    name = {'Enter': 'Enter', ' ': 'Space', 'q': 'KeyQ'}[value]
    for kind in ['keyDown', 'keyUp']:
        client.call('Input.dispatchKeyEvent', type=kind, key=value, code=name,
                    windowsVirtualKeyCode=code, **({'text': '\r' if value == 'Enter' else value} if kind == 'keyDown' else {}))


def assert_reader_owns_next_key(js, client):
    js('queueStageFit(activeId)')
    time.sleep(.2)
    key(client, 'q')
    assert js("!!document.activeElement.closest('.conversation-panel,.conversation-notices')")
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


@pytest.mark.parametrize('activation', ['Enter', ' ', 'pointer'])
def test_dismiss_keeps_focus_before_removing_its_button(cockpit, activation):
    js, wait, client = prepare_submission(cockpit)
    js("newRecord.text='Different recorded prompt';promptInput.value=sentText;sendPrompt()")
    wait('receipts.length===1')
    js('turnDone=true;conversationView.refresh()')
    wait("reader.querySelector('.conversation-submission-dismiss')!==null")
    wait_reading_layout(js)
    js("packets.length=0;reader.querySelector('.conversation-submission-dismiss').focus()")
    if activation == 'pointer':
        point = js("(()=>{const b=reader.querySelector('.conversation-submission-dismiss');b.scrollIntoView({block:'nearest'});const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
        for kind in ['mousePressed', 'mouseReleased']:
            client.call('Input.dispatchMouseEvent', type=kind, button='left', clickCount=1, **point)
    else:
        key(client, activation)
    wait("reader.querySelector('.conversation-submission')===null")
    assert_reader_owns_next_key(js, client)


@pytest.mark.parametrize('selector', ['.conversation-code-copy', '.conversation-output-toggle', '.conversation-system-toggle'])
@pytest.mark.parametrize('changed', [False, True])
def test_snapshot_preserves_reader_focus_when_controls_are_moved_or_replaced(cockpit, selector, changed):
    js, wait, client = prepare(cockpit, 'placeholder')
    rows = [dict(id='code', role='assistant', kind='text', text='```sh\necho generated\n```'),
            dict(id='output', role='user', kind='text', text='<bash-stdout>'+'generated\n'*20+'</bash-stdout>'),
            dict(id='notice', role='system', kind='system', text='Background task completed', system_detail='Generated task details')]
    js('conversationView.close();window.focusRows='+json.dumps(rows)+';OrreryConversationSource.Source.prototype.read=async()=>({mode:"snapshot",provider:"hermes",events:focusRows,after:"focus"});conversationView.open()')
    wait("document.querySelector('.conversation-system-toggle')!==null")
    wait_reading_layout(js)
    js("Object.defineProperty(navigator,'clipboard',{value:{writeText:async()=>{}},configurable:true});packets.length=0;document.querySelector("+json.dumps(selector)+').focus()')
    key(client, 'Enter')
    assert_reader_owns_next_key(js, client)
    if changed:
        js("focusRows=focusRows.map(e=>({...e,text:e.text.replace('generated','updated'),system_detail:'Updated task details'}))")
    # A snapshot moves unchanged nodes through a fragment as well as replacing
    # changed rows; either operation can remove the focused button from DOM.
    js('packets.length=0;conversationView.refresh()')
    time.sleep(.1)
    assert_reader_owns_next_key(js, client)
