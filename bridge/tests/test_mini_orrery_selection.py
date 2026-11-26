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
    for _ in range(100):
        if evaluate("Boolean(window.OrreryRail&&document.querySelector('#mail .mailview-list'))"):
            break
        time.sleep(.02)
    else:
        pytest.fail('mini graph and mail view did not mount')
    evaluate("""(()=>{
      // The second CDP worker can foreground another tab during a history poll.
      Object.defineProperty(document,'hidden',{value:false});
      document.querySelectorAll('.flight-close').forEach(e=>e.click());
      localStorage.setItem('oc-mini-mail-graph','1');
      document.dispatchEvent(new CustomEvent('oc:prefs-changed',{detail:{keys:['oc-mini-mail-graph']}}));
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


def test_mini_node_hover_docks_the_roster_card_without_covering_the_graph(mini_browser):
    client, evaluate = mini_browser
    before = evaluate("""(()=>{
      const agent=currentAgentNamed('Pilot');
      Object.assign(agent,{model_id:'fixture-model',harness_kind:'codex',cwd:'/fixture/release',
        annot:{role:'Release review'},permission_controls:{
          computer_use:{value:'view',can_change:true,action:'restart'},
          browser_use:{value:true,mode:'temporary',options:['off','temporary','personal'],
            can_change:true,action:'restart'}}});
      permissionApi=55;permissionApiCheckedAt=performance.now();
      tileFor(agent);tiles.get('Pilot').dispatchEvent(new MouseEvent('mouseenter'));
      const graph=document.getElementById('miniGraphViewport');
      graph.querySelector('.mini-graph-zoom button:last-child').click();
      const node=graph.querySelector('[data-agent="Pilot"]');
      node.scrollIntoView({block:'nearest',inline:'nearest'});
      window.fixtureDetail=agentDetail;
      const {x,y,width,height}=node.querySelector('.orrery-hit').getBoundingClientRect();
      return {card:agentDetail.innerHTML,graph:graph.getBoundingClientRect().toJSON(),
        zoomed:graph.querySelector('svg.miniorrery').clientHeight>graph.clientHeight,
        x:x+width/2,y:y+height/2};
    })()""")
    assert before['zoomed']
    for text in ('Pilot', 'fixture-model', 'Codex', 'Release review', '/fixture/release',
                 'data-computer="view"', 'Temporary Chrome'):
        assert text in before['card']
    client.call('Input.dispatchMouseEvent', type='mouseMoved', x=before['x'], y=before['y'])
    after = evaluate("""(()=>{
      const graph=document.getElementById('miniGraphViewport');
      const card=agentDetail.getBoundingClientRect();
      return {same:agentDetail===window.fixtureDetail,visible:!agentDetail.hidden,
        card:agentDetail.innerHTML,graph:graph.getBoundingClientRect().toJSON(),
        below:card.top>=graph.getBoundingClientRect().bottom,
        docked:agentDetail.previousElementSibling.id==='mailGraphDivider',
        point:{x:card.left+card.width/2,y:card.top+card.height/2}};
    })()""")
    assert after == {**after, 'same': True, 'visible': True, 'card': before['card'],
                     'graph': before['graph'], 'below': True, 'docked': True}
    client.call('Input.dispatchMouseEvent', type='mouseMoved', **after['point'])
    assert evaluate("""(async()=>{
      await new Promise(resolve=>setTimeout(resolve,200));
      return !agentDetail.hidden&&agentDetail.matches(':hover');
    })()""")
    client.call('Input.dispatchMouseEvent', type='mouseMoved', x=500, y=100)
    assert evaluate("""(async()=>{
      await new Promise(resolve=>setTimeout(resolve,200));return agentDetail.hidden;
    })()""")


def test_mini_node_keyboard_opens_shared_permissions_across_redraws(mini_browser):
    client, evaluate = mini_browser
    client.call('Emulation.setFocusEmulationEnabled', enabled=True)
    assert evaluate("""(async()=>{
      Object.assign(currentAgentNamed('Helper'),{harness_kind:'codex',permission_controls:{
        browser_use:{value:true,mode:'temporary',options:['off','temporary','personal'],
          can_change:true,action:'restart'}}});
      permissionApi=55;permissionApiCheckedAt=performance.now();
      const graph=document.getElementById('orrery');
      const node=()=>graph.querySelector('[data-agent="Helper"]');
      const key=(target,key)=>target.dispatchEvent(new KeyboardEvent('keydown',{key,bubbles:true}));
      const draw=()=>document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      const first=node();first.focus();
      const shown=!agentDetail.hidden;
      draw();
      const restored=node()!==first&&document.activeElement===node();
      key(node(),'F2');
      const button=agentDetail.querySelector('[data-browser]');draw();
      const retained=document.activeElement===button&&detailAnchor===node();
      button.click();
      const permission=permissionConfirm.open&&pendingPermissionChange.agent.name==='Helper'&&
        [...permissionBrowser.options].map(option=>option.value).join(',')===',off,personal';
      permissionConfirm.querySelector('[value="cancel"]').click();
      await new Promise(resolve=>setTimeout(resolve,0));
      button.focus();key(button,'Escape');
      draw();
      const dismissed=agentDetail.hidden&&document.activeElement===node();
      return {restored,retained,permission,dismissed,shown};
    })()""") == dict(restored=True, retained=True, permission=True, dismissed=True, shown=True)
    assert evaluate("""(async()=>{
      document.getElementById('mailGraphDivider').focus();
      document.querySelector('#orrery [data-agent="Helper"]').focus();
      if(agentDetail.hidden)return false;
      document.getElementById('mailGraphBtn').click();
      await Promise.resolve();return agentDetail.hidden;
    })()""")


def test_mini_hover_card_follows_the_node_and_card_not_the_graph_background(mini_browser):
    client, evaluate = mini_browser
    client.call('Emulation.setFocusEmulationEnabled', enabled=True)
    client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    blank = evaluate("""(()=>{
      const viewport=document.getElementById('miniGraphViewport');
      const b=viewport.getBoundingClientRect();
      for(let y=b.top+32;y<b.bottom-4;y+=12){
        for(let x=b.left+12;x<b.right-12;x+=12){
          const hit=document.elementFromPoint(x,y);
          if(viewport.contains(hit)&&!hit.closest('.mini-agent,.orrery-mail-edge,.mini-graph-zoom,.orrery-expand')){
            return {x,y};
          }
        }
      }
    })()""")
    assert blank
    visible_name = "agentDetail.hidden?null:agentDetail.querySelector('.agent-detail-name').textContent"

    def center(selector, part=None):
        return evaluate(f"""(()=>{{
          const element=document.querySelector({json.dumps(selector)});
          const sample={json.dumps(part)};
          const r=(sample?element.querySelector(sample):element).getBoundingClientRect();
          const x=r.x+r.width/2,y=r.y+r.height/2;
          return element.contains(document.elementFromPoint(x,y))?{{x,y}}:null;
        }})()""")

    def node(name):
        return center(f'#orrery [data-agent="{name}"]', '.orrery-hit')

    def move(point):
        assert point
        client.call('Input.dispatchMouseEvent', type='mouseMoved', **point)

    def name_after_grace():
        return evaluate(f"(async()=>{{await new Promise(resolve=>setTimeout(resolve,220));return {visible_name};}})()")

    move(node('Pilot'))
    assert evaluate(visible_name) == 'Pilot'
    move(blank)
    assert evaluate(visible_name) == 'Pilot'
    assert name_after_grace() is None

    move(node('Pilot'))
    assert evaluate(visible_name) == 'Pilot'
    card = center('#agentDetail')
    move(blank)
    move(card)
    assert evaluate("agentDetail.matches(':hover')"), card
    assert name_after_grace() == 'Pilot'
    move(blank)
    assert name_after_grace() is None

    move(node('Pilot'))
    move(node('Helper'))
    assert name_after_grace() == 'Helper'

    client.call('Input.dispatchMouseEvent', type='mousePressed', button='left', clickCount=1, **node('Helper'))
    assert evaluate("document.activeElement.matches('.mini-agent:not(:focus-visible)')")
    move(blank)
    client.call('Input.dispatchMouseEvent', type='mouseReleased', button='left', clickCount=1, **blank)
    assert name_after_grace() is None

    for event in ('keyDown', 'keyUp'):
        client.call('Input.dispatchKeyEvent', type=event, key='Tab', code='Tab', windowsVirtualKeyCode=9)
    evaluate("document.querySelector('#orrery [data-agent=Pilot]').focus()")
    move(node('Helper'))
    assert name_after_grace() == 'Pilot'
    move(blank)
    assert name_after_grace() == 'Pilot'
    evaluate("document.getElementById('mailGraphDivider').focus()")
    assert name_after_grace() is None


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
      return {bounds,viewport:rect(svg.parentElement),rail:rect(svg.closest('.col')),
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
def test_graph_captions_fit_dense_layout_and_keep_the_full_name(mini_browser, mode):
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
          full:long.getAttribute('aria-label').includes(longName)&&
            (selector==='#orrery'?long.getAttribute('aria-controls')==='agentDetail':
              long.querySelector(':scope > title').textContent.includes(longName)),
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


def test_mini_graph_keeps_mail_pairs_by_default_and_can_use_only_recent_links(mini_browser):
    client, evaluate = mini_browser
    client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    assert evaluate("document.getElementById('miniMailLinks').value") == 'keep'
    retained = evaluate("""(async()=>{
      const settings=document.getElementById('miniMailLinks'),graph=document.getElementById('orrery');
      window.setMailLinks=value=>{settings.value=value;settings.dispatchEvent(new Event('change'));};
      window.mailLinksState=()=>{
        const history=graph.querySelector('.orrery-history-edge[data-a=Pilot][data-b=Watcher]');
        return {watcher:!!graph.querySelector('[data-agent=Watcher]'),
          countWidth:history?.getAttribute('stroke-width')??null,
          live:!!graph.querySelector('.orrery-comm-edge[data-a=Pilot][data-b=Watcher]')};
      };
      setMailLinks('recent');
      const fetchOriginal=window.fetch;
      window.fetch=(url,...args)=>url==='/telemetry/graph?days=1'
        ? Promise.resolve(new Response(JSON.stringify({edges:[
            {source:'Pilot',target:'Watcher',kind:'to',count:2,last_ts:1},
            {source:'Watcher',target:'Pilot',kind:'cc',count:3,last_ts:2},
          ]})))
        : fetchOriginal(url,...args);
      setMiniViewMode('network');
      setMiniNetworkDepth(1);
      localStorage.removeItem('oc-mini-mail-links');
      document.dispatchEvent(new CustomEvent('oc:prefs-changed',{detail:{keys:['oc-mini-mail-links']}}));
      for(let i=0;i<60&&!mailLinksState().watcher;i++)await new Promise(resolve=>setTimeout(resolve,20));
      return mailLinksState();
    })()""")
    assert retained == {'watcher': True, 'countWidth': '3.58', 'live': False}
    assert evaluate("setMailLinks('recent');mailLinksState()") == {
        'watcher': False, 'countWidth': None, 'live': False}
    assert evaluate("localStorage.getItem('oc-mini-mail-links')") == 'recent'
    assert evaluate("""document.dispatchEvent(new CustomEvent('oc:mail',
      {detail:{messages:[{sender:'Pilot',recipient:'Watcher',ts:Date.now()}]}}));mailLinksState()""") == {
        'watcher': True, 'countWidth': None, 'live': True}
    assert evaluate("""const realNow=Date.now;Date.now=()=>realNow()+91000;
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      mailLinksState()""") == {'watcher': False, 'countWidth': None, 'live': False}
    assert evaluate("setMailLinks('keep');mailLinksState()") == retained


def test_graph_edge_mouse_and_keyboard_filter_mail_both_ways(mini_browser):
    client, evaluate = mini_browser
    client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    point = evaluate("""(async()=>{
      localStorage.setItem('oc-mini-graph-height','352');
      document.dispatchEvent(new CustomEvent('oc:prefs-changed',{detail:{keys:['oc-mini-graph-height']}}));
      const settings=document.getElementById('miniMailLinks');
      const setMailLinks=value=>{settings.value=value;settings.dispatchEvent(new Event('change'));};
      setMailLinks('recent');
      const originalFetch=window.fetch;
      window.loadedPairAgents=[];
      const item=(id,sender,recipients,subject)=>({id,sender,recipients,subject,ts:Date.now()/1000-200+id-301,
        thread_id:'shared-thread'});
      const first=item(301,'Helper',['Watcher','Pilot'],'First direction');
      const reverse=item(302,'Watcher',['Helper'],'Reverse direction');
      const unrelated=item(303,'Pilot',['Helper','Watcher'],'Two recipients, different sender');
      const copy=item(304,'Helper',[{name:'Watcher',kind:'cc'},'Pilot'],'Copied to Watcher');
      window.fetch=(url,...args)=>{
        if(url==='/telemetry/graph?days=1')return Promise.resolve(new Response(JSON.stringify({edges:[
          {source:'Helper',target:'Watcher',count:3}
        ]})));
        if(typeof url==='string'&&url.startsWith('/telemetry/mail/recent?limit=100&agent=')){
          const agent=new URL(url,location.href).searchParams.get('agent');
          loadedPairAgents.push(agent);
          return Promise.resolve(new Response(JSON.stringify({messages:agent==='Watcher'?[reverse]:[first,copy]})));
        }
        return originalFetch(url,...args);
      };
      window.edgeMail=messages=>document.dispatchEvent(new CustomEvent('oc:mail',{detail:{messages}}));
      edgeMail([first,unrelated,{id:305,sender:'Pilot',recipient:'Watcher',subject:'Recent',ts:Date.now()/1000}]);
      window.edgeChip=()=>document.querySelector('.mail-clear-filter span').textContent;
      window.edgeContents=()=>document.querySelector('#mail .mailcards').textContent;
      const graph=document.getElementById('orrery');
      setMailLinks('keep');
      for(let i=0;i<60&&!graph.querySelector('.orrery-history-edge');i++)await new Promise(r=>setTimeout(r,20));
      const edge=graph.querySelector('.orrery-history-edge');
      const length=edge.getTotalLength();
      const matrix=edge.getScreenCTM();
      for(const t of [.5,.4,.6,.3,.7]){
        const p=edge.getPointAtLength(length*t).matrixTransform(matrix);
        const q=edge.getPointAtLength(length*t+1).matrixTransform(matrix);
        const step=Math.hypot(q.x-p.x,q.y-p.y);
        const x=p.x-(q.y-p.y)*5/step,y=p.y+(q.x-p.x)*5/step;
        const hit=document.elementFromPoint(x,y);
        if(hit?.parentElement===edge.parentElement&&hit.classList.contains('orrery-mail-edge-hit'))return {x,y};
      }
      return null;
    })()""")
    assert point is not None
    xy = point
    client.call('Input.dispatchMouseEvent', type='mouseMoved', **xy)
    assert evaluate("getComputedStyle(document.querySelector('.orrery-history-edge')).strokeOpacity") == '0.56'
    client.call('Input.dispatchMouseEvent', type='mousePressed', button='left', clickCount=1, **xy)
    client.call('Input.dispatchMouseEvent', type='mouseReleased', button='left', clickCount=1, **xy)
    assert evaluate("edgeChip()") == 'Helper ↔ Watcher'
    assert evaluate("loadedPairAgents.slice().sort()") == ['Helper', 'Watcher']
    contents = evaluate("""(async()=>{
      const complete=()=>['First direction','Reverse direction','Copied to Watcher'].every(s=>edgeContents().includes(s));
      for(let i=0;i<60&&!complete();i++)await new Promise(r=>setTimeout(r,20));
      return edgeContents();
    })()""")
    assert all(subject in contents for subject in ('First direction', 'Reverse direction', 'Copied to Watcher')), contents
    assert 'Two recipients, different sender' not in contents
    evaluate("document.dispatchEvent(new CustomEvent('oc:focus-agent',{detail:{name:'Pilot'}}))")
    assert evaluate("edgeChip()") == 'Helper ↔ Watcher'
    evaluate("document.querySelector('.mail-clear-filter').click()")
    assert evaluate("document.querySelector('.mail-filter-summary').hidden&&edgeContents().includes('Two recipients, different sender')")

    for kind, pair in [('spawn', 'Helper ↔ Pilot'), ('comm', 'Pilot ↔ Watcher')]:
        evaluate(f"""document.querySelector('#orrery .orrery-{kind}-edge').parentElement.focus();
          document.dispatchEvent(new CustomEvent('oc:agents',{{detail:{{agents:currentAgents}}}}))""")
        assert evaluate(f"document.activeElement.firstElementChild?.classList.contains('orrery-{kind}-edge')")
        client.call('Input.dispatchKeyEvent', type='keyDown', key='Enter', code='Enter', windowsVirtualKeyCode=13)
        client.call('Input.dispatchKeyEvent', type='keyUp', key='Enter', code='Enter', windowsVirtualKeyCode=13)
        assert evaluate('edgeChip()') == pair


@pytest.mark.parametrize('mode', ['network', 'orrery'])
def test_dense_mini_graph_keeps_names_readable_and_pans_the_whole_graph(mini_browser, mode):
    client, evaluate = mini_browser
    client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    result = evaluate("""(()=>{
      setMailPaneWidth(260,mailPaneBounds());
      setMiniViewMode(MODE);
      const svg=document.getElementById('orrery'),scroll=svg.parentElement;
      const names=['Pilot','Helper',...Array.from({length:30},(_,i)=>'FixtureAgent'+i)];
      currentAgents=names.map(name=>({name,provider:'openai'}));
      names.slice(1).forEach(name=>OC.lineageParent.set(name,'Pilot'));
      const refresh=()=>document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      refresh();
      const pilot=svg.querySelector('[data-agent=Pilot]'),name=pilot.querySelector('.orrery-caption-name');
      const nameSize=Number.parseFloat(getComputedStyle(name).fontSize)*pilot.getScreenCTM().a;
      const portrait=pilot.querySelector('.mini-portrait').getBoundingClientRect().width;
      const control=scroll.parentElement.querySelector('.orrery-expand');
      const inside=element=>{
        const r=element.getBoundingClientRect(),bounds=scroll.getBoundingClientRect();
        return r.left>=bounds.left&&r.right<=bounds.right&&r.top>=bounds.top&&r.bottom<=bounds.bottom;
      };
      const startVisible=inside(pilot);
      scroll.scrollLeft=scroll.scrollWidth;
      scroll.scrollTop=scroll.scrollHeight;
      const pan=[scroll.scrollLeft,scroll.scrollTop];
      const reached=[...svg.querySelectorAll('.mini-agent')].some(node=>node!==pilot&&inside(node));
      refresh();
      return {count:svg.querySelectorAll('.mini-agent').length,nameSize,portrait,startVisible,reached,pan,
        preserved:[scroll.scrollLeft,scroll.scrollTop],expandVisible:inside(control),keyboard:scroll.tabIndex};
    })()""".replace('MODE', json.dumps(mode)))
    assert result['count'] == 32
    assert result['nameSize'] >= 11.6 and result['portrait'] >= 22, result
    assert result['startVisible'] and result['reached'] and result['expandVisible'], result
    assert result['pan'] != [0, 0] and result['pan'] == result['preserved'], result
    assert result['keyboard'] == 0


def test_dense_network_centers_focus_and_puts_frequent_mail_on_the_inner_ring(mini_browser):
    client, evaluate = mini_browser
    client.call('Emulation.setEmulatedMedia', features=[
        {'name': 'prefers-reduced-motion', 'value': 'reduce'}])
    result = evaluate("""(async()=>{
      setMailPaneWidth(380,mailPaneBounds());
      const settings=document.getElementById('miniMailLinks');
      settings.value='recent';settings.dispatchEvent(new Event('change'));
      const peers=Array.from({length:15},(_,i)=>'Peer'+String(i).padStart(2,'0'));
      currentAgents=['Pilot',...peers].map(name=>({name,provider:'openai'}));
      OC.lineageParent.clear();
      peers.forEach(name=>OC.lineageParent.set(name,'Pilot'));
      document.dispatchEvent(new CustomEvent('oc:agents',{detail:{agents:currentAgents}}));
      const originalFetch=window.fetch;
      window.fetch=(url,...args)=>url==='/telemetry/graph?days=1'?
        Promise.resolve(new Response(JSON.stringify({edges:[{source:'Pilot',target:'Peer14',count:50}]}))):
        originalFetch(url,...args);
      setMiniViewMode('network');
      settings.value='keep';settings.dispatchEvent(new Event('change'));
      const svg=document.getElementById('orrery');
      for(let i=0;i<60&&!svg.querySelector('.orrery-history-edge');i++)await new Promise(r=>setTimeout(r,20));
      if(!svg.querySelector('.orrery-history-edge'))throw new Error('Fixture Mail history did not load');
      const hit=name=>svg.querySelector(`[data-agent="${name}"] .orrery-hit`);
      const center=name=>{
        const el=hit(name);
        return [Number(el.getAttribute('cx')),Number(el.getAttribute('cy'))];
      };
      const [x,y]=center('Pilot'),box=svg.viewBox.baseVal;
      const radius=name=>{
        const [px,py]=center(name);
        return Math.hypot(px-x,py-y);
      };
      const [out,into]=document.querySelectorAll('.mini-graph-zoom button');
      const scale=()=>hit('Pilot').getScreenCTM().a;
      const normal=scale();into.click();const enlarged=scale();out.click();
      return {centered:x===box.width/2&&y===box.height/2,normal,enlarged,restored:scale(),
        inner:radius('Peer14'),outer:radius('Peer10'),rings:new Set(peers.map(name=>Math.round(radius(name)))).size};
    })()""")
    assert result['centered'] and result['rings'] == 2, result
    assert result['inner'] < result['outer'], result
    assert result['enlarged'] > result['normal'] == result['restored'], result


def graph_resize_metrics(evaluate):
    return evaluate("""(()=>{
      const graph=document.getElementById('orrery'),divider=document.getElementById('mailGraphDivider');
      const portrait=graph.querySelector('.orrery-hit');
      return {height:document.getElementById('miniGraphViewport').clientHeight,viewBox:graph.getAttribute('viewBox'),
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
            if evaluate("!window.graphResizeBeforeReload&&document.getElementById('miniGraphViewport')?.clientHeight===496"):
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
