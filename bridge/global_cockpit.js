/* Cockpit DOM and terminal adapter; installed Telemetry modules own flows. */
(function(){'use strict';
let session=null,mail=null,operations=null,host=null,ws=null,socketReady=false,viewer=null,roster=[],dialog=null,proof=null,recentSeq=0;
const portraits=new WeakMap();
const driver={
 nativeInvoke(){
  const invoke=window.__TAURI__?.core?.invoke;
  return invoke? (...args)=>session?.unlocked?invoke(...args):Promise.reject(Error('HTTP_OPERATOR_REQUIRED')):null;
 },
 get unlocked(){return !!session?.unlocked;},get socketReady(){return socketReady;},
 async fetch(path,options={}){
  if(!session?.unlocked)throw Error('HTTP_OPERATOR_REQUIRED');
  const method=options.method||'GET';
  if(!['GET','POST'].includes(method))throw Error('HTTP_OPERATOR_METHOD_UNAVAILABLE');
  const data=await session.api(path,method==='POST'?JSON.parse(options.body||'{}'):undefined);
  return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
 },
 spawn(){if(!session?.unlocked){required();return;}operations.open();},
 network(){if(!session?.unlocked){required();return;}host.network(viewer);},
 portrait(img,name){
  if(!session?.unlocked||portraits.get(img)===name)return;
  portraits.set(img,name);const epoch=session.epoch;
  session.apiBlob('/portrait?name='+encodeURIComponent(name)+'&hi=1').then(url=>{
   if(epoch===session.epoch&&portraits.get(img)===name){img.src=url;img.style.display='';}
  }).catch(()=>{if(epoch===session.epoch)img.style.display='none';});
 },
 connect(){
  if(!session?.unlocked||ws&&ws.readyState<2)return;
  socketReady=false;
  const next=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');ws=next;host.socket(next);
  next.onopen=()=>{if(ws===next&&session.unlocked)next.send(JSON.stringify({type:'authenticate',version:1,capability:session.stored('sessionStorage','getItem','orrery.operator-capability')}));};
  next.onmessage=e=>{if(ws!==next)return;let value;try{value=JSON.parse(e.data);}catch(_){return;}
   if(!socketReady){if(value.type!=='authenticated'||value.version!==1){session.lock();return;}socketReady=true;host.linked();return;}host.receive(value);
  };
  next.onclose=e=>{if(ws!==next)return;ws=null;socketReady=false;host.disconnected();if(e.code===4401){session.lock();return;}setTimeout(()=>driver.connect(),1500);};
 }
};window.OrreryCockpitGlobal=Object.freeze(driver);
let F,E,B,selector,status,drawer,list;
function say(text){if(status)status.textContent=String(text||'');}
function showDialog(title){closeDialog();dialog=E('div','global-dialog');dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');dialog.setAttribute('aria-label',title);const form=E('form','global-form');form.append(E('h2','',title));dialog.append(form);document.body.append(dialog);return form;}
function closeDialog(){dialog?.remove();dialog=null;}
function errorAt(form,error){let row=form.querySelector('.global-error');if(!row){row=E('p','global-error');row.setAttribute('role','alert');form.append(row);}row.textContent=String(error.message||error).slice(0,256);}
function required(error){
 if(!E)return;
 if(dialog?.querySelector('[name=capability]')){if(error)errorAt(dialog.querySelector('form'),error);return;}
 const form=showDialog('Unlock ORRERY'),label=E('label','','Operator capability'),input=E('input');input.name='capability';input.type='password';input.autocomplete='off';input.required=true;label.append(input);
 form.append(E('p','','Run agentstack-http-operator show with this cockpit’s AGENTSTACK_HOME. Paste the capability here; it stays in this page session.'),label,B('Unlock',()=>form.requestSubmit()));
 form.onsubmit=async e=>{e.preventDefault();try{await session.accept(input.value.trim());}catch(error){errorAt(form,error);}};
 if(error)errorAt(form,error);input.focus();
}
function clear(){
 recentSeq++;const previous=ws;ws=null;socketReady=false;previous?.close();
 mail?.clear();operations?.clear();host?.clear();roster=[];viewer=null;selector?.replaceChildren();say('Locked');
 for(const img of document.querySelectorAll('#roster img')){portraits.delete(img);img.removeAttribute('src');}
 document.getElementById('spawnOverlay')?.classList.remove('on');
 document.getElementById('usageDials')?.replaceChildren();document.getElementById('usageKicker').textContent='Locked';
 for(const slot of document.querySelectorAll('#usageBtn .up-p')){slot.classList.add('none');slot.querySelector('b').textContent='—';}
}
async function loadRoster(){
 const epoch=session.epoch,all=[];let before=null;
 do{const page=(await session.api('/api/agents?limit=200'+(before?'&before_agent_id='+before:''))).data;all.push(...page.items);before=page.next_before_agent_id;}while(before&&all.length<10000);
 let observations=[];
 try{for(let at=0;at<all.length;at+=200){const ids=all.slice(at,at+200).map(a=>a.agent_id);if(ids.length)observations.push(...(await session.api('/api/runtime-observations?agent_ids='+ids.join(','))).items);}}
 catch(error){if(epoch!==session.epoch)throw error;observations=[];}
 if(epoch!==session.epoch)return;
 roster=all;const adapted=window.OrreryRuntimeNode.adapt(all,observations),names=new Map(all.map(a=>[a.agent_id,a.name]));
 host.parents(observations.filter(o=>o.parent_state==='known'&&names.has(o.agent_id)&&names.has(o.parent_agent_id)).map(o=>[names.get(o.agent_id),names.get(o.parent_agent_id)]));
 host.renderRoster(all.map(a=>{const row=adapted.get(a.agent_id);return {...row,category:'agent',provider:a.program==='claude-code'?'anthropic':a.program==='codex'?'openai':a.program==='gemini'?'google':'',act_state:row.actState,ctx_used:row.ctxUsed};}));
 selector.replaceChildren(E('option','','Choose a Mail viewpoint'));selector.firstChild.value='';
 for(const a of all){const option=E('option','',a.name+' · #'+a.agent_id);option.value=a.agent_id;selector.append(option);}
 if(viewer&&all.some(a=>a.agent_id===viewer))selector.value=viewer;else viewer=null;
 mail.setViewer(viewer);
}
async function recent(cursor=null,previous=[]){
 const request=++recentSeq;
 if(!viewer){mail.clear();list.replaceChildren(E('p','gap-note','Choose a Mail viewpoint.'));return;}
 const mine=viewer,epoch=session.epoch;
 const page=(await session.api('/api/mail/recent?view_as_agent_id='+mine+'&limit=20'+(cursor?'&cursor='+encodeURIComponent(cursor):''))).data;
 if(epoch!==session.epoch||mine!==viewer||request!==recentSeq)return;
 const notice=await mail.instruction(mine);
 if(epoch!==session.epoch||mine!==viewer||request!==recentSeq)return;
 const messages=[...previous,...page.items];
 drawer.classList.add('on');drawer.setAttribute('aria-hidden','false');drawer.querySelector('.ed-a').textContent='Recent Mail';drawer.querySelector('.ed-b').textContent='';drawer.querySelector('.ed-cnt').textContent=messages.length+' visible';
 F.render(list,{messages,instruction:notice,next:page.next_cursor,onMore:()=>recent(page.next_cursor,messages).catch(error=>say(error.message)),onSelect:id=>{if(id){recentSeq++;mail.openMessage(id).catch(error=>say(error.message));}}});
}
async function quotas(){
 if(!session?.unlocked)return;
 const epoch=session.epoch;
 try{
  const data=await session.api('/api/quotas');if(epoch!==session.epoch)return;
  const body=document.getElementById('usageDials');body.replaceChildren();
  document.getElementById('usageKicker').textContent='Account usage · read only';
  for(const provider of data.providers||[]){
   const section=E('section','up-prov');section.append(E('div','up-head',provider.provider+' · '+provider.status));
   for(const bucket of provider.buckets||[])section.append(E('p','',bucket.label+': '+(Number.isFinite(bucket.remaining_percent)?Math.round(bucket.remaining_percent)+'% left':'unknown')));
   if(!(provider.buckets||[]).length)section.append(E('p','up-empty',provider.reason||'No observation'));
   body.append(section);
   const slot=[...document.querySelectorAll('#usageBtn .up-p')].find(x=>x.dataset.provider===provider.provider);
   const values=(provider.buckets||[]).map(b=>b.remaining_percent).filter(Number.isFinite);
   if(slot){slot.classList.toggle('none',!values.length);slot.querySelector('b').textContent=values.length?Math.round(Math.min(...values))+'%':'—';}
  }
 }catch(error){if(epoch===session.epoch){document.getElementById('usageDials').textContent='Usage unavailable';say(error.message);}}
}
async function start(){
 if(new URLSearchParams(location.search).has('ws'))throw Error('GLOBAL_WEBSOCKET_OVERRIDE_NOT_SUPPORTED');
 const next=await session.api('/telemetry/health');
 if(next.runtime_mode!=='global'||next.api!==1||next.capabilities?.websocket_first_frame_auth!==1)throw Error('COCKPIT_GLOBAL_CAPABILITY_REQUIRED');
 if(proof&&(proof.boot!==next.boot||JSON.stringify(proof.upstream.binding)!==JSON.stringify(next.upstream.binding)))throw Error('MANAGEMENT_BINDING_MISMATCH');proof=next;
 const value=new URLSearchParams(location.search).get('view_as_agent_id');viewer=value&&/^[1-9]\d*$/.test(value)?Number(value):null;
 await loadRoster();await recent();await quotas();
}
window.addEventListener('DOMContentLoaded',async()=>{
 F=window.OrreryMailFlow;E=F.element;B=F.button;host=window.OrreryCockpitHost;
 document.documentElement.classList.add('cockpit-global');
 const select=document.getElementById('rosterSelectBtn');select.disabled=true;select.title='Global exit is unavailable; required before PR7.';
 const exitNote=E('p','global-exit-note',select.title);exitNote.id='globalExitNote';select.setAttribute('aria-describedby',exitNote.id);document.querySelector('.roster-filter').before(exitNote);
 const root=document.getElementById('mail');root.replaceChildren();drawer=E('section','cockpit-mail-drawer');drawer.setAttribute('aria-hidden','true');
 const title=E('div','cockpit-mail-heading');title.append(E('span','ed-a','—'),E('span','',' ⇄ '),E('span','ed-b','—'),E('small','ed-cnt','0'));list=E('div','cockpit-mail-list reply-view');drawer.append(title,list);root.append(drawer);
 status=E('p','global-status');status.setAttribute('role','status');root.before(status);
 const tools=E('div','cockpit-global-tools'),label=E('label','','View as ');selector=E('select');selector.setAttribute('aria-label','Mail viewpoint');label.append(selector);tools.append(label,B('Recent',()=>recent().catch(error=>say(error.message))),B('Lock',()=>session.lock()));root.before(tools);
 session=window.OrreryOperatorSession.create({onLock:clear,onRequired:required,onAccept:start,onAccepted:()=>{closeDialog();driver.connect();if(session.memoryOnly)say('BROWSER_SESSION_STORAGE_UNAVAILABLE · Memory only; reload requires Unlock.');}});
 mail=window.OrreryMailController.create({session,drawer,list,say});
 operations=window.OrreryOperationController.create({session,showDialog,closeDialog,errorAt,getDialog:()=>dialog,refresh:loadRoster});
 selector.onchange=()=>{viewer=selector.value?Number(selector.value):null;mail.setViewer(viewer);recent().catch(error=>say(error.message));};
 document.getElementById('mailTag').textContent='visible Mail';
 document.getElementById('usagePopover').addEventListener('toggle',e=>{if(e.newState==='open')quotas();});
 document.getElementById('settingsBtn').addEventListener('click',async()=>{
  if(!session.unlocked)return;
  let section=document.getElementById('globalInstructionSettings');
  if(!section){section=E('section');section.id='globalInstructionSettings';document.getElementById('settingsPopover').append(section);}
  const mine=viewer,epoch=session.epoch;
  if(!mine){section.replaceChildren(E('p','','Choose a Mail viewpoint to check instructions.'));return;}
  const finding=await mail.instruction(mine);
  if(epoch===session.epoch&&mine===viewer)section.replaceChildren(F.notice(finding,{force:true}));
 });
 document.addEventListener('keydown',e=>{if(e.key==='Tab'&&dialog){const items=[...dialog.querySelectorAll('input,select,button,a[href]')].filter(x=>!x.disabled),first=items[0],last=items.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}});
 if(new URLSearchParams(location.search).has('ws'))say('GLOBAL_WEBSOCKET_OVERRIDE_NOT_SUPPORTED');
 await session.restore();
 setInterval(async()=>{if(!session.unlocked||dialog)return;try{const next=await session.api('/telemetry/health');if(next.boot!==proof.boot||JSON.stringify(next.upstream.binding)!==JSON.stringify(proof.upstream.binding)){session.lock();return;}await loadRoster();await mail.refreshNotice();}catch(error){session.lock();say(error.message);}},15000);
},{once:true});
})();
