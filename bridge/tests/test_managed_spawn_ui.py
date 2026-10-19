"""Stage1 managed launch UI: exact request, stable attempt and honest readiness.

Everything uses a dummy catalog/HTTP response; no real child, Mail, key or API.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from test_cockpit_tour import tour_browser  # noqa: F401
from test_spawn_model_first import node
from test_spawn_model_overflow import ob


@pytest.mark.parametrize('provider,harness', [('strata','dsh'),('strata','hermes'),('deepseek','dsh'),('deepseek','hermes')])
def test_four_managed_pairs_keep_scope_parent_identity_and_readiness_separate(tour_browser, provider, harness):
    _, evaluate = tour_browser
    result = evaluate('''(async()=>{
      const original=window.fetch,posts=[],queries=[];let verdict='pending';
      window.fetch=async(url,options)=>{
        if(url==='/telemetry/spawn'){
          const p=JSON.parse(options.body);posts.push(p);
          return {ok:true,status:202,json:async()=>({ok:true,pending:true,attempt_id:p.attempt_id,state:'pending',phase:'queued'})};
        }
        if(String(url).startsWith('/telemetry/spawn-status?')){
          queries.push(String(url));const id=new URL(url,location.origin).searchParams.get('attempt_id');
          return {ok:true,json:async()=>({ok:true,managed:true,attempt_id:id,name:'OfflineChild',state:verdict,phase:verdict==='failed'?'retiring':verdict==='ready'?'running':'registered',
            task_success:verdict==='failed'?true:null,runtime_success:verdict==='failed'?false:null,finished:verdict==='failed',state_path:'/fixture/state',error:verdict==='failed'?'Cleanup failed':null})};
        }
        return original(url,options);
      };
      try{
        const provider={id:PROVIDER,managed:true,program:HARNESS,locality:PROVIDER==='strata'?'local':'cloud',
          models:[{id:'configured-model',default:true}],harnesses:[{id:HARNESS,available:true,default:true}],
          helper_models:['other-model'],efforts:['low','high'],effort_default:'high',context_source:'unreported'};
        spawnCatalog={providers:[provider],naming:{},dirs:[]};
        currentAgents=[{name:'OfflineParent',provider:HARNESS==='hermes'?'openai':'anthropic',program:HARNESS==='hermes'?'codex-cli':'claude-code',running:true,category:'agent'}];
        selFamily=null;selProvider=null;selModel=null;selHarness=null;selScientist='';populateSpawnParents();renderProviderTabs();spawnParent.value='OfflineParent';
        spawnDirPath='/workspace';spawnTask.value='Write result.txt with done and report.';
        spawnAllowedPaths.value='result.txt';spawnExpectedPath.value='result.txt';spawnExpectedKind.value='contains';spawnExpectedValue.value='done';
        const controls={name:ncName.textContent,helper:spawnHelper.value,disabled:spawnHelper.disabled,options:[...spawnHelper.options].map(o=>o.value),note:document.getElementById('spawnSummary').textContent};
        await submitSpawn(new Event('submit',{cancelable:true}));await new Promise(r=>setTimeout(r,25));
        const id=posts[0].attempt_id,pending={...managedAttempts.get(id)},pendingText=document.getElementById('spawnLaunchRows').textContent;
        verdict='ready';await refreshManagedSpawn(id);const readyText=document.getElementById('spawnLaunchRows').textContent;
        verdict='failed';await refreshManagedSpawn(id);const failed={...managedAttempts.get(id)},failedText=document.getElementById('spawnLaunchRows').textContent;
        return {controls,posts,queries,pending,pendingText,readyText,failed,failedText,stored:JSON.parse(localStorage.getItem(SPAWN_ATTEMPTS_KEY)),open:!document.getElementById('spawnLaunches').hidden};
      }finally{window.fetch=original;}
    })()'''.replace('PROVIDER',json.dumps(provider)).replace('HARNESS',json.dumps(harness)))
    assert len(result['posts']) == 1
    payload = result['posts'][0]
    assert payload['provider'] == provider and payload['harness'] == harness
    assert payload['model'] == 'configured-model' and payload['parent'] == 'OfflineParent'
    assert payload['standalone'] is False and payload['worktree'] is True
    assert payload['allowed_paths'] == ['result.txt'] and payload['expected'] == [dict(path='result.txt',contains='done')]
    assert payload['helper_model'] == 'same' and payload['async'] is True
    assert not {'name','headless','worktree_base','context','context_length'} & payload.keys()
    assert all('attempt_id='+payload['attempt_id'] in url for url in result['queries'])
    assert result['controls']['name'] == 'Assigned at launch'
    assert result['controls']['disabled'] and result['controls']['options'] == ['same']
    assert 'Server-reported context: not yet available' in result['controls']['note']
    assert result['pending']['state'] == 'pending' and 'Ready' not in result['pendingText']
    assert 'Readiness confirmed; task completion is separate.' in result['readyText']
    assert result['failed']['state'] == 'failed' and result['failed']['state_path'] == '/fixture/state'
    assert 'Task: succeeded' in result['failedText'] and 'Cleanup: failed' in result['failedText']
    assert result['open'] and result['stored'][0]['attempt_id'] == payload['attempt_id']


def test_transport_timeout_and_unknown_status_keep_the_same_attempt_without_reposting(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(async()=>{
      const original=window.fetch;let posts=0,queryId=null;
      window.fetch=async(url,options)=>{
        if(url==='/telemetry/spawn'){posts++;return {ok:false,status:504,json:async()=>({error:'spawn still running after 90s'})};}
        if(String(url).startsWith('/telemetry/spawn-status?')){
          queryId=new URL(url,location.origin).searchParams.get('attempt_id');
          return {ok:false,json:async()=>({ok:false,error_code:'attempt_not_found'})};
        }return original(url,options);
      };
      try{
        spawnCatalog={providers:[{id:'strata',locality:'local',models:[{id:'local-model'}],harnesses:[{id:'dsh',available:true}]}],naming:{},dirs:[]};
        currentAgents=[{name:'OfflineParent',provider:'anthropic',running:true,category:'agent'}];
        selFamily=null;selProvider=null;selModel=null;selHarness=null;selScientist='';populateSpawnParents();renderProviderTabs();spawnParent.value='OfflineParent';
        spawnDirPath='/workspace';spawnTask.value='Write scoped artifact';spawnAllowedPaths.value='result.txt';spawnExpectedPath.value='result.txt';spawnExpectedValue.value='done';
        await submitSpawn(new Event('submit',{cancelable:true}));await new Promise(r=>setTimeout(r,25));
        const record=[...managedAttempts.values()][0];return {posts,queryId,record,saved:JSON.parse(localStorage.getItem(SPAWN_ATTEMPTS_KEY)),text:document.getElementById('spawnLaunchRows').textContent};
      }finally{window.fetch=original;}
    })()''')
    assert result['posts'] == 1
    assert result['record']['attempt_id'] == result['queryId'] == result['saved'][0]['attempt_id']
    assert result['record']['state'] == 'pending'
    assert 'Attempt not found yet' in result['text'] and 'Check status' in result['text']


def test_managed_rejection_and_scope_validation_do_not_claim_ready():
    result = node('''
      const base={provider:'deepseek',harness:'dsh',task:'Write output',dir:'/workspace',parent:'Parent',name:'Ignored',headless:true};
      const make=(paths,expected)=>picker.managedPayload(base,'attempt',paths,expected);
      console.log(JSON.stringify({missingParent:picker.managedError({...make(['x'],[{path:'x',contains:'ok'}]),parent:null}),
        glob:picker.managedError(make(['**'],[{path:'x',contains:'ok'}])),
        outside:picker.managedError(make(['x'],[{path:'y',contains:'ok'}])),
        valid:picker.managedError(make(['x'],[{path:'x',sha256:'a'.repeat(64)}]))}));
    ''')
    assert result['missingParent'] and result['glob'] and result['outside']
    assert result['valid'] == ''


def test_bridge_forwards_attempt_id_to_the_existing_status_endpoint():
    urls = []
    class Response:
        status = 200
        headers = {'Content-Type':'application/json'}
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def read(self):return b'{"ok":true,"state":"pending"}'
    class Session:
        def get(self,url,*args,**kwargs):urls.append(url);return Response()
    app={ob.HTTP_SESSION_KEY:Session(),ob.TMUX_BIN_KEY:'unused-fixture-tmux'}
    request=SimpleNamespace(path='/telemetry/spawn-status',query={'attempt_id':'fixture-attempt','unrelated':'discard'},app=app)
    response=asyncio.run(ob.proxy_dashboard(request))
    assert response.status == 200
    assert urls == [ob.DASHBOARD_URL+'/api/spawn-status?attempt_id=fixture-attempt']


def test_reload_restores_pending_attempt_and_never_reposts(tour_browser):
    client, evaluate = tour_browser
    attempt='aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
    evaluate('''localStorage.setItem('orrery.managed-spawn-attempts.v1',JSON.stringify([
      {attempt_id:ID,provider:'strata',harness:'dsh',state:'pending',phase:'queued',finished:false}]));'''.replace('ID',json.dumps(attempt)))
    client.call('Page.navigate',url=evaluate.base+'/cockpit.html')
    result=evaluate('''(async()=>{
      for(let n=0;n<50;n++){
        const row=document.querySelector('#spawnLaunchRows [data-attempt-id]');
        if(row)return {id:row.dataset.attemptId,state:row.dataset.state,text:row.textContent,
          reposted:performance.getEntriesByType('resource').some(e=>new URL(e.name).pathname==='/telemetry/spawn')};
        await new Promise(r=>setTimeout(r,20));
      }throw Error('Attempt did not survive reload');
    })()''')
    assert result['id'] == attempt and result['state'] == 'pending'
    assert not result['reposted'] and 'Check status' in result['text']


def test_three_existing_provider_payloads_do_not_enter_managed_dispatch(tour_browser):
    _, evaluate = tour_browser
    result=evaluate('''(async()=>{
      const original=window.fetch,posted=[];
      window.fetch=async(url,options)=>url==='/telemetry/spawn'
        ?{ok:true,json:async()=>{posted.push(JSON.parse(options.body));return {ok:true,child_name:'LegacyFixture'};}}
        :original(url,options);
      try{
        for(const id of ['claude','codex','gemini']){
          spawnCatalog={providers:[{id,program:id==='claude'?'claude-code':id==='codex'?'codex-cli':'gemini',models:[{id:id+'-fixture'}]}],naming:{},dirs:[]};
          selFamily=null;selProvider=null;selModel=null;selHarness=null;selScientist='';
          currentAgents=[];populateSpawnParents();renderProviderTabs();spawnTask.value='Fixture task';spawnDirPath='/workspace';
          await submitSpawn(new Event('submit',{cancelable:true}));
        }
        return posted;
      }finally{window.fetch=original;}
    })()''')
    assert [row['provider'] for row in result] == ['claude','codex','gemini']
    assert all(not {'attempt_id','allowed_paths','expected','helper_model','harness'} & row.keys() for row in result)
    assert all(row['standalone'] is True for row in result)


@pytest.mark.parametrize('http_status', [200,409])
def test_profile_busy_is_a_rejection_not_a_queue_or_status_poll(tour_browser,http_status):
    _, evaluate = tour_browser
    result=evaluate('''(async()=>{
      const original=window.fetch;let posts=0,polls=0;
      window.fetch=async(url,options)=>{
        if(url==='/telemetry/spawn'){posts++;return {ok:STATUS===200,status:STATUS,json:async()=>({ok:false,error_code:'profile_busy'})};}
        if(String(url).startsWith('/telemetry/spawn-status?')){polls++;throw Error('Rejected job must not be polled');}
        return original(url,options);
      };
      try{
        spawnCatalog={providers:[{id:'strata',managed:true,locality:'local',models:[{id:'configured-model'}],harnesses:[{id:'hermes',available:true}]}],naming:{},dirs:[]};
        currentAgents=[{name:'OfflineParent',provider:'openai',running:true,category:'agent'}];
        selFamily=null;selProvider=null;selModel=null;selHarness=null;selScientist='';populateSpawnParents();renderProviderTabs();spawnParent.value='OfflineParent';
        spawnDirPath='/workspace';spawnTask.value='Scoped fixture';spawnAllowedPaths.value='result.txt';spawnExpectedPath.value='result.txt';spawnExpectedValue.value='done';
        await submitSpawn(new Event('submit',{cancelable:true}));await new Promise(r=>setTimeout(r,20));
        return {posts,polls,record:[...managedAttempts.values()][0],text:document.getElementById('spawnLaunchRows').textContent};
      }finally{window.fetch=original;}
    })()'''.replace('STATUS',str(http_status)))
    assert result['posts']==1 and result['polls']==0
    assert result['record']['state']=='failed' and result['record']['rejected'] is True
    assert result['record']['error_code']=='profile_busy'
    assert result['record']['phase']=='rejected'
    assert 'already using this backend profile' in result['text']
    assert 'Check status' not in result['text'] and 'Dismiss' in result['text']
