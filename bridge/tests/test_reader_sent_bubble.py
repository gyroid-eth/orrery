"""Sent prompts use a quiet bubble while their provider record is pending."""
import json
import time

import pytest
from test_conversation_submissions import cockpit,prepare
from test_conversation_review_regressions import wait_reading_layout


def send(js,wait,text='Generated prompt to check the Reader layout.'):
    js('promptInput.value='+json.dumps(text)+';sendPrompt()')
    wait('receipts.length===1')
    assert js("reader.querySelector('.conversation-submission').dataset.state") == 'awaiting'


@pytest.mark.parametrize('theme',['dark','light'])
@pytest.mark.parametrize('split',[False,True])
def test_sent_bubble_has_no_dashed_frame_and_promotes_only_after_enter(cockpit,theme,split):
    js,wait,client=prepare(cockpit,split=split)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    if split:client.call('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=False)
    send(js,wait)
    style=js("(()=>{const s=getComputedStyle(reader.querySelector('.conversation-submission'));return {border:s.borderTopStyle,radius:parseFloat(s.borderTopLeftRadius)}})()")
    assert style['border']=='solid' and style['radius']>=10
    assert js("reader.querySelector('.conversation-submission-note').hidden")
    js('clock+=60001;receiptTimers.forEach(f=>f())')
    assert js("reader.querySelector('.conversation-submission').dataset.state") == 'late'
    assert js("reader.querySelector('.conversation-submission').textContent.includes('Not recorded yet')")


@pytest.mark.parametrize('theme',['dark','light'])
def test_long_prompt_expansion_and_selection_survive_poll(cockpit,theme):
    js,wait,client=prepare(cockpit,split=True)
    client.call('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=False)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    text='Generated prompt\n/workspace/project/'+('long-path-part/'*25)+'file.txt\nKeep all the original lines.'
    send(js,wait,text)
    wait("!reader.querySelector('.conversation-submission-more').hidden")
    js("window.keptBubble=reader.querySelector('.conversation-submission');window.more=keptBubble.querySelector('.conversation-submission-more');more.focus();packets.length=0")
    client.call('Input.dispatchKeyEvent',type='keyDown',key='Enter',windowsVirtualKeyCode=13,text='\r')
    client.call('Input.dispatchKeyEvent',type='keyUp',key='Enter',windowsVirtualKeyCode=13)
    assert js("more.getAttribute('aria-expanded')") == 'true'
    js("window.selectedPrompt=keptBubble.querySelector('.conversation-text').firstChild;window.promptRange=document.createRange();promptRange.setStart(selectedPrompt,0);promptRange.setEnd(selectedPrompt,9);getSelection().removeAllRanges();getSelection().addRange(promptRange);conversationView.refresh();queueStageFit(activeId)")
    time.sleep(.15)
    assert js("keptBubble===reader.querySelector('.conversation-submission')&&more.isConnected")
    assert js("more.getAttribute('aria-expanded')") == 'true'
    assert js('document.activeElement===more')
    assert js('getSelection().toString()') == 'Generated'
    assert js("keptBubble.querySelector('.conversation-text').textContent") == text
    assert js("keptBubble.scrollWidth<=keptBubble.clientWidth+1")
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


@pytest.mark.parametrize('failure',['paste','enter','removed','guard'])
def test_sending_attempt_never_leaves_a_sent_bubble_after_failure(cockpit,failure):
    js,wait,client=prepare(cockpit)
    js("window.sendAttempts=[];document.addEventListener('oc:prompt-sending',e=>sendAttempts.push(e.detail));window.cancelledAttempts=[];document.addEventListener('oc:prompt-send-cancelled',e=>cancelledAttempts.push(e.detail))")
    if failure=='paste':js('send=()=>false')
    if failure=='enter':js("send=p=>p.data!=='\\r'")
    js('promptInput.value='+json.dumps('/logout' if failure=='guard' else 'Generated failed send')+';sendPrompt()'+(";panes.delete('%901')" if failure=='removed' else ''))
    time.sleep(.35)
    assert js('sendAttempts.length') == (1 if failure in ['enter','removed'] else 0)
    assert js('cancelledAttempts.length') == (1 if failure in ['enter','removed'] else 0)
    assert js('receipts.length')==0
    assert js("reader.querySelector('.conversation-submission')===null")


def test_sending_uses_a_separate_attempt_and_then_the_confirmed_receipt(cockpit):
    js,wait,client=prepare(cockpit)
    js("window.finishSend=null;window.nativeSendTimeout=setTimeout;window.setTimeout=(fn,ms,...args)=>{if(ms===250){finishSend=fn;return 0}return nativeSendTimeout(fn,ms,...args)};window.startAttempts=[];document.addEventListener('oc:prompt-sending',e=>startAttempts.push(e.detail));promptInput.value='Generated delayed Enter';sendPrompt()")
    assert js("reader.querySelector('.conversation-submission')?.dataset.state") == 'sending'
    assert js('receipts.length')==0
    js("window.sendingBubble=reader.querySelector('.conversation-submission')")
    js('finishSend()')
    assert js('receipts.length')==1
    assert js('receipts[0].attemptId===startAttempts[0].attemptId')
    assert js("reader.querySelectorAll('.conversation-submission').length")==1
    assert js("reader.querySelector('.conversation-submission').dataset.state") == 'awaiting'
    assert js("sendingBubble===reader.querySelector('.conversation-submission')")


@pytest.mark.parametrize('theme',['dark','light'])
def test_unmatched_note_is_small_and_the_bubble_stays_before_activity(cockpit,theme):
    js,wait,client=prepare(cockpit)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+');Object.assign(currentAgents[0],{running:true,act_state:"work",work_disp:"2m"});document.dispatchEvent(new Event("oc:agents"))')
    send(js,wait)
    js("OrreryConversationSource.Source.prototype.read=async()=>({events:[{id:'different-new',role:'user',kind:'text',text:'Different generated record',ts:new Date(clock+1000).toISOString()}],after:'different'});conversationView.refresh()")
    wait("reader.querySelector('.conversation-submission')?.dataset.state==='unmatched'")
    assert js("reader.querySelector('.conversation-submission-note').textContent") == 'Check the conversation above.'
    assert js("reader.querySelector('.conversation-submission-note').hidden") is False
    assert js("reader.querySelector('.conversation-pending').nextElementSibling===reader.querySelector('.conversation-activity')")


@pytest.mark.parametrize('change',['binding','disabled','closed','reopened'])
def test_delayed_confirmation_cannot_cross_a_reader_binding(cockpit,change):
    js,wait,client=prepare(cockpit)
    js("window.nativeSendTimeout=setTimeout;window.setTimeout=(fn,ms,...args)=>{if(ms===250){window.finishBubbleSend=fn;return 0}return nativeSendTimeout(fn,ms,...args)};promptInput.value='Generated bound attempt';sendPrompt()")
    assert js("reader.querySelector('.conversation-submission').dataset.state") == 'sending'
    if change=='binding':
        js("currentAgents[0].history_session_id='next-generated-session';document.dispatchEvent(new Event('oc:agents'))")
    elif change=='disabled':
        js("conversationEnabled.checked=false;conversationEnabled.dispatchEvent(new Event('change'))")
    else:
        js('conversationView.close()'+(';conversationView.open()' if change=='reopened' else ''))
    js('finishBubbleSend()')
    assert js("reader.querySelectorAll('.conversation-submission').length") == (1 if change=='reopened' else 0)
    if change=='reopened':
        assert js("reader.querySelector('.conversation-submission').dataset.state") == 'awaiting'


@pytest.mark.parametrize('theme',['dark','light'])
@pytest.mark.parametrize('split',[False,True])
def test_bubble_updates_cancel_and_dismiss_keep_the_reading_character(cockpit,theme,split):
    js,wait,client=prepare(cockpit,split=split)
    if split:client.call('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=False)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    rows=[dict(id='kept'+str(i),role='assistant',kind='text',text='Generated readable paragraph '+str(i)+'.\nA second line with more words to read.') for i in range(60)]
    js('conversationView.close();window.bubbleRows='+json.dumps(rows)+';OrreryConversationSource.Source.prototype.read=async()=>({mode:"cursor",events:bubbleRows,after:"bubble-tail"});conversationView.open()')
    wait("reader.querySelector('[data-event-id=kept30]')!==null")
    send(js,wait)
    wait_reading_layout(js)
    js("""window.readerScroll=reader.querySelector('.conversation-scroll');
      window.keptBubbleNode=reader.querySelector('[data-event-id=kept30] .conversation-text').firstChild;
      window.keptBubbleRange=document.createRange();keptBubbleRange.setStart(keptBubbleNode,4);keptBubbleRange.setEnd(keptBubbleNode,5);
      window.bubbleTop=()=>keptBubbleRange.getBoundingClientRect().top-readerScroll.getBoundingClientRect().top;
      readerScroll.dispatchEvent(new WheelEvent('wheel'));readerScroll.scrollTop+=bubbleTop()-32;readerScroll.dispatchEvent(new Event('scroll'));readerScroll.focus();packets.length=0;
    """)
    time.sleep(.08)
    before=js('bubbleTop()')
    def unchanged():
        wait_reading_layout(js)
        assert abs(js('bubbleTop()')-before)<=1
        assert js('document.activeElement===readerScroll&&keptBubbleNode.isConnected')
    js('clock+=60001;receiptTimers.forEach(f=>f())')
    unchanged()
    js("document.dispatchEvent(new CustomEvent('oc:prompt-sending',{detail:{attemptId:'cancelled-generated-attempt',name:'ReviewFixture',text:'Generated temporary attempt',startedAt:clock}}))")
    unchanged()
    js("document.dispatchEvent(new CustomEvent('oc:prompt-send-cancelled',{detail:{attemptId:'cancelled-generated-attempt'}}))")
    unchanged()
    js("bubbleRows.push({id:'unrelated-record',role:'user',kind:'text',text:'Different generated user record',ts:new Date(clock+1000).toISOString()});conversationView.refresh()")
    wait("reader.querySelector('.conversation-submission-dismiss')!==null")
    unchanged()
    js("reader.querySelector('.conversation-submission-dismiss').click()")
    unchanged()
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


def test_preview_limit_and_links_remain_truthful(cockpit):
    js,wait,client=prepare(cockpit)
    text='Generated prompt https://example.com/check\n'+('Original long line\n'*120)
    send(js,wait,text)
    assert js("reader.querySelector('.conversation-submission-text').textContent") == text[:1000]+'…'
    assert js("reader.querySelector('.conversation-submission a').href") == 'https://example.com/check'
    wait("!reader.querySelector('.conversation-submission-more').hidden")
    js("reader.querySelector('.conversation-submission-more').click()")
    assert js("reader.querySelector('.conversation-submission-more').textContent") == 'Show less'
    assert js("reader.querySelector('.conversation-submission-text').textContent") == text[:1000]+'…'


def test_more_losing_its_overflow_keeps_focus_before_hiding(cockpit):
    js,wait,client=prepare(cockpit,split=True)
    client.call('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=False)
    send(js,wait,'Generated prompt to check wrapping and keyboard focus in a narrow Reader pane.')
    wait("!reader.querySelector('.conversation-submission-more').hidden")
    js("window.more=reader.querySelector('.conversation-submission-more');more.focus();packets.length=0")
    client.call('Emulation.setDeviceMetricsOverride',width=1600,height=844,deviceScaleFactor=1,mobile=False)
    wait('more.hidden')
    assert js("document.activeElement===reader.querySelector('.conversation-scroll')")
    js('queueStageFit(activeId)')
    time.sleep(.12)
    for kind in ['keyDown','keyUp']:
        client.call('Input.dispatchKeyEvent',type=kind,key='q',code='KeyQ',windowsVirtualKeyCode=81,**({'text':'q'} if kind=='keyDown' else {}))
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


def test_focusing_a_link_in_clamped_text_exposes_it(cockpit):
    js,wait,client=prepare(cockpit)
    send(js,wait,'Generated prompt line\n'*8+'https://example.com/keyboard')
    wait("!reader.querySelector('.conversation-submission-more').hidden")
    js("window.bubbleLink=reader.querySelector('.conversation-submission a');bubbleLink.focus()")
    assert js("reader.querySelector('.conversation-submission').classList.contains('submission-expanded')")
    assert js("(()=>{const l=bubbleLink.getBoundingClientRect(),s=reader.querySelector('.conversation-scroll').getBoundingClientRect();return l.top>=s.top&&l.bottom<=s.bottom})()")
    assert js('document.activeElement===bubbleLink')


@pytest.mark.parametrize('split',[False,True])
@pytest.mark.parametrize('control',['more','link'])
def test_matching_first_receipt_keeps_focus_in_the_surviving_bubble(cockpit,split,control):
    js,wait,client=prepare(cockpit,split=split)
    if split:client.call('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=False)
    js("sentText='First generated prompt';newRecord.text=sentText;promptInput.value=sentText;sendPrompt()")
    wait('receipts.length===1')
    text='Second generated prompt\n'+'Keep this line visible.\n'*12+'https://example.com/second'
    js('promptInput.value='+json.dumps(text)+';sendPrompt()')
    wait('receipts.length===2')
    wait("reader.querySelectorAll('.conversation-submission').length===2&&!reader.querySelectorAll('.conversation-submission-more')[1].hidden")
    selector='.conversation-submission-more' if control=='more' else 'a'
    js("window.survivingBubble=reader.querySelectorAll('.conversation-submission')[1];window.keptBubbleControl=survivingBubble.querySelector("+json.dumps(selector)+");keptBubbleControl.focus()")
    wait_reading_layout(js)
    js('packets.length=0;turnDone=true;conversationView.refresh()')
    wait("reader.querySelectorAll('.conversation-submission').length===1")
    assert js("reader.querySelector('.conversation-submission')===survivingBubble&&keptBubbleControl.isConnected")
    assert js('document.activeElement===keptBubbleControl')
    js('queueStageFit(activeId)')
    time.sleep(.2)
    for kind in ['keyDown','keyUp']:
        client.call('Input.dispatchKeyEvent',type=kind,key='q',code='KeyQ',windowsVirtualKeyCode=81,**({'text':'q'} if kind=='keyDown' else {}))
    assert js('document.activeElement===keptBubbleControl')
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []
