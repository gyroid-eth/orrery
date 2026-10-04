/* Tour checklists (first flight, and any later tour) and the help map.
   A checklist's copy and progress are shared by every view of it: the docked
   panel, its folded band, its own window, and (for the first flight) the help map. */
(function(root){
'use strict';
const STEPS=Object.freeze([
  {id:'start',title:'Start an agent',label:'New agent',target:'#newAgentBtn',copy:'Start an agent here. Give it a task and choose a model.'},
  {id:'choose',title:'Choose your agent',label:'Agent list',target:'.col.roster',copy:'Choose an agent on the left to open its terminal.'},
  {id:'talk',title:'Talk to it',label:'Terminal and input',target:'.promptbar',copy:'Read the agent’s work in the center. Type below and press Enter to talk to it.'},
  {id:'mail',title:'Read Agent Mail',label:'Agent mail',target:'#mail',manual:'Mark as read',copy:'Follow messages exchanged between agents on the right.'},
  {id:'telemetry',title:'Open Telemetry',label:'Telemetry',target:'#networkBtn',copy:"Cockpit is for working with agents; Telemetry shows everyone's status and history, with RESUME / EXIT."},
  {id:'planetarium',title:'Explore Planetarium',label:'Planetarium',target:'#planetariumBtn',copy:'See who spawned whom in the full agent family tree.'},
  {id:'settings',title:'Make it comfortable',label:'Settings',target:'#settingsBtn',copy:'Adjust the theme, terminal text size, and mini view.'},
]);
// Help-map notes for controls that are not first-flight steps. The steps supply
// the other notes, so every note's words live in one place; MAP_ORDER is the
// order the compact legend reads in.
const MAP_EXTRA=Object.freeze([
  {id:'select',label:'Select',target:'#rosterSelectBtn',copy:'Turn on Select to pick several agents in the list, then exit them together.'},
  {id:'crew',label:'Working and waiting',target:'.topstat.crew',copy:'How many of your running agents are working right now, and how many are waiting for their next instruction.'},
  {id:'usage',label:'Usage left',target:'#usageBtn',copy:'LEFT shows how much account allowance remains for Claude and Codex. Open it to see each window and when it resets.'},
]);
const MAP_ORDER=['start','select','choose','talk','mail','crew','usage','telemetry','planetarium','settings'];
const MAP_NOTES=Object.freeze(MAP_ORDER.map(id=>STEPS.find(s=>s.id===id)||MAP_EXTRA.find(s=>s.id===id)));
// The help map's sizes, largest first: [data-scale, gap between notes, spacings
// to try]. Scale 0 is the full size; 1-3 set the notes smaller in
// cockpit_tour.css (the smallest: 12px headings, 9px text).
const MAP_SCALES=Object.freeze([[0,18,[1.4,.8]],[1,13,[1,.6]],[2,9,[1,.6]],[3,6,[1,.6]]]);
const KEY='oc-first-flight-v1';
const CHANNEL='orrery-tour';
function createState(storage,{steps=STEPS,key=KEY,autoOpen=true}={}){
  const valid=new Set(steps.map(s=>s.id));
  // focus: a step the viewer moved to by clicking it. It only changes which
  // step is current; a step is done only through its real action.
  let done,open,folded,focus,map=false;
  function load(){
    let saved={};
    try{saved=JSON.parse(storage.getItem(key))||{};}catch(_){}
    done=new Set(Array.isArray(saved.done)?saved.done.filter(id=>valid.has(id)):[]);
    open=autoOpen?saved.seen!==true||saved.open===true:saved.open===true;
    folded=saved.folded===true;
    focus=valid.has(saved.focus)&&!done.has(saved.focus)?saved.focus:null;
  }
  function persist(){try{storage.setItem(key,JSON.stringify({seen:true,open,folded,done:[...done],focus}));}catch(_){}}
  // After the focused step is done, go on from there rather than back to a
  // step that was skipped: the next open step after it, else the first.
  function nextOpenAfter(id){
    const at=steps.findIndex(s=>s.id===id);
    const later=steps.slice(at+1).find(s=>!done.has(s.id));
    return later?later.id:null;
  }
  load();persist();
  return {
    get open(){return open;},get folded(){return folded;},get map(){return map;},get done(){return new Set(done);},
    get current(){return (focus&&steps.find(s=>s.id===focus))||steps.find(s=>!done.has(s.id))||null;},
    get steps(){return steps;},
    show(){open=true;folded=false;map=false;persist();},
    close(){open=false;persist();},
    fold(){folded=true;persist();},
    unfold(){folded=false;persist();},
    toggleMap(){map=!map;return map;},
    hideMap(){map=false;},
    mark(id){
      if(!open||!valid.has(id)||done.has(id))return false;
      done.add(id);
      if(focus===id)focus=nextOpenAfter(id);
      persist();return true;
    },
    // Make an open step the current one (back or ahead); a done step cannot be.
    goTo(id){
      if(!valid.has(id)||done.has(id))return false;
      const first=steps.find(s=>!done.has(s.id));
      const next=first&&first.id===id?null:id;
      if(next===focus)return false;
      focus=next;persist();return true;
    },
    reset(){done.clear();focus=null;open=true;folded=false;map=false;persist();},
    // Another window of the same viewer changed the saved progress.
    reload(){load();},
  };
}
// Leaders are runs of horizontal and vertical segments ("M x,y H x V y ...").
// Two leaders cross, or run along each other, when any of their segments meet
// away from their ends.
function leaderSegments(d){
  let x=0,y=0;const out=[];
  for(const part of d.match(/[MHV][^MHV]*/g)||[]){
    const n=part.slice(1).split(',').map(Number);
    if(part[0]==='M'){x=n[0];y=n[1];}
    else if(part[0]==='H'){out.push([x,y,n[0],y]);x=n[0];}
    else{out.push([x,y,x,n[0]]);y=n[0];}
  }
  return out;
}
function segmentsMeet(a,b){
  const within=(v,lo,hi)=>v>Math.min(lo,hi)+.5&&v<Math.max(lo,hi)-.5;
  const ah=a[1]===a[3],bh=b[1]===b[3];
  if(ah&&!bh)return within(b[0],a[0],a[2])&&within(a[1],b[1],b[3]);
  if(!ah&&bh)return within(a[0],b[0],b[2])&&within(b[1],a[1],a[3]);
  if(ah&&bh)return Math.abs(a[1]-b[1])<1.5&&Math.min(Math.max(a[0],a[2]),Math.max(b[0],b[2]))-Math.max(Math.min(a[0],a[2]),Math.min(b[0],b[2]))>.5;
  return Math.abs(a[0]-b[0])<1.5&&Math.min(Math.max(a[1],a[3]),Math.max(b[1],b[3]))-Math.max(Math.min(a[1],a[3]),Math.min(b[1],b[3]))>.5;
}
function leadersCross(paths){
  const segs=paths.map(leaderSegments);
  return segs.some((one,i)=>segs.slice(i+1).some(other=>one.some(a=>other.some(b=>segmentsMeet(a,b)))));
}
// Where the HERE tag sits next to the tour's ring: below, above, right or left
// of the ring, inside the view and clear of what it must not cover (the tour's
// panel). r: the ring; size: {w,h} of the tag; view: {w,h}; avoid: rects;
// blocked: optionally, whether a spot would cover something the person reads
// or presses there. Returns {x,y,side}, or null when no side has room (the
// ring alone shows).
function placeHereTag(r,size,view,avoid=[],gap=8,margin=6,blocked=null){
  const cx=(r.l+r.r)/2,cy=(r.t+r.b)/2;
  const sides=[
    ['below',cx-size.w/2,r.b+gap],['above',cx-size.w/2,r.t-gap-size.h],
    ['right',r.r+gap,cy-size.h/2],['left',r.l-gap-size.w,cy-size.h/2]];
  for(const [side,x0,y0] of sides){
    const x=side==='below'||side==='above'?Math.max(margin,Math.min(view.w-margin-size.w,x0)):x0;
    const y=side==='left'||side==='right'?Math.max(margin,Math.min(view.h-margin-size.h,y0)):y0;
    const box={l:x,t:y,r:x+size.w,b:y+size.h};
    if(box.l<margin||box.t<margin||box.r>view.w-margin||box.b>view.h-margin)continue;
    if(avoid.some(a=>a&&box.l<a.r&&box.r>a.l&&box.t<a.b&&box.b>a.t))continue;
    if(blocked&&blocked(box))continue;
    return {x,y,side};
  }
  return null;
}
// What the HERE tag must not cover: controls, the brand, the clock, the
// header's status and terminals (their last line is where people type).
const KEEP_CLEAR='button,a[href],input,textarea,select,[role="button"],[contenteditable="true"],.brand,.clock,.topstat,.termhost';
const API={STEPS,MAP_NOTES,KEY,CHANNEL,createState,leadersCross,placeHereTag};
if(typeof module!=='undefined'&&module.exports)module.exports=API;
root.OrreryTour=API;
if(!root.document)return;
const doc=root.document;
const params=new URLSearchParams(root.location.search);
// Only the dedicated tour page (tour.html) is a tour window.
const windowTour=doc.documentElement.classList.contains('tour-window')?params.get('tour'):null;
let storage;try{storage=root.localStorage;}catch(_){}
let channel=null;try{channel=new BroadcastChannel(CHANNEL);}catch(_){}
// In the desktop app the webview opens no window.open popups; the app builds a
// tour window itself (open_tour_window). An app from before that command
// refuses the call, and from then on the checklist stays docked.
let appTourWindows=true;
const APP_CHECK_MS=2000;
function appInvoke(){return root.__TAURI__&&root.__TAURI__.core&&root.__TAURI__.core.invoke;}
function canPopOut(){return appInvoke()?appTourWindows:typeof root.open==='function';}
// A window of this backend: same origin and the same ?ws= override.
function sameBackend(href){
  try{const url=new URL(href);return url.origin===root.location.origin&&(url.searchParams.get('ws')||'')===(params.get('ws')||'');}
  catch(_){return false;}
}
function narrow(){return root.innerWidth<720;}
function readPosition(key){try{const p=JSON.parse(storage.getItem(key+'-pos'));return p&&Number.isFinite(p.left)&&Number.isFinite(p.top)?p:null;}catch(_){return null;}}
function writePosition(key,p){try{if(p)storage.setItem(key+'-pos',JSON.stringify(p));else storage.removeItem(key+'-pos');}catch(_){}}
function settingsSection(){
  const settings=doc.getElementById('settingsPopover');
  let section=settings&&settings.querySelector('.flight-settings');
  if(settings&&!section){
    section=doc.createElement('section');section.className='flight-settings';
    section.innerHTML='<div class="settings-section-title">Getting started</div><div class="flight-settings-actions"></div>';
    settings.querySelector('.settings-body').prepend(section);
  }
  return section;
}
function closeSettings(){const settings=doc.getElementById('settingsPopover');if(settings&&settings.matches(':popover-open'))settings.hidePopover();}
function addSettingsEntry(label,handler,id){
  const section=settingsSection();if(!section)return null;
  const button=doc.createElement('button');button.type='button';button.className='modal-btn';button.textContent=label;
  if(id)button.id=id;
  button.addEventListener('click',()=>{closeSettings();handler();});
  section.querySelector('.flight-settings-actions').append(button);
  return button;
}
API.addSettingsEntry=addSettingsEntry;

/* A checklist panel: a printed checklist (item …… response) that folds to a
   one-line band, floats over the cockpit on frosted glass, drags anywhere in
   the window and, dragged past the edge, moves into a window of its own. */
// Every mounted checklist by id: mounting the same tour twice returns the first.
const checklists=new Map();
const DEFINITION_PREFIX='oc-tour-definition:';
API.getChecklist=id=>checklists.get(id)||null;
function mountChecklist(definition){
  const {id,title,steps,storageKey,autoOpen=false,meta='Use each control once',footer='Reopen anytime in Settings.'}=definition;
  const existing=checklists.get(id);
  // A tour window mounted from the stored definition gives way to the page's own
  // script, whose definition is the current one.
  if(existing&&!(existing.fromStore&&!definition.fromStore))return existing;
  if(existing)existing.destroy();
  // A tour's own window (tour.html?tour=<id>) shows that tour alone; any other checklist stays out of it.
  if(windowTour&&windowTour!==id)return null;
  const solo=windowTour===id;
  // The cockpit leaves the definition (plain data) for the tour's own window,
  // which mounts it from there when no script of the page did (see tour.html).
  if(!solo&&!definition.fromStore)try{storage.setItem(DEFINITION_PREFIX+id,JSON.stringify({id,title,steps,storageKey,meta,footer}));}catch(_){}
  const state=createState(storage,{steps,key:storageKey,autoOpen});
  const el=doc.createElement('aside');
  el.className='flight-guide';el.dataset.tour=id;el.setAttribute('aria-label',title);
  el.innerHTML='<button type="button" class="flight-band"><span class="flight-item"></span><span class="flight-leader"></span><span class="flight-response"></span><span class="flight-count"></span></button>'+
    '<div class="flight-panel"><div class="flight-head"><h2></h2><span class="flight-controls">'+
    '<button type="button" class="flight-popout" aria-label="Open in its own window" title="Open in its own window">↗</button>'+
    '<button type="button" class="flight-fold">Fold</button>'+
    '<button type="button" class="flight-close">×</button></span></div>'+
    '<div class="flight-meta"><span></span><span class="flight-count"></span></div>'+
    '<div class="flight-status" aria-live="polite"></div><ol class="flight-steps"></ol>'+
    '<div class="flight-footer"><span></span><button type="button" class="flight-restart">Restart</button></div></div>';
  el.querySelector('h2').textContent=title;
  el.querySelector('.flight-meta span').textContent=meta;
  el.querySelector('.flight-footer span').textContent=footer;
  el.querySelector('.flight-close').setAttribute('aria-label',solo?'Close this window':'Close '+title);
  el.querySelector('.flight-fold').hidden=solo;
  el.classList.toggle('solo',solo);
  const band=el.querySelector('.flight-band'),head=el.querySelector('.flight-head');
  const rows=new Map();
  steps.forEach(step=>{
    const row=doc.createElement('li');row.dataset.step=step.id;
    const line=doc.createElement('div');line.className='flight-line';
    line.innerHTML='<span class="flight-item"></span><span class="flight-leader"></span><span class="flight-response"></span>';
    line.firstChild.textContent=step.title;
    // Choosing a step moves the tour there; it does not complete it.
    line.setAttribute('role','button');
    const go=()=>{if(state.goTo(step.id))changed();};
    line.addEventListener('click',go);
    line.addEventListener('keydown',event=>{
      if(event.key==='Enter'||event.key===' '){event.preventDefault();go();}
    });
    const copy=doc.createElement('p');copy.textContent=step.copy;
    row.append(line,copy);
    if(step.manual){
      const button=doc.createElement('button');button.type='button';button.className='flight-read';button.textContent=step.manual;
      button.addEventListener('click',()=>{if(state.mark(step.id))changed();});row.append(button);
    }
    el.querySelector('.flight-steps').append(row);rows.set(step.id,row);
  });
  let popup=null,popped=false,suspended=false,highlight=null,dragged=null;
  // The next control: a ring drawn over it (not a style on it, which its
  // container could clip) and a HERE tag beside it. Cyan, unlike the gold the
  // cockpit and its help map use, so it reads as the tour's.
  const ring=doc.createElement('div');ring.className='flight-ring';ring.hidden=true;ring.setAttribute('aria-hidden','true');
  const here=doc.createElement('div');here.className='flight-here';here.hidden=true;here.setAttribute('aria-hidden','true');
  if(!solo)doc.body.append(ring,here);
  function placeRing(){
    const hide=()=>{ring.hidden=true;here.hidden=true;};
    if(destroyed)return hide();
    if(!highlight||!highlight.isConnected)return hide();
    const b=highlight.getBoundingClientRect(),W=root.innerWidth,H=root.innerHeight;
    if(b.width<2||b.height<2||b.right<=0||b.bottom<=0||b.left>=W||b.top>=H)return hide();
    // A target that fills the window (the Telemetry overlay, for its steps)
    // has nothing to point at; a frame around the whole screen would only pulse.
    const shown=(Math.min(W,b.right)-Math.max(0,b.left))*(Math.min(H,b.bottom)-Math.max(0,b.top));
    if(shown>=.9*W*H)return hide();
    // A control under something else (a dialog opened over it) is not pointed
    // at. The tour's own panel does not count: Agent Mail sits under it.
    const cx=Math.min(W-1,Math.max(0,(b.left+b.right)/2)),cy=Math.min(H-1,Math.max(0,(b.top+b.bottom)/2));
    const top=doc.elementFromPoint(cx,cy);
    if(top&&top!==highlight&&!highlight.contains(top)&&!top.closest('.flight-guide'))return hide();
    // Under the panel the ring alone shows where it is: a tag beside it would
    // land on whatever is next to the panel, such as a terminal's input line.
    const underPanel=!!(top&&top.closest('.flight-guide'));
    const pad=4,r={l:Math.max(2,b.left-pad),t:Math.max(2,b.top-pad),r:Math.min(W-2,b.right+pad),b:Math.min(H-2,b.bottom+pad)};
    Object.assign(ring.style,{left:r.l+'px',top:r.t+'px',width:(r.r-r.l)+'px',height:(r.b-r.t)+'px'});
    ring.hidden=false;
    here.hidden=false;here.style.visibility='hidden';
    // The panel's words and buttons are kept clear, not its empty top edge: a
    // small header button whose only free side is above the panel still gets
    // its tag in that strip.
    const panel=el.hidden?null:el.getBoundingClientRect();
    let contentTop=panel?panel.top:0;
    if(panel){
      const tops=[...el.querySelectorAll('.flight-panel h2,.flight-panel button,.flight-panel .flight-meta')]
        .map(c=>c.getBoundingClientRect()).filter(b=>b.width>0&&b.height>0).map(b=>b.top);
      if(tops.length)contentTop=Math.max(panel.top,Math.min(...tops));
    }
    const avoid=panel?[{l:panel.left-6,t:contentTop-4,r:panel.right+6,b:panel.bottom+6}]:[];
    if(underPanel){here.hidden=true;here.style.visibility='';return;}
    // Nor does the tag sit on another control, the brand, the clock or a
    // terminal: a few points across the spot say what is under it.
    const blocked=box=>{
      const xs=[box.l+2,(box.l+box.r)/2,box.r-2],ys=[box.t+2,(box.t+box.b)/2,box.b-2];
      return xs.some(x=>ys.some(y=>{
        const hit=doc.elementFromPoint(x,y);
        return !!hit&&hit!==highlight&&!highlight.contains(hit)&&!!hit.closest(KEEP_CLEAR);
      }));
    };
    const label=side=>side==='below'?'▲ HERE':side==='above'?'▼ HERE':side==='right'?'◀ HERE':'HERE ▶';
    // The arrow depends on the side and the size on the arrow: measure the
    // finished tag, and settle when its side gives back the same label.
    let spot=null;here.textContent=here.textContent||label('below');
    for(let i=0;i<3;i++){
      spot=placeHereTag(r,{w:here.offsetWidth,h:here.offsetHeight},{w:W,h:H},avoid,8,6,blocked);
      if(!spot||label(spot.side)===here.textContent)break;
      here.textContent=label(spot.side);
    }
    if(!spot||label(spot.side)!==here.textContent){here.hidden=true;here.style.visibility='';return;}
    here.dataset.side=spot.side;
    Object.assign(here.style,{left:spot.x+'px',top:spot.y+'px',visibility:''});
  }
  // The control can move (layout, scrolling, a pane opening) without a tour change.
  let ringTimer=0;
  function followRing(){
    clearInterval(ringTimer);placeRing();
    if(highlight)ringTimer=setInterval(placeRing,700);
  }
  root.addEventListener('resize',()=>placeRing());
  root.addEventListener('scroll',()=>placeRing(),true);
  const listeners=[];
  function changed(){render();if(!solo&&channel)channel.postMessage({type:'changed',tour:id});}
  function place(){
    const pos=solo||narrow()?null:readPosition(storageKey);
    el.classList.toggle('placed',!!pos);
    if(!pos){el.style.left=el.style.top='';return;}
    const w=el.offsetWidth,h=el.offsetHeight;
    // A spot that no longer fits (smaller window, other screen) is pulled back in.
    el.style.left=Math.max(0,Math.min(root.innerWidth-w,pos.left))+'px';
    el.style.top=Math.max(0,Math.min(root.innerHeight-Math.min(h,root.innerHeight),pos.top))+'px';
  }
  // Dodging: the panel folds to its band on its own while it would hide what
  // the step needs (its control under the panel, a control the page marks
  // data-tour-keep-visible, or a drawer the embedded Telemetry reports), and
  // opens again once nothing is under it. Not saved, and the ring stays.
  // Opening the band by hand wins until the cover ends.
  let dodging=false,dodgeOverride=false,panelBox=null,measuredSpot=null,cover=[];
  const meets=(a,b)=>a.l<b.r&&a.r>b.l&&a.t<b.b&&a.b>b.t;
  function needsRoom(box){
    const rects=[...cover];
    for(const node of doc.querySelectorAll('[data-tour-keep-visible]')){
      const b=node.getBoundingClientRect();
      if(b.width>0&&b.height>0)rects.push({l:b.left,t:b.top,r:b.right,b:b.bottom});
    }
    const target=highlight&&highlight.isConnected?highlight.getBoundingClientRect():null;
    if(target&&target.width>0&&target.height>0){
      // Only a control mostly under the panel: one beside it, or a target that
      // fills the window (the Telemetry overlay), is not hidden by it.
      const cx=(target.left+target.right)/2,cy=(target.top+target.bottom)/2;
      if(cx>=box.l&&cx<=box.r&&cy>=box.t&&cy<=box.b)rects.push({l:target.left,t:target.top,r:target.right,b:target.bottom});
    }
    return rects.some(r=>meets(r,box));
  }
  // The rect the panel has open: itself when open; when folded, opened unseen
  // within this frame (nothing is painted) by the same place() that opening
  // uses, so a placed panel's own height limit is included.
  function openRect(){
    if(!el.classList.contains('folded')){
      const b=el.getBoundingClientRect();
      return b.width&&b.height?{l:b.left,t:b.top,r:b.right,b:b.bottom}:panelBox;
    }
    el.style.visibility='hidden';el.classList.remove('folded');place();
    const b=el.getBoundingClientRect();
    el.classList.add('folded');place();el.style.visibility='';
    return b.width&&b.height?{l:b.left,t:b.top,r:b.right,b:b.bottom}:panelBox;
  }
  function checkDodge(){
    // Not mid-drag: measuring opens the panel through place(), which would put
    // it back where it was saved; the drag's end judges it once.
    if(dragged)return;
    if(solo||destroyed||el.hidden||state.folded){
      if(dodging||dodgeOverride){dodging=false;dodgeOverride=false;render();}
      return;
    }
    // Docked, the panel opens where it was; placed by hand (the band dragged),
    // judge it where it would open now.
    if(!dodging){panelBox=openRect();measuredSpot=null;}
    else if(el.classList.contains('placed')){
      const band=el.getBoundingClientRect(),spot=band.left+','+band.top;
      if(spot!==measuredSpot){measuredSpot=spot;panelBox=openRect();}
    }
    if(!panelBox)return;
    const covered=needsRoom(panelBox);
    if(!covered)dodgeOverride=false;
    const next=covered&&!dodgeOverride;
    if(next!==dodging){dodging=next;render();}
  }
  const dodgeTimer=solo?0:setInterval(checkDodge,500);
  let destroyed=false;
  function render(){
    if(destroyed)return;
    const done=state.done,current=state.current,count=done.size+' / '+steps.length;
    el.hidden=!solo&&(!state.open||suspended||popped);
    el.classList.toggle('folded',(state.folded||dodging)&&!solo);
    el.classList.toggle('dodging',dodging&&!solo);
    el.querySelector('.flight-popout').hidden=solo||!canPopOut();
    el.querySelectorAll('.flight-count').forEach(node=>{node.textContent=count;});
    el.querySelector('.flight-status').textContent=current?done.size+' of '+steps.length+' done. Next: '+current.title+'.':'All '+steps.length+' done.';
    band.querySelector('.flight-item').textContent=current?current.title:'All done';
    band.querySelector('.flight-response').textContent=current?'now':'done';
    band.setAttribute('aria-label',(current?'Next: '+current.title:'All done')+', '+count+'. Open '+title+'.');
    rows.forEach((row,stepId)=>{
      const isDone=done.has(stepId),isCurrent=!!current&&current.id===stepId;
      row.classList.toggle('done',isDone);row.classList.toggle('current',isCurrent);
      row.querySelector('.flight-response').textContent=isDone?'done':isCurrent?'now':'';
      if(isCurrent)row.setAttribute('aria-current','step');else row.removeAttribute('aria-current');
      const line=row.querySelector('.flight-line'),pickable=!isDone&&!isCurrent;
      line.tabIndex=pickable?0:-1;
      line.setAttribute('aria-disabled',String(!pickable));
      line.setAttribute('aria-label',isDone?steps.find(s=>s.id===stepId).title+', done':
        isCurrent?steps.find(s=>s.id===stepId).title+', current step':'Go to step: '+steps.find(s=>s.id===stepId).title);
      const button=row.querySelector('.flight-read');if(button)button.hidden=!isCurrent;
    });
    if(highlight)highlight.classList.remove('flight-target');
    highlight=!solo&&!el.hidden&&!state.folded&&current&&current.target?doc.querySelector(current.target):null;
    if(highlight)highlight.classList.add('flight-target');
    if(!el.hidden)place();
    followRing();
    listeners.forEach(fn=>fn());
  }
  // The app reports its windows closing; ours carries this tour and this backend's address.
  let appWatch=null,appCloses=0,appOpenings=0;
  // Resolves true once the close notice is subscribed, false when it cannot be.
  function watchAppWindow(){
    if(appWatch)return appWatch;
    const events=root.__TAURI__&&root.__TAURI__.event;
    if(!events||typeof events.listen!=='function')return Promise.resolve(false);
    appWatch=Promise.resolve().then(()=>events.listen('orrery://pane-window-closed',event=>{
      const payload=event&&event.payload||{};
      if(payload.tour===id&&sameBackend(payload.url)){appCloses++;popped=false;render();}
    })).then(()=>true,()=>{appWatch=null;return false;});
    return appWatch;
  }
  // While the tour is out, ask the app now and then whether its window is still
  // there, in case a close notice went unheard.
  let appCheck=0;
  function checkAppWindow(){
    clearTimeout(appCheck);
    const invoke=appInvoke();
    if(!popped||!invoke||popup)return;
    // An answer about an earlier opening of the window says nothing about this one.
    const opening=appOpenings;
    appCheck=setTimeout(()=>{
      if(!popped||opening!==appOpenings)return;
      Promise.resolve().then(()=>invoke('tour_window_exists',{tour:id})).then(exists=>{
        if(opening!==appOpenings)return;
        if(exists===false){popped=false;render();}else checkAppWindow();
      },()=>{if(opening===appOpenings)checkAppWindow();});
    },APP_CHECK_MS);
  }
  function show(){
    state.show();
    // An app window has no handle here; asking for it again brings it forward.
    if(popped&&!popup&&appInvoke()){render();popOut();return;}
    popped=popped&&!!popup&&!popup.closed;render();if(popped)popup.focus();
  }
  function popOut(screenX,screenY){
    if(!canPopOut())return false;
    const width=360,height=Math.min(680,root.screen.availHeight||680);
    const left=Math.round(Number.isFinite(screenX)?screenX-width/2:root.screenX+root.outerWidth-width-24);
    const top=Math.round(Number.isFinite(screenY)?screenY-20:root.screenY+80);
    const invoke=appInvoke();
    if(invoke){
      // Listen for the window closing before asking for it, so a close cannot
      // arrive unheard; without that the panel stays rather than vanish for good.
      watchAppWindow().then(listening=>{
        if(!listening){appTourWindows=false;render();return;}
        const closesBefore=appCloses,opening=++appOpenings;
        return Promise.resolve().then(()=>invoke('open_tour_window',{tour:id,x:left,y:top,width,height})).then(()=>{
          if(appCloses!==closesBefore||opening!==appOpenings)return; // closed, or opened again, meanwhile
          popped=true;render();checkAppWindow();
        },error=>{
          // An older app without the command: keep the panel and stop offering windows.
          appTourWindows=false;popped=false;render();
          console.warn('[tour] no tour windows in this app:',error);
        });
      });
      return true;
    }
    const url=new URL('tour.html',root.location.href);
    ['ws'].forEach(key=>{if(params.get(key))url.searchParams.set(key,params.get(key));});
    url.searchParams.set('tour',id);
    let win=null;
    try{win=root.open(url.href,'orrery-tour-'+id,`popup=yes,width=${width},height=${height},left=${left},top=${top}`);}catch(_){win=null;}
    if(!win)return false;
    popup=win;
    // The panel steps aside once the window reports that it shows the tour.
    if(!channel){popped=true;render();}
    // A popup closed from its title bar may not say so; watching it brings the panel back.
    const timer=setInterval(()=>{if(popup!==win)return clearInterval(timer);if(win.closed){clearInterval(timer);popup=null;popped=false;render();}},800);
    return true;
  }
  // Drag from the header or the band; a press that barely moves is a click.
  function startDrag(event){
    if(solo||narrow()||event.button!==0||event.target.closest('.flight-controls'))return;
    const r=el.getBoundingClientRect();
    dragged={x:event.clientX,y:event.clientY,left:r.left,top:r.top,moved:false,pointer:event.pointerId};
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function outside(event){return event.clientX<0||event.clientY<0||event.clientX>root.innerWidth||event.clientY>root.innerHeight;}
  function moveDrag(event){
    if(!dragged||event.pointerId!==dragged.pointer)return;
    const dx=event.clientX-dragged.x,dy=event.clientY-dragged.y;
    if(!dragged.moved&&Math.hypot(dx,dy)<5)return;
    dragged.moved=true;el.classList.add('dragging','placed');
    el.classList.toggle('leaving',canPopOut()&&outside(event));
    el.style.left=dragged.left+dx+'px';el.style.top=dragged.top+dy+'px';
  }
  function endDrag(event){
    if(!dragged||event.pointerId!==dragged.pointer)return;
    const moved=dragged.moved;dragged=null;el.classList.remove('dragging','leaving');
    if(!moved)return;
    event.preventDefault();
    band.dataset.dragged='1';setTimeout(()=>{delete band.dataset.dragged;},0);
    if(canPopOut()&&outside(event)&&popOut(event.screenX,event.screenY))return;
    const r=el.getBoundingClientRect();writePosition(storageKey,{left:r.left,top:r.top});place();
    checkDodge();
  }
  [head,band].forEach(handle=>{
    handle.addEventListener('pointerdown',startDrag);handle.addEventListener('pointermove',moveDrag);
    handle.addEventListener('pointerup',endDrag);handle.addEventListener('pointercancel',endDrag);
  });
  band.addEventListener('click',()=>{
    if(band.dataset.dragged)return;
    if(dodging){dodging=false;dodgeOverride=true;render();el.querySelector('.flight-fold').focus();return;}
    state.unfold();changed();el.querySelector('.flight-fold').focus();
  });
  el.querySelector('.flight-fold').addEventListener('click',()=>{state.fold();changed();band.focus();});
  el.querySelector('.flight-close').addEventListener('click',()=>{
    if(solo){const invoke=appInvoke();if(invoke)Promise.resolve().then(()=>invoke('close_tour_window',{tour:id})).catch(()=>root.close());else root.close();return;}
    state.close();changed();
  });
  el.querySelector('.flight-restart').addEventListener('click',()=>{state.reset();changed();});
  el.querySelector('.flight-popout').addEventListener('click',()=>{
    if(!popOut()&&typeof root.showToast==='function')root.showToast('POPUP BLOCKED · allow popups for the cockpit',true);
  });
  // Every window of this viewer saves to the same storage; the others repaint from it.
  root.addEventListener('storage',event=>{if(event.key===storageKey){state.reload();render();}});
  if(channel)channel.addEventListener('message',event=>{
    const msg=event.data||{};if(msg.tour!==id)return;
    if(msg.type==='changed'){state.reload();render();}
    else if(!solo&&msg.type==='open'){popped=true;render();}
    else if(!solo&&msg.type==='closed'){popup=null;popped=false;render();}
  });
  if(solo){
    if(channel){channel.postMessage({type:'open',tour:id});root.addEventListener('pagehide',()=>channel.postMessage({type:'closed',tour:id}));}
    doc.title=title+' · ORRERY';
  }else{
    doc.addEventListener('oc:tour-action',event=>{
      const detail=event.detail||{};
      if((detail.tour===undefined||detail.tour===id)&&state.mark(detail.id))changed();
    });
  }
  root.addEventListener('resize',()=>{if(!el.hidden)place();});
  doc.body.append(el);
  const controller={el,state,render,show,popOut,fromStore:!!definition.fromStore,
    destroy(){destroyed=true;clearInterval(ringTimer);clearInterval(dodgeTimer);el.remove();ring.remove();here.remove();if(checklists.get(id)===controller)checklists.delete(id);},
    fold(){state.fold();changed();},unfold(){state.unfold();changed();},
    close(){state.close();changed();},reset(){state.reset();changed();},
    mark(stepId){if(state.mark(stepId)){changed();return true;}return false;},
    // Hide without closing (the help map stands in for the first flight).
    suspend(flag){suspended=!!flag;render();},
    // Called after every repaint (progress, fold, window); read controller.state.current.
    onChange(fn){listeners.push(fn);},
    // Rects (page coordinates) the embedded page needs to keep in view.
    setCover(rects){
      cover=(Array.isArray(rects)?rects:[]).filter(a=>a&&[a.l,a.t,a.r,a.b].every(Number.isFinite));
      checkDodge();
    },
    get dodging(){return dodging;},
    get solo(){return solo;},
  };
  checklists.set(id,controller);
  render();
  return controller;
}
API.mountChecklist=mountChecklist;
// tour.html: after the page's own scripts, mount the tour from the definition
// the cockpit left; without one, say so instead of a blank window.
function mountWindowTour(){
  if(!windowTour||checklists.has(windowTour))return;
  let definition=null;
  try{definition=JSON.parse(storage.getItem(DEFINITION_PREFIX+windowTour));}catch(_){}
  if(definition&&definition.id===windowTour&&Array.isArray(definition.steps)&&definition.steps.length){mountChecklist({...definition,fromStore:true});return;}
  const note=doc.createElement('p');note.className='flight-missing';
  note.textContent='This tour is not available here. Close this window and open it again from the cockpit.';
  doc.body.append(note);
}

function mount(){
  if(doc.documentElement.classList.contains('pane-window'))return;
  const flight=mountChecklist({id:'first-flight',title:'Your first flight',steps:STEPS,storageKey:KEY,autoOpen:true});
  if(!flight)return;
  API.state=flight.state;API.firstFlight=flight;
  if(flight.solo)return;
  const state=flight.state;
  const map=doc.createElement('section');map.className='flight-map';map.hidden=true;
  map.setAttribute('aria-label','Cockpit help map');
  map.innerHTML='<svg class="flight-map-art" aria-hidden="true"><defs><mask id="flightMapMask" maskUnits="userSpaceOnUse"></mask></defs><rect class="flight-map-veil" mask="url(#flightMapMask)"/><g class="flight-map-marks"></g></svg><div class="flight-map-title"><b>The cockpit, annotated</b><span>Press Esc or click anywhere to close.</span><button type="button" class="flight-map-close">Close</button></div><div class="flight-map-notes"></div>';
  const notes=map.querySelector('.flight-map-notes'),title=map.querySelector('.flight-map-title');
  MAP_NOTES.forEach(step=>{
    const note=doc.createElement('article');note.className='flight-map-note';note.dataset.step=step.id;note.tabIndex=-1;
    const heading=doc.createElement('h3');heading.textContent=step.label;
    const copy=doc.createElement('p');copy.textContent=step.copy;note.append(heading,copy);notes.append(note);
  });
  doc.body.append(map);
  const settings=doc.getElementById('settingsPopover');
  addSettingsEntry('Your first flight',()=>{flight.show();(flight.el.querySelector('.flight-fold:not([hidden])')||flight.el.querySelector('.flight-close')).focus();},'firstFlightBtn');
  const helpMapBtn=addSettingsEntry('Show help map',()=>{
    previousFocus=doc.getElementById('settingsBtn');state.toggleMap();render();
    if(state.map)map.querySelector('.flight-map-close').focus();
  },'helpMapBtn');
  helpMapBtn.setAttribute('aria-pressed','false');
  let previousFocus=null;
  function hideMap(){state.hideMap();render();if(previousFocus&&previousFocus.isConnected)previousFocus.focus();}
  const SVG='http://www.w3.org/2000/svg';
  function svg(tag,attrs,parent){const el=doc.createElementNS(SVG,tag);for(const k in attrs)el.setAttribute(k,attrs[k]);parent.append(el);return el;}
  const art=map.querySelector('.flight-map-art'),mask=art.querySelector('mask'),marks=art.querySelector('.flight-map-marks');
  // Each visible control is cut out of the veil and framed with corner ticks;
  // in the annotated layout a leader runs from it to its note.
  function targetRects(){
    const view={l:0,t:0,r:root.innerWidth,b:root.innerHeight};
    const rects=MAP_NOTES.map(step=>{
      const el=doc.querySelector(step.target);if(!el)return null;
      const r=el.getBoundingClientRect();
      const l=Math.max(view.l,r.left),t=Math.max(view.t,r.top),rr=Math.min(view.r,r.right),b=Math.min(view.b,r.bottom);
      return rr-l>4&&b-t>4?{l,t,r:rr,b}:null;
    });
    // A control inside a larger one (New agent inside the roster) keeps its own
    // frame; the larger frame starts below it.
    rects.forEach((a,i)=>rects.forEach((b,j)=>{
      if(!a||!b||i===j)return;
      if(b.l>=a.l&&b.r<=a.r&&b.t>=a.t&&b.b<=a.b&&b.b<a.t+(a.b-a.t)/3)a.t=b.b+8;
    }));
    return rects;
  }
  function drawFrames(rects){
    mask.replaceChildren();marks.replaceChildren();
    svg('rect',{width:'100%',height:'100%',fill:'white'},mask);
    rects.forEach(r=>{
      if(!r)return;
      const p=3,x=Math.max(1,r.l-p),y=Math.max(1,r.t-p);
      const w=Math.min(root.innerWidth-1,r.r+p)-x,h=Math.min(root.innerHeight-1,r.b+p)-y,a=Math.min(10,w/3,h/3);
      svg('rect',{x,y,width:w,height:h,rx:5,fill:'black'},mask);
      svg('path',{class:'flight-map-frame',d:[[x,y,1,1],[x+w,y,-1,1],[x,y+h,1,-1],[x+w,y+h,-1,-1]].map(([cx,cy,dx,dy])=>`M${cx+dx*a},${cy}H${cx}V${cy+dy*a}`).join('')},marks);
    });
  }
  function drawLeader(step,d,dot){svg('path',{class:'flight-map-leader','data-step':step,d},marks);svg('circle',{class:'flight-map-dot',cx:dot[0],cy:dot[1],r:2.4},marks);}
  // The reason the annotated layout gave way to the legend, kept for tests.
  function fail(reason){map.dataset.fallback=reason;return false;}
  // spread: the space between stacked notes, in units of the gap.
  // gap: the space between notes and their leaders' room (smaller when scaled down).
  function annotate(rects,spread,gap=18){
    const stage=doc.getElementById('termstage');
    const v=stage&&stage.getBoundingClientRect();
    if(!v||rects.some(r=>!r)||v.width<440||v.height<320)return fail('room');
    const colGap=28,lane=6,wide=210;
    const headerEl=doc.querySelector('header');
    const hb=headerEl?headerEl.getBoundingClientRect().bottom:v.top;
    const cxOf=r=>(r.l+r.r)/2;
    const sides=rects.map(r=>r.r<=v.left+2?'left':r.b<=v.top+2?'top':r.l>=v.right-2?'right':'bottom');
    // Each left-column leader runs down its own lane just left of the dots.
    const leftDotFor=lanes=>v.left+14+lane*lanes;
    const sizeFor=(leftDot,rightDot)=>Math.min(300,(rightDot-leftDot-colGap)/2-10);
    // Header controls over the stage: the rightmost join the right column while
    // both columns keep room; the rest join the left one along the header's edge.
    const tops=rects.map((r,i)=>i).filter(i=>sides[i]==='top').sort((a,b)=>cxOf(rects[b])-cxOf(rects[a]));
    const leftLeaders=sides.filter(side=>side==='left').length;
    // Right-column header leaders each keep a lane of their own right of the dots.
    let rightDot=v.right-30;
    tops.forEach((i,k)=>{
      const dot=Math.min(v.right-30,cxOf(rects[i])-18-lane*(k+1));
      const remaining=tops.length-k-1;
      if(sizeFor(leftDotFor(leftLeaders+remaining),dot)>=wide)rightDot=dot;
      else tops.slice(k).forEach(j=>{sides[j]='head';});
    });
    const heads=sides.filter(side=>side==='head').length;
    const leftDot=leftDotFor(leftLeaders+heads);
    const width=sizeFor(leftDot,rightDot);
    if(width<180)return fail('width');
    const els=[...notes.children];
    els.forEach(el=>{el.style.width=width+'px';el.style.left='';el.style.top='';el.classList.remove('end');});
    title.style.width=width+'px';
    const mid=el=>{const h=el.firstElementChild;return h.offsetTop+h.offsetHeight/2;};
    // A left control with another framed control beside it leaves over the top
    // instead of running through its neighbour.
    const boxed=i=>{const r=rects[i],y=(r.t+r.b)/2;return rects.some((o,j)=>j!==i&&o.l>=r.r-1&&o.l<v.left&&o.t<=y&&o.b>=y);};
    // Columns are stacked top-down in the order their leaders arrive, so none cross:
    // header notes first (rightmost highest), then controls leaving over the top.
    const left=[],right=[];let bottom=null;
    rects.forEach((r,i)=>{
      const item={i,el:els[i],r,h:els[i].offsetHeight};
      if(sides[i]==='head')item.want=-1e6-cxOf(r),left.push(item);
      else if(sides[i]==='left'&&boxed(i))item.over=true,item.want=-1e5+r.t,left.push(item);
      else if(sides[i]==='left')item.want=r.b-r.t<90?Math.max(v.top+gap,(r.t+r.b)/2):r.t+(r.b-r.t)*.45,left.push(item);
      else if(sides[i]==='top')item.want=v.top+gap+cxOf(r)/1e4,right.push(item);
      else if(sides[i]==='right')item.want=r.t+(r.b-r.t)*.45,right.push(item);
      else bottom=item;
    });
    left.push({el:title,h:title.offsetHeight,want:v.top+v.height*.36});
    const stack=(items,x,alignRight)=>{
      let y=v.top+gap;
      items.sort((a,b)=>a.want-b.want).forEach(item=>{
        item.y=Math.max(y,item.want-mid(item.el));y=item.y+item.h+gap*spread;
        item.x=alignRight?x-width:x;item.el.classList.toggle('end',alignRight);
      });
      return y;
    };
    const leftEnd=stack(left,leftDot+10,false),rightEnd=stack(right,rightDot-10,true);
    // The prompt bar's note sits at the foot of whichever column still has room
    // above it; its leader rises straight from the bar along that column's dots.
    if(bottom){
      bottom.y=bottom.r.t-gap-6-bottom.h;
      const fits=end=>end-gap*(spread-1)<=bottom.y;
      if(fits(leftEnd)){bottom.x=leftDot+10;bottom.col='left';}
      else if(fits(rightEnd)){bottom.x=rightDot-10-width;bottom.col='right';bottom.el.classList.add('end');}
      else return fail('bottom');
    }
    if(leftEnd-gap*spread>v.bottom||rightEnd-gap*spread>v.bottom)return fail('height');
    [...left,...right,...(bottom?[bottom]:[])].forEach(item=>{item.el.style.left=item.x+'px';item.el.style.top=item.y+'px';});
    const rightTops=rects.map((r,i)=>i).filter(i=>sides[i]==='top').sort((a,b)=>cxOf(rects[a])-cxOf(rects[b]));
    // Lanes: the higher a left note, the nearer its lane to the dots.
    let laneIndex=0,headIndex=0;
    // Leaders are drawn only once the whole set is known not to cross.
    const pending=[],leader=(id,d,dot)=>pending.push([id,d,dot]);
    left.forEach(item=>{if(item.i!==undefined)item.lane=leftDot-lane*(++laneIndex);});
    left.concat(right,bottom?[bottom]:[]).forEach(item=>{
      if(item.i===undefined)return;
      const r=item.r,y=item.y+mid(item.el),side=sides[item.i],id=MAP_NOTES[item.i].id;
      if(side==='head'){
        // Along the header's lower edge, the higher note on the lower track.
        const track=Math.max(r.b+5,hb-3-4*headIndex++);
        leader(id,`M${cxOf(r)},${r.b+3}V${track}H${item.lane}V${y}H${leftDot}`,[leftDot,y]);
      }
      else if(side==='left'&&item.over){
        const track=Math.max(hb+2,r.t-8);
        leader(id,`M${cxOf(r)},${r.t-3}V${track}H${item.lane}V${y}H${leftDot}`,[leftDot,y]);
      }
      else if(side==='left'){const sy=Math.max(r.t+8,Math.min(r.b-8,y));leader(id,`M${r.r+3},${sy}H${item.lane}V${y}H${leftDot}`,[leftDot,y]);}
      else if(side==='right'){const sy=Math.max(r.t+8,Math.min(r.b-8,y));leader(id,`M${r.l-3},${sy}H${rightDot+lane*(rightTops.length+1)}V${y}H${rightDot}`,[rightDot,y]);}
      else if(side==='top'){
        // Just below the header and down a lane of its own: the further right the
        // control, the lower its track and the further out its lane.
        const k=rightTops.indexOf(item.i);
        leader(id,`M${cxOf(r)},${r.b+3}V${hb+4+5*k}H${rightDot+lane*(k+1)}V${y}H${rightDot}`,[rightDot,y]);
      }
      else{const x=item.col==='left'?leftDot:rightDot;leader(id,`M${x},${r.t-3}V${y}`,[x,y]);}
    });
    // A wrapped header control (Settings at 1160px) can push its track past its
    // neighbour's; a layout whose leaders cross is not used (the next size, or
    // the legend, is tried instead).
    if(leadersCross(pending.map(p=>p[1])))return fail('crossing');
    pending.forEach(p=>drawLeader(...p));
    return true;
  }
  function placeMap(){
    if(!state.map)return;
    art.setAttribute('width',root.innerWidth);art.setAttribute('height',root.innerHeight);
    art.querySelector('.flight-map-veil').setAttribute('width',root.innerWidth);
    art.querySelector('.flight-map-veil').setAttribute('height',root.innerHeight);
    const rects=targetRects();
    map.classList.remove('compact');delete map.dataset.fallback;drawFrames(rects);
    // Ten notes are a lot for a small stage. Keep the large layout and close
    // the spacing first, then set the notes smaller step by step (data-scale,
    // see cockpit_tour.css); the legend is left for when even the smallest
    // step does not fit.
    for(const [scale,gap,spreads] of MAP_SCALES){
      if(scale)map.dataset.scale=scale;else delete map.dataset.scale;
      if(spreads.some(spread=>annotate(rects,spread,gap))){delete map.dataset.fallback;return;}
    }
    delete map.dataset.scale;
    [title,...notes.children].forEach(el=>{el.style.left=el.style.top=el.style.width='';el.classList.remove('end');});
    map.classList.add('compact');drawFrames(rects);
  }
  function render(){
    map.hidden=!state.map;flight.suspend(state.map);
    helpMapBtn.setAttribute('aria-pressed',String(state.map));
    helpMapBtn.textContent=state.map?'Hide help map':'Show help map';
    placeMap();
  }
  map.querySelector('.flight-map-close').addEventListener('click',hideMap);
  // Anywhere outside the compact legend closes the map; the legend itself scrolls.
  map.addEventListener('click',event=>{if(event.target.closest('.flight-map-close'))return;
    if(!(map.classList.contains('compact')&&event.target.closest('.flight-map-notes,.flight-map-title')))hideMap();});
  doc.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&state.map){event.preventDefault();event.stopImmediatePropagation();hideMap();}
  },true);
  doc.addEventListener('oc:theme-profile-committed',()=>flight.mark('settings'));
  doc.getElementById('mail').addEventListener('click',()=>flight.mark('mail'));
  settings.addEventListener('change',event=>{if(event.target.matches('input,select,textarea'))flight.mark('settings');});
  // Sliders apply on input rather than waiting for a change event.
  settings.addEventListener('input',event=>{if(event.target.matches('input[type="range"]'))flight.mark('settings');});
  let frame=0;
  root.addEventListener('resize',()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(placeMap);});
  root.addEventListener('scroll',()=>{if(state.map)placeMap();},true);
  render();
}
if(doc.readyState==='loading')doc.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
// After the page has loaded, so the page's own tour scripts (including ones that
// mount on DOMContentLoaded) have had their turn.
if(windowTour){if(doc.readyState==='complete')setTimeout(mountWindowTour,0);else root.addEventListener('load',()=>setTimeout(mountWindowTour,0),{once:true});}
})(typeof window==='undefined'?globalThis:window);
