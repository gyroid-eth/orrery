"""Selected A in the actual Reader; synthetic provider records and shared CDP."""
import json
import os
from pathlib import Path
import base64
import time

import pytest

from test_conversation_review_regressions import cockpit, stable_roster, wait_reading_layout
from test_conversation_steps import c, claude_events, native, project, segmented_records


def events(provider, complete=True, prefix='one'):
    if provider=='claude':
        records=[c('user','Check the generated layout'),c('assistant','I will inspect the generated file.'),
            c('assistant',[dict(type='tool_use',id=prefix,name='Read',input={'file_path':'/fixture/review-notes.py'})])]
        if complete:records.append(c('user',[dict(type='tool_result',tool_use_id=prefix,is_error=False)]))
        return claude_events(records)
    rows=[project(dict(type='event_msg',payload=dict(type='task_started',turn_id='turn-one',started_at=1)),0),
          dict(id='user',kind='text',role='user',text='Check the generated layout'),
          dict(id='intro',kind='text',role='assistant',text='I will inspect the generated file.')]
    if complete:rows.append(project(native('CommandExecution',ident=prefix,command=['pytest'],status='completed',exit_code=0),10))
    return rows


def prepare(cockpit, provider='claude', rows=None, theme='dark', working=True):
    js,wait,client,requests,enable=cockpit
    stable_roster(js);enable(count=1)
    js('conversationView.close();currentAgents[0]={...currentAgents[0],program:'+
       json.dumps('claude-code' if provider=='claude' else 'codex')+
       ',running:true,act_state:'+json.dumps('work' if working else 'wait')+',work_disp:"1m 00s"}')
    payload=dict(ok=True,agent='ReviewFixture',provider=provider,mode='cursor',
                 events=events(provider) if rows is None else rows,after='tail',has_older=False)
    js('window.stepsPage='+json.dumps(payload)+';OrreryConversationSource.Source.prototype.read=async()=>stepsPage;'+
       'OrreryColorTheme.setPreference('+json.dumps(theme)+');conversationView.open()')
    wait("document.querySelector('.conversation-event')!==null")
    wait_reading_layout(js)
    return js,wait,client


@pytest.mark.parametrize('provider,separator', [('claude', 'mail'), ('codex', 'assistant')])
def test_step_cards_split_in_order_on_delta_and_reload(cockpit, provider, separator):
    first, boundary, last = segmented_records(provider, separator)
    records = first + boundary + last
    rows = claude_events(records) if provider == 'claude' else [project(record, i) for i, record in enumerate(records)]
    projected_count = len(first)
    initial, separator_row, tail = rows[:projected_count], rows[projected_count], rows[projected_count+1:]
    js, wait, _ = prepare(cockpit, provider, rows=initial)
    js("""window.firstCard=document.querySelector('.conversation-steps');
      window.deltaPage={...stepsPage,events:[],after:'tail'};
      OrreryConversationSource.Source.prototype.read=async(name,{after}={})=>after?deltaPage:stepsPage;
      window.stepOrder=()=>[...firstCard.parentElement.children].filter(row=>!row.hidden).map(row=>
        row.matches('.conversation-steps')?row.querySelectorAll('.conversation-step').length:row.dataset.eventId);
    """)
    assert js('stepOrder()') == [initial[1 if provider == 'codex' else 0]['id'], 3]
    js('deltaPage={...deltaPage,events:'+json.dumps([separator_row])+',after:"separator"};conversationView.refresh()')
    wait("document.querySelectorAll('.conversation-steps').length===2")
    assert js("firstCard.querySelector('.conversation-steps-toggle').getAttribute('aria-expanded')") == 'false'
    js('deltaPage={...deltaPage,events:'+json.dumps(tail)+',after:"end"};conversationView.refresh()')
    wait("document.querySelectorAll('.conversation-step').length===5")
    expected = [initial[1 if provider == 'codex' else 0]['id'], 3, separator_row['id'], 2]
    assert js('stepOrder()') == expected
    assert js("firstCard===document.querySelector('.conversation-steps')")
    js('stepsPage={...stepsPage,events:'+json.dumps(rows)+',after:"end"};'+
       'deltaPage={...deltaPage,events:[]};conversationView.close();conversationView.open()')
    wait("document.querySelectorAll('.conversation-step').length===5")
    js("firstCard=document.querySelector('.conversation-steps')")
    assert js('stepOrder()') == expected


