"""Selection follows the actual center pane, independently of roster selection.

DOM regressions use the shared CDP browser and an isolated static server;
no production backend, tmux, or real agent is involved.
"""
import json
from pathlib import Path
import time

import pytest

from test_cockpit_tour import tour_browser

BRIDGE = Path(__file__).resolve().parents[1]
SELECTED = "[...document.querySelectorAll('#orrery .mini-selection-ring')].map(e=>e.parentElement.dataset.agent)"


@pytest.fixture
def mini_browser(tour_browser):
    client, evaluate = tour_browser
    evaluate("""(()=>{
      document.querySelectorAll('.flight-close').forEach(e=>e.click());
      document.getElementById('mailGraphBtn').click();
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
        centered:['cx','cy'].every(key=>ring.getAttribute(key)===ring.parentElement.querySelector('.orrery-hit').getAttribute(key)),
        workRadius:Number(ring.parentElement.querySelector('.orrery-motion-ring').getAttribute('r'))};
    })()""".replace('SHAPE', json.dumps(shape)))
    for clip in ['viewport', 'rail']:
        for side in ['left', 'top']:
            assert result['bounds'][side] >= result[clip][side], (shape, theme, clip, result)
        for side in ['right', 'bottom']:
            assert result['bounds'][side] <= result[clip][side], (shape, theme, clip, result)
    assert result['workRadius'] == 13.7
    assert result['centered']


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


@pytest.mark.parametrize('mode', ['orrery', 'network'])
def test_graph_captions_fit_dense_layout_and_keep_the_full_tooltip(mini_browser, mode):
    client, evaluate = mini_browser
    client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    result = evaluate("""(()=>{
      const longName='ASyntheticAgentWithAnEspeciallyLongName';
      const names=['Pilot',longName,...Array.from({length:14},(_,i)=>'FixtureAgent'+i)];
      currentAgents=names.map((name,i)=>({name,category:'agent',running:true,act_state:'work',
        provider:'openai',annot:i===0?{}:{role:'Fixture release review'}}));
      OC.lineageParent.clear();
      names.slice(1).forEach(name=>OC.lineageParent.set(name,'Pilot'));
      setMiniViewMode(MODE);
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      OrreryRail.openPlanetarium();
      const overlaps=(a,b)=>a.x<b.x+b.width-.1&&b.x<a.x+a.width-.1&&
        a.y<b.y+b.height-.1&&b.y<a.y+a.height-.1;
      return ['#orrery','.planetarium-svg'].map(selector=>{
        const svg=document.querySelector(selector),view=svg.viewBox.baseVal;
        const nodes=[...svg.querySelectorAll('.orrery-agent')];
        const boxes=nodes.map(node=>({caption:node.querySelector('foreignObject').getBBox(),
          portrait:node.querySelector('.orrery-hit').getBBox()}));
        const long=nodes.find(node=>node.dataset.agent===longName);
        const name=long.querySelector('.orrery-caption-name');
        const bounds=box=>box.x>=view.x&&box.y>=view.y&&box.x+box.width<=view.x+view.width+.1&&
          box.y+box.height<=view.y+view.height+.1;
        return {count:boxes.length,clear:boxes.every(({caption,portrait},i)=>bounds(caption)&&
          caption.y>portrait.y+portrait.height&&boxes.every((other,j)=>i===j||
            (!overlaps(caption,other.caption)&&!overlaps(caption,other.portrait)))),
          ellipsis:getComputedStyle(name).textOverflow==='ellipsis'&&name.scrollWidth>name.clientWidth,
          full:long.querySelector(':scope > title').textContent.includes(longName)&&
            long.getAttribute('aria-label').includes(longName),
          role:long.querySelector('.orrery-caption-role').textContent,
          noRole:!nodes.find(node=>node.dataset.agent==='Pilot').querySelector('.orrery-caption-role')};
      });
    })()""".replace('MODE', json.dumps(mode)))
    assert result == [dict(count=16, clear=True, ellipsis=True, full=True, role='Fixture release review', noRole=True)] * 2


