/* First-flight copy and state are shared by the checklist and help map. */
(function(root){
'use strict';
const STEPS=Object.freeze([
  {id:'start',title:'Start an agent',label:'New agent',target:'#newAgentBtn',copy:'Start an agent here. Give it a task and choose a model.'},
  {id:'choose',title:'Choose your agent',label:'Agent list',target:'.col.roster',copy:'Choose an agent on the left to open its terminal.'},
  {id:'talk',title:'Talk to it',label:'Terminal and input',target:'.promptbar',copy:'Read the agent’s work in the center. Type below and press Enter to talk to it.'},
  {id:'mail',title:'Read Agent Mail',label:'Agent mail',target:'#mail',copy:'Follow messages exchanged between agents on the right.'},
  {id:'telemetry',title:'Open Telemetry',label:'Telemetry',target:'#networkBtn',copy:"Cockpit is for working with agents; Telemetry shows everyone's status and history, with RESUME / EXIT."},
  {id:'planetarium',title:'Explore Planetarium',label:'Planetarium',target:'#planetariumBtn',copy:'See who spawned whom in the full agent family tree.'},
  {id:'settings',title:'Make it comfortable',label:'Settings',target:'#settingsBtn',copy:'Adjust the theme, terminal text size, and mini view.'},
]);
const KEY='oc-first-flight-v1';
function createState(storage){
  let saved={};
  try{saved=JSON.parse(storage.getItem(KEY))||{};}catch(_){}
  const valid=new Set(STEPS.map(s=>s.id));
  const done=new Set(Array.isArray(saved.done)?saved.done.filter(id=>valid.has(id)):[]);
  let open=saved.seen!==true||saved.open===true, map=false;
  function persist(){try{storage.setItem(KEY,JSON.stringify({seen:true,open,done:[...done]}));}catch(_){}}
  persist();
  return {
    get open(){return open;},get map(){return map;},get done(){return new Set(done);},
    get current(){return STEPS.find(s=>!done.has(s.id))||null;},
    show(){open=true;map=false;persist();},
    close(){open=false;persist();},
    toggleMap(){map=!map;return map;},
    hideMap(){map=false;},
    mark(id){if(!open||!valid.has(id)||done.has(id))return false;done.add(id);persist();return true;},
    reset(){done.clear();open=true;map=false;persist();},
  };
}
const API={STEPS,KEY,createState};
if(typeof module!=='undefined'&&module.exports)module.exports=API;
root.OrreryTour=API;
if(!root.document)return;
const doc=root.document;
function mount(){
  if(doc.documentElement.classList.contains('pane-window'))return;
  let storage;try{storage=root.localStorage;}catch(_){}
  const state=createState(storage);
  const guide=doc.createElement('aside');
  guide.className='flight-guide';guide.setAttribute('aria-label','Your first flight');
  guide.innerHTML='<div class="flight-head"><div><div class="flight-kicker">GETTING STARTED</div><h2>Your first flight</h2></div><button class="flight-close" type="button" aria-label="Close first flight">×</button></div><div class="flight-status" aria-live="polite"></div><progress class="flight-progress" max="7"></progress><ol class="flight-steps"></ol><div class="flight-footer"><span>Reopen anytime in Settings.</span><button type="button" class="flight-restart">Restart</button></div>';
  const list=guide.querySelector('.flight-steps');
  const rows=new Map();
  STEPS.forEach((step,index)=>{
    const row=doc.createElement('li');row.dataset.step=step.id;
    const num=doc.createElement('span');num.className='flight-number';num.textContent=String(index+1);
    const content=doc.createElement('div');
    const title=doc.createElement('h3');title.textContent=step.title;
    const copy=doc.createElement('p');copy.textContent=step.copy;
    content.append(title,copy);
    if(step.id==='mail'){
      const button=doc.createElement('button');button.type='button';button.className='flight-read';button.textContent='I’ve read it →';
      button.addEventListener('click',()=>{state.mark('mail');render();});content.append(button);
    }
    row.append(num,content);list.append(row);rows.set(step.id,row);
  });
  const map=doc.createElement('section');map.className='flight-map';map.hidden=true;
  map.setAttribute('aria-label','Cockpit help map');
  map.innerHTML='<svg class="flight-map-art" aria-hidden="true"><defs><mask id="flightMapMask" maskUnits="userSpaceOnUse"></mask></defs><rect class="flight-map-veil" mask="url(#flightMapMask)"/><g class="flight-map-marks"></g></svg><div class="flight-map-title"><b>The cockpit, annotated</b><span>Press Esc or click anywhere to close.</span><button type="button" class="flight-map-close">Close</button></div><div class="flight-map-notes"></div>';
  const notes=map.querySelector('.flight-map-notes'),title=map.querySelector('.flight-map-title');
  STEPS.forEach(step=>{
    const note=doc.createElement('article');note.className='flight-map-note';note.dataset.step=step.id;note.tabIndex=-1;
    const heading=doc.createElement('h3');heading.textContent=step.label;
    const copy=doc.createElement('p');copy.textContent=step.copy;note.append(heading,copy);notes.append(note);
  });
  doc.body.append(guide,map);
  const settings=doc.getElementById('settingsPopover');
  const help=doc.createElement('section');help.className='flight-settings';
  help.innerHTML='<div class="settings-section-title">Getting started</div><div class="flight-settings-actions"><button type="button" class="modal-btn" id="firstFlightBtn">Your first flight</button><button type="button" class="modal-btn" id="helpMapBtn" aria-pressed="false">Show help map</button></div>';
  settings.querySelector('.settings-body').prepend(help);
  let previousFocus=null,highlight=null;
  function closeSettings(){if(settings.matches(':popover-open'))settings.hidePopover();}
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
    guide.hidden=!state.open||state.map;map.hidden=!state.map;
    doc.body.classList.toggle('flight-open',state.open&&!state.map);
    const done=state.done,current=state.current;
    guide.querySelector('.flight-status').textContent=done.size===7?'All set. Enjoy your first flight!':done.size+' / 7 complete · use a control to check it off';
    guide.querySelector('progress').value=done.size;
    rows.forEach((row,id)=>{
      row.classList.toggle('done',done.has(id));row.classList.toggle('current',current&&current.id===id);
      row.querySelector('.flight-number').textContent=done.has(id)?'✓':String(STEPS.findIndex(s=>s.id===id)+1);
      if(current&&current.id===id)row.setAttribute('aria-current','step');else row.removeAttribute('aria-current');
      const button=row.querySelector('button');if(button)button.hidden=done.has(id)||!current||current.id!==id;
    });
    if(highlight)highlight.classList.remove('flight-target');
    highlight=state.open&&!state.map&&current?doc.querySelector(current.target):null;
    if(highlight)highlight.classList.add('flight-target');
    doc.getElementById('helpMapBtn').setAttribute('aria-pressed',String(state.map));
    doc.getElementById('helpMapBtn').textContent=state.map?'Hide help map':'Show help map';
    placeMap();
    root.dispatchEvent(new Event('resize'));
  }
  guide.querySelector('.flight-close').addEventListener('click',()=>{state.close();render();});
  guide.querySelector('.flight-restart').addEventListener('click',()=>{state.reset();render();});
  map.querySelector('.flight-map-close').addEventListener('click',hideMap);
  // Anywhere outside the compact legend closes the map; the legend itself scrolls.
  map.addEventListener('click',event=>{if(event.target.closest('.flight-map-close'))return;
    if(!(map.classList.contains('compact')&&event.target.closest('.flight-map-notes,.flight-map-title')))hideMap();});
  doc.getElementById('firstFlightBtn').addEventListener('click',()=>{closeSettings();state.show();render();guide.querySelector('.flight-close').focus();});
  doc.getElementById('helpMapBtn').addEventListener('click',()=>{
    previousFocus=doc.getElementById('settingsBtn');closeSettings();state.toggleMap();render();
    if(state.map)map.querySelector('.flight-map-close').focus();
  });
  doc.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&state.map){event.preventDefault();event.stopImmediatePropagation();hideMap();}
  },true);
  doc.addEventListener('oc:tour-action',event=>{if(state.mark(event.detail&&event.detail.id))render();});
  doc.addEventListener('oc:theme-profile-committed',()=>{if(state.mark('settings'))render();});
  doc.getElementById('mail').addEventListener('click',()=>{if(state.mark('mail'))render();});
  settings.addEventListener('change',event=>{if(event.target.matches('input,select,textarea')&&state.mark('settings'))render();});
  // Sliders apply on input rather than waiting for a change event.
  settings.addEventListener('input',event=>{if(event.target.matches('input[type="range"]')&&state.mark('settings'))render();});
  let frame=0;
  root.addEventListener('resize',()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(placeMap);});
  root.addEventListener('scroll',()=>{if(state.map)placeMap();},true);
  API.state=state;render();
}
if(doc.readyState==='loading')doc.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})(typeof window==='undefined'?globalThis:window);
