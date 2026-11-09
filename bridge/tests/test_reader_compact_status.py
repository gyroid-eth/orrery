"""Narrow headers keep every action, and transient notices restore the state."""
import json
import time

import pytest
from test_conversation_review_regressions import cockpit, stable_roster, wait_reading_layout
from test_reader_header_notices import show
from test_reader_panel import pause_at_reader_limit


def fail(js, wait):
    js("OrreryConversationSource.Source.prototype.read=async()=>{const e=new Error('Generated read failure');e.code='record_too_large';throw e};conversationView.refresh()")
    wait("!readerHost.querySelector('.conversation-retry').hidden")


def header_geometry(js):
    return js("""(()=>{const h=readerHost.querySelector('.split-cell-head'),b=h.getBoundingClientRect();return {left:b.left,right:b.right,name:h.querySelector('.scl-name').getBoundingClientRect().width,items:[...h.querySelectorAll('.scl-name,.scl-close,.conversation-retry,.conversation-mode,.conversation-notice-toggle,.split-history-toggle,.conversation-expand,.split-pane-window')].map(e=>{const r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {class:e.className,width:r.width,height:r.height,left:r.left,right:r.right,hit:hit===e||e.contains(hit)}}).filter(r=>r.width>0&&r.height>0)}})()""")


