"""Ephemeral send receipts stay distinct from delayed provider records."""
import sys,json,time
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_conversation_review_regressions import cockpit,stable_roster
from test_split_pane_headers import setup


def prepare(cockpit,provider='codex',split=False):
    js,wait,client,requests,enable=cockpit
    if split:js,wait,client=setup(cockpit,2);js("document.querySelector('.split-cell[data-session=ReviewFixture] .split-history-toggle').click()")
    else:stable_roster(js);enable(count=1)
    wait("document.querySelector('.conversation-event')!==null")
    # This HTTP fixture has no WebSocket backend. Its reconnect loop must not
    # replace the captured socket halfway through a generated paste/Enter.
    js("clearTimeout(reconnectTimer);scheduleReconnect=()=>{}")
    js("""window.clock=Date.now();window.realNow=Date.now;Date.now=()=>clock;
      window.sentText='Generated queued prompt <img src=x onerror=alert(1)>';window.turnDone=false;
      window.oldRecord={id:'old',kind:'text',role:'user',text:sentText,ts:new Date(clock-10000).toISOString()};
      window.newRecord={id:'new',kind:'text',role:'user',text:sentText,ts:new Date(clock+600000).toISOString()};
      window.receipts=[];document.addEventListener('oc:prompt-submitted',e=>receipts.push(e.detail));
      window.receiptTimers=[];window.originalTimeout=window.setTimeout;window.setTimeout=(f,ms,...args)=>{if(ms>=59000&&ms<=60000)receiptTimers.push(f);return originalTimeout(f,ms,...args)};
      OrreryConversationSource.Source.prototype.read=async(name,options)=>({agent:name,provider:"""+json.dumps(provider)+""",mode:"""+json.dumps('snapshot' if provider=='hermes' else 'cursor')+""",events:turnDone?[oldRecord,newRecord,{id:'reply',kind:'text',role:'assistant',text:'Generated turn response'}]:[oldRecord],after:'tail',has_older:true});
      conversationView.refresh();
      window.reader=document.querySelector('.conversation-panel:not([hidden])');
      if(reader.parentElement.querySelector('.conversation-expand').getAttribute('aria-pressed')!=='true')reader.parentElement.querySelector('.conversation-expand').click();
    """)
    wait("reader.querySelector('[data-event-id=old]')!==null")
    return js,wait,client


@pytest.mark.parametrize('provider',['codex','claude','dsh','hermes'])
def test_queued_turn_keeps_receipt_until_exact_new_user_record(cockpit,provider):
    js,wait,client=prepare(cockpit,provider)
    js("promptInput.value=sentText;sendPrompt()")
    wait('receipts.length===1')
    assert js("reader.querySelectorAll('.conversation-submission').length")==1
    assert js("reader.querySelector('.conversation-submission').textContent.includes('ReviewFixture')")
    assert not js("reader.querySelector('.conversation-submission img')")
    assert js("reader.parentElement.classList.contains('conversation-just-submitted')")
    assert js("reader.querySelector('.conversation-submission').getBoundingClientRect().bottom<=reader.querySelector('.conversation-scroll').getBoundingClientRect().bottom")
    js("clock+=60001;receiptTimers.forEach(f=>f());conversationView.refresh()")
    assert js("reader.querySelector('.conversation-submission').textContent.includes('Not recorded yet')")
    js("clock+=600000;conversationView.refresh()")
    assert js("reader.querySelectorAll('.conversation-submission').length")==1
    js('turnDone=true;conversationView.refresh()')
    wait("reader.querySelector('[data-event-id=new]')!==null")
    assert js("reader.querySelectorAll('.conversation-submission').length")==0
    js('conversationView.refresh()')
    assert js("reader.querySelectorAll('[data-event-id=new]').length")==1
    assert js("packets.filter(p=>p.type==='input').map(p=>p.paneId)")==['%901','%901']


def test_split_receipt_stays_on_sent_pane_when_focus_moves(cockpit):
    js,wait,client=prepare(cockpit,split=True)
    js("promptInput.value=sentText;sendPrompt();document.querySelector('.split-cell[data-session=OtherFixture] .split-history-toggle').click()")
    wait('receipts.length===1')
    assert js("document.querySelectorAll('.split-cell[data-session=ReviewFixture] .conversation-submission').length")==1
    assert js("document.querySelectorAll('.split-cell[data-session=OtherFixture] .conversation-submission').length")==0
    assert js('promptTarget.textContent')=='OtherFixture'
    assert js("packets.filter(p=>p.type==='input').map(p=>p.paneId)")==['%901','%901']


@pytest.mark.parametrize('failure',['paste','enter','removed','guard'])
def test_failed_or_guarded_send_never_claims_sent(cockpit,failure):
    js,wait,client=prepare(cockpit)
    if failure=='paste':js("send=()=>false")
    if failure=='enter':js("send=p=>p.data!=='\\r'")
    js("promptInput.value="+('"/logout"' if failure=='guard' else 'sentText')+";sendPrompt()"+(";panes.delete('%901')" if failure=='removed' else ''))
    time.sleep(.35)
    assert js('receipts.length')==0
    assert js("reader.querySelectorAll('.conversation-submission').length")==0


def test_repeated_prompt_matches_fifo_once_and_binding_change_clears(cockpit):
    js,wait,client=prepare(cockpit)
    for i in range(2):
        js('promptInput.value=sentText;sendPrompt()');wait('receipts.length==='+str(i+1))
    assert js("reader.querySelectorAll('.conversation-submission').length")==2
    js('turnDone=true;conversationView.refresh()')
    wait("reader.querySelectorAll('.conversation-submission').length===1")
    js('conversationView.refresh()')
    assert js("reader.querySelectorAll('.conversation-submission').length")==1
    js("currentAgents[0].history_session_id='different';document.dispatchEvent(new Event('oc:agents'))")
    assert js("reader.querySelectorAll('.conversation-submission').length")==0


def test_receipt_survives_close_reopen_and_clears_on_off(cockpit):
    js,wait,client=prepare(cockpit)
    js('promptInput.value=sentText;sendPrompt()');wait('receipts.length===1')
    js('conversationView.close();conversationView.open()')
    wait("reader.querySelectorAll('.conversation-submission').length===1")
    js("conversationEnabled.checked=false;conversationEnabled.dispatchEvent(new Event('change'))")
    assert js("document.querySelectorAll('.conversation-submission').length")==0


def test_inflight_new_page_can_reconcile_but_older_page_cannot(cockpit):
    js,wait,client=prepare(cockpit)
    js("window.finishRead=null;OrreryConversationSource.Source.prototype.read=()=>new Promise(r=>finishRead=r);conversationView.refresh();promptInput.value=sentText;sendPrompt()")
    wait('receipts.length===1')
    js("finishRead({events:[newRecord],after:'new-tail'});OrreryConversationSource.Source.prototype.read=async()=>({events:[],after:'new-tail'})")
    wait("reader.querySelectorAll('.conversation-submission').length===0")
    js('promptInput.value=sentText;sendPrompt()');wait('receipts.length===2')
    js("OrreryConversationSource.Source.prototype.read=async()=>({events:[{...newRecord,id:'older-copy'}],after:'older'});reader.querySelector('.conversation-older').hidden=false;reader.querySelector('.conversation-older').click()")
    time.sleep(.1)
    assert js("reader.querySelectorAll('.conversation-submission').length")==1
