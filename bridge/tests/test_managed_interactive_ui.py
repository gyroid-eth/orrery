"""I3: native pane interaction, optional assignment, and I5 effort provenance.

Only synthetic catalogs/statuses and an existing CDP browser; no real child/Mail.
"""
import json

import pytest

from test_cockpit_tour import tour_browser  # noqa: F401
from test_spawn_model_first import node


@pytest.mark.parametrize('provider,harness', [('strata','dsh'),('deepseek','dsh'),('strata','hermes'),('deepseek','hermes')])
def test_conversation_has_no_parent_task_checks_or_effort_requirement(provider,harness):
    result=node('''
      const base={provider:PROVIDER,harness:HARNESS,model:'fixture-model',parent:null,task:'',dir:'/source',name:'Ignored',headless:true};
      const conversation=picker.managedPayload(base,'id',[],[]);
      const assignment=picker.managedPayload({...base,task:'Write a result'},'id',['result.txt'],[{path:'result.txt',contains:'done'}]);
      const child=picker.managedPayload({...base,parent:'RealParent',task:'Write a result'},'id',['result.txt'],[{path:'result.txt',contains:'done'}]);
      console.log(JSON.stringify({conversation,assignment,child,error:picker.managedError(conversation)}));
    '''.replace('PROVIDER',json.dumps(provider)).replace('HARNESS',json.dumps(harness)))
    conv=result['conversation']
    assert conv['standalone'] is True and conv['parent'] is None
    assert conv['task_mode']=='conversation' and conv['report_policy']=='pane'
    assert result['error']==''
    assert not {'effort','allowed_paths','expected','name','headless','worktree_base'} & conv.keys()
    assert result['assignment']['report_policy']=='pane'
    assert result['child']['report_policy']=='mail' and result['child']['standalone'] is False


def test_blank_conversation_and_explicit_assignment_use_the_actual_form(tour_browser):
    _, evaluate=tour_browser
    result=evaluate('''(async()=>{
      const original=window.fetch,posts=[];
      window.fetch=async(url,options)=>{
        if(url==='/telemetry/spawn'){
          const p=JSON.parse(options.body);posts.push(p);
          return {ok:true,status:202,json:async()=>({ok:true,attempt_id:p.attempt_id,pending:true,phase:'queued'})};
        }
        if(String(url).startsWith('/telemetry/spawn-status?'))return {ok:false,json:async()=>({error_code:'attempt_not_found'})};
        return original(url,options);
      };
      try{
        spawnCatalog={providers:[{id:'strata',managed:true,locality:'local',models:[{id:'Qwen',harnesses:[{id:'dsh',available:true,efforts:null,effort_source:'unknown'}]}]}],naming:{},dirs:[]};
        currentAgents=[];selFamily=null;selProvider=null;selModel=null;selHarness=null;renderProviderTabs();populateSpawnParents();
        spawnDirPath='/source';spawnTask.value='';spawnAssignment.checked=false;spawnAssignment.dispatchEvent(new Event('change'));
        const optional={required:spawnTask.required,checksHidden:document.getElementById('spawnAssignmentChecks').hidden,advanced:spawnAdvanced.open};
        await submitSpawn(new Event('submit',{cancelable:true}));
        spawnAssignment.checked=true;spawnAssignment.dispatchEvent(new Event('change'));spawnTask.value='Write result';
        spawnAllowedPaths.value='result.txt';spawnExpectedPath.value='result.txt';spawnExpectedKind.value='contains';spawnExpectedValue.value='done';
        const required=spawnTask.required;await submitSpawn(new Event('submit',{cancelable:true}));
        spawnAllowedPaths.value='';spawnExpectedPath.value='';spawnExpectedValue.value='';
        await submitSpawn(new Event('submit',{cancelable:true}));
        return {posts,optional,required};
      }finally{window.fetch=original;}
    })()''')
    assert len(result['posts'])==3
    assert result['optional']==dict(required=False,checksHidden=True,advanced=False)
    assert result['required'] is True
    assert result['posts'][0]['task_mode']=='conversation' and result['posts'][0]['task']==''
    assert 'expected' not in result['posts'][0] and 'effort' not in result['posts'][0]
    assert result['posts'][1]['expected']==[dict(path='result.txt',contains='done')]
    assert result['posts'][1]['report_policy']=='pane'
    assert result['posts'][2]['task_mode']=='assignment'
    assert result['posts'][2]['expected']==[] and result['posts'][2]['allowed_paths']==[]