def assert_geometry(js):
    state = header_geometry(js)
    assert state['name'] >= 16, state
    items = sorted(state['items'], key=lambda item:item['left'])
    for item in items:
        assert item['left'] >= state['left']-.5 and item['right'] <= state['right']+.5, state
        assert item['hit'], state
    for left, right in zip(items, items[1:]):
        assert left['right'] <= right['left']+.5, state


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [280, 320, 360, 375, 390])
def test_narrow_split_names_and_all_actions_remain_visible(cockpit, theme, width):
    js, wait, client = show(cockpit, theme, 'split-phone', 'dsh')
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=844, deviceScaleFactor=1, mobile=False)
    wait_reading_layout(js)
    assert_geometry(js)
    fail(js, wait)
    assert_geometry(js)
    assert js("readerHost.querySelector('.conversation-notice-toggle').title.includes('Generated read failure')")
    assert js("readerHost.querySelector('.conversation-notice-toggle').title.includes('Recorded append timeline')")


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [280, 390])
def test_compact_notice_keyboard_retry_preserves_reader_focus(cockpit, theme, width):
    js, wait, client = show(cockpit, theme, 'split-phone', 'dsh')
    client.call('Emulation.setDeviceMetricsOverride', width=width, height=844, deviceScaleFactor=1, mobile=False)
    wait_reading_layout(js)
    fail(js, wait)
    js("readerHost.querySelector('.conversation-notice-toggle').focus();packets.length=0")
    for kind in ['keyDown', 'keyUp']:
        client.call('Input.dispatchKeyEvent', type=kind, key='Enter', code='Enter', windowsVirtualKeyCode=13, **({'text':'\r'} if kind=='keyDown' else {}))
    wait("document.querySelector('.conversation-notice-menu:not([hidden])')!==null")
    assert js("readerHost.querySelector('.conversation-notice-toggle').getAttribute('aria-expanded')") == 'true'
    js("window.compactMenu=document.getElementById(readerHost.querySelector('.conversation-notice-toggle').getAttribute('aria-controls'))")
    assert js("compactMenu.querySelector('.conversation-notice-copy').textContent.includes('Recorded append timeline')")
    assert js("(()=>{const r=compactMenu.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth})()")
    js('queueStageFit(activeId)')
    time.sleep(.2)
    assert js("document.activeElement===compactMenu.querySelector('.conversation-menu-retry')")
    js("OrreryConversationSource.Source.prototype.read=()=>new Promise(resolve=>window.finishCompactRetry=resolve);compactMenu.querySelector('.conversation-menu-retry').focus()")
    for kind in ['keyDown', 'keyUp']:
        client.call('Input.dispatchKeyEvent', type=kind, key='Enter', code='Enter', windowsVirtualKeyCode=13, **({'text':'\r'} if kind=='keyDown' else {}))
    wait("typeof finishCompactRetry==='function'")
    assert js("document.querySelector('.conversation-notice-menu').hidden")
    assert js("document.activeElement===readerScroll")
    js("finishCompactRetry({mode:'cursor',events:[],after:'tail',unchanged:true});queueStageFit(activeId)")
    time.sleep(.2)
    assert js("document.activeElement===readerScroll")
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('state', ['paused', 'released', 'skipped'])
def test_continuing_state_returns_after_the_jump_notice_expires(cockpit, theme, state):
    js, wait, client, requests, enable = cockpit
    stable_roster(js)
    enable(count=200)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    if state == 'paused':
        pause_at_reader_limit(js, wait)
    elif state == 'released':
        for _ in range(4):
            js("document.querySelector('.conversation-scroll').scrollTop=1e9;conversationView.refresh()")
        wait("document.querySelector('.conversation-toolbar').title.includes('released')")
    else:
        js("OrreryConversationSource.Source.prototype.read=async()=>({mode:'cursor',events:[],after:'skipped',skipped_large_record:true});conversationView.refresh()")
        wait("document.querySelector('.conversation-toolbar').title.includes('skipped')")
    js("OrreryConversationSource.Source.prototype.read=()=>new Promise(()=>{});0")
    before = js("document.querySelector('.conversation-toolbar').title")
    js("document.querySelectorAll('.conversation-text')[5].focus();packets.length=0")
    for kind in ['keyDown', 'keyUp']:
        client.call('Input.dispatchKeyEvent', type=kind, key='Enter', code='Enter', windowsVirtualKeyCode=13, **({'text':'\r'} if kind=='keyDown' else {}))
    wait("document.querySelector('.conversation-toolbar').title.includes('Terminal changed')")
    time.sleep(5.2)
    assert js("document.querySelector('.conversation-toolbar').title") == before
    assert not js("document.querySelector('.conversation-toolbar').hidden")
    if state == 'paused':
        assert js("document.querySelector('.conversation-latest').getAttribute('aria-label').includes('resume')")
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('agent', [True, False], ids=['agent', 'terminal'])
def test_single_header_displays_session_without_internal_identifiers(cockpit, theme, agent):
    js, wait, client, requests, enable = cockpit
    stable_roster(js)
    enable(count=1)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+')')
    js("const p=panes.get('%901');if(!"+json.dumps(agent)+"){p.session='TerminalFixture';currentAgents=[]};p.meta={...p.meta,session:p.session,paneId:'%901',windowIndex:7,paneIndex:2,windowName:'InternalWindowFixture',currentCommand:'fixture-command'};paintHead(p.meta)")
    expected = 'ReviewFixture' if agent else 'TerminalFixture'
    assert js('scrName.textContent') == expected
    assert js('scrPath.textContent') == ''
    text = js("document.querySelector('.scr-head').innerText")
    for internal in ['%901', 'w7/p2', 'w?/p?', 'InternalWindowFixture', 'fixture-command']:
        assert internal not in text, text


def pointer_click(js, client, selector):
    point=js('(()=>{const element=document.querySelector('+json.dumps(selector)+');const rect=element.getBoundingClientRect();return {x:rect.x+rect.width/2,y:rect.y+rect.height/2}})()')
    for kind in ['mousePressed','mouseReleased']:
        client.call('Input.dispatchMouseEvent',type=kind,button='left',clickCount=1,**point)


def press_enter(client):
    for kind in ['keyDown','keyUp']:
        client.call('Input.dispatchKeyEvent',type=kind,key='Enter',code='Enter',windowsVirtualKeyCode=13,**({'text':'\r'} if kind=='keyDown' else {}))


