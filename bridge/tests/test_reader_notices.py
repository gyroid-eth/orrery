"""Mode information and temporary notices share a fixed, text-safe slot."""
import json

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
    return js("""(()=>{const hits={};for(const selector of ['.conversation-role','.conversation-tool-name','.conversation-text']){const e=document.querySelector(selector);if(!e)continue;const r=document.createRange();r.setStart(e.firstChild,0);r.setEnd(e.firstChild,1);const b=r.getBoundingClientRect(),hit=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);hits[selector]=!!hit&&(e===hit||e.contains(hit));}return hits})()""")


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [1600, 390])
@pytest.mark.parametrize('mode', ['fresh', 'dsh', 'legacy'])
def test_sparse_reader_keeps_mode_notice_and_first_rows_separate(cockpit, theme, width, mode):
    js, wait, client = sparse(cockpit, theme, width, mode)
    assert js("(()=>{const s=document.querySelector('.conversation-scroll');return s.scrollHeight===s.clientHeight})()")
    assert all(first_row_hits(js).values()), first_row_hits(js)
    assert js("document.querySelector('.conversation-scroll').firstElementChild.classList.contains('conversation-top')")
    assert js("document.querySelector('.conversation-top').getBoundingClientRect().height") == 50
    assert js("document.querySelector('.conversation-toolbar').hidden")
    info = js("document.querySelector('.conversation-mode').textContent")
    assert info == '' if mode == 'legacy' else ('Fresh' in info if mode == 'fresh' else 'Recorded append timeline' in info)


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [1600, 390])
def test_temporary_notice_fits_the_slot_without_covering_sparse_text(cockpit, theme, width):
    js, wait, client = sparse(cockpit, theme, width, 'legacy')
    before = js("document.querySelector('.conversation-text').getBoundingClientRect().top")
    for message in ['Generated read failure', 'Generated read failure with more context. '*10]:
        js('window.noticeFailure='+json.dumps(message)+";OrreryConversationSource.Source.prototype.read=async()=>{throw new Error(noticeFailure)};conversationView.refresh()")
        wait("!document.querySelector('.conversation-retry').hidden")
        assert abs(js("document.querySelector('.conversation-text').getBoundingClientRect().top")-before) <= 1
        assert all(first_row_hits(js).values()), first_row_hits(js)
        assert js("document.querySelector('.conversation-toolbar').getBoundingClientRect().height") == 50
        assert js("Math.abs(document.querySelector('.conversation-toolbar').getBoundingClientRect().top-document.querySelector('.conversation-top').getBoundingClientRect().top)") <= 1
        assert js("""(()=>{const b=document.querySelector('.conversation-retry'),r=b.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===b})()""")
    js("OrreryConversationSource.Source.prototype.read=()=>new Promise(resolve=>window.finishNoticeRead=resolve);document.querySelector('.conversation-retry').click()")
    wait("document.querySelector('.conversation-toolbar .conversation-status').textContent.includes('Loading')")
    assert all(first_row_hits(js).values()), first_row_hits(js)
    assert js("document.querySelector('.conversation-toolbar').getBoundingClientRect().height") == 50
    js('finishNoticeRead(noticePayload)')
    wait("document.querySelector('.conversation-toolbar').hidden")
    assert abs(js("document.querySelector('.conversation-text').getBoundingClientRect().top")-before) <= 1


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_overlay_earlier_control_only_replaces_the_covered_control(cockpit, theme):
    js, wait, client, requests, enable = cockpit
    stable_roster(js)
    enable(count=80)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    wait_reading_layout(js)
    js("const s=document.querySelector('.conversation-scroll');s.dispatchEvent(new WheelEvent('wheel'));s.scrollTop=0;s.dispatchEvent(new Event('scroll'));OrreryConversationSource.Source.prototype.read=async()=>{throw new Error('Generated read failure')};conversationView.refresh()")
    wait("!document.querySelector('.conversation-retry').hidden")
    assert js("!document.querySelector('.conversation-notice-older').hidden")
    assert all(first_row_hits(js).values()), first_row_hits(js)
    js("document.querySelector('.conversation-scroll').scrollTop=300;document.querySelector('.conversation-scroll').dispatchEvent(new Event('scroll'))")
    assert js("document.querySelector('.conversation-notice-older').hidden")
    assert js("getComputedStyle(document.querySelector('.conversation-older')).visibility") == 'visible'
