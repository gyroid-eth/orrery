"""Local badges share maker resolution; cloud DOM stays byte-identical.

The cloud fixture was captured before introducing local badges. Only the SVG
seat translation is omitted: node placement animates independently of badges.
"""
import json
from pathlib import Path

from test_cockpit_tour import tour_browser

FIXTURE = Path(__file__).parent / 'fixtures' / 'provider_badge_cloud.json'
CLOUD_CASES = [
    dict(provider='anthropic', model='claude-demo'),
    dict(provider='openai', model='gpt-demo'),
    dict(provider='google', model='gemini-demo'),
    dict(provider='deepseek', model='deepseek-demo'),
    dict(provider='other', program='custom-cli', model='unknown'),
    dict(program='codex', model=''),
    dict(model='deepseek-r1'),
]


def rendered_badges(evaluate, cases):
    return evaluate("""(async()=>{
      document.querySelectorAll('.flight-close').forEach(e=>e.click());
      setMiniViewMode('orrery');
      // Static tour server omits cockpit-owned asset routes; isolate DOM painting
      // from image transport here. Asset loading is checked on the proxy fixture.
      document.addEventListener('error',e=>e.stopImmediatePropagation(),true);
      currentAgents=CASES.map((a,i)=>({...a,name:'Badge'+i,category:'agent',
        running:true,act_state:'wait'}));
      OC.lineageParent.clear();
      currentAgents.forEach(a=>tileFor(a));
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      OrreryRail.openPlanetarium();
      await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
      const svg=(selector,a)=>{
        const badge=document.querySelector(selector+' [data-agent="'+a.name+'"] .mini-provider-badge').cloneNode(true);
        badge.removeAttribute('transform');return badge.outerHTML;
      };
      return currentAgents.map(a=>{
        const tile=tiles.get(a.name);
        return {presentation:providerPresentation(a),
          roster:tile.querySelector('.provider-badge').outerHTML,
          pill:tile.querySelector('.pill.eng').outerHTML,
          mini:svg('#orrery',a),planet:svg('.planetarium-svg',a)};
      });
    })()""".replace('CASES', json.dumps(cases)))


def test_no_local_input_preserves_cloud_presentation_and_badge_dom(tour_browser):
    _, evaluate = tour_browser
    actual = rendered_badges(evaluate, CLOUD_CASES)
    assert actual == json.loads(FIXTURE.read_text())


def test_light_graph_uses_original_logo_artwork_and_readable_seats(tour_browser):
    _, evaluate = tour_browser
    rendered_badges(evaluate, [
        dict(provider='openai', model='gpt-demo'),
        dict(provider='local', model='glm-4.7'),
        dict(provider='local', model='inkling-2-mini'),
        dict(provider='other', program='custom-cli'),
    ])
    result = evaluate("""(()=>{
      function measure(theme){
        OrreryColorTheme.setPreference(theme);
        return ['#orrery','.planetarium-svg'].map(selector=>{
          const badges=[...document.querySelectorAll(selector+' .mini-provider-badge')];
          const badge=name=>badges.find(el=>el.parentElement.dataset.agent===name);
          const seat=name=>getComputedStyle(badge(name).querySelector('.mini-provider-seat')).fill;
          const fallback=getComputedStyle(badge('Badge3').querySelector('text')).fill;
          const filter=name=>getComputedStyle(badge(name).querySelector('image')).filter;
          return {filters:[filter('Badge0'),filter('Badge1')],fills:[seat('Badge0'),seat('Badge1')],
            empty:seat('Badge2'),fallbackSeat:seat('Badge3'),fallback};
        });
      }
      return {light:measure('light'),dark:measure('dark')};
    })()""")
    for light, dark in zip(result['light'], result['dark']):
        assert light['filters'] == dark['filters'] == ['none', 'none']
        assert light['fills'] == [light['fallback']] * 2
        assert light['empty'] == light['fallbackSeat'] != light['fallback']
        assert dark['fills'] == [dark['fallbackSeat']] * 2


