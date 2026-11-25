"""Catalog capabilities, model identity and request compatibility for the picker."""
import asyncio
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


def test_proxied_catalog_mode_comes_from_the_runtime_boundary():
    class Response:
        status = 200
        headers = {'Content-Type': 'application/json'}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def read(self):
            return b'{"providers":[],"runtime_mode":"unknown"}'

    class Session:
        def get(self, *_args, **_kwargs):
            return Response()

    fresh = object.__new__(ob.FreshTargetBoundary)
    for boundary, mode in [(object(), 'legacy'), (fresh, 'fresh')]:
        body, status, _ = asyncio.run(ob.fetch_proxied(
            Session(), '/telemetry/spawn-catalog', 'http://fixture.invalid', boundary))
        assert status == 200
        assert json.loads(body)['runtime_mode'] == mode


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
      const payload=spawnPayloadFromForm(),metadata=modelChoices.querySelector('input:checked').closest('label').title;
      const disabled=[...modelChoices.querySelectorAll('input')].find(e=>e.value==='sleeping').disabled;
      spawnCatalog.providers[1].models=spawnCatalog.providers[1].models.filter(m=>m.url_index!==2);
      renderProviderTabs();renderProviderTabs();
      return {payload,metadata,disabled,lost:selModel===null,blocked:spawnSubmit.disabled};
    })()''')
    assert (result['payload']['provider'],result['payload']['model'],result['payload']['url_index'])==('workstation','shared-model',2)
    assert result['payload']['url_key']=='2'*64
    assert 'Workstation' in result['metadata'] and 'URL 3' in result['metadata']
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
      spawnTask.value='Fixture task';
      selFamily=null;selProvider=null;selModel=null;selHarness=null;renderProviderTabs();
      const initial={provider:selProvider,model:selModel,harness:selHarness,payload:spawnPayloadFromForm(),
        order:[...providerTabs.querySelectorAll('button')].map(b=>b.dataset.family)};
      providerTabs.querySelector('[data-family="local"]').click();
      const unavailable=spawnSubmit.disabled&&spawnHarnesses.querySelector('[data-harness="hermes"]').disabled;
      spawnModelSearch.value='not-present';spawnModelSearch.dispatchEvent(new Event('input'));
      const empty=modelChoices.textContent.includes('No models found');
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


def test_tool_defaults_follow_harness_and_keep_manual_choices_on_render(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(()=>{
      const model={id:'fixture',default:true};
      spawnCatalog={providers:[
        {id:'claude',program:'claude-code',models:[model]},
        {id:'codex',program:'codex-cli',models:[model]},
        {id:'deepseek',program:'dsh',models:[model],harnesses:[
          {id:'dsh',available:true,default:true},{id:'hermes',available:true}]}]};
      const select=family=>providerTabs.querySelector(`[data-family="${family}"]`).click();
      const states=()=>spawnToolSwitches.map(control=>control.getAttribute('aria-checked')==='true');
      renderProviderTabs();
      const claude=states();
      spawnComputerUse.click();
      renderProviderTabs();
      const edited=states();
      select('codex');const codex=states();
      const codexTitle=spawnBrowserUse.title;
      spawnBrowserUse.click();const codexNotice=spawnStatus.textContent;
      select('deepseek');const dsh=states();
      const dshNotice=spawnStatus.textContent;
      spawnHarnesses.querySelector('[data-harness="hermes"]').click();const hermes=states();
      spawnHarnesses.querySelector('[data-harness="dsh"]').click();
      return {claude,edited,codex,dsh,hermes,dshAgain:states(),codexTitle,codexNotice,dshNotice};
    })()''')
    assert "config.toml" in result.pop("codexTitle")
    assert "chrome-devtools" in result.pop("codexNotice")
    assert result.pop("dshNotice") == ""
    assert result == dict(claude=[True, True], edited=[False, True], codex=[True, False],
                         dsh=[False, False], hermes=[True, True], dshAgain=[False, False])


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
          {id:'deepseek',program:'dsh',models:[{id:'deepseek-fixture',default:true}]},
          {id:'local-fixture',locality:'local',program:'codex-cli',models:[{id:'local-one',default:true}],
            harnesses:[{id:'example-tool',default:true,available:true}],helper_models:['small']}],naming:{},dirs:[]};
        selFamily=null;selProvider=null;selModel=null;selHarness=null;selScientist='';
        spawnDirPath='/workspace';spawnTask.value='Test accepted launch';renderProviderTabs();
        const cloudModels=[...modelChoices.querySelectorAll('input[name="spawnModel"]')].map(i=>i.value);
        await submitSpawn(new Event('submit',{cancelable:true}));
        providerTabs.querySelector('[data-family="codex"]').click();
        spawnComputerUse.click();
        await submitSpawn(new Event('submit',{cancelable:true}));
        spawnBrowserUse.click();
        await submitSpawn(new Event('submit',{cancelable:true}));
        providerTabs.querySelector('[data-family="deepseek"]').click();
        await submitSpawn(new Event('submit',{cancelable:true}));
        spawnComputerUse.click();spawnBrowserUse.click();
        await submitSpawn(new Event('submit',{cancelable:true}));
        providerTabs.querySelector('[data-family="local"]').click();
        spawnHelper.value='small';
        const hidden=spawnTools.hidden;
        await submitSpawn(new Event('submit',{cancelable:true}));
        return {posted,cloudModels,hidden,recent:SpawnPicker.recent(localStorage,SPAWN_RECENT_STORAGE_KEY)};
      }finally{window.fetch=originalFetch;}
    })()''')
    claude,codex_off,codex,dsh_off,dsh_on,local=result['posted']
    assert result['cloudModels'] == ['claude-fixture']
    assert claude['provider'] == 'claude' and 'effort' not in claude
    assert codex['provider'] == 'codex' and codex['effort']=='high'
    assert 'harness' not in claude and 'helper_model' not in claude
    assert 'harness' not in codex and 'helper_model' not in codex
    assert claude['tools'] == {'mcp': ['cua-driver'], 'browser': {}}
    assert codex['tools'] == {'browser': {}} and codex['base'] == 'mail-only'
    assert codex_off['tools'] == {} and codex_off['base'] == 'mail-only'
    assert dsh_off['tools'] == {} and dsh_off['base'] == 'mail-only'
    assert dsh_on['tools'] == {'mcp': ['cua-driver', 'chrome-devtools']}
    assert local['provider'] == 'local-fixture' and local['harness'] == 'example-tool' and local['helper_model'] == 'small'
    assert result['hidden'] and 'tools' not in local
    assert result['recent'][0] == json.dumps(['local-fixture','local-one'],separators=(',',':'))


def test_browser_icon_selects_modes_without_adding_a_layout_control(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(()=>{
      const model={id:'fixture',default:true};
      openSpawnModal();
      spawnCatalog={browser_modes:{'claude-code':['off','temporary','personal'],antigravity:[]},
        providers:[{id:'claude',program:'claude-code',models:[model]},
          {id:'gemini',program:'antigravity',models:[model]}]};
      selFamily=null;selProvider=null;selModel=null;selHarness=null;
      renderProviderTabs();
      const initial=spawnToolOptions();
      spawnBrowserUse.click();
      const choices=[...spawnBrowserMenu.querySelectorAll('button:not([hidden])')].map(b=>b.textContent);
      const opened=spawnBrowserMenu.matches(':popover-open');
      spawnBrowserChoices[1][1].click();
      const chosen=spawnToolOptions(),caption=spawnBrowserUse.getAttribute('aria-label');
      selProvider='gemini';selHarness='antigravity';renderSpawnTools();
      return {initial,choices,opened,chosen,caption,limited:spawnBrowserUse.getAttribute('aria-disabled'),
        reason:spawnBrowserUse.title,hasText:spawnBrowserUse.textContent.trim()!==''};
    })()''')
    assert result['opened'] and not result['hasText']
    assert result['choices'] == ['Off','Temporary Chrome','My Chrome']
    assert result['initial']['tools']['browser_mode'] == 'personal'
    assert result['chosen']['tools']['browser_mode'] == 'temporary'
    assert result['caption'] == 'Browser: Temporary Chrome'
    assert result['limited'] == 'true' and 'Antigravity' in result['reason']


