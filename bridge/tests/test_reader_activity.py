"""Current agent activity stays at the tail without moving a reader's text."""
import json
import time

import pytest
from test_reader_tool_fold import cockpit, prepare, event
from test_conversation_review_regressions import wait_reading_layout


def set_activity(js, state, elapsed=None, running=True):
    js('Object.assign(currentAgents.find(a=>a.name==="ReviewFixture"),'+json.dumps(dict(act_state=state, work_disp=elapsed, running=running))+');document.dispatchEvent(new Event("oc:agents"))')


def opened(cockpit, theme='dark', layout='desktop'):
    rows=[event('activity-text'+str(i), text='Generated reader line '+str(i)+'.\nAnother line to keep reading.') for i in range(40)]
    js,wait,client=prepare(cockpit,theme,layout,rows)
    assert js('reader.querySelector(".conversation-activity")!==null')
    return js,wait,client


@pytest.mark.parametrize('theme',['dark','light'])
@pytest.mark.parametrize('state,elapsed,running,label',[
    ('work','2m05s',True,'Working'),('work',None,True,'Working'),
    ('wait','3m',True,'Waiting'),('ask','3m',True,'Waiting for you'),
    ('question',None,True,'Waiting for you'),(None,'3m',True,None),
    ('unknown','3m',True,None),('work','3m',False,None),
])
def test_activity_uses_the_agent_state_and_only_reported_elapsed(cockpit,theme,state,elapsed,running,label):
    js,wait,client=opened(cockpit,theme)
    set_activity(js,state,elapsed,running)
    assert js('reader.querySelector(".conversation-activity").hidden') == (label is None)
    if label:
        assert js('reader.querySelector(".conversation-activity-label").textContent') == label
        value=js('reader.querySelector(".conversation-activity-time").textContent')
        assert value == ('· '+elapsed if state=='work' and elapsed else '')
        assert js('reader.querySelector(".conversation-activity-label").getAttribute("role")') == 'status'
        assert js('reader.querySelector(".conversation-activity-time").getAttribute("aria-hidden")') == 'true'
    js('Date.now=()=>1e12;document.dispatchEvent(new Event("oc:agents"))')
    assert js('reader.querySelector(".conversation-activity-time").textContent') == ('· '+elapsed if label and state=='work' and elapsed else '')


@pytest.mark.parametrize('theme',['dark','light'])
@pytest.mark.parametrize('layout',['desktop','phone','split','split-phone'])
def test_activity_changes_keep_the_same_character_and_follow_the_tail(cockpit,theme,layout):
    js,wait,client=opened(cockpit,theme,layout)
    js("window.keptActivityNode=reader.querySelector('[data-event-id=activity-text20] .conversation-text').firstChild;window.keptActivityRange=document.createRange();keptActivityRange.setStart(keptActivityNode,4);keptActivityRange.setEnd(keptActivityNode,5);window.activityTop=()=>keptActivityRange.getBoundingClientRect().top-readerScroll.getBoundingClientRect().top;readerScroll.dispatchEvent(new WheelEvent('wheel'));readerScroll.scrollTop+=activityTop()-32;readerScroll.dispatchEvent(new Event('scroll'));readerScroll.focus();packets.length=0")
    time.sleep(.08)
    before=js('activityTop()')
    reads=js('foldReads')
    for state in ['work','question','wait',None,'work']:
        set_activity(js,state,'2m')
        assert abs(js('activityTop()')-before)<=1
        assert js('document.activeElement===readerScroll')
        assert js('keptActivityNode.isConnected')
    assert js('foldReads') == reads
    for state in ['question',None,'work','wait']:
        js('readerScroll.scrollTop=1e9')
        set_activity(js,state,'3m')
        assert js('readerScroll.scrollHeight-readerScroll.clientHeight-readerScroll.scrollTop')<=1
    js('readerScroll.scrollTop=readerScroll.scrollHeight-readerScroll.clientHeight-46;readerScroll.dispatchEvent(new Event("scroll"))')
    top=js('readerScroll.scrollTop')
    set_activity(js,None)
    assert abs(js('readerScroll.scrollTop')-top)<=1
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))")==[]


@pytest.mark.parametrize('theme',['dark','light'])
def test_activity_stays_after_submissions_and_stops_motion(cockpit,theme):
    js,wait,client=opened(cockpit,theme,'split-phone')
    set_activity(js,'work','2m')
    js("document.dispatchEvent(new CustomEvent('oc:prompt-submitted',{detail:{name:'ReviewFixture',id:'generated-send',text:'Generated pending prompt',submittedAt:Date.now()}}))")
    wait("reader.querySelector('.conversation-submission')!==null")
    assert js("reader.querySelector('.conversation-pending').nextElementSibling===reader.querySelector('.conversation-activity')")
    assert js("reader.querySelector('.conversation-activity').getBoundingClientRect().right<=readerScroll.getBoundingClientRect().right")
    assert js("getComputedStyle(reader.querySelector('.conversation-activity-mark i')).animationName") != 'none'
    client.call('Emulation.setEmulatedMedia',features=[dict(name='prefers-reduced-motion',value='reduce')])
    assert js("getComputedStyle(reader.querySelector('.conversation-activity-mark i')).animationName") == 'none'
    client.call('Emulation.setEmulatedMedia',features=[])
    js("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'))")
    assert js("getComputedStyle(reader.querySelector('.conversation-activity-mark i')).animationPlayState") == 'paused'
    js("Object.defineProperty(document,'hidden',{configurable:true,get:()=>false});document.dispatchEvent(new Event('visibilitychange'));currentAgents[0].history_session_id='new-activity-binding';document.dispatchEvent(new Event('oc:agents'))")
    assert js("reader.querySelector('.conversation-submission')===null")


@pytest.mark.parametrize('theme',['dark','light'])
def test_question_uses_existing_alert_red_with_readable_contrast(cockpit,theme):
    js,wait,client=opened(cockpit,theme)
    set_activity(js,'question')
    colors=js("(()=>{const a=reader.querySelector('.conversation-activity'),e=document.createElement('span');e.style.color='var(--theme-status-alert,#d2685e)';reader.appendChild(e);return {actual:getComputedStyle(a).color,expected:getComputedStyle(e).color,bg:getComputedStyle(reader).backgroundColor}})()")
    assert colors['actual']==colors['expected']
    def luminance(color):
        values=[float(x)/255 for x in color[4:-1].split(',')]
        values=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in values]
        return sum(a*b for a,b in zip(values,[.2126,.7152,.0722]))
    low,high=sorted([luminance(colors['actual']),luminance(colors['bg'])])
    ratio=(high+.05)/(low+.05)
    print('activity contrast',theme,colors,ratio)
    assert ratio>=4.5
