"""The provider transcript is an independent draggable reader, not xterm state."""

import pytest

from test_demo_mode_browser import CHROME, browser, wait

pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chromium (set ORRERY_CHROME)")


def setup_history(js):
    js("""OrreryTour.state.close();window.packets=[];
      window.send=packet=>{packets.push(packet);return true;};
      window.originalFetch=window.fetch.bind(window);window.requestedPaths=[];
      window.fetch=(url,...rest)=>{
        if(!String(url).startsWith('/telemetry/transcript?'))
          return originalFetch(url,...rest);
        requestedPaths.push(String(url));\n        const older=String(url).includes('before=');
        const count=older?20:100;
        const items=Array.from({length:count},(_,i)=>({
          role:i%2?'assistant':'user',
          text:'synthetic message '+(older?i:i+20)+'\\n'.repeat(4)+'an independent history line',
          clipped:false
        }));
        return Promise.resolve({ok:true,json:async()=>({
          provider:'codex',source_id:'1234567890abcdef',items,has_older:!older,older_before:older?null:110,
        })});
      };
      createPane('HistoryFixture',{paneId:'%991',width:85,height:20,
        alternateOn:true,mouseTracking:true});
      window.p=panes.get('%991');
      setActive('%991');
      window.settle=()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    """)


def bounds(js):
    return js("""(()=>{
      const e=p.historyScroll,r=e.getBoundingClientRect();
      return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,
        height:e.clientHeight,total:e.scrollHeight,at:e.scrollTop,
        width:e.offsetWidth-e.clientWidth};
    })()""")


def test_transcript_view_uses_native_drag_and_leaves_live_tui_unchanged():
    with browser() as (go, js):
        go("")
        assert wait(js, "typeof createPaneTranscript==='function'&&Boolean(window.OrreryTour)")
        setup_history(js)
        assert js("p._wheelAlternate===true")
        assert js("getComputedStyle(p.historyHandle).display!=='none'")
        js("p.historyHandle.click()")
        assert wait(js, "p.historyMessages.children.length===100")
        js("settle()")
        initial = bounds(js)
        assert initial["width"] >= 12
        assert initial["total"] > initial["height"] * 2
        assert initial["at"] > initial["height"]

        # Actual native thumb drag (not setting scrollTop from JS).
        thumb = max(24, initial["height"] ** 2 / initial["total"])
        source = initial["bottom"] - thumb / 2
        target = initial["top"] + thumb / 2 + .2 * (initial["height"] - thumb)
        x = initial["right"] - initial["width"] / 2
        c = js.client
        c.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=source)
        c.call("Input.dispatchMouseEvent", type="mousePressed", x=x, y=source,
               button="left", buttons=1, clickCount=1)
        for step in range(1, 8):
            c.call("Input.dispatchMouseEvent", type="mouseMoved", x=x,
                   y=source + (target - source) * step / 7,
                   button="left", buttons=1)
        c.call("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=target,
               button="left", buttons=0, clickCount=1)
        assert wait(js, "p.historyScroll.scrollTop<p.historyScroll.scrollHeight/2")
        assert js("packets.filter(m=>m.type==='input'||m.type==='codex-page')") == []
        assert js("p.historyPanel.hidden") is False

        js("p.historyOlder.click()")
        assert wait(js, "p.historyMessages.children.length===120")
        assert js("requestedPaths.some(path=>path.includes('source_id=1234567890abcdef'))")
        assert js("p.historyMessages.firstElementChild.textContent.includes('synthetic message 0')")
        assert js("p.historyOlder.hidden")
        js("p.historyPanel.querySelector('.transcript-close').click()")
        assert js("p.historyPanel.hidden")
        assert js("!p.host.classList.contains('history-reading')")
        assert js("packets.filter(m=>m.type==='input'||m.type==='codex-page')") == []


def test_normal_screen_does_not_offer_misleading_transcript_handle():
    with browser() as (go, js):
        go("")
        assert wait(js, "typeof createPaneTranscript==='function'&&Boolean(window.OrreryTour)")
        js("""OrreryTour.state.close();
          createPane('PlainShell',{paneId:'%992',alternateOn:false,mouseTracking:false});
          window.p=panes.get('%992');setActive('%992');""")
        assert js("p._wheelAlternate===false")
        assert js("getComputedStyle(p.historyHandle).display==='none'")
        assert js("p.historyPanel.hidden")
