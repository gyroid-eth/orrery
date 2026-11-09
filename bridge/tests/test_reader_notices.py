"""Header notices keep the reader free of reserved space and overlays."""
import json
import time

import pytest
from test_conversation_review_regressions import cockpit, stable_roster, wait_reading_layout


def sparse(cockpit, theme, width, mode):
    js, wait, client, requests, enable = cockpit
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=844, deviceScaleFactor=1, mobile=False)
    stable_roster(js)
    enable(count=1)
    payload = dict(mode='cursor', provider='claude', events=[dict(id='first-text', kind='text', role='assistant', text='First readable line.\nSecond generated line.')], after='tail', has_older=False)
    if mode == 'fresh':
        payload.update(mode='fresh_tail', provider='codex', limited=True)
    elif mode == 'hermes':
        payload.update(mode='snapshot', provider='hermes', notice='Recent provider snapshot.')
    elif mode == 'dsh':
        payload.update(provider='dsh', notice='Recorded append timeline · not the current model context')
        payload['events'].insert(0, dict(id='first-tool', kind='tool', role='assistant', text='read'))
    js('conversationView.close();window.noticePayload='+json.dumps(payload)+';OrreryConversationSource.Source.prototype.read=async()=>noticePayload;conversationView.open()')
    wait("document.querySelector('[data-event-id=first-text]')!==null")
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    wait_reading_layout(js)
    js("document.querySelector('.conversation-scroll').scrollTop=0")
    return js, wait, client


