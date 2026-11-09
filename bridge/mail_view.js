/* ── agent-mail rail (right rail, below the orrery) ──
   Owns <div id="mail"> and everything rendered inside it.
   Inputs (read-only):
     window.OC — { esc, relTime, jumpToAgent, renderPeerAvatar, agents(), mailBacklog() }
     document event 'oc:mail' detail:{messages} — NEW, deduped live messages.
     document event 'oc:focus-agent' detail:{name} — follow active terminal pane.
   All API and event message fields are untrusted. Rendering is escape-first. */
(function(){
'use strict';
const OC=window.OC;
const mailEl=document.getElementById('mail');
if(!mailEl||!OC)return;

const byId=new Map();
const mailItems=[];
let activeFilter='';
let drawerOpen=false;
let drawerMode='detail';
let currentMessage=null;
let lastTrigger=null;
let messageRequest=0;
let threadRequest=0;
let threadKey='';
let threadItems=[];
let threadReady=false;
let threadLoading=false;
let showThreadWhenReady=false;

mailEl.classList.add('mailview-host');
mailEl.innerHTML='<div class="mailview-list"><div class="mailfilters" role="toolbar" aria-label="Filter agent mail"></div>'+
  '<div class="mailcards"></div></div><aside class="maildrawer" aria-hidden="true"></aside>';
const listEl=mailEl.querySelector('.mailview-list');
const filterEl=mailEl.querySelector('.mailfilters');
const cardsEl=mailEl.querySelector('.mailcards');
const drawerEl=mailEl.querySelector('.maildrawer');

function E(value){return OC.esc(value==null?'':String(value));}
function text(value){return value==null?'':String(value);}
function keyOf(value){return value==null?'':String(value);}
function highImportance(value){return value==='high'||value==='urgent';}
function threadKeyOf(value){return value==null||value===''?'':String(value);}

function normalizeRecipient(value){
  if(value==null)return null;
  if(typeof value==='string'||typeof value==='number')return{name:text(value),kind:'to'};
  const name=text(value.name==null?value.recipient:value.name);
  if(!name)return null;
  return{name,kind:text(value.kind)||'to'};
}

/* The live route expands one row per recipient (`recipient`), while /recent
   returns a `recipients` array. Keep both shapes on one internal contract. */
function normalizeMessage(raw){
  if(!raw||raw.id==null)return null;
  const recipients=[];
  const source=Array.isArray(raw.recipients)?raw.recipients:[];
  source.forEach(value=>{const recipient=normalizeRecipient(value);if(recipient)recipients.push(recipient);});
  if(raw.recipient!=null){
    const recipient=normalizeRecipient(raw.recipient);
    if(recipient&&!recipients.some(r=>r.name===recipient.name&&r.kind===recipient.kind))recipients.push(recipient);
  }
  const parsedTs=Number(raw.ts);
  return{
    id:raw.id,key:keyOf(raw.id),
    ts:Number.isFinite(parsedTs)?parsedTs:0,
    sender:text(raw.sender),
    recipients,
    subject:text(raw.subject),
    excerpt:text(raw.excerpt),
    importance:text(raw.importance),
    thread_id:raw.thread_id==null||raw.thread_id===''?null:raw.thread_id,
    body_md:Object.prototype.hasOwnProperty.call(raw,'body_md')?text(raw.body_md):null,
  };
}

function mergeRecipients(left,right){
  const merged=left.slice();
  right.forEach(recipient=>{
    if(!merged.some(r=>r.name===recipient.name&&r.kind===recipient.kind))merged.push(recipient);
  });
  return merged;
}

function mergeMessage(next){
  const prior=byId.get(next.key);
  if(!prior){
    byId.set(next.key,next);
    mailItems.push(next);
    return next;
  }
  const merged={
    ...prior,
    ts:next.ts||prior.ts,
    sender:next.sender||prior.sender,
    recipients:mergeRecipients(prior.recipients,next.recipients),
    subject:next.subject||prior.subject,
    excerpt:next.excerpt||prior.excerpt,
    importance:next.importance||prior.importance,
    thread_id:next.thread_id==null?prior.thread_id:next.thread_id,
    body_md:next.body_md==null?prior.body_md:next.body_md,
  };
  byId.set(next.key,merged);
  const index=mailItems.indexOf(prior);
  if(index>=0)mailItems[index]=merged;
  return merged;
}

function newestFirst(){
  return mailItems.slice().sort((a,b)=>(b.ts-a.ts)||b.key.localeCompare(a.key));
}

function recipientNames(message){
  const names=[];
  message.recipients.forEach(recipient=>{if(recipient.name&&!names.includes(recipient.name))names.push(recipient.name);});
  return names;
}

function messageIncludesAgent(message,agent){
  return !agent||message.sender===agent||message.recipients.some(recipient=>recipient.name===agent);
}

function agentsByRecency(items){
  const names=[];
  items.forEach(message=>{
    [message.sender,...recipientNames(message)].forEach(name=>{if(name&&!names.includes(name))names.push(name);});
  });
  return names;
}
function visibleFilterAgents(items,selected=''){
  const agents=agentsByRecency(items);
  const visible=agents.slice(0,8);
  if(selected&&agents.includes(selected)&&!visible.includes(selected)){
    visible[Math.max(0,visible.length-1)]=selected;
  }
  return visible;
}
/* The rail holds only the latest messages, so an agent that has been quiet
   (a resident bot, say) is not in it. Ask the backend for that agent's own
   recent mail before deciding there is nothing to show (2026-09-25). */
const fetchedAgents=new Set();
async function loadAgentMail(agent){
  if(!agent||fetchedAgents.has(agent))return;
  fetchedAgents.add(agent);
  try{
    const data=await fetchJson('/telemetry/mail/recent?limit=40&agent='+encodeURIComponent(agent));
    if(data&&Array.isArray(data.messages))ingest(data.messages);
  }catch(_){fetchedAgents.delete(agent);}
}
async function selectMailFilter(agent,{requireExisting=false}={}){
  const next=text(agent);
  const known=()=>agentsByRecency(newestFirst()).includes(next);
  if(next&&!known())await loadAgentMail(next);
  if(requireExisting&&!known())return false;
  activeFilter=next;
  renderMail();
  return true;
}

function relativeLabel(ts){
  const relative=OC.relTime(ts);
  return relative?relative+' ago':'time unavailable';
}

function exactTime(ts){
  if(!ts)return'';
  const date=new Date(ts*1000);
  if(Number.isNaN(date.getTime()))return'';
  const two=value=>String(value).padStart(2,'0');
  return date.getFullYear()+'-'+two(date.getMonth()+1)+'-'+two(date.getDate())+' '+
    two(date.getHours())+':'+two(date.getMinutes())+':'+two(date.getSeconds());
}

function renderFilters(items){
  const agents=agentsByRecency(items);
  const visible=visibleFilterAgents(items,activeFilter);
  const choices=['',...visible];
  filterEl.innerHTML='';
  choices.forEach(agent=>{
    const button=document.createElement('button');
    button.type='button';
    button.className='mailchip'+(activeFilter===agent?' on':'');
    button.setAttribute('aria-pressed',String(activeFilter===agent));
    button.innerHTML=agent?E(agent):'ALL';
    button.addEventListener('click',()=>selectMailFilter(agent));
    filterEl.appendChild(button);
  });
  const overflow=agents.length-visible.length;
  if(overflow>0){
    const more=document.createElement('span');
    more.className='mailchip mailchip-more';
    more.innerHTML='+'+E(overflow);
    filterEl.appendChild(more);
  }
}

function appendPeer(container,name){
  const peer=document.createElement('span');peer.className='mail-peer';peer.dataset.peerName=name;
  const label=document.createElement('span');label.className='mail-peer-name';label.textContent=name;
  peer.appendChild(label);container.appendChild(peer);
}
function refreshPeerAvatars(){
  if(typeof OC.renderPeerAvatar!=='function')return;
  cardsEl.querySelectorAll('.mail-peer').forEach(peer=>{
    const previous=peer.querySelector('.conversation-avatar'),avatar=OC.renderPeerAvatar(peer.dataset.peerName,previous);
    if(avatar!==previous){if(previous)previous.remove();if(avatar)peer.prepend(avatar);}
  });
  layoutRecipients();
}

let recipientFrame=null;
const recipientObserver=typeof ResizeObserver==='function'?new ResizeObserver(scheduleRecipientLayout):null;
function scheduleRecipientLayout(){
  if(recipientFrame!==null)return;
  recipientFrame=requestAnimationFrame(()=>{recipientFrame=null;layoutRecipients();});
}
function layoutRecipients(){
  for(const head of cardsEl.querySelectorAll('.mtop')){
    const from=head.querySelector('.from'),to=head.querySelector('.to'),more=to.querySelector('.mail-more');
    const peers=[...to.querySelectorAll('.mail-peer')],multiple=peers.length>1;
    to.classList.remove('is-stacked');more.hidden=true;
    peers.forEach(peer=>{peer.hidden=false;peer.classList.remove('is-first');});
    const natural=peer=>{
      const range=document.createRange();range.selectNodeContents(peer.querySelector('.mail-peer-name'));
      return range.getBoundingClientRect().width+(peer.querySelector('.conversation-avatar')?22:0);
    };
    const gap=parseFloat(getComputedStyle(head).columnGap)||0;
    const available=Math.max(0,head.clientWidth-head.querySelector('.arrow').offsetWidth-head.querySelector('.imp').offsetWidth-gap*3);
    const sender=natural(from.querySelector('.mail-peer'));
    const names=peers.reduce((sum,peer)=>sum+natural(peer),0)+
      [...to.querySelectorAll('.mail-separator')].reduce((sum,part)=>sum+part.getBoundingClientRect().width,0);
    if(multiple&&sender+names>available){
      to.classList.add('is-stacked');more.hidden=false;more.textContent='+'+peers.length;
      const counter=more.getBoundingClientRect().width;
      from.style.maxWidth=Math.max(0,Math.min(sender,available-counter-3))+'px';
      const room=Math.max(0,to.clientWidth-3),known=peers.filter(peer=>peer.querySelector('.conversation-avatar'));
      const extent=n=>n?18+(n-1)*14+3:0;
      let count=known.length;
      if(count!==peers.length||extent(count)>room){
        count=Math.max(0,Math.min(count,Math.floor((room-counter-4-21)/14)+1));
      }
      const shown=new Set(known.slice(0,count));
      peers.forEach(peer=>{peer.hidden=!shown.has(peer);});
      if(count)known[0].classList.add('is-first');
      const hidden=peers.filter(peer=>!shown.has(peer));
      more.hidden=!hidden.length;more.textContent='+'+hidden.length;
      more.title=hidden.map(peer=>peer.dataset.peerName).join(', ');
      more.classList.toggle('is-only',count===0);
    }else{
      const minimum=peers[0]?.querySelector('.conversation-avatar')?34:12;
      from.style.maxWidth=Math.max(0,Math.min(sender,available-minimum-3))+'px';
    }
  }
}
document.fonts?.ready.then(scheduleRecipientLayout);
document.fonts?.addEventListener('loadingdone',scheduleRecipientLayout);

function renderCards(items){
  recipientObserver?.disconnect();
  cardsEl.innerHTML='';
  const visible=items.filter(message=>messageIncludesAgent(message,activeFilter));
  if(!visible.length){
    const empty=document.createElement('div');
    empty.className='mailempty';
    empty.innerHTML=activeFilter?'no loaded mail involving '+E(activeFilter)+'.':
      'waiting for agent-mail…<br>messages appear here as agents talk.';
    cardsEl.appendChild(empty);
    return;
  }
  visible.forEach((message,index)=>{
    const card=document.createElement('button');
    const recipients=recipientNames(message);
    const importance=message.importance||'normal';
    card.type='button';
    // first paint: staggered rise for everything. After boot, only a card
    // never shown before gets the landing+ember entrance — the rest keep
    // still (renderMail FLIPs them to their new slots instead).
    const fresh=!shownIds.has(message.id);
    if(fresh)shownIds.add(message.id);
    card.className='msg '+(booted?(fresh?'landing':'settled'):'');
    card.dataset.mid=message.id;
    card.style.animationDelay=booted?'0s':(Math.min(index,12)*.03)+'s';
    card.innerHTML='<span class="mtop"><span class="from"></span>'+
      '<span class="arrow">→</span><span class="to"></span>'+
      '<span class="imp '+(highImportance(importance)?'hi':'')+'">'+E(importance)+'</span></span>'+
      '<span class="body">'+E(message.subject||message.excerpt||'(no subject)')+'</span>'+
      '<span class="time">'+E(relativeLabel(message.ts))+'</span>';
    appendPeer(card.querySelector('.from'),message.sender||'unknown');
    const to=card.querySelector('.to');
    to.setAttribute('role','group');to.title=to.ariaLabel=recipients.join(', ')||'—';
    (recipients.length?recipients:['—']).forEach((name,index)=>{
      if(index){const separator=document.createElement('span');separator.className='mail-separator';separator.textContent=', ';to.appendChild(separator);}
      appendPeer(to,name);
    });
    const more=document.createElement('span');more.className='mail-more';more.hidden=true;more.setAttribute('aria-hidden','true');to.appendChild(more);
    card.addEventListener('click',()=>openMessage(message.id,card));
    cardsEl.appendChild(card);
    recipientObserver?.observe(card.querySelector('.mtop'));
  });
  refreshPeerAvatars();
}

let booted=false;
const shownIds=new Set();
function renderMail(){
  // FLIP: remember where every card sat, rebuild, then slide survivors from
  // their old slot to the new one — a fresh card pushes the list down
  // smoothly instead of the whole rail re-rising.
  const before=new Map();
  cardsEl.querySelectorAll('.msg[data-mid]').forEach(el=>
    before.set(el.dataset.mid,el.getBoundingClientRect().top));
  const items=newestFirst();
  renderFilters(items);
  renderCards(items);
  cardsEl.querySelectorAll('.msg.settled[data-mid]').forEach(el=>{
    const prev=before.get(el.dataset.mid);
    if(prev==null)return;
    const delta=prev-el.getBoundingClientRect().top;
    if(!delta)return;
    el.style.transition='none';
    el.style.transform=`translateY(${delta}px)`;
    requestAnimationFrame(()=>{
      el.style.transition='transform .45s cubic-bezier(.2,.8,.2,1)';
      el.style.transform='';
      el.addEventListener('transitionend',()=>{el.style.transition='';},{once:true});
    });
  });
  booted=true;
}

function ingest(list){
  let changed=false;
  (Array.isArray(list)?list:[]).forEach(raw=>{
    const message=normalizeMessage(raw);
    if(!message)return;
    mergeMessage(message);
    changed=true;
  });
  if(changed)renderMail();
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
  const recipients=message.recipients.length?message.recipients:
    [{name:'—',kind:'to'}];
  return '<div class="drawer-route"><span class="drawer-sender">'+E(message.sender||'unknown')+'</span>'+
    '<span class="drawer-arrow">→</span><span class="drawer-recipients">'+recipients.map(recipient=>
      '<span class="drawer-recipient"><span class="recipient-kind">'+E(recipient.kind||'to')+'</span> '+
      E(recipient.name)+'</span>').join('')+'</span></div>';
}

function detailHtml(message){
  const importance=message.importance||'normal';
  const body=message.body_md==null?message.excerpt:message.body_md;
  return routeHtml(message)+'<div class="drawer-meta"><span>'+E(exactTime(message.ts))+'</span>'+
    '<span>'+E(relativeLabel(message.ts))+'</span><span class="imp '+(highImportance(importance)?'hi':'')+'">'+
    E(importance)+'</span></div><h2>'+E(message.subject||'(no subject)')+'</h2>'+
    '<div class="mail-md">'+(body?renderMarkdown(body):'<p class="md-empty">(no body)</p>')+'</div>';
}

function threadHtml(){
  if(!threadReady)return'<div class="drawer-empty">loading thread…</div>';
  if(!threadItems.length)return'<div class="drawer-empty">no thread messages found.</div>';
  return '<div class="thread-chain">'+threadItems.map(message=>{
    const current=currentMessage&&message.key===currentMessage.key;
    return '<button type="button" class="thread-item '+(current?'current':'')+'" data-message-id="'+E(message.key)+'">'+
      '<span class="thread-top"><span class="thread-from">'+E(message.sender||'unknown')+'</span>'+
      '<span class="thread-time">'+E(relativeLabel(message.ts))+'</span></span>'+
      '<span class="thread-excerpt">'+E(message.excerpt||message.subject||'(no excerpt)')+'</span></button>';
  }).join('')+'</div>';
}

function renderDrawer(){
  if(!drawerOpen||!currentMessage)return;
  const hasThread=Boolean(threadKeyOf(currentMessage.thread_id));
  let threadLabel='thread';
  if(threadLoading)threadLabel='thread (…)';
  else if(threadReady)threadLabel='thread ('+threadItems.length+')';
  const modeButton=hasThread?(drawerMode==='thread'?
    '<button type="button" class="drawer-mode" data-action="detail">message</button>':
    '<button type="button" class="drawer-mode" data-action="thread">'+E(threadLabel)+'</button>'):'';
  drawerEl.innerHTML='<div class="drawer-head"><button type="button" class="drawer-back" data-action="close" title="Back to mail list">←</button>'+
    '<span class="drawer-label">'+(drawerMode==='thread'?'THREAD':'MESSAGE')+'</span>'+modeButton+'</div>'+
    '<div class="drawer-scroll">'+(drawerMode==='thread'?threadHtml():detailHtml(currentMessage))+'</div>';
  drawerEl.classList.add('open');
  drawerEl.setAttribute('aria-hidden','false');
}

function closeDrawer(){
  if(!drawerOpen)return;
  messageRequest++;
  threadRequest++;
  threadLoading=false;
  showThreadWhenReady=false;
  drawerOpen=false;
  drawerEl.classList.remove('open');
  drawerEl.setAttribute('aria-hidden','true');
  listEl.removeAttribute('aria-hidden');
  listEl.inert=false;
  if(lastTrigger&&lastTrigger.isConnected)lastTrigger.focus();
}

async function fetchJson(url){
  try{
    const response=await fetch(url,{cache:'no-store'});
    if(!response.ok)return null;
    const data=await response.json();
    return data&&data.ok!==false?data:null;
  }catch(error){
    return null;
  }
}

async function openMessage(id,trigger){
  const request=++messageRequest;
  const data=await fetchJson('/telemetry/mail/message?id='+encodeURIComponent(id));
  if(request!==messageRequest||!data||!data.message)return;
  const normalized=normalizeMessage(data.message);
  if(!normalized)return;
  const message=mergeMessage(normalized);
  const nextThreadKey=threadKeyOf(message.thread_id);
  if(nextThreadKey!==threadKey){
    threadRequest++;
    threadKey=nextThreadKey;
    threadItems=[];
    threadReady=false;
    threadLoading=false;
    showThreadWhenReady=false;
  }
  currentMessage=message;
  drawerMode='detail';
  if(trigger)lastTrigger=trigger;
  if(!drawerOpen){
    drawerOpen=true;
    listEl.setAttribute('aria-hidden','true');
    listEl.inert=true;
  }
  renderDrawer();
  const back=drawerEl.querySelector('.drawer-back');
  if(trigger&&back)back.focus();
  if(threadKey)loadThread(false);
}

async function loadThread(showWhenReady){
  if(!currentMessage||!threadKey)return;
  if(threadReady){
    if(showWhenReady){drawerMode='thread';renderDrawer();}
    return;
  }
  showThreadWhenReady=showThreadWhenReady||showWhenReady;
  if(threadLoading)return;
  threadLoading=true;
  renderDrawer();
  const requestedKey=threadKey;
  const request=++threadRequest;
  const data=await fetchJson('/telemetry/mail/thread?thread_id='+encodeURIComponent(currentMessage.thread_id)+'&limit=50');
  if(request!==threadRequest||requestedKey!==threadKey)return;
  threadLoading=false;
  if(data&&Array.isArray(data.messages)){
    threadItems=data.messages.map(normalizeMessage).filter(Boolean).sort((a,b)=>(a.ts-b.ts)||a.key.localeCompare(b.key));
    threadReady=true;
    if(showThreadWhenReady)drawerMode='thread';
  }
  showThreadWhenReady=false;
  renderDrawer();
}

drawerEl.addEventListener('click',event=>{
  const action=event.target.closest('[data-action]');
  if(action){
    if(action.dataset.action==='close')closeDrawer();
    else if(action.dataset.action==='detail'){drawerMode='detail';renderDrawer();}
    else if(action.dataset.action==='thread')loadThread(true);
    return;
  }
  const item=event.target.closest('.thread-item');
  if(!item)return;
  if(currentMessage&&item.dataset.messageId===currentMessage.key){
    drawerMode='detail';
    renderDrawer();
    return;
  }
  openMessage(item.dataset.messageId,null);
});

document.addEventListener('keydown',event=>{
  if(event.key!=='Escape'||!drawerOpen||document.querySelector('.overlay.on'))return;
  event.preventDefault();
  event.stopPropagation();
  closeDrawer();
},true);

document.addEventListener('oc:mail',event=>ingest(event.detail&&event.detail.messages));
document.addEventListener('oc:agents',refreshPeerAvatars);
document.addEventListener('oc:filter-agent',event=>{
  selectMailFilter(event.detail&&event.detail.agent);
});
document.addEventListener('oc:focus-agent',event=>{
  selectMailFilter(event.detail&&event.detail.name,{requireExisting:true});
});
ingest(OC.mailBacklog());   // live messages the thin poller saw before module load
renderMail();

/* /mail routes may not exist during a staggered merge. A 404 or any malformed
   response is intentionally ignored, leaving the live-only rail intact. */
fetchJson('/telemetry/mail/recent?limit=40').then(data=>{
  if(data&&Array.isArray(data.messages))ingest(data.messages);
});
})();
