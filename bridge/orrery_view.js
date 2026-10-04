/* ── orrery view: real spawn + communication graph (rail + planetarium) ──
   Owns <svg id="orrery"> and its full-stage planetarium.
   Inputs (read-only):
     window.OC — { jumpToAgent, lineageHue, lineageParent, agents(),
                   mailBacklog() }
     document events:
       'oc:agents'  detail:{agents}    — every roster poll tick (~3s)
       'oc:mail'    detail:{messages}  — NEW mail since last tick (deduped)
   Colour stays reserved for spawn lineage; state/events use motion. */
(function(){
'use strict';
const OC=window.OC;
const miniSvg=document.getElementById('orrery');
if(!miniSvg||!OC)return;

const SVG_NS='http://www.w3.org/2000/svg';
const MINI={
  width:280,height:200,large:false,dynamic:false,
  xPadding:17,topPadding:31,bottomPadding:14,
  treePitchX:34,treePitchY:43,singlePitchX:35,singlePitchY:32,
  singleColumns:7,sectionGap:34,treeGapUnits:.55,promoteComms:true,
};
const PLANET={
  width:1000,height:620,large:true,dynamic:true,
  xPadding:64,topPadding:58,bottomPadding:74,
  treePitchX:112,treePitchY:122,singlePitchX:112,singlePitchY:100,
  singleColumns:8,sectionGap:128,treeGapUnits:.55,promoteComms:false,
};
const MAIL_EDGE_LIFETIME=90000;
const COMM_PROMOTION_HYSTERESIS=4000;
const MAX_COMETS=6;
const MOTION_STIFFNESS=150;
const MOTION_DAMPING=22;
const MOTION_SETTLE_DISTANCE=.1;
const MOTION_SETTLE_SPEED=.12;
const MOTION_SETTLE_FRAMES=4;
const reducedMotion=window.matchMedia&&
  window.matchMedia('(prefers-reduced-motion: reduce)');
let liveAgents=OC.agents()||[];
let miniPositions=new Map();
let planetPositions=new Map();
let planetarium=null;
let planetSvg=null;
let planetLastFocus=null;
let activeComets=0;
const commPairs=new Map();
let commRefreshTimer=null;
let motionFrameId=null;
let motionLastTime=null;
let miniMode=(OC.miniView&&OC.miniView().mode)==='network'?'network':'orrery';
let miniNetworkDepth=Number(OC.miniView&&OC.miniView().depth)||2;
let miniFocusName=OC.activeAgent&&OC.activeAgent()||'';

function svgEl(tag,attrs={}){
  const el=document.createElementNS(SVG_NS,tag);
  Object.entries(attrs).forEach(([key,value])=>el.setAttribute(key,value));
  return el;
}
function stateOf(agent){
  return String(agent.act_state||(agent.running?'work':'idle')).replaceAll('_',' ');
}
function roleOf(agent){
  return String(agent&&agent.annot&&agent.annot.role||'').trim();
}
function modelOf(agent){
  const raw=String(agent&&agent.model||agent&&agent.cmd||'agent').trim();
  const normalized=raw.toUpperCase();
  if(/^GPT-?5\.6/.test(normalized))return 'GPT 5.6';
  const claude=normalized.match(/^CLAUDE-(OPUS|FABLE|SONNET|HAIKU)-(\d+)(?:-(\d+))?/);
  if(claude)return `${claude[1]} ${claude[2]}${claude[3]?'.'+claude[3]:''}`;
  return normalized.replace(/[-_]/g,' ').replace(/\s+/g,' ').slice(0,22);
}
function stateGlyph(agent){
  const state=String(agent&&agent.act_state||'').toLowerCase();
  if(state==='question'||state==='ask_user_question')return '?';
  if(state==='ask'||agent&&agent.annot&&agent.annot.attention)return '!';
  return '';
}
function drawStateGlyph(target,agent,x,y,large){
  const glyph=stateGlyph(agent);if(!glyph)return;
  const radius=large?36:14,offset=large?31:13;
  const group=svgEl('g',{class:'orrery-state-glyph '+(glyph==='?'?'question':'attention')});
  group.appendChild(svgEl('circle',{class:'orrery-state-orbit',cx:x,cy:y,r:radius,pathLength:'100'}));
  const text=svgEl('text',{x:x+offset,y:y-offset+1,'text-anchor':'middle'});
  text.textContent=glyph;group.appendChild(text);target.appendChild(group);
}
function initials(name){
  const capitals=String(name).match(/[A-Z](?=[a-z]|$)/g);
  if(capitals&&capitals.length)return capitals.slice(0,2).join('');
  return String(name).trim().slice(0,2).toUpperCase()||'?';
}
function initialLetter(name){
  return String(name).trim().slice(0,1).toUpperCase()||'?';
}
function activateAgent(agent){
  document.dispatchEvent(new CustomEvent(
    'oc:filter-agent',{detail:{agent:agent.name}}));
  // The jump switches the stage BEHIND the overlay — close it so the
  // pane is actually revealed (2026-07-30 product decision).
  if(planetarium&&planetarium.classList.contains('on'))closePlanetarium();
  OC.jumpToAgent(agent.name);
}
function makeInteractive(group,agent){
  group.setAttribute('role','button');
  group.setAttribute('tabindex','0');
  const role=roleOf(agent),model=modelOf(agent);
  group.setAttribute('aria-label',`Jump to ${agent.name}, ${model}${role?`, ${role}`:''}, ${stateOf(agent)}`);
  group.addEventListener('click',()=>activateAgent(agent));
  group.addEventListener('keydown',event=>{
    if(event.key==='Enter'||event.key===' '){
      event.preventDefault();
      activateAgent(agent);
    }
  });
}

/* Build a live-only forest. Invalid/cyclic parent links are ignored so a stale
   graph cannot hide agents. Connected trees lead; true singletons form the
   compact grid that follows them. */
function buildForest(live){
  const byName=new Map();
  (live||[]).forEach(agent=>{
    if(agent&&agent.name&&!byName.has(agent.name))byName.set(agent.name,agent);
  });
  const names=[...byName.keys()].sort((a,b)=>a.localeCompare(b));
  const parentOf=new Map();
  names.forEach(child=>{
    const parent=OC.lineageParent.get(child);
    if(!parent||parent===child||!byName.has(parent))return;
    let cursor=parent;
    const seen=new Set([child]);
    while(parentOf.has(cursor)&&!seen.has(cursor)){
      seen.add(cursor);
      cursor=parentOf.get(cursor);
    }
    if(cursor===child||seen.has(cursor))return;
    parentOf.set(child,parent);
  });
  const children=new Map(names.map(name=>[name,[]]));
  parentOf.forEach((parent,child)=>children.get(parent).push(child));
  children.forEach(items=>items.sort((a,b)=>a.localeCompare(b)));
  const roots=names.filter(name=>!parentOf.has(name));
  return {
    byName,parentOf,children,
    trees:roots.filter(name=>children.get(name).length),
    singletons:roots.filter(name=>!children.get(name).length),
  };
}

function activePromotionPartners(forest,now=Date.now()){
  if(!forest||!forest.singletons.length)return new Map();
  const constellation=new Set();
  forest.byName.forEach((agent,name)=>{
    if(forest.parentOf.has(name)||(forest.children.get(name)||[]).length){
      constellation.add(name);
    }
  });
  if(!constellation.size)return new Map();
  const singletons=new Set(forest.singletons);
  const strongest=new Map();
  commPairs.forEach(pair=>{
    if(now-pair.ts>=MAIL_EDGE_LIFETIME+COMM_PROMOTION_HYSTERESIS)return;
    let singleton=null,partner=null;
    if(singletons.has(pair.a)&&constellation.has(pair.b)){
      singleton=pair.a;partner=pair.b;
    }else if(singletons.has(pair.b)&&constellation.has(pair.a)){
      singleton=pair.b;partner=pair.a;
    }
    if(!singleton)return;
    const previous=strongest.get(singleton);
    if(!previous||pair.ts>previous.ts||
       (pair.ts===previous.ts&&partner.localeCompare(previous.partner)<0)){
      strongest.set(singleton,{partner,ts:pair.ts});
    }
  });
  return new Map([...strongest].map(([name,value])=>[name,value.partner]));
}

function promotedPosition(name,partnerPosition,occupied,dimensions){
  const radius=dimensions.large?76:27;
  const angles=[0,Math.PI,-Math.PI/2,Math.PI/2,-Math.PI/4,Math.PI/4,
    -3*Math.PI/4,3*Math.PI/4];
  const seed=[...String(name)].reduce((sum,char)=>sum+char.codePointAt(0),0);
  const ordered=angles.map((_,index)=>angles[(index+seed)%angles.length]);
  let best=null;
  ordered.forEach((angle,index)=>{
    const x=partnerPosition.x+Math.cos(angle)*radius;
    const y=partnerPosition.y+Math.sin(angle)*radius;
    const edgeMargin=dimensions.large?38:14;
    if(x<edgeMargin||x>dimensions.width-edgeMargin||
       y<edgeMargin||y>dimensions.height-edgeMargin)return;
    const clearance=occupied.reduce((nearest,position)=>
      Math.min(nearest,Math.hypot(x-position.x,y-position.y)),Infinity);
    const candidate={x,y,score:clearance-index*.001};
    if(!best||candidate.score>best.score)best=candidate;
  });
  if(best)return best;
  return {
    x:Math.max(14,Math.min(dimensions.width-14,partnerPosition.x+radius)),
    y:Math.max(14,Math.min(dimensions.height-14,partnerPosition.y)),
  };
}

/* Shared forest layout. The rail compresses into its fixed 280×200 viewBox;
   the planetarium grows its coordinate space instead, preserving >=112 px
   horizontal pitch (comfortably above the 96 px label-clearance contract). */
function layoutAgents(live,dimensions){
  const forest=buildForest(live);
  const promotionPartners=dimensions.promoteComms
    ?activePromotionPartners(forest):new Map();
  const waitingSingletons=forest.singletons.filter(name=>
    !promotionPartners.has(name));
  const spanCache=new Map();
  function treeSpan(name){
    if(spanCache.has(name))return spanCache.get(name);
    const children=forest.children.get(name);
    const span=children.length
      ?children.reduce((sum,child)=>sum+treeSpan(child),0):1;
    spanCache.set(name,span);
    return span;
  }

  const rawTreePositions=new Map();
  let maxDepth=0;
  function placeTree(name,depth,start){
    maxDepth=Math.max(maxDepth,depth);
    const children=forest.children.get(name);
    let unitX=start+.5;
    if(children.length){
      let cursor=start;
      const childXs=[];
      children.forEach(child=>{
        placeTree(child,depth+1,cursor);
        childXs.push(rawTreePositions.get(child).unitX);
        cursor+=treeSpan(child);
      });
      unitX=(childXs[0]+childXs[childXs.length-1])/2;
    }
    rawTreePositions.set(name,{unitX,depth});
  }
  let treeCursor=0;
  forest.trees.forEach(root=>{
    placeTree(root,0,treeCursor);
    treeCursor+=treeSpan(root)+dimensions.treeGapUnits;
  });

  const rawXs=[...rawTreePositions.values()].map(item=>item.unitX);
  const rawMin=rawXs.length?Math.min(...rawXs):0;
  const rawMax=rawXs.length?Math.max(...rawXs):0;
  const rawTreeWidth=rawMax-rawMin;
  // Promotions leave a deterministic hole in the waiting grid. Keeping the
  // original grid dimensions/indices prevents one conversation from shifting
  // the spawn forest or every unrelated singleton.
  const singletonCount=forest.singletons.length;
  const singletonColumns=singletonCount
    ?Math.min(singletonCount,dimensions.singleColumns):0;
  const singletonRows=singletonCount
    ?Math.ceil(singletonCount/singletonColumns):0;
  const desiredTreeWidth=rawTreeWidth*dimensions.treePitchX;
  const desiredSingletonWidth=Math.max(
    0,(singletonColumns-1)*dimensions.singlePitchX);
  const desiredContentWidth=Math.max(desiredTreeWidth,desiredSingletonWidth);
  const width=dimensions.dynamic
    ?Math.max(dimensions.width,desiredContentWidth+dimensions.xPadding*2)
    :dimensions.width;
  const innerWidth=width-dimensions.xPadding*2;
  const treePitchX=rawTreeWidth
    ?(dimensions.dynamic
      ?dimensions.treePitchX
      :Math.min(dimensions.treePitchX,innerWidth/rawTreeWidth))
    :0;
  const treeWidth=rawTreeWidth*treePitchX;
  const treeLeft=(width-treeWidth)/2;
  const singletonWidth=(singletonColumns-1)*dimensions.singlePitchX;
  const singletonLeft=(width-singletonWidth)/2;

  const idealTreeHeight=rawTreePositions.size
    ?maxDepth*dimensions.treePitchY:0;
  const idealSingletonHeight=singletonRows
    ?(singletonRows-1)*dimensions.singlePitchY:0;
  const idealGap=rawTreePositions.size&&singletonCount
    ?dimensions.sectionGap:0;
  const idealContentHeight=idealTreeHeight+idealGap+idealSingletonHeight;
  const height=dimensions.dynamic
    ?Math.max(dimensions.height,
      idealContentHeight+dimensions.topPadding+dimensions.bottomPadding)
    :dimensions.height;
  const innerHeight=height-dimensions.topPadding-dimensions.bottomPadding;
  const verticalScale=!dimensions.dynamic&&idealContentHeight>innerHeight
    ?innerHeight/idealContentHeight:1;
  const treePitchY=dimensions.treePitchY*verticalScale;
  const singletonPitchY=dimensions.singlePitchY*verticalScale;
  const sectionGap=idealGap*verticalScale;
  const contentHeight=idealTreeHeight*verticalScale+
    sectionGap+idealSingletonHeight*verticalScale;
  const top=dimensions.topPadding+Math.max(0,(innerHeight-contentHeight)/2);
  const singletonTop=top+idealTreeHeight*verticalScale+sectionGap;

  const positions=new Map();
  rawTreePositions.forEach((raw,name)=>{
    const agent=forest.byName.get(name);
    positions.set(name,{
      x:treeLeft+(raw.unitX-rawMin)*treePitchX,
      y:top+raw.depth*treePitchY,
      agent,
      hue:OC.lineageHue.get(name)||'#7a8794',
      working:agent.act_state==='work',
    });
  });
  waitingSingletons.forEach(name=>{
    const agent=forest.byName.get(name);
    const index=forest.singletons.indexOf(name);
    const column=index%singletonColumns;
    const row=Math.floor(index/singletonColumns);
    positions.set(name,{
      x:singletonLeft+column*dimensions.singlePitchX,
      y:singletonTop+row*singletonPitchY,
      agent,
      hue:OC.lineageHue.get(name)||'#7a8794',
      working:agent.act_state==='work',
    });
  });
  const occupied=[...positions.values()];
  [...promotionPartners].sort(([a],[b])=>a.localeCompare(b))
    .forEach(([name,partner])=>{
      const agent=forest.byName.get(name);
      const partnerPosition=positions.get(partner);
      if(!agent||!partnerPosition)return;
      const target=promotedPosition(name,partnerPosition,occupied,{
        ...dimensions,width,height,
      });
      const position={
        x:target.x,y:target.y,agent,
        hue:OC.lineageHue.get(name)||'#7a8794',
        working:agent.act_state==='work',
        promoted:true,promotionPartner:partner,
      };
      positions.set(name,position);occupied.push(position);
    });
  return {
    width,height,positions,parentOf:forest.parentOf,
    trees:forest.trees,singletons:waitingSingletons,
    promotions:promotionPartners,
  };
}

/* The compact telemetry view is a bounded, undirected subgraph.  A hop is
   one lineage or still-live mail edge; once selected, every internal edge is
   retained by the normal spawn/mail layers below. */
function telemetryNetworkSubset(live,focus,depth,now=Date.now()){
  const byName=new Map((live||[]).filter(agent=>agent&&agent.name)
    .map(agent=>[agent.name,agent]));
  if(!focus||!byName.has(focus))return null;
  const adjacent=new Map([...byName.keys()].map(name=>[name,new Set()]));
  OC.lineageParent.forEach((parent,child)=>{
    if(!adjacent.has(parent)||!adjacent.has(child))return;
    adjacent.get(parent).add(child);adjacent.get(child).add(parent);
  });
  commPairs.forEach(pair=>{
    if(now-pair.ts>=MAIL_EDGE_LIFETIME||!adjacent.has(pair.a)||!adjacent.has(pair.b))return;
    adjacent.get(pair.a).add(pair.b);adjacent.get(pair.b).add(pair.a);
  });
  const visible=new Set([focus]);
  let frontier=[focus];
  for(let hop=0;hop<Math.max(1,Math.min(3,Number(depth)||2));hop++){
    const next=[];
    frontier.forEach(name=>(adjacent.get(name)||[]).forEach(other=>{
      if(visible.has(other))return;
      visible.add(other);next.push(other);
    }));
    frontier=next;
    if(!frontier.length)break;
  }
  return {byName,visible};
}
function telemetryMiniLayout(live,focus,depth,dimensions){
  const subset=telemetryNetworkSubset(live,focus,depth);
  if(!subset)return layoutAgents(live,dimensions);
  const names=[...subset.visible].sort((a,b)=>a.localeCompare(b));
  const others=names.filter(name=>name!==focus);
  const width=dimensions.width,height=dimensions.height;
  const centerX=width/2,centerY=height/2;
  const positions=new Map();
  const positionFor=(name,x,y,networkFocus=false)=>{
    const agent=subset.byName.get(name);
    positions.set(name,{x,y,agent,hue:OC.lineageHue.get(name)||'#7a8794',
      working:agent.act_state==='work',networkFocus});
  };
  positionFor(focus,centerX,centerY,true);
  const rx=dimensions.large?Math.min(330,width*.34):Math.min(102,width*.36);
  const ry=dimensions.large?Math.min(215,height*.34):Math.min(69,height*.34);
  others.forEach((name,index)=>{
    const angle=-Math.PI/2+(Math.PI*2*index)/Math.max(1,others.length);
    positionFor(name,centerX+Math.cos(angle)*rx,centerY+Math.sin(angle)*ry);
  });
  const parentOf=new Map();
  OC.lineageParent.forEach((parent,child)=>{
    if(positions.has(parent)&&positions.has(child))parentOf.set(child,parent);
  });
  return {width,height,positions,parentOf,trees:[],singletons:[],
    promotions:new Map(),networkFocus:focus};
}

function createMotionSurface(target,dimensions){
  return {
    target,dimensions,states:new Map(),positions:new Map(),nodes:new Map(),
    spawnEdges:[],initialized:false,active:false,settledFrames:0,
  };
}
const miniMotion=createMotionSurface(miniSvg,MINI);
let planetMotion=null;
miniPositions=miniMotion.positions;

function motionIsReduced(){
  return Boolean(reducedMotion&&reducedMotion.matches);
}
function newNodeStart(name,target,dimensions){
  const centerX=dimensions.width/2,centerY=dimensions.height/2;
  let dx=target.x-centerX,dy=target.y-centerY;
  let distance=Math.hypot(dx,dy);
  if(distance<1){
    const angle=[...String(name)].reduce((sum,char)=>
      sum+char.codePointAt(0),0)%360*Math.PI/180;
    dx=Math.cos(angle);dy=Math.sin(angle);distance=1;
  }
  const offset=dimensions.large?46:16;
  return {
    x:target.x+dx/distance*offset,
    y:target.y+dy/distance*offset,
  };
}
function prepareMotion(surface,layout){
  const instant=!surface.initialized||motionIsReduced();
  surface.layoutDimensions={
    ...surface.dimensions,width:layout.width,height:layout.height,
  };
  const seen=new Set();
  layout.positions.forEach((target,name)=>{
    seen.add(name);
    let state=surface.states.get(name);
    if(!state){
      const start=instant?target:newNodeStart(name,target,{
        ...surface.dimensions,width:layout.width,height:layout.height,
      });
      state={
        name,x:start.x,y:start.y,vx:0,vy:0,opacity:instant?1:0,
        targetOpacity:1,removing:false,
      };
      surface.states.set(name,state);
    }
    state.tx=target.x;state.ty=target.y;
    state.baseX=target.x;state.baseY=target.y;
    state.agent=target.agent;state.hue=target.hue;
    state.working=target.working;
    state.promoted=Boolean(target.promoted);
    state.promotionPartner=target.promotionPartner||null;
    state.targetOpacity=1;state.removing=false;
    if(instant){
      state.x=state.tx;state.y=state.ty;state.vx=0;state.vy=0;state.opacity=1;
    }
  });
  [...surface.states].forEach(([name,state])=>{
    if(seen.has(name))return;
    if(instant){surface.states.delete(name);return;}
    state.tx=state.x;state.ty=state.y;
    state.baseX=state.x;state.baseY=state.y;
    state.targetOpacity=0;state.removing=true;
  });
  surface.positions.clear();
  surface.states.forEach((state,name)=>surface.positions.set(name,state));
  surface.initialized=true;surface.settledFrames=0;
  surface.active=!instant&&[...surface.states.values()].some(state=>
    Math.hypot(state.tx-state.x,state.ty-state.y)>MOTION_SETTLE_DISTANCE||
    Math.hypot(state.vx,state.vy)>MOTION_SETTLE_SPEED||
    Math.abs(state.targetOpacity-state.opacity)>.006);
}
function updateSurfaceGeometry(surface){
  surface.states.forEach((state,name)=>{
    const node=surface.nodes.get(name);
    if(node){
      const dx=state.x-state.baseX,dy=state.y-state.baseY;
      if(Math.abs(dx)>.001||Math.abs(dy)>.001){
        node.setAttribute('transform',`translate(${dx} ${dy})`);
      }else node.removeAttribute('transform');
      node.style.opacity=String(Math.max(0,Math.min(1,state.opacity)));
    }
  });
  surface.spawnEdges.forEach(edge=>{
    const from=surface.states.get(edge.dataset.parent);
    const to=surface.states.get(edge.dataset.child);
    if(!from||!to)return;
    edge.setAttribute('x1',from.x);edge.setAttribute('y1',from.y);
    edge.setAttribute('x2',to.x);edge.setAttribute('y2',to.y);
    edge.style.opacity=String(Math.min(from.opacity,to.opacity));
  });
  const commLayer=commLayerOf(surface.target);
  if(commLayer){
    commLayer.querySelectorAll('.orrery-comm-edge').forEach(edge=>{
      const from=surface.states.get(edge.dataset.a);
      const to=surface.states.get(edge.dataset.b);
      if(!from||!to)return;
      const curve=commPathBetween(
        from,to,surface.layoutDimensions||surface.dimensions);
      edge.setAttribute('d',curve.d);
      const life=Number(edge.dataset.life||0);
      edge.setAttribute('stroke-opacity',
        (.58*life*Math.min(from.opacity,to.opacity)).toFixed(3));
    });
  }
}
function finishSurfaceMotion(surface){
  const removing=[];
  surface.states.forEach((state,name)=>{
    state.x=state.tx;state.y=state.ty;state.vx=0;state.vy=0;
    state.opacity=state.targetOpacity;
    if(state.removing)removing.push(name);
  });
  removing.forEach(name=>{
    const node=surface.nodes.get(name);if(node)node.remove();
    surface.nodes.delete(name);surface.states.delete(name);surface.positions.delete(name);
  });
  surface.active=false;surface.settledFrames=0;
  updateSurfaceGeometry(surface);
}
function stepSurfaceMotion(surface,dt){
  if(!surface.active)return false;
  let unsettled=false;
  surface.states.forEach(state=>{
    const ax=(state.tx-state.x)*MOTION_STIFFNESS-state.vx*MOTION_DAMPING;
    const ay=(state.ty-state.y)*MOTION_STIFFNESS-state.vy*MOTION_DAMPING;
    state.vx+=ax*dt;state.vy+=ay*dt;
    state.x+=state.vx*dt;state.y+=state.vy*dt;
    const alpha=1-Math.exp(-11*dt);
    state.opacity+=(state.targetOpacity-state.opacity)*alpha;
    const distance=Math.hypot(state.tx-state.x,state.ty-state.y);
    const speed=Math.hypot(state.vx,state.vy);
    if(distance>=MOTION_SETTLE_DISTANCE||speed>=MOTION_SETTLE_SPEED||
       Math.abs(state.targetOpacity-state.opacity)>=.006)unsettled=true;
  });
  updateSurfaceGeometry(surface);
  surface.settledFrames=unsettled?0:surface.settledFrames+1;
  if(surface.settledFrames>=MOTION_SETTLE_FRAMES){
    finishSurfaceMotion(surface);return false;
  }
  return true;
}
function motionSurfaces(){
  const surfaces=[miniMotion];
  if(planetMotion&&planetarium&&planetarium.classList.contains('on')){
    surfaces.push(planetMotion);
  }
  return surfaces;
}
function syncMotionLoop(){
  const active=motionSurfaces().some(surface=>surface.active);
  if(!active){
    if(motionFrameId!==null)cancelAnimationFrame(motionFrameId);
    motionFrameId=null;motionLastTime=null;return;
  }
  if(motionFrameId===null)motionFrameId=requestAnimationFrame(runMotionFrame);
}
function runMotionFrame(now){
  motionFrameId=null;
  const dt=motionLastTime===null?1/60:
    Math.max(1/240,Math.min(1/30,(now-motionLastTime)/1000));
  motionLastTime=now;
  motionSurfaces().forEach(surface=>stepSurfaceMotion(surface,dt));
  syncMotionLoop();
}

function drawSpawnEdges(target,layout,large){
  const layer=svgEl('g',{class:'orrery-spawn-layer'});
  layout.parentOf.forEach((parent,child)=>{
    const from=layout.positions.get(parent),to=layout.positions.get(child);
    if(!from||!to)return;
    layer.appendChild(svgEl('line',{
      class:'orrery-spawn-edge'+(large?' planet-edge':''),
      x1:from.x,y1:from.y,x2:to.x,y2:to.y,
      'data-parent':parent,'data-child':child,
    }));
  });
  target.appendChild(layer);
  return layer;
}

function drawMiniAgent(target,defs,position,index,dimensions){
  const {agent,x,y,hue,working}=position;
  const portraitRadius=8.5;
  const ringRadius=11;
  const clipId=`mini-portrait-${index}`;
  const clip=svgEl('clipPath',{id:clipId});
  clip.appendChild(svgEl('circle',{cx:x,cy:y,r:portraitRadius}));
  defs.appendChild(clip);
  const group=svgEl('g',{
    class:'orrery-agent mini-agent'+(working?' is-working':'')+(position.networkFocus?' is-network-focus':''),
    'data-agent':agent.name,
  });
  makeInteractive(group,agent);
  group.appendChild(svgEl('circle',{class:'orrery-hit',cx:x,cy:y,r:14}));
  group.appendChild(svgEl('circle',{
    class:'mini-portrait-fallback',cx:x,cy:y,r:portraitRadius,
  }));
  const fallback=svgEl('text',{
    class:'mini-initial',x,y:y+2.7,'text-anchor':'middle',
  });
  fallback.textContent=initialLetter(agent.name);
  group.appendChild(fallback);
  const image=svgEl('image',{
    class:'mini-portrait',
    x:x-portraitRadius,y:y-portraitRadius,
    width:portraitRadius*2,height:portraitRadius*2,
    href:'/telemetry/portrait?v=3&style=pixel&name='+encodeURIComponent(agent.name),
    'clip-path':`url(#${clipId})`,
    preserveAspectRatio:'xMidYMid slice',
    'aria-hidden':'true',
  });
  image.addEventListener('error',()=>image.classList.add('failed'));
  group.appendChild(image);
  // Neutral ring in the compact rail (2026-07-30 product decision): spawn edges already
  // tie families together at this scale — lineage hue stays in the dense
  // fullscreen views (planetarium / NETWORK) only.
  group.appendChild(svgEl('circle',{
    class:'mini-lineage-ring',cx:x,cy:y,r:ringRadius,
    stroke:'rgba(236,229,214,.30)',
  }));
  group.appendChild(svgEl('circle',{
    class:'orrery-motion-ring mini-motion-ring',cx:x,cy:y,r:ringRadius+2.7,
    pathLength:'100',
  }));
  // Last, so the portrait cannot bury it: SVG has no z-index — paint order is
  // DOM order. Drawn before the <image>, "someone is waiting on you" was
  // silently painted over by the face (2026-08-06).
  drawStateGlyph(group,agent,x,y,false);
  const rightSide=x<=dimensions.width/2;
  const below=y<28;
  const label=svgEl('text',{
    class:'orrery-hover-label',
    x:x+(rightSide?15:-15),
    y:y+(below?17:-13),
    'text-anchor':rightSide?'start':'end',
  });
  const role=roleOf(agent),model=modelOf(agent);
  label.textContent=`${agent.name}${role?` · ${role}`:''} · ${model}`;
  group.appendChild(label);
  target.appendChild(group);
  return group;
}

function drawPlanetAgent(target,defs,position,index){
  const {agent,x,y,hue,working}=position;
  const radius=28;
  const portraitRadius=24;
  const clipId=`planet-portrait-${index}`;
  const clip=svgEl('clipPath',{id:clipId});
  clip.appendChild(svgEl('circle',{cx:x,cy:y,r:portraitRadius}));
  defs.appendChild(clip);
  const group=svgEl('g',{
    class:'orrery-agent planet-agent'+(working?' is-working':''),
    'data-agent':agent.name,
  });
  makeInteractive(group,agent);
  const title=svgEl('title');
  const role=roleOf(agent),model=modelOf(agent);
  title.textContent=`${agent.name} · ${model}${role?` · ${role}`:''}`;
  group.appendChild(title);
  group.appendChild(svgEl('circle',{class:'orrery-hit',cx:x,cy:y,r:radius+8}));
  group.appendChild(svgEl('circle',{
    class:'planet-portrait-fallback',cx:x,cy:y,r:portraitRadius,
  }));
  const fallback=svgEl('text',{
    class:'planet-initials',x,y:y+6,'text-anchor':'middle',
  });
  fallback.textContent=initials(agent.name);
  group.appendChild(fallback);
  // Line art, not the photographs: at medallion size the greyscale portraits
  // read as smudges against the dark ground, and the whole point of the
  // disc is telling one agent from another at a glance (2026-08-25 maintainer).
  const image=svgEl('image',{
    class:'planet-portrait',
    x:x-portraitRadius,y:y-portraitRadius,
    width:portraitRadius*2,height:portraitRadius*2,
    href:'/telemetry/portrait?v=3&style=pixel&name='+encodeURIComponent(agent.name),
    'clip-path':`url(#${clipId})`,
    preserveAspectRatio:'xMidYMid slice',
    'aria-hidden':'true',
  });
  image.addEventListener('error',()=>image.classList.add('failed'));
  group.appendChild(image);
  group.appendChild(svgEl('circle',{
    class:'planet-lineage-ring',cx:x,cy:y,r:radius,
  }));
  group.appendChild(svgEl('circle',{
    class:'orrery-motion-ring planet-motion-ring',cx:x,cy:y,r:radius+5,
    pathLength:'100',
  }));
  // After the motion ring, not before: the rotating arc was painting over the
  // state orbit that sits just outside it.
  drawStateGlyph(group,agent,x,y,true);
  const name=svgEl('text',{
    class:'planet-agent-name',x,y:y+radius+19,'text-anchor':'middle',
  });
  name.textContent=agent.name;
  group.appendChild(name);
  if(role){
    const roleLabel=svgEl('text',{
      class:'planet-agent-role',x,y:y+radius+32,'text-anchor':'middle',
    });
    roleLabel.textContent=role;
    group.appendChild(roleLabel);
  }
  const modelLabel=svgEl('text',{
    class:'planet-agent-model',x,y:y-radius-10,'text-anchor':'middle',
  });
  modelLabel.textContent=model;
  group.appendChild(modelLabel);
  // state caption retired with the medallion language — working is the
  // amber arc, only ask (needs a human) earns a caption.
  if(stateOf(agent)==='ask'){
    const state=svgEl('text',{
      class:'planet-agent-state',x,y:y+radius+(role?44:33),'text-anchor':'middle',
    });
    state.textContent='ask';
    group.appendChild(state);
  }
  target.appendChild(group);
  return group;
}

function addExpandAffordance(target,dimensions,isOpen){
  const large=dimensions.large;
  const x=dimensions.width-(large?31:14);
  const y=large?31:14;
  const group=svgEl('g',{
    class:'orrery-expand',
    role:'button',
    tabindex:'0',
    'aria-label':isOpen?'Close planetarium':'Open planetarium',
  });
  group.appendChild(svgEl('rect',{
    x:x-(large?20:11),y:y-(large?20:10),
    width:large?40:22,height:large?40:20,rx:large?7:4,
  }));
  const glyph=svgEl('text',{
    x,y:y+(large?7:4),'text-anchor':'middle',
  });
  glyph.textContent='⤢';
  group.appendChild(glyph);
  const activate=event=>{
    event.preventDefault();
    event.stopPropagation();
    if(isOpen)closePlanetarium();
    else openPlanetarium();
  };
  group.addEventListener('click',activate);
  group.addEventListener('keydown',event=>{
    if(event.key==='Enter'||event.key===' ')activate(event);
  });
  target.appendChild(group);
}

function preservedFlights(target){
  return [...target.children].filter(child=>
    child.classList.contains('orrery-comet-flight'));
}
function renderMini(){
  const flights=preservedFlights(miniSvg);
  miniSvg.replaceChildren();
  const layout=miniMode==='network'
    ?telemetryMiniLayout(liveAgents,miniFocusName,miniNetworkDepth,MINI)
    :layoutAgents(liveAgents,MINI);
  prepareMotion(miniMotion,layout);
  miniSvg.setAttribute('viewBox',`0 0 ${MINI.width} ${MINI.height}`);
  miniSvg.classList.toggle('telemetry-network',Boolean(layout.networkFocus));
  miniSvg.setAttribute('aria-label',layout.networkFocus
    ?`Telemetry network for ${layout.networkFocus}, ${miniNetworkDepth} hops`
    :'Live agent spawn and communication graph');
  const defs=svgEl('defs');
  miniSvg.appendChild(defs);
  const spawnLayer=drawSpawnEdges(miniSvg,layout,false);
  miniSvg.appendChild(svgEl('g',{class:'orrery-comm-layer'}));
  const nodes=svgEl('g',{class:'orrery-node-layer'});
  let index=0;
  miniMotion.nodes.clear();
  miniMotion.states.forEach((state,name)=>{
    const group=drawMiniAgent(nodes,defs,{
      ...state,x:state.baseX,y:state.baseY,
    },index++,MINI);
    miniMotion.nodes.set(name,group);
  });
  miniSvg.appendChild(nodes);
  addExpandAffordance(miniSvg,MINI,false);
  flights.forEach(flight=>miniSvg.appendChild(flight));
  miniMotion.spawnEdges=[...spawnLayer.children];
  refreshCommEdges();
  updateSurfaceGeometry(miniMotion);
  syncMotionLoop();
}
function renderPlanetarium(){
  if(!planetSvg||!planetarium.classList.contains('on'))return;
  const flights=preservedFlights(planetSvg);
  planetSvg.replaceChildren();
  /* The planetarium is the forest — its own subtitle says so, and the reason
     to open it is to see who spawned whom. It used to follow the rail's view
     mode, which meant that in "telemetry network" mode it drew a ring around
     whichever agent was focused instead of the tree. With no focus yet, that
     path fell through to the tree (telemetryMiniLayout returns layoutAgents
     when the subset is empty), so a fresh window looked right and opening a
     single pane silently replaced the overview with a one-agent ring — and
     nothing put it back, because the focus never cleared.

     The ring answers "who is this agent talking to", which is a rail-sized
     question; the rail still asks it. Up here the answer wanted is the whole
     hierarchy, so draw that and nothing else. */
  const layout=layoutAgents(liveAgents,PLANET);
  prepareMotion(planetMotion,layout);
  planetSvg.setAttribute('viewBox',`0 0 ${layout.width} ${layout.height}`);
  planetSvg.classList.toggle('telemetry-network',Boolean(layout.networkFocus));
  const defs=svgEl('defs');
  planetSvg.appendChild(defs);
  const spawnLayer=drawSpawnEdges(planetSvg,layout,true);
  planetSvg.appendChild(svgEl('g',{class:'orrery-comm-layer'}));
  const nodes=svgEl('g',{class:'orrery-node-layer'});
  let index=0;
  planetMotion.nodes.clear();
  planetMotion.states.forEach((state,name)=>{
    const group=drawPlanetAgent(nodes,defs,{
      ...state,x:state.baseX,y:state.baseY,
    },index++);
    planetMotion.nodes.set(name,group);
  });
  planetSvg.appendChild(nodes);
  addExpandAffordance(
    planetSvg,{...PLANET,width:layout.width,height:layout.height},true);
  flights.forEach(flight=>planetSvg.appendChild(flight));
  planetMotion.spawnEdges=[...spawnLayer.children];
  refreshCommEdges();
  updateSurfaceGeometry(planetMotion);
  syncMotionLoop();
}

function ensurePlanetarium(){
  if(planetarium)return;
  planetarium=document.createElement('div');
  planetarium.className='overlay orrery-planetarium';
  planetarium.id='planetariumOverlay';
  planetarium.setAttribute('role','dialog');
  planetarium.setAttribute('aria-modal','true');
  planetarium.setAttribute('aria-labelledby','planetariumTitle');
  planetarium.setAttribute('aria-hidden','true');
  const panel=document.createElement('section');
  panel.className='planetarium-panel';
  const head=document.createElement('header');
  head.className='planetarium-head';
  const title=document.createElement('div');
  title.id='planetariumTitle';
  title.className='planetarium-title';
  title.textContent='Planetarium';
  const note=document.createElement('div');
  note.className='planetarium-note';
  note.textContent='SPAWN FOREST · LIVE MAIL (90 S)';
  const telemetry=document.createElement('button');
  telemetry.className='planetarium-telemetry';telemetry.type='button';
  telemetry.textContent='OPEN TELEMETRY ↗';
  telemetry.setAttribute('aria-label','Open the telemetry network dashboard');
  telemetry.addEventListener('click',()=>{
    // Keep the nested overlays ordered: reveal the telemetry workspace before
    // its open event reaches cockpit.html.
    closePlanetarium();
    document.dispatchEvent(new CustomEvent('oc:open-telemetry',{
      detail:{focus:OC.activeAgent&&OC.activeAgent()||miniFocusName||''},
    }));
  });
  head.append(title,note,telemetry);
  planetSvg=svgEl('svg',{
    class:'planetarium-svg',
    viewBox:`0 0 ${PLANET.width} ${PLANET.height}`,
    role:'group',
    'aria-label':'Live agent spawn and communication graph',
    tabindex:'-1',
  });
  planetMotion=createMotionSurface(planetSvg,PLANET);
  planetPositions=planetMotion.positions;
  panel.append(head,planetSvg);
  planetarium.appendChild(panel);
  planetarium.addEventListener('mousedown',event=>{
    if(event.target===planetarium)closePlanetarium();
  });
  document.body.appendChild(planetarium);
}
function openPlanetarium(){
  ensurePlanetarium();
  if(planetarium.classList.contains('on'))return;
  planetLastFocus=document.activeElement;
  planetarium.classList.add('on');
  planetarium.setAttribute('aria-hidden','false');
  renderPlanetarium();
  requestAnimationFrame(()=>planetSvg.focus());
}
function closePlanetarium(){
  if(!planetarium||!planetarium.classList.contains('on'))return;
  planetarium.classList.remove('on');
  planetarium.setAttribute('aria-hidden','true');
  if(planetMotion){
    planetMotion.active=false;planetMotion.initialized=false;
    planetMotion.states.clear();planetMotion.positions.clear();
    planetMotion.nodes.clear();planetMotion.spawnEdges=[];
  }
  syncMotionLoop();
  const restoreTarget=planetLastFocus&&planetLastFocus.isConnected&&
    planetLastFocus!==document.body
    ?planetLastFocus:miniSvg.querySelector('.orrery-expand');
  if(restoreTarget)restoreTarget.focus();
  document.dispatchEvent(new CustomEvent('oc:planetarium-closed'));
}

function recipientNames(message){
  if(message.recipient)return [typeof message.recipient==='string'
    ?message.recipient:message.recipient.name].filter(Boolean);
  if(!Array.isArray(message.recipients))return [];
  return message.recipients.map(recipient=>
    typeof recipient==='string'?recipient:recipient&&recipient.name).filter(Boolean);
}
function senderName(message){
  return typeof message.sender==='string'
    ?message.sender:message.sender&&message.sender.name;
}
function timestampMs(value){
  if(typeof value==='number'&&Number.isFinite(value)){
    return value>1e12?value:value*1000;
  }
  if(typeof value==='string'&&value.trim()){
    const numeric=Number(value);
    if(Number.isFinite(numeric))return numeric>1e12?numeric:numeric*1000;
    const parsed=Date.parse(value);
    if(Number.isFinite(parsed))return parsed;
  }
  return null;
}
function observedMailTime(message,serverNowMs){
  const sentAt=timestampMs(message.ts||message.created_ts);
  if(sentAt===null)return Date.now();
  if(serverNowMs!==null){
    const age=Math.max(0,serverNowMs-sentAt);
    return Date.now()-age;
  }
  return Math.min(Date.now(),sentAt);
}
function pairKey(a,b){
  return a.localeCompare(b)<=0?`${a}\u001f${b}`:`${b}\u001f${a}`;
}
function recordMessages(messages,serverNowMs=null){
  const now=Date.now();
  (messages||[]).forEach(message=>{
    const from=senderName(message);
    if(!from)return;
    const sentAt=observedMailTime(message,serverNowMs);
    if(now-sentAt>=MAIL_EDGE_LIFETIME)return;
    recipientNames(message).forEach(to=>{
      if(!to||to===from)return;
      const key=pairKey(from,to);
      const previous=commPairs.get(key);
      if(!previous||sentAt>previous.ts){
        const ordered=from.localeCompare(to)<=0?[from,to]:[to,from];
        commPairs.set(key,{a:ordered[0],b:ordered[1],ts:sentAt});
      }
    });
  });
}
function commLayerOf(target){
  return [...target.children].find(child=>
    child.classList.contains('orrery-comm-layer'));
}
function commPathBetween(from,to,dimensions){
  const dx=to.x-from.x,dy=to.y-from.y;
  const sameRow=Math.abs(dy)<=(dimensions.large?12:5);
  if(!sameRow){
    return {
      curved:false,d:`M ${from.x} ${from.y} L ${to.x} ${to.y}`,
      point:t=>({x:from.x+dx*t,y:from.y+dy*t}),
    };
  }
  const distance=Math.abs(dx);
  const depth=Math.min(
    dimensions.large?78:27,
    (dimensions.large?18:7)+distance*(dimensions.large?.17:.18));
  const height=dimensions.height;
  const margin=dimensions.large?42:15;
  const direction=Math.max(from.y,to.y)+depth>height-margin?-1:1;
  const cx=(from.x+to.x)/2;
  const cy=(from.y+to.y)/2+depth*direction;
  return {
    curved:true,d:`M ${from.x} ${from.y} Q ${cx} ${cy} ${to.x} ${to.y}`,
    point:t=>{
      const mt=1-t;
      return {
        x:mt*mt*from.x+2*mt*t*cx+t*t*to.x,
        y:mt*mt*from.y+2*mt*t*cy+t*t*to.y,
      };
    },
  };
}
/* A spawn always carries its task message, so a parent and its child are a
   mail pair by definition. Drawing both a spawn line and a mail curve for
   them puts two lines where there is one relationship. Hand the mail to the
   line that is already there — brighten it — and keep curves for pairs the
   lineage does not connect, where the curve is the only thing saying the two
   agents have anything to do with each other. */
function isLineagePair(a,b){
  const parent=(window.OC&&OC.lineageParent)||null;
  if(!parent)return false;
  return parent.get(a)===b||parent.get(b)===a;
}
function markLiveSpawnEdges(target,liveSet){
  if(!target)return;
  target.querySelectorAll('.orrery-spawn-edge').forEach(edge=>{
    edge.classList.toggle('mail-live',
      liveSet.has(pairKey(edge.dataset.parent,edge.dataset.child)));
  });
}
function renderCommLayer(target,positions,dimensions){
  const layer=target&&commLayerOf(target);
  if(!layer)return;
  layer.replaceChildren();
  const now=Date.now();
  const liveLineage=new Set();
  commPairs.forEach(pair=>{
    const from=positions.get(pair.a),to=positions.get(pair.b);
    if(!from||!to)return;
    const life=1-(now-pair.ts)/MAIL_EDGE_LIFETIME;
    if(life<=0)return;
    if(isLineagePair(pair.a,pair.b)){
      liveLineage.add(pairKey(pair.a,pair.b));
      return;
    }
    const curve=commPathBetween(from,to,dimensions);
    layer.appendChild(svgEl('path',{
      class:'orrery-comm-edge',
      d:curve.d,fill:'none',
      'stroke-opacity':(.58*life).toFixed(3),
      'data-a':pair.a,'data-b':pair.b,'data-life':life.toFixed(5),
    }));
  });
  markLiveSpawnEdges(target,liveLineage);
}
function refreshCommEdges(){
  const now=Date.now();
  let layoutChanged=false;
  commPairs.forEach((pair,key)=>{
    const expired=now-pair.ts>=
      MAIL_EDGE_LIFETIME+COMM_PROMOTION_HYSTERESIS;
    const absentFromLive=liveAgents.length&&
      (!liveAgents.some(agent=>agent.name===pair.a)||!liveAgents.some(agent=>agent.name===pair.b));
    if(expired||absentFromLive){commPairs.delete(key);layoutChanged=true;}
  });
  renderCommLayer(miniSvg,miniPositions,MINI);
  if(planetarium&&planetarium.classList.contains('on')){
    renderCommLayer(
      planetSvg,planetPositions,
      (planetMotion&&planetMotion.layoutDimensions)||PLANET);
  }
  scheduleCommRefresh();
  return layoutChanged;
}
function scheduleCommRefresh(){
  if(commRefreshTimer!==null){
    clearTimeout(commRefreshTimer);commRefreshTimer=null;
  }
  const now=Date.now();
  let delay=Infinity;
  commPairs.forEach(pair=>{
    const age=now-pair.ts;
    if(age<MAIL_EDGE_LIFETIME){
      delay=Math.min(delay,500,Math.max(16,MAIL_EDGE_LIFETIME-age));
    }else if(age<MAIL_EDGE_LIFETIME+COMM_PROMOTION_HYSTERESIS){
      delay=Math.min(delay,Math.max(
        16,MAIL_EDGE_LIFETIME+COMM_PROMOTION_HYSTERESIS-age));
    }
  });
  if(!Number.isFinite(delay))return;
  commRefreshTimer=setTimeout(()=>{
    commRefreshTimer=null;
    const layoutChanged=refreshCommEdges();
    if(layoutChanged){renderMini();renderPlanetarium();}
  },delay);
}
async function seedRecentMail(){
  try{
    const data=await (await fetch(
      '/telemetry/mail/recent?limit=40',{cache:'no-store'})).json();
    if(data&&data.ok){
      recordMessages(data.messages,timestampMs(data.now));
      renderMini();
      renderPlanetarium();
    }
  }catch(error){/* live oc:mail still keeps the graph current */}
}

function subjectLabel(subject){
  const characters=[...String(subject||'')];
  return characters.length<=40
    ?characters.join('')
    :characters.slice(0,39).join('')+'…';
}
function animateComet(target,positions,fromName,toName,message,large){
  const from=positions.get(fromName),to=positions.get(toName);
  if(!from||!to||motionIsReduced())return Promise.resolve();
  const important=/^(high|urgent)$/i.test(message.importance||'');
  const flight=svgEl('g',{
    class:'orrery-comet-flight'+(important?' important':''),
  });
  const tail=svgEl('ellipse',{class:'orrery-comet-tail',cx:large?-16:-7,cy:0,
    rx:large?20:9,ry:large?3.2:1.45});
  const halo=svgEl('circle',{class:'orrery-comet-halo',cx:0,cy:0,r:large?10:4.8});
  const head=svgEl('circle',{class:'orrery-comet',cx:0,cy:0,r:large?(important?6:4.5):(important?2.9:2.1)});
  flight.append(tail,halo,head);
  if(large){
    const label=svgEl('text',{
      class:'orrery-comet-label',x:10,y:-8,
    });
    /* textContent is the escape boundary for untrusted mail subjects. */
    label.textContent=subjectLabel(message.subject);
    flight.appendChild(label);
  }
  target.appendChild(flight);
  const duration=700;
  return new Promise(resolve=>{
    let started=null;
    function frame(now){
      if(started===null)started=now;
      const progress=Math.min(1,(now-started)/duration);
      const eased=progress<.5
        ?4*progress*progress*progress
        :1-Math.pow(-2*progress+2,3)/2;
      const point=commPathBetween(
        from,to,large&&planetMotion
          ?planetMotion.layoutDimensions||PLANET:MINI).point(eased);
      const envelope=cometEnvelope(progress);
      const angle=Math.atan2(to.y-from.y,to.x-from.x)*180/Math.PI;
      flight.setAttribute('transform',`translate(${point.x} ${point.y}) scale(${envelope.scale})`);
      flight.style.opacity=String(envelope.opacity);
      tail.setAttribute('transform',`rotate(${angle})`);
      tail.style.opacity=String(envelope.tailOpacity);
      if(progress<1)requestAnimationFrame(frame);
      else{flight.remove();resolve();}
    }
    requestAnimationFrame(frame);
  });
}
function cometEnvelope(t){
  t=Math.max(0,Math.min(1,t));
  const smooth=x=>x*x*(3-2*x);
  const opacity=smooth(Math.min(1,t/.15))*(1-smooth(Math.max(0,(t-.82)/.18)));
  return {opacity,scale:t<=.5?1+.6*smooth(t/.5):1.6-.8*smooth((t-.5)/.5),
    tailOpacity:opacity*(.2+.8*Math.sin(Math.PI*t))};
}
function launchComet(message,toName){
  const fromName=senderName(message);
  if(!fromName||!miniPositions.has(fromName)||!miniPositions.has(toName))return;
  if(activeComets>=MAX_COMETS)return;
  activeComets+=1;
  const animations=[
    animateComet(miniSvg,miniPositions,fromName,toName,message,false),
  ];
  if(planetarium&&planetarium.classList.contains('on')&&
     planetPositions.has(fromName)&&planetPositions.has(toName)){
    animations.push(animateComet(
      planetSvg,planetPositions,fromName,toName,message,true));
  }
  Promise.all(animations).finally(()=>{activeComets=Math.max(0,activeComets-1);});
}
function receiveMail(messages){
  recordMessages(messages);
  renderMini();
  renderPlanetarium();
  const flights=[];
  (messages||[]).forEach(message=>{
    recipientNames(message).forEach(recipient=>flights.push([message,recipient]));
  });
  requestAnimationFrame(()=>{
    flights.forEach(([message,recipient])=>launchComet(message,recipient));
  });
}

document.addEventListener('oc:agents',event=>{
  liveAgents=(event.detail&&event.detail.agents)||[];
  renderMini();
  renderPlanetarium();
});
document.addEventListener('oc:mail',event=>
  receiveMail(event.detail&&event.detail.messages));
document.addEventListener('oc:focus-agent',event=>{
  miniFocusName=event.detail&&event.detail.name||'';
  if(miniMode==='network')renderMini();
});
document.addEventListener('oc:mini-view',event=>{
  const detail=event.detail||{};
  miniMode=detail.mode==='network'?'network':'orrery';
  miniNetworkDepth=[1,2,3].includes(Number(detail.depth))?Number(detail.depth):2;
  miniFocusName=OC.activeAgent&&OC.activeAgent()||miniFocusName;
  renderMini();
});
window.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&planetarium&&planetarium.classList.contains('on')){
    event.preventDefault();
    event.stopImmediatePropagation();
    closePlanetarium();
  }
},true);

/* The planetarium was only reachable from a bare ⤢ glyph tucked into the
   corner of the rail, which is not a legible way to say "show me the whole
   forest" — the lineage view is the thing people actually want back once a
   pane is open, and they could not find their way to it. Expose it so the
   header can offer it by name. */
window.OrreryRail={openPlanetarium,closePlanetarium,
  planetariumOpen:()=>Boolean(planetarium&&planetarium.classList.contains('on'))};

recordMessages(OC.mailBacklog&&OC.mailBacklog());
renderMini();
seedRecentMail();
})();
