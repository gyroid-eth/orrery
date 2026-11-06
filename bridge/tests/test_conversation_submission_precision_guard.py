"""New reads can contain pre-existing records from the same second."""
import base64,json,sys,time
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'bridge/tests'))
from test_conversation_submissions import cockpit,prepare
OUT=Path(__file__).parent

@pytest.mark.parametrize('provider',['claude','hermes'])
@pytest.mark.parametrize('case',['known-same','unseen-same','unseen-different'])
def test_presend_record_from_same_second_cannot_confirm_or_discredit_new_send(cockpit,provider,case):
    js,wait,client=prepare(cockpit,provider)
    js("clock=Math.floor(clock/1000)*1000+600;window.releaseOld=false;window.preexistingRecord={id:'preexisting-same-second',role:'user',kind:'text',text:"+('"Different earlier user record"' if case=='unseen-different' else 'sentText')+",ts:new Date(clock-500).toISOString()};OrreryConversationSource.Source.prototype.read=async()=>({provider:"+json.dumps(provider)+",mode:"+json.dumps('snapshot' if provider=='hermes' else 'cursor')+",events:[oldRecord,...(releaseOld?[preexistingRecord]:[])],after:'old-tail'});")
    if case=='known-same':
        js('releaseOld=true;conversationView.refresh()')
        wait("reader.querySelector('[data-event-id=preexisting-same-second]')!==null")
    js('promptInput.value=sentText;sendPrompt()');wait('receipts.length===1')
    assert js("reader.querySelectorAll('.conversation-submission').length")==1
    # A post-send fetch returns a record timestamped 500ms BEFORE the send.
    js('releaseOld=true;conversationView.refresh()')
    wait("reader.querySelector('[data-event-id=preexisting-same-second]')!==null")
    time.sleep(.1)
    state=js("({submittedAt:receipts[0].submittedAt,existingAt:Date.parse(preexistingRecord.ts),pending:reader.querySelectorAll('.conversation-submission').length,label:reader.querySelector('.conversation-submission .conversation-byline')?.textContent})")
    print(provider,case,state)
    assert state['existingAt']<state['submittedAt']
    assert state['pending']==1,state
    assert 'record not matched' not in state['label'],state

@pytest.mark.parametrize('same',[True,False])
def test_pre_send_snapshot_cannot_become_new_on_later_repeat(cockpit,same):
    js,wait,client=prepare(cockpit,'hermes')
    js("clock=Math.floor(clock/1000)*1000+100;window.precisionOld={id:'before-snapshot',role:'user',kind:'text',text:"+('sentText' if same else "'Different old user record'")+",ts:new Date(Math.floor(clock/1000)*1000).toISOString()};window.finishOld=null;window.finishRepeat=null;window.reads=0;OrreryConversationSource.Source.prototype.read=()=>++reads===1?new Promise(r=>finishOld=r):reads===2?new Promise(r=>finishRepeat=r):Promise.resolve({mode:'snapshot',events:[oldRecord,precisionOld],after:'tail'});conversationView.refresh();clock+=300;promptInput.value=sentText;sendPrompt()")
    wait('receipts.length===1')
    js("finishOld({mode:'snapshot',events:[oldRecord,precisionOld],after:'old'})")
    wait('typeof finishRepeat==="function"')
    js("finishRepeat({mode:'snapshot',events:[oldRecord,precisionOld,{id:'progress',kind:'text',role:'assistant',text:'Generated progress'}],after:'next'})")
    wait("reader.querySelector('[data-event-id=progress]')!==null")
    assert js("reader.querySelectorAll('.conversation-submission').length")==1
    assert js("reader.querySelector('.conversation-submission').textContent.includes('record not matched')")==same


def test_user_ids_seen_in_previous_snapshot_remain_excluded(cockpit):
    js,wait,client=prepare(cockpit,'hermes')
    js("window.previousUser={id:'previous-user',kind:'text',role:'user',text:sentText,ts:new Date(clock+100000).toISOString()};window.oldVisible=true;OrreryConversationSource.Source.prototype.read=async()=>({mode:'snapshot',events:oldVisible?[previousUser]:[{id:'assistant-only',kind:'text',role:'assistant',text:'Generated progress'}],after:'snapshot'});conversationView.refresh()")
    wait("reader.querySelector('[data-event-id=previous-user]')!==null")
    js('oldVisible=false;conversationView.refresh()')
    wait("reader.querySelector('[data-event-id=previous-user]')===null")
    js('promptInput.value=sentText;sendPrompt()');wait('receipts.length===1')
    js('oldVisible=true;conversationView.refresh()')
    wait("reader.querySelector('[data-event-id=previous-user]')!==null")
    assert js("reader.querySelectorAll('.conversation-submission').length")==1
    assert not js("reader.querySelector('.conversation-submission').textContent.includes('record not matched')")


def test_hermes_user_ids_stay_stable_across_snapshot_changes(tmp_path):
    from test_conversation_providers import make_db,row,page
    p=tmp_path/'state.db';db=make_db(p)
    db.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(1,'fixture-session','user','Generated prior user',1793775600)");db.commit()
    first=page(row(p,'hermes'))['events'][0]['id']
    db.execute("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(2,'fixture-session','assistant','Generated progress',1793775601)");db.commit()
    second=next(e['id'] for e in page(row(p,'hermes'))['events'] if e['role']=='user');db.close()
    assert first==second=='1:0:0'