def dialog_screenshot(client, tmp_path, name):
    import base64
    import os
    from pathlib import Path
    output=Path(os.environ.get('ORRERY_READER_DIALOG_SCREENSHOTS',tmp_path))
    output.mkdir(parents=True,exist_ok=True)
    (output/name).write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))
    print('Reader dialog screenshot:',output/name)


@pytest.mark.parametrize('theme', ['dark','light'])
def test_relocated_dialog_retry_focus_stays_in_reader_after_fit(cockpit, theme, tmp_path):
    js,wait,client=show(cockpit,theme,'split-phone','dsh')
    fail(js,wait)
    pointer_click(js,client,'.split-cell[data-session=ReviewFixture] .conversation-notice-toggle')
    wait("document.querySelector('.conversation-notice-menu:not([hidden])')!==null")
    # Escape returns to the trigger; Enter opens it again with Retry focused.
    client.call('Input.dispatchKeyEvent',type='keyDown',key='Escape',windowsVirtualKeyCode=27)
    client.call('Input.dispatchKeyEvent',type='keyUp',key='Escape',windowsVirtualKeyCode=27)
    press_enter(client)
    assert js("document.activeElement.classList.contains('conversation-menu-retry')")
    js("packets.length=0;setActive(paneIdForSession('ReviewFixture'),'single');renderStage()")
    wait_reading_layout(js)
    js('queueStageFit(activeId)')
    time.sleep(.25)
    assert js("document.querySelectorAll('.conversation-notice-menu:not([hidden])').length") == 0
    assert js("!!document.activeElement.closest('.conversation-panel,.conversation-notices')")
    assert js('document.activeElement.getClientRects().length>0')
    client.call('Input.dispatchKeyEvent',type='keyDown',key='q',code='KeyQ',text='q',windowsVirtualKeyCode=81)
    client.call('Input.dispatchKeyEvent',type='keyUp',key='q',code='KeyQ',windowsVirtualKeyCode=81)
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []
    dialog_screenshot(client,tmp_path,theme+'-relocated-focus.png')


@pytest.mark.parametrize('theme', ['dark','light'])
def test_outside_header_dismisses_dialog_and_only_one_menu_opens(cockpit, theme, tmp_path):
    js,wait,client=show(cockpit,theme,'split-phone','dsh')
    fail(js,wait)
    owner='.split-cell[data-session=ReviewFixture]'
    other='.split-cell[data-session=OtherFixture]'
    pointer_click(js,client,owner+' .conversation-notice-toggle')
    wait("document.querySelector('.conversation-notice-menu:not([hidden])')!==null")
    pointer_click(js,client,other+' .scl-name')
    assert js("document.querySelectorAll('.conversation-notice-menu:not([hidden])').length") == 0
    js("OrreryConversationSource.Source.prototype.read=async()=>({...noticePayload,provider:'hermes',mode:'snapshot',notice:'Other provider snapshot.'})")
    pointer_click(js,client,other+' .split-history-toggle')
    wait("document.querySelector('.split-cell[data-session=OtherFixture] .conversation-mode')?.title==='Other provider snapshot.'")
    pointer_click(js,client,other+' .conversation-mode')
    assert js("document.querySelectorAll('.conversation-notice-menu:not([hidden])').length") == 1
    assert js("document.querySelector('.conversation-notice-menu:not([hidden])').textContent.includes('Other provider snapshot.')")
    # Switching by keyboard has no outside pointerdown to dismiss the old menu.
    js("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-notice-toggle').focus();packets.length=0")
    press_enter(client)
    assert js("document.querySelectorAll('.conversation-notice-menu:not([hidden])').length") == 1
    assert js("document.querySelector('.conversation-notice-menu:not([hidden])').textContent.includes('Generated read failure')")
    assert js("document.querySelector('.split-cell[data-session=OtherFixture] .conversation-mode').getAttribute('aria-expanded')") == 'false'
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))") == []
    dialog_screenshot(client,tmp_path,theme+'-single-dialog.png')
