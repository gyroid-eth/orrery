/* Agent Mail shows requests and replies by recipient or in time order.
   The transport has delivery metadata and thread IDs, but no task completion
   state. The rail shows whether a reply has arrived. */
(function(){
'use strict';
const OC=window.OC;
const mailEl=document.getElementById('mail');
const filterButton=document.getElementById('mailFilterBtn');
const viewButton=document.getElementById('mailViewBtn');
const graphButton=document.getElementById('mailGraphBtn');
const graph=document.getElementById('orrery');
const selectedGraph=document.getElementById('mailSelectedRoute');
if(!mailEl||!OC||!filterButton)return;

const byId=new Map(),groupsByName=new Map(),rowsByKey=new Map();
const requestedAgents=new Map();
const motion=matchMedia('(prefers-reduced-motion: reduce)');
let activeFilter='',waitingOnly=false,filterRequest=0;
let drawer=null,drawerMotion=null,drawerMotionTimer=0,replyRequest=0;
let hoveredRoute=null,focusedRoute=null;
let manualGraphOpen=false;
const VIEW_KEY='oc-mail-view';
let timeline=false;
try{timeline=localStorage.getItem(VIEW_KEY)==='timeline';}catch(_){/* preference unavailable */}
let seeded=false;

mailEl.classList.add('mailview-host');
mailEl.innerHTML='<div class="mailview-list"><div class="mailcards"></div></div>'+
  '<div class="mailfilters" id="mailFilters" role="group" aria-label="Filter agent mail" hidden></div>'+
  '<aside class="maildrawer" role="dialog" aria-label="Mail thread" hidden>'+
  '<div class="drawer-head"></div><div class="drawer-scroll">'+
  '<div class="drawer-body"></div><div class="thread-chain" hidden></div></div></aside>';
const listEl=mailEl.querySelector('.mailview-list');
const filterEl=mailEl.querySelector('.mailfilters');
filterButton.parentElement.appendChild(filterEl);
const cardsEl=mailEl.querySelector('.mailcards');
const drawerEl=mailEl.querySelector('.maildrawer');
const drawerHead=drawerEl.querySelector('.drawer-head');
const drawerScroll=drawerEl.querySelector('.drawer-scroll');
const drawerBody=drawerEl.querySelector('.drawer-body');
const drawerChain=drawerEl.querySelector('.thread-chain');

const icons={
  arrow:'<path d="M4 12h15m-5-5 5 5-5 5"/>',
  from:'<path d="M20 12H5m5-5-5 5 5 5"/>',
  open:'<path d="m9 6 6 6-6 6"/>',
  close:'<path d="m6 6 12 12M18 6 6 18"/>',
  thread:'<path d="M5 5v14h6M5 12h6"/><circle cx="14" cy="12" r="2"/><circle cx="14" cy="19" r="2"/>',
  group:'<circle cx="7" cy="6" r="2"/><circle cx="7" cy="15" r="2"/><path d="M12 6h7m-7 9h7m-7 4h5"/>',
  reverse:'<path d="M4 8h15m-4-4 4 4-4 4M20 16H5m4-4-4 4 4 4"/>',
};
function icon(name){
  return '<svg class="mail-icon" viewBox="0 0 24 24" aria-hidden="true">'+icons[name]+'</svg>';
}
function control(action,label,symbol){
  return '<button class="rail-icon" type="button" data-action="'+action+'" title="'+label+'" aria-label="'+label+'">'+icon(symbol)+'</button>';
}
function text(value){return value==null?'':String(value);}
function E(value){return OC.esc(text(value));}
function highImportance(value){return value==='high'||value==='urgent';}
function threadKeyOf(value){return value==null||value===''?'':String(value);}

function normalizeRecipient(value){
  if(value==null)return null;
  const name=typeof value==='object'?text(value.name??value.recipient):text(value);
  return name?{name,kind:text(value.kind)||'to'}:null;
}
function mergeRecipients(left,right){
  const merged=left.slice();
  for(const recipient of right){
    if(!merged.some(r=>r.name===recipient.name&&r.kind===recipient.kind))merged.push(recipient);
  }
  return merged;
}
function normalizeMessage(raw){
  if(!raw||raw.id==null)return null;
  const recipients=(Array.isArray(raw.recipients)?raw.recipients:[]).map(normalizeRecipient).filter(Boolean);
  const flat=raw.recipient;
  const recipient=normalizeRecipient(flat==null||typeof flat==='object'?flat:{name:flat,kind:raw.kind});
  return {
    id:raw.id,key:String(raw.id),ts:Number(raw.ts)||0,sender:text(raw.sender),
    recipients:mergeRecipients(recipients,recipient?[recipient]:[]),
    subject:text(raw.subject),excerpt:text(raw.excerpt),importance:text(raw.importance),
    thread:threadKeyOf(raw.thread_id),
    body_md:Object.hasOwn(raw,'body_md')?text(raw.body_md):null,
  };
}
function mergeMessage(next){
  const prior=byId.get(next.key);
  if(prior)next={
    ...prior,ts:next.ts||prior.ts,sender:next.sender||prior.sender,
    recipients:mergeRecipients(prior.recipients,next.recipients),
    subject:next.subject||prior.subject,excerpt:next.excerpt||prior.excerpt,
    importance:next.importance||prior.importance,thread:next.thread||prior.thread,
    body_md:next.body_md??prior.body_md,
  };
  byId.set(next.key,next);
  return next;
}
function chronological(a,b){
  return a.ts-b.ts||(Number(a.id)-Number(b.id))||a.key.localeCompare(b.key);
}
function recipientNames(message){
  return [...new Set(message.recipients.map(recipient=>recipient.name))];
}
function includesAgent(message,name){
  return message.sender===name||message.recipients.some(r=>r.name===name);
}
function mailboxAgents(){
  const names=new Set();
  for(const m of [...byId.values()].sort((a,b)=>chronological(b,a))){
    if(m.sender)names.add(m.sender);
    recipientNames(m).forEach(name=>names.add(name));
  }
  return [...names];
}
function clock(ts){
  const date=new Date(ts*1000);
  if(!ts||Number.isNaN(date.getTime()))return null;
  return {short:date.toTimeString().slice(0,5),full:date.toLocaleString('en')};
}
function timeHtml(ts){
  const time=clock(ts);
  return time?'<time title="'+E(time.full)+'">'+E(time.short)+'</time>':'';
}
function titleFor(message){return message.subject||message.excerpt||'(No subject)';}

function directRecipients(message){
  const direct=[...new Set(message.recipients.filter(r=>r.kind==='to').map(r=>r.name))];
  // Keep a message with only copied recipients accessible without assigning
  // it to an observer.
  return direct.length?direct:[''];
}
function routeKey(sender,recipient){return JSON.stringify([sender,recipient]);}
function makeAssignment(key,message,recipient){
  return {key,recipient,request:message,latest:message,replies:[],followups:[]};
}
function expectsReply(assignment){
  return Boolean(assignment.recipient&&assignment.recipient!==assignment.request.sender);
}
function addReply(assignment,message){
  assignment.replies.push(message);
  assignment.latest=message;
}

function assignments(){
  const threads=new Map(),pending=new Map(),result=[];
  for(const message of [...byId.values()].sort(chronological)){
    if(message.thread){
      if(!threads.has(message.thread))threads.set(message.thread,[]);
      threads.get(message.thread).push(message);
      continue;
    }

    const recipients=directRecipients(message);
    let linked=false;
    for(const recipient of recipients){
      if(!recipient||recipient===message.sender)continue;
      const key=routeKey(recipient,message.sender);
      const requests=pending.get(key);
      if(!requests)continue;
      addReply(requests.pop(),message);
      if(!requests.length)pending.delete(key);
      linked=true;
    }
    // A delivery linked as a reply may also address other peers. Those
    // recipients can still read the route, but do not create new requests.
    if(linked)continue;

    for(const recipient of recipients){
      const route=routeKey(message.sender,recipient);
      const assignment=makeAssignment(JSON.stringify(['message:'+message.key,route]),message,recipient);
      result.push(assignment);
      if(expectsReply(assignment)){
        if(!pending.has(route))pending.set(route,[]);
        pending.get(route).push(assignment);
      }
    }
  }

  for(const [thread,messages] of threads){
    const routes=new Map();
    for(const message of messages){
      for(const name of directRecipients(message)){
        const route=routeKey(message.sender,name);
        const reverse=message.sender!==name&&routes.get(routeKey(name,message.sender));
        if(reverse)addReply(reverse,message);
        else if(routes.has(route)){
          const assignment=routes.get(route);
          assignment.followups.push(message);
          assignment.latest=message;
        }else routes.set(route,makeAssignment(JSON.stringify(['thread:'+thread,route]),message,name));
      }
    }
    result.push(...routes.values());
  }
  return result.sort((a,b)=>chronological(b.latest,a.latest));
}
function visibleAssignments(){
  return assignments().filter(a=>(!waitingOnly||(expectsReply(a)&&!a.replies.length))&&
    (!activeFilter||[a.request,...a.replies,...a.followups].some(m=>includesAgent(m,activeFilter))));
}

function assignmentsForView(source){
  if(!timeline)return source;
  const byRequest=new Map();
  for(const a of source){
    const key='timeline:'+a.request.key;
    const record=byRequest.get(key);
    if(!record){
      byRequest.set(key,{...a,key,deliveries:[a.recipient],replies:new Map(a.replies.map(m=>[m.key,m])),
        followups:new Map(a.followups.map(m=>[m.key,m]))});
      continue;
    }
    record.deliveries.push(a.recipient);
    if(expectsReply(a))record.recipient=a.recipient;
    for(const m of a.replies)record.replies.set(m.key,m);
    for(const m of a.followups)record.followups.set(m.key,m);
  }
  return [...byRequest.values()].sort((a,b)=>chronological(b.request,a.request)).map(a=>({
    ...a,replies:[...a.replies.values()].sort(chronological),
    followups:[...a.followups.values()].sort(chronological)
  }));
}

function filterChoice(label,pressed,activate){
  const option=document.createElement('button');
  option.type='button';option.textContent=label;option.setAttribute('aria-pressed',String(pressed));
  option.addEventListener('click',activate);
  return option;
}
function setFilterOpen(open,restoreFocus=false){
  filterEl.hidden=!open;
  filterButton.setAttribute('aria-expanded',String(open));
  if(open){
    filterEl.replaceChildren(
      filterChoice('Awaiting a reply',waitingOnly,()=>{
        waitingOnly=!waitingOnly;setFilterOpen(false,true);renderMail({animate:true});
      }),
      ...['',...mailboxAgents()].map(agent=>filterChoice(agent||'All agents',activeFilter===agent,()=>{
        selectMailFilter(agent);setFilterOpen(false,true);
      }))
    );
    filterEl.querySelector('button')?.focus({preventScroll:true});
    if(!document.hidden)filterEl.animate(motion.matches?[{opacity:0},{opacity:1}]:[
      {opacity:.3,transform:'scale(.94)'},{opacity:1,transform:'none'}
    ],{duration:motion.matches?90:160,easing:'ease-out'});
  }else if(restoreFocus)filterButton.focus({preventScroll:true});
}
filterButton.addEventListener('click',()=>setFilterOpen(filterEl.hidden));
document.addEventListener('pointerdown',event=>{
  if(!filterEl.hidden&&!filterEl.contains(event.target)&&!filterButton.contains(event.target))setFilterOpen(false);
});
async function loadAgentMail(agent){
  if(!requestedAgents.has(agent)){
    const request=fetchJson('/telemetry/mail/recent?limit=40&agent='+encodeURIComponent(agent)).then(data=>{
      if(!Array.isArray(data?.messages)){requestedAgents.delete(agent);return;}
      ingest(data.messages);
    });
    requestedAgents.set(agent,request);
  }
  await requestedAgents.get(agent);
}
async function selectMailFilter(agent,{requireExisting=false}={}){
  const request=++filterRequest,next=text(agent);
  const known=()=>[...byId.values()].some(m=>includesAgent(m,next));
  if(next&&!known())await loadAgentMail(next);
  if(request!==filterRequest||(requireExisting&&!known()))return false;
  if(activeFilter!==next){
    activeFilter=next;
    renderMail({animate:true});
  }
  return true;
}

function emitRoute(){
  document.dispatchEvent(new CustomEvent('oc:mail-route',{detail:selectedRoute()||hoveredRoute||focusedRoute}));
}
function bindRoute(button,message){
  button.addEventListener('pointerenter',()=>{hoveredRoute=message();emitRoute();});
  button.addEventListener('pointerleave',()=>{hoveredRoute=null;emitRoute();});
  button.addEventListener('focus',()=>{focusedRoute=message();emitRoute();});
  button.addEventListener('blur',()=>{focusedRoute=null;emitRoute();});
}
function assignmentRoute(a){return {sender:a.request.sender,recipients:(a.deliveries||[a.recipient]).filter(Boolean)};}
function messageRoute(m){return m?{sender:m.sender,recipients:recipientNames(m)}:null;}
function selectedRoute(){
  if(!drawer)return null;
  if(drawer.message)return messageRoute(drawer.message);
  const route=assignmentRoute(drawer.assignment);
  return route.recipients.length?route:messageRoute(drawer.request);
}
function paintGraph(){
  const route=selectedRoute();
  const showGraph=manualGraphOpen&&!route;
  graph.toggleAttribute('hidden',!showGraph);
  graphButton.hidden=Boolean(route);
  graphButton.setAttribute('aria-expanded',String(showGraph));
  graphButton.title=showGraph?'Hide mini graph':'Show mini graph';
  graphButton.setAttribute('aria-label',graphButton.title);
  selectedGraph.hidden=!route;
  if(!route)return;
  const stop=name=>'<span class="mail-route-stop">'+
    '<span aria-hidden="true"></span>'+E(name)+'</span>';
  const markup=stop(route.sender||'Unknown sender')+icon('arrow')+
    '<span class="mail-route-destinations">'+(route.recipients.length
      ?route.recipients.map(stop).join(''):stop('No direct recipient'))+'</span>';
  if(selectedGraph.markup===markup)return;
  selectedGraph.innerHTML=markup;
  selectedGraph.markup=markup;
  selectedGraph.setAttribute('role','img');
  selectedGraph.setAttribute('aria-label',(route.sender||'Unknown sender')+' to '+
    (route.recipients.join(', ')||'no direct recipient'));
}
graphButton.addEventListener('click',()=>{manualGraphOpen=!manualGraphOpen;paintGraph();});

function paintView(){
  viewButton.title=timeline?'Group by recipient':'Show thread timeline';
  viewButton.setAttribute('aria-label',viewButton.title);
  viewButton.innerHTML=icon(timeline?'group':'thread');
}
viewButton.addEventListener('click',()=>{
  if(drawer)closeDrawer(false);
  timeline=!timeline;
  try{localStorage.setItem(VIEW_KEY,timeline?'timeline':'recipient');}catch(_){/* preference unavailable */}
  paintView();
  renderMail();
  listEl.scrollTop=0;
});

function paintPortrait(group){
  const {name,heading,fallback}=group;
  const previous=heading.firstElementChild;
  const avatar=name&&OC.renderPeerAvatar?.(name,previous===fallback?null:previous);
  const next=avatar||fallback;
  if(next!==previous){
    next.setAttribute('aria-hidden','true');
    previous.replaceWith(next);
  }
}
function makeGroup(name){
  const el=document.createElement('section');
  el.className='mail-assignee';
  el.innerHTML='<h3 class="mail-assignee-name"><span class="mail-assignee-fallback" aria-hidden="true"></span>'+
    '<span>'+E(name||'No direct recipient')+'</span></h3><div class="mail-assignments"></div>';
  const group={name,el,heading:el.firstElementChild,fallback:el.querySelector('.mail-assignee-fallback'),list:el.lastElementChild};
  paintPortrait(group);
  return group;
}
function makeRow(assignment){
  const el=document.createElement('article');
  el.className='mail-assignment';
  el.innerHTML='<button class="mail-request" type="button" aria-haspopup="dialog"></button>'+
    '<button class="mail-reply" type="button" aria-haspopup="dialog" title="Open reply" hidden></button>';
  const row={el,request:el.firstElementChild,reply:el.lastElementChild,history:null,assignment};
  row.request.addEventListener('click',()=>openThread(row.assignment,row.request));
  row.reply.addEventListener('click',()=>openThread(row.assignment,row.reply,row.assignment.replies.at(-1)));
  bindRoute(row.request,()=>assignmentRoute(row.assignment));
  bindRoute(row.reply,()=>messageRoute(row.assignment.replies.at(-1)));
  return row;
}
function paintRow(row,assignment){
  row.assignment=assignment;
  const {request,replies}=assignment;
  const latest=replies.at(-1),awaitsReply=expectsReply(assignment);
  const state=!assignment.recipient?'No direct recipient':!awaitsReply?'Self-addressed notice':
    latest?'Reply received':'Awaiting a reply';
  const sender=request.sender||'Unknown sender';
  const urgency=[request,latest].some(m=>m&&highImportance(m.importance));
  const direct=assignmentRoute(assignment).recipients;
  const recipients=(timeline&&!direct.length?recipientNames(request):direct).join(', ')||'no direct recipient';
  const action=awaitsReply?'Open request':'Open message';
  const label=`${action}: ${titleFor(request)}, ${sender} to ${recipients}. ${state}${urgency?', high importance':''}`;
  if(row.label!==label){
    row.request.setAttribute('aria-label',label);
    row.label=label;
  }
  const title=action+'. '+state;
  if(row.request.title!==title)row.request.title=title;
  const parties=timeline?'<span class="mail-route">'+E(sender)+icon('arrow')+E(recipients)+'</span>'
    :icon('from')+'<span>'+E(sender)+'</span>';
  const senderLine='<span class="mail-requester">'+parties+timeHtml(request.ts)+'</span>';
  const delivery=timeline?'<span class="mail-timeline-start">'+senderLine+
    (request.excerpt?'<span class="thread-excerpt">'+E(request.excerpt)+'</span>':'')+'</span>':senderLine;
  const requestHtml='<span class="mail-state'+(latest?' replied':'')+(urgency?' important':'')+
    (awaitsReply?'':' no-reply')+'" aria-hidden="true"></span>'+
    '<span class="mail-subject">'+E(titleFor(request))+'</span><span class="mail-open">'+icon('open')+'</span>'+delivery;
  if(row.requestHtml!==requestHtml){row.request.innerHTML=requestHtml;row.requestHtml=requestHtml;}
  if(timeline){
    paintTimelineReplies(row);
    return;
  }
  if(row.reply.hidden!==!latest)row.reply.hidden=!latest;
  if(!latest)return;
  const replyHtml='<span class="mail-route">'+E(latest.sender||'Unknown sender')+
    icon('arrow')+E(recipientNames(latest).join(', '))+'</span>'+timeHtml(latest.ts)+
    '<span class="mail-reply-excerpt">'+E(latest.excerpt||titleFor(latest))+'</span>';
  if(row.replyHtml!==replyHtml){row.reply.innerHTML=replyHtml;row.replyHtml=replyHtml;}
}
function paintTimelineReplies(row){
  const entries=row.entries=threadEntries(row.assignment);
  if(row.history)row.history.hidden=!entries.length;
  if(!entries.length)return;
  if(!row.history){
    row.history=document.createElement('div');
    row.history.className='mail-timeline-replies';
    row.el.appendChild(row.history);
    row.history.addEventListener('click',event=>{
      const button=event.target.closest('[data-reply]');
      const message=button&&row.entries.find(m=>m.key===button.dataset.reply);
      if(message)openThread(row.assignment,button,message);
    });
  }
  const markup=entries.map(replyHtml).join('');
  if(row.history.markup===markup)return;
  const focused=row.history.contains(document.activeElement)?document.activeElement.dataset.reply:null;
  row.history.innerHTML=markup;
  row.history.markup=markup;
  for(const button of row.history.children){
    button.title='Open message';
    bindRoute(button,()=>messageRoute(row.entries.find(m=>m.key===button.dataset.reply)));
    if(button.dataset.reply===focused)button.focus({preventScroll:true});
  }
}
function reconcile(parent,want){
  const keep=new Set(want);
  for(const old of [...parent.children]){if(!keep.has(old))old.remove();}
  let next=parent.firstElementChild;
  for(const node of want){
    if(node!==next)parent.insertBefore(node,next);
    next=node.nextElementSibling;
  }
}
function originFor(sender){
  const selector='[data-agent="'+CSS.escape(sender)+'"]';
  const node=(!graph.hasAttribute('hidden')&&graph.querySelector(selector))
    ||document.querySelector('#roster .agent'+selector+':not(.filtered-out,.folded-out)');
  const rect=node?.getBoundingClientRect?.();
  return rect?.width&&rect.height?rect:null;
}

function renderMail({animate=false,fresh=new Set()}={}){
  filterButton.toggleAttribute('data-filtered',Boolean(activeFilter||waitingOnly));
  const visible=assignmentsForView(visibleAssignments());
  const focus=cardsEl.contains(document.activeElement)?document.activeElement:null;
  const moving=animate?OC.railPositions([
    ...[...groupsByName.values()].map(group=>group.el),
    ...[...rowsByKey.values()].map(row=>row.el)
  ],listEl):null;
  const groups=new Map(),used=new Set(),arrivals=[],timelineRows=[];
  for(const a of visible){
    const existing=rowsByKey.get(a.key);
    const row=existing||makeRow(a);
    const lastReply=existing?.assignment.replies.at(-1)?.key;
    const latest=a.replies.at(-1);
    rowsByKey.set(a.key,row);
    used.add(a.key);
    paintRow(row,a);
    if(timeline){
      timelineRows.push(row.el);
      if(!existing&&fresh.has(a.request.key))arrivals.push([row.el,a.request.sender]);
      else if(latest&&lastReply!==latest.key&&fresh.has(latest.key)){
        const button=row.history?.querySelector('[data-reply="'+CSS.escape(latest.key)+'"]');
        if(button)arrivals.push([button,latest.sender]);
      }
      continue;
    }
    const newGroup=!groupsByName.has(a.recipient);
    const group=groupsByName.get(a.recipient)||makeGroup(a.recipient);
    groupsByName.set(a.recipient,group);
    if(!groups.has(group))groups.set(group,[]);
    groups.get(group).push(row.el);
    if((newGroup||!existing)&&fresh.has(a.request.key))arrivals.push([newGroup?group.el:row.el,a.request.sender]);
    else if(latest&&lastReply!==latest.key&&fresh.has(latest.key))arrivals.push([row.reply,latest.sender]);
  }
  for(const [group,rows] of groups)reconcile(group.list,rows);
  const visibleGroups=new Set(groups.keys());
  for(const [name,group] of groupsByName)if(!visibleGroups.has(group))groupsByName.delete(name);
  for(const key of rowsByKey.keys())if(!used.has(key))rowsByKey.delete(key);
  const display=timeline?timelineRows:[...groups.keys()].map(group=>group.el);
  if(!display.length){
    const empty=cardsEl.querySelector('.mailempty')||document.createElement('p');
    empty.className='mailempty';
    const text=activeFilter||waitingOnly?'No matching requests':'No agent mail yet';
    if(empty.textContent!==text)empty.textContent=text;
    display.push(empty);
  }
  reconcile(cardsEl,display);
  if(focus?.isConnected&&focus!==document.activeElement)focus.focus({preventScroll:true});
  else if(focus&&!cardsEl.contains(document.activeElement)){hoveredRoute=focusedRoute=null;emitRoute();}
  if(moving)OC.railMoveRows(moving);
  for(const [node,sender] of arrivals)OC.railArrive(node,originFor(sender),listEl);
}
function ingest(list,{live=false}={}){
  const fresh=new Set();
  for(const raw of Array.isArray(list)?list:[]){
    const next=normalizeMessage(raw);
    if(!next)continue;
    if(live&&seeded&&!byId.has(next.key))fresh.add(next.key);
    mergeMessage(next);
  }
  renderMail({animate:fresh.size>0,fresh});
}
/* Escape the complete source before introducing our own small, fixed tag set.
   Link destinations and raw HTML are never emitted into the DOM. */
function plainMarkdownLinks(source){
  let result='';
  let index=0;
  while(index<source.length){
    const image=source[index]==='!'&&source[index+1]==='[';
    const labelStart=image?index+1:index;
    if(source[labelStart]==='['){
      const labelEnd=source.indexOf(']',labelStart+1);
      if(labelEnd>=0&&source[labelEnd+1]==='('){
        let cursor=labelEnd+2;
        let depth=1;
        while(cursor<source.length&&depth){
          if(source[cursor]==='\\'){cursor+=2;continue;}
          if(source[cursor]==='(')depth++;
          else if(source[cursor]===')')depth--;
          cursor++;
        }
        if(depth===0){
          result+=source.slice(labelStart+1,labelEnd);
          index=cursor;
          continue;
        }
      }
    }
    result+=source[index];
    index++;
  }
  return result;
}

function inlineMarkdown(escaped){
  const code=[];
  let value=escaped.replace(/`([^`\n]+)`/g,(_,contents)=>{
    const index=code.push('<code>'+contents+'</code>')-1;
    return '\uE000'+index+'\uE001';
  });
  value=plainMarkdownLinks(value);
  value=value.replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');
  value=value.replace(/__([^_\n]+)__/g,'<strong>$1</strong>');
  return value.replace(/\uE000(\d+)\uE001/g,(_,index)=>code[Number(index)]||'');
}

function renderMarkdown(source){
  const escaped=E(text(source).replace(/\r\n?/g,'\n'));
  const lines=escaped.split('\n');
  const html=[];
  let fenced=false;
  let code=[];
  const flushCode=()=>{
    html.push('<pre><code>'+code.join('\n')+'</code></pre>');
    code=[];
  };
  lines.forEach(line=>{
    if(/^\s*```/.test(line)){
      if(fenced){flushCode();fenced=false;}else{fenced=true;code=[];}
      return;
    }
    if(fenced){code.push(line);return;}
    const heading=line.match(/^(#{1,6})\s+(.+)$/);
    if(heading){
      const level=Math.min(heading[1].length,4);
      html.push('<h'+level+'>'+inlineMarkdown(heading[2])+'</h'+level+'>');
      return;
    }
    const unordered=line.match(/^\s*[-+*]\s+(.+)$/);
    if(unordered){
      html.push('<div class="md-list-row"><span class="md-marker">•</span><span>'+inlineMarkdown(unordered[1])+'</span></div>');
      return;
    }
    const ordered=line.match(/^\s*(\d+)[.)]\s+(.+)$/);
    if(ordered){
      html.push('<div class="md-list-row"><span class="md-marker">'+E(ordered[1])+'.</span><span>'+inlineMarkdown(ordered[2])+'</span></div>');
      return;
    }
    if(!line.trim()){html.push('<div class="md-space"></div>');return;}
    html.push('<p>'+inlineMarkdown(line)+'</p>');
  });
  if(fenced)flushCode();
  return html.join('');
}

