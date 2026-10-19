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


def test_explicit_local_uses_resolved_model_and_unknown_keeps_an_empty_hexagon(tour_browser):
    _, evaluate = tour_browser
    cases = [
        dict(provider='local', program='codex', model='Qwen3-Coder-30B'),
        dict(provider='local', program='claude', model='display name', model_raw='deepseek-ai/DeepSeek-R1'),
        dict(provider='local', program='codex', model='custom-7b'),
        dict(provider=' LOCAL ', program='claude', model='DeepSeek display', model_raw='Qwen/Qwen3-8B-Q4_K_M'),
        dict(provider='local', program='codex', model='DeepSeek-R1-Distill-Qwen-7B'),
    ]
    actual = rendered_badges(evaluate, cases)
    for result, asset in zip(actual, ['qwen', 'deepseek', None, 'qwen', 'deepseek']):
        assert result['presentation']['local'] is True
        assert result['presentation']['compactText'] == ''
        assert 'local-provider-badge' in result['roster']
        for surface in ['mini', 'planet']:
            assert '<polygon ' in result[surface]
            assert '<circle ' not in result[surface]
            assert '<text ' not in result[surface]
        if asset:
            assert result['presentation']['provider']['asset'] == asset
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