@pytest.mark.parametrize('theme',['light','dark'])
@pytest.mark.parametrize('provider',['claude','codex'])
def test_current_turn_has_steps_and_no_duplicate_tool_group(cockpit,theme,provider):
    js,wait,client=prepare(cockpit,provider,theme=theme)
    assert js("document.querySelectorAll('.conversation-step').length")==1
    assert js("document.querySelectorAll('.conversation-tool-group').length")==0
    assert js("document.querySelector('.conversation-steps-toggle').getAttribute('aria-expanded')")=='false'
    assert js("document.querySelector('.conversation-steps-heading').textContent")=='Working…'
    assert js("document.querySelector('.conversation-steps-count').textContent")=='1 step'
    assert js("document.querySelector('.conversation-steps-expansion').inert") is True
    assert js("document.querySelector('.conversation-activity').hidden")
    before=js("document.querySelector('.conversation-steps-time').textContent")
    wait("document.querySelector('.conversation-steps-time').textContent!=="+json.dumps(before))
    assert js("document.querySelector('.conversation-steps-time').textContent").startswith(', 1m ')


@pytest.mark.parametrize('provider',['claude','codex'])
def test_operations_share_inline_row_through_completion_and_button_reopens(cockpit,provider):
    js,wait,client=prepare(cockpit,provider,rows=events(provider,False))
    assert js("document.querySelectorAll('.conversation-step').length")==(1 if provider=='claude' else 0)
    if provider=='claude':
        assert js("document.querySelector('.conversation-step-outcome').textContent")=='Running…'
        js("window.originalStep=document.querySelector('.conversation-step');window.originalCard=originalStep.closest('.conversation-steps')")
        js("currentAgents[0].act_state=null;document.dispatchEvent(new CustomEvent('oc:agents'))")
        assert js("originalCard.querySelector('.conversation-steps-count').textContent")=='1 step'
        js("currentAgents[0].act_state='wait';document.dispatchEvent(new CustomEvent('oc:agents'))")
        assert js("originalCard.querySelector('.conversation-steps-count').textContent")=='1 tool call'
        assert js("document.querySelectorAll('.conversation-tool-group').length")==0
        js("currentAgents[0].act_state='work';document.dispatchEvent(new CustomEvent('oc:agents'))")
    assert js("document.querySelectorAll('.conversation-tool-group').length")==0
    js('stepsPage.events='+json.dumps(events(provider))+';conversationView.refresh()')
    wait("document.querySelectorAll('.conversation-step-icon.done').length===1")
    if provider=='claude':
        assert js("originalStep===document.querySelector('.conversation-step') && originalCard.isConnected")
        assert js("document.querySelector('.conversation-steps-count').textContent")=='1 step'
        assert js("document.querySelectorAll('.conversation-tool-group').length")==0
    js("document.querySelector('.conversation-steps-toggle').click()")
    assert js("document.querySelector('.conversation-steps-toggle').getAttribute('aria-expanded')")=='true'
    if provider=='codex':
        end=project(dict(type='event_msg',payload=dict(type='task_complete',turn_id='turn-one',duration_ms=125000,started_at=1,completed_at=126)),20)
        js('stepsPage.events.push('+json.dumps(end)+');conversationView.refresh()')
    else:js("currentAgents[0].act_state='wait';document.dispatchEvent(new CustomEvent('oc:agents'))")
    wait("document.querySelector('.conversation-steps-toggle').getAttribute('aria-expanded')==='false'")
    assert js("document.querySelector('.conversation-steps-heading').hidden") is True
    if provider=='codex':assert js("document.querySelector('.conversation-steps-toggle').ariaLabel")=='1 tool call, 2m 05s'
    js("document.querySelector('.conversation-steps-toggle').click()")
    assert js("document.querySelector('.conversation-steps-toggle').getAttribute('aria-expanded')")=='true'
    assert js("document.querySelector('.conversation-steps-expansion').inert") is False
    js("document.querySelector('.conversation-steps-toggle').focus()")
    for kind in ['keyDown','keyUp']:client.call('Input.dispatchKeyEvent',type=kind,key='Enter',code='Enter',windowsVirtualKeyCode=13,**({'text':'\r'} if kind=='keyDown' else {}))
    assert js("document.querySelector('.conversation-steps-toggle').getAttribute('aria-expanded')")=='false'
    assert js("packets.filter(p=>p.type==='input')")==[]


