import sys,json,time,os
import pytest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'bridge/tests'),str(ROOT)]
from test_conversation_review_regressions import cockpit
from test_conversation_jump_mail_browser import configure

@pytest.mark.skipif(not os.environ.get('ORRERY_CDP_URL'),reason='existing CDP required')
def test_duplicate_outside_scan_budget_must_not_jump(cockpit):
    js,wait,client,requests,enable=cockpit
    marker='DUPLICATED_JUMP_MESSAGE_20261104'
    configure(js,wait,enable,marker,'bootstrap')
    js("{const p=panes.get('%901');p.term.resize(520,20);p.term.reset();}")
    data='\r\n'.join(marker if i in (0,5500) else 'x'*500 for i in range(6000))+'\r\n'
    js("writePaneOutput(panes.get('%901'),{snapshot:true,data:"+json.dumps(data)+"});true")
    wait("!hostSnapshotPending(panes.get('%901').host)")
    evidence=js("""(()=>{const p=panes.get('%901'),b=p.term.buffer.active;let actual=0,chars=0;for(let i=0;i<b.length;i++){const s=b.getLine(i)?.translateToString(true)||'';if(s===jumpFixtureText)actual++;chars+=s.length;}return {rows:b.length,cols:p.term.cols,actualMatches:actual,chars,before:b.viewportY,matcher:OrreryConversationTerminal.find(b,jumpFixtureText)}})()""")
    assert evidence['actualMatches']==2,evidence
    js("document.querySelector('.conversation-text').click()")
    time.sleep(.8)
    evidence.update(js("({after:panes.get('%901').term.buffer.active.viewportY,selection:panes.get('%901').term.getSelection(),packets:packets.filter(p=>['input','resize','claim','release','codex-page'].includes(p.type)),full:document.querySelector('.screen').classList.contains('conversation-full')})"))
    print(evidence)
    assert evidence['after']==evidence['before'] and not evidence['selection'],evidence
