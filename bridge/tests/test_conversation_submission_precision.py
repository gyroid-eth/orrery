"""Independent native precision and continuous send/receipt lifecycle probes."""
import base64,json,sys,time,os
from pathlib import Path
from datetime import datetime,timezone
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'bridge/tests'));sys.path.insert(0,str(ROOT/'bridge'))
from test_conversation_submissions import cockpit,prepare
from conversation_readers import normalize
OUT=Path(os.environ['ORRERY_SUBMISSION_CAPTURE_DIR']) if os.environ.get('ORRERY_SUBMISSION_CAPTURE_DIR') else None

def screenshot(client,name):
    if OUT is None:return
    time.sleep(.15)
    shot=client.call('Page.captureScreenshot',format='png')
    (OUT/name).write_bytes(base64.b64decode(shot['data']))

@pytest.mark.parametrize('provider',['claude','hermes'])
def test_new_native_second_precision_record_replaces_receipt(cockpit,provider):
    js,wait,client=prepare(cockpit,provider)
    submitted=js('clock=Math.floor(clock/1000)*1000+100')
    text=js('sentText')
    stamp=datetime.fromtimestamp(submitted//1000,timezone.utc).isoformat().replace('+00:00','Z')
    raw=({'type':'user','sessionId':'fixture-session','timestamp':stamp,'message':{'role':'user','content':text}}
        if provider=='claude' else {'role':'user','content':text,'timestamp':submitted//1000})
    event=normalize(raw,provider,'fixture-session')[0][1]
    event['id']='new-second-precision'
    js('promptInput.value=sentText;sendPrompt()');wait('receipts.length===1')
    assert js("reader.querySelectorAll('.conversation-submission').length")==1
    # Enter occurs 250ms after paste; the timestamp still has the same whole second.
    js("clock+=250")
    # Publish only after Enter accepted, exactly as the native adapter emits it.
    js('window.secondPrecisionRecord='+json.dumps(event)+';OrreryConversationSource.Source.prototype.read=async()=>({events:[oldRecord,secondPrecisionRecord],mode:'+json.dumps('snapshot' if provider=='hermes' else 'cursor')+',after:"second-tail"});conversationView.refresh()')
    wait("reader.querySelector('[data-event-id=new-second-precision]')!==null")
    js('clock+=60001;receiptTimers.forEach(f=>f());conversationView.refresh()')
    time.sleep(.1)
    observed=js("({submittedAt:receipts[0].submittedAt,recordTimestamp:secondPrecisionRecord.ts,pending:reader.querySelectorAll('.conversation-submission').length,records:reader.querySelectorAll('[data-event-id=new-second-precision]').length,waiting:reader.querySelector('.conversation-submission')?.textContent.includes('Not recorded yet')})")
    print(provider,observed)
    screenshot(client,provider+'-second-precision.png')
    assert observed['records']==1
    assert observed['pending']==0,observed


@pytest.mark.parametrize('provider',['claude','hermes'])
def test_second_precision_two_prompts_reconcile_fifo(cockpit,provider):
    js,wait,client=prepare(cockpit,provider)
    js("clock=Math.floor(clock/1000)*1000+100;window.precisionRows=[];OrreryConversationSource.Source.prototype.read=async()=>({events:[oldRecord,...precisionRows],mode:"+json.dumps('snapshot' if provider=='hermes' else 'cursor')+",after:'precision'})")
    for count in [1,2]:
        js('promptInput.value=sentText;sendPrompt()');wait('receipts.length==='+str(count));js('clock+=300')
    ids=js("[...reader.querySelectorAll('.conversation-submission')].map(e=>e.dataset.submissionId)")
    for n in [1,2]:
        js("precisionRows.push({id:'precision-'+"+str(n)+",kind:'text',role:'user',text:sentText,ts:new Date(Math.floor(clock/1000)*1000).toISOString()});conversationView.refresh()")
        wait("reader.querySelector('[data-event-id=precision-"+str(n)+"]')!==null")
        assert js("[...reader.querySelectorAll('.conversation-submission')].map(e=>e.dataset.submissionId)")==ids[n:]
        js('conversationView.refresh()')
        assert js("reader.querySelectorAll('.conversation-submission').length")==2-n

@pytest.mark.parametrize('variant',['whitespace','truncated','unknown','ambiguous-prefix'])
def test_reformatted_truncated_and_uncertain_receipts(cockpit,variant):
    js,wait,client=prepare(cockpit)
    sent='Heading\n\n  body\tend' if variant=='whitespace' else ('a'*65537 if variant=='truncated' else 'Generated prompt A '+('x'*300))
    js('sentText='+json.dumps(sent)+';promptInput.value=sentText;sendPrompt()');wait('receipts.length===1')
    if variant=='ambiguous-prefix':
        js("promptInput.value=sentText+'different';sendPrompt()");wait('receipts.length===2')
    recorded='Heading body end' if variant=='whitespace' else sent[:65536] if variant=='truncated' else 'Different generated record' if variant=='unknown' else sent[:256]
    event=dict(id='reformatted',kind='text',role='user',text=recorded,truncated=variant in ['truncated','ambiguous-prefix'])
    js('window.variantRecord='+json.dumps(event)+";variantRecord.ts=new Date(clock+1000).toISOString();OrreryConversationSource.Source.prototype.read=async()=>({events:[oldRecord,variantRecord],after:'variant'});conversationView.refresh()")
    wait("reader.querySelector('[data-event-id=reformatted]')!==null")
    if variant in ['whitespace','truncated']:assert js("reader.querySelectorAll('.conversation-submission').length")==0
    else:
        assert js("reader.querySelectorAll('.conversation-submission').length")== (2 if variant=='ambiguous-prefix' else 1)
        assert js("reader.querySelector('.conversation-submission').textContent.includes('Record not matched')")
        js('clock+=600000;receiptTimers.forEach(f=>f());conversationView.refresh()')
        assert not js("reader.querySelector('.conversation-submission').textContent.includes('Not recorded yet')")
