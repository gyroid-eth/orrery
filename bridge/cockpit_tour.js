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
const KEY='oc-first-flight-v1';
const CHANNEL='orrery-tour';
function createState(storage,{steps=STEPS,key=KEY,autoOpen=true}={}){
  const valid=new Set(steps.map(s=>s.id));
  let done,open,folded,map=false;
  function load(){
    let saved={};
    try{saved=JSON.parse(storage.getItem(key))||{};}catch(_){}
    done=new Set(Array.isArray(saved.done)?saved.done.filter(id=>valid.has(id)):[]);
    open=autoOpen?saved.seen!==true||saved.open===true:saved.open===true;
    folded=saved.folded===true;
  }
  function persist(){try{storage.setItem(key,JSON.stringify({seen:true,open,folded,done:[...done]}));}catch(_){}}
  load();persist();
  return {
    get open(){return open;},get folded(){return folded;},get map(){return map;},get done(){return new Set(done);},
    get current(){return steps.find(s=>!done.has(s.id))||null;},
    get steps(){return steps;},
    show(){open=true;folded=false;map=false;persist();},
    close(){open=false;persist();},
    fold(){folded=true;persist();},
    unfold(){folded=false;persist();},
    toggleMap(){map=!map;return map;},
    hideMap(){map=false;},
    mark(id){if(!open||!valid.has(id)||done.has(id))return false;done.add(id);persist();return true;},
    reset(){done.clear();open=true;folded=false;map=false;persist();},
    // Another window of the same viewer changed the saved progress.
    reload(){load();},
  };
}
const API={STEPS,KEY,CHANNEL,createState};
if(typeof module!=='undefined'&&module.exports)module.exports=API;
root.OrreryTour=API;
if(!root.document)return;
const doc=root.document;
const params=new URLSearchParams(root.location.search);
// Only the dedicated tour page (tour.html) is a tour window.
const windowTour=doc.documentElement.classList.contains('tour-window')?params.get('tour'):null;
let storage;try{storage=root.localStorage;}catch(_){}
let channel=null;try{channel=new BroadcastChannel(CHANNEL);}catch(_){}
// The desktop app's webview opens no window.open popups (its own windows come
// from the open_pane_window command), so there a checklist stays docked.
const canPopOut=!(root.__TAURI__&&root.__TAURI__.core)&&typeof root.open==='function';
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
  el.querySelector('.flight-popout').hidden=!canPopOut||solo;
  el.querySelector('.flight-fold').hidden=solo;
  el.classList.toggle('solo',solo);
  const band=el.querySelector('.flight-band'),head=el.querySelector('.flight-head');
  const rows=new Map();
  steps.forEach(step=>{
    const row=doc.createElement('li');row.dataset.step=step.id;
    const line=doc.createElement('div');line.className='flight-line';
    line.innerHTML='<span class="flight-item"></span><span class="flight-leader"></span><span class="flight-response"></span>';
    line.firstChild.textContent=step.title;
    const copy=doc.createElement('p');copy.textContent=step.copy;
    row.append(line,copy);
    if(step.manual){
      const button=doc.createElement('button');button.type='button';button.className='flight-read';button.textContent=step.manual;
      button.addEventListener('click',()=>{if(state.mark(step.id))changed();});row.append(button);
    }
    el.querySelector('.flight-steps').append(row);rows.set(step.id,row);
  });
  let popup=null,popped=false,suspended=false,highlight=null,dragged=null;
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
  let destroyed=false;
  function render(){
    if(destroyed)return;
    const done=state.done,current=state.current,count=done.size+' / '+steps.length;
    el.hidden=!solo&&(!state.open||suspended||popped);
    el.classList.toggle('folded',state.folded&&!solo);
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
      const button=row.querySelector('.flight-read');if(button)button.hidden=!isCurrent;
    });
    if(highlight)highlight.classList.remove('flight-target');
    highlight=!solo&&!el.hidden&&!state.folded&&current&&current.target?doc.querySelector(current.target):null;
    if(highlight)highlight.classList.add('flight-target');
    if(!el.hidden)place();
    listeners.forEach(fn=>fn());
  }
  function show(){state.show();popped=popped&&!!popup&&!popup.closed;render();if(popped)popup.focus();}
  function popOut(screenX,screenY){
    if(!canPopOut)return false;
    const width=360,height=Math.min(680,root.screen.availHeight||680);
    const left=Math.round(Number.isFinite(screenX)?screenX-width/2:root.screenX+root.outerWidth-width-24);
    const top=Math.round(Number.isFinite(screenY)?screenY-20:root.screenY+80);
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
    el.classList.toggle('leaving',canPopOut&&outside(event));
    el.style.left=dragged.left+dx+'px';el.style.top=dragged.top+dy+'px';
  }
  function endDrag(event){
    if(!dragged||event.pointerId!==dragged.pointer)return;
    const moved=dragged.moved;dragged=null;el.classList.remove('dragging','leaving');
    if(!moved)return;
    event.preventDefault();
    band.dataset.dragged='1';setTimeout(()=>{delete band.dataset.dragged;},0);
    if(canPopOut&&outside(event)&&popOut(event.screenX,event.screenY))return;
    const r=el.getBoundingClientRect();writePosition(storageKey,{left:r.left,top:r.top});place();
  }
  [head,band].forEach(handle=>{
    handle.addEventListener('pointerdown',startDrag);handle.addEventListener('pointermove',moveDrag);
    handle.addEventListener('pointerup',endDrag);handle.addEventListener('pointercancel',endDrag);
  });
  band.addEventListener('click',()=>{if(band.dataset.dragged)return;state.unfold();changed();el.querySelector('.flight-fold').focus();});
  el.querySelector('.flight-fold').addEventListener('click',()=>{state.fold();changed();band.focus();});
  el.querySelector('.flight-close').addEventListener('click',()=>{if(solo){root.close();return;}state.close();changed();});
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
    destroy(){destroyed=true;el.remove();if(checklists.get(id)===controller)checklists.delete(id);},
    fold(){state.fold();changed();},unfold(){state.unfold();changed();},
    close(){state.close();changed();},reset(){state.reset();changed();},
    mark(stepId){if(state.mark(stepId)){changed();return true;}return false;},
    // Hide without closing (the help map stands in for the first flight).
    suspend(flag){suspended=!!flag;render();},
    // Called after every repaint (progress, fold, window); read controller.state.current.
    onChange(fn){listeners.push(fn);},
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
  STEPS.forEach(step=>{
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
    const rects=STEPS.map(step=>{
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
  function leader(step,d,dot){svg('path',{class:'flight-map-leader','data-step':step,d},marks);svg('circle',{class:'flight-map-dot',cx:dot[0],cy:dot[1],r:2.4},marks);}
  // The reason the annotated layout gave way to the legend, kept for tests.
  function fail(reason){map.dataset.fallback=reason;return false;}
  function annotate(rects){
    const stage=doc.getElementById('termstage');
    const v=stage&&stage.getBoundingClientRect();
    if(!v||rects.some(r=>!r)||v.width<440||v.height<320)return fail('room');
    const inset=30,gap=18,colGap=28;
    const sides=rects.map(r=>r.r<=v.left+2?'left':r.b<=v.top+2?'top':r.l>=v.right-2?'right':'bottom');
    const tops=rects.map((r,i)=>sides[i]==='top'?(r.l+r.r)/2:Infinity);
    const leftDot=v.left+inset,rightDot=Math.min(v.right-inset,Math.min(...tops)-18);
    const width=Math.min(300,(rightDot-leftDot-colGap)/2-10);
    if(width<180)return fail('width');
    const els=[...notes.children];
    els.forEach(el=>{el.style.width=width+'px';el.style.left='';el.style.top='';el.classList.remove('end');});
    title.style.width=width+'px';
    const mid=el=>{const h=el.firstElementChild;return h.offsetTop+h.offsetHeight/2;};
    // Columns are stacked top-down in the order their controls sit, so leaders never cross.
    const left=[],right=[];let bottom=null;
    rects.forEach((r,i)=>{
      const item={i,el:els[i],r,h:els[i].offsetHeight};
      if(sides[i]==='left')item.want=r.b-r.t<90?Math.max(v.top+gap,(r.t+r.b)/2):r.t+(r.b-r.t)*.45,left.push(item);
      else if(sides[i]==='top')item.want=v.top+gap+(r.l+r.r)/2/1e4,right.push(item);
      else if(sides[i]==='right')item.want=r.t+(r.b-r.t)*.45,right.push(item);
      else bottom=item;
    });
    left.push({el:title,h:title.offsetHeight,want:v.top+v.height*.36});
    const stack=(items,x,alignRight)=>{
      let y=v.top+gap;
      items.sort((a,b)=>a.want-b.want).forEach(item=>{
        item.y=Math.max(y,item.want-mid(item.el));y=item.y+item.h+gap*1.4;
        item.x=alignRight?x-width:x;item.el.classList.toggle('end',alignRight);
      });
      return y;
    };
    const leftEnd=stack(left,leftDot+10,false),rightEnd=stack(right,rightDot-10,true);
    // The prompt bar's note sits at the foot of whichever column still has room
    // above it; its leader rises straight from the bar along that column's dots.
    if(bottom){
      bottom.y=bottom.r.t-gap-6-bottom.h;
      const fits=end=>end-gap*0.4<=bottom.y;
      if(fits(leftEnd)){bottom.x=leftDot+10;bottom.col='left';}
      else if(fits(rightEnd)){bottom.x=rightDot-10-width;bottom.col='right';bottom.el.classList.add('end');}
      else return fail('bottom');
    }
    if(leftEnd-gap*1.4>v.bottom||rightEnd-gap*1.4>v.bottom)return fail('height');
    [...left,...right,...(bottom?[bottom]:[])].forEach(item=>{item.el.style.left=item.x+'px';item.el.style.top=item.y+'px';});
    left.concat(right,bottom?[bottom]:[]).forEach(item=>{
      if(item.i===undefined)return;
      const r=item.r,y=item.y+mid(item.el),side=sides[item.i];
      if(side==='left'){const sy=Math.max(r.t+8,Math.min(r.b-8,y));leader(STEPS[item.i].id,`M${r.r+3},${sy}H${leftDot-10}V${y}H${leftDot}`,[leftDot,y]);}
      else if(side==='right'){const sy=Math.max(r.t+8,Math.min(r.b-8,y));leader(STEPS[item.i].id,`M${r.l-3},${sy}H${rightDot+10}V${y}H${rightDot}`,[rightDot,y]);}
      else if(side==='top'){
        const cx=(r.l+r.r)/2;
        // A drop that would run through another framed control turns into the
        // margin just above that frame instead.
        const block=rects.find((o,j)=>sides[j]==='right'&&cx>=o.l&&cx<=o.r&&y>o.t-8);
        if(block)leader(STEPS[item.i].id,`M${cx},${r.b+3}V${block.t-16}H${rightDot+12}V${y}H${rightDot}`,[rightDot,y]);
        else leader(STEPS[item.i].id,`M${cx},${r.b+3}V${y}H${rightDot}`,[rightDot,y]);
      }
      else{const x=item.col==='left'?leftDot:rightDot;leader(STEPS[item.i].id,`M${x},${r.t-3}V${y}`,[x,y]);}
    });
    return true;
  }
  function placeMap(){
    if(!state.map)return;
    art.setAttribute('width',root.innerWidth);art.setAttribute('height',root.innerHeight);
    art.querySelector('.flight-map-veil').setAttribute('width',root.innerWidth);
    art.querySelector('.flight-map-veil').setAttribute('height',root.innerHeight);
    const rects=targetRects();
    map.classList.remove('compact');delete map.dataset.fallback;drawFrames(rects);
    if(!annotate(rects)){
      [title,...notes.children].forEach(el=>{el.style.left=el.style.top=el.style.width='';el.classList.remove('end');});
      map.classList.add('compact');drawFrames(rects);
    }
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