def test_mail_edges_and_selected_routes_bend_only_around_a_portrait(mini_browser):
    client, evaluate = mini_browser
    client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    result = evaluate("""(()=>{
      OC.lineageParent.clear();
      currentAgents=['Alpha','Middle','Zulu'].map(name=>({name,provider:'openai'}));
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      const messages=['Middle','Zulu'].map(recipient=>({sender:'Alpha',recipient}));
      document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages}}));
      OrreryRail.openPlanetarium();
      const route=sender=>document.dispatchEvent(new CustomEvent('oc:mail-route',
        {detail:{sender,recipients:[sender==='Alpha'?'Zulu':'Alpha']}}));
      route('Alpha');
      const graphs=['#orrery','.planetarium-svg'].map(selector=>{
        const svg=document.querySelector(selector);
        const portrait=svg.querySelector('[data-agent=Middle] .orrery-hit');
        const x=Number(portrait.getAttribute('cx')),y=Number(portrait.getAttribute('cy'));
        const edge=name=>svg.querySelector('.orrery-comm-edge[data-a=Alpha][data-b='+name+']');
        const clear=edge('Middle').getAttribute('d'),blocked=edge('Zulu');
        const focus=()=>svg.querySelector('.orrery-mail-focus path');
        const length=blocked.getTotalLength();
        const clearance=Math.min(...Array.from({length:101},(_,i)=>{
          const p=blocked.getPointAtLength(length*i/100);
          return Math.hypot(x-p.x,y-p.y);
        }));
        const midpoint=path=>path.getPointAtLength(path.getTotalLength()/2);
        return {clear:clear.includes(' L '),bent:blocked.getAttribute('d').includes(' Q '),
          selectedMatches:focus().getAttribute('d')===blocked.getAttribute('d'),
          clearance,midpoint:midpoint(blocked),focus,midpointOf:midpoint};
      });
      route('Zulu');
      return graphs.map(({focus,midpointOf,midpoint,...rest})=>{
        const reverse=midpointOf(focus());
        return {...rest,reverseMatches:Math.hypot(midpoint.x-reverse.x,midpoint.y-reverse.y)<.01};
      });
    })()""")
    for graph, radius in zip(result, (14, 32), strict=True):
        assert graph['clear'] and graph['bent'], graph
        assert graph['selectedMatches'] and graph['reverseMatches'], graph
        assert graph['clearance'] >= radius, graph


def test_selected_parent_child_mail_overlays_the_spawn_line(mini_browser):
    client, evaluate = mini_browser
    client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    result = evaluate("""(()=>{
      const peers=Array.from('ABCDEFGH',letter=>'Peer'+letter);
      OC.lineageParent.clear();
      peers.forEach(name=>OC.lineageParent.set(name,'Pilot'));
      currentAgents=['Pilot',...peers].map(name=>({name,provider:'openai'}));
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      setMiniViewMode('network');
      OrreryRail.openPlanetarium();
      const show=(sender,recipient)=>document.dispatchEvent(new CustomEvent('oc:mail-route',
        {detail:{sender,recipients:[recipient]}}));
      show('PeerG','Pilot');
      const graphs=['#orrery','.planetarium-svg'].map(selector=>{
        const svg=document.querySelector(selector);
        const spawn=svg.querySelector('.orrery-spawn-edge[data-parent=Pilot][data-child=PeerG]');
        const [x1,y1,x2,y2]=['x1','y1','x2','y2'].map(key=>spawn.getAttribute(key));
        const d=svg.querySelector('.orrery-mail-focus path').getAttribute('d');
        return {horizontal:Math.abs(y1-y2)<.01,overlaid:d===`M ${x2} ${y2} L ${x1} ${y1}`};
      });
      // The same central portrait blocks a diagonal route in the radial rail.
      show('PeerB','PeerF');
      return {graphs,diagonal:document.querySelector('#orrery .orrery-mail-focus path').getAttribute('d')};
    })()""")
    assert result['graphs'] == [
        {'horizontal': True, 'overlaid': True}, {'horizontal': False, 'overlaid': True},
    ]
    assert ' Q ' in result['diagonal']


def graph_resize_metrics(evaluate):
    return evaluate("""(()=>{
      const graph=document.getElementById('orrery'),divider=document.getElementById('mailGraphDivider');
      const portrait=graph.querySelector('.orrery-hit');
      return {height:graph.clientHeight,viewBox:graph.getAttribute('viewBox'),
        portrait:portrait?.getBoundingClientRect().width||0,
        mail:document.getElementById('mail').clientHeight,
        min:Number(divider.getAttribute('aria-valuemin')),max:Number(divider.getAttribute('aria-valuemax')),
        now:Number(divider.getAttribute('aria-valuenow'))};
    })()""")