def test_browser_off_keeps_the_standard_base_on_current_telemetry(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(()=>{
      const model={id:'fixture',default:true};
      spawnCatalog={supports_browser_off:true,providers:[
        {id:'claude',program:'claude-code',models:[model]},
        {id:'codex',program:'codex-cli',models:[model]},
        {id:'local-fixture',program:'dsh',locality:'local',models:[model],
         harnesses:[{id:'dsh',available:true,default:true},{id:'hermes',available:true}]}]};
      selFamily=null;selProvider=null;selModel=null;selHarness=null;renderProviderTabs();
      spawnBrowserUse.click();
      const claude=spawnToolOptions();
      providerTabs.querySelector('[data-family="codex"]').click();
      spawnComputerUse.click();
      const codex=spawnToolOptions();
      spawnBrowserUse.click();
      const codexBrowserOn=spawnToolOptions();
      providerTabs.querySelector('[data-family="local"]').click();
      const dsh=spawnToolOptions();
      spawnHarnesses.querySelector('[data-harness="hermes"]').click();
      spawnBrowserUse.click();
      const hermes=spawnToolOptions();
      return {claude,codex,codexBrowserOn,dsh,hermes};
    })()''')
    assert result == {
        'claude': {'tools': {'mcp': ['cua-driver'], 'browser_off': True}},
        'codex': {'tools': {'browser_off': True}},
        'codexBrowserOn': {'tools': {'browser': {}}},
        'dsh': {'tools': {'browser_off': True}},
        'hermes': {'tools': {'mcp': ['cua-driver'], 'browser_off': True}},
    }


def test_fresh_spawn_omits_unsupported_tool_options(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(async()=>{
      const originalFetch=window.fetch,posted=[];
      window.fetch=async(url,options)=>{
        if(url==='/telemetry/spawn'){posted.push(JSON.parse(options.body));return {ok:true,json:async()=>({ok:true,child_name:'FixtureOnly'})};}
        return originalFetch(url,options);
      };
      try{
        const catalog={providers:[{id:'claude',program:'claude-code',models:[{id:'claude-fixture',default:true}]}],naming:{},dirs:[]};
        spawnCatalog={...catalog,runtime_mode:'legacy'};renderProviderTabs();
        const legacyVisible=!spawnTools.hidden;
        spawnCatalog={...catalog,runtime_mode:'fresh'};renderProviderTabs();
        const freshHidden=spawnTools.hidden;
        spawnDirPath='/workspace';spawnTask.value='Fixture task';
        await submitSpawn(new Event('submit',{cancelable:true}));
        return {legacyVisible,freshHidden,posted};
      }finally{window.fetch=originalFetch;}
    })()''')
    assert result['legacyVisible'] and result['freshHidden']
    assert len(result['posted']) == 1
    assert {'tools', 'base'}.isdisjoint(result['posted'][0])


