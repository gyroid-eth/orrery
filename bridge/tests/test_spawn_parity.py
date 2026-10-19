"""Standard spawn contract across families; dummy HTTP and existing CDP only."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from test_cockpit_tour import tour_browser  # noqa: F401
from test_spawn_model_first import node
from test_spawn_model_overflow import ob


def catalog():
    return dict(providers=[dict(id=id,program=program,locality='local' if id=='strata' else 'cloud',
        models=[dict(id=id+'-model',harnesses=[dict(id=h,available=True,default=i==0,
            efforts=['low','high'],default_effort='high',effort_source='harness',helper_models=[])
            for i,h in enumerate(harnesses)])]) for id,program,harnesses in [
            ('claude','claude-code',['claude-code']),('codex','codex-cli',['codex-cli']),('gemini','gemini',['gemini']),
            ('deepseek','dsh',['dsh','hermes']),('strata','dsh',['dsh','hermes'])]],
        naming=dict(scientists=['Tesla'],adjectives=['Bold'],taken=[]),dirs=[])


@pytest.mark.parametrize('provider,harness', [('claude','claude-code'),('codex','codex-cli'),('gemini','gemini'),
    ('deepseek','dsh'),('deepseek','hermes'),('strata','dsh'),('strata','hermes')])
@pytest.mark.parametrize('parent', ['', 'OtherHarnessParent'])
def test_all_families_use_the_same_form_payload_and_parent_candidates(tour_browser,provider,harness,parent):
    _,evaluate=tour_browser
    result=evaluate('''(async()=>{
      const original=window.fetch,posts=[];
      window.fetch=async(url,options)=>url==='/telemetry/spawn'
        ?{ok:true,json:async()=>{posts.push(JSON.parse(options.body));return {ok:true,child_name:'ChosenChild',tmux_session:'ChosenChild'};}}
        :original(url,options);
      try{
        spawnCatalog=CATALOG;
        currentAgents=[{name:'OtherHarnessParent',program:'hermes',provider:'local',running:true,category:'agent'},
          {name:'ClaudeParent',program:'claude-code',provider:'anthropic',running:true,category:'agent'},
          {name:'Stopped',running:false,category:'agent'},{name:'Human',running:true,category:'human'}];
        selFamily=null;selProvider=null;selModel=null;selHarness=null;selScientist='';
        spawnAdvanced.open=false;populateSpawnParents();renderProviderTabs();renderAgentStrip();
        providerTabs.querySelector('[data-family="'+FAMILY+'"]').click();
        spawnHarnesses.querySelector('[data-harness="'+HARNESS+'"]').click();
        spawnParent.value=PARENT;
        agentStrip.querySelector('[role=option]').click();spawnAdjective.value='Bold';updateNameCard();
        spawnTask.value='Use the selected folder';spawnDirPath='/source';spawnRole.value='research';spawnEmoji.value='🔭';
        spawnWorktree.checked=Boolean(PARENT);spawnGhostty.checked=Boolean(PARENT);
        const controls={picker:!spawnForm.querySelector('.spawn-identity-options').hidden,portrait:!ncPortrait.hidden,
          worktreeEnabled:!spawnWorktree.disabled,terminalEnabled:!spawnGhostty.disabled,advanced:spawnAdvanced.open,
          checks:!!document.getElementById('spawnManagedFields'),launchRows:!!document.getElementById('spawnLaunches'),
          helperHidden:document.getElementById('spawnHelperField').hidden,
          parents:[...spawnParent.options].map(o=>o.value),harnesses:[...spawnHarnesses.children].map(b=>b.dataset.harness)};
        await submitSpawn(new Event('submit',{cancelable:true}));
        return {posts,controls};
      }finally{window.fetch=original;}
    })()'''.replace('CATALOG',json.dumps(catalog())).replace('FAMILY',json.dumps('local' if provider=='strata' else provider))
        .replace('HARNESS',json.dumps(harness)).replace('PARENT',json.dumps(parent)))
    assert len(result['posts'])==1
    payload=result['posts'][0]
    assert payload['provider']==provider and payload['model']==provider+'-model'
    assert payload['name']=='BoldTesla' and payload['task']=='Use the selected folder'
    assert payload['parent']==(parent or None) and payload['standalone'] is (not bool(parent))
    assert payload['worktree'] is bool(parent) and payload['headless'] is (not bool(parent))
    assert payload['dir']=='/source' and payload['role']=='research' and payload['emoji']=='🔭'
    assert payload['async'] is True
    assert not {'attempt_id','managed','task_mode','report_policy','allowed_paths','expected','effort','family','locality'} & payload.keys()
    if provider in ('deepseek','strata'):
        assert payload['harness']==harness
    else:
        assert 'harness' not in payload
    controls=result['controls']
    assert controls['picker'] and controls['portrait'] and controls['worktreeEnabled'] and controls['terminalEnabled']
    assert not controls['advanced'] and not controls['checks'] and not controls['launchRows']
    assert controls['helperHidden']
    assert set(controls['parents'])=={'','OtherHarnessParent','ClaudeParent'}
    assert controls['harnesses']==(['dsh','hermes'] if provider in ('deepseek','strata') else [harness])


@pytest.mark.parametrize('main_only',[False,True])
def test_harness_effort_and_helper_capabilities_do_not_fall_back_to_trial_defaults(tour_browser,main_only):
    _,evaluate=tour_browser
    result=evaluate('''(()=>{
      spawnCatalog=CATALOG;const p=spawnCatalog.providers.find(p=>p.id==='strata');
      p.efforts=['trial-only'];p.helper_models=['trial-helper'];
      p.models[0].harnesses[0].helper_models=HELPERS;
      p.models[0].harnesses[1].efforts=null;p.models[0].harnesses[1].effort_source='unknown';
      selFamily='local';selProvider='strata';selModel='strata-model';selHarness='dsh';selEffort=null;renderProviderTabs();
      const a={levels:effortsForModel(p,selModel),hasEffort:Object.hasOwn(spawnPayloadFromForm(),'effort'),
        helpers:[...spawnHelper.options].map(o=>o.value),helperHidden:document.getElementById('spawnHelperField').hidden};
      effortChoices.querySelector('input').value=1;effortChoices.querySelector('input').dispatchEvent(new Event('input'));
      const explicit=spawnPayloadFromForm().effort;
      spawnHarnesses.querySelector('[data-harness=hermes]').click();
      return {a,explicit,unknown:{levels:effortsForModel(p,selModel),hasEffort:Object.hasOwn(spawnPayloadFromForm(),'effort'),
        text:effortChoices.textContent,summary:document.getElementById('spawnSummary').textContent,helperHidden:document.getElementById('spawnHelperField').hidden}};
    })()'''.replace('CATALOG',json.dumps(catalog())).replace('HELPERS',json.dumps(['same','strata-model']+([] if main_only else ['small']))))
    assert result['a']['levels']['efforts']==['low','high'] and result['a']['hasEffort'] is False
    assert result['a']['helpers']==(['same'] if main_only else ['same','small'])
    assert result['a']['helperHidden'] is main_only
    assert result['explicit']=='high'
    assert result['unknown']['levels']['efforts'] is None and result['unknown']['hasEffort'] is False
    assert result['unknown']['text']=='Uses harness default' and result['unknown']['helperHidden']
    assert 'Effort: Default' in result['unknown']['summary']
    assert 'Not supported' not in result['unknown']['summary']


@pytest.mark.parametrize('verdict',['ready','failed'])
def test_standard_async_status_is_queried_by_child_name(tour_browser,verdict):
    _,evaluate=tour_browser
    result=evaluate('''(async()=>{
      const original=window.fetch,originalWatch=watchSpawnLaunch,queries=[];let posts=0,deadline=null;
      watchSpawnLaunch=(name,seconds)=>{deadline=seconds;return originalWatch(name,seconds);};
      window.fetch=async(url,options)=>{
        if(url==='/telemetry/spawn'){posts++;return {ok:true,json:async()=>({ok:true,child_name:'StandardChild',tmux_session:'StandardChild',pending:true,verdict_deadline_seconds:170})};}
        if(String(url).startsWith('/telemetry/spawn-status?')){queries.push(String(url));return {ok:true,json:async()=>({ok:true,state:VERDICT,error:VERDICT==='failed'?'Fixture failed':null})};}
        return original(url,options);
      };
      try{
        spawnCatalog=CATALOG;selFamily='deepseek';selProvider='deepseek';selModel='deepseek-model';selHarness='dsh';selScientist='';renderProviderTabs();
        spawnParent.value='';spawnTask.value='Initial task';spawnDirPath='/source';
        await submitSpawn(new Event('submit',{cancelable:true}));await new Promise(r=>setTimeout(r,2200));
        return {posts,queries,deadline,toast:toastEl.textContent};
      }finally{window.fetch=original;watchSpawnLaunch=originalWatch;}
    })()'''.replace('CATALOG',json.dumps(catalog())).replace('VERDICT',json.dumps(verdict)))
    assert result['posts']==1 and result['queries']==['/telemetry/spawn-status?name=StandardChild']
    assert result['deadline']==170
    assert ('SPAWNED' if verdict=='ready' else 'SPAWN FAILED') in result['toast']


@pytest.mark.parametrize('deadline,ready_at,expected_ms',[(170,160000,160000),(170,None,170000),(None,None,140000)])
def test_standard_status_waits_for_server_deadline_or_legacy_default(deadline,ready_at,expected_ms):
    import re
    from pathlib import Path
    source=(Path(__file__).resolve().parents[1]/'cockpit.html').read_text()
    watch=re.search(r'async function watchSpawnLaunch\([^)]*\)\{.*?(?=\nasync function submitSpawn)',source,re.S).group()
    result=node('const events=[],toasts=[];let now=0;Date.now=()=>now;'
        'function setTimeout(cb,ms){now+=ms;cb();}'
        'const document={dispatchEvent:e=>events.push(e.detail.id)};'
        'class CustomEvent{constructor(_,v){this.detail=v.detail;}}'
        'function showToast(t){toasts.push(t);}'
        'async function fetch(){return {json:async()=>({ok:true,state:'+
        ('now>=160000?"ready":"launching"' if ready_at else '"launching"')+'})};}'
        +watch+';watchSpawnLaunch("Fixture",'+json.dumps(deadline)+')'
        '.then(()=>console.log(JSON.stringify({now,events,toasts})));')
    assert result['now']==expected_ms
    assert bool(result['events']) is bool(ready_at)
    assert ('SPAWNED' if ready_at else f'after {deadline or 140}s') in result['toasts'][0]


@pytest.mark.parametrize('harness,model', [('dsh','GPT-model'),('hermes','GPT-model'),('dsh','Claude-model'),('codex-cli','Claude-model'),('claude-code','GPT-model'),('gemini','GPT-model')])
def test_composer_uses_the_harness_not_the_model_vendor(tour_browser,harness,model):
    _,evaluate=tour_browser
    result=evaluate('''(()=>{
      currentAgents=[{name:'MixedHarness',program:HARNESS,provider:'openai',model:MODEL}];
      panes.set('fixture',{session:'MixedHarness'});activeId='fixture';
      return {program:targetProgram(),prefix:targetPrefix()};
    })()'''.replace('HARNESS',json.dumps(harness)).replace('MODEL',json.dumps(model)))
    expected={'codex-cli':'codex','claude-code':'claude'}.get(harness,harness)
    assert result==dict(program=expected,prefix='$' if expected=='codex' else '/')


@pytest.mark.parametrize('program',['dsh','hermes','dsh-tui','unknown'])
def test_unexposed_native_skills_never_borrow_claude_files(monkeypatch,program):
    monkeypatch.setattr(ob,'_collect_skills',lambda *_:pytest.fail('must not collect another harness skills'))
    response=asyncio.run(ob.serve_skills(SimpleNamespace(query={'program':program})))
    assert json.loads(response.body)==dict(program='dsh' if program=='dsh-tui' else program,prefix='/',skills=[])
