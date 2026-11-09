"""Closing a split pane shares the action style and ends the header tab order."""
import json

import pytest
from test_split_pane_headers import cockpit, setup
from test_conversation_review_regressions import wait_reading_layout


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('width', [1600,390,280])
@pytest.mark.parametrize('reader', [False,True])
def test_close_is_the_rightmost_matching_icon_and_remains_hittable(cockpit, theme, width, reader):
    js,wait,client=setup(cockpit,2)
    client.call('Emulation.setDeviceMetricsOverride',width=width,height=844,deviceScaleFactor=1,mobile=False)
    js('OrreryColorTheme.setPreference('+json.dumps(theme)+');window.closeHead=document.querySelector(".split-cell[data-session=ReviewFixture] .split-cell-head")')
    if reader:
        js("closeHead.querySelector('.split-history-toggle').click()")
        wait("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-text')!==null")
        js("closeHead.querySelector('.conversation-expand').click()")
        wait_reading_layout(js)
    data=js("""(()=>{const close=closeHead.querySelector('.scl-close'),other=closeHead.querySelector('.split-pane-window'),c=close.getBoundingClientRect(),o=other.getBoundingClientRect(),s=getComputedStyle(close),t=getComputedStyle(other),h=closeHead.getBoundingClientRect(),hit=document.elementFromPoint(c.x+c.width/2,c.y+c.height/2),buttons=[...closeHead.querySelectorAll('button')].filter(b=>!b.hidden&&b.getBoundingClientRect().width);return {rightmost:buttons.at(-1)===close&&c.left>=o.right,inside:c.right<=h.right&&c.left>=h.left,hit:hit===close||close.contains(hit),label:close.getAttribute('aria-label'),svg:!!close.querySelector('svg'),width:c.width,otherWidth:o.width,height:c.height,otherHeight:o.height,style:[s.color,s.borderTopWidth,s.borderTopStyle,s.borderTopColor,s.borderRadius,s.backgroundColor,s.opacity],otherStyle:[t.color,t.borderTopWidth,t.borderTopStyle,t.borderTopColor,t.borderRadius,t.backgroundColor,t.opacity]}})()""")
    assert data['rightmost'] and data['inside'] and data['hit'],data
    assert data['label']=='Close ReviewFixture pane' and data['svg'],data
    assert data['width']==data['otherWidth'] and data['height']==data['otherHeight'],data
    assert data['width']>=16 and data['height']>=24,data
    assert data['style']==data['otherStyle'],data
    js("closeHead.querySelector('.scl-close').focus()")
    assert js("getComputedStyle(document.activeElement).outlineStyle") != 'none'


@pytest.mark.parametrize('key,code,text', [('Enter',13,'\r'),(' ',32,' ')])
def test_close_follows_window_in_keyboard_order_and_keeps_existing_detach(cockpit,key,code,text):
    js,wait,client=setup(cockpit,2)
    js("attachedSessions.add('ReviewFixture');document.querySelector('.split-cell[data-session=ReviewFixture] .split-pane-window').focus();packets.length=0")
    client.call('Input.dispatchKeyEvent',type='keyDown',key='Tab',code='Tab',windowsVirtualKeyCode=9)
    client.call('Input.dispatchKeyEvent',type='keyUp',key='Tab',code='Tab',windowsVirtualKeyCode=9)
    assert js("document.activeElement===document.querySelector('.split-cell[data-session=ReviewFixture] .scl-close')")
    client.call('Input.dispatchKeyEvent',type='keyDown',key=key,windowsVirtualKeyCode=code,text=text)
    client.call('Input.dispatchKeyEvent',type='keyUp',key=key,windowsVirtualKeyCode=code)
    wait("document.querySelector('.split-cell[data-session=ReviewFixture]')===null")
    assert js("packets.filter(p=>p.type==='detach').map(p=>p.session)")==['ReviewFixture']
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))")==[]