function routeHtml(message){
  const recipients=message.recipients.map(recipient=>'<span'+
    (recipient.kind==='to'?'':' title="'+E(recipient.kind.toUpperCase())+'"')+'>'+E(recipient.name)+'</span>');
  return '<div class="drawer-route"><span>'+E(message.sender||'Unknown sender')+'</span>'+icon('arrow')+
    '<span class="drawer-recipients">'+(recipients.join(', ')||'No direct recipient')+'</span>'+timeHtml(message.ts)+'</div>';
}
function detailHtml(message){
  const body=message.body_md??message.excerpt;
  return routeHtml(message)+'<h2>'+E(titleFor(message))+'</h2>'+
    '<div class="mail-md">'+(body?renderMarkdown(body):'<p class="md-empty">No message text</p>')+'</div>';
}
function replyHtml(message){
  return '<button type="button" class="thread-item" data-reply="'+E(message.key)+'">'+routeHtml(message)+
    '<span class="thread-excerpt">'+E(message.excerpt||titleFor(message))+'</span></button>';
}
function threadEntries(assignment){
  return [...assignment.followups,...assignment.replies].sort(chronological);
}

function drawerLinkSource(assignment){
  if(!assignment.replies.length&&!assignment.followups.length)return '';
  const threaded=Boolean(assignment.request.thread);
  const label=threaded?'Linked by thread':'Linked by reverse delivery direction (inferred)';
  return '<span class="drawer-link-source" role="img" title="'+label+'" aria-label="'+label+'">'+
    icon(threaded?'thread':'reverse')+'</span>';
}

