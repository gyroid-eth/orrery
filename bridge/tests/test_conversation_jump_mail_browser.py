"""J1/M1 in the real cockpit; generated xterm text and provider records only."""
import json,sys,time
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_conversation_review_regressions import cockpit,stable_roster
from test_conversation_mail import native,NOTICE,ARGS


def configure(js,wait,enable,text,terminal,*,alternate=False):
    stable_roster(js);enable(count=1)
    js('conversationView.close();window.jumpFixtureText='+json.dumps(text)+';')
    js("""OrreryConversationSource.Source.prototype.read=async()=>({events:[{id:'jump-event',kind:'text',role:'assistant',text:jumpFixtureText}],after:'fixture:1',has_older:false});
      const p=panes.get('%901');p.meta.alternateOn=false;p._wheelAlternate=false;
      writePaneOutput(p,{snapshot:true,data:"""+json.dumps(terminal)+"""});""")
    wait("!hostSnapshotPending(panes.get('%901').host)")
    if alternate:js("panes.get('%901').meta.alternateOn=true;panes.get('%901')._wheelAlternate=true")
    js("conversationView.open()")
    wait("document.querySelector('.conversation-text')?.textContent===jumpFixtureText")
    js("document.querySelector('.conversation-expand').click()")
    time.sleep(.12);js('packets.length=0')


@pytest.mark.parametrize('case',['unique','absent','multiple','alternate','alternate-visible'])
def test_j1_click_searches_only_retained_same_pane_without_input(cockpit,case):
    js,wait,client,requests,enable=cockpit
    text='Generated unique terminal jump message 20261104'
    terminal='\r\n'.join(['earlier generated row']*30+[text]+['later generated row']*85)+'\r\n'
    if case=='absent':terminal=terminal.replace(text,'Different generated message')
    if case=='multiple':terminal=text+'\r\n'+terminal
    if case=='alternate':terminal='\x1b[?1049h\x1b[2J\x1b[HCurrent alternate frame only'
    if case=='alternate-visible':terminal='\x1b[?1049h\x1b[2J\x1b[H'+text
    configure(js,wait,enable,text,terminal,alternate=case.startswith('alternate'))
    before=js("panes.get('%901').term.buffer.active.viewportY")
    js("document.querySelector('.conversation-text').click()")
    if case in {'unique','alternate-visible'}:
        wait("panes.get('%901').term.getSelection().includes(jumpFixtureText)")
        assert not js("document.querySelector('.screen').classList.contains('conversation-full')")
        if case=='unique':assert js("panes.get('%901').term.buffer.active.viewportY")<before
    else:
        needle={'absent':'Not found in terminal scrollback','multiple':'Same text found in 2 places','alternate':'not kept in the terminal'}[case]
        wait("document.querySelector('.conversation-toolbar').textContent.includes("+json.dumps(needle)+")")
        assert js("panes.get('%901').term.buffer.active.viewportY")==before
        assert js("document.querySelector('.screen').classList.contains('conversation-full')")
    assert js("packets.filter(p=>['input','codex-page','resize','claim','release'].includes(p.type))")==[]


def test_j1_selection_and_double_click_do_not_jump(cockpit):
    js,wait,client,requests,enable=cockpit
    text='Generated selection stays copyable in history'
    configure(js,wait,enable,text,'\r\n'.join([text]+['fixture line']*90))
    original=js("panes.get('%901').term.buffer.active.viewportY")
    js("""{const textNode=document.querySelector('.conversation-text'),r=document.createRange();r.selectNodeContents(textNode);getSelection().removeAllRanges();getSelection().addRange(r);textNode.click();}""")
    time.sleep(.5)
    assert js("getSelection().toString()")==text
    assert js("panes.get('%901').term.buffer.active.viewportY")==original
    js("""{getSelection().removeAllRanges();document.querySelector('.conversation-text').dispatchEvent(new MouseEvent('click',{detail:1,bubbles:true}));}""")
    time.sleep(.45)
    js("document.querySelector('.conversation-text').dispatchEvent(new MouseEvent('click',{detail:2,bubbles:true}))")
    time.sleep(.5)
    assert js("panes.get('%901').term.buffer.active.viewportY")==original
    assert js("panes.get('%901').term.getSelection()")==''


@pytest.mark.parametrize('provider',['codex','claude','dsh','hermes'])
def test_m1_received_and_sent_mail_expand_recorded_body_only(cockpit,tmp_path,provider):
    js,wait,client,requests,enable=cockpit
    received=native(tmp_path,provider)[0];child=tmp_path/'out';child.mkdir()
    sent=native(child,provider,args=ARGS)[0]
    if provider=='codex':received['mail'][0]['body']+='x'*20000+'END_FULL_MAIL'
    stable_roster(js);enable(count=1)
    js('conversationView.close();window.mailFixturePage='+json.dumps([received,sent])+';')
    js("OrreryConversationSource.Source.prototype.read=async()=>({events:mailFixturePage.map((e,i)=>({...e,id:String(i)})),provider:"+json.dumps(provider)+",after:'fixture:1',has_older:false});conversationView.open()")
    wait("document.querySelectorAll('.conversation-mail').length===2")
    assert js("[...document.querySelectorAll('.conversation-mail-label')].map(e=>e.textContent)") == ['Mail · Received','Mail · Sent']
    assert js("[...document.querySelectorAll('.conversation-mail-route')].map(e=>e.title)") == ['ParentFixture → ReviewFixture','ReviewFixture → ParentFixture']
    assert js("[...document.querySelectorAll('.conversation-mail-label')].every(e=>e.title.startsWith('ORRERY Mail'))")
    assert not js("document.querySelector('.conversation-role')?.textContent==='You'")
    js("document.querySelectorAll('.conversation-mail-summary').forEach(e=>e.click())")
    assert js("[...document.querySelectorAll('.conversation-mail')].every(e=>e.open)")
    assert js("document.querySelector('.conversation-events').textContent.includes('Generated outgoing body')")
    assert js("document.querySelector('.conversation-events').textContent.includes('Generated full message')")
    if provider=='codex':assert js("document.querySelector('.conversation-events').textContent.includes('END_FULL_MAIL')")
    assert not js("document.querySelector('.conversation-events').textContent.includes('HIDDEN_')")
    assert not [path for path in requests if path.startswith('/telemetry/mail/message')]


