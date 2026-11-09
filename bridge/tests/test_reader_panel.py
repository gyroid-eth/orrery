"""Reader controls stay with their pane; notices and navigation stay usable."""
import json
import time

import pytest
from test_conversation_review_regressions import cockpit, stable_roster, wait_reading_layout
from test_split_pane_headers import setup


def opened(cockpit):
    js, wait, client, requests, enable = cockpit
    stable_roster(js)
    enable(count=80)
    return js, wait, client


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_reader_header_icons_toggle_and_full_width(cockpit, theme):
    js, wait, client = opened(cockpit)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    assert js('document.querySelector("#conversationToggle svg")!==null')
    assert js('document.getElementById("conversationToggle").getAttribute("aria-pressed")') == 'true'
    assert js('document.getElementById("conversationToggle").getAttribute("aria-label")') == 'Close Reader'
    assert js('document.querySelectorAll(".conversation-panel .conversation-head").length') == 0
    assert js('document.querySelector(".conversation-toolbar").hidden')
    assert js('document.querySelector(".scr-head .conversation-expand:not([hidden])")!==null')
    js('document.querySelector(".scr-head .conversation-expand").click()')
    assert js('document.querySelector(".screen").classList.contains("conversation-full")')
    assert js('document.querySelector(".scr-head .conversation-expand").getAttribute("aria-pressed")') == 'true'
    assert js('document.querySelector(".scr-head .conversation-expand").getAttribute("aria-label")') == 'Restore side panel'
    js('document.querySelector(".scr-head .conversation-expand").focus()')
    assert js('getComputedStyle(document.activeElement).outlineStyle') != 'none'
    js('queueStageFit(activeId)')
    time.sleep(.2)
    assert js('document.activeElement.classList.contains("conversation-expand")')
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', text='\r', windowsVirtualKeyCode=13)
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', windowsVirtualKeyCode=13)
    assert not js('document.querySelector(".screen").classList.contains("conversation-full")')
    js('document.getElementById("conversationToggle").focus()')
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', text='\r', windowsVirtualKeyCode=13)
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', windowsVirtualKeyCode=13)
    assert js('document.querySelector(".conversation-panel").hidden')
    assert js('document.querySelector(".scr-head .conversation-expand").hidden')
    assert js('document.getElementById("conversationToggle").getAttribute("aria-label")') == 'Reader'
    assert js('document.querySelector("#panePopout svg")!==null&&document.querySelector("#paneReturn svg")!==null')


def test_latest_shows_only_when_reading_earlier_and_keeps_the_tail_clear(cockpit):
    js, wait, client = opened(cockpit)
    wait('document.querySelector(".conversation-bottom").hidden')
    js('''{const s=document.querySelector('.conversation-scroll');s.dispatchEvent(new WheelEvent('wheel'));s.scrollTop=0;s.dispatchEvent(new Event('scroll'));}''')
    wait('!document.querySelector(".conversation-bottom").hidden')
    assert js("parseFloat(getComputedStyle(document.querySelector('.conversation-scroll')).paddingRight)") == 18
    assert js("parseFloat(getComputedStyle(document.querySelector('.conversation-scroll')).paddingBottom)") >= 42
    assert js("getComputedStyle(document.querySelector('.conversation-latest')).backgroundColor") == js("getComputedStyle(document.querySelector('.conversation-panel')).backgroundColor")
    assert js('document.querySelector(".conversation-latest").getAttribute("aria-label").startsWith("Latest")')
    js('document.querySelector(".conversation-latest").focus()')
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', text='\r', windowsVirtualKeyCode=13)
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', windowsVirtualKeyCode=13)
    wait('document.querySelector(".conversation-bottom").hidden')
    assert js('document.activeElement.classList.contains("conversation-scroll")')