def test_historical_turn_starts_folded_and_failure_is_not_inferred_from_prose(cockpit):
    rows=events('codex')+[project(native('ImageView',ident='image',path='/fixture/a.png'),11),
        project(native('McpToolCall',ident='mail',tool='send_message',status='completed',result={'isError':True}),12)]
    rows.append(project(dict(type='event_msg',payload=dict(type='task_complete',turn_id='turn-one',duration_ms=125000)),15))
    js,wait,client=prepare(cockpit,'codex',rows=rows,working=False)
    assert js("document.querySelector('.conversation-steps-toggle').getAttribute('aria-expanded')")=='false'
    js("document.querySelector('.conversation-steps-toggle').click()")
    assert js("document.querySelectorAll('.conversation-step-icon.failed').length")==1
    assert js("document.querySelectorAll('.conversation-step-icon.observed').length")==1
    assert js("[...document.querySelectorAll('.conversation-step-outcome')].map(n=>n.textContent)")==['','Observed','Failed']


def test_append_keeps_existing_row_selection_and_earlier_pair_fills_without_duplicate(cockpit):
    rows=events('claude')
    js,wait,client=prepare(cockpit,'claude',rows=rows)
    js("""document.querySelector('.conversation-steps-toggle').click();
      window.firstStep=document.querySelector('.conversation-step');
      window.selectedText=firstStep.querySelector('.conversation-step-target').firstChild;
      const range=document.createRange();range.selectNodeContents(selectedText);
      getSelection().removeAllRanges();getSelection().addRange(range);""")
    more=claude_events([c('assistant',[dict(type='tool_use',id='two',name='Bash',input={'command':'pytest'})]),
        c('user',[dict(type='tool_result',tool_use_id='two')])])
    for i,event in enumerate(more):event['id']='more-'+str(i)
    js('stepsPage.events.push(...'+json.dumps(more)+');conversationView.refresh()')
    wait("document.querySelectorAll('.conversation-step').length===2")
    assert js("document.querySelector('.conversation-step')===firstStep")
    assert js("getSelection().toString()")=='review-notes.py'
    js('conversationView.refresh()')
    time.sleep(.12)
    assert js("document.querySelectorAll('.conversation-step').length")==2


def test_close_clears_steps_and_reduced_motion_opens_without_animation(cockpit):
    js,wait,client=prepare(cockpit)
    js("conversationView.close()")
    assert js("document.querySelectorAll('.conversation-steps').length")==0
    js("conversationView.open()")
    wait("document.querySelector('.conversation-steps')!==null")
    client.call('Emulation.setEmulatedMedia',features=[{'name':'prefers-reduced-motion','value':'reduce'}])
    assert js("document.querySelector('.conversation-steps-heading').getAnimations().length")==0
    assert js("""(()=>{document.querySelector('.conversation-steps-toggle').click();
      const body=document.querySelector('.conversation-steps-expansion');
      return body.getAnimations().length===0&&body.getBoundingClientRect().height>0;})()""")
    assert js("document.querySelectorAll('.conversation-step').length")==1
    assert js("packets.filter(p=>p.type==='input')")==[]


