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


def test_separate_window_selection_does_not_mark_the_external_session(mini_browser):
    _, evaluate = mini_browser
    assert evaluate("""(()=>{
      takeSessionOut('Helper');
      registerPaneWindow('Helper',{kind:'window',win:{closed:false,focus(){}}});
      jumpToAgent('Helper');
      // On this master, focusing another window leaves the center pane intact.
      return {selected:SELECTED,active:OC.activeAgent(),roster:selectedAgent};
    })()""".replace('SELECTED', SELECTED)) == {
        'selected': ['Pilot'], 'active': 'Pilot', 'roster': 'Helper'}


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