def test_status_and_retry_stay_available(cockpit):
    js, wait, client = opened(cockpit)
    js('conversationView.close();window.readerFail=true;OrreryConversationSource.Source.prototype.read=async()=>{if(readerFail)throw new Error("Generated read failure");return {events:[{id:"retry-row",kind:"text",role:"assistant",text:"Recovered"}],after:"one",before:"zero",has_older:true}};conversationView.open()')
    wait('!document.querySelector(".conversation-retry").hidden')
    assert js('document.querySelector(".conversation-thread > .conversation-toolbar")!==null')
    assert js('!document.querySelector(".conversation-toolbar").hidden')
    js('readerFail=false;document.querySelector(".conversation-retry").click()')
    wait('document.querySelector("[data-event-id=retry-row]")!==null')
    assert js('document.querySelector(".conversation-toolbar").hidden')
    assert js('!document.querySelector(".conversation-older").hidden')


def test_split_reader_icons_and_expansion_belong_to_the_owner(cockpit):
    js, wait, client = setup(cockpit, 2)
    assert js('document.querySelectorAll(".split-history-toggle svg").length') == 2
    js('document.querySelector(".split-cell[data-session=ReviewFixture] .split-history-toggle").click()')
    wait('document.querySelector(".split-cell[data-session=ReviewFixture] .conversation-event")!==null')
    assert js('document.querySelector(".split-cell[data-session=ReviewFixture] .split-cell-actions .conversation-expand:not([hidden])")!==null')
    js('document.querySelector(".split-cell[data-session=ReviewFixture] .conversation-expand").click()')
    assert js('document.querySelector(".split-cell[data-session=ReviewFixture]").classList.contains("conversation-full")')
    assert not js('document.querySelector(".split-cell[data-session=OtherFixture]").classList.contains("conversation-full")')
    assert js('document.querySelectorAll(".split-pane-window svg").length') == 2


def pause_at_reader_limit(js, wait):
    for n in range(2, 5):
        js("document.querySelector('.conversation-scroll').scrollTop=1e9;conversationView.refresh()")
        wait("document.querySelectorAll('.conversation-event').length==="+str(n*200))
    js("document.querySelector('.conversation-scroll').dispatchEvent(new WheelEvent('wheel'));document.querySelector('.conversation-scroll').scrollTop=110;conversationView.refresh()")
    wait("document.querySelector('.conversation-latest').getAttribute('aria-label').includes('resume')")


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('mode', ['fresh_tail', 'cursor'])
def test_initial_long_reader_stops_at_the_tail_without_latest(cockpit, theme, mode):
    js, wait, client, requests, enable = cockpit
    stable_roster(js)
    enable(mode=mode, count=200)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    wait_reading_layout(js)
    assert js("(()=>{const s=document.querySelector('.conversation-scroll');return s.scrollHeight-s.clientHeight-s.scrollTop<1})()")
    assert js("document.querySelector('.conversation-bottom').hidden")


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('notice', ['fresh', 'error', 'paused'])
def test_notices_and_retry_remain_visible_in_a_long_reader(cockpit, theme, notice):
    js, wait, client, requests, enable = cockpit
    stable_roster(js)
    enable(mode='fresh_tail' if notice == 'fresh' else 'cursor', count=200)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    if notice == 'paused':
        pause_at_reader_limit(js, wait)
        assert js("document.querySelector('.conversation-scroll').scrollTop") == 110
    elif notice == 'error':
        js("OrreryConversationSource.Source.prototype.read=async()=>{throw new Error('Generated read failure')};conversationView.refresh()")
        wait("!document.querySelector('.conversation-retry').hidden")
    else:
        wait("document.querySelector('.conversation-status').textContent.includes('Fresh')")
    assert js("document.querySelector('.conversation-scroll').scrollTop>100")
    assert js("""(()=>{const s=document.querySelector('.conversation-scroll').getBoundingClientRect(),t=document.querySelector('.conversation-toolbar').getBoundingClientRect();return t.height>0&&t.top>=s.top&&t.bottom<=s.bottom})()""")
    if notice != 'paused':
        assert js("(()=>{const s=document.querySelector('.conversation-scroll');return s.scrollHeight-s.clientHeight-s.scrollTop<1})()")
    if notice == 'error':
        assert js("""(()=>{const b=document.querySelector('.conversation-retry'),r=b.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===b})()""")


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_paused_latest_enter_keeps_focus_in_the_reader_after_fit(cockpit, theme):
    js, wait, client, requests, enable = cockpit
    stable_roster(js)
    enable(count=200)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    pause_at_reader_limit(js, wait)
    js("document.querySelector('.conversation-latest').focus();packets.length=0")
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', text='\r', windowsVirtualKeyCode=13)
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', windowsVirtualKeyCode=13)
    wait("document.querySelectorAll('.conversation-event').length===200")
    assert js("document.activeElement.classList.contains('conversation-scroll')")
    js('queueStageFit(activeId)')
    time.sleep(.2)
    assert js("document.activeElement.classList.contains('conversation-scroll')")
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