@pytest.mark.parametrize('unknown', [False, True], ids=['missing-completion', 'unknown-completion'])
def test_codex_unmatched_tools_remain_in_existing_group(cockpit, unknown):
    rows=events('codex',False)
    rows.append(project(dict(type='response_item',payload=dict(type='function_call',name='old_server_tool',
                      call_id='old-call',arguments='{}')),21))
    if unknown:
        assert project(native('Extension',kind='unknown'),22) is None
    rows.append(project(dict(type='event_msg',payload=dict(type='task_complete',turn_id='turn-one')),23))
    js,wait,client=prepare(cockpit,'codex',rows=rows,working=False)
    assert js("document.querySelectorAll('.conversation-steps:not([hidden])').length")==0
    assert js("document.querySelectorAll('.conversation-step').length")==0
    assert js("document.querySelectorAll('.conversation-tool-group').length")==1
    js("document.querySelector('.conversation-tool-group').click()")
    assert js("document.querySelector('[data-event-id=\"21\"]').hidden") is False
    assert js("document.querySelector('[data-event-id=\"21\"] .conversation-tool-name').textContent")=='old_server_tool'
    folder=os.environ.get('ORRERY_STEPS_SCREENSHOTS')
    if folder and not unknown:
        wait_reading_layout(js)
        Path(folder,'codex-unmatched-tool.png').write_bytes(base64.b64decode(client.call('Page.captureScreenshot',format='png')['data']))


def test_hidden_reader_pauses_working_shimmer_and_elapsed_timer(cockpit):
    rows=events('codex')+[project(native('ImageView',ident='image',path='/fixture/a.png'),11)]
    js,wait,client=prepare(cockpit,'codex',rows=rows)
    assert js("getComputedStyle(document.querySelector('.conversation-steps-heading')).animationName")=='conversation-working-shimmer'
    js("""Object.defineProperty(document,'hidden',{configurable:true,value:true});
      document.dispatchEvent(new Event('visibilitychange'));""")
    assert js("document.querySelector('.conversation-steps').classList.contains('is-paused')")
    assert js("getComputedStyle(document.querySelector('.conversation-steps-heading')).animationPlayState")=='paused'
    before=js("document.querySelector('.conversation-steps-time').textContent")
    time.sleep(1.1)
    assert js("document.querySelector('.conversation-steps-time').textContent")==before
    js("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))")
    assert js("getComputedStyle(document.querySelector('.conversation-steps-heading')).animationPlayState")=='running'


def test_step_expansion_uses_soft_height_spring_and_reverses_from_current_height(cockpit):
    js,wait,_=prepare(cockpit,working=False)
    sample=js("""(()=>{
      const toggle=document.querySelector('.conversation-steps-toggle');
      const body=document.querySelector('.conversation-steps-expansion');
      const curve=OrreryConversationMotion.spring(260,24);
      toggle.click();
      const opening=body.getAnimations()[0];
      const values=opening.effect.getKeyframes().map(frame=>parseFloat(frame.height));
      const target=values.at(-1);
      opening.pause();opening.currentTime=120;
      const current=body.getBoundingClientRect().height;
      toggle.click();
      const closing=body.getAnimations()[0];
      const reversed=parseFloat(closing.effect.getKeyframes()[0].height);
      return {expected:values.length===curve.length&&values.every((h,i)=>Math.abs(h-target*curve[i])<.01),
        target,current,reversed,expanded:toggle.getAttribute('aria-expanded'),inert:body.inert};
    })()""")
    assert sample['expected']
    assert 0 < sample['current'] < sample['target']
    assert abs(sample['current']-sample['reversed']) < .05
    assert sample['expanded']=='false' and sample['inert']
    wait("document.querySelector('.conversation-steps-expansion').getBoundingClientRect().height===0")