def first_row_hits(js):
    return js("""(()=>{const hits={};for(const selector of ['.conversation-tool-count','.conversation-event:not([hidden]) .conversation-role','.conversation-text']){const e=document.querySelector(selector);if(!e)continue;const r=document.createRange();r.setStart(e.firstChild,0);r.setEnd(e.firstChild,1);const b=r.getBoundingClientRect(),hit=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);hits[selector]=!!hit&&(e===hit||e.contains(hit));}return hits})()""")


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [1600, 390])
@pytest.mark.parametrize('mode', ['fresh', 'dsh', 'legacy', 'hermes'])
def test_sparse_reader_keeps_mode_notice_and_first_rows_separate(cockpit, theme, width, mode):
    js, wait, client = sparse(cockpit, theme, width, mode)
    assert js("(()=>{const s=document.querySelector('.conversation-scroll');return s.scrollHeight===s.clientHeight})()")
    assert all(first_row_hits(js).values()), first_row_hits(js)
    assert js("!document.querySelector('.conversation-panel .conversation-top,.conversation-panel .conversation-toolbar')")
    first = '.conversation-tool-group' if mode == 'dsh' else '.conversation-byline'
    assert js('document.querySelector('+json.dumps(first)+').getBoundingClientRect().top-document.querySelector(".conversation-scroll").getBoundingClientRect().top<25')
    assert js("document.querySelector('.conversation-toolbar').hidden")
    info = js("document.querySelector('.conversation-mode').title")
    assert info == '' if mode == 'legacy' else ('Fresh' in info if mode == 'fresh' else 'snapshot' in info if mode == 'hermes' else 'Recorded append timeline' in info)


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [1600, 390])
def test_temporary_header_notice_never_covers_sparse_text(cockpit, theme, width):
    js, wait, client = sparse(cockpit, theme, width, 'legacy')
    before = js("document.querySelector('.conversation-text').getBoundingClientRect().top")
    for message in ['Generated read failure', 'Generated read failure with more context. '*10]:
        js('window.noticeFailure='+json.dumps(message)+";OrreryConversationSource.Source.prototype.read=async()=>{throw new Error(noticeFailure)};conversationView.refresh()")
        wait("!document.querySelector('.conversation-retry').hidden")
        assert abs(js("document.querySelector('.conversation-text').getBoundingClientRect().top")-before) <= 1
        assert all(first_row_hits(js).values()), first_row_hits(js)
        assert js("document.querySelector('.conversation-toolbar').closest('.scr-head')!==null")
        assert js("document.querySelector('.scr-head').getBoundingClientRect().height") == 40
        assert js("""(()=>{const b=document.querySelector('.conversation-retry'),r=b.getBoundingClientRect();return b.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))})()""")
    js("OrreryConversationSource.Source.prototype.read=()=>new Promise(resolve=>window.finishNoticeRead=resolve);document.querySelector('.conversation-retry').click()")
    wait("typeof finishNoticeRead==='function'")
    assert js("document.querySelector('.conversation-toolbar').hidden")
    assert all(first_row_hits(js).values()), first_row_hits(js)
    js('finishNoticeRead(noticePayload)')
    wait("document.querySelector('.conversation-toolbar').hidden")
    assert abs(js("document.querySelector('.conversation-text').getBoundingClientRect().top")-before) <= 1


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_header_notice_does_not_replace_load_earlier(cockpit, theme):
    js, wait, client, requests, enable = cockpit
    stable_roster(js)
    enable(count=80)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    wait_reading_layout(js)
    js("const s=document.querySelector('.conversation-scroll');s.dispatchEvent(new WheelEvent('wheel'));s.scrollTop=0;s.dispatchEvent(new Event('scroll'));OrreryConversationSource.Source.prototype.read=async()=>{throw new Error('Generated read failure')};conversationView.refresh()")
    wait("!document.querySelector('.conversation-retry').hidden")
    assert js("!document.querySelector('.conversation-older').hidden")
    assert js("document.querySelector('.conversation-notice-older')===null")
    assert all(first_row_hits(js).values()), first_row_hits(js)
    js("document.querySelector('.conversation-scroll').scrollTop=300;document.querySelector('.conversation-scroll').dispatchEvent(new Event('scroll'))")
    assert js("!document.querySelector('.conversation-older').hidden")
    assert js("getComputedStyle(document.querySelector('.conversation-older')).visibility") == 'visible'


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [1600, 390])
def test_scrolling_focused_load_earlier_keeps_focus_in_reader(cockpit, theme, width):
    js, wait, client, requests, enable = cockpit
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=844, deviceScaleFactor=1, mobile=False)
    stable_roster(js)
    enable(count=80)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    wait_reading_layout(js)
    js("const s=document.querySelector('.conversation-scroll');s.scrollTop=0;s.dispatchEvent(new Event('scroll'));OrreryConversationSource.Source.prototype.read=async()=>{throw new Error('Generated read failure')};conversationView.refresh()")
    wait("!document.querySelector('.conversation-retry').hidden")
    js("document.querySelector('.conversation-older').focus();packets.length=0")
    assert js("document.activeElement===document.querySelector('.conversation-older')")
    center = js("(()=>{const r=document.querySelector('.conversation-scroll').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
    client.call('Input.dispatchMouseEvent', type='mouseWheel', x=center['x'], y=center['y'], deltaX=0, deltaY=300)
    wait("document.querySelector('.conversation-scroll').scrollTop>100")
    assert js("document.querySelector('.conversation-panel').contains(document.activeElement)")
    js('queueStageFit(activeId)')
    time.sleep(.2)
    assert js("document.querySelector('.conversation-panel').contains(document.activeElement)")
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_retry_unchanged_clears_temporary_notice_and_keeps_rows(cockpit, theme):
    js, wait, client = sparse(cockpit, theme, 390, 'dsh')
    js("window.savedNoticeRow=document.querySelector('[data-event-id=first-text]');window.savedMode=document.querySelector('.conversation-mode').title;window.savedTextTop=savedNoticeRow.getBoundingClientRect().top;OrreryConversationSource.Source.prototype.read=async()=>{const e=new Error('Generated read failure');e.code='record_too_large';throw e};conversationView.refresh()")
    wait("!document.querySelector('.conversation-retry').hidden")
    js("window.unchangedReads=0;OrreryConversationSource.Source.prototype.read=()=>{unchangedReads++;return unchangedReads===1?new Promise(resolve=>window.finishUnchanged=resolve):Promise.resolve({mode:'cursor',events:[],after:'tail',unchanged:true})};document.querySelector('.conversation-retry').click()")
    wait("typeof finishUnchanged==='function'&&document.querySelector('.conversation-toolbar').hidden")
    js("finishUnchanged({mode:'cursor',events:[],after:'tail',unchanged:true})")
    time.sleep(.1)
    assert js("document.querySelector('.conversation-toolbar').hidden")
    assert js("document.querySelector('.conversation-retry').hidden")
    assert js("document.querySelector('[data-event-id=first-text]')===savedNoticeRow&&document.querySelector('.conversation-mode').title===savedMode")
    assert js("Math.abs(savedNoticeRow.getBoundingClientRect().top-savedTextTop)<=1")
    wait('unchangedReads>=2')
    assert js("document.querySelector('.conversation-toolbar').hidden")
    assert js("document.querySelector('[data-event-id=first-text]')===savedNoticeRow&&document.querySelector('.conversation-mode').title===savedMode")
