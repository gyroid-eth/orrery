"""Pane header notices leave every provider's reading area unobstructed."""
import json
import time

import pytest
from test_conversation_review_regressions import cockpit, stable_roster, wait_reading_layout
from test_split_pane_headers import setup


def show(cockpit, theme='dark', layout='desktop', provider='claude'):
    js, wait, client, requests, enable = cockpit
    width = 390 if layout in ['phone', 'split-phone'] else 1600
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=844, deviceScaleFactor=1, mobile=False)
    if layout.startswith('split'):
        setup(cockpit, 2)
        js("window.readerHost=document.querySelector('.split-cell[data-session=ReviewFixture]')")
    else:
        stable_roster(js)
        enable(count=1)
        js("conversationView.close();window.readerHost=document.querySelector('.screen')")
    payload = dict(mode='cursor', provider=provider, events=[dict(id='first-text', kind='text', role='assistant', text='First readable line.\nSecond generated line.')], after='tail', has_older=False)
    if provider == 'fresh':
        payload.update(mode='fresh_tail', provider='codex', limited=True)
    elif provider == 'dsh':
        payload['notice'] = 'Recorded append timeline · not the current model context'
        payload['events'].insert(0, dict(id='first-tool', kind='tool', role='assistant', text='read'))
    elif provider == 'hermes':
        payload.update(mode='snapshot', notice='Recent provider snapshot.')
    js('window.noticePayload='+json.dumps(payload)+';OrreryConversationSource.Source.prototype.read=async()=>noticePayload;OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    if layout.startswith('split'):
        js("readerHost.querySelector('.split-history-toggle').click()")
    else:
        js('conversationView.open()')
    wait("readerHost.querySelector('[data-event-id=first-text]')!==null")
    wait_reading_layout(js)
    js("window.reader=readerHost.querySelector('.conversation-panel');window.readerScroll=reader.querySelector('.conversation-scroll');readerScroll.scrollTop=0")
    return js, wait, client


def hit(js, selector):
    return js("""(()=>{const e=readerHost.querySelector("""+json.dumps(selector)+""");if(!e||e.hidden)return false;const r=e.getBoundingClientRect(),h=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return r.width>0&&r.height>0&&(h===e||e.contains(h))})()""")


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('layout', ['desktop', 'phone', 'split', 'split-phone'])
@pytest.mark.parametrize('provider', ['claude', 'dsh', 'fresh', 'hermes'])
def test_provider_notices_live_only_in_the_owning_header(cockpit, theme, layout, provider):
    js, wait, client = show(cockpit, theme, layout, provider)
    assert js("!reader.querySelector('.conversation-top,.conversation-toolbar,.conversation-mode')")
    assert js("readerScroll.scrollHeight===readerScroll.clientHeight")
    first = '.conversation-tool-group' if provider == 'dsh' else '.conversation-byline'
    assert js('reader.querySelector('+json.dumps(first)+').getBoundingClientRect().top-readerScroll.getBoundingClientRect().top<25')
    assert hit(js, first)
    assert hit(js, '.conversation-text')
    if provider == 'dsh':
        assert js("reader.querySelector('.conversation-tool-group').getAttribute('aria-expanded')") == 'false'
    assert js("readerHost.querySelector('.conversation-toolbar').hidden")
    info = js("readerHost.querySelector('.conversation-mode').title")
    assert js("readerHost.querySelector('.conversation-mode').hidden") == (provider == 'claude')
    if provider != 'claude':
        assert info and hit(js, '.conversation-mode')
        assert js("readerHost.querySelector('.conversation-mode').getAttribute('aria-label')") == info
    assert js("readerHost.querySelector('.conversation-older').hidden")


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('layout', ['desktop', 'phone', 'split', 'split-phone'])
def test_header_retry_is_visible_and_keyboard_focus_survives_success(cockpit, theme, layout):
    js, wait, client = show(cockpit, theme, layout, 'dsh')
    before = js("reader.querySelector('.conversation-text').getBoundingClientRect().top")
    for failure in ['Generated read failure', 'Generated failure with multiple paragraphs.\n\n'*30]:
        js('window.noticeFailure='+json.dumps(failure)+";OrreryConversationSource.Source.prototype.read=async()=>{const e=new Error(noticeFailure);e.code='record_too_large';throw e};conversationView.refresh()")
        wait("!readerHost.querySelector('.conversation-retry').hidden")
        assert hit(js, '.conversation-notice-toggle' if layout == 'split-phone' else '.conversation-retry') and hit(js, '.conversation-text')
        assert hit(js, '.conversation-expand')
        assert hit(js, '.split-pane-window' if layout.startswith('split') else '#panePopout')
        if layout.startswith('split'):
            assert hit(js, '.scl-close')
            assert js("readerHost.querySelector('.conversation-notices').getBoundingClientRect().right<=readerHost.querySelector('.split-history-toggle').getBoundingClientRect().left+1")
        assert js("readerHost.querySelector('.conversation-toolbar').title") == failure
        assert abs(js("reader.querySelector('.conversation-text').getBoundingClientRect().top")-before) <= 1
    js("OrreryConversationSource.Source.prototype.read=()=>new Promise(resolve=>window.finishHeaderRead=resolve);packets.length=0")
    if layout == 'split-phone':
        js("readerHost.querySelector('.conversation-notice-toggle').click();document.getElementById(readerHost.querySelector('.conversation-notice-toggle').getAttribute('aria-controls')).querySelector('.conversation-menu-retry').focus()")
    else:
        js("readerHost.querySelector('.conversation-retry').focus()")
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', text='\r', windowsVirtualKeyCode=13)
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', windowsVirtualKeyCode=13)
    wait("typeof finishHeaderRead==='function'")
    assert js("readerHost.querySelector('.conversation-toolbar').hidden")
    assert js("document.activeElement===readerScroll")
    js("finishHeaderRead({mode:'cursor',events:[],after:'tail',unchanged:true})")
    js('queueStageFit(activeId)')
    time.sleep(.2)
    assert js("document.activeElement===readerScroll")
    assert js("readerHost.querySelector('.conversation-toolbar').hidden")
    assert abs(js("reader.querySelector('.conversation-text').getBoundingClientRect().top")-before) <= 1
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('layout', ['desktop', 'phone'])
def test_load_earlier_keyboard_focus_survives_the_last_older_page(cockpit, theme, layout):
    js, wait, client = show(cockpit, theme, layout)
    js("conversationView.close();noticePayload.has_older=true;noticePayload.before='start';conversationView.open()")
    wait("!readerHost.querySelector('.conversation-older').hidden")
    js("reader=readerHost.querySelector('.conversation-panel');readerScroll=reader.querySelector('.conversation-scroll');readerScroll.scrollTop=0;OrreryConversationSource.Source.prototype.read=async()=>({mode:'cursor',events:[{id:'older',kind:'text',role:'assistant',text:'Earlier generated message.'}],after:'tail',before:'oldest',has_older:false});reader.querySelector('.conversation-older').focus();packets.length=0")
    assert hit(js, '.conversation-older')
    assert js("reader.querySelector('.conversation-older').getBoundingClientRect().height<35")
    client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', text='\r', windowsVirtualKeyCode=13)
    client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', windowsVirtualKeyCode=13)
    wait("reader.querySelector('[data-event-id=older]')!==null")
    js('queueStageFit(activeId)')
    time.sleep(.2)
    assert js("reader.querySelector('.conversation-older').hidden")
    assert js("document.activeElement===readerScroll")
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_terminal_jump_result_expires_in_the_header(cockpit, theme):
    from test_conversation_jump_mail_browser import configure
    js, wait, client, requests, enable = cockpit
    configure(js, wait, enable, 'Generated absent message', 'Other generated terminal output\r\n'*80)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+');OrreryConversationSource.Source.prototype.read=()=>new Promise(()=>{});document.querySelector(".conversation-text").click()')
    wait("document.querySelector('.conversation-toolbar').title.includes('Not found')")
    assert js("document.querySelector('.conversation-toolbar').closest('.scr-head')!==null")
    assert js("document.querySelector('.conversation-status-label').textContent") == 'Not found'
    time.sleep(1)
    assert not js("document.querySelector('.conversation-toolbar').hidden")
    wait("document.querySelector('.conversation-toolbar').hidden")


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_header_notices_follow_the_owner_between_split_and_single(cockpit, theme):
    js, wait, client = show(cockpit, theme, 'split', 'dsh')
    js("OrreryConversationSource.Source.prototype.read=async name=>{if(name==='ReviewFixture'){const e=new Error('Owner read failure');e.code='record_too_large';throw e};return {...noticePayload,provider:'hermes',mode:'snapshot',notice:'Other provider snapshot.'}};readerHost.querySelector('.conversation-mode').focus();conversationView.refresh()")
    wait("!readerHost.querySelector('.conversation-retry').hidden")
    js("document.querySelector('.split-cell[data-session=OtherFixture] .split-history-toggle').click()")
    wait("document.querySelector('.split-cell[data-session=OtherFixture] .conversation-mode')?.title==='Other provider snapshot.'")
    assert js("document.querySelector('.split-cell[data-session=OtherFixture] .conversation-toolbar').hidden")
    js("focusSplitSession('ReviewFixture');document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-retry').focus();setActive(paneIdForSession('ReviewFixture'),'single');renderStage()")
    wait("document.querySelector('.scr-head .conversation-toolbar')?.title==='Owner read failure'")
    assert js("document.querySelector('.scr-head .conversation-mode').title") == 'Recorded append timeline · not the current model context'
    js('queueStageFit(activeId)')
    time.sleep(.2)
    assert js("document.activeElement.closest('.scr-head')!==null")
    js("replaceSplitSessions(['OtherFixture','ReviewFixture']);splitVisible=true;focusSplitSession('ReviewFixture');renderStage()")
    wait("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-toolbar')?.title==='Owner read failure'")
    assert js("document.querySelector('.split-cell[data-session=OtherFixture] .conversation-mode').title") == 'Other provider snapshot.'
    assert js("document.querySelector('.split-cell[data-session=OtherFixture] .conversation-toolbar').hidden")
    assert js("document.querySelector('.scr-head .conversation-notices:not([hidden])')===null")


@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_pending_and_catch_up_reads_do_not_flash_header_text(cockpit, theme):
    js, wait, client = show(cockpit, theme)
    js("OrreryConversationSource.Source.prototype.read=()=>new Promise(resolve=>window.finishQuietRead=resolve);conversationView.refresh();0")
    wait("typeof finishQuietRead==='function'")
    assert js("readerHost.querySelector('.conversation-toolbar').hidden")
    js("finishQuietRead({...noticePayload,has_newer:true})")
    time.sleep(.1)
    assert js("readerHost.querySelector('.conversation-toolbar').hidden")
    assert js("readerHost.querySelector('.conversation-notices').hidden")