function renderDrawer({initial=false}={}){
  const state=drawer;
  if(!state)return;
  paintGraph();
  emitRoute();
  const focused=document.activeElement;
  const focusAction=drawerHead.contains(focused)?focused.dataset.action:'';
  const focusReply=drawerChain.contains(focused)?focused.dataset.reply:'';
  const {message,assignment,entries}=state;
  const head=drawerLinkSource(assignment)+(message?control('thread','Back to request','thread'):'')+
    control('close','Close mail','close');
  if(drawerHead.markup!==head){drawerHead.innerHTML=head;drawerHead.markup=head;}
  const body=detailHtml(message||state.request||assignment.request)+
    (state.failed?'<p class="drawer-empty" role="status">Could not load the full message. Reopen it to retry.</p>':'');
  if(drawerBody.markup!==body){drawerBody.innerHTML=body;drawerBody.markup=body;}
  drawerChain.hidden=Boolean(message||!entries.length);
  const chain=entries.map(replyHtml).join('');
  if(drawerChain.markup!==chain){
    drawerChain.innerHTML=chain;
    drawerChain.markup=chain;
    drawerChain.querySelectorAll('[data-reply]').forEach(button=>{
      bindRoute(button,()=>messageRoute(drawer?.entries.find(m=>m.key===button.dataset.reply)));
    });
  }
  if(initial||!focused?.isConnected){
    const next=(focusAction&&drawerHead.querySelector('[data-action="'+focusAction+'"]'))||
      (!drawerChain.hidden&&focusReply&&[...drawerChain.children].find(button=>button.dataset.reply===focusReply))||
      drawerHead.querySelector('[data-action="close"]');
    next.focus({preventScroll:true});
  }
}
function anchorClip(anchor){
  if(!anchor?.isConnected||!anchor.getClientRects().length)return null;
  const a=anchor.getBoundingClientRect(),b=drawerEl.getBoundingClientRect();
  return `inset(${Math.max(0,a.top-b.top)}px ${Math.max(0,b.right-a.right)}px ${Math.max(0,b.bottom-a.bottom)}px ${Math.max(0,a.left-b.left)}px round 8px)`;
}
function morphDrawer(anchor,open){
  clearTimeout(drawerMotionTimer);
  drawerMotion?.cancel();
  drawerEl.inert=!open;
  if(document.hidden){
    drawerEl.hidden=!open;
    return;
  }
  const origin=anchorClip(anchor);
  const frames=!motion.matches&&origin
    ?[{clipPath:origin,opacity:.35},{clipPath:'inset(0 round 0px)',opacity:1}]
    :[{opacity:0},{opacity:1}];
  const duration=motion.matches?90:open?260:215;
  const animation=drawerEl.animate(open?frames:frames.reverse(),{
    duration,easing:'cubic-bezier(.2,.8,.2,1)',fill:'both'
  });
  drawerMotion=animation;
  const finish=()=>{
    if(drawerMotion!==animation)return;
    clearTimeout(drawerMotionTimer);
    if(!open&&!drawer)drawerEl.hidden=true;
    drawerMotion=null;
    animation.cancel();
  };
  animation.onfinish=finish;
  // A hidden or occluded compositor can suspend frame callbacks mid-close.
  drawerMotionTimer=setTimeout(finish,duration+75);
}
async function fetchJson(url){
  try{
    const response=await fetch(url,{cache:'no-store'});
    if(!response.ok)return null;
    const data=await response.json();
    return data&&data.ok!==false?data:null;
  }catch(_){return null;}
}
async function messageBody(message){
  if(message.body_md!==null)return message;
  const data=await fetchJson('/telemetry/mail/message?id='+encodeURIComponent(message.id));
  const normalized=normalizeMessage(data?.message);
  return normalized?mergeMessage(normalized):null;
}
async function openThread(assignment,anchor,selectedMessage=null){
  setFilterOpen(false);
  const entries=threadEntries(assignment);
  const state={assignment,anchor,request:assignment.request,entries,message:null,failed:false};
  drawer=state;
  hoveredRoute=focusedRoute=null;
  drawerEl.hidden=false;
  drawerEl.inert=false;
  listEl.inert=true;
  if(selectedMessage)openReply(selectedMessage);
  else renderDrawer({initial:true});
  drawerScroll.scrollTop=0;
  morphDrawer(anchor,true);

  const threadFetch=assignment.request.thread?fetchJson('/telemetry/mail/thread?thread_id='+
    encodeURIComponent(assignment.request.thread)+'&limit=50'):null;
  const request=await messageBody(assignment.request);
  if(drawer!==state)return;
  state.request=request||assignment.request;
  state.requestFailed=!request;
  if(!state.message){
    state.failed=state.requestFailed;
    renderDrawer();
  }
  const thread=await threadFetch;
  if(drawer!==state)return;
  let fullRequest=request,original=assignment.request;
  if(Array.isArray(thread?.messages)){
    for(const raw of thread.messages){
      const normalized=normalizeMessage(raw);
      if(normalized)mergeMessage(normalized);
    }
    const updatedAssignments=assignmentsForView(assignments());
    const updated=updatedAssignments.find(a=>a.key===assignment.key)||
      updatedAssignments.find(a=>assignmentRoute(a).recipients.includes(assignment.request.sender)&&
        a.replies.some(m=>m.key===assignment.request.key));
    if(updated){
      original=updated.request;
      if(original.key!==assignment.request.key)fullRequest=await messageBody(original);
      if(drawer!==state)return;
      state.assignment=updated;
      state.entries=threadEntries(updated);
    }
  }
  state.request=fullRequest||original;
  state.requestFailed=!fullRequest;
  if(!state.message){
    state.failed=state.requestFailed;
  }
  renderDrawer();
}
async function openReply(item){
  if(!item)return;
  const state=drawer,token=++replyRequest;
  state.message=item;state.failed=false;
  renderDrawer({initial:true});
  drawerScroll.scrollTop=0;
  const message=await messageBody(item);
  if(token!==replyRequest||drawer!==state)return;
  state.message=message||item;state.failed=!message;
  renderDrawer();
}
function closeDrawer(restoreFocus=true){
  if(!drawer)return;
  const {anchor}=drawer;
  ++replyRequest;
  drawer=null;
  hoveredRoute=focusedRoute=null;
  paintGraph();
  emitRoute();
  morphDrawer(anchor,false);
  listEl.inert=false;
  renderMail();
  if(restoreFocus)(anchor?.isConnected?anchor:filterButton).focus({preventScroll:true});
}
drawerEl.addEventListener('click',event=>{
  if(!drawer)return;
  const button=event.target.closest('button');
  if(button?.dataset.action==='close')closeDrawer();
  else if(button?.dataset.action==='thread'){
    ++replyRequest;drawer.message=null;drawer.failed=drawer.requestFailed;
    renderDrawer({initial:true});drawerScroll.scrollTop=0;
  }else if(button?.dataset.reply!==undefined)openReply(drawer.entries.find(item=>item.key===button.dataset.reply));
});

document.addEventListener('keydown',event=>{
  if(event.key!=='Escape'||document.querySelector('.overlay.on'))return;
  if(drawer){event.preventDefault();event.stopPropagation();closeDrawer();}
  else if(!filterEl.hidden){event.preventDefault();event.stopPropagation();setFilterOpen(false,true);}
},true);
document.addEventListener('oc:mail',event=>ingest(event.detail?.messages,{live:true}));
document.addEventListener('oc:agents',()=>groupsByName.forEach(paintPortrait));
document.addEventListener('oc:filter-agent',event=>selectMailFilter(event.detail?.agent));
document.addEventListener('oc:focus-agent',event=>selectMailFilter(event.detail?.name,{requireExisting:true}));
paintView();
ingest(OC.mailBacklog());
fetchJson('/telemetry/mail/recent?limit=40').then(data=>{
  if(Array.isArray(data?.messages))ingest(data.messages);
  seeded=true;
});
})();
