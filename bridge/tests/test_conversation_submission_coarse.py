"""A pre-started read may return a genuinely new record at Enter dispatch."""
import base64,json,os,sys,time
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'bridge/tests'))
from test_conversation_submissions import cockpit,prepare
@pytest.mark.parametrize('precision',['milliseconds','seconds'])
@pytest.mark.parametrize('migration',[False,True])
def test_true_new_record_resolved_at_enter_is_not_permanently_excluded(cockpit,precision,migration):
    js,wait,client=prepare(cockpit,'hermes',split=migration)
    js("""clock=Math.floor(clock/1000)*1000+100;window.causalReads=0;window.finishCausal=null;window.causalEntered=false;
      OrreryConversationSource.Source.prototype.read=()=>++causalReads===1?new Promise(r=>finishCausal=r):Promise.resolve({mode:'snapshot',events:[oldRecord,currentCausalRecord],after:'current'});
      conversationView.refresh();
      window.beforeCausalSend=send;
      window.send=p=>{const ok=beforeCausalSend(p);if(ok&&p.type==='input'&&p.data==='\\r'&&!causalEntered){
        causalEntered=true;clock+=300;
        window.currentCausalRecord={id:'current-causal-user',kind:'text',role:'user',text:sentText,
          ts:new Date("""+('Math.floor(clock/1000)*1000' if precision=='seconds' else 'clock')+""").toISOString()};
        finishCausal({mode:'snapshot',events:[oldRecord,currentCausalRecord],after:'arrived-at-enter'});
      }return ok;};
      promptInput.value=sentText;sendPrompt();
    """)
    if migration:
        js("document.querySelector('.split-cell[data-session=OtherFixture] .scl-close').click()")
    wait('receipts.length===1&&causalReads>=2')
    wait("reader.querySelector('[data-event-id=current-causal-user]')!==null")
    first=js("({pending:reader.querySelectorAll('.conversation-submission').length,submitted:receipts[0].submittedAt,recordAt:currentCausalRecord.ts,reads:causalReads})")
    js('clock+=60001;receiptTimers.forEach(f=>f());conversationView.close();conversationView.open()')
    wait("reader.querySelector('[data-event-id=current-causal-user]')!==null")
    after=js("({pending:reader.querySelectorAll('.conversation-submission').length,label:reader.querySelector('.conversation-submission .conversation-byline')?.textContent,records:reader.querySelectorAll('[data-event-id=current-causal-user]').length})")
    print('causal Enter',precision,'migration',migration,first,'reopened',after)
    assert after['records']==1
    if precision=='milliseconds':assert first['pending']==0 and after['pending']==0,(first,after)
    else:
        assert first['pending']==1 and after['pending']==1,(first,after)
        assert 'record not matched' in after['label'] and 'Not recorded yet' not in after['label']
        js("OrreryConversationSource.Source.prototype.read=async()=>({mode:'snapshot',events:[oldRecord,currentCausalRecord,{...currentCausalRecord,id:'later-certain',ts:new Date(clock+1000).toISOString()}],after:'later'});conversationView.refresh()")
        wait("reader.querySelectorAll('.conversation-submission').length===0")