def test_explicit_local_uses_resolved_model_and_unknown_keeps_an_empty_hexagon(tour_browser):
    _, evaluate = tour_browser
    cases = [
        dict(provider='local', program='codex', model='Qwen3-Coder-30B'),
        dict(provider='local', program='hermes', model='glm-5.3-flash'),
        dict(provider='local', program='hermes', model='facebook/xglm-7.5B'),
        dict(provider='local', program='hermes', model='chatglm3-6b'),
        dict(provider='local', program='hermes', model='zai-org/GLM-4.6'),
        dict(provider='strata', locality='local', program='dsh', model='display', model_raw='zai-org/GLM-5.3-Flash'),
        dict(provider='local', program='hermes', model='deepseek-v4.1-flash'),
        dict(provider='local', program='claude', model='display name', model_raw='deepseek-ai/DeepSeek-R1'),
        dict(provider='local', program='codex', model='custom-7b'),
        dict(provider=' LOCAL ', program='claude', model='DeepSeek display', model_raw='Qwen/Qwen3-8B-Q4_K_M'),
        dict(provider='local', program='codex', model='DeepSeek-R1-Distill-Qwen-7B'),
        dict(provider='strata', locality='local', program='dsh', model='Inkling 2 Mini', model_raw='inkling-2-mini'),
        dict(provider='local', program='hermes', model='thinkingmachines/Inkling-2-Mini'),
        dict(provider='local', program='hermes', model='custom-inkling-2-mini-alias'),
    ]
    actual = rendered_badges(evaluate, cases)
    expected = ['qwen', 'glm', None, None, 'glm', 'glm', 'deepseek', 'deepseek', None, 'qwen', 'deepseek',
                'thinking-machines', 'thinking-machines', None]
    for result, asset in zip(actual, expected, strict=True):
        assert result['presentation']['local'] is True
        assert result['presentation']['compactText'] == ''
        assert 'local-provider-badge' in result['roster']
        for surface in ['mini', 'planet']:
            assert '<polygon ' in result[surface]
            assert '<circle ' not in result[surface]
            assert '<text ' not in result[surface]
        if asset:
            assert result['presentation']['provider']['asset'] == asset
            if asset == 'glm':
                assert result['presentation']['text'] == 'GLM · Local'
            if asset == 'thinking-machines':
                assert result['presentation']['text'] == 'Thinking Machines Lab · Local'
            for surface in ['roster', 'mini', 'planet']:
                assert 'cockpit-assets/' + asset + '.svg' in result[surface]
        else:
            assert 'provider' not in result['presentation']
            assert 'src=' not in result['roster']
            assert '<image ' not in result['mini']
            assert '<image ' not in result['planet']