def test_demo_keeps_native_tool_label_and_masks_only_targets(cockpit):
    js,wait,client,requests,enable=cockpit
    client.call('Page.addScriptToEvaluateOnNewDocument',source="""
      window.OrreryDemoBootstrap={on:true,identity:{users:['mira'],hosts:['mira-node']},words:['Read','review-notes']};
    """)
    client.call('Page.reload')
    wait("typeof conversationView!=='undefined'&&typeof createPane==='function'&&document.documentElement.dataset.demo==='on'")
    js,wait,client=prepare(cockpit)
    wait("document.querySelector('.conversation-step-target').textContent.includes('*')")
    assert js("document.querySelector('.conversation-step-tool').textContent")=='Read'
    assert 'review-notes' not in js("document.querySelector('.conversation-step-target').textContent")
    assert js("OrreryDemo.mask('Read review-notes')")=='**** ************'


def test_step_replacement_keeps_existing_file_and_recorded_mail_cards(cockpit):
    rows=events('claude')
    call=next(e for e in rows if e.get('step',{}).get('phase')=='call')
    call['references']=[dict(id='x'*32,label='generated-report.md',kind='text')]
    call['mail']=[dict(direction='sent',recipients=['PeerFixture'],subject='Generated report',
                       body='The generated file is ready.',coverage='complete')]
    js,wait,client=prepare(cockpit,rows=rows)
    assert js("document.querySelectorAll('.conversation-tool-group').length")==0
    assert js("document.querySelector('.conversation-files').closest('.conversation-event').hidden") is False
    assert js("document.querySelector('.conversation-mail').getBoundingClientRect().height>0")
    assert js("getComputedStyle(document.querySelector('.conversation-step-record>.conversation-byline')).display")=='none'
    js("document.querySelector('.conversation-steps-toggle').click()")
    assert js("document.querySelector('.conversation-mail').getBoundingClientRect().height>0")


@pytest.mark.parametrize('mode',['snapshot','fresh_tail'])
def test_non_legacy_modes_do_not_enable_native_steps(cockpit,mode):
    js,wait,client,requests,enable=cockpit
    stable_roster(js);enable(count=1)
    js('conversationView.close();currentAgents[0].act_state="wait";OrreryConversationSource.Source.prototype.read=async()=>('+
       json.dumps(dict(ok=True,mode=mode,provider='claude',events=events('claude'),after='tail'))+
       ');conversationView.open()')
    wait("document.querySelectorAll('.conversation-event').length>1")
    assert js("document.querySelectorAll('.conversation-steps').length")==0


@pytest.mark.parametrize('provider,mode', [
    ('codex','cursor'), ('dsh','cursor'), ('hermes','snapshot'), ('antigravity','cursor')])
def test_generic_active_tool_fold_has_one_owner(cockpit,provider,mode):
    from conversation_readers import normalize
    now = '2026-11-24T01:00:00Z'
    if provider == 'dsh':
        _, call = normalize(dict(type='tool/call', data=dict(name='terminal')), provider, 'fixture')[0]
        _, result = normalize(dict(type='tool/result', data=dict(message={})), provider, 'fixture')[0]
    elif provider == 'hermes':
        _, call = normalize(dict(role='assistant', tool_calls=[dict(function=dict(name='terminal'))]), provider, 'fixture')[0]
        _, result = normalize(dict(role='tool', tool_name='terminal'), provider, 'fixture')[0]
    elif provider == 'codex':
        call = project(dict(type='response_item', payload=dict(
            type='function_call', name='fixture_tool', call_id='one', arguments='{}')), 1)
        result = None
    else:
        # Antigravity emits these generic rows from its DONE planner and result records.
        call, result = [dict(kind=kind, role='assistant', text=name, ts=now) for kind,name in
                        [('tool','run_command'),('tool_result','Tool result')]]
    call['id']='request'
    if result:
        result['id']='result'
    history = [dict(id='old',kind='tool',role='assistant',text='older tool'),
               dict(id='prompt',kind='text',role='user',text='Run the fixture')]
    js,wait,_=prepare(cockpit,provider,rows=history)
    js('conversationView.close();currentAgents[0].program='+json.dumps(provider)+';stepsPage.mode='+json.dumps(mode)+
       ';conversationView.open()')
    wait("Boolean(document.querySelector('[data-event-id=prompt]'))")
    js('stepsPage.events.push('+json.dumps(call)+');conversationView.refresh()')
    wait("document.querySelector('.conversation-steps:not([hidden]) .conversation-steps-count')?.textContent==='1 step'")
    assert js("document.querySelectorAll('.conversation-tool-group').length")==1  # Earlier history.
    js("window.activeToolCard=document.querySelector('.conversation-steps:not([hidden])');")
    if result:
        js('stepsPage.events.push('+json.dumps(result)+');conversationView.refresh()')
        wait("Boolean(document.querySelector('[data-event-id=result]'))")
        assert js("activeToolCard===document.querySelector('.conversation-steps:not([hidden])')")
        assert js("activeToolCard.querySelector('.conversation-steps-count').textContent")=='1 step'
        assert js("document.querySelectorAll('.conversation-tool-group').length")==1
    js("currentAgents[0].act_state='wait';document.dispatchEvent(new CustomEvent('oc:agents'))")
    wait("document.querySelectorAll('.conversation-tool-group').length===2")
    assert js("!activeToolCard.isConnected")
    assert js("Array.from(document.querySelectorAll('.conversation-tool-count')).map(n=>n.textContent)")==['1 tool call','1 tool call']


