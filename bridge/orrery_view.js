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
const miniViewport=document.getElementById('miniGraphViewport');
const miniScroll=miniSvg.parentElement;
const miniExpand=miniViewport.querySelector('.mini-graph-expand');

const SVG_NS='http://www.w3.org/2000/svg';
const MINI={
  width:280,height:200,large:false,
  xPadding:34,topPadding:30,bottomPadding:38,
  treePitchX:66,treePitchY:64,singlePitchX:66,singlePitchY:64,
  singleColumns:5,sectionGap:64,treeGapUnits:.55,promoteComms:true,
  captionWidth:62,captionTop:15,captionHeight:20,nodeAbove:20,
};
const MINI_HEIGHT_KEY='oc-mini-graph-height';
// Keep about 12 px names on open, with room for wide names in the scene.
const MINI_PREFERRED_SCALE=1.3;
const MINI_MAX_CAPTION_WIDTH=112;
const miniCaptionMeasure=document.createElement('canvas').getContext('2d');
const MINI_MIN_HEIGHT=120;
const MINI_MAX_HEIGHT=520;
const MAIL_BELOW_GRAPH=160; // Leave room for the handle and at least several Mail rows.
const PLANET={
  width:1000,height:620,large:true,
  xPadding:64,topPadding:90,bottomPadding:80,
  treePitchX:112,treePitchY:122,singlePitchX:112,singlePitchY:122,
  singleColumns:8,sectionGap:128,treeGapUnits:.55,promoteComms:false,
  captionWidth:104,captionTop:37,captionHeight:34,nodeAbove:37,
};
const MAIL_EDGE_LIFETIME=90000;
const MAIL_HISTORY_REFRESH=30000;
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
let activeMailRoute=null;
const commPairs=new Map();
let historyPairs=new Map(),historyRequest=null,historyTimer=null;
let keepMailLinks=OC.miniView?.().mailLinks!=='recent';
let commRefreshTimer=null;
let motionFrameId=null;
let motionLastTime=null;
let miniMode=(OC.miniView&&OC.miniView().mode)==='network'?'network':'orrery';
let miniNetworkDepth=Number(OC.miniView&&OC.miniView().depth)||2;
let miniFocusName=OC.activeAgent&&OC.activeAgent()||'';
let miniWidth=MINI.width,miniHeight=MINI.height;
let miniOverflow=false;
const MINI_MAX_ZOOM=2.5;
let miniZoom=1,miniDefaultZoom=1,miniMaxZoom=MINI_MAX_ZOOM,miniZoomControls;
let miniViewAdjusted=false;
let miniHoveredAgent='',miniFocusedAgent='';

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
  return String(agent&&(agent.model_raw||agent.model||agent.cmd)||'agent').trim();
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

function captionClearance(dimensions){
  return [dimensions.captionWidth+4,dimensions.nodeAbove+dimensions.captionTop+dimensions.captionHeight+2];
}
function promotedPosition(name,partnerPosition,occupied,dimensions){
  const [horizontal,vertical]=captionClearance(dimensions);
  const angles=[0,Math.PI,-Math.PI/2,Math.PI/2,-Math.PI/4,Math.PI/4,
    -3*Math.PI/4,3*Math.PI/4];
  const seed=[...String(name)].reduce((sum,char)=>sum+char.codePointAt(0),0);
  const ordered=angles.map((_,index)=>angles[(index+seed)%angles.length]);
  let best=null;
  for(const angle of ordered){
    const x=partnerPosition.x+Math.cos(angle)*vertical;
    const y=partnerPosition.y+Math.sin(angle)*vertical;
    if(x<dimensions.xPadding||x>dimensions.width-dimensions.xPadding||
       y<dimensions.topPadding||y>dimensions.height-dimensions.bottomPadding)continue;
    let nearest=Infinity;
    for(const [other,position] of occupied){
      if(other===name)continue;
      const clearance=Math.max(Math.abs(x-position.x)/horizontal,Math.abs(y-position.y)/vertical);
      nearest=Math.min(nearest,clearance);
    }
    if(nearest>=1&&(!best||nearest>best.score))best={x,y,score:nearest};
  }
  return best;
}

/* Keep each portrait and its caption in a separate cell. The SVG viewport
   fits the resulting coordinate space on both surfaces. */
function layoutAgents(live,dimensions){
  const forest=buildForest(live);
  const promotionPartners=dimensions.promoteComms
    ?activePromotionPartners(forest):new Map();
  const promotions=new Map();
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
  // Reserve every singleton's cell before selecting promotion destinations.
  const singletonCount=forest.singletons.length;
  const singletonColumns=singletonCount
    ?Math.min(singletonCount,dimensions.singleColumns):0;
  const singletonRows=singletonCount
    ?Math.ceil(singletonCount/singletonColumns):0;
  const desiredTreeWidth=rawTreeWidth*dimensions.treePitchX;
  const desiredSingletonWidth=Math.max(
    0,(singletonColumns-1)*dimensions.singlePitchX);
  const desiredContentWidth=Math.max(desiredTreeWidth,desiredSingletonWidth);
  const width=Math.max(dimensions.width,desiredContentWidth+dimensions.xPadding*2);
  const treeLeft=(width-desiredTreeWidth)/2;
  const singletonWidth=(singletonColumns-1)*dimensions.singlePitchX;
  const singletonLeft=(width-singletonWidth)/2;

  const idealTreeHeight=rawTreePositions.size
    ?maxDepth*dimensions.treePitchY:0;
  const idealSingletonHeight=singletonRows
    ?(singletonRows-1)*dimensions.singlePitchY:0;
  const idealGap=rawTreePositions.size&&singletonCount
    ?dimensions.sectionGap:0;
  const idealContentHeight=idealTreeHeight+idealGap+idealSingletonHeight;
  const minimumHeight=idealContentHeight+dimensions.topPadding+dimensions.bottomPadding;
  const height=Math.max(dimensions.height,minimumHeight);
  const top=dimensions.topPadding+(height-minimumHeight)/2;
  const singletonTop=top+idealTreeHeight+idealGap;

  const positions=new Map();
  rawTreePositions.forEach((raw,name)=>{
    const agent=forest.byName.get(name);
    positions.set(name,{
      x:treeLeft+(raw.unitX-rawMin)*dimensions.treePitchX,
      y:top+raw.depth*dimensions.treePitchY,
      agent,
      hue:OC.lineageHue.get(name)||'#7a8794',
      working:agent.act_state==='work',
    });
  });
  forest.singletons.forEach((name,index)=>{
    const agent=forest.byName.get(name);
    const column=index%singletonColumns;
    const row=Math.floor(index/singletonColumns);
    positions.set(name,{
      x:singletonLeft+column*dimensions.singlePitchX,
      y:singletonTop+row*dimensions.singlePitchY,
      agent,
      hue:OC.lineageHue.get(name)||'#7a8794',
      working:agent.act_state==='work',
    });
  });
  [...promotionPartners].sort(([a],[b])=>a.localeCompare(b))
    .forEach(([name,partner])=>{
      const partnerPosition=positions.get(partner);
      if(!partnerPosition)return;
      const target=promotedPosition(name,partnerPosition,positions,{
        ...dimensions,width,height,
      });
      if(!target)return;
      Object.assign(positions.get(name),{x:target.x,y:target.y,promoted:true,promotionPartner:partner});
      promotions.set(name,partner);
    });
  return {
    width,height,positions,parentOf:forest.parentOf,
    trees:forest.trees,singletons:forest.singletons.filter(name=>!promotions.has(name)),promotions,
  };
}