def test_effort_comes_from_selected_harness_and_unknown_never_falls_back(tour_browser):
    _, evaluate=tour_browser
    result=evaluate('''(()=>{
      spawnCatalog={providers:[{id:'strata',managed:true,locality:'local',efforts:['medium'],effort_default:'medium',
        models:[{id:'Qwen',harnesses:[{id:'dsh',available:true,default:true,efforts:['off','high'],default_effort:'high',effort_source:'harness'},
          {id:'hermes',available:true,efforts:null,default_effort:null,effort_source:'unknown'}]}]}],naming:{},dirs:[]};
      selFamily=null;selProvider=null;selModel=null;selHarness=null;selEffort=null;renderProviderTabs();
      const initial={cap:effortsForModel(providerById(selProvider),selModel),payload:spawnPayloadFromForm(),text:effortChoices.textContent};
      const range=effortChoices.querySelector('input');range.value=1;range.dispatchEvent(new Event('input'));
      const explicit=spawnPayloadFromForm();spawnHarnesses.querySelector('[data-harness="hermes"]').click();
      const unknown={payload:spawnPayloadFromForm(),text:effortChoices.textContent,controls:effortChoices.querySelectorAll('input').length};
      spawnHarnesses.querySelector('[data-harness="dsh"]').click();
      const reset=spawnPayloadFromForm();
      return {initial,explicit,unknown,reset};
    })()''')
    assert result['initial']['cap']==dict(efforts=['off','high'],fallback='high',source='harness')
    assert 'effort' not in result['initial']['payload'] and 'Reported default: high' in result['initial']['text']
    assert result['explicit']['effort']=='high'
    assert 'effort' not in result['unknown']['payload'] and result['unknown']['controls']==0
    assert 'unknown' in result['unknown']['text'] and 'effort' not in result['reset']


def test_two_turns_and_task_report_keep_the_same_pane_and_native_composer(tour_browser):
    _, evaluate=tour_browser
    result=evaluate('''(async()=>{
      const original=window.fetch,originalSend=send,id='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',messages=[];
      const status={ok:true,attempt_id:id,name:'InteractiveChild',state:'ready',phase:'running',finished:false,running:true,
        activity:'idle',task_mode:'conversation',task_success:null,task_evaluation:'not_applicable',cleanup_success:null,
        latest_turn:{id:'turn-2',completed:true,at:null},capabilities:{interactive:true,followup_via_pane:true,followup_via_mail:false},worktree:'/private/work/child'};
      window.fetch=async(url,options)=>String(url).startsWith('/telemetry/spawn-status?')?{ok:true,json:async()=>({...status})}:original(url,options);
      send=msg=>{messages.push(msg);return true;};
      try{
        createPane('InteractiveChild',{paneId:'%interactive',windowName:'dsh',currentCommand:'node',active:true});setActive('%interactive');
        const pane=panes.get('%interactive'),input=promptInput;
        managedAttempts.set(id,{attempt_id:id,name:'InteractiveChild',provider:'strata',harness:'dsh',state:'pending',source:'/source'});
        await refreshManagedSpawn(id);const conversation=managedPaneStatus.textContent;
        promptInput.value='A follow-up message';sendPrompt();await new Promise(r=>setTimeout(r,300));
        Object.assign(status,{task_mode:'assignment',task_evaluation:'reported',task_success:true,report_policy:'mail'});
        const keepPolling=await refreshManagedSpawn(id),reported=managedPaneStatus.textContent;
        const dismiss=[...document.querySelectorAll('#spawnLaunchRows button')].some(b=>b.textContent==='Dismiss');
        status.task_evaluation='failed';status.task_success=false;await refreshManagedSpawn(id);const failedTask=managedPaneStatus.textContent;
        const same=pane===panes.get('%interactive')&&input===promptInput;
        createPane('NativeClaude',{paneId:'%native',windowName:'claude',currentCommand:'claude',active:true});setActive('%native');
        const hiddenForNative=managedPaneStatus.hidden;setActive('%interactive');
        Object.assign(status,{state:'failed',finished:true,activity:'exited',cleanup_success:false});await refreshManagedSpawn(id);
        return {conversation,reported,failedTask,same,dismiss,keepPolling,hiddenForNative,messages:messages.filter(m=>m.type==='input'),
          failedCleanup:managedPaneStatus.textContent,record:managedAttempts.get(id)};
      }finally{window.fetch=original;send=originalSend;}
    })()''')
    assert 'Idle' in result['conversation'] and 'Turn turn-2 complete' in result['conversation']
    assert 'Task:' not in result['conversation'] and 'Cleanup: complete' not in result['conversation']
    assert 'Task: reported' in result['reported'] and 'Task: failed' in result['failedTask']
    assert result['same'] and result['keepPolling'] and not result['dismiss'] and result['hiddenForNative']
    assert len(result['messages'])==2 and all(m['paneId']=='%interactive' for m in result['messages'])
    assert 'A follow-up message' in result['messages'][0]['data'] and result['messages'][1]['data']=='\r'
    assert 'Cleanup: failed' in result['failedCleanup']
    assert result['record']['worktree']=='/private/work/child'


