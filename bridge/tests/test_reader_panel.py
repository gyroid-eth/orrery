"""Reader controls stay with their pane; notices and navigation stay usable."""
import json
import time

import pytest
from test_conversation_review_regressions import cockpit, stable_roster
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


def test_status_and_retry_stay_in_the_reading_flow(cockpit):
    js, wait, client = opened(cockpit)
    js('conversationView.close();window.readerFail=true;OrreryConversationSource.Source.prototype.read=async()=>{if(readerFail)throw new Error("Generated read failure");return {events:[{id:"retry-row",kind:"text",role:"assistant",text:"Recovered"}],after:"one",before:"zero",has_older:true}};conversationView.open()')
    wait('!document.querySelector(".conversation-retry").hidden')
    assert js('document.querySelector(".conversation-scroll .conversation-toolbar")!==null')
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