@pytest.mark.parametrize('theme',['light','dark'])
def test_stopped_unpaired_claude_call_survives_prompt_then_late_result(cockpit,theme,tmp_path):
    pending=events('claude',False)
    call=next(e for e in pending if e.get('step',{}).get('phase')=='call')
    js,wait,client=prepare(cockpit,'claude',rows=pending,theme=theme,working=False)
    js("currentAgents[0].running=false;document.dispatchEvent(new CustomEvent('oc:agents'))")
    wait("document.querySelector('.conversation-tool-group')!==null")
    assert js("document.querySelectorAll('.conversation-step').length")==0
    assert js("document.querySelectorAll('.conversation-steps:not([hidden])').length")==0
    js("document.querySelector('.conversation-tool-group').click();window.pendingCall=document.querySelector('[data-event-id='+CSS.escape("+json.dumps(call['id'])+")+']')")
    assert js('pendingCall.hidden') is False
    assert js("pendingCall.querySelector('.conversation-tool-name').textContent")=='Read'
    folder=Path(os.environ.get('ORRERY_STEPS_UNPAIRED_CAPTURE_DIR',str(tmp_path)))
    folder.mkdir(parents=True,exist_ok=True)
    def capture(stage):
        wait_reading_layout(js)
        js('new Promise(r=>setTimeout(r,300))')
        data=client.call('Page.captureScreenshot',format='png',captureBeyondViewport=False)['data']
        (folder/('pc-'+theme+'-'+stage+'.png')).write_bytes(base64.b64decode(data))
    capture('call-only')
    later=dict(id='later-prompt',kind='text',role='user',text='Now inspect another file.',step_boundary=True)
    js('stepsPage.events.push('+json.dumps(later)+');conversationView.refresh()')
    wait("document.querySelector('[data-event-id=later-prompt]')!==null")
    assert js('pendingCall.hidden') is False
    assert js("document.querySelectorAll('.conversation-tool-group').length")==1
    assert js("document.querySelectorAll('.conversation-step').length")==0
    capture('later-prompt')
    result=events('claude')[-1]
    js('stepsPage.events.push('+json.dumps(result)+');conversationView.refresh()')
    wait("document.querySelectorAll('.conversation-step').length===1")
    assert js('pendingCall.hidden') is True
    assert js("document.querySelectorAll('.conversation-tool-group').length")==0
    assert js("document.querySelectorAll('.conversation-step-icon.done').length")==1
    js("document.querySelector('.conversation-steps:not([hidden]) .conversation-steps-toggle').click()")
    capture('matched')
    assert js("packets.filter(p=>p.type==='input')")==[]