def line_top(js):
    return js("""(()=>{const s=document.querySelector('.conversation-scroll'),r=document.createRange();r.setStart(readerAnchorNode,11);r.setEnd(readerAnchorNode,12);return {id:readerAnchorId,top:r.getBoundingClientRect().top-s.getBoundingClientRect().top}})()""")


def fail_read(js, wait, message='Generated read failure'):
    js('window.readerFailure='+json.dumps(message)+';OrreryConversationSource.Source.prototype.read=async()=>{throw new Error(readerFailure)};conversationView.refresh()')
    wait("!document.querySelector('.conversation-retry').hidden")


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('transition', ['show', 'recover', 'older'])
@pytest.mark.parametrize('message', ['Generated read failure', 'Generated read failure with more context. '*10], ids=['short', 'long'])
def test_notice_transition_preserves_the_same_read_character(cockpit, theme, transition, message):
    js, wait, client, requests, enable = cockpit
    stable_roster(js)
    enable(count=80)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    wait_reading_layout(js)
    js("""window.readerAnchorText=document.querySelectorAll('.conversation-text')[20];window.readerAnchorNode=readerAnchorText.firstChild;window.readerAnchorId=readerAnchorText.closest('.conversation-event').dataset.eventId;const s=document.querySelector('.conversation-scroll');s.dispatchEvent(new WheelEvent('wheel'));s.scrollTop+=readerAnchorText.getBoundingClientRect().top-s.getBoundingClientRect().top-30;s.dispatchEvent(new Event('scroll'));""")
    if transition != 'show':
        fail_read(js, wait, message)
    before = line_top(js)
    if transition == 'show':
        fail_read(js, wait, message)
    elif transition == 'recover':
        js("OrreryConversationSource.Source.prototype.read=async()=>({events:[],mode:'cursor',after:'recovered',has_older:true});document.querySelector('.conversation-retry').click()")
        wait("document.querySelector('.conversation-toolbar').hidden")
    else:
        js("OrreryConversationSource.Source.prototype.read=async()=>({events:Array.from({length:40},(_,i)=>({id:'older-'+i,kind:'text',role:'assistant',text:'Earlier generated message '+i})),mode:'cursor',before:'older-start',after:'older-end',has_older:true});document.querySelector('.conversation-older').click()")
        wait("document.querySelectorAll('.conversation-event').length===120")
        wait("document.querySelector('.conversation-toolbar').hidden")
    time.sleep(.15)
    after = line_top(js)
    assert after['id'] == before['id']
    assert abs(after['top']-before['top']) <= 1, (before, after)


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_short_long_hidden_notice_keeps_text_position_and_retry_visible(cockpit, theme):
    js, wait, client, requests, enable = cockpit
    stable_roster(js)
    enable(count=80)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    wait_reading_layout(js)
    js("""window.readerAnchorText=document.querySelectorAll('.conversation-text')[20];window.readerAnchorNode=readerAnchorText.firstChild;window.readerAnchorId=readerAnchorText.closest('.conversation-event').dataset.eventId;const s=document.querySelector('.conversation-scroll');s.dispatchEvent(new WheelEvent('wheel'));s.scrollTop+=readerAnchorText.getBoundingClientRect().top-s.getBoundingClientRect().top-30;s.dispatchEvent(new Event('scroll'));""")
    before = line_top(js)
    for message in ['Generated read failure', 'Generated read failure with more context. '*10]:
        fail_read(js, wait, message)
        assert abs(line_top(js)['top']-before['top']) <= 1
        assert js("""(()=>{const s=document.querySelector('.conversation-toolbar .conversation-status');return s.getBoundingClientRect().height<=2*parseFloat(getComputedStyle(s).lineHeight)+1})()""")
        assert js("document.querySelector('.conversation-toolbar .conversation-status').title") == message
        assert js("""(()=>{const b=document.querySelector('.conversation-retry'),r=b.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===b})()""")
    js("OrreryConversationSource.Source.prototype.read=async()=>({events:[],mode:'cursor',after:'recovered',has_older:true});document.querySelector('.conversation-retry').click()")
    wait("document.querySelector('.conversation-toolbar').hidden")
    assert abs(line_top(js)['top']-before['top']) <= 1


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [1600, 390])
def test_notice_load_earlier_is_clickable_at_the_top(cockpit, theme, width):
    js, wait, client, requests, enable = cockpit
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=1000, deviceScaleFactor=1, mobile=False)
    stable_roster(js)
    enable(count=80)
    js(r"""conversationView.close();OrreryConversationSource.Source.prototype.read=async()=>({events:Array.from({length:80},(_,i)=>({id:'paragraph-'+i,kind:'text',role:'assistant',text:'Generated paragraph '+i+'.\n\nThis text stays in the same position when a notice appears or disappears.'})),mode:'cursor',before:'first',after:'last',has_older:true});conversationView.open()""")
    wait("document.querySelector('[data-event-id=paragraph-0]')!==null")
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    wait_reading_layout(js)
    js("""window.readerAnchorText=document.querySelector('.conversation-text');window.readerAnchorNode=readerAnchorText.firstChild;window.readerAnchorId=readerAnchorText.closest('.conversation-event').dataset.eventId;const s=document.querySelector('.conversation-scroll');s.dispatchEvent(new WheelEvent('wheel'));s.scrollTop=0;s.dispatchEvent(new Event('scroll'));""")
    before = line_top(js)
    js("document.querySelector('.conversation-older').focus()")
    fail_read(js, wait, 'Generated read failure with more context. '*10)
    assert js("document.querySelector('.conversation-panel').contains(document.activeElement)")
    assert abs(line_top(js)['top']-before['top']) <= 1
    assert js("getComputedStyle(document.querySelector('.conversation-older')).visibility") == 'hidden'
    bounds = js("""(()=>{const b=document.querySelector('.conversation-notice-older'),r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,hit:document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===b||b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)),label:b.getAttribute('aria-label')}})()""")
    assert bounds['hit'] and bounds['label'] == 'Load earlier'
    js("OrreryConversationSource.Source.prototype.read=async()=>({events:Array.from({length:40},(_,i)=>({id:'older-'+i,kind:'text',role:'assistant',text:'Earlier generated message '+i})),mode:'cursor',before:'older-start',after:'older-end',has_older:true})")
    client.call('Input.dispatchMouseEvent', type='mousePressed', x=bounds['x'], y=bounds['y'], button='left', clickCount=1)
    client.call('Input.dispatchMouseEvent', type='mouseReleased', x=bounds['x'], y=bounds['y'], button='left', clickCount=1)
    wait("document.querySelectorAll('.conversation-event').length===120")
    wait("document.querySelector('.conversation-toolbar').hidden")
    wait_reading_layout(js)
    assert js("getComputedStyle(document.querySelector('.conversation-older')).visibility") == 'visible'
    assert js("document.activeElement.classList.contains('conversation-scroll')")
