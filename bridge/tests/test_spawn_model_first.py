"""Catalog capabilities, model identity and request compatibility for the picker."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from test_spawn_model_overflow import ob, _remote
from test_cockpit_tour import tour_browser  # noqa: F401

BRIDGE = Path(__file__).resolve().parents[1]


def node(body):
    result = subprocess.run(['node', '-e',
        f'const picker=require({json.dumps(str(BRIDGE / "spawn_picker.js"))});\n' + body],
        capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_legacy_catalog_gets_its_existing_launch_path_without_model_changes():
    catalog = ob.normalize_spawn_catalog(_remote())
    provider = catalog['providers'][0]
    assert provider['locality'] == 'cloud'
    assert provider['harnesses'] == [dict(id='claude-code', label='Claude Code', available=True, default=True)]
    assert provider['models'][0] == dict(id='claude-sonnet-5', label='claude-sonnet-5')


def test_model_capabilities_override_provider_and_empty_means_unavailable():
    provider = dict(id='local-one', program='codex-cli', locality='local',
        harnesses=[dict(id='hermes', available=True, default=True)],
        server='server-one', context='32K', helper_models=['small-model'],
        models=[dict(id='model-one', harnesses=[], helper_models=[], locality='cloud')])
    catalog = ob.normalize_spawn_catalog(dict(providers=[provider]))
    result = node('const p='+json.dumps(catalog['providers'][0])+''';const m=p.models[0];
      console.log(JSON.stringify({entries:picker.entries({providers:[p]}),
        harnesses:picker.harnesses(p,m),helpers:picker.helperModels(p,m),metadata:picker.metadata(p,m)}));''')
    assert result['entries'][0]['family'] != 'local'
    assert not any(h['available'] for h in result['harnesses'])
    assert result['helpers'] == []
    assert result['metadata'] == 'server-one / 32K'


def test_harness_availability_is_catalog_driven_including_future_tools():
    result = node('''
      const provider={id:'local',program:'codex-cli',locality:'local'};
      const missing=picker.harnesses(provider,{id:'one'});
      const future=picker.harnesses(provider,{id:'one',harnesses:[
        {id:'hermes',available:true,default:true},{id:'dsh',available:true},
        {id:'new-harness',label:'Another harness',available:true}]});
      console.log(JSON.stringify({missing,future}));''')
    assert [h['id'] for h in result['missing'] if h['available']] == ['codex-cli']
    assert all(h['available'] for h in result['future'])


def test_local_duplicates_have_distinct_identity_and_removed_recents_are_not_choices():
    result = node('''
      let stored='[]';const store={getItem:()=>stored,setItem:(k,v)=>{stored=v;}};
      const providers=['a','b'].map(id=>({id,locality:'local',models:[{id:'same'}]}));
      const entries=picker.entries({providers});entries.forEach(e=>picker.remember(store,'recent',e.key));
      const saved=picker.recent(store,'recent');const remaining=entries.slice(1);
      console.log(JSON.stringify({keys:entries.map(e=>e.key),saved,
        visible:saved.map(k=>remaining.find(e=>e.key===k)).filter(Boolean).map(e=>e.key),
        denied:picker.recent({getItem:()=>{throw Error('denied');}},'recent')}));''')
    assert len(set(result['keys'])) == 2
    assert result['saved'] == result['keys'][::-1]
    assert result['visible'] == result['keys'][1:]
    assert result['denied'] == []


@pytest.mark.parametrize('agent, expected', [
    (dict(provider='anthropic', program='claude-code', model='claude-model'), None),
    (dict(provider='openai', program='codex-cli', model='gpt-model'), None),
    (dict(provider='local', program='codex-cli', model='Qwen'), 'Codex'),
    (dict(provider='local', program='hermes', model='Qwen'), 'Hermes'),
    (dict(provider='deepseek', program='dsh', model='DeepSeek'), 'dsh'),
    (dict(provider='openai', program='hermes', model='gpt-model'), 'Hermes'),
])
def test_roster_chips_only_suppress_the_native_cloud_pairs(agent, expected):
    result = node('console.log(JSON.stringify(picker.rosterHarness('+json.dumps(agent)+')));')
    assert (result['label'] if result else None) == expected


def test_default_spawn_payload_is_byte_compatible_and_optional_controls_are_explicit():
    source = (BRIDGE / 'cockpit.html').read_text()
    function = re.search(r'function buildSpawnPayload\(values\)\{.*?\n\}', source, re.S).group()
    result = subprocess.run(['node', '-e', function + '''
      const values={provider:'codex',model:'model-one',task:'test',dir:'/workspace',effort:'high'};
      console.log(JSON.stringify([buildSpawnPayload(values),buildSpawnPayload({...values,harness:'hermes',helper_model:'small'})]));
    '''], capture_output=True, text=True, check=True)
    old, new = json.loads(result.stdout)
    assert old == dict(standalone=True,parent=None,name=None,provider='codex',model='model-one',
        effort='high',dir='/workspace',role='',emoji='',group='',task='test',worktree=False,worktree_base='',headless=True)
    assert new == {**old, 'harness':'hermes', 'helper_model':'small'}


def test_picker_defaults_local_search_and_capability_updates_in_browser(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(async()=>{
      spawnCatalog={providers:[
        {id:'codex',program:'codex-cli',models:[{id:'gpt-fixture',default:true}],efforts:['low','high'],effort_default:'high'},
        {id:'claude',program:'claude-code',models:[{id:'claude-fixture',default:true}],efforts:null},
        {id:'local-server',locality:'local',program:'codex-cli',server:'test-server',
          models:[{id:'Qwen-one',context:'32K',vision:true},{id:'Qwen-two'}],
          harnesses:[{id:'hermes',label:'Hermes',default:true,available:false}]}],naming:{},dirs:[]};
      selFamily=null;selProvider=null;selModel=null;selHarness=null;renderProviderTabs();
      const initial={provider:selProvider,model:selModel,harness:selHarness,payload:spawnPayloadFromForm(),
        order:[...providerTabs.children].map(b=>b.dataset.family)};
      providerTabs.querySelector('[data-family="local"]').click();
      const unavailable=spawnSubmit.disabled&&spawnHarnesses.querySelector('[data-harness="hermes"]').disabled;
      spawnModelSearch.value='not-present';spawnModelSearch.dispatchEvent(new Event('input'));
      const empty=modelChoices.textContent.includes('No models match');
      spawnModelSearch.value='test-server';spawnModelSearch.dispatchEvent(new Event('input'));
      const visible=modelChoices.querySelectorAll('input[name="spawnModel"]').length;
      spawnCatalog.providers[2].harnesses[0].available=true;renderHarnesses();
      const available=!spawnSubmit.disabled&&!spawnHarnesses.querySelector('[data-harness="hermes"]').disabled;
      const localPayload=spawnPayloadFromForm();
      providerTabs.querySelector('[data-family="codex"]').click();
      return {initial,unavailable,empty,visible,available,localPayload,searchSaved:localStorage.getItem(SPAWN_SEARCH_STORAGE_KEY),
        codex:{provider:selProvider,model:selModel,effort:selEffort,payload:spawnPayloadFromForm()},
        disabledEfforts:effortChoices.querySelectorAll('button:disabled').length};
    })()''')
    assert result['initial']['provider'] == 'claude'
    assert result['initial']['order'][:4] == ['claude','codex','deepseek','local']
    assert 'harness' not in result['initial']['payload']
    assert result['unavailable'] and result['empty'] and result['available']
    assert result['visible'] == 2
    assert result['searchSaved'] == 'test-server'
    assert result['localPayload']['harness'] == 'hermes'
    assert result['codex']['provider'] == 'codex' and result['codex']['effort'] == 'high'
    assert 'harness' not in result['codex']['payload']
    assert result['disabledEfforts'] > 0


def test_submit_cloud_defaults_and_optional_local_parameters_without_real_spawn(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(async()=>{
      const originalFetch=window.fetch,posted=[];
      window.fetch=async(url,options)=>{
        if(url==='/telemetry/spawn'){posted.push(JSON.parse(options.body));return {ok:true,json:async()=>({ok:true,child_name:'FixtureOnly'})};}
        return originalFetch(url,options);
      };
      try{
        spawnCatalog={providers:[
          {id:'claude',program:'claude-code',models:[{id:'claude-fixture',default:true},{id:'local-override',locality:'local'}]},
          {id:'codex',program:'codex-cli',models:[{id:'gpt-fixture',default:true}],efforts:['low','high'],effort_default:'high'},
          {id:'local-fixture',locality:'local',program:'codex-cli',models:[{id:'local-one',default:true}],
            harnesses:[{id:'example-tool',default:true,available:true}],helper_models:['small']}],naming:{},dirs:[]};
        selFamily=null;selProvider=null;selModel=null;selHarness=null;selScientist='';
        spawnDirPath='/workspace';spawnTask.value='Test accepted launch';populateSpawnParents();renderProviderTabs();
        const cloudModels=[...modelChoices.querySelectorAll('input[name="spawnModel"]')].map(i=>i.value);
        await submitSpawn(new Event('submit',{cancelable:true}));
        providerTabs.querySelector('[data-family="codex"]').click();
        await submitSpawn(new Event('submit',{cancelable:true}));
        providerTabs.querySelector('[data-family="local"]').click();
        spawnHelper.value='small';
        await submitSpawn(new Event('submit',{cancelable:true}));
        return {posted,cloudModels,recent:SpawnPicker.recent(localStorage,SPAWN_RECENT_STORAGE_KEY)};
      }finally{window.fetch=originalFetch;}
    })()''')
    claude,codex,local=result['posted']
    assert result['cloudModels'] == ['claude-fixture']
    assert claude['provider'] == 'claude' and claude['effort'] is None
    assert codex['provider'] == 'codex' and codex['effort'] == 'high'
    assert 'harness' not in claude and 'helper_model' not in claude
    assert 'harness' not in codex and 'helper_model' not in codex
    assert local['provider'] == 'local-fixture' and local['harness'] == 'example-tool' and local['helper_model'] == 'small'
    assert result['recent'][0] == json.dumps(['local-fixture','local-one'],separators=(',',':'))


def test_empty_provider_keeps_its_configuration_error_visible(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(()=>{
      spawnCatalog={providers:[{id:'claude',program:'claude-code',models:[],model_error:'Fixture configuration error'}],naming:{},dirs:[]};
      selFamily=null;selProvider=null;selModel=null;selHarness=null;renderProviderTabs();
      return {text:modelChoices.textContent,disabled:spawnSubmit.disabled};
    })()''')
    assert 'Fixture configuration error' in result['text']
    assert result['disabled']


def test_picker_controls_fit_a_small_viewport_and_footer_stays_visible(tour_browser):
    client, evaluate = tour_browser
    client.call('Emulation.setDeviceMetricsOverride',width=390,height=844,deviceScaleFactor=1,mobile=False)
    result=evaluate('''(async()=>{
      spawnCatalog={providers:[{id:'local-one',locality:'local',program:'codex-cli',
        models:[{id:'Qwen-fixture',default:true}],efforts:['low','medium','high']}],naming:{},dirs:[]};
      selFamily=null;selProvider=null;selModel=null;selHarness=null;renderProviderTabs();
      spawnOverlay.classList.add('on');
      await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
      const form=spawnForm.getBoundingClientRect(),picker=document.querySelector('.spawn-picker').getBoundingClientRect(),
        submit=spawnSubmit.getBoundingClientRect();
      return {form:form.width,pickerRight:picker.right,footerBottom:submit.bottom,width:innerWidth,height:innerHeight,
        helperWidth:spawnHelper.getBoundingClientRect().width};
    })()''')
    assert result['form'] <= result['width']
    assert result['pickerRight'] <= result['width']
    assert result['footerBottom'] <= result['height']
    assert result['helperWidth'] > 0
