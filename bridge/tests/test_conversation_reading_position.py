from test_conversation_review_regressions import wait_reading_layout
"""Exercise re-narrowing after the fixed collapse, and continuous resizing."""
import sys,time,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from test_conversation_survivor_sequences import cockpit,prepare,open_reader,full,close_other,screenshot

def boundary(js):
    js("""sequencePanels.ReviewFixture.querySelector('.conversation-mail-summary').click();
      window.readScroll=sequencePanels.ReviewFixture.querySelector('.conversation-scroll');
      window.readMessage=sequencePanels.ReviewFixture.querySelector('[data-event-id=ReviewFixture-text-8]');
      readScroll.dispatchEvent(new WheelEvent('wheel'));readScroll.scrollTop+=readMessage.getBoundingClientRect().top-readScroll.getBoundingClientRect().top-20;
      window.readPosition=()=>({top:readMessage.getBoundingClientRect().top-readScroll.getBoundingClientRect().top,width:readScroll.clientWidth});
    """)
    wait_reading_layout(js)
    return js('readPosition()')

def test_collapse_then_split_again_keeps_visible_message_boundary(cockpit):
    js,wait,client=prepare(cockpit,2)
    open_reader(js,wait,'ReviewFixture');full(js,'ReviewFixture')
    before=boundary(js)
    close_other(js,'OtherFixture');wait_reading_layout(js)
    collapsed=js('readPosition()')
    js("createPane('OtherFixture',{paneId:'%902',windowId:'@902',width:80,height:20});replaceSplitSessions(['ReviewFixture','OtherFixture']);splitVisible=true;focusSplitSession('ReviewFixture')")
    wait_reading_layout(js)
    after=js('readPosition()')
    print('split / collapse / split:',before,collapsed,after)
    screenshot(js,client,'reverse-split.png')
    assert js("sequencePanels.ReviewFixture.isConnected&&!sequencePanels.ReviewFixture.hidden&&sequencePanels.ReviewFixture.querySelector('.conversation-mail').open")
    assert abs(collapsed['top']-before['top'])<30,(before,collapsed)
    assert abs(after['top']-before['top'])<30,(before,after)

def test_continuous_resize_roundtrip_keeps_message_boundary(cockpit):
    js,wait,client=prepare(cockpit,2)
    open_reader(js,wait,'ReviewFixture');full(js,'ReviewFixture')
    initial=boundary(js)
    points=[]
    for width in [1200,900,390,1600]:
        client.call('Emulation.setDeviceMetricsOverride',width=width,height=1000,deviceScaleFactor=1,mobile=False)
        wait_reading_layout(js)
        points.append({'viewport':width,**js('readPosition()')})
    print('resize:',initial,points)
    screenshot(js,client,'resize-roundtrip.png')
    assert all(abs(p['top']-initial['top'])<30 for p in points),(initial,points)

def test_long_message_line_through_image_preview_and_collapse(cockpit):
    js,wait,client=prepare(cockpit,2)
    js(r"""window.longText=Array.from({length:300},(_,i)=>'Paragraph '+String(i).padStart(4,'0')+': This is generated history text for testing stable reading through layout changes.').join('\n');
      OrreryConversationSource.Source.prototype.read=async(name,options)=>({events:options.after?[]:[{id:'long-message',role:'assistant',kind:'text',text:longText},{id:'image-event',role:'assistant',kind:'tool',text:'View image',references:[{id:'A'.repeat(32),label:'fixture.png',kind:'image'}]}],after:'long-tail'});
      OrreryConversationSource.Source.prototype.reference=async()=>({kind:'image',mime:'image/png',width:1,height:1,data:'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jv1sAAAAASUVORK5CYII='});
      sequenceOpen('ReviewFixture');
    """)
    wait("sequencePanels.ReviewFixture.querySelector('[data-event-id=long-message]')!==null")
    full(js,'ReviewFixture')
    js("""window.longPanel=sequencePanels.ReviewFixture;window.longScroll=longPanel.querySelector('.conversation-scroll');
      window.longNode=longPanel.querySelector('[data-event-id=long-message] .conversation-text').firstChild;
      window.readRange=document.createRange();window.readOffset=longText.indexOf('Paragraph 0120');readRange.setStart(longNode,readOffset);readRange.setEnd(longNode,readOffset+1);
      window.linePosition=()=>{const r=document.createRange();r.setStart(longNode,readOffset);r.setEnd(longNode,readOffset+1);return {lineTop:r.getBoundingClientRect().top-longScroll.getBoundingClientRect().top,eventTop:longNode.parentElement.getBoundingClientRect().top-longScroll.getBoundingClientRect().top,width:longScroll.clientWidth}};
      longScroll.dispatchEvent(new WheelEvent('wheel'));longScroll.scrollTop+=readRange.getBoundingClientRect().top-longScroll.getBoundingClientRect().top-30;
    """)
    wait_reading_layout(js)
    before=js('linePosition()')
    screenshot(js,client,'long-line-before.png')
    js("longPanel.querySelector('.conversation-file').click()")
    wait("longPanel.querySelector('.conversation-preview-image')?.naturalWidth===1")
    js("window.keptImage=longPanel.querySelector('.conversation-preview-image')")
    close_other(js,'OtherFixture');wait_reading_layout(js)
    assert js('keptImage.isConnected&&keptImage===longPanel.querySelector(".conversation-preview-image")')
    screenshot(js,client,'long-image-survives.png')
    js("longPanel.querySelector('.conversation-preview-close').click()")
    wait_reading_layout(js)
    after=js('linePosition()')
    screenshot(js,client,'long-line-after.png')
    print('same character Paragraph 0120:',before,'=>',after)
    assert js('longPanel.isConnected&&!longPanel.hidden')
    assert abs(after['lineTop']-before['lineTop'])<30,(before,after)
