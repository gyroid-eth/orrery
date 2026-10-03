/* First-flight copy and state are shared by the checklist and help map. */
(function(root){
'use strict';
const STEPS=Object.freeze([
  {id:'start',title:'Start an agent',label:'NEW AGENT',target:'#newAgentBtn',copy:'Start an agent here. Give it a task and choose a model.'},
  {id:'choose',title:'Choose your agent',label:'AGENT LIST',target:'.col.roster',copy:'Choose an agent on the left to open its terminal.'},
  {id:'talk',title:'Talk to it',label:'TERMINAL + INPUT',target:'.promptbar',copy:'Read the agent’s work in the center. Type below and press Enter to talk to it.'},
  {id:'mail',title:'Read Agent Mail',label:'AGENT MAIL',target:'#mail',copy:'Follow messages exchanged between agents on the right.'},
  {id:'telemetry',title:'Open Telemetry',label:'TELEMETRY',target:'#networkBtn',copy:"Cockpit is for working with agents; Telemetry shows everyone's status and history, with RESUME / EXIT."},
  {id:'planetarium',title:'Explore Planetarium',label:'PLANETARIUM',target:'#planetariumBtn',copy:'See who spawned whom in the full agent family tree.'},
  {id:'settings',title:'Make it comfortable',label:'SETTINGS',target:'#settingsBtn',copy:'Adjust the theme, terminal text size, and mini view.'},
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
  map.innerHTML='<div class="flight-map-head"><div><b>Cockpit help map</b><span>Explore in any order · Esc to close</span></div><button type="button" class="flight-close" aria-label="Close help map">×</button></div><div class="flight-map-cards"></div>';
  const cards=map.querySelector('.flight-map-cards');
  STEPS.forEach((step,index)=>{
    const card=doc.createElement('article');card.className='flight-map-card';card.dataset.step=step.id;
    const heading=doc.createElement('h3');heading.textContent=(index+1)+' · '+step.label;
    const copy=doc.createElement('p');copy.textContent=step.copy;card.append(heading,copy);cards.append(card);
  });
  doc.body.append(guide,map);
  const settings=doc.getElementById('settingsPopover');
  const help=doc.createElement('section');help.className='flight-settings';
  help.innerHTML='<div class="settings-section-title">Getting started</div><div class="flight-settings-actions"><button type="button" class="modal-btn" id="firstFlightBtn">Your first flight</button><button type="button" class="modal-btn" id="helpMapBtn" aria-pressed="false">Show help map</button></div>';
  settings.querySelector('.settings-body').prepend(help);
  let previousFocus=null,highlight=null;
  const rings=[];
  function clearRings(){rings.splice(0).forEach(el=>el.remove());}
  function closeSettings(){if(settings.matches(':popover-open'))settings.hidePopover();}
  function hideMap(){state.hideMap();render();if(previousFocus&&previousFocus.isConnected)previousFocus.focus();}
  function placeMap(){
    clearRings();if(!state.map)return;
    const compact=root.innerWidth<1100||root.innerHeight<620;
    map.classList.toggle('compact',compact);
    const occupied=[];
    const gap=12,pad=14,top=132;
    [...cards.children].forEach((card,index)=>{
      card.style.left='';card.style.top='';
      const target=doc.querySelector(STEPS[index].target);
      if(!target)return;
      const r=target.getBoundingClientRect();
      const visible=r.width>0&&r.height>0&&r.bottom>0&&r.top<root.innerHeight&&r.right>0&&r.left<root.innerWidth;
      if(!visible)return;
      const ring=doc.createElement('span');ring.className='flight-map-marker';ring.textContent=String(index+1);
      ring.style.left=Math.max(pad,Math.min(root.innerWidth-32,STEPS[index].id==='choose'?r.left+12:r.right-14))+'px';
      ring.style.top=Math.max(4,Math.min(root.innerHeight-30,r.top+(STEPS[index].id==='choose'?106:3)))+'px';map.append(ring);rings.push(ring);
      if(compact)return;
      const w=card.offsetWidth,h=card.offsetHeight;
      const maxX=root.innerWidth-w-pad,maxY=root.innerHeight-h-pad;
      const clamp=(x,y)=>({x:Math.max(pad,Math.min(maxX,x)),y:Math.max(top,Math.min(maxY,y))});
      const candidates=[clamp(r.left,r.bottom+gap),clamp(r.right+gap,r.top),clamp(r.left-w-gap,r.top),clamp(r.left,r.top-h-gap)];
      // Search free locations nearest the control when an anchored card collides.
      for(let y=top;y<=maxY;y+=28)for(let x=pad;x<=maxX;x+=28)candidates.push({x,y});
      const intersects=(p)=>occupied.some(o=>p.x<o.x+o.w+gap&&p.x+w+gap>o.x&&p.y<o.y+o.h+gap&&p.y+h+gap>o.y);
      const distance=p=>Math.hypot(p.x+w/2-(r.left+r.width/2),p.y+h/2-(r.top+r.height/2));
      const available=candidates.filter(p=>!intersects(p));
      if(!available.length){map.classList.add('compact');return;}
      const pos=available.sort((a,b)=>distance(a)-distance(b))[0];
      card.style.left=pos.x+'px';card.style.top=pos.y+'px';occupied.push({...pos,w,h});
    });
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
  map.querySelector('.flight-close').addEventListener('click',hideMap);
  doc.getElementById('firstFlightBtn').addEventListener('click',()=>{closeSettings();state.show();render();guide.querySelector('.flight-close').focus();});
  doc.getElementById('helpMapBtn').addEventListener('click',()=>{
    previousFocus=doc.getElementById('settingsBtn');closeSettings();state.toggleMap();render();
    if(state.map)map.querySelector('.flight-close').focus();
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