/* The compact telemetry view is a bounded, undirected subgraph. A hop is
   one lineage or visible Mail edge; once selected, every internal edge is
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
  const connect=pair=>{
    if(!adjacent.has(pair.a)||!adjacent.has(pair.b))return;
    adjacent.get(pair.a).add(pair.b);adjacent.get(pair.b).add(pair.a);
  };
  if(keepMailLinks)historyPairs.forEach(connect);
  commPairs.forEach(pair=>{
    if(now-pair.ts<MAIL_EDGE_LIFETIME)connect(pair);
  });
  const distances=new Map([[focus,0]]);
  let frontier=[focus];
  for(let hop=0;hop<Math.max(1,Math.min(3,Number(depth)||2));hop++){
    const next=[];
    frontier.forEach(name=>(adjacent.get(name)||[]).forEach(other=>{
      if(distances.has(other))return;
      distances.set(other,hop+1);next.push(other);
    }));
    frontier=next;
    if(!frontier.length)break;
  }
  return {byName,distances};
}
function ringNetworkOffsets(names,dimensions){
  const rx=dimensions.width/2-dimensions.xPadding;
  const ry=dimensions.height/2-Math.max(dimensions.topPadding,dimensions.bottomPadding);
  if(rx<=0||ry<=0)return null;
  const [horizontal,vertical]=captionClearance(dimensions);
  const overlaps=(a,b)=>Math.abs(a.x-b.x)<horizontal&&Math.abs(a.y-b.y)<vertical;
  const fits=(positions,placed)=>positions.every((point,index)=>
    !placed.some(other=>overlaps(point,other))&&
    !positions.slice(0,index).some(other=>overlaps(point,other)));
  const arrangements=[[1],[.6,1],[.53,1],[.7,1],[.42,.71,1],[.48,.74,1],[.32,.58,.79,1]];
  for(const rings of arrangements){
    const placed=[{x:0,y:0}];
    for(const ratio of rings){
      // Try a few rotations before giving up a seat on this ring.
      const capacity=Math.min(names.length+1-placed.length,
        Math.ceil(Math.PI*2*ratio*Math.max(rx,ry)/Math.min(horizontal,vertical)));
      let seated=[];
      for(let count=capacity;count>0&&!seated.length;count--){
        for(const phase of [0,.5,.25,.75]){
          const positions=Array.from({length:count},(_,i)=>{
            const angle=(i+phase)*2*Math.PI/count-Math.PI/2;
            return {x:rx*ratio*Math.cos(angle),y:ry*ratio*Math.sin(angle)};
          });
          if(fits(positions,placed)){seated=positions;break;}
        }
      }
      placed.push(...seated);
      if(placed.length===names.length+1)return placed.slice(1).map((point,i)=>({...point,name:names[i]}));
    }
  }
  return null;
}
function telemetryMiniLayout(subset,focus,dimensions){
  const names=[...subset.distances.keys()].filter(name=>name!==focus);
  const {width,height}=dimensions;
  const mailCount=name=>historyPairs.get(pairKey(focus,name))?.count||0;
  names.sort((a,b)=>mailCount(b)-mailCount(a)||
    subset.distances.get(a)-subset.distances.get(b)||a.localeCompare(b));
  const offsets=ringNetworkOffsets(names,dimensions);
  if(!offsets)return null;
  const positions=new Map();
  [{name:focus,x:0,y:0},...offsets].forEach(({name,x,y})=>{
    const agent=subset.byName.get(name);
    positions.set(name,{x:width/2+x,y:height/2+y,agent,
      hue:OC.lineageHue.get(name)||'#7a8794',working:agent.act_state==='work',networkFocus:name===focus});
  });
  const parentOf=new Map();
  OC.lineageParent.forEach((parent,child)=>{
    if(positions.has(parent)&&positions.has(child))parentOf.set(child,parent);
  });
  return {width,height,positions,parentOf,networkFocus:focus};
}
function fitMiniTree(live,dimensions){
  const [pitchX,pitchY]=captionClearance(dimensions);
  const columns=Math.max(1,1+Math.floor((dimensions.width-2*dimensions.xPadding)/pitchX));
  const layout=layoutAgents(live,{...dimensions,treePitchX:pitchX,treePitchY:pitchY,
    singlePitchX:pitchX,singlePitchY:pitchY,singleColumns:columns});
  if(layout.width===dimensions.width&&layout.height===dimensions.height)return layout;
  const unpromoted=layout.promotions.size?layoutAgents(live,{...dimensions,promoteComms:false}):layout;
  const levels=new Map();
  const ordered=[...unpromoted.positions.values()].sort((a,b)=>a.y-b.y||a.x-b.x);
  for(const node of ordered){
    if(!levels.has(node.y))levels.set(node.y,[]);
    levels.get(node.y).push(node);
  }
  const rows=[...levels.values()].flatMap(level=>{
    const count=Math.ceil(level.length/columns),length=Math.ceil(level.length/count);
    return Array.from({length:count},(_,i)=>level.slice(i*length,(i+1)*length));
  });
  const required=dimensions.topPadding+Math.max(0,rows.length-1)*pitchY+dimensions.bottomPadding;
  if(required>dimensions.height)return null;
  const top=dimensions.topPadding+(dimensions.height-required)/2;
  rows.forEach((row,i)=>row.forEach((node,j)=>{
    node.x=dimensions.width/2+(j-(row.length-1)/2)*pitchX;
    node.y=top+i*pitchY;
  }));
  return {...unpromoted,width:dimensions.width,height:dimensions.height};
}
function miniCaptionWidth(agents){
  if(!miniCaptionMeasure)return MINI.captionWidth;
  const font=getComputedStyle(miniSvg).getPropertyValue('--rail-sans').trim()||'sans-serif';
  miniCaptionMeasure.font=`600 9px ${font}`;
  let width=MINI.captionWidth;
  for(const agent of agents){
    width=Math.max(width,Math.ceil(miniCaptionMeasure.measureText(agent.name||'').width)+3);
    if(width>=MINI_MAX_CAPTION_WIDTH)return MINI_MAX_CAPTION_WIDTH;
  }
  return width;
}
function fitMiniScene(live,width,height){
  const subset=miniMode==='network'&&telemetryNetworkSubset(live,miniFocusName,miniNetworkDepth);
  const agents=subset?[...subset.distances.keys()].map(name=>subset.byName.get(name)):live;
  const scale=Math.max(MINI_PREFERRED_SCALE,Math.min(width/MINI.width,height/MINI.height));
  const captionWidth=miniCaptionWidth(agents),xPadding=Math.max(MINI.xPadding,captionWidth/2+3);
  // Find a scene with room for both caption rows. Fitting the whole scene is
  // the minimum zoom, and its readable scale determines the opening zoom.
  for(let zoom=1;;zoom*=1.12){
    const dimensions={...MINI,captionWidth,xPadding,width:width/scale*zoom,height:height/scale*zoom};
    const layout=subset?telemetryMiniLayout(subset,miniFocusName,dimensions):fitMiniTree(live,dimensions);
    if(layout)return {layout,dimensions,zoom};
  }
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
function prepareMotion(surface,layout,viewportChanged=false){
  const instant=viewportChanged||!surface.initialized||motionIsReduced();
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
function miniParallelOffsets(surface){
  const offsets=new Map(),axes=new Map();
  const edges=[...miniSvg.querySelectorAll('.orrery-mail-edge')]
    .map(edge=>[edge.dataset.edgeFrom,edge.dataset.edgeTo])
    .sort(([a,b],[c,d])=>pairKey(a,b).localeCompare(pairKey(c,d)));
  for(const [a,b] of edges){
    const from=surface.states.get(a),to=surface.states.get(b);
    if(!from||!to)continue;
    const dx=to.tx-from.tx,dy=to.ty-from.ty,length=Math.hypot(dx,dy);
    if(!length)continue;
    const direction=dx<0||dx===0&&dy<0?-1:1;
    const x=dx*direction/length,y=dy*direction/length;
    const axis=[x,y,-y*from.tx+x*from.ty].map(value=>Math.round(value*1000)).join(',');
    const start=Math.min(x*from.tx+y*from.ty,x*to.tx+y*to.ty),end=start+length;
    const lines=axes.get(axis)||[];
    const taken=new Set(lines.filter(line=>Math.min(end,line.end)-Math.max(start,line.start)>16)
      .map(line=>line.lane));
    let lane=0;
    while(taken.has(lane))lane=lane>0?-lane:1-lane;
    lines.push({start,end,lane});
    axes.set(axis,lines);
    if(lane)offsets.set(pairKey(a,b),{x:-y*lane*8,y:x*lane*8});
  }
  return offsets;
}
function updateSurfaceGeometry(surface){
  surface.states.forEach((state,name)=>{
    const cutout=surface.edgeCutouts?.get(name);
    if(cutout){cutout.setAttribute('cx',state.x);cutout.setAttribute('cy',state.y);}
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
    if(surface===miniMotion){
      const offset=surface.edgeOffsets.get(pairKey(from.name,to.name));
      const curve=commPathBetween(from,to,surface.positions,surface.layoutDimensions,offset);
      edge.setAttribute('d',curve.d);
      edge.nextElementSibling.setAttribute('d',curve.d);
    }
    edge.setAttribute('x1',from.x);edge.setAttribute('y1',from.y);
    edge.setAttribute('x2',to.x);edge.setAttribute('y2',to.y);
    edge.style.opacity=String(Math.min(from.opacity,to.opacity));
  });
  surface.target.querySelectorAll('.orrery-comm-edge,.orrery-history-edge').forEach(edge=>{
    const from=surface.states.get(edge.dataset.a);
    const to=surface.states.get(edge.dataset.b);
    if(!from||!to)return;
    const offset=surface.edgeOffsets?.get(pairKey(from.name,to.name));
    const curve=commPathBetween(from,to,surface.positions,surface.layoutDimensions||surface.dimensions,offset);
    edge.setAttribute('d',curve.d);
    if(surface===miniMotion)edge.nextElementSibling.setAttribute('d',curve.d);
    const life=Number(edge.dataset.life||0);
    const alpha=edge.classList.contains('orrery-history-edge') ? .22+.36*life : .58*life;
    edge.setAttribute('stroke-opacity',(alpha*Math.min(from.opacity,to.opacity)).toFixed(3));
  });
  if(activeMailRoute)renderMailFocus(surface);
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
    surface.edgeCutouts?.get(name)?.remove();
    surface.edgeCutouts?.delete(name);
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

function highlightMiniEdge(edge,agent){
  edge.classList.toggle('is-incident',Boolean(agent)&&[edge.dataset.edgeFrom,edge.dataset.edgeTo].includes(agent));
}
function syncMiniEdgeHighlight(){
  const agent=miniHoveredAgent||miniFocusedAgent;
  miniSvg.classList.toggle('has-node-edge-highlight',Boolean(agent));
  miniSvg.querySelectorAll('.orrery-mail-edge').forEach(edge=>highlightMiniEdge(edge,agent));
}
function miniAgentName(element){
  return element?.closest?.('.mini-agent')?.dataset.agent||'';
}
function miniKeyboardAgentName(element){
  return element?.matches?.(':focus-visible')?miniAgentName(element):'';
}
function appendMailEdge(layer,edge,a,b,mini){
  if(!mini){layer.appendChild(edge);return;}
  const label=`Show mail between ${a} and ${b}`;
  const group=svgEl('g',{class:'orrery-mail-edge',role:'button',tabindex:'0',
    'aria-label':label,'aria-controls':'mail','data-edge-from':a,'data-edge-to':b,
    'data-edge-key':`${edge.getAttribute('class')}:${pairKey(a,b)}`});
  const width=edge.getAttribute('stroke-width');
  if(width)group.style.setProperty('--mail-edge-width',`${width}px`);
  highlightMiniEdge(group,miniHoveredAgent||miniFocusedAgent);
  const hit=svgEl('path',{class:'orrery-mail-edge-hit',d:edge.getAttribute('d')||''});
  group.append(edge,hit);
  const activate=()=>document.dispatchEvent(new CustomEvent('oc:filter-mail-pair',{detail:{a,b}}));
  group.addEventListener('click',activate);
  group.addEventListener('keydown',event=>{
    if(event.key!=='Enter'&&event.key!==' ')return;
    event.preventDefault();event.stopPropagation();activate();
  });
  layer.appendChild(group);
}
function focusedEdgeKey(container){
  const focused=document.activeElement;
  return container.contains(focused)?focused.dataset.edgeKey:null;
}
function restoreEdgeFocus(container,key){
  if(key)container.querySelector(`[data-edge-key="${CSS.escape(key)}"]`)?.focus({preventScroll:true});
}
function drawSpawnEdges(target,layout,large){
  const layer=svgEl('g',{class:'orrery-spawn-layer'});
  if(!large)layer.setAttribute('mask','url(#mini-edge-cutouts)');
  layout.parentOf.forEach((parent,child)=>{
    const from=layout.positions.get(parent),to=layout.positions.get(child);
    if(!from||!to)return;
    appendMailEdge(layer,svgEl(large?'line':'path',{
      class:'orrery-spawn-edge'+(large?' planet-edge':''),
      x1:from.x,y1:from.y,x2:to.x,y2:to.y,
      'data-parent':parent,'data-child':child,
    }),parent,child,!large);
  });
  target.appendChild(layer);
  return layer;
}

// Keep provider choice and unknown labels identical across portrait views.
// Compact fallback text is shared with the roster; hover keeps it whole.
function drawProviderBadge(group,agent,x,y,portraitRadius,size=14){
  const presentation=OC.providerPresentation(agent);
  const {provider,text,compactText,local}=presentation;
  const label=local?text:(provider?provider.label:text);
  const seat=svgEl('g',{class:'mini-provider-badge'+(size>14?' planet-provider-badge':'')+(local?' local-provider-badge':''),role:'img','aria-label':label,
    transform:`translate(${x+portraitRadius*.72} ${y+portraitRadius*.72})`});
  const title=svgEl('title');title.textContent=label;seat.appendChild(title);
  if(local){
    const r=size/2;
    seat.appendChild(svgEl('polygon',{class:'mini-provider-seat',
      points:`0,${-r*.92} ${r*.8},${-r*.46} ${r*.8},${r*.46} 0,${r*.92} ${-r*.8},${r*.46} ${-r*.8},${-r*.46}`}));
  }else seat.appendChild(svgEl('circle',{class:'mini-provider-seat',r:size/2}));
  const fallback=()=>{
    if(local)return; // Unknown local maker keeps the hexagon without an adapter mark.
    const mark=svgEl('text',{class:'mini-provider-fallback',x:0,y:0,
      'text-anchor':'middle','dominant-baseline':'central',transform:`scale(${size/14})`});
    mark.textContent=compactText;seat.appendChild(mark);
  };
  if(provider){
    const h=size*.58;
    const aspect={anthropic:1,openai:256/260,google:1,deepseek:71.69/52.76};
    const w=h*(aspect[provider.asset]||1);
    const mark=svgEl('image',{class:'mini-provider-logo',x:-w/2,y:-h/2,width:w,height:h,
      href:'cockpit-assets/'+provider.asset+'.svg','aria-label':label,
      preserveAspectRatio:'xMidYMid meet'});
    mark.addEventListener('error',()=>{mark.remove();fallback();},{once:true});
    seat.appendChild(mark);
  }else fallback();
  group.appendChild(seat);
  return label;
}
function drawAgentCaption(group,{agent,x,y},dimensions,provider,showTitle=true){
  const role=roleOf(agent);
  if(showTitle){
    const title=svgEl('title');
    title.textContent=[agent.name,role,modelOf(agent),provider].filter(Boolean).join(' · ');
    group.prepend(title);
  }

  // Keep the full text in the DOM so Demo can mask whole names before the
  // browser clips them to the cell.
  const caption=svgEl('foreignObject',{x:x-dimensions.captionWidth/2,y:y+dimensions.captionTop,
    width:dimensions.captionWidth,height:dimensions.captionHeight,'aria-hidden':'true'});
  const text=document.createElement('div');
  text.className='orrery-caption';
  const name=document.createElement('div');
  name.className='orrery-caption-name';
  name.textContent=agent.name;
  text.appendChild(name);
  if(role){
    const roleLabel=document.createElement('div');
    roleLabel.className='orrery-caption-role';
    roleLabel.textContent=role;
    text.appendChild(roleLabel);
  }
  caption.appendChild(text);
  group.appendChild(caption);
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
  OC.bindMiniAgentDetail?.(group);
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
    href:'/telemetry/portrait?v=4&style=pixel&name='+encodeURIComponent(agent.name),
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
  const providerLabel=drawProviderBadge(group,agent,x,y,portraitRadius);
  drawStateGlyph(group,agent,x,y,false);
  drawAgentCaption(group,position,dimensions,providerLabel,!OC.bindMiniAgentDetail);
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
    href:'/telemetry/portrait?v=4&style=pixel&name='+encodeURIComponent(agent.name),
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
  const providerLabel=drawProviderBadge(group,agent,x,y,portraitRadius,26);
  drawStateGlyph(group,agent,x,y,true);
  drawAgentCaption(group,position,PLANET,providerLabel);
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
    // The tour's checklist folds out of the way of the way out.
    ...(isOpen?{'data-tour-keep-visible':''}:{}),
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
function syncMiniSelection(){
  miniSvg.querySelectorAll('.mini-selection-ring').forEach(ring=>ring.remove());
  if(miniMode!=='orrery')return;
  // The roster can point to a separate window or a terminal-less agent.
  // Only the pane actually displayed in the center owns this marker.
  const name=OC.activeAgent&&OC.activeAgent();
  const group=miniMotion.nodes.get(name);
  if(!group)return;
  const hit=group.querySelector('.orrery-hit');
  group.appendChild(svgEl('circle',{
    class:'mini-selection-ring',cx:hit.getAttribute('cx'),cy:hit.getAttribute('cy'),r:19.5,
  }));
}
function installMiniGraphDivider(){
  const divider=document.getElementById('mailGraphDivider');
  if(!divider)return;
  const rail=miniViewport.parentElement,head=miniViewport.previousElementSibling;
  let preferred=readPreference(),drag=null;
  function readPreference(){
    try{
      const saved=Number(localStorage.getItem(MINI_HEIGHT_KEY));
      if(Number.isFinite(saved)&&saved>=MINI_MIN_HEIGHT&&saved<=MINI_MAX_HEIGHT)return Math.round(saved);
    }catch(_){/* preference unavailable */}
    return MINI.height;
  }
  function maxHeight(){
    return Math.max(MINI_MIN_HEIGHT,Math.min(MINI_MAX_HEIGHT,rail.clientHeight-head.offsetHeight-MAIL_BELOW_GRAPH));
  }
  function paint(height=preferred){
    const max=maxHeight(),value=Math.max(MINI_MIN_HEIGHT,Math.min(max,Math.round(height)));
    miniViewport.style.height=value+'px';
    divider.setAttribute('aria-valuemin',MINI_MIN_HEIGHT);
    divider.setAttribute('aria-valuemax',max);
    divider.setAttribute('aria-valuenow',value);
    divider.setAttribute('aria-valuetext',value+' pixels');
    return value;
  }
  function save(height){
    preferred=height;
    paint();
    try{
      localStorage.setItem(MINI_HEIGHT_KEY,String(preferred));
      window.OrreryPrefs?.flush();
    }catch(_){/* keep the live height */}
  }
  function syncPreference(){
    preferred=readPreference();
    if(!drag)paint();
  }
  divider.addEventListener('pointerdown',event=>{
    if(event.button!==0||drag)return;
    event.preventDefault();
    const height=miniViewport.clientHeight;
    drag={id:event.pointerId,y:event.clientY,height,preview:height};
    divider.focus({preventScroll:true});
    divider.classList.add('dragging');
    divider.setPointerCapture(event.pointerId);
  });
  function move(event){
    if(!drag||drag.id!==event.pointerId)return;
    drag.preview=paint(drag.height+event.clientY-drag.y);
  }
  function finish(event){
    if(!drag||drag.id!==event.pointerId)return;
    if(event.type==='pointerup')move(event);
    const {height,preview}=drag;
    drag=null;
    divider.classList.remove('dragging');
    if(event.type==='pointerup'&&preview!==height)save(preview);
    else paint();
  }
  divider.addEventListener('pointermove',move);
  for(const type of ['pointerup','pointercancel','lostpointercapture'])divider.addEventListener(type,finish);
  divider.addEventListener('dblclick',()=>save(MINI.height));
  divider.addEventListener('keydown',event=>{
    if(drag)return;
    const step=event.shiftKey?64:24;
    const current=miniViewport.clientHeight;
    let height;
    switch(event.key){
      case 'ArrowUp':height=Math.max(MINI_MIN_HEIGHT,current-step);break;
      case 'ArrowDown':height=Math.min(maxHeight(),current+step);break;
      case 'Home':height=MINI_MIN_HEIGHT;break;
      case 'End':height=maxHeight();break;
      case 'Enter':height=MINI.height;break;
      default:return;
    }
    event.preventDefault();save(height);
  });
  window.addEventListener('storage',event=>{if(event.key===MINI_HEIGHT_KEY)syncPreference();});
  document.addEventListener('oc:prefs-changed',event=>{
    if(event.detail?.keys?.includes(MINI_HEIGHT_KEY))syncPreference();
  });
  new ResizeObserver(()=>paint(drag?.preview??preferred)).observe(rail);
  paint();
}
function miniFocusPoint(){
  const focus=miniMotion.states.get(miniFocusName);
  const matrix=miniSvg.getScreenCTM();
  return focus&&matrix?new DOMPoint(focus.tx,focus.ty).matrixTransform(matrix):null;
}
function centerMiniViewport(){
  if(!miniOverflow)return;
  const center=miniFocusPoint();
  if(!center){
    miniScroll.scrollLeft=(miniScroll.scrollWidth-miniScroll.clientWidth)/2;
    miniScroll.scrollTop=0;
    return;
  }
  const bounds=miniScroll.getBoundingClientRect();
  miniScroll.scrollLeft+=center.x-bounds.left-miniScroll.clientWidth/2;
  miniScroll.scrollTop+=center.y-bounds.top-miniScroll.clientHeight/2;
}
function paintMiniZoom(){
  miniSvg.style.width=miniWidth*miniZoom+'px';
  miniSvg.style.height=miniHeight*miniZoom+'px';
  const [out,into]=miniZoomControls;
  out.disabled=miniZoom===1;
  into.disabled=miniZoom===miniMaxZoom;
  miniOverflow=miniZoom>1;
  miniScroll.classList.toggle('can-pan',miniOverflow);
  if(miniOverflow)miniScroll.tabIndex=0;
  else miniScroll.removeAttribute('tabindex');
}
function setMiniZoom(next,clientX,clientY){
  next=Math.max(1,Math.min(miniMaxZoom,next));
  if(next===miniZoom)return;
  miniViewAdjusted=true;
  const bounds=miniScroll.getBoundingClientRect();
  const x=Number.isFinite(clientX)?clientX-bounds.left:bounds.width/2;
  const y=Number.isFinite(clientY)?clientY-bounds.top:bounds.height/2;
  const factor=next/miniZoom;
  const left=(miniScroll.scrollLeft+x)*factor-x;
  const top=(miniScroll.scrollTop+y)*factor-y;
  miniZoom=next;
  paintMiniZoom();
  miniScroll.scrollLeft=left;
  miniScroll.scrollTop=top;
}
function installMiniZoom(){
  miniViewport.insertAdjacentHTML('beforeend',
    '<div class="mini-graph-zoom" role="group" aria-label="Mini graph zoom">'+
    '<button type="button" aria-label="Zoom out" title="Zoom out" disabled>−</button>'+
    '<button type="button" aria-label="Zoom in" title="Zoom in">+</button></div>');
  miniZoomControls=miniViewport.querySelectorAll('.mini-graph-zoom button');
  const [out,into]=miniZoomControls;
  out.addEventListener('click',()=>{
    setMiniZoom(miniZoom<=miniDefaultZoom+.001?1:miniZoom/1.25);
    if(document.activeElement===out&&out.disabled)into.focus({preventScroll:true});
  });
  into.addEventListener('click',()=>{
    setMiniZoom(miniZoom*1.25);
    if(document.activeElement===into&&into.disabled)out.focus({preventScroll:true});
  });
  let gestureZoom=null;
  miniViewport.addEventListener('wheel',event=>{
    if(!event.ctrlKey&&!event.metaKey){
      if(miniOverflow)miniViewAdjusted=true;
      return;
    }
    event.preventDefault();
    if(gestureZoom!==null)return;
    const units=event.deltaMode===1?16:event.deltaMode===2?miniHeight:1;
    // Chromium sends a pinch as small Ctrl-wheel deltas. Command-wheel also
    // accepts larger deltas from a physical mouse.
    const sensitivity=event.metaKey ? .004 : .01;
    setMiniZoom(miniZoom*Math.exp(-event.deltaY*units*sensitivity),event.clientX,event.clientY);
  },{passive:false});
  miniViewport.addEventListener('gesturestart',event=>{
    event.preventDefault();
    gestureZoom=miniZoom;
  },{passive:false});
  miniViewport.addEventListener('gesturechange',event=>{
    event.preventDefault();
    if(gestureZoom!==null&&Number.isFinite(event.scale))setMiniZoom(gestureZoom*event.scale,event.clientX,event.clientY);
  },{passive:false});
  miniViewport.addEventListener('gestureend',()=>{gestureZoom=null;});
}
function installMiniPan(){
  let drag=null,suppressClick=false;
  miniScroll.addEventListener('pointerdown',event=>{
    if(drag)return;
    suppressClick=false;
    if(!miniOverflow||!event.isPrimary||event.pointerType!=='mouse'||event.button!==0||
      event.target.closest('.mini-agent,.orrery-mail-edge'))return;
    drag={id:event.pointerId,x:event.clientX,y:event.clientY,active:false};
    // Capture the background gesture before it can reach a node or an edge.
    miniScroll.setPointerCapture(event.pointerId);
  });
  function move(event){
    if(!drag||event.pointerId!==drag.id||!miniOverflow)return;
    const dx=event.clientX-drag.x,dy=event.clientY-drag.y;
    if(!drag.active){
      if(dx*dx+dy*dy<16)return;
      drag.active=suppressClick=true;
      miniViewAdjusted=true;
      miniScroll.classList.add('is-panning');
    }
    miniScroll.scrollLeft-=dx;
    miniScroll.scrollTop-=dy;
    drag.x=event.clientX;drag.y=event.clientY;
  }
  function finish(event){
    if(!drag||event.pointerId!==drag.id)return;
    if(event.type==='pointerup')move(event);
    drag=null;
    miniScroll.classList.remove('is-panning');
  }
  miniScroll.addEventListener('pointermove',move);
  for(const type of ['pointerup','pointercancel','lostpointercapture'])miniScroll.addEventListener(type,finish);
  miniScroll.addEventListener('click',event=>{
    if(!suppressClick||!event.detail)return;
    suppressClick=false;
    event.preventDefault();
    event.stopImmediatePropagation();
  },true);
}
function renderMini({recenter=false}={}){
  const focusedEdge=focusedEdgeKey(miniSvg);
  const focusedAgent=miniAgentName(document.activeElement);
  miniViewport.classList.toggle('orrery-mode',miniMode==='orrery');
  const width=miniViewport.clientWidth||miniWidth,height=miniViewport.clientHeight||miniHeight;
  const resized=width!==miniWidth||height!==miniHeight;
  miniWidth=width;miniHeight=height;
  const resetView=resized||recenter||!miniMotion.initialized;
  if(resetView)miniViewAdjusted=false;
  const {layout,dimensions,zoom}=fitMiniScene(liveAgents,width,height);
  miniDefaultZoom=zoom;
  miniMaxZoom=Math.max(MINI_MAX_ZOOM,zoom*1.25);
  miniZoom=miniViewAdjusted?Math.min(miniMaxZoom,miniZoom):zoom;
  const flights=preservedFlights(miniSvg);
  miniSvg.replaceChildren();
  const previous=miniMotion.layoutDimensions;
  const geometryChanged=previous&&(previous.width!==layout.width||previous.height!==layout.height);
  prepareMotion(miniMotion,layout,resized||recenter||geometryChanged);
  miniSvg.setAttribute('viewBox',`0 0 ${layout.width} ${layout.height}`);
  paintMiniZoom();
  miniSvg.classList.toggle('telemetry-network',Boolean(layout.networkFocus));
  miniSvg.setAttribute('aria-label',layout.networkFocus
    ?`Telemetry network for ${layout.networkFocus}, ${miniNetworkDepth} hops`
    :'Live agent spawn and communication graph');
  const defs=svgEl('defs');
  miniSvg.appendChild(defs);
  const mask=svgEl('mask',{id:'mini-edge-cutouts',maskUnits:'userSpaceOnUse',
    x:0,y:0,width:layout.width,height:layout.height});
  mask.appendChild(svgEl('rect',{width:layout.width,height:layout.height,fill:'white'}));
  miniMotion.edgeCutouts=new Map();
  miniMotion.states.forEach((state,name)=>{
    const cutout=svgEl('circle',{cx:state.x,cy:state.y,r:17,fill:'black'});
    mask.appendChild(cutout);
    miniMotion.edgeCutouts.set(name,cutout);
  });
  defs.appendChild(mask);
  miniSvg.appendChild(svgEl('g',{class:'orrery-history-layer',mask:'url(#mini-edge-cutouts)'}));
  const spawnLayer=drawSpawnEdges(miniSvg,layout,false);
  miniSvg.appendChild(svgEl('g',{class:'orrery-comm-layer',mask:'url(#mini-edge-cutouts)'}));
  const nodes=svgEl('g',{class:'orrery-node-layer'});
  let index=0;
  miniMotion.nodes.clear();
  miniMotion.states.forEach((state,name)=>{
    const group=drawMiniAgent(nodes,defs,{
      ...state,x:state.baseX,y:state.baseY,
    },index++,dimensions);
    miniMotion.nodes.set(name,group);
  });
  miniSvg.appendChild(nodes);
  flights.forEach(flight=>miniSvg.appendChild(flight));
  miniMotion.spawnEdges=[...spawnLayer.querySelectorAll('.orrery-spawn-edge')];
  renderMailHistory();
  syncMiniSelection();
  refreshCommEdges();
  OC.syncMiniAgentDetail?.(miniMotion.nodes,focusedAgent);
  restoreEdgeFocus(miniSvg,focusedEdge);
  if(!layout.positions.has(miniHoveredAgent))miniHoveredAgent='';
  miniFocusedAgent=miniKeyboardAgentName(document.activeElement);
  syncMiniEdgeHighlight();
  if(!miniViewAdjusted&&(resetView||geometryChanged))centerMiniViewport();
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
    ?planetLastFocus:miniExpand.querySelector('.orrery-expand');
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
function renderMailHistory(){
  const layer=miniSvg.querySelector('.orrery-history-layer');
  const focused=focusedEdgeKey(layer);
  layer.replaceChildren();
  const spawn=new Set(miniMotion.spawnEdges.map(edge=>pairKey(edge.dataset.parent,edge.dataset.child)));
  if(!keepMailLinks)return;
  historyPairs.forEach(({a,b,count})=>{
    if(!miniPositions.has(a)||!miniPositions.has(b))return;
    // A spawn line already represents this pair. Retained Mail has only a
    // small width range so busy relationships stay as light as the other edges.
    if(spawn.has(pairKey(a,b)))return;
    const width=Math.min(1.5,1.15+.07*Math.log2(Math.max(1,count)));
    appendMailEdge(layer,svgEl('path',{
      class:'orrery-history-edge','data-a':a,'data-b':b,'stroke-width':width.toFixed(2),
    }),a,b,true);
  });
  restoreEdgeFocus(layer,focused);
}
function syncMailHistory(){
  if(!keepMailLinks||document.hidden||!miniViewport.clientWidth||!miniViewport.clientHeight){
    clearTimeout(historyTimer);historyTimer=null;
    historyRequest?.abort();historyRequest=null;
    return;
  }
  if(historyRequest||historyTimer!==null)return;
  const request=new AbortController();
  historyRequest=request;
  // Match NETWORK's default node window. Its counts include all deliveries
  // between the returned agents, with no cutoff based on an edge's age.
  fetch('/telemetry/graph?days=1',{cache:'no-store',signal:request.signal})
    .then(response=>response.ok?response.json():null)
    .then(data=>{
      if(historyRequest!==request||data?.error||!Array.isArray(data?.edges))return;
      const pairs=new Map();
      for(const {source,target,count} of data.edges){
        if(typeof source!=='string'||typeof target!=='string'||!source||!target||source===target||
           !Number.isFinite(count)||count<=0)continue;
        const key=pairKey(source,target);
        const prior=pairs.get(key);
        if(prior)prior.count+=count;
        else {
          const [a,b]=source.localeCompare(target)<=0?[source,target]:[target,source];
          pairs.set(key,{a,b,count});
        }
      }
      if(pairs.size===historyPairs.size&&[...pairs].every(([key,pair])=>historyPairs.get(key)?.count===pair.count))return;
      historyPairs=pairs;
      if(miniMode==='network')renderMini();
      else {renderMailHistory();refreshCommEdges();}
    }).catch(()=>{/* keep the last available history and the live Mail highlights */})
    .finally(()=>{
      if(historyRequest!==request)return;
      historyRequest=null;
      historyTimer=setTimeout(()=>{historyTimer=null;syncMailHistory();},MAIL_HISTORY_REFRESH);
    });
}
function commLayerOf(target){
  return [...target.children].find(child=>
    child.classList.contains('orrery-comm-layer'));
}
function segmentNearNode(from,to,node,radius){
  const dx=to.x-from.x,dy=to.y-from.y;
  const x=node.x-from.x,y=node.y-from.y;
  const t=Math.max(0,Math.min(1,(x*dx+y*dy)/(dx*dx+dy*dy||1)));
  return (x-dx*t)**2+(y-dy*t)**2<=radius*radius;
}
function commPathBetween(from,to,positions,dimensions,offset={x:0,y:0}){
  const dx=to.x-from.x,dy=to.y-from.y;
  const straight={
    d:`M ${from.x+offset.x} ${from.y+offset.y} L ${to.x+offset.x} ${to.y+offset.y}`,
    point:t=>({x:from.x+offset.x+dx*t,y:from.y+offset.y+dy*t}),
  };
  const distance=Math.hypot(dx,dy);
  if(!dimensions.large||!distance||isLineagePair(from.name,to.name))return straight;
  // Clear the portrait's outer ring, with room for the edge stroke.
  const radius=32;
  const nodes=[...positions.values()].filter(node=>node!==from&&node!==to);
  if(!nodes.some(node=>segmentNearNode(from,to,node,radius)))return straight;

  // Start with a shallow detour on either side of the line. Use the same
  // side in both directions, so a highlighted reply retraces its Mail edge.
  const direction=dx<0||(dx===0&&dy<0)?-1:1;
  const nx=direction*dy/distance,ny=-direction*dx/distance;
  let best=straight,fewest=Infinity;
  for(const depth of [2.5,4,6]){
    for(const side of [1,-1]){
      const offset=depth*side*radius;
      const cx=Math.max(0,Math.min(dimensions.width,(from.x+to.x)/2+nx*offset));
      const cy=Math.max(0,Math.min(dimensions.height,(from.y+to.y)/2+ny*offset));
      const point=t=>{
        const mt=1-t;
        return {
          x:mt*mt*from.x+2*mt*t*cx+t*t*to.x,
          y:mt*mt*from.y+2*mt*t*cy+t*t*to.y,
        };
      };
      const curve={d:`M ${from.x} ${from.y} Q ${cx} ${cy} ${to.x} ${to.y}`,point};
      // Test the detour for other portraits as well. Twelve chords with one
      // extra unit of clearance cover the small gap between each chord and
      // the quadratic at these depths.
      const points=Array.from({length:13},(_,index)=>point(index/12));
      const hits=nodes.filter(node=>points.some((end,index)=>index>0&&
        segmentNearNode(points[index-1],end,node,radius+1))).length;
      if(!hits)return curve;
      if(hits<fewest){best=curve;fewest=hits;}
    }
  }
  return best;
}
function renderMailFocus(surface){
  const target=surface?.target;
  if(!target)return;
  let layer=target.querySelector('.orrery-mail-focus');
  if(!activeMailRoute){
    layer?.remove();
    return;
  }
  const from=surface.states.get(activeMailRoute.sender);
  if(!layer){
    layer=svgEl('g',{class:'orrery-mail-focus','aria-hidden':'true'});
    if(surface===miniMotion)layer.setAttribute('mask','url(#mini-edge-cutouts)');
    target.insertBefore(layer,target.querySelector('.orrery-node-layer'));
  }
  layer.replaceChildren();
  if(!from||from.removing)return;
  const dimensions=surface.layoutDimensions||surface.dimensions;
  for(const name of activeMailRoute.recipients||[]){
    const to=surface.states.get(name);
    if(!to||to.removing||to===from)continue;
    const offset=surface.edgeOffsets?.get(pairKey(from.name,to.name));
    const curve=commPathBetween(from,to,surface.positions,dimensions,offset);
    const distance=Math.hypot(to.x-from.x,to.y-from.y);
    const t=Math.max(.45,1-(dimensions.large?27:18)/Math.max(distance,1));
    const tip=curve.point(t),base=curve.point(t-.05);
    const angle=Math.atan2(tip.y-base.y,tip.x-base.x),length=dimensions.large?9:5;
    const wing=turn=>`${tip.x-length*Math.cos(angle+turn)} ${tip.y-length*Math.sin(angle+turn)}`;
    layer.append(
      svgEl('path',{d:curve.d}),
      svgEl('path',{d:`M ${wing(.58)} L ${tip.x} ${tip.y} L ${wing(-.58)}`})
    );
  }
}
document.addEventListener('oc:mail-route',event=>{
  activeMailRoute=event.detail;
  renderMailFocus(miniMotion);
  if(planetarium?.classList.contains('on'))renderMailFocus(planetMotion);
});
/* A spawn always carries its task message, so a parent and its child are a
   mail pair by definition. Drawing both a spawn line and a mail curve for
   them puts two lines where there is one relationship. Hand the mail to the
   line that is already there — brighten it — and draw separate Mail edges
   for pairs the lineage does not connect. */
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
  const focused=focusedEdgeKey(layer);
  layer.replaceChildren();
  const now=Date.now();
  const liveLineage=new Set();
  const mini=target===miniSvg;
  const retained=new Map(mini?[...target.querySelectorAll('.orrery-history-edge')].map(edge=>
    [pairKey(edge.dataset.a,edge.dataset.b),edge]):[]);
  const lineage=mini?new Set(miniMotion.spawnEdges.map(edge=>pairKey(edge.dataset.parent,edge.dataset.child))):null;
  const activeHistory=new Set();
  commPairs.forEach(pair=>{
    const from=positions.get(pair.a),to=positions.get(pair.b);
    if(!from||!to)return;
    const life=1-(now-pair.ts)/MAIL_EDGE_LIFETIME;
    if(life<=0)return;
    const key=pairKey(pair.a,pair.b);
    if(mini?lineage.has(key):isLineagePair(pair.a,pair.b)){
      liveLineage.add(key);
      return;
    }
    const history=retained.get(key);
    if(history){
      activeHistory.add(history);
      history.dataset.life=life.toFixed(5);
      history.classList.add('mail-live');
      history.setAttribute('stroke-opacity',((.22+.36*life)*Math.min(from.opacity,to.opacity)).toFixed(3));
      return;
    }
    const curve=commPathBetween(from,to,positions,dimensions);
    appendMailEdge(layer,svgEl('path',{
      class:'orrery-comm-edge',
      d:curve.d,fill:'none',
      'stroke-opacity':(.58*life).toFixed(3),
      'data-a':pair.a,'data-b':pair.b,'data-life':life.toFixed(5),
    }),pair.a,pair.b,mini);
  });
  retained.forEach(edge=>{
    if(activeHistory.has(edge)||edge.dataset.life===undefined)return;
    delete edge.dataset.life;
    edge.classList.remove('mail-live');
    edge.setAttribute('stroke-opacity','.22');
  });
  markLiveSpawnEdges(target,liveLineage);
  restoreEdgeFocus(layer,focused);
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
  renderCommLayer(miniSvg,miniPositions,miniMotion.layoutDimensions||MINI);
  miniMotion.edgeOffsets=miniParallelOffsets(miniMotion);
  updateSurfaceGeometry(miniMotion);
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
      const curve=commPathBetween(
        from,to,positions,large&&planetMotion
          ?planetMotion.layoutDimensions||PLANET:miniMotion.layoutDimensions||MINI);
      const point=curve.point(eased);
      const envelope=cometEnvelope(progress);
      const ahead=curve.point(Math.min(1,eased+.01)),behind=curve.point(Math.max(0,eased-.01));
      const angle=Math.atan2(ahead.y-behind.y,ahead.x-behind.x)*180/Math.PI;
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
  const name=event.detail&&event.detail.name||'';
  const changed=name!==miniFocusName;
  miniFocusName=name;
  if(miniMode==='network')renderMini({recenter:changed});
  else if(changed)centerMiniViewport();
});
document.addEventListener('oc:stage-agent',syncMiniSelection);
document.addEventListener('oc:mini-view',event=>{
  const detail=event.detail||{};
  const oldMode=miniMode;
  miniMode=detail.mode==='network'?'network':'orrery';
  miniNetworkDepth=[1,2,3].includes(Number(detail.depth))?Number(detail.depth):2;
  keepMailLinks=detail.mailLinks!=='recent';
  miniFocusName=OC.activeAgent&&OC.activeAgent()||miniFocusName;
  renderMini({recenter:miniMode!==oldMode});
  syncMailHistory();
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
miniSvg.addEventListener('pointerover',event=>{
  const name=miniAgentName(event.target);
  if(name===miniHoveredAgent)return;
  miniHoveredAgent=name;
  syncMiniEdgeHighlight();
});
miniSvg.addEventListener('pointerleave',()=>{
  miniHoveredAgent='';
  syncMiniEdgeHighlight();
});
miniSvg.addEventListener('focusin',event=>{
  miniFocusedAgent=miniKeyboardAgentName(event.target);
  syncMiniEdgeHighlight();
});
miniSvg.addEventListener('focusout',event=>{
  miniFocusedAgent=miniKeyboardAgentName(event.relatedTarget);
  syncMiniEdgeHighlight();
});
addExpandAffordance(miniExpand,{...MINI,width:28,height:28},false);
installMiniZoom();
installMiniPan();
installMiniGraphDivider();
renderMini();
new ResizeObserver(()=>{
  const width=miniViewport.clientWidth,height=miniViewport.clientHeight;
  if(width&&height&&(width!==miniWidth||height!==miniHeight))renderMini();
  syncMailHistory();
}).observe(miniViewport);
document.addEventListener('visibilitychange',syncMailHistory);
seedRecentMail();
})();
