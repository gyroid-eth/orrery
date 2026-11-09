"""Reader tail spacing follows Latest visibility without shifting earlier text."""
import json

import pytest

from test_reader_activity import opened, set_activity
from test_reader_tool_fold import cockpit, prepare, event
from test_conversation_review_regressions import wait_reading_layout


LAYOUTS = ['desktop', 'split', 'full', 'phone', 'split-phone']


def layout(js, value):
    if value == 'full':
        js("readerHost.querySelector('.conversation-expand').click()")
        wait_reading_layout(js)


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('view', LAYOUTS)
@pytest.mark.parametrize('tail', ['message', 'work'])
def test_following_tail_has_a_small_bottom_gap(cockpit, theme, view, tail):
    js, wait, client = opened(cockpit, theme, 'desktop' if view == 'full' else view)
    layout(js, view)
    set_activity(js, 'work' if tail == 'work' else None, '36s')
    js("readerScroll.scrollTop=1e9;readerScroll.dispatchEvent(new Event('scroll'))")
    wait_reading_layout(js)
    assert js("reader.querySelector('.conversation-bottom').hidden")
    gap = js("""(()=>{const last=reader.querySelector('.conversation-activity:not([hidden])')||
      reader.querySelector('.conversation-event:last-child');
      return readerScroll.getBoundingClientRect().bottom-last.getBoundingClientRect().bottom})()""")
    assert 0 <= gap <= 16, gap
    assert js('readerScroll.scrollHeight-readerScroll.clientHeight-readerScroll.scrollTop') <= 1


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('view', LAYOUTS)
def test_latest_clearance_keeps_the_tail_above_the_button(cockpit, theme, view):
    rows = [event('bounded-'+str(i), text='Generated bounded reader row '+str(i)) for i in range(800)]
    js, wait, client = prepare(cockpit, theme, 'desktop' if view == 'full' else view, rows)
    layout(js, view)
    set_activity(js, 'work', '36s')
    js("""readerScroll.dispatchEvent(new WheelEvent('wheel'));readerScroll.scrollTop=100;
      readerScroll.dispatchEvent(new Event('scroll'));
      foldPage.events=Array.from({length:200},(_,i)=>({id:'incoming-'+i,kind:'text',role:'assistant',text:'Generated incoming row'}));
      conversationView.refresh();""")
    wait("reader.querySelector('.conversation-latest').title.includes('resume')")
    # A layout restoration can reach the end without a user's resume gesture.
    js("window.dispatchEvent(new Event('resize'))")
    wait_reading_layout(js)
    js('readerScroll.scrollTop=1e9')
    wait_reading_layout(js)
    assert not js("reader.querySelector('.conversation-bottom').hidden")
    assert js("reader.querySelector('.conversation-latest').title.includes('resume')")
    assert js("reader.querySelector('.conversation-activity').getBoundingClientRect().bottom<=reader.querySelector('.conversation-latest').getBoundingClientRect().top")
    assert js("reader.querySelectorAll('.conversation-event').length") == 800


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('view', LAYOUTS)
def test_changing_latest_clearance_keeps_the_same_reading_character(cockpit, theme, view):
    js, wait, client = opened(cockpit, theme, 'desktop' if view == 'full' else view)
    layout(js, view)
    js("""window.bottomRange=document.createRange();
      const text=reader.querySelector('[data-event-id=activity-text20] .conversation-text').firstChild;
      bottomRange.setStart(text,4);bottomRange.setEnd(text,5);
      window.bottomCharacterTop=()=>bottomRange.getBoundingClientRect().top-readerScroll.getBoundingClientRect().top;
      readerScroll.dispatchEvent(new WheelEvent('wheel'));
      readerScroll.scrollTop+=bottomCharacterTop()-32;readerScroll.dispatchEvent(new Event('scroll'));
      readerScroll.focus();packets.length=0;""")
    wait_reading_layout(js)
    before = js('bottomCharacterTop()')
    for hidden in (True, False, True, False):
        js("reader.querySelector('.conversation-bottom').hidden="+json.dumps(hidden))
        wait_reading_layout(js)
        assert abs(js('bottomCharacterTop()')-before) <= 1
        assert js('document.activeElement===readerScroll')
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []
