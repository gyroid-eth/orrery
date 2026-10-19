"""Selection follows the actual center pane, independently of roster selection.

DOM regressions use the shared CDP browser and an isolated static server;
no production backend, tmux, or real agent is involved.
"""
import json
from pathlib import Path

import pytest

from test_cockpit_tour import tour_browser

BRIDGE = Path(__file__).resolve().parents[1]
SELECTED = "[...document.querySelectorAll('#orrery .mini-selection-ring')].map(e=>e.parentElement.dataset.agent)"


@pytest.fixture
def mini_browser(tour_browser):
    client, evaluate = tour_browser
    evaluate("""(()=>{
      document.querySelectorAll('.flight-close').forEach(e=>e.click());
      setMiniViewMode('orrery');
      const names=['Pilot','Helper','Watcher'];
      currentAgents=names.map(name=>({name,category:'agent',running:true,
        act_state:'work',provider:'openai',model:'sol'}));
      OC.lineageParent.clear();OC.lineageParent.set('Helper','Pilot');
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      handleSessions(names.map(session=>({session,windows:1})));
      ['Pilot','Helper'].forEach((session,i)=>resetSession({session,panes:[{
        paneId:'%'+(i+1),windowId:'@'+(i+1),sessionId:'$'+(i+1),
        windowIndex:'0',paneIndex:'0',width:100,height:30,active:true,
        windowName:'fixture',currentCommand:'codex'}]}));
      focusSession('Pilot');
    })()""")
    yield client, evaluate


def test_selection_moves_synchronously_without_rebuilding_working_nodes(mini_browser):
    _, evaluate = mini_browser
    result = evaluate("""(()=>{
      const selected=()=>SELECTED;
      const before=selected();
      const node=document.querySelector('#orrery [data-agent="Pilot"]');
      const arc=node.querySelector('.orrery-motion-ring');
      focusSession('Helper');
      const after=selected();
      return {before,after,active:OC.activeAgent(),
        sameNode:node===document.querySelector('#orrery [data-agent="Pilot"]'),
        sameArc:arc===node.querySelector('.orrery-motion-ring')};
    })()""".replace('SELECTED', SELECTED))
    assert result == {'before': ['Pilot'], 'after': ['Helper'], 'active': 'Helper',
                      'sameNode': True, 'sameArc': True}


def test_split_uses_the_focused_pane_and_clears_for_a_pending_cell(mini_browser):
    _, evaluate = mini_browser
    assert evaluate("""(()=>{
      const selected=()=>SELECTED;
      replaceSplitSessions(['Pilot','Helper','Watcher']);
      focusSplitSession('Pilot');const first=selected();
      focusSplitSession('Helper');const second=selected();
      focusSplitSession('Watcher');
      return {first,second,pending:selected(),active:OC.activeAgent()};
    })()""".replace('SELECTED', SELECTED)) == {
        'first': ['Pilot'], 'second': ['Helper'], 'pending': [], 'active': None}


def test_removing_the_last_center_pane_clears_selection(mini_browser):
    _, evaluate = mini_browser
    assert evaluate("""(()=>{
      // The current window-popout path removes center panes this way.
      takeSessionOut('Helper');takeSessionOut('Pilot');
      registerPaneWindow('Pilot',{kind:'window',win:null});
      return {selected:SELECTED,active:OC.activeAgent()};
    })()""".replace('SELECTED', SELECTED)) == {'selected': [], 'active': None}


def test_terminal_less_roster_selection_does_not_keep_the_old_ring(mini_browser):
    _, evaluate = mini_browser
    assert evaluate("""(()=>{
      currentAgents.push({name:'Desktop',cmd:'codex-app',category:'agent',running:true});
      jumpToAgent('Desktop');
      return {selected:SELECTED,active:OC.activeAgent(),name:scrName.textContent};
    })()""".replace('SELECTED', SELECTED)) == {
        'selected': [], 'active': None, 'name': 'Desktop'}


def test_roster_refresh_preserves_the_actual_center_selection(mini_browser):
    _, evaluate = mini_browser
    assert evaluate("""(()=>{
      focusSession('Helper');selectAgent('Watcher');
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      return {selected:SELECTED,active:OC.activeAgent(),roster:selectedAgent};
    })()""".replace('SELECTED', SELECTED)) == {
        'selected': ['Helper'], 'active': 'Helper', 'roster': 'Watcher'}


def test_separate_window_selection_clears_the_center_ring_and_local_focus_restores_it(mini_browser):
    _, evaluate = mini_browser
    assert evaluate("""(()=>{
      takeSessionOut('Helper');
      registerPaneWindow('Helper',{kind:'window',win:{closed:false,focus(){}}});
      jumpToAgent('Helper');
      const external={selected:SELECTED,active:OC.activeAgent(),roster:selectedAgent,
        visible:document.querySelectorAll('#termstage .termhost.on').length};
      focusSession('Pilot');
      return {external,restored:SELECTED,active:OC.activeAgent()};
    })()""".replace('SELECTED', SELECTED)) == {
        'external': {'selected': [], 'active': None, 'roster': 'Helper', 'visible': 0},
        'restored': ['Pilot'], 'active': 'Pilot'}


def test_network_and_planetarium_do_not_get_the_selection_ring(mini_browser):
    _, evaluate = mini_browser
    assert evaluate("""(()=>{
      setMiniViewMode('network');const network=SELECTED;
      OrreryRail.openPlanetarium();
      const planet=document.querySelectorAll('.planetarium-svg .mini-selection-ring').length;
      const planetNodes=document.querySelectorAll('.planetarium-svg .planet-agent').length;
      OrreryRail.closePlanetarium();setMiniViewMode('orrery');
      return {network,planet,planetNodes,orrery:SELECTED};
    })()""".replace('SELECTED', SELECTED)) == {
        'network': [], 'planet': 0, 'planetNodes': 3, 'orrery': ['Pilot']}


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('reduced', [False, True])
def test_theme_static_ring_and_working_arc_coexist(mini_browser, theme, reduced):
    client, evaluate = mini_browser
    client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce' if reduced else 'no-preference'}])
    evaluate('OrreryColorTheme.setPreference(' + json.dumps(theme) + ')')
    result = evaluate("""(()=>{
      const group=document.querySelector('#orrery [data-agent="Pilot"]');
      const ring=group.querySelector('.mini-selection-ring'),arc=group.querySelector('.orrery-motion-ring');
      if(!ring)return null;
      const style=getComputedStyle(ring);
      return {selected:SELECTED,working:group.classList.contains('is-working'),
        stroke:style.stroke,width:style.strokeWidth,animation:style.animationName,
        animations:ring.getAnimations().length,radius:Number(ring.getAttribute('r')),
        arcRadius:Number(arc.getAttribute('r')),arcWidth:getComputedStyle(arc).strokeWidth,
        arcAnimation:getComputedStyle(arc).animationName,hit:style.pointerEvents};
    })()""".replace('SELECTED', SELECTED))
    assert result is not None
    assert result == {
        'selected': ['Pilot'], 'working': True,
        'stroke': 'rgb(236, 229, 214)' if theme == 'dark' else 'rgb(1, 1, 0)',
        'width': '0.75px', 'animation': 'none', 'animations': 0, 'radius': 19.5,
        'arcRadius': 13.7, 'arcWidth': '1.6px',
        'arcAnimation': 'none' if reduced else 'orrery-spin', 'hit': 'none'}


@pytest.mark.parametrize('shape', ['chain', 'fan-left', 'fan-right'])
@pytest.mark.parametrize('theme', ['dark', 'light'])
def test_deep_and_wide_layouts_keep_the_whole_selected_ring_visible(mini_browser, shape, theme):
    client, evaluate = mini_browser
    # Settle the layout immediately; this does not change node coordinates.
    client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    evaluate('OrreryColorTheme.setPreference(' + json.dumps(theme) + ')')
    result = evaluate("""(()=>{
      const shape=SHAPE;
      const names=shape==='chain'?['Pilot','StepTwo','StepThree','StepFour','Helper']:
        ['Pilot','Helper',...Array.from({length:10},(_,i)=>(shape==='fan-left'?'Z':'A')+i)];
      currentAgents=names.map(name=>({name,category:'agent',running:true,
        act_state:'work',provider:'openai',model:'sol'}));
      OC.lineageParent.clear();
      names.slice(1).forEach((name,i)=>OC.lineageParent.set(name,shape==='chain'?names[i]:'Pilot'));
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      focusSession('Helper');
      const svg=document.getElementById('orrery'),ring=svg.querySelector('.mini-selection-ring');
      const matrix=ring.getScreenCTM(),radius=Number(ring.getAttribute('r'))+
        parseFloat(getComputedStyle(ring).strokeWidth)/2;
      const center=new DOMPoint(Number(ring.getAttribute('cx')),Number(ring.getAttribute('cy'))).matrixTransform(matrix);
      const bounds={left:center.x-radius*matrix.a,right:center.x+radius*matrix.a,
        top:center.y-radius*matrix.d,bottom:center.y+radius*matrix.d};
      const rect=e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};};
      return {bounds,viewport:rect(svg),rail:rect(svg.closest('.col')),
        x:Number(ring.getAttribute('cx')),y:Number(ring.getAttribute('cy')),
        workRadius:Number(ring.parentElement.querySelector('.orrery-motion-ring').getAttribute('r'))};
    })()""".replace('SHAPE', json.dumps(shape)))
    for clip in ['viewport', 'rail']:
        for side in ['left', 'top']:
            assert result['bounds'][side] >= result[clip][side], (shape, theme, clip, result)
        for side in ['right', 'bottom']:
            assert result['bounds'][side] <= result[clip][side], (shape, theme, clip, result)
    assert result['workRadius'] == 13.7
    # Preserve the layout rather than moving edge nodes to fit the marker.
    assert (result['x'], result['y']) == {
        'chain': (140, 186), 'fan-left': (17, 130), 'fan-right': (263, 130)}[shape]


def test_orrery_model_labels_keep_the_raw_id_instead_of_shortening_it(mini_browser):
    _,evaluate=mini_browser
    result=evaluate("""(()=>{
      currentAgents[0].model='Friendly display';currentAgents[0].model_raw='gpt-fixture-long-model-id';
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      OrreryRail.openPlanetarium();
      return {mini:document.querySelector('#orrery [data-agent=Pilot]').getAttribute('aria-label'),
        planet:document.querySelector('.planetarium-svg [data-agent=Pilot]').getAttribute('aria-label')};
    })()""")
    assert 'gpt-fixture-long-model-id' in result['mini'] and 'gpt-fixture-long-model-id' in result['planet']
    assert 'Friendly display' not in str(result)
