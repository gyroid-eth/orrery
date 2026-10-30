"""Native viewport scrollbar: actual pointer drags in the static cockpit.

Uses an isolated browser/profile and mock HTTP server, never tmux, a live
backend, or the on-disk history store. No wheel algorithm is replaced.
"""
import json

import pytest

from test_demo_mode_browser import CHROME, browser, wait

pytestmark = pytest.mark.skipif(CHROME is None, reason='no Chromium (set ORRERY_CHROME)')


@pytest.fixture
def history_browser():
    with browser() as (go, js):
        go('')
        assert wait(js, "typeof createPane==='function'&&Boolean(window.OrreryTour)")
        js("""OrreryTour.state.close();window.packets=[];
          window.send=m=>{packets.push(m);return true;};
          window.settle=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
          window.writeHistory=async(p,data)=>{
            writePaneOutput(p,{data});await new Promise(r=>p.term.write('',r));await settle();
          };
          window.view=()=>{
            const v=p.host.querySelector('.xterm-viewport'),r=v.getBoundingClientRect();
            const b=p.term.buffer.active;
            return {x:r.right-(v.offsetWidth-v.clientWidth)/2,y:r.top,height:v.clientHeight,
              width:v.offsetWidth-v.clientWidth,top:v.scrollTop,total:v.scrollHeight,
              row:b.viewportY,base:b.baseY,reader:!!p._readerScrolled,
              bottom:p.bottomJump.classList.contains('visible')};
          };""")
        yield js


def start(js, split=False, claimed=True):
    js(f"""(async()=>{{
      for(const [name,id] of [['HistoryFixture','%901'],['OtherFixture','%902']]){{
        if({json.dumps(claimed)})claimedSessions.add(name);
        createPane(name,{{paneId:id,width:80,height:20,alternateOn:false,mouseTracking:false}});
      }}
      window.p=panes.get('%901');window.other=panes.get('%902');
      if({json.dumps(split)}){{replaceSplitSessions(['HistoryFixture','OtherFixture']);splitVisible=true;}}
      setActive('%901');await settle();
      await writeHistory(p,Array.from({{length:180}},(_,i)=>'HISTORY '+i+'\\r\\n').join(''));
      endPaneSnapshot(p);endPaneSnapshot(other);await settle();
      packets.length=0;
    }})()""")


def drag(js, fraction):
    """Drag the real native thumb; never assign scrollTop to simulate it."""
    v = js('view()')
    thumb = max(24, v['height'] ** 2 / v['total'])
    travel = v['height'] - thumb
    source = v['y'] + thumb / 2 + travel * v['top'] / (v['total'] - v['height'])
    target = v['y'] + thumb / 2 + travel * fraction
    client = js.client
    client.call('Input.dispatchMouseEvent', type='mouseMoved', x=v['x'], y=source)
    client.call('Input.dispatchMouseEvent', type='mousePressed', x=v['x'], y=source,
                button='left', buttons=1, clickCount=1)
    for step in range(1, 9):
        client.call('Input.dispatchMouseEvent', type='mouseMoved', x=v['x'],
                    y=source + (target - source) * step / 8, button='left', buttons=1)
    client.call('Input.dispatchMouseEvent', type='mouseReleased', x=v['x'], y=target,
                button='left', buttons=0, clickCount=1)
    js('settle()')


@pytest.mark.parametrize('split', [False, True])
@pytest.mark.parametrize('claimed', [False, True], ids=['follow', 'claimed'])
def test_native_drag_tracks_real_buffer_and_preserves_reading_bottom_input_and_selection(history_browser, split, claimed):
    js = history_browser
    start(js, split, claimed)
    before = js('view()')
    assert before['width'] >= 12  # Persistent grab area, including macOS overlay defaults.
    assert before['row'] == before['base'] > 0
    other = js('other.term.buffer.active.viewportY')
    drag(js, .3)
    assert wait(js, 'view().row>0&&view().row<view().base*.6&&view().reader&&view().bottom')
    reading = js('view()')
    assert abs(reading['row'] / reading['base'] - .3) < .06
    assert abs(reading['top'] / (reading['total'] - reading['height']) - .3) < .06
    drag(js, 0)
    assert wait(js, 'view().row===0')
    drag(js, .3)
    reading = js('view()')
    js("writeHistory(p,'NEW OUTPUT\\r\\n')")
    assert js('view().row') == reading['row']
    assert js('other.term.buffer.active.viewportY') == other
    assert js("packets.filter(m=>m.type==='input'||m.type==='codex-page')") == []
    # Selection/copy still addresses the same xterm buffer after a drag.
    assert js("p.term.selectLines(0,0);p.term.getSelection()") == 'HISTORY 0'
    js("p.term.clearSelection();p.bottomJump.click();settle()")
    assert wait(js, 'view().row===view().base&&!view().bottom&&!view().reader')
    js("writeHistory(p,'FOLLOWED\\r\\n')")
    assert js('view().row===view().base')
    js.client.call('Input.dispatchKeyEvent', type='char', text='z')
    assert js("packets.filter(m=>m.type==='input')") == [
        {'type': 'input', 'paneId': '%901', 'data': 'z'}]


@pytest.mark.parametrize('mode', [47, 1047, 1049])
def test_remote_alternate_and_live_modes_hide_the_bar_without_blocking_tui_mouse(history_browser, mode):
    js = history_browser
    start(js)
    js("setCodexWheelModes(p,{alternateOn:true,mouseTracking:true});settle()")
    assert js("p.term.buffer.active.type") == 'normal'  # Cold viewer from #62.
    assert js('view().width') == 0
    js("setCodexWheelModes(p,{alternateOn:false,mouseTracking:false});settle()")
    assert js('view().width') >= 12
    js(f"writeHistory(p,'\\x1b[?{mode}h\\x1b[?1003h\\x1b[?1006hTUI')")
    assert js('view().width') == 0
    js("""(()=>{const screen=p.host.querySelector('.xterm-screen'),r=screen.getBoundingClientRect();
      screen.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,
        clientX:r.left+5,clientY:r.top+5,deltaY:-120}));})()""")
    assert js("packets.filter(m=>m.type==='input')") == [
        {'type': 'input', 'paneId': '%901', 'data': '\x1b[<64;1;1M'}]
    js(f"writeHistory(p,'\\x1b[?{mode}l\\x1b[?1003l')")
    assert js('view().width') >= 12
