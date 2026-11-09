"""A Reader paused at its retention limit resumes when its reader returns to the end."""
import time

import pytest

from test_conversation_review_regressions import cockpit, stable_roster, wait_reading_layout


def paused_reader(cockpit):
    js, wait, client, _, enable = cockpit
    stable_roster(js);enable(count=1)
    js("""conversationView.close();window.tailChunk=0;window.tailReads=[];
      OrreryConversationSource.Source.prototype.read=async(name,options)=>{
        tailReads.push({before:options.before??null,after:options.after??null});
        return {mode:'cursor',provider:'claude',events:Array.from({length:200},(_,i)=>({
          id:'tail-'+tailChunk+'-'+i,kind:'text',role:'assistant',text:'Generated bounded-window message '+i,
          cursor_before:'c:'+tailChunk+':'+i,cursor_after:'c:'+tailChunk+':'+(i+1)})),
          before:'c:'+tailChunk+':0',after:'c:'+tailChunk+':200',has_older:false};
      };conversationView.open();window.tailScroll=document.querySelector('.conversation-scroll');""")
    wait("document.querySelector('[data-event-id=tail-0-199]')!==null")
    for n in range(1, 4):
        js('tailScroll.scrollTop=1e9;tailChunk=' + str(n) + ';conversationView.refresh()')
        wait("document.querySelector('[data-event-id=tail-" + str(n) + "-199]')!==null")
        wait_reading_layout(js)
    assert js("document.querySelectorAll('.conversation-event').length") == 800
    js("tailScroll.dispatchEvent(new WheelEvent('wheel'));tailScroll.scrollTop=110;tailScroll.dispatchEvent(new Event('scroll'));tailChunk=4;conversationView.refresh()")
    wait("document.querySelector('.conversation-latest').title.includes('resume')")
    wait_reading_layout(js)
    return js, wait, client


@pytest.mark.parametrize('gesture', ['wheel', 'End'])
def test_paused_reader_resumes_at_bottom_without_latest_and_follows_new_rows(cockpit, gesture):
    js, wait, client = paused_reader(cockpit)
    reads = js('tailReads.length')
    if gesture == 'wheel':
        js("tailScroll.dispatchEvent(new WheelEvent('wheel'));tailScroll.scrollTop=1e9;tailScroll.dispatchEvent(new Event('scroll'))")
    else:
        js('tailScroll.focus()')
        client.call('Input.dispatchKeyEvent', type='keyDown', key='End', code='End', windowsVirtualKeyCode=35)
        client.call('Input.dispatchKeyEvent', type='keyUp', key='End', code='End', windowsVirtualKeyCode=35)
    wait("document.querySelector('[data-event-id=tail-4-199]')!==null")
    wait_reading_layout(js)
    assert js('tailReads.length') == reads + 1
    assert js('tailReads[tailReads.length-1]') == {'before': None, 'after': None}
    assert js("document.querySelectorAll('.conversation-event').length") == 200
    assert not js("document.querySelector('.conversation-latest').title.includes('resume')")
    js('tailChunk=5')
    wait("document.querySelector('[data-event-id=tail-5-199]')!==null")
    wait_reading_layout(js)
    assert js('tailScroll.scrollHeight-tailScroll.clientHeight-tailScroll.scrollTop') <= 1
    assert js("packets.filter(p=>p.type==='input')") == []


def test_reading_above_the_end_keeps_reader_paused(cockpit):
    js, wait, client = paused_reader(cockpit)
    reads = js('tailReads.length')
    for offset in (200, 400):
        js("tailScroll.dispatchEvent(new WheelEvent('wheel'));tailScroll.scrollTop=" + str(offset) + ";tailScroll.dispatchEvent(new Event('scroll'));conversationView.refresh()")
    time.sleep(.25)
    assert js('tailReads.length') == reads
    assert js("document.querySelector('.conversation-latest').title.includes('resume')")
    assert js("document.querySelector('[data-event-id=tail-4-199]')") is None


def test_programmatic_layout_scroll_does_not_resume_a_paused_reader(cockpit):
    js, wait, client = paused_reader(cockpit)
    reads = js('tailReads.length')
    # Layout restoration has not received a fresh scrolling gesture.
    js("window.dispatchEvent(new Event('resize'))")
    wait_reading_layout(js)
    js("tailScroll.scrollTop=1e9;tailScroll.dispatchEvent(new Event('scroll'))")
    time.sleep(.25)
    assert js('tailReads.length') == reads
