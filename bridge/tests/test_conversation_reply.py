"""Select a real Reader passage, stage it, and use the guarded original composer."""
import base64
import json
import os
from pathlib import Path

import pytest

from test_conversation_review_regressions import cockpit, stable_roster
from test_conversation_inline_images import message, prepare, shown

PASSAGE='Keep the original image pixels unchanged.'


def select(js, client, *, mouse=False):
    rects=js("""(()=>{const box=document.querySelector('[data-event-id=quote] .conversation-text'),walk=document.createTreeWalker(box,NodeFilter.SHOW_TEXT);let node;while(node=walk.nextNode()){if(node.textContent.includes('Keep the original'))break;}const at=node.textContent.indexOf('Keep the original'),range=document.createRange();range.setStart(node,at);range.setEnd(node,at+"""+str(len(PASSAGE))+""");window.selectedReplyRange=range;
      const first=range.cloneRange(),last=range.cloneRange();first.setEnd(node,at+1);last.setStart(node,at+"""+str(len(PASSAGE)-1)+""");
      const a=first.getBoundingClientRect(),b=last.getBoundingClientRect();return {x:a.left+1,y:a.top+a.height/2,endX:b.right-1,endY:b.top+b.height/2};})()""")
    if mouse:
        client.call('Input.dispatchMouseEvent',type='mouseMoved',x=rects['x'],y=rects['y'])
        client.call('Input.dispatchMouseEvent',type='mousePressed',button='left',buttons=1,clickCount=1,x=rects['x'],y=rects['y'])
        for step in range(1,13):
            client.call('Input.dispatchMouseEvent',type='mouseMoved',button='left',buttons=1,x=rects['x']+(rects['endX']-rects['x'])*step/12,y=rects['y']+(rects['endY']-rects['y'])*step/12)
        client.call('Input.dispatchMouseEvent',type='mouseReleased',button='left',buttons=0,clickCount=1,x=rects['endX'],y=rects['endY'])
    else:
        js('getSelection().removeAllRanges();getSelection().addRange(selectedReplyRange);document.dispatchEvent(new Event("selectionchange"))')


def ready(cockpit):
    return prepare(cockpit,[message('quote',PASSAGE+'\n\nUse the saved source when checking the result.'),message('other','The reference will stay above your reply.')])


def stage(js,wait,client):
    select(js,client)
    wait("!document.querySelector('.conversation-selection-reply').hidden")
    js("document.querySelector('.conversation-selection-reply').click()")
    wait("!document.querySelector('.conversation-reply-reference').hidden")


@pytest.mark.parametrize('cockpit,layout',[(False,'desktop'),(True,'phone')],indirect=['cockpit'])
def test_selection_stages_without_sending_and_reply_uses_original_target(cockpit,layout):
    js,wait,client=ready(cockpit)
    js("promptInput.value='Please check this part again.'")
    select(js,client,mouse=layout=='desktop')
    wait("!document.querySelector('.conversation-selection-reply').hidden")
    assert PASSAGE[:-1] in js('getSelection().toString()')
    capture=os.environ.get('ORRERY_REPLY_SCREENSHOTS')
    if capture:
        folder=Path(capture);folder.mkdir(parents=True,exist_ok=True)
        (folder/(layout+'-selection.png')).write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))
    js("document.querySelector('.conversation-selection-reply').click()")
    wait("!document.querySelector('.conversation-reply-reference').hidden")
    js('document.fonts.ready;new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    assert js('promptInput.value')=='Please check this part again.'
    assert js("packets.filter(p=>p.type==='input').length")==0
    assert 'Message reference' in js("document.querySelector('.conversation-reply-label').textContent")
    assert 'Keep the original image pixels unchanged' in js("document.querySelector('.conversation-reply-quote').textContent")
    if layout=='phone':
        assert js("document.querySelector('.conversation-panel').getBoundingClientRect().bottom<=document.querySelector('.promptbar').getBoundingClientRect().top+1")
        assert js("promptInput.getBoundingClientRect().bottom<=visualViewport.height+1")
    if capture:
        (folder/(layout+'-reply.png')).write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))
    js('sendPrompt()')
    wait("packets.filter(p=>p.type==='input').length===2")
    sent=js("packets.filter(p=>p.type==='input')")
    assert sent[0]['paneId']==sent[1]['paneId']=='%901'
    assert '> Keep the original image pixels unchanged' in sent[0]['data']
    assert 'Recorded message: quote' in sent[0]['data']
    assert 'Use the saved source' not in sent[0]['data']
    assert sent[0]['data'].endswith('Please check this part again.\x1b[201~')
    assert sent[1]['data']=='\r'
    assert js("document.querySelector('.conversation-reply-reference').hidden")


@pytest.mark.parametrize('change',["currentAgents[0].history_session_id='new'", "createPane('OtherFixture',{paneId:'%902',windowId:'@902',width:80,height:20});setActive('%902')"])
def test_changed_conversation_or_target_blocks_reference_send(cockpit,change):
    js,wait,client=ready(cockpit);stage(js,wait,client)
    js("promptInput.value='Preserve this draft';"+change+";packets.length=0;sendPrompt()")
    assert js("packets.filter(p=>p.type==='input').length")==0
    assert js('promptInput.value')=='Preserve this draft'
    assert not js("document.querySelector('.conversation-reply-reference').hidden")


def test_reference_does_not_hide_destructive_command_guard_or_clear_draft(cockpit):
    js,wait,client=ready(cockpit);stage(js,wait,client)
    js("promptInput.value='/logout';sendPrompt()")
    assert js('!sendGuard.hidden')
    assert js("packets.filter(p=>p.type==='input').length")==0
    js("sendGuardCancel.click();document.querySelector('.conversation-reply-remove').click()")
    assert js('promptInput.value')=='/logout'
    assert js("document.querySelector('.conversation-reply-reference').hidden")


def test_file_preview_reference_is_explicit_and_does_not_send(cockpit):
    js,wait,_=prepare(cockpit,[shown()])
    js("document.querySelector('.conversation-inline-image').click()")
    wait("document.querySelector('.conversation-preview-image')?.naturalWidth>0")
    js("document.querySelector('.conversation-preview-reply').click()")
    wait("!document.querySelector('.conversation-reply-reference').hidden")
    assert js("document.querySelector('.conversation-reply-quote').textContent")=='figure.png'
    assert 'File reference' in js("document.querySelector('.conversation-reply-label').textContent")
    assert js("packets.filter(p=>p.type==='input').length")==0


def test_binding_change_between_paste_and_enter_cancels_submission(cockpit):
    js,wait,client=ready(cockpit);stage(js,wait,client)
    js("promptInput.value='Check this reference';sendPrompt();currentAgents[0].history_session_id='changed-before-enter'")
    js('new Promise(resolve=>setTimeout(resolve,350))')
    sent=js("packets.filter(p=>p.type==='input')")
    assert len(sent)==1
    assert sent[0]['data'].startswith('\x1b[200~Reference:')
    assert all(p['data']!='\r' for p in sent)


@pytest.mark.parametrize('cockpit',[True],indirect=True)
def test_reference_keeps_the_original_composer_visible_in_light_theme(cockpit):
    js,wait,client=ready(cockpit)
    js("OrreryColorTheme.setPreference('light');promptInput.value='Keep this part unchanged.'")
    stage(js,wait,client)
    wait("document.querySelector('.conversation-reply-reference').getBoundingClientRect().bottom<=promptInput.getBoundingClientRect().top")
    assert js('promptInput.getBoundingClientRect().top')>0
    assert js('promptInput.getBoundingClientRect().bottom<=visualViewport.height')
    capture=os.environ.get('ORRERY_REPLY_SCREENSHOTS')
    if capture:
        js('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        (Path(capture)/'phone-reply-light.png').write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))


def recorded_reply(id, origin, *, timestamp=' · 2026-11-01T04:00:00Z', **extra):
    text = ('Reference: ReviewFixture · assistant' + timestamp + '\r\n'
            + 'Recorded message: ' + origin + '\r\n'
            + '> <img src=x onerror=alert(1)>\r\n> \r\n> Second line\r\n\r\n'
            + 'Keep `label` and https://example.test/path intact.')
    return dict(message(id, text), role='user', **extra)


CARD = 'document.querySelector("[data-event-id=reply] .conversation-reference-link")'
READER = 'document.querySelector(".conversation-panel:not([hidden]) .conversation-scroll")'
ORIGIN = 'document.querySelector("[data-event-id=source]")'


def test_recorded_reference_shows_one_line_and_keyboard_jumps_to_source(cockpit):
    events = [message('source', PASSAGE), message('gap', 'Additional context.\n' * 60), recorded_reply('reply', 'source')]
    js, wait, client = prepare(cockpit, events)
    assert js(CARD + '.querySelector(".conversation-reference-quote").textContent') == '<img src=x onerror=alert(1)>'
    assert js(CARD + '.querySelectorAll("img:not(.conversation-avatar img), .conversation-reference-quote img").length') == 0
    assert js(CARD + '.querySelector("svg").getAttribute("stroke-width")') == '1.5'
    assert js(CARD + '.title').endswith('<img src=x onerror=alert(1)>\n\nSecond line')
    assert js(CARD + '.ariaLabel') == 'Jump to quoted message from ReviewFixture at 13:00 JST'
    assert js(CARD + '.nextElementSibling.querySelector(".conversation-text").textContent') == 'Keep `label` and https://example.test/path intact.'
    assert js(CARD + '.nextElementSibling.querySelector(".conversation-text a").href') == 'https://example.test/path'
    assert js(READER + '.scrollTop') > 200
    js(CARD + '.focus({preventScroll:true})')
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13, text='\r')
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)
    wait(ORIGIN + '.classList.contains("conversation-reference-target")')
    assert js('document.activeElement.dataset.eventId') == 'source'
    assert js(READER + '.scrollTop') < 40
    assert js("packets.filter(p=>p.type==='input').length") == 0
    wait('!' + ORIGIN + '.classList.contains("conversation-reference-target")')