def test_gemini_mark_only_appears_when_catalog_offers_antigravity(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      const geminiTab=()=>providerTabs.querySelector('[data-family="gemini"]');
      spawnCatalog={providers:[{id:'claude',models:[{id:'claude-fixture'}]}]};
      renderProviderTabs();
      const before=Boolean(geminiTab());
      spawnCatalog.providers.push({
        id:'gemini',label:'Antigravity',program:'antigravity',models:[{id:'gemini-fixture'}]
      });
      renderProviderTabs();
      const tab=geminiTab(),icon=tab.querySelector('img');
      const mark={src:icon.getAttribute('src'),mono:icon.classList.contains('mono'),alt:icon.alt,
        title:tab.title,label:tab.getAttribute('aria-label'),enabled:!tab.disabled};
      tab.click();
      const selected=selProvider;
      spawnCatalog.providers.pop();
      renderProviderTabs();
      return {before,mark,selected,after:Boolean(geminiTab()),fallback:selProvider};
    })()""")
    assert result == {
        'before': False, 'after': False, 'selected': 'gemini', 'fallback': 'claude',
        'mark': {'src': 'cockpit-assets/google.svg', 'mono': True, 'alt': '',
                 'title': 'Antigravity', 'label': 'Antigravity', 'enabled': True},
    }


def test_empty_provider_keeps_its_configuration_error_visible(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(()=>{
      spawnCatalog={providers:[{id:'claude',program:'claude-code',models:[],model_error:'Fixture configuration error'}],naming:{},dirs:[]};
      selFamily=null;selProvider=null;selModel=null;selHarness=null;renderProviderTabs();
      return {text:spawnStatus.textContent,disabled:spawnSubmit.disabled};
    })()''')
    assert 'Fixture configuration error' in result['text']
    assert result['disabled']


@pytest.mark.parametrize('width', [1600, 390])
def test_launcher_and_model_sheet_fit_and_name_draft_can_be_discarded(tour_browser, width):
    client,evaluate=tour_browser
    client.call('Emulation.setDeviceMetricsOverride',width=width,height=844,deviceScaleFactor=1,mobile=False)
    result=evaluate('''(async()=>{
      const originalFetch=window.fetch;
      const catalog={providers:[{id:'lab',locality:'local',program:'codex-cli',
        models:[{id:'intentionally-long-local-model-identifier-and-server',default:true}],helper_models:['fixture-small'],
        efforts:['low','medium','high','xhigh','max','ultra'],effort_default:'xhigh'}],
        naming:{scientists:['Curie','Noether'],adjectives:['Calm']},dirs:[]};
      window.fetch=async(url)=>({ok:true,json:async()=>url.startsWith('/telemetry/fs/dirs')?{path:'/workspace',dirs:[]}:catalog});
      const settle=()=>new Promise(r=>setTimeout(r,530));
      const within=element=>{const box=element.getBoundingClientRect();return box.width>0&&box.left>=0&&box.right<=innerWidth&&box.bottom<=innerHeight;};
      try{
        openSpawnModal();await settle();
        const normal={name:spawnNameSheet.hidden,model:spawnModelSheet.hidden,disabled:spawnSubmit.disabled};
        spawnNameButton.click();await settle();
        const options=agentStrip.querySelectorAll('[role=option]').length;
        const fieldsFit=within(spawnNameSearch)&&within(spawnRole);
        spawnRole.value='Review';spawnRole.dispatchEvent(new Event('input'));
        const preview=ncRole.textContent;
        closeSpawnModal();openSpawnModal();await settle();
        const restored=spawnNameSheet.hidden&&!ncRole.hidden&&spawnRole.value==='Review';
        const discardFits=within(spawnDiscardDraft);
        spawnDiscardDraft.click();
        const reset=spawnNameSheet.hidden&&ncRole.hidden&&spawnRole.value==='';
        const before=spawnSubmit.getBoundingClientRect();
        spawnModelButton.click();await settle();
        const range=effortChoices.querySelector('input[type=range]');
        const after=spawnSubmit.getBoundingClientRect();
        return {normal,options,fieldsFit,preview,restored,discardFits,reset,helper:within(spawnHelper),sheet:within(spawnModelSheet),
          launcher:within(spawnLauncher),fixed:before.bottom===after.bottom&&before.left===after.left,
          range:{max:Number(range.max),value:Number(range.value),label:range.getAttribute('aria-valuetext'),
            stops:effortChoices.querySelectorAll('.effort-stop').length,modelFits:modelChoices.scrollWidth<=modelChoices.clientWidth}};
      }finally{window.fetch=originalFetch;}
    })()''')
    assert result['normal'] == dict(name=True, model=True, disabled=True)
    assert result['options'] == 2 and result['fieldsFit'] and result['preview']=='Review'
    assert all(result[k] for k in ['restored','discardFits','reset','helper','sheet','launcher','fixed'])
    assert result['range'] == dict(max=5, value=3, label='Default (xhigh)', stops=6, modelFits=True)


def test_directory_sheet_commits_only_on_confirmation_and_escape_keeps_launcher(tour_browser):
    _,evaluate=tour_browser
    result=evaluate('''(async()=>{
      const originalFetch=window.fetch;
      window.fetch=async(url)=>({ok:true,json:async()=>url.startsWith('/telemetry/fs/dirs')?
        {path:decodeURIComponent(url.split('path=')[1]),dirs:[]}:{providers:[],naming:{},dirs:[]}});
      const esc=()=>window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
      try{
        spawnDirPath='/workspace';renderSpawnDirPath();spawnOverlay.classList.add('on');
        openSpawnDirPicker();await browseDir('/workspace/docs');
        const before=spawnDirPath;esc();
        const cancelled=spawnDirPath;
        openSpawnDirPicker();await browseDir('/workspace/tools');spawnDirUse.click();
        const confirmed=spawnDirPath,label=document.getElementById('spawnDirSelected').textContent,title=spawnDirButton.title;
        openSpawnDirPicker();esc();
        return {before,cancelled,confirmed,label,title,closed:spawnOpenSheet!==spawnDirSheet,parent:spawnOverlay.classList.contains('on'),payload:spawnPayloadFromForm().dir};
      }finally{window.fetch=originalFetch;}
    })()''')
    assert result['before'] == result['cancelled'] == '/workspace'
    assert result['confirmed'] == result['title'] == result['payload'] == '/workspace/tools'
    assert result['label'] == 'tools'
    assert result['closed'] and result['parent']


def test_directory_sheet_scopes_search_to_current_breadcrumb_and_lists_children(tour_browser):
    _,evaluate=tour_browser
    result=evaluate('''(async()=>{
      const original=window.fetch,requests=[];
      const vault='/work/Notes',projects=vault+'/Code Projects';
      const other=vault+'/Archive',project=projects+'/plotter',archived=other+'/plotter';
      let releaseOld;
      const folder=path=>({path,name:path.split('/').at(-1)});
      const directories={[vault]:[projects,other],[projects]:[project], [project]:[]};
      window.fetch=async(url)=>{
        const request=new URL(url,location.origin),parameters=request.searchParams;
        if(request.pathname==='/telemetry/fs/dir-search'){
          const q=parameters.get('q'),under=parameters.get('under');
          requests.push({q,under});
          if(q==='later')await new Promise(resolve=>{releaseOld=resolve;});
          const dirs=under===vault?[project,archived,'/outside/plotter']:[project];
          return {ok:true,json:async()=>({dirs:dirs.map(folder)})};
        }
        const path=parameters.get('path');
        return {ok:true,json:async()=>({path,dirs:(directories[path]||[]).map(folder)})};
      };
      const rows=()=>Array.from(spawnDirResults.children,row=>row.querySelector('span').textContent);
      const waitFor=async condition=>{
        for(let attempt=0;attempt<100&&!condition();attempt++)await new Promise(resolve=>setTimeout(resolve,20));
      };
      const type=value=>{spawnDirSearch.value=value;spawnDirSearch.dispatchEvent(new Event('input'));};
      const press=key=>spawnDirSearch.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true,cancelable:true}));
      try{
        spawnDirPath=vault;spawnOverlay.classList.add('on');openSpawnDirPicker();
        await waitFor(()=>rows().length===2);
        const focus=document.activeElement===spawnDirSearch,children=rows();
        type('plotter');await waitFor(()=>rows().length===2&&rows()[0].endsWith('/plotter'));
        const rootMatches=rows(),first=spawnDirSearch.getAttribute('aria-activedescendant'),scopeActionHidden=spawnDirUse.hidden;
        press('ArrowDown');const second=spawnDirSearch.getAttribute('aria-activedescendant');
        type('');press('Enter');await waitFor(()=>spawnDirBrowsePath===projects);
        const projectChildren=rows(),crumb=dirCrumbs.querySelector('[aria-current]').textContent;
        type('later');await waitFor(()=>typeof releaseOld==='function');
        [...dirCrumbs.querySelectorAll('button')].find(button=>button.title===vault).click();
        await waitFor(()=>spawnDirBrowsePath===vault);releaseOld();
        await new Promise(resolve=>setTimeout(resolve,30));
        const ignoredStale=rows().join(' ')==='Code Projects Archive';
        press('Enter');await waitFor(()=>spawnDirBrowsePath===projects);
        type('plotter');await waitFor(()=>requests.at(-1)?.q==='plotter'&&rows().length===1);
        const narrowed=rows();press('Enter');await waitFor(()=>spawnOpenSheet!==spawnDirSheet);
        return {focus,children,rootMatches,first,second,projectChildren,crumb,ignoredStale,narrowed,scopeActionHidden,
          picked:spawnPayloadFromForm().dir,requests};
      }finally{window.fetch=original;}
    })()''')
    vault='/work/Notes'
    projects=vault+'/Code Projects'
    assert result['focus'] and result['ignoredStale'] and result['scopeActionHidden']
    assert result['children']==['Code Projects','Archive']
    assert result['rootMatches']==['Code Projects/plotter','Archive/plotter']
    assert result['projectChildren']==result['narrowed']==['plotter']
    assert result['crumb']=='Code Projects'
    assert result['first']=='spawnDirResult0' and result['second']=='spawnDirResult1'
    assert result['picked']==projects+'/plotter'
    assert result['requests']==[dict(q='plotter',under=vault),dict(q='later',under=projects),dict(q='plotter',under=projects)]


def test_directory_search_proxy_preserves_scope_and_empty_or_repeated_parameters(monkeypatch):
    from aiohttp import ClientSession, web
    from aiohttp.test_utils import TestClient, TestServer

    async def run():
        async def echo(request):
            return web.json_response(list(request.query.items()))

        upstream=web.Application()
        upstream.router.add_get('/api/fs/dir-search', echo)
        async with TestServer(upstream) as source, ClientSession() as session:
            monkeypatch.setattr(ob,'DASHBOARD_URL',str(source.make_url('')).rstrip('/'))
            app=web.Application()
            app[ob.HTTP_SESSION_KEY]=session
            app[ob.TMUX_BIN_KEY]='unused'
            app.router.add_get('/telemetry/fs/dir-search',ob.proxy_dashboard)
            async with TestClient(TestServer(app)) as client:
                params=[('q',''),('under','/Work/Code Projects'),('under','')]
                async with client.get('/telemetry/fs/dir-search',params=params) as response:
                    assert response.status==200
                    return await response.json()

    assert asyncio.run(run())==[['q',''],['under','/Work/Code Projects'],['under','']]


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
      spawnModelButton.click();
    })()'''.replace('CATALOG',json.dumps(catalog)))
    assert evaluate("({specified:Object.hasOwn(spawnPayloadFromForm(),'effort'),label:effortChoices.querySelector('input').getAttribute('aria-valuetext')})") == dict(specified=True,label='Default (low)')
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
    assert evaluate("effortChoices.querySelector('.effort-reset').disabled") is False
    evaluate("effortChoices.querySelector('.effort-reset').click()")
    assert evaluate("({specified:Object.hasOwn(spawnPayloadFromForm(),'effort'),label:effortChoices.querySelector('input').getAttribute('aria-valuetext'),focused:document.activeElement.type})") == dict(specified=True,label='Default (low)',focused='range')
    evaluate('Promise.all(spawnModelSheet.getAnimations().map(animation=>animation.finished))')
    center=evaluate("(()=>{const r=effortChoices.querySelector('input').getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()")
    client.call('Input.dispatchMouseEvent',type='mousePressed',button='left',buttons=1,clickCount=1,**center)
    client.call('Input.dispatchMouseEvent',type='mouseReleased',button='left',buttons=0,clickCount=1,**center)
    assert evaluate('spawnPayloadFromForm().effort') == levels[len(levels)//2]
    key('Home',36)
    assert evaluate('spawnPayloadFromForm().effort') == levels[0]
    evaluate("modelChoices.querySelector('input[value=unsupported]').click()")
    assert evaluate("({specified:Object.hasOwn(spawnPayloadFromForm(),'effort'),inputs:effortChoices.querySelectorAll('input').length,text:effortChoices.textContent})") == dict(specified=False,inputs=0,text='')
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
        spawnTask.value='Fixture task';await loadSpawnCatalog();
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
    assert 'Model catalog unavailable' in result['failed']['status'] and 'Retry' in result['failed']['message']
    assert result['recovered'] == dict(model='telemetry-current',disabled=False,status='',labels=['telemetry-current'],notes=0)


def test_model_ids_are_used_in_sheet_chip_helper_and_roster(tour_browser):
    _,evaluate=tour_browser
    result=evaluate('''(()=>{
      spawnCatalog={providers:[{id:'codex',label:'Codex from telemetry',program:'codex-cli',
        models:[{id:'raw-model-id',label:'Handwritten display',hint:'Legacy description',title:'Legacy tooltip',default:true}],
        helper_models:[{id:'raw-helper-id',label:'Friendly helper'}]}],naming:{},dirs:[]};
      selFamily=null;selProvider=null;selModel=null;selHarness=null;renderProviderTabs();
      const a={name:'FixtureModel',category:'agent',running:true,provider:'openai',model:'Friendly display',model_raw:'raw-model-id'};
      currentAgents=[a];tileFor(a);
      const rosterModel=document.querySelector('[data-agent="FixtureModel"] .roster-model');
      return {notes:modelChoices.querySelectorAll('.model-choice-note').length,tooltip:modelChoices.querySelector('.model-choice').title,name:modelChoices.querySelector('.model-choice-name').textContent,harnessHidden:spawnHarnesses.hidden,
        chip:spawnModelLabel.textContent,
        helper:[...spawnHelper.options].map(o=>o.textContent),provider:providerTabs.querySelector('[data-family=codex]').getAttribute('aria-label'),
        case:getComputedStyle(rosterModel).textTransform,roster:rosterModel.textContent,rosterTooltip:rosterModel.title};
    })()''')
    assert result['name']==result['chip']=='raw-model-id'
    assert result['roster']=='Friendly display' and 'raw-model-id' in result['rosterTooltip']
    assert result['harnessHidden'] and result['helper']==['Same as main','raw-helper-id']
    assert result['provider']=='Codex from telemetry' and result['notes']==0 and result['tooltip']=='raw-model-id' and result['case']=='none'


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


def test_palette_keeps_agent_search_and_launches_from_an_unmatched_query(tour_browser):
    _, evaluate = tour_browser
    result = evaluate('''(async()=>{
      const original=window.fetch,posts=[];
      const catalog={providers:[{id:'claude',program:'claude-code',models:[{id:'fixture'}]}],naming:{},dirs:[]};
      window.fetch=async(url,options)=>{
        if(url==='/telemetry/spawn'){posts.push(JSON.parse(options.body));return {ok:true,json:async()=>({ok:true,child_name:'FixtureOnly'})};}
        if(url==='/telemetry/spawn-catalog')return {ok:true,json:async()=>catalog};
        if(url.startsWith('/telemetry/fs/dirs'))return {ok:true,json:async()=>({path:'/workspace',dirs:[]})};
        return original(url,options);
      };
      const key=(key,metaKey=false)=>window.dispatchEvent(new KeyboardEvent('keydown',{key,metaKey,bubbles:true,cancelable:true}));
      const search=value=>{paletteInput.value=value;paletteInput.dispatchEvent(new Event('input'));};
      try{
        currentAgents=[{name:'CalmCurie',running:true,category:'agent'}];
        key('k',true);search('Curie');
        const matched=paletteResults.firstElementChild?.querySelector('.palette-name').textContent;
        search('Review the launcher');
        const unmatched=paletteResults.firstElementChild?.querySelector('.palette-name').textContent;
        const anchor=spawnAnchor(paletteOverlay.querySelector('.palette').getBoundingClientRect());
        key('Enter');
        const task=spawnTask.value, paletteClosed=!paletteOverlay.classList.contains('on');
        const fromPalette=Math.abs(parseFloat(spawnLauncher.style.getPropertyValue('--spawn-origin-x'))+spawnLauncher.offsetLeft-anchor.x)<1;
        await loadSpawnCatalog();key('Enter',true);
        await new Promise(r=>setTimeout(r,40));
        return {matched,unmatched,task,paletteClosed,fromPalette,posts,open:spawnOverlay.classList.contains('on')};
      }finally{window.fetch=original;}
    })()''')
    assert result['matched'] == 'CalmCurie'
    assert result['unmatched'] == 'New agent'
    assert result['task'] == 'Review the launcher'
    assert result['paletteClosed'] and result['fromPalette'] and not result['open']
    assert len(result['posts']) == 1 and result['posts'][0]['task'] == result['task']


def test_scientist_grid_scrolls_filters_and_remembers_successful_names(tour_browser):
    client,evaluate=tour_browser
    names=sorted(p.stem for p in (BRIDGE.parent/'assets'/'portraits').glob('*.png'))
    assert len(names)==50
    catalog=dict(providers=[dict(id='claude',program='claude-code',models=[dict(id='fixture')])],
        naming=dict(scientists=names,adjectives=['Calm']),dirs=[])
    evaluate('''(async()=>{
      const catalog=CATALOG;
      window.fetch=async url=>({ok:true,json:async()=>url==='/telemetry/spawn'?{ok:true, child_name:'CalmCurie'}:
        url.startsWith('/telemetry/fs/dirs')?{path:'/work',dirs:[]}:catalog});
      SpawnPicker.remember(spawnViewerStorage,SPAWN_NAME_RECENT_KEY,'Noether');
      openSpawnModal();await loadSpawnCatalog();
      spawnNameButton.click();
      await new Promise(resolve=>setTimeout(resolve,550));
    })()'''.replace('CATALOG',json.dumps(catalog)))
    initial=evaluate('''(()=>{
      const options=spawnScientistOptions(),box=agentStrip.getBoundingClientRect();
      const visibleRows=new Set(options.filter(option=>option.getBoundingClientRect().bottom<=box.bottom+1)
        .map(option=>option.offsetTop));
      return {focused:document.activeElement===spawnNameSearch,count:options.length,rows:visibleRows.size,
        first:options[0].dataset.scientist,remainingStartsSecond:options[1].offsetTop>options[0].offsetTop,
        scrolls:agentStrip.scrollHeight>agentStrip.clientHeight};
    })()''')
    assert initial == dict(focused=True,count=50,rows=4,first='Noether',remainingStartsSecond=True,scrolls=True)
    for key,code,expected in [('ArrowDown',40,'Noether'),('ArrowDown',40,'Archimedes'),('ArrowRight',39,'Arrhenius')]:
        client.call('Input.dispatchKeyEvent',type='keyDown',key=key,code=key,windowsVirtualKeyCode=code)
        client.call('Input.dispatchKeyEvent',type='keyUp',key=key,code=key,windowsVirtualKeyCode=code)
        assert evaluate('document.activeElement.dataset.scientist')==expected
    evaluate("""spawnNameSearch.focus();spawnNameSearch.value='Cu';spawnNameSearch.dispatchEvent(new Event('input'))""")
    assert evaluate('spawnScientistOptions().map(option=>option.dataset.scientist)')==['Curie']
    for key,code in [('ArrowDown',40),('Enter',13)]:
        client.call('Input.dispatchKeyEvent',type='keyDown',key=key,code=key,windowsVirtualKeyCode=code)
        client.call('Input.dispatchKeyEvent',type='keyUp',key=key,code=key,windowsVirtualKeyCode=code)
    assert evaluate("({chosen:selScientist,name:composedName(),option:spawnScientistOptions()[0].getAttribute('aria-selected')})")==dict(chosen='Curie',name='CalmCurie',option='true')
    assert evaluate("spawnNameSheet.querySelectorAll('svg use[href=\"#spawn-icon-dice\"]').length")==1
    assert evaluate("spawnScientistOptions()[0].click();spawnPayloadFromForm().name") is None
    assert evaluate("spawnScientistOptions()[0].click();spawnPayloadFromForm().name")=='CalmCurie'
    saved=evaluate('''(async()=>{
      spawnTask.value='Review the launcher';await submitSpawn(new Event('submit',{cancelable:true}));
      openSpawnModal();await loadSpawnCatalog();spawnNameButton.click();
      return {history:SpawnPicker.recent(spawnViewerStorage,SPAWN_NAME_RECENT_KEY),
        top:spawnScientistOptions().slice(0,2).map(option=>option.dataset.scientist)};
    })()''')
    assert saved==dict(history=['Curie','Noether'],top=['Curie','Noether'])


def test_folder_browser_reports_the_canonical_home(monkeypatch, tmp_path):
    from types import SimpleNamespace

    real_home = tmp_path / 'account'
    folder = real_home / 'projects'
    folder.mkdir(parents=True)
    alias = tmp_path / 'home'
    alias.symlink_to(real_home)
    monkeypatch.setenv('HOME', str(alias))
    response = asyncio.run(ob.serve_fs_dirs(SimpleNamespace(query={'path': '~/projects'})))
    result = json.loads(response.body)
    assert result['home'] == str(real_home.resolve())
    assert result['path'] == str(folder.resolve())


@pytest.mark.parametrize('width', [1600, 390])
def test_long_folder_only_compresses_the_folder_chip(tour_browser, width):
    client,evaluate=tour_browser
    client.call('Emulation.setDeviceMetricsOverride',width=width,height=850,deviceScaleFactor=1,mobile=False)
    home='/home/fixture'
    leaf='a-very-long-folder-name-that-cannot-normally-fit-the-launch-row'
    path=home+'/projects/lab/notes/archive/'+leaf
    model='claude-opus-5-5-20261120'
    data=dict(home=home,path=path,model=model)
    result=evaluate('''(async()=>{
      const data=DATA;
      const catalog={providers:[{id:'claude',program:'claude-code',
        models:[{id:data.model}],efforts:['low','medium','high','xhigh','max'],effort_default:'high'}],
        naming:{adjectives:['ResourcefulThoughtful'],scientists:['Leeuwenhoek']},dirs:[{path:data.path}]};
      const original=window.fetch;
      window.fetch=async url=>({ok:true,json:async()=>url.startsWith('/telemetry/fs/dirs')
        ?{path:url.includes('path=~')?data.home:data.path,home:data.home,dirs:[]}:catalog});
      const modelChip=()=>spawnModelButton.getBoundingClientRect();
      const folderLabel=document.getElementById('spawnDirSelected');
      try{
        openSpawnModal();await loadSpawnCatalog();await new Promise(resolve=>setTimeout(resolve,550));
        selScientist='Leeuwenhoek';spawnAdjective.value='ResourcefulThoughtful';
        spawnRole.value='Release engineering';updateNameCard();
        const long={label:folderLabel.textContent,title:spawnDirButton.title,payload:spawnPayloadFromForm(),
          modelWidth:modelChip().width,folderShortened:folderLabel.scrollWidth>folderLabel.clientWidth,
          modelFits:spawnModelLabel.scrollWidth<=spawnModelLabel.clientWidth&&
            spawnPips.getBoundingClientRect().right<=modelChip().right,
          pips:spawnPips.querySelectorAll('i').length,model:spawnModelLabel.textContent,
          modelTitle:spawnModelButton.title,modelOnscreen:modelChip().right<=spawnLauncher.getBoundingClientRect().right};
        await browseDir('~');
        return {long,home:{label:folderLabel.textContent,title:spawnDirButton.title,modelWidth:modelChip().width},
          generic:compactSpawnModelLabel('vendor/Qwen3.8-Flash-Next-IQ3_XXS')};
      }finally{window.fetch=original;}
    })()'''.replace('DATA',json.dumps(data)))
    assert result['long']['label']==leaf and result['long']['title']==path
    payload=result['long']['payload']
    assert (payload['dir'],payload['model'],payload['effort'])==(path,model,'high')
    assert result['long']['model']=='opus-5-5' and model in result['long']['modelTitle']
    assert result['long']['folderShortened'] and result['long']['modelFits'] and result['long']['modelOnscreen']
    assert result['long']['pips']==5 and result['generic']=='Qwen3.8-Flas…XXS'
    assert result['home']==dict(label='~',title=home,modelWidth=result['long']['modelWidth'])
