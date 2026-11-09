from test_conversation_review_regressions import wait_reading_layout
"""A live pane owns its reader independently of split/host geometry."""
import sys,time,json
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_split_pane_headers import cockpit,setup


def prepare(cockpit,count,mode):
    js,wait,client=setup(cockpit,count)
    js("""window.owner='ReviewFixture';window.closedName="""+json.dumps(['ReviewFixture','OtherFixture','ThirdFixture','FourthFixture'][count-1])+""";
      window.survivorAborted={};window.survivorReads={};
      OrreryConversationSource.Source.prototype.read=async(name,options)=>{
        survivorReads[name]=(survivorReads[name]||0)+1;
        if(options.after){options.signal.addEventListener('abort',()=>survivorAborted[name]=true);return new Promise(()=>{});}
        return {agent:name,mode:'cursor',after:'one',has_older:true,events:[
          ...Array.from({length:25},(_,i)=>({id:'message-'+i,kind:'text',role:'assistant',text:'Generated paragraph '+i+'. '+('Reading history safely. '.repeat(12))})),
          {id:'mail',kind:'mail',role:'user',text:'Generated mail',mail:[{direction:'received',sender:'ParentFixture',subject:'Generated mail',coverage:'complete',body:'Generated expanded body'}]},
          {id:'file',kind:'tool',role:'assistant',text:'Read',references:[{id:'A'.repeat(32),label:'example.py',kind:'file'}]}
        ]};
      };
      OrreryConversationSource.Source.prototype.reference=async()=>({kind:'text',text:'Generated preview stays mounted'});
      document.querySelector('.split-cell[data-session=ReviewFixture] .split-history-toggle').click();
    """)
    wait("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-mail')!==null")
    js("""window.keptPanel=document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-panel');
      keptPanel.querySelector('.conversation-mail').open=true;
      window.keptMail=keptPanel.querySelector('.conversation-mail');
    """)
    if mode=='full':js("keptPanel.parentElement.querySelector('.conversation-expand').click()")
    if mode=='preview':
        js("keptPanel.querySelector('.conversation-file').click()")
        wait("keptPanel.querySelector('.conversation-preview-text')!==null")
    js("keptPanel.querySelector('.conversation-scroll').scrollTop=260;window.keptTop=keptPanel.querySelector('.conversation-scroll').scrollTop")
    time.sleep(.1)
    js("document.querySelector('.split-cell[data-session='+closedName+'] .split-history-toggle').click()")
    wait("document.querySelector('.split-cell[data-session='+closedName+'] .conversation-mail')!==null")
    js("window.removedPanel=document.querySelector('.split-cell[data-session='+closedName+'] .conversation-panel');conversationView.refresh();focusSplitSession('ReviewFixture');conversationView.refresh();packets.length=0")
    return js,wait,client


@pytest.mark.parametrize('count',[2,3,4])
@pytest.mark.parametrize('mode',['side','full','preview'])
@pytest.mark.parametrize('rebuild',[False,True])
def test_closing_another_pane_keeps_reader_instance_and_state(cockpit,count,mode,rebuild):
    js,wait,client=prepare(cockpit,count,mode)
    js("document.querySelector('.split-cell[data-session='+closedName+'] .scl-close').click()")
    if rebuild:js("emptySplitCells();renderStage()")
    wait_reading_layout(js)
    assert js('keptPanel.isConnected&&!keptPanel.hidden')
    assert js("keptPanel.querySelector('.conversation-mail')===keptMail&&keptMail.open")
    assert js("keptPanel.parentElement.classList.contains('conversation-full')")== (mode!='side')
    if mode!='preview':assert js("keptPanel.querySelector('.conversation-scroll').scrollTop")>0
    assert not js("survivorAborted.ReviewFixture")
    assert js("survivorAborted[closedName]")
    assert not js('removedPanel.isConnected')
    if mode=='preview':assert js("keptPanel.querySelector('.conversation-preview-text').textContent")=='Generated preview stays mounted'
    if count==2:assert js("keptPanel.parentElement.classList.contains('screen')")
    else:assert js("keptPanel.parentElement.dataset.session")=='ReviewFixture'
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))")==[]


def test_tab_single_split_rebuild_resize_keep_per_pane_reader(cockpit):
    js,wait,client=prepare(cockpit,2,'preview')
    js("setActive(paneIdForSession('ReviewFixture'),'single')")
    assert js('keptPanel.isConnected&&!keptPanel.hidden')
    js("setActive(paneIdForSession('OtherFixture'),'single')")
    assert js('!keptPanel.isConnected||keptPanel.hidden')
    js("setActive(paneIdForSession('ReviewFixture'),'single')")
    assert js('keptPanel.isConnected&&!keptPanel.hidden&&keptMail.open')
    js("replaceSplitSessions(['OtherFixture','ReviewFixture']);splitVisible=true;focusSplitSession('ReviewFixture');emptySplitCells();renderStage()")
    client.call('Emulation.setDeviceMetricsOverride',width=900,height=900,deviceScaleFactor=1,mobile=False)
    wait_reading_layout(js)
    assert js('keptPanel.isConnected&&!keptPanel.hidden&&keptMail.open')
    assert js("keptPanel.querySelector('.conversation-preview-text').textContent")=='Generated preview stays mounted'
    js("conversationEnabled.checked=false;conversationEnabled.dispatchEvent(new Event('change'))")
    assert not js('keptPanel.isConnected')
    assert js("document.querySelectorAll('.conversation-panel,.split-history-toggle').length")==0


def test_owner_replacement_disposes_old_reader_even_if_session_name_stays(cockpit):
    js,wait,client=prepare(cockpit,2,'full')
    js("resetSession({session:'ReviewFixture',panes:[{paneId:'%990',windowId:'@990',width:80,height:20}]})")
    assert not js('keptPanel.isConnected')
    assert js('survivorAborted.ReviewFixture')
    js("document.querySelector('.split-cell[data-session=ReviewFixture] .split-history-toggle').click()")
    wait("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-mail')!==null")
    assert js("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-panel')!==keptPanel")
    assert not js("document.querySelector('.split-cell[data-session=ReviewFixture] .conversation-mail').open")


def test_pending_preview_survives_host_migration_and_finishes_in_same_reader(cockpit):
    js,wait,client=prepare(cockpit,2,'full')
    js("""window.previewSignal=null;window.finishSurvivingPreview=null;
      OrreryConversationSource.Source.prototype.reference=(id,options)=>{previewSignal=options.signal;return new Promise(resolve=>finishSurvivingPreview=resolve)};
      keptPanel.querySelector('.conversation-file').click();
      document.querySelector('.split-cell[data-session='+closedName+'] .scl-close').click();""")
    assert not js('previewSignal.aborted')
    assert js('keptPanel.isConnected&&!keptPanel.hidden')
    js("finishSurvivingPreview({kind:'text',text:'Late generated preview for the same pane'})")
    wait("keptPanel.querySelector('.conversation-preview-text')?.textContent==='Late generated preview for the same pane'")