def test_recorded_mobile_reference_shows_the_quote_and_jumps_to_source(cockpit):
    quote = 'Keep "quoted text" | Reply: inside the quote.\nSecond line.'
    body = 'Check again | Reply: this is still the reply.'
    text = ('Reference: ReviewFixture · assistant · 2026-11-01T04:00:00Z | Recorded message: source'
            f' | Quote: {json.dumps(quote)} | Reply: {body}')
    js, wait, _ = prepare(cockpit, [message('source', quote), dict(message('reply', text), role='user')])
    assert js(CARD + '.querySelector(".conversation-reference-quote").textContent') == quote.splitlines()[0]
    assert js(CARD + '.title').endswith(quote)
    assert js(CARD + '.nextElementSibling.querySelector(".conversation-text").textContent') == body
    js(CARD + '.click()')
    wait(ORIGIN + '.classList.contains("conversation-reference-target")')


def test_malformed_and_truncated_references_stay_in_the_original_body(cockpit):
    truncated = recorded_reply('truncated', 'source', truncated=True)
    invalid_date = recorded_reply('bad-date', 'source', timestamp=' · yesterday')
    missing_id = dict(recorded_reply('bad-id', 'source'), text=truncated['text'].replace('Recorded message: source\r\n', ''))
    non_user = dict(recorded_reply('assistant-quote', 'source'), role='assistant')
    empty_body = dict(recorded_reply('empty-body', 'source'), text=truncated['text'].split('\r\n\r\n')[0] + '\r\n\r\n  ')
    malformed_mobile = dict(message('bad-mobile', 'Reference: ReviewFixture · assistant | Recorded message: source'
                                                   ' | Quote: "\\q" | Reply: answer'), role='user')
    js, _, _ = prepare(cockpit, [truncated, invalid_date, missing_id, non_user, empty_body, malformed_mobile])
    assert js("document.querySelectorAll('.conversation-reference-link').length") == 0
    for event in [truncated, invalid_date, missing_id, non_user, empty_body, malformed_mobile]:
        assert 'Reference: ReviewFixture' in js(f'document.querySelector("[data-event-id={event["id"]}] .conversation-text").textContent')


@pytest.mark.parametrize('available', [True, False], ids=['older-source', 'unavailable'])
def test_recorded_reference_uses_older_pages_in_same_conversation(cockpit, available):
    js, wait, _, _, enable = cockpit
    stable_roster(js)
    enable(count=1)
    replies = [message('gap', 'More detail.\n' * 60), recorded_reply('reply', 'source', timestamp='')]
    older = [message('source', PASSAGE)] if available else [message('other-record', 'No source in this record.')]
    js('conversationView.close();window.quoteTail=' + json.dumps(replies) + ';window.quoteOlder=' + json.dumps(older) + ''';
      window.quoteReads=[];OrreryConversationSource.Source.prototype.read=async(name,options)=>{
        quoteReads.push([name,options.before||null]);
        if(options.after)return {unchanged:true,events:[],after:'tail'};
        if(options.before)return {events:quoteOlder,before:'head',after:'tail',has_older:false};
        return {events:quoteTail,before:'previous',after:'tail',has_older:true};
      };conversationView.open();''')
    wait('Boolean(' + CARD + ')')
    assert js(CARD + '.ariaLabel') == 'Jump to quoted message from ReviewFixture'
    js(CARD + '.click()')
    wait('quoteReads.some(([,cursor])=>cursor==="previous") && !' + CARD + '.hasAttribute("aria-busy")')
    names = js('quoteReads.map(([name])=>name)')
    assert len(set(names)) == 1
    if available:
        assert js(ORIGIN + '.classList.contains("conversation-reference-target")')
        assert js('document.activeElement.dataset.eventId') == 'source'
    else:
        assert js(CARD + '.getAttribute("aria-disabled")') == 'true'
        assert 'not in the loaded part of this conversation' in js(CARD + '.title')
        js(CARD + '.click()')
        assert js('quoteReads.filter(([,cursor])=>cursor).length') == 1