def test_j1_keyboard_and_stale_pane_do_not_leak_input(cockpit):
    js,wait,client,requests,enable=cockpit
    text='Generated keyboard terminal jump destination'
    configure(js,wait,enable,text,'\r\n'.join([text]+['later row']*90))
    js("document.querySelector('.conversation-text').focus()")
    client.call('Input.dispatchKeyEvent',type='keyDown',key='Enter',windowsVirtualKeyCode=13)
    client.call('Input.dispatchKeyEvent',type='keyUp',key='Enter',windowsVirtualKeyCode=13)
    wait("panes.get('%901').term.getSelection().includes(jumpFixtureText)")
    assert js("packets.filter(p=>p.type==='input')")==[]
    js("panes.get('%901').term.clearSelection();panes.get('%901').session='ReplacementFixture';document.querySelector('.conversation-text').click()")
    wait("document.querySelector('.conversation-toolbar').textContent.includes('Terminal changed')")
    assert js("panes.get('%901').term.getSelection()")==''


def test_j1_real_pointer_in_split_jumps_only_owner_buffer(cockpit):
    js,wait,client,requests,enable=cockpit
    stable_roster(js);enable(count=1)
    js("""conversationView.close();currentAgents.push({name:'OtherFixture',program:'codex',history_binding:'bound'});
      createPane('OtherFixture',{paneId:'%902',windowId:'@902',width:80,height:20});
      window.splitJump='Generated split jump marker in both private buffers';
      OrreryConversationSource.Source.prototype.read=async name=>({agent:name,events:[...Array.from({length:30},(_,i)=>({id:'older-'+i,kind:'text',role:'assistant',text:'Generated reading text. '.repeat(5)})),{id:'marker',kind:'text',role:'assistant',text:splitJump}],after:'fixture:1',has_older:false});
      replaceSplitSessions(['ReviewFixture','OtherFixture']);splitVisible=true;focusSplitSession('OtherFixture');""")
    wait("document.querySelectorAll('.split-history-toggle').length===2")
    js("document.querySelectorAll('.split-history-toggle').forEach(e=>e.click())")
    wait("[...document.querySelectorAll('.split-cell')].every(cell=>cell.querySelectorAll('.conversation-event').length===31)")
    js(r"""document.querySelector('.split-cell .conversation-expand').click();
      for(const id of ['%901','%902']){const p=panes.get(id);p.meta.alternateOn=false;p._wheelAlternate=false;writePaneOutput(p,{snapshot:true,data:splitJump+'\r\n'+('Later generated row\r\n').repeat(100)})}""")
    wait("[...panes.values()].every(p=>!hostSnapshotPending(p.host))")
    time.sleep(.2)
    js("""document.querySelector('.split-cell .conversation-scroll').scrollTop=1e9;
      document.querySelectorAll('.split-cell .conversation-scroll')[1].scrollTop=120;packets.length=0;""")
    rect=js("(()=>{const r=[...document.querySelectorAll('.split-cell .conversation-text')].find(e=>e.textContent===splitJump).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
    client.call('Input.dispatchMouseEvent',type='mousePressed',x=rect['x'],y=rect['y'],button='left',clickCount=1)
    client.call('Input.dispatchMouseEvent',type='mouseReleased',x=rect['x'],y=rect['y'],button='left',clickCount=1)
    wait("panes.get('%901').term.getSelection().includes(splitJump)")
    assert js('activeSession()')=='ReviewFixture'
    assert js("panes.get('%902').term.getSelection()") == ''
    assert js("document.querySelector('.split-cell .conversation-panel').hidden")
    assert not js("document.querySelectorAll('.split-cell .conversation-panel')[1].hidden")
    assert js("document.querySelectorAll('.split-cell .conversation-scroll')[1].scrollTop")==120
    assert js("packets.filter(p=>['input','resize','claim','release'].includes(p.type))")==[]


def test_mixed_mail_tool_keeps_byline_file_chip_and_recorded_diff(cockpit):
    js,wait,client,requests,enable=cockpit
    stable_roster(js);enable(count=1)
    event=dict(id='mixed',kind='tool',role='assistant',text='functions.exec',
        mail=[dict(direction='sent',recipients=['ParentFixture'],subject='Mixed edit report',body='Generated Mail body',coverage='request')],
        references=[dict(id='A'*32,label='example.txt',kind='file')],diff='--- example.txt\n+++ example.txt\n-before\n+after')
    js('conversationView.close();window.mixedFixture='+json.dumps(event)+';')
    js("OrreryConversationSource.Source.prototype.read=async()=>({events:[mixedFixture],after:'fixture:1',has_older:false});conversationView.open()")
    wait("document.querySelector('.conversation-mail')!==null")
    assert js("document.querySelector('.conversation-tool-name').textContent")=='functions.exec'
    assert js("document.querySelectorAll('.conversation-file').length")==1
    assert js("document.querySelector('.conversation-diff-code').textContent.includes('-before\\n+after')")
    js("document.querySelector('.conversation-mail-summary').click()")
    assert js("document.querySelector('.conversation-mail').open")
    assert js("document.querySelector('.conversation-mail-text').textContent")=='Generated Mail body'
