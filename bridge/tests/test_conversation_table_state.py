"""Shape limits, wide Unicode cells, and appended tables during active reading."""
import base64,json,sys,time,os
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'bridge/tests'))
from test_conversation_markdown import cockpit,prepare
OUT=Path(os.environ['ORRERY_TABLE_CAPTURE_DIR']) if os.environ.get('ORRERY_TABLE_CAPTURE_DIR') else None

def table(cols,rows,wide=False):
    head='|'+'|'.join(('全角の列名ＡＢＣ日本語'+str(i)) if wide else '列' for i in range(cols))+'|\n'
    rule='|'+'|'.join(['---']*cols)+'|\n'
    body=('|'+'|'.join(['計測１２３４ＡＢＣ長い結果' if wide else '測']*cols)+'|\n')*rows
    return head+rule+body

def capture(client,name):
    if OUT is None:return
    time.sleep(.15)
    shot=client.call('Page.captureScreenshot',format='png')
    (OUT/name).write_bytes(base64.b64decode(shot['data']))

def test_append_wide_unicode_tables_preserves_existing_scroll_and_follow(cockpit):
    tab=table(16,4,wide=True)
    text=('上の段落 日本語とＡＢＣ\n'*40)+'\n'+tab+'\n'+('下の段落\n'*50)
    js,wait,client=prepare(cockpit,text)
    js("{const b=document.querySelector('.conversation-expand');if(b.getAttribute('aria-pressed')!=='true')b.click()}" )
    js("""window.tableStage=0;window.keptArticle=document.querySelector('[data-event-id=table]');window.keptTable=keptArticle.querySelector('.conversation-table-scroll');window.readerScroll=document.querySelector('.conversation-scroll');
      window.appendMarkdown="""+json.dumps(tab)+""";
      OrreryConversationSource.Source.prototype.read=async()=>({events:Array.from({length:tableStage},(_,i)=>({id:'appended-'+i,role:'assistant',kind:'text',text:appendMarkdown})),after:'append-'+tableStage});
      keptTable.scrollLeft=180;readerScroll.dispatchEvent(new WheelEvent('wheel'));readerScroll.scrollTop+=keptTable.getBoundingClientRect().top-readerScroll.getBoundingClientRect().top-20;
      window.keptTop=readerScroll.scrollTop;window.keptX=keptTable.scrollLeft;packets.length=0;
    """)
    time.sleep(.15)
    for stage in [1,2]:
        js('tableStage='+str(stage)+';conversationView.refresh()')
        wait("document.querySelector('[data-event-id=appended-"+str(stage-1)+"]')!==null")
        assert js('keptTable.isConnected&&keptTable===keptArticle.querySelector(".conversation-table-scroll")')
        assert js('keptTable.scrollLeft')==js('keptX')
        assert abs(js('readerScroll.scrollTop')-js('keptTop'))<2
    js("document.querySelector('.conversation-latest').click();tableStage=3;conversationView.refresh()")
    wait("document.querySelector('[data-event-id=appended-2]')!==null")
    assert js('readerScroll.scrollHeight-readerScroll.clientHeight-readerScroll.scrollTop<45')
    js('conversationView.refresh()');time.sleep(.1)
    assert js("document.querySelectorAll('.conversation-table').length")==4
    # Rehome the existing reader into a narrow split, then use its local scroll.
    js("currentAgents.push({name:'OtherFixture',program:'codex',history_binding:'bound'});createPane('OtherFixture',{paneId:'%902',windowId:'@902',width:80,height:20});replaceSplitSessions(['ReviewFixture','OtherFixture']);splitVisible=true;focusSplitSession('ReviewFixture')")
    client.call('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=False)
    time.sleep(.15)
    print('rehome',js('({connected:keptTable.isConnected,before:keptX,after:keptTable.scrollLeft,same:keptTable===keptArticle.querySelector(".conversation-table-scroll")})'))
    assert js('keptTable.isConnected&&keptTable.scrollLeft===keptX')
    js('readerScroll.scrollTop+=keptTable.getBoundingClientRect().top-readerScroll.getBoundingClientRect().top-20;keptTable.focus()')
    before=js('keptTable.scrollLeft')
    client.call('Input.dispatchKeyEvent',type='keyDown',key='ArrowRight',windowsVirtualKeyCode=39)
    client.call('Input.dispatchKeyEvent',type='keyUp',key='ArrowRight',windowsVirtualKeyCode=39)
    time.sleep(.2)
    assert js('keptTable.scrollLeft')>before
    state=js('({readerClient:readerScroll.clientWidth,readerWidth:readerScroll.scrollWidth,tableClient:keptTable.clientWidth,tableWidth:keptTable.scrollWidth})')
    print('appended split phone',state)
    assert state['readerWidth']<=state['readerClient']+1,state
    assert state['tableWidth']>state['tableClient'],state
    assert js("packets.filter(p=>['input','codex-page'].includes(p.type))")==[]
    capture(client,'appended-split-phone.png')

@pytest.mark.parametrize('mode',['snapshot','fresh_tail'])
def test_unchanged_snapshot_preserves_table_horizontal_position(cockpit,mode):
    js,wait,client=prepare(cockpit,table(16,4,wide=True),provider='hermes')
    client.call('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=False)
    time.sleep(.15)
    js("""window.snapshotArticle=document.querySelector('[data-event-id=table]');window.snapshotTable=snapshotArticle.querySelector('.conversation-table-scroll');snapshotTable.scrollLeft=220;window.snapshotX=snapshotTable.scrollLeft;
      window.snapshotReads=0;OrreryConversationSource.Source.prototype.read=async()=>{snapshotReads++;return {provider:'hermes',mode:"""+json.dumps(mode)+""",events:[{id:'table',kind:'text',role:'assistant',text:originalMessage}],after:'same'}};
    """)
    capture(client,mode+'-before.png')
    if mode!='snapshot':js('conversationView.refresh()')
    wait('snapshotReads===1');time.sleep(.15)
    observed=js("({before:snapshotX,after:snapshotTable.scrollLeft,sameArticle:snapshotArticle===document.querySelector('[data-event-id=table]'),sameTable:snapshotTable===document.querySelector('.conversation-table-scroll')})")
    print('unchanged',mode,observed)
    capture(client,mode+'-after.png')
    assert observed['sameArticle'] and observed['sameTable']
    assert observed['after']==observed['before'],observed

@pytest.mark.parametrize('fence',['```text | example','~~~text | example','# Heading | example','> quoted | text','- list | item','1. list | item'])
def test_table_ends_at_next_block_before_pipe_text(cockpit,fence):
    valid='| A | B |\n|---|---|\n|left|right|\n'
    following=fence+'\n|inside|code|\n|---|---|\n|literal|pipe|\n'+('```' if fence.startswith('`') else '~~~' if fence.startswith('~') else '')
    js,wait,client=prepare(cockpit,valid+following)
    rows=js("[...document.querySelectorAll('.conversation-text table tr')].map(r=>[...r.children].map(c=>c.textContent))")
    if fence.startswith(('`','~')):assert rows==[['A','B'],['left','right']]
    else:assert rows[:2]==[['A','B'],['left','right']] and not any(r[0]==fence.split('|')[0].strip() for r in rows)
    js("window.copied=null;Object.defineProperty(navigator,'clipboard',{value:{writeText:async t=>copied=t},configurable:true});document.querySelector('.conversation-table-copy').click()")
    wait('copied!==null');assert js('copied')==valid
