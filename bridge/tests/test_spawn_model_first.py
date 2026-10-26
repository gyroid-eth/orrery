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


def test_dynamic_same_id_per_url_survives_normalization_and_payload():
    remote=dict(providers=[dict(id='workstation',kind='strata',locality='local',dynamic_models=True,
        models=[dict(id='shared-model',display_name='Readable model',url_index=i) for i in range(3)])])
    provider=ob.normalize_spawn_catalog(remote)['providers'][0]
    result=node('const p='+json.dumps(provider)+''';console.log(JSON.stringify({keys:picker.entries({providers:[p]}).map(e=>e.key),
      names:p.models.map(m=>m.display_name)}));''')
    assert len(set(result['keys']))==3 and result['names']==['Readable model']*3
    source=(BRIDGE/'cockpit.html').read_text()
    function=re.search(r'function buildSpawnPayload\(values\)\{.*?\n\}',source,re.S).group()
    value=subprocess.run(['node','-e',function+"console.log(JSON.stringify(buildSpawnPayload({provider:'workstation',harness:'hermes',model:'shared-model',url_index:2})));"],capture_output=True,text=True,check=True)
    assert json.loads(value.stdout)['url_index']==2


def test_dynamic_local_real_controls_keep_route_and_refuse_lost_selection(tour_browser):
    _,evaluate=tour_browser
    result=evaluate('''(()=>{
      const row=(url_index,id='shared-model',model_state='available')=>({id,display_name:id,url_index,url_key:String(url_index).repeat(64),model_state,
        context:64000,context_source:'default',harnesses:[{id:'hermes',available:model_state!=='unloaded',default:true,efforts:null,effort_source:'unknown'}]});
      spawnCatalog={providers:[{id:'remote',kind:'strata',label:'Remote server',locality:'local',dynamic_models:true,models:[row(0)]},
        {id:'workstation',kind:'strata',label:'Workstation',locality:'local',dynamic_models:true,
         models:[row(0),row(1),row(2),row(2,'sleeping','unloaded')]}]};
      selFamily='local';selProvider=null;selModel=null;selUrlIndex=null;selUrlKey=null;selHarness=null;spawnModelSearch.value='';renderProviderTabs();
      modelChoices.querySelector('[data-connection=workstation][data-url-index="2"]').click();
      const payload=spawnPayloadFromForm(),summary=document.getElementById('spawnSummary').textContent;
      const disabled=[...modelChoices.querySelectorAll('input')].find(e=>e.value==='sleeping').disabled;
      spawnCatalog.providers[1].models=spawnCatalog.providers[1].models.filter(m=>m.url_index!==2);
      renderProviderTabs();renderProviderTabs();
      return {payload,summary,disabled,lost:selModel===null,blocked:spawnSubmit.disabled};
    })()''')
    assert (result['payload']['provider'],result['payload']['model'],result['payload']['url_index'])==('workstation','shared-model',2)
    assert result['payload']['url_key']=='2'*64
    assert 'Workstation' in result['summary'] and 'URL 3' in result['summary']
    assert result['disabled'] and result['lost'] and result['blocked']


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
        rangeMax:effortChoices.querySelector('input[type=range]').max};
    })()''')
    assert result['initial']['provider'] == 'claude'
    assert result['initial']['order'][:4] == ['claude','codex','deepseek','local']
    assert 'harness' not in result['initial']['payload']
    assert result['unavailable'] and result['empty'] and result['available']
    assert result['visible'] == 2
    assert result['searchSaved'] == 'test-server'
    assert result['localPayload']['harness'] == 'hermes'
    assert result['codex']['provider'] == 'codex' and result['codex']['effort'] is None
    assert 'harness' not in result['codex']['payload']
    assert result['rangeMax'] == '1'
    assert result['codex']['payload']['effort']=='high'


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
    assert claude['provider'] == 'claude' and 'effort' not in claude
    assert codex['provider'] == 'codex' and codex['effort']=='high'
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
        models:[{id:'Qwen-fixture',default:true}],helper_models:['fixture-small'],efforts:['low','medium','high']}],naming:{},dirs:[]};
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


@pytest.mark.parametrize('width', [1600, 390])
def test_effort_slider_fits_and_scientists_open_on_each_modal_open(tour_browser, width):
    client,evaluate=tour_browser
    client.call('Emulation.setDeviceMetricsOverride',width=width,height=844,deviceScaleFactor=1,mobile=False)
    result=evaluate('''(async()=>{
      const originalFetch=window.fetch;
      const catalog={providers:[{id:'codex',program:'codex-cli',models:[{id:'gpt-fixture-with-an-intentionally-long-model-identifier',default:true}],
        efforts:['low','medium','high','xhigh','max','ultra'],effort_default:'xhigh'}],naming:{scientists:['Curie','Noether'],adjectives:['Calm']},dirs:[]};
      window.fetch=async(url)=>({ok:true,json:async()=>url.startsWith('/telemetry/fs/dirs')?{path:'/workspace',dirs:[]}:catalog});
      try{
        openSpawnModal();await new Promise(r=>setTimeout(r,30));
        const details=spawnForm.querySelector('.spawn-identity-options');
        const initiallyOpen=details.open;details.open=false;spawnAdvanced.open=true;closeSpawnModal(true);
        openSpawnModal();await new Promise(r=>setTimeout(r,30));
        effortChoices.scrollIntoView({block:'center'});
        const range=effortChoices.querySelector('input[type=range]');
        const slider={max:Number(range.max),value:range.getAttribute('aria-valuetext'),
          height:effortRow.getBoundingClientRect().height,
          client:effortChoices.clientWidth,scroll:effortChoices.scrollWidth,
          stops:effortChoices.querySelectorAll('.effort-stop').length,modelFits:modelChoices.scrollWidth<=modelChoices.clientWidth,
          columns:[...document.querySelectorAll('.spawn-column')].map(el=>el.getBoundingClientRect().width),
          contentFits:document.querySelector('.spawn-picker').scrollHeight<=document.querySelector('.spawn-picker').clientHeight+1,
          noOverlap:document.querySelector('.spawn-context').getBoundingClientRect().top>=document.querySelector('.spawn-picker').getBoundingClientRect().bottom};
        const body=spawnForm.querySelector('.spawn-grid'),head=spawnForm.querySelector('.modal-head'),foot=spawnForm.querySelector('.modal-foot');
        const before={head:head.getBoundingClientRect().top,foot:foot.getBoundingClientRect().bottom};
        body.scrollTop=body.scrollHeight;
        const pathBox=spawnDirButton.getBoundingClientRect(),taskBox=spawnTask.getBoundingClientRect();
        return {initiallyOpen,reopened:details.open,advancedClosed:!spawnAdvanced.open,contextAligned:Math.abs(pathBox.left-taskBox.left)<1&&Math.abs(pathBox.width-taskBox.width)<1,slider,
          fixed:head.getBoundingClientRect().top===before.head&&foot.getBoundingClientRect().bottom===before.foot,
          footer:foot.getBoundingClientRect().bottom,height:innerHeight};
      }finally{window.fetch=originalFetch;}
    })()''')
    assert result['initiallyOpen'] and result['reopened'] and result['advancedClosed'] and result['contextAligned']
    assert result['slider']['max'] == 5 and result['slider']['stops'] == 6
    assert result['slider']['value'] == 'Default' and result['slider']['height'] <= 120
    assert result['slider']['scroll'] == result['slider']['client'] and result['slider']['modelFits'] and result['slider']['contentFits'] and result['slider']['noOverlap']
    if width==1600:
        assert result['slider']['columns'][2] >= 330 and result['slider']['columns'][1] >= 280
    assert result['fixed'] and result['footer'] <= result['height']


def test_directory_dialog_commits_only_on_confirmation_and_escape_keeps_parent(tour_browser):
    _,evaluate=tour_browser
    result=evaluate('''(async()=>{
      const originalFetch=window.fetch;
      window.fetch=async(url)=>({ok:true,json:async()=>url.startsWith('/telemetry/fs/dirs')?
        {path:decodeURIComponent(url.split('path=')[1]),dirs:[]}:{providers:[],naming:{},dirs:[]}});
      try{
        spawnDirPath='/workspace';renderSpawnDirPath();spawnOverlay.classList.add('on');
        openSpawnDirPicker();await browseDir('/workspace/docs');
        const before=spawnDirPath;document.getElementById('spawnDirCancel').click();
        const cancelled=spawnDirPath;
        openSpawnDirPicker();await browseDir('/workspace/tools');spawnDirUse.click();
        const confirmed=spawnDirPath,label=document.getElementById('spawnDirSelected').textContent;
        openSpawnDirPicker();window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
        return {before,cancelled,confirmed,label,closed:!spawnDirDialog.open,parent:spawnOverlay.classList.contains('on'),payload:spawnPayloadFromForm().dir};
      }finally{window.fetch=originalFetch;}
    })()''')
    assert result['before'] == result['cancelled'] == '/workspace'
    assert result['confirmed'] == result['label'] == result['payload'] == '/workspace/tools'
    assert result['closed'] and result['parent']


@pytest.mark.parametrize('provider,levels', [
    ('codex',['off','low','medium','high','xhigh','max','ultra']),
    ('claude',['low','medium','high','xhigh','max']),
])
def test_effort_sends_catalog_default_and_reset_restores_default(tour_browser,provider,levels):
    client,evaluate=tour_browser
    catalog=dict(providers=[dict(id=provider,program='claude-code' if provider=='claude' else 'codex-cli',
        models=[dict(id='fixture',default=True),dict(id='unsupported',efforts=[])],
        efforts=levels,effort_default='low')],naming={},dirs=[])
    evaluate('''(()=>{
      spawnCatalog=CATALOG;selFamily=null;selProvider=null;selModel=null;selHarness=null;selEffort=null;
      renderProviderTabs();spawnOverlay.classList.add('on');spawnTask.value='Fixture task';spawnDirPath='/workspace';
    })()'''.replace('CATALOG',json.dumps(catalog)))
    assert evaluate("({specified:Object.hasOwn(spawnPayloadFromForm(),'effort'),label:effortChoices.querySelector('input').getAttribute('aria-valuetext')})") == dict(specified=True,label='Default')
    evaluate("effortChoices.querySelector('input').focus()")
    def key(name,code):
        for event in ('keyDown','keyUp'):
            client.call('Input.dispatchKeyEvent',type=event,key=name,code=name,windowsVirtualKeyCode=code)
    key('End',35)
    assert evaluate('spawnPayloadFromForm().effort') == levels[-1]
    for _ in range(len(levels)-1-levels.index('high')):
        key('ArrowLeft',37)
    assert evaluate('spawnPayloadFromForm().effort') == 'high'
    # Returning to the starting neutral position still sends an explicit effort.
    assert evaluate("effortChoices.querySelector('.effort-reset').hidden") is False
    evaluate("effortChoices.querySelector('.effort-reset').click()")
    assert evaluate("({specified:Object.hasOwn(spawnPayloadFromForm(),'effort'),label:effortChoices.querySelector('input').getAttribute('aria-valuetext'),focused:document.activeElement.type})") == dict(specified=True,label='Default',focused='range')
    center=evaluate("(()=>{const r=effortChoices.querySelector('input').getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()")
    client.call('Input.dispatchMouseEvent',type='mousePressed',button='left',buttons=1,clickCount=1,**center)
    client.call('Input.dispatchMouseEvent',type='mouseReleased',button='left',buttons=0,clickCount=1,**center)
    assert evaluate('spawnPayloadFromForm().effort') == 'high'
    key('Home',36)
    assert evaluate('spawnPayloadFromForm().effort') == levels[0]
    evaluate("modelChoices.querySelector('input[value=unsupported]').click()")
    assert evaluate("({specified:Object.hasOwn(spawnPayloadFromForm(),'effort'),inputs:effortChoices.querySelectorAll('input').length,text:effortChoices.textContent})") == dict(specified=False,inputs=0,text='Not supported')
    evaluate("modelChoices.querySelector('input[value=fixture]').click()")
    assert evaluate('spawnPayloadFromForm().effort') == 'low'


@pytest.mark.parametrize('failure',['offline','http','malformed'])
def test_catalog_failure_has_no_fabricated_models_and_retry_recovers(tour_browser,failure):
    _,evaluate=tour_browser
    result=evaluate('''(async()=>{
      const originalFetch=window.fetch;let recovered=false,posts=0;
      const catalog={providers:[{id:'codex',program:'codex-cli',models:[{id:'telemetry-current',default:true}]}],naming:{},dirs:[]};
      window.fetch=async(url,options)=>{
        if(url==='/telemetry/spawn'){posts++;return {ok:true,json:async()=>({ok:true,child_name:'FixtureOnly'})};}
        if(url==='/telemetry/spawn-catalog'){
          if(recovered)return {ok:true,json:async()=>catalog};
          if(FAILURE==='offline')throw Error('fixture offline');
          if(FAILURE==='http')return {ok:false,json:async()=>catalog};
          return {ok:true,json:async()=>({not:'a catalog'})};
        }
        if(url.startsWith('/telemetry/fs/dirs'))return {ok:true,json:async()=>({path:'/workspace',dirs:[]})};
        return originalFetch(url,options);
      };
      try{
        await loadSpawnCatalog();
        const failed={count:modelChoices.querySelectorAll('input[name=spawnModel]').length,
          providers:spawnCatalog.providers.length,message:modelChoices.textContent,disabled:spawnSubmit.disabled,
          model:spawnPayloadFromForm().model,status:spawnStatus.textContent};
        await submitSpawn(new Event('submit',{cancelable:true}));
        recovered=true;modelChoices.querySelector('button').click();
        await new Promise(r=>setTimeout(r,30));
        return {failed,posts,recovered:{model:selModel,disabled:spawnSubmit.disabled,status:spawnStatus.textContent,
          labels:[...modelChoices.querySelectorAll('.model-choice-name')].map(e=>e.textContent),
          notes:modelChoices.querySelectorAll('.model-choice-note').length}};
      }finally{window.fetch=originalFetch;}
    })()'''.replace('FAILURE',json.dumps(failure)))
    assert result['failed']['count'] == result['failed']['providers'] == result['posts'] == 0
    assert result['failed']['disabled'] and result['failed']['model'] == ''
    assert 'Telemetry unavailable' in result['failed']['message'] and 'Retry' in result['failed']['message']
    assert result['recovered'] == dict(model='telemetry-current',disabled=False,status='ready',labels=['telemetry-current'],notes=0)


def test_model_ids_are_used_in_picker_summary_harness_helper_and_roster(tour_browser):
    _,evaluate=tour_browser
    result=evaluate('''(()=>{
      spawnCatalog={providers:[{id:'codex',label:'Codex from telemetry',program:'codex-cli',
        models:[{id:'raw-model-id',label:'Handwritten display',hint:'Legacy description',title:'Legacy tooltip',default:true}],
        helper_models:[{id:'raw-helper-id',label:'Friendly helper'}]}],naming:{},dirs:[]};
      selFamily=null;selProvider=null;selModel=null;selHarness=null;renderProviderTabs();
      const a={name:'FixtureModel',category:'agent',running:true,provider:'openai',model:'Friendly display',model_raw:'raw-model-id'};
      currentAgents=[a];rosterEl.append(tileFor(a));
      return {notes:modelChoices.querySelectorAll('.model-choice-note').length,tooltip:modelChoices.querySelector('.model-choice').title,name:modelChoices.querySelector('.model-choice-name').textContent,harness:document.getElementById('spawnHarnessHint').textContent,
        summary:document.getElementById('spawnSummary').querySelector('strong').textContent,
        helper:[...spawnHelper.options].map(o=>o.textContent),provider:providerTabs.querySelector('[data-family=codex] .spawn-family-copy>span').textContent,
        case:getComputedStyle(document.querySelector('[data-agent="FixtureModel"] .pill.model')).textTransform,roster:document.querySelector('[data-agent="FixtureModel"] .pill.model')?.textContent};
    })()''')
    assert result['name']==result['summary']==result['roster']=='raw-model-id'
    assert result['harness']=='For raw-model-id' and result['helper']==['Same as main','raw-helper-id']
    assert result['provider']=='Codex from telemetry' and result['notes']==0 and result['tooltip']=='' and result['case']=='none'


@pytest.mark.parametrize('levels,value,fallback,expected', [
    (['low','high'],None,'high','high'),
    (['low','high'],None,None,None),
    (['low','high'],None,'invalid',None),
    (None,None,None,None),
    ([],None,'high',None),
    (['low','high'],'low','high','low'),
    (['low','high'],'invalid','high',None),
    (['none','high'],None,'none','none'),
])
def test_effective_effort_uses_only_supported_explicit_or_reported_default(levels,value,fallback,expected):
    source=(BRIDGE/'cockpit.html').read_text()
    function=re.search(r'function resolveSpawnEffort\(levels,value,fallback\)\{.*?\n\}',source,re.S).group()
    run=subprocess.run(['node','-e',function+'\nconsole.log(JSON.stringify(resolveSpawnEffort('+','.join(json.dumps(v) for v in (levels,value,fallback))+')));'],capture_output=True,text=True,check=True)
    assert json.loads(run.stdout)==expected


@pytest.mark.parametrize('model,expected', [
    ({'id':'fixture','efforts':['low','high'],'effort_default':None}, None),
    ({'id':'fixture','efforts':['low','high'],'effort_default':'low'}, 'low'),
    ({'id':'fixture','harnesses':[{'id':'hermes','available':True,'efforts':['low','high'],'default_effort':None,'effort_source':'harness'}]}, None),
    ({'id':'fixture','harnesses':[{'id':'hermes','available':True,'efforts':None,'default_effort':None,'effort_source':'unknown'}]}, None),
    ({'id':'fixture','efforts':[]}, None),
    ({'id':'fixture'}, 'high'),
])
def test_model_or_harness_null_default_does_not_inherit_provider_guess(model,expected):
    source=(BRIDGE/'cockpit.html').read_text()
    names=['effortsForModel','resolveSpawnEffort','spawnExplicitEffortMissing','effectiveSpawnEffort']
    functions='\n'.join(re.search(r'function '+name+r'\([^\n]*\)\{.*?\n\}',source,re.S).group() for name in names)
    result=node('const SpawnPicker=picker;let selHarness="hermes",selEffort=null;'+functions+
        '\nconst p='+json.dumps({'id':'deepseek','efforts':['low','high'],'effort_default':'high','models':[model]})+
        ';console.log(JSON.stringify(effectiveSpawnEffort(p,"fixture")));')
    assert result==expected


@pytest.mark.parametrize('model,fields', [
    ({'id':'fixture','efforts':None,'effort_default':None}, {}),
    ({'id':'fixture'}, {'model_efforts':{'fixture':None}}),
    ({'id':'fixture','effort_default':None}, {}),
    ({'id':'fixture','efforts':[]}, {}),
    ({'id':'fixture','efforts':{}}, {}),
    ({'id':'fixture'}, {'model_efforts':{'fixture':'invalid'}}),
    ({'id':'fixture'}, {'model_efforts':{'fixture':['low','high']},'model_effort_defaults':{'fixture':None}}),
])
def test_own_null_effort_metadata_keeps_provider_default_unresolved(model,fields):
    source=(BRIDGE/'cockpit.html').read_text()
    names=['effortsForModel','resolveSpawnEffort','spawnExplicitEffortMissing','effectiveSpawnEffort']
    functions='\n'.join(re.search(r'function '+name+r'\([^\n]*\)\{.*?\n\}',source,re.S).group() for name in names)
    provider={'id':'deepseek','efforts':['low','high'],'effort_default':'high','models':[model],**fields}
    result=node('const SpawnPicker=picker;let selHarness="hermes",selEffort=null;'+functions+
        '\nconst p='+json.dumps(provider)+';console.log(JSON.stringify(effectiveSpawnEffort(p,"fixture")));')
    assert result is None


def test_required_effort_requires_explicit_choice_before_button_and_post(tour_browser):
    _,evaluate=tour_browser
    result=evaluate('''(async()=>{
      spawnCatalog={providers:[{id:'codex',program:'codex-cli',models:[{id:'fixture'}],
        capabilities:{effort_required:true},efforts:['low','high'],effort_default:'high'}],naming:{},dirs:[]};
      selFamily=null;selProvider=null;selModel=null;selHarness=null;selEffort=null;renderProviderTabs();
      spawnTask.value='Fixture task';spawnDirPath='/fixture';
      const original=window.fetch;let posts=0;
      window.fetch=async(url,...args)=>{if(String(url)!=='/telemetry/spawn')return original(url,...args);posts++;return {ok:true,json:async()=>({ok:true,child_name:'Fixture'})};};
      try{
        const untouched={disabled:spawnSubmit.disabled,payload:spawnPayloadFromForm()};
        await submitSpawn(new Event('submit',{cancelable:true}));untouched.posts=posts;
        effortChoices.querySelector('input').value=0;effortChoices.querySelector('input').dispatchEvent(new Event('input'));
        const explicit={disabled:spawnSubmit.disabled,payload:spawnPayloadFromForm()};
        await submitSpawn(new Event('submit',{cancelable:true}));explicit.posts=posts;
        effortChoices.querySelector('.effort-reset').click();
        const reset={disabled:spawnSubmit.disabled,payload:spawnPayloadFromForm()};
        await submitSpawn(new Event('submit',{cancelable:true}));reset.posts=posts;
        selEffort='invented';updateSpawnAvailability();
        const invalid={disabled:spawnSubmit.disabled,payload:spawnPayloadFromForm()};
        await submitSpawn(new Event('submit',{cancelable:true}));invalid.posts=posts;
        return {untouched,explicit,reset,invalid};
      }finally{window.fetch=original;}
    })()''')
    assert result['untouched']['disabled'] and result['untouched']['posts']==0
    assert 'effort' not in result['untouched']['payload']
    assert result['explicit']['disabled'] is False and result['explicit']['posts']==1
    assert result['explicit']['payload']['effort']=='low'
    assert result['reset']['disabled'] and result['reset']['posts']==1
    assert 'effort' not in result['reset']['payload']
    assert result['invalid']['disabled'] and result['invalid']['posts']==1
    assert 'effort' not in result['invalid']['payload']
