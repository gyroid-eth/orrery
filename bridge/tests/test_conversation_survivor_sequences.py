from test_conversation_review_regressions import wait_reading_layout
"""Independent continuous user sequences on private, synthetic cockpit data."""
import base64,json,sys,time,os
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'bridge/tests'))
from test_conversation_review_regressions import cockpit
from test_split_pane_headers import setup
OUT=Path(os.environ['ORRERY_SURVIVOR_CAPTURE_DIR']) if os.environ.get('ORRERY_SURVIVOR_CAPTURE_DIR') else None

def prepare(cockpit,count):
    js,wait,client=setup(cockpit,count)
    js(r"""window.sequenceReads=[];window.sequenceSent=false;
      const oldSend=window.send;window.send=p=>{if(p.type==='input'&&p.data.includes('survivor prompt'))sequenceSent=true;return oldSend(p)};
      OrreryConversationSource.Source.prototype.reference=async()=>({kind:'text',text:'Synthetic retained preview'});
      OrreryConversationSource.Source.prototype.read=async(name,options)=>{
        sequenceReads.push({name,before:options.before,after:options.after});
        if(options.after)return {agent:name,mode:'cursor',events:sequenceSent?[{id:name+'-response',kind:'text',role:'assistant',text:'Synthetic response after submitted prompt'}]:[],after:name+'-new',has_older:true};
        return {agent:name,mode:'cursor',before:name+'-old',after:name+'-tail',has_older:true,events:Array.from({length:50},(_,i)=>i===9?
          {id:name+'-mail',kind:'mail',role:'user',text:'Generated Mail',mail:[{direction:'received',sender:'ParentFixture',subject:'Retained card',coverage:'complete',body:'Synthetic expanded mail body. '.repeat(20)}]}:i===15?
          {id:name+'-file',kind:'tool',role:'assistant',text:'Read',references:[{id:'A'.repeat(32),label:'fixture.txt',kind:'file'}]}:
          {id:name+'-text-'+i,kind:'text',role:'assistant',text:'Synthetic message '+i+'. '+('A paragraph for testing the reading position. '.repeat(16))})};
      };
      window.sequencePanels={};window.sequenceAnchors={};
      window.sequenceOpen=name=>{document.querySelector('.split-cell[data-session='+name+'] .split-history-toggle').click();sequencePanels[name]=document.querySelector('.split-cell[data-session='+name+'] .conversation-panel')};
      window.sequenceAnchor=name=>{const p=sequencePanels[name],s=p.querySelector('.conversation-scroll'),top=s.getBoundingClientRect().top,e=[...p.querySelectorAll('.conversation-event')].find(e=>e.getBoundingClientRect().bottom>top);return {id:e?.dataset.eventId,offset:e?e.getBoundingClientRect().top-top:null,scroll:s.scrollTop}};
      window.sequencePlace=(name,id)=>{const p=sequencePanels[name],s=p.querySelector('.conversation-scroll'),e=p.querySelector('[data-event-id="'+id+'"]');s.dispatchEvent(new WheelEvent('wheel'));s.scrollTop+=e.getBoundingClientRect().top-s.getBoundingClientRect().top+40};
    """)
    return js,wait,client

def open_reader(js,wait,name):
    js('sequenceOpen('+json.dumps(name)+')')
    wait('sequencePanels['+json.dumps(name)+'].querySelector(".conversation-mail")!==null')

def full(js,name):
    js('(()=>{const b=sequencePanels['+json.dumps(name)+'].parentElement.querySelector(".conversation-expand");if(b.getAttribute("aria-pressed")!=="true")b.click()})()')

def anchor(js,name):return js('sequenceAnchor('+json.dumps(name)+')')
def place(js,name,event):
    js('sequencePlace('+json.dumps(name)+','+json.dumps(event)+')')
    time.sleep(.1)
    return anchor(js,name)
def verify_anchor(js,name,saved):
    current=anchor(js,name)
    print(name,'anchor',saved,'=>',current)
    assert current['id']==saved['id'],(saved,current)
    assert abs(current['offset']-saved['offset'])<30,(saved,current)
def close_other(js,name):js("document.querySelector('.split-cell[data-session="+name+"] .scl-close').click()")
def screenshot(js,client,name):
    if OUT is None:return
    wait_reading_layout(js)
    shot=client.call('Page.captureScreenshot',format='png')
    (OUT/name).write_bytes(base64.b64decode(shot['data']))