def test_reconciled_roster_clears_local_shape_and_stale_maker(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      const el=document.createElement('div');
      el.innerHTML='<span class="pill eng"></span><span class="provider-badge" hidden><img class="provider-logo" alt=""></span>';
      paintRosterProvider(el,{provider:'local',program:'codex',model:'Qwen3'});
      paintRosterProvider(el,{provider:'local',program:'codex',model:'custom-7b'});
      const empty={rim:el.querySelectorAll('polygon').length,src:el.querySelector('img').getAttribute('src'),
        hidden:el.querySelector('img').hidden,pill:el.querySelector('.pill').hidden};
      paintRosterProvider(el,{provider:'openai',model:'gpt-demo'});
      const cloud=el.querySelector('.provider-badge').outerHTML;
      return {empty,cloud};
    })()""")
    assert result['empty'] == dict(rim=1, src=None, hidden=True, pill=True)
    assert result['cloud'] == json.loads(FIXTURE.read_text())[1]['roster']


def test_strata_and_locality_metadata_use_the_resolved_local_maker(tour_browser):
    _, evaluate = tour_browser
    cases = [
        dict(provider='strata', locality='local', program='dsh', harness='dsh',
             model='Qwen 3.8 flash', model_raw='qwen3.8-flash-next-iq3_xxs'),
        dict(provider='strata', program='hermes', model='Qwen3'),
        dict(provider='custom', locality='local', program='dsh', model='Qwen3'),
        dict(provider=' STRATA ', locality=' LOCAL ', program='dsh',
             model='DeepSeek display', model_raw='Qwen/Qwen3-8B'),
        dict(provider='strata', locality='local', program='dsh',
             model='Qwen display', model_raw='deepseek-ai/DeepSeek-R1'),
        dict(provider='strata', locality='local', program='dsh', model='custom-7b'),
        dict(provider='custom', locality='local', program='hermes', model='custom-7b'),
    ]
    actual = rendered_badges(evaluate, cases)
    for result, asset in zip(actual, ['qwen', 'qwen', 'qwen', 'qwen', 'deepseek', None, None]):
        assert result['presentation']['local'] is True
        assert result['presentation']['compactText'] == ''
        assert 'local-provider-badge' in result['roster']
        assert 'local-provider-rim' in result['roster']
        for surface in ['mini', 'planet']:
            assert '<polygon ' in result[surface]
            assert '<circle ' not in result[surface]
            assert '<text ' not in result[surface]
        if asset:
            assert result['presentation']['provider']['asset'] == asset
            assert result['presentation']['text'].endswith(' · Local')
            for surface in ['roster', 'mini', 'planet']:
                assert 'cockpit-assets/' + asset + '.svg' in result[surface]
        else:
            assert result['presentation']['text'] == 'Unknown maker · Local'
            assert 'provider' not in result['presentation']
            assert 'src=' not in result['roster']
            assert '<image ' not in result['mini'] and '<image ' not in result['planet']


def test_strata_roster_reconciliation_clears_local_shape_and_stale_maker(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      const el=document.createElement('div');
      el.innerHTML='<span class="pill eng"></span><span class="provider-badge" hidden><img class="provider-logo" alt=""></span>';
      paintRosterProvider(el,{provider:'strata',locality:'local',program:'dsh',model_raw:'qwen3.8-flash-next-iq3_xxs'});
      const qwen={rim:el.querySelectorAll('polygon').length,src:el.querySelector('img').getAttribute('src')};
      paintRosterProvider(el,{provider:'strata',locality:'local',program:'dsh',model_raw:'custom-7b'});
      const empty={rim:el.querySelectorAll('polygon').length,src:el.querySelector('img').getAttribute('src'),
        hidden:el.querySelector('img').hidden,pill:el.querySelector('.pill').hidden};
      paintRosterProvider(el,{provider:'deepseek',locality:'cloud',program:'dsh',model:'deepseek-demo'});
      return {qwen,empty,cloud:el.querySelector('.provider-badge').outerHTML};
    })()""")
    assert result['qwen'] == dict(rim=1, src='cockpit-assets/qwen.svg')
    assert result['empty'] == dict(rim=1, src=None, hidden=True, pill=True)
    assert result['cloud'] == json.loads(FIXTURE.read_text())[3]['roster']


def test_picker_models_use_local_maker_badges(tour_browser):
    _, evaluate = tour_browser
    result = evaluate("""(()=>{
      document.querySelectorAll('.flight-close').forEach(e=>e.click());
      spawnCatalog={providers:[{id:'local-fixture',locality:'local',label:'Local fixture',
        models:[{id:'glm-5.3-flash'},{id:'deepseek-v4.1-flash'},{id:'inkling-2-mini'}],
        harnesses:[{id:'hermes',available:true,default:true}]}],naming:{},dirs:[]};
      selFamily='local';selProvider=null;selModel=null;selHarness=null;
      spawnModelSearch.value='';renderProviderTabs();
      return ['glm-5.3-flash','deepseek-v4.1-flash','inkling-2-mini'].map(model=>{
        modelChoices.querySelector('input[value="'+model+'"]').click();
        const badge=document.getElementById('spawnModelMark');
        return {model,title:badge.title,src:badge.querySelector('img').getAttribute('src')};
      });
    })()""")
    expected = [
        ('glm-5.3-flash', 'glm', 'GLM'),
        ('deepseek-v4.1-flash', 'deepseek', 'DeepSeek'),
        ('inkling-2-mini', 'thinking-machines', 'Thinking Machines Lab'),
    ]
    for row, (model, asset, maker) in zip(result, expected, strict=True):
        assert row['model'] == model
        assert row['title'] == maker + ' · Local'
        assert row['src'] == 'cockpit-assets/' + asset + '.svg'