def test_unavailable_status_keeps_the_last_evidence_but_displays_unknown(tour_browser):
    _, evaluate=tour_browser
    result=evaluate('''(async()=>{
      const original=window.fetch,id='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeef';
      createPane('StatusChild',{paneId:'%status',windowName:'dsh',currentCommand:'node',active:true});setActive('%status');
      managedAttempts.set(id,{attempt_id:id,name:'StatusChild',state:'ready',activity:'idle',task_mode:'conversation',latest_turn:{id:'2',completed:true},finished:false});
      window.fetch=async(url,options)=>String(url).startsWith('/telemetry/spawn-status?')?Promise.reject(Error('Status service unavailable')):original(url,options);
      try{
        await refreshManagedSpawn(id);const record={...managedAttempts.get(id)},text=managedPaneStatus.textContent;
        closePane('%status');return {record,text,hidden:managedPaneStatus.hidden};
      }finally{window.fetch=original;}
    })()''')
    assert result['record']['state']=='ready' and result['record']['latest_turn']['id']=='2'
    assert result['record']['notice']=='Status service unavailable'
    assert result['text'].startswith('Unknown') and result['hidden']


def test_task_mode_gate_is_catalog_driven_and_keeps_hermes_assignment_available(tour_browser):
    _, evaluate=tour_browser
    result=evaluate('''(async()=>{
      const original=window.fetch,posts=[];
      window.fetch=async(url,options)=>{
        if(url==='/telemetry/spawn'){
          const p=JSON.parse(options.body);posts.push(p);
          return {ok:true,status:202,json:async()=>({ok:true,attempt_id:p.attempt_id,pending:true})};
        }
        if(String(url).startsWith('/telemetry/spawn-status?'))return {ok:false,json:async()=>({error_code:'attempt_not_found'})};
        return original(url,options);
      };
      try{
        const both={conversation:{available:true,requires_parent:false,requires_scope:false,requires_expected:false,report_policies:['pane','mail']},assignment:{available:true,requires_parent:false,requires_scope:false,requires_expected:false,report_policies:['pane','mail']}};
        const legacy={conversation:{available:false,reason:'interactive_not_ready',requires_parent:false,report_policies:['pane','mail']},assignment:{available:true,requires_parent:true,requires_scope:true,requires_expected:true,report_policies:['mail']}};
        spawnCatalog={providers:[{id:'deepseek',managed:true,models:[{id:'DeepSeek',harnesses:[
          {id:'dsh',available:true,default:true,interactive:true,task_modes:both},
          {id:'hermes',available:true,interactive:false,task_modes:legacy}]}]}],naming:{},dirs:[]};
        currentAgents=[{name:'ActualParent',provider:'anthropic',category:'agent',running:true}];
        selFamily=null;selProvider=null;selModel=null;selHarness=null;spawnAssignment.checked=false;spawnConversation.checked=true;renderProviderTabs();populateSpawnParents();
        spawnDirPath='/source';spawnTask.value='Verify result';spawnAllowedPaths.value='result.txt';spawnExpectedPath.value='result.txt';spawnExpectedValue.value='done';
        const dsh={conversationDisabled:spawnConversation.disabled,assignmentDisabled:spawnAssignment.disabled};
        spawnHarnesses.querySelector('[data-harness="hermes"]').click();
        const gated={conversationDisabled:spawnConversation.disabled,assignmentDisabled:spawnAssignment.disabled,assignmentSelected:spawnAssignment.checked,
          reason:document.getElementById('spawnModeReason').textContent,submitDisabled:spawnSubmit.disabled,summary:document.getElementById('spawnSummary').textContent,
          scopeRequired:spawnAllowedPaths.required,expectedRequired:spawnExpectedPath.required};
        spawnConversation.click();const stillAssignment=spawnAssignment.checked;
        // Direct submission is rechecked too; a stale form must not send an unsupported mode.
        spawnConversation.checked=true;spawnAssignment.checked=false;await submitSpawn(new Event('submit',{cancelable:true}));
        const rejected={posts:posts.length,text:spawnStatus.textContent};renderHarnesses();
        spawnParent.value='ActualParent';spawnParent.dispatchEvent(new Event('change'));
        await submitSpawn(new Event('submit',{cancelable:true}));
        const assignment=posts[0];
        // The same harness becomes interactive when I2 advertises it; no name-based ban.
        selectedSpawnModel().harnesses[1].task_modes=both;selectedSpawnModel().harnesses[1].interactive=true;
        renderHarnesses();spawnParent.value='';spawnConversation.click();
        const enabled={disabled:spawnConversation.disabled,selected:spawnConversation.checked,scopeRequired:spawnAllowedPaths.required,expectedRequired:spawnExpectedPath.required};
        spawnTask.value='';await submitSpawn(new Event('submit',{cancelable:true}));
        return {dsh,gated,stillAssignment,rejected,assignment,enabled,conversation:posts[1]};
      }finally{window.fetch=original;}
    })()''')
    assert result['dsh']==dict(conversationDisabled=False,assignmentDisabled=False)
    assert result['gated']['conversationDisabled'] and not result['gated']['assignmentDisabled']
    assert result['gated']['assignmentSelected'] and result['gated']['submitDisabled'] and result['stillAssignment']
    assert result['gated']['scopeRequired'] and result['gated']['expectedRequired']
    assert 'Conversation for Hermes is not ready yet' in result['gated']['reason']
    assert 'Choose a parent' in result['gated']['reason']
    assert 'Assignment compatibility mode' in result['gated']['summary']
    assert 'does not close' not in result['gated']['summary']
    assert result['rejected']['posts']==0 and 'not ready yet' in result['rejected']['text']
    assert result['assignment']['harness']=='hermes' and result['assignment']['task_mode']=='assignment'
    assert result['assignment']['parent']=='ActualParent' and result['assignment']['report_policy']=='mail'
    assert result['enabled']==dict(disabled=False,selected=True,scopeRequired=False,expectedRequired=False)
    assert result['conversation']['task_mode']=='conversation' and result['conversation']['parent'] is None


def test_assignment_artifact_checks_are_optional_except_when_catalog_requires_them():
    result=node('''
      const base={provider:'strata',harness:'dsh',model:'Qwen',parent:null,task:'Investigate the issue',dir:'/source'};
      const promptOnly=picker.managedPayload(base,'id',[],[],true);
      const rootCheck=picker.managedPayload(base,'id',[],[{path:'notes/result.txt',contains:'done'}],true);
      const escape={...rootCheck,expected:[{path:'../outside',contains:'done'}]};
      console.log(JSON.stringify({promptOnly:picker.managedError(promptOnly),rootCheck:picker.managedError(rootCheck),
        missingScope:picker.managedError(promptOnly,{requires_scope:true}),missingExpected:picker.managedError(promptOnly,{requires_expected:true}),
        escape:picker.managedError(escape)}));
    ''')
    assert result['promptOnly']==result['rootCheck']==''
    assert result['missingScope'] and result['missingExpected'] and result['escape']