def test_full_mail_past_close_other_send_then_split_and_close_owner(cockpit):
    js,wait,client=prepare(cockpit,2)
    name='ReviewFixture';open_reader(js,wait,name);full(js,name)
    js("sequencePanels.ReviewFixture.querySelector('.conversation-mail-summary').click();window.savedMail=sequencePanels.ReviewFixture.querySelector('.conversation-mail')")
    saved=place(js,name,name+'-text-8')
    close_other(js,'OtherFixture');wait_reading_layout(js)
    assert js("sequencePanels.ReviewFixture.isConnected&&!sequencePanels.ReviewFixture.hidden&&sequencePanels.ReviewFixture.parentElement.classList.contains('conversation-full')")
    assert js("savedMail.isConnected&&savedMail.open&&sequencePanels.ReviewFixture.querySelector('.conversation-mail')===savedMail")
    verify_anchor(js,name,saved)
    screenshot(js,client,'sequence-mail-survivor.png')
    js("packets.length=0;promptInput.value='survivor prompt';promptSend.click()")
    wait("sequencePanels.ReviewFixture.querySelector('[data-event-id=ReviewFixture-response]')!==null")
    assert js("(()=>{const s=sequencePanels.ReviewFixture.querySelector('.conversation-scroll');return s.scrollHeight-s.clientHeight-s.scrollTop<45})()")
    assert js("packets.filter(p=>p.type==='input').every(p=>p.paneId==='%901')&&packets.filter(p=>p.type==='input').length===2")
    js("currentAgents.push({name:'ThirdFixture',program:'codex',history_binding:'bound'});createPane('ThirdFixture',{paneId:'%903',windowId:'@903',width:80,height:20});replaceSplitSessions(['ReviewFixture','ThirdFixture']);splitVisible=true;focusSplitSession('ThirdFixture')")
    open_reader(js,wait,'ThirdFixture')
    assert js('sequencePanels.ReviewFixture.isConnected&&!sequencePanels.ReviewFixture.hidden&&savedMail.open')
    close_other(js,'ReviewFixture')
    assert js('!sequencePanels.ReviewFixture.isConnected')
    assert js('sequencePanels.ThirdFixture.isConnected&&!sequencePanels.ThirdFixture.hidden')

def test_preview_mail_close_reorder_resize_tabs_and_close_owner(cockpit):
    js,wait,client=prepare(cockpit,4)
    a='ReviewFixture';c='ThirdFixture'
    open_reader(js,wait,a);full(js,a)
    saved_a=place(js,a,a+'-text-11')
    js("sequencePanels.ReviewFixture.querySelector('.conversation-file').click()")
    wait("sequencePanels.ReviewFixture.querySelector('.conversation-preview-text')!==null")
    open_reader(js,wait,c);full(js,c)
    js("sequencePanels.ThirdFixture.querySelector('.conversation-mail-summary').click();window.thirdMail=sequencePanels.ThirdFixture.querySelector('.conversation-mail')")
    saved_c=place(js,c,c+'-text-7')
    close_other(js,'OtherFixture')
    js("replaceSplitSessions(['FourthFixture','ThirdFixture','ReviewFixture']);renderStage()")
    client.call('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=False)
    wait_reading_layout(js)
    assert js("sequencePanels.ReviewFixture.querySelector('.conversation-preview-text').textContent==='Synthetic retained preview'")
    verify_anchor(js,c,saved_c)
    js("setActive(paneIdForSession('ThirdFixture'),'single');setActive(paneIdForSession('ReviewFixture'),'single');restoreSplit()")
    wait_reading_layout(js)
    assert js('sequencePanels.ReviewFixture.isConnected&&sequencePanels.ThirdFixture.isConnected&&thirdMail.open')
    client.call('Emulation.setDeviceMetricsOverride',width=1600,height=1000,deviceScaleFactor=1,mobile=False)
    wait_reading_layout(js)
    close_other(js,'FourthFixture')
    js("sequencePanels.ReviewFixture.querySelector('.conversation-preview-close').click()")
    wait_reading_layout(js)
    verify_anchor(js,a,saved_a)
    verify_anchor(js,c,saved_c)
    screenshot(js,client,'sequence-two-survivors.png')
    close_other(js,'ReviewFixture')
    wait_reading_layout(js)
    assert js('!sequencePanels.ReviewFixture.isConnected')
    assert js('sequencePanels.ThirdFixture.isConnected&&!sequencePanels.ThirdFixture.hidden&&thirdMail.open')
    verify_anchor(js,c,saved_c)

def test_collapse_does_not_skip_start_of_message_at_reading_boundary(cockpit):
    js,wait,client=prepare(cockpit,2)
    open_reader(js,wait,'ReviewFixture');full(js,'ReviewFixture')
    js("""sequencePanels.ReviewFixture.querySelector('.conversation-mail-summary').click();
      window.boundaryScroll=sequencePanels.ReviewFixture.querySelector('.conversation-scroll');
      window.boundaryMessage=sequencePanels.ReviewFixture.querySelector('[data-event-id=ReviewFixture-text-8]');
      boundaryScroll.dispatchEvent(new WheelEvent('wheel'));boundaryScroll.scrollTop+=boundaryMessage.getBoundingClientRect().top-boundaryScroll.getBoundingClientRect().top-20;
      window.boundaryPosition=()=>({messageTop:boundaryMessage.getBoundingClientRect().top-boundaryScroll.getBoundingClientRect().top,
        previousHeight:boundaryMessage.previousElementSibling.getBoundingClientRect().height,
        anchor:sequenceAnchor('ReviewFixture'),width:boundaryScroll.clientWidth});
    """)
    wait_reading_layout(js)
    before=js('boundaryPosition()')
    screenshot(js,client,'reading-boundary-before.png')
    close_other(js,'OtherFixture');wait_reading_layout(js)
    after=js('boundaryPosition()')
    screenshot(js,client,'reading-boundary-after.png')
    print('reading boundary:',before,'=>',after)
    assert js("sequencePanels.ReviewFixture.isConnected&&!sequencePanels.ReviewFixture.hidden&&sequencePanels.ReviewFixture.parentElement.classList.contains('conversation-full')")
    assert js("sequencePanels.ReviewFixture.querySelector('.conversation-mail').open")
    assert abs(after['messageTop']-before['messageTop'])<30,(before,after)