def test_mail_graph_divider_drag_reflows_the_live_svg_and_double_click_resets(mini_browser):
    client, evaluate = mini_browser
    before = graph_resize_metrics(evaluate)
    assert before['height'] == 200
    x, y = evaluate("""(()=>{
      const r=document.getElementById('mailGraphDivider').getBoundingClientRect();
      return [r.x+r.width/2,r.y+r.height/2];
    })()""")
    client.call('Input.dispatchMouseEvent', type='mousePressed', x=x, y=y,
                button='left', buttons=1, clickCount=1)
    client.call('Input.dispatchMouseEvent', type='mouseMoved', x=x, y=y+120, button='left', buttons=1)
    for _ in range(100):
        during = graph_resize_metrics(evaluate)
        if during['viewBox'] != before['viewBox'] and during['height'] == 320:
            break
        time.sleep(.025)
    else:
        pytest.fail(f'Graph did not reflow during drag: {before} → {during}')
    assert during['portrait'] > before['portrait']
    assert during['mail'] == before['mail'] - 120
    assert evaluate("localStorage.getItem('oc-mini-graph-height')") is None
    client.call('Input.dispatchMouseEvent', type='mouseReleased', x=x, y=y+120,
                button='left', clickCount=1)
    assert evaluate("localStorage.getItem('oc-mini-graph-height')") == '320'
    assert evaluate("document.activeElement.id") == 'mailGraphDivider'
    assert evaluate(SELECTED) == ['Pilot']

    for click_count in (1, 2):
        client.call('Input.dispatchMouseEvent', type='mousePressed', x=x, y=y+120,
                    button='left', buttons=1, clickCount=click_count)
        client.call('Input.dispatchMouseEvent', type='mouseReleased', x=x, y=y+120,
                    button='left', clickCount=click_count)
    assert graph_resize_metrics(evaluate)['height'] == 200
    assert evaluate("localStorage.getItem('oc-mini-graph-height')") == '200'
    assert evaluate("""(()=>{
      document.getElementById('mailGraphBtn').click();
      return getComputedStyle(document.getElementById('mailGraphDivider')).display;
    })()""") == 'none'


def test_mail_graph_keyboard_clamps_and_restores_height_after_reload(mini_browser):
    client, evaluate = mini_browser
    evaluate("document.getElementById('mailGraphDivider').focus()")

    def key(name, code, modifiers=0):
        for event in ('keyDown', 'keyUp'):
            client.call('Input.dispatchKeyEvent', type=event, key=name,
                        windowsVirtualKeyCode=code, modifiers=modifiers)

    key('Home', 36)
    smallest = graph_resize_metrics(evaluate)
    assert smallest['height'] == smallest['min'] == smallest['now'] == 120
    key('ArrowDown', 40, modifiers=8)
    assert graph_resize_metrics(evaluate)['height'] == 184
    key('End', 35)
    largest = graph_resize_metrics(evaluate)
    assert largest['height'] == largest['max'] == largest['now'] == 520
    key('ArrowUp', 38)
    assert graph_resize_metrics(evaluate)['height'] == 496
    assert evaluate("localStorage.getItem('oc-mini-graph-height')") == '496'
    evaluate('window.graphResizeBeforeReload=true')
    client.call('Page.reload', ignoreCache=True)
    for _ in range(100):
        try:
            if evaluate("!window.graphResizeBeforeReload&&document.getElementById('orrery')?.clientHeight===496"):
                break
        except RuntimeError as error:
            if 'Inspected target navigated or closed' not in str(error):
                raise
        time.sleep(.025)
    else:
        pytest.fail('Saved Mail graph height did not restore')
    assert graph_resize_metrics(evaluate)['height'] == 496
    client.call('Emulation.setDeviceMetricsOverride', width=1600, height=460,
                deviceScaleFactor=1, mobile=False)
    for _ in range(100):
        compact = graph_resize_metrics(evaluate)
        if compact['height'] < 496:
            break
        time.sleep(.025)
    else:
        pytest.fail('Mail graph height did not clamp to the shorter viewport')
    assert compact['height'] == compact['max'] == compact['now']
    assert compact['mail'] >= 140
    assert evaluate("localStorage.getItem('oc-mini-graph-height')") == '496'
    evaluate("document.getElementById('mailGraphDivider').focus()")
    key('Enter', 13)
    assert graph_resize_metrics(evaluate)['height'] == min(compact['max'], 200)
    assert evaluate("localStorage.getItem('oc-mini-graph-height')") == '200'
