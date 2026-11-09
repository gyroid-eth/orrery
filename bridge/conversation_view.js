/* Presentation only: source.read is replaceable for another provider/layout.
   This view renders inert text. Future file/preview navigation belongs in an
   explicit renderer/activation adapter, never arbitrary HTML or browser paths. */
(function(root){
  'use strict';
  const KEY='oc-term-conversation-enabled';
  const MAX_EVENTS=800,MAX_BYTES=2*1024*1024;
  // One Load earlier gathers about OLDER_EVENTS events with up to OLDER_READS
  // pages of OLDER_LIMIT (the server's cap). Tool calls and results are one
  // event each, and a page also stops at the server's scan window, so one
  // 80-event page went back only a few exchanges. MAX_EVENTS keeps two such
  // loads beside the first page before older rows are released.
  const OLDER_LIMIT=200,OLDER_EVENTS=300,OLDER_READS=4;
  // Failures about the record's binding: never keep content read with it.
  const BINDING_ERRORS=['history_changed','history_unconfirmed','history_stale','agent_unavailable','claude_next_phase','provider_unavailable',
    'dashboard_upgrade_required','dsh_decoder_unavailable','history_format_unsupported','history_unreadable','history_pending'];
  // A held poll keeps one browser connection busy; HTTP/1.1 allows about six
  // per host, which the rest of the cockpit also needs. Four, the same as the
  // server's cap, lets every pane of a 4-way split hold (measured with the
  // roster and graph polls, 2026-11-05: History waited <=4 ms for a
  // connection). Panes beyond it, or beyond the server's cap shared by every
  // tab, keep the plain interval.
  const WAIT_SECONDS=25,MAX_WAITING=4,waiting=new Set();
  // After a server-slot answer with new rows, the next read starts after this
  // gap: a record that changes all the time costs a few reads a second at most.
  const CONTENT_GAP_MS=250;
  // A held poll is background work. While any user operation is in flight in
  // this tab or another cockpit tab (BroadcastChannel), no poll is held: its
  // start ends every held poll, so the operation gets a browser connection,
  // and when the last one ends every reader plans again (plan() below).
  // What counts as a user operation is decided in one place, userRequest().
  // The longest an operation counts, ours or another tab's: the backend allows
  // a spawn 90 s (other actions 60 s). Past it an operation that never settled
  // (a closed tab, a frame navigated mid-request) stops holding History back.
  const OP_MAX_MS=90000;
  const ops={own:new Map(),foreign:new Map(),planners:new Set(),seq:0,tab:Math.random().toString(36).slice(2)};
  function yieldLocal(){for(const holder of waiting)holder.yield?.();}
  let holdChannel=null;
  function post(message){try{holdChannel?.postMessage(message);}catch(_){}}
  function opsActive(){
    const now=Date.now();
    for(const [id,at] of ops.foreign)if(now-at>OP_MAX_MS)ops.foreign.delete(id);
    for(const [id,at] of ops.own)if(now-at>OP_MAX_MS){ops.own.delete(id);post({type:'end',id});}
    return ops.own.size>0||ops.foreign.size>0;
  }
  function replanAll(){if(!opsActive())for(const plan of ops.planners)plan();}
  function beginOp(){
    const id=ops.tab+':'+(++ops.seq);ops.own.set(id,Date.now());yieldLocal();post({type:'begin',id});
    setTimeout(()=>endOp(id),OP_MAX_MS+50);  // one that never settles expires
    return id;
  }
  function endOp(id){if(id&&ops.own.delete(id)){post({type:'end',id});replanAll();}}
  try{
    holdChannel=new root.BroadcastChannel('orrery-history-holds');
    holdChannel.onmessage=({data})=>{
      if(data?.type==='begin'&&typeof data.id==='string'){
        ops.foreign.set(data.id,Date.now());yieldLocal();
        setTimeout(replanAll,OP_MAX_MS+50);  // a closed tab's operation expires
      }else if(data?.type==='end'&&typeof data.id==='string'){ops.foreign.delete(data.id);replanAll();}
      else if(data?.type==='who'){for(const id of ops.own.keys())post({type:'begin',id});}
    };
    // A tab opened later asks once for the operations already in flight.
    post({type:'who'});
  }catch(_){holdChannel=null;}
  // A closing tab ends its operations for the other tabs.
  root.addEventListener?.('pagehide',()=>{for(const id of ops.own.keys())post({type:'end',id});});
  // The user operations (README: History, "user operations"), by name. Same
  // origin only. Not History's own polls, not the terminal hover's path
  // probe, and not the dashboard frame's automatic error report (/api/jserr):
  // nobody asked for those. From the NETWORK frame: the dashboard's actions.
  const USER_POSTS=new Set(['/telemetry/open-url','/telemetry/reveal-path','/telemetry/open-ghostty',
    '/telemetry/spawn','/api/exit','/telemetry/conversation/reveal']);
  const FRAME_POSTS=new Set(['/api/jump','/api/kill','/api/exit','/api/annotate','/api/spawn','/api/reactivate']);
  const USER_GETS=new Set(['/telemetry/clipboard/files','/telemetry/conversation/preview']);
  function userRequest(input,init,{frame=false,origin=root.location?.origin}={}){
    try{
      const url=new URL(typeof input==='string'?input:input.url,root.location.href);
      const method=String(init?.method||(typeof input==='string'?'GET':input.method)||'GET').toUpperCase();
      if(url.origin!==origin)return false;
      if(method==='GET')return USER_GETS.has(url.pathname);
      return (frame?FRAME_POSTS:USER_POSTS).has(url.pathname);
    }catch(_){return false;}
  }
  // fetch for a page (the cockpit, the NETWORK frame): a user operation is
  // counted from its start until it settles, failed or aborted alike.
  // `endAll()` ends this wrapper's operations at once: a frame whose document
  // navigates away mid-request never settles its fetch.
  function trackFetch(nativeFetch,options={}){
    const mine=new Set();
    const end=id=>{mine.delete(id);endOp(id);};
    const tracked=(input,init)=>{
      if(!userRequest(input,init,options))return nativeFetch(input,init);
      const id=beginOp();mine.add(id);
      try{return Promise.resolve(nativeFetch(input,init)).finally(()=>end(id));}
      catch(error){end(id);throw error;}
    };
    tracked.endAll=()=>{for(const id of [...mine])end(id);};
    return tracked;
  }
  function yieldHolds(){const id=beginOp();queueMicrotask(()=>endOp(id));}
  function mount({getContext,source=new root.OrreryConversationSource.Source(),pollMs=4000,renderEvent=null,host=null,control=null,panelId='conversationPanel',bindToggle=true,onActivate=()=>{},onState=()=>{},focusControl=null,jumpToEvent=null,openExternalUrl=null}){
    let screen=host||document.querySelector('.screen');
    const toggle=control||document.getElementById('conversationToggle');
    const listeners=[];
    function listen(target,type,handler,options){if(!target)return;target.addEventListener(type,handler,options);listeners.push(()=>target.removeEventListener(type,handler,options));}
    const setting=document.getElementById('conversationEnabled');
    const panel=document.createElement('section');
    panel.className='conversation-panel';panel.id=panelId;panel.hidden=true;
    panel.setAttribute('aria-label','Read-only conversation history');
    panel.innerHTML='<div class="conversation-head"><div class="conversation-heading">'+
      '<h2 class="conversation-title">Conversation</h2><div class="conversation-subtitle"></div></div>'+
      '<button class="cockpit-control conversation-action conversation-expand" type="button" aria-pressed="false">Full width</button>'+
      '<button class="cockpit-control conversation-action conversation-close" type="button" aria-label="Close conversation history">Close</button></div>'+
      '<div class="conversation-toolbar"><span class="conversation-status" role="status"></span>'+
      '<button class="cockpit-control conversation-action conversation-retry" type="button" hidden>Retry</button></div>'+
      '<div class="conversation-body"><div class="conversation-thread"><div class="conversation-scroll" tabindex="0" aria-label="Conversation messages">'+
      '<button class="cockpit-control conversation-action conversation-older" type="button" hidden>Load earlier</button>'+
      '<div class="conversation-events"></div><div class="conversation-pending" role="status" aria-live="polite"></div><div class="conversation-empty"></div></div>'+
      '<div class="conversation-bottom"><span class="conversation-status conversation-position"></span>'+
      '<button class="cockpit-control conversation-action conversation-latest" type="button">Latest</button></div></div>'+
      '<aside class="conversation-preview" aria-label="Selected file preview" hidden></aside></div>';
    screen.appendChild(panel);
    const el=selector=>panel.querySelector(selector);
    const scroll=el('.conversation-scroll'),eventsEl=el('.conversation-events');
    let linkPress=null;
    listen(panel,'pointerdown',event=>{linkPress={x:event.clientX,y:event.clientY,selected:!root.getSelection()?.isCollapsed};});
    function activateLink(event){
      if(event.type==='auxclick'&&event.button!==1)return;
      const link=event.target.closest('a');if(!link||!panel.contains(link))return;
      clearTimeout(jumpTimer);event.stopPropagation();
      const selected=!root.getSelection()?.isCollapsed;
      if(event.detail>1||selected||event.detail>0&&(linkPress?.selected||linkPress&&Math.hypot(event.clientX-linkPress.x,event.clientY-linkPress.y)>5)){
        event.preventDefault();return;
      }
      // Mail links retain the browser's native handling. HTTP links use the
      // same opener as the terminal, including modified clicks in the app.
      if(!/^https?:$/i.test(link.protocol))return;
      event.preventDefault();
      if(openExternalUrl)openExternalUrl(link.href);
      else root.open(link.href,'_blank','noopener,noreferrer');
    }
    listen(panel,'click',activateLink);listen(panel,'auxclick',activateLink);
    const status=el('.conversation-toolbar .conversation-status'),empty=el('.conversation-empty');
    const earlier=el('.conversation-older'),retry=el('.conversation-retry'),latest=el('.conversation-latest');
    let fullWidth=false,tableMutating=false,tableFrame=0;
    const tablePositions=new Map();
    let submissions=[],submissionTimer=0,flashTimer=0,readSequence=0;
    const observedIds=new Set(),matchedSubmissions=new Set(),pendingEl=el('.conversation-pending');
    const normalizePrompt=text=>text.replace(/\s+/gu,' ').trim();
    function renderSubmissions(){
      clearTimeout(submissionTimer);submissionTimer=0;pendingEl.replaceChildren();
      let next=Infinity;
      for(const item of submissions){
        const row=document.createElement('article');row.className='conversation-submission';row.dataset.submissionId=item.id;
        const label=document.createElement('div');label.className='conversation-byline';
        const elapsed=Date.now()-item.at;
        label.textContent='Sent → '+item.name+' · '+(item.unmatched?'Record not matched':elapsed>=60000?'Not recorded yet':'Awaiting record');
        const text=document.createElement('p');text.className='conversation-text';
        if(root.OrreryConversationMarkdown)root.OrreryConversationMarkdown.renderText(item.preview,text);else text.textContent=item.preview;
        const note=document.createElement('div');note.className='conversation-submission-note';
        note.textContent=item.unmatched?'A user record arrived after this send, but it cannot be matched to this text. Check the conversation above.':'Sent to the terminal. The agent may still be busy. Shown here until it appears in the conversation record.';
        row.append(label,text,note);pendingEl.appendChild(row);
        if(!item.unmatched&&elapsed<60000)next=Math.min(next,60000-elapsed);
      }
      if(Number.isFinite(next))submissionTimer=setTimeout(renderSubmissions,Math.max(1,next));
    }
    function clearSubmissions(){
      submissions=[];observedIds.clear();matchedSubmissions.clear();clearTimeout(submissionTimer);clearTimeout(flashTimer);
      flashTimer=0;screen.classList.remove('conversation-just-submitted');renderSubmissions();
    }
    function reconcileSubmissions(incoming,direction,sequence){
      if(!submissions.length)return;
      for(const event of incoming){
        if(event.role!=='user'||event.kind!=='text'||matchedSubmissions.has(event.id))continue;
        const ts=Date.parse(event.ts),text=normalizePrompt(event.text);
        const fraction=/\.(\d+)(?:Z|[+-]\d\d:\d\d)$/.exec(event.ts||'');
        const secondsOnly=!fraction||!/[1-9]/.test(fraction[1]);
        for(const item of submissions){
          // A response begun before this send cannot later promote its old
          // user IDs just because Hermes repeats them in a newer snapshot.
          if(direction==='older')item.known.add(event.id);
          else if(sequence<item.nextRead&&!item.known.has(event.id)){
            const ambiguous=secondsOnly&&Number.isFinite(ts)&&ts===Math.floor(item.at/1000)*1000;
            if(ambiguous){
              item.uncertain.add(event.id);
              if(item.text===text||event.truncated&&text.length>=256&&item.text.startsWith(text))item.unmatched=true;
            }else if(!(Number.isFinite(ts)&&ts>=item.at))item.known.add(event.id);
          }
        }
        if(direction==='older')continue;
        const eligible=submissions.filter(item=>!item.known.has(event.id)&&!item.uncertain.has(event.id)&&
          (Number.isFinite(ts)?ts>=item.at||ts>=(secondsOnly?Math.floor(item.at/1000)*1000:item.at)&&sequence>=item.nextRead:
            sequence>=item.nextRead&&direction==='newer'));
        let candidates=eligible.filter(item=>item.matchable&&!event.truncated&&item.text===text);
        if(!candidates.length&&event.truncated&&text.length>=256){
          candidates=eligible.filter(item=>item.text.startsWith(text));
          // A shared prefix cannot distinguish two different pending prompts.
          if(candidates.some(item=>item.text!==candidates[0].text||item.length!==candidates[0].length))candidates=[];
        }
        if(candidates.length){
          submissions.splice(submissions.indexOf(candidates[0]),1);matchedSubmissions.add(event.id);
        }else if(eligible.length){
          // A new user record exists, but we cannot assert which send it is.
          // Keep the receipt without claiming that no record has arrived.
          eligible[0].unmatched=true;matchedSubmissions.add(event.id);
        }
      }
      renderSubmissions();
    }
    function viewport(){
      if(!opened||!enabled||!presented)return;
      const view=root.visualViewport;
      screen.style.setProperty('--conversation-viewport-height',(view?view.height:root.innerHeight)+'px');
      screen.style.setProperty('--conversation-viewport-top',(view?view.offsetTop:0)+'px');
    }
    listen(root.visualViewport,'resize',viewport);
    listen(root.visualViewport,'scroll',viewport);
    function expand(value){
      fullWidth=value;screen.classList.toggle('conversation-full',value);
      el('.conversation-expand').setAttribute('aria-pressed',String(value));
      el('.conversation-expand').textContent=value?'Side panel':'Full width';
    }
    const preview=root.OrreryConversationPreview?.mount({host:el('.conversation-preview'),source,onBeforeOpen:layoutChanged,onClose:layoutChanged,onActivate:()=>expand(true)});
    let enabled=false,opened=false,agent='',generation=0,controller=null,timer=0,busy=false;
    let before=null,after=null,hasOlder=false,mode='',newCount=0,events=new Map();
    let presented=true,lastPosition=null,lastWidth=0,lastHeight=0,lastFocused=null;
    let layoutTimer=0,layoutFrame=0,layoutPending=false,restoring=false,userScrolling=false,layoutStarted=0;
    panel.dataset.conversationLayout="idle";
    let contextKey='',boundContext={},paused=false,retainedBytes=0,providerLabel='Codex',followPending=false,jumpTimer=0;
    const byteSize=event=>new TextEncoder().encode(JSON.stringify(event)).byteLength;
    const fingerprint=current=>JSON.stringify(['name','program','provider','history_binding','transcript_path',
      'native_session_id','history_session_id','history_receipt_ts','created','mail_instance_id','mail_agent_id','terminalPaneId'].map(key=>current[key]??null));
    function nearBottom(){return scroll.scrollHeight-scroll.clientHeight-scroll.scrollTop<45;}
    function position(){
      const atBottom=nearBottom();
      if(atBottom)newCount=0;
      el('.conversation-position').textContent=events.size+' loaded · '+(['fresh_tail','snapshot'].includes(mode)?'recent window':'loaded portion');
      latest.textContent=paused?'Latest · resume':newCount?newCount+' new':'Latest';
    }
    function message(text){status.textContent=text;}
    function stop(keepFollow=false){clearTimeout(timer);clearTimeout(jumpTimer);timer=jumpTimer=0;if(controller)controller.abort();controller=null;generation++;busy=false;if(pendingAction){endOp(pendingAction.op);pendingAction=null;}if(!keepFollow)followPending=false;}
    function clear({keepSubmissions=false}={}){tablePositions.clear();if(!keepSubmissions)clearSubmissions();lastPosition=null;clearTimeout(jumpTimer);jumpTimer=0;preview?.close();events.clear();eventsEl.replaceChildren();before=after=null;hasOlder=false;newCount=0;mode='';paused=false;followPending=false;retainedBytes=0;earlier.hidden=true;retry.hidden=true;empty.hidden=false;empty.textContent='Loading conversation…';position();}
    const tableKey=(article,index)=>JSON.stringify([article.dataset.eventId,index]);
    function saveTables(){
      if(tableMutating)return;
      for(const article of eventsEl.children)article.querySelectorAll('.conversation-table-scroll').forEach((table,index)=>{
        if(table.isConnected&&table.getClientRects().length)tablePositions.set(tableKey(article,index),table.scrollLeft);
      });
    }
    function restoreTables(){
      tableMutating=true;cancelAnimationFrame(tableFrame);
      const apply=()=>{for(const article of eventsEl.children)article.querySelectorAll('.conversation-table-scroll').forEach((table,index)=>{
        const key=tableKey(article,index);if(tablePositions.has(key))table.scrollLeft=tablePositions.get(key);
      });};
      apply();tableFrame=requestAnimationFrame(()=>{tableFrame=0;apply();tableMutating=false;});
    }
    function draw(event){
      const article=renderEvent?renderEvent(event,node):node(event);
      article.querySelectorAll('.conversation-table-scroll').forEach((table,index)=>{
        table.addEventListener('scroll',()=>{
          if(!tableMutating&&table.isConnected&&table.getClientRects().length)tablePositions.set(tableKey(article,index),table.scrollLeft);
        },{passive:true});
      });
      return preview?preview.render(event,article):article;
    }
    function anchor(){
      const top=scroll.getBoundingClientRect().top;
      const first=[...eventsEl.children].find(child=>child.getBoundingClientRect().bottom>top);
      const next=first?.nextElementSibling;
      return first?{id:first.dataset.eventId,offset:first.getBoundingClientRect().top-top,
        next:next?{id:next.dataset.eventId,offset:next.getBoundingClientRect().top-top}:null}:null;
    }
    function restoreAnchor(saved,fallback){
      let target=saved&&[...eventsEl.children].find(child=>child.dataset.eventId===saved.id),offset=saved?.offset;
      // Rewrapping can make the former tail offset longer than the whole
      // event. Keep its next visible boundary instead of skipping past it.
      if(target&&offset<0&&-offset>=target.getBoundingClientRect().height&&saved.next){
        const next=[...eventsEl.children].find(child=>child.dataset.eventId===saved.next.id);
        if(next){target=next;offset=saved.next.offset;}
      }
      if(target)scroll.scrollTop+=target.getBoundingClientRect().top-scroll.getBoundingClientRect().top-offset;
      else scroll.scrollTop=fallback;
    }
    function textNodes(article){
      const walker=document.createTreeWalker(article,NodeFilter.SHOW_TEXT),nodes=[];
      while(walker.nextNode())nodes.push(walker.currentNode);return nodes;
    }
    function remember(force=false){
      if(!opened||!presented||!panel.isConnected||!scroll.getClientRects().length)return;
      const rect=screen.getBoundingClientRect();
      if(!force&&(layoutPending||restoring||rect.width!==lastWidth||rect.height!==lastHeight))return;
      if(nearBottom()){lastPosition={bottom:true};return;}
      const bounds=scroll.getBoundingClientRect(),top=bounds.top;
      const article=[...eventsEl.children].find(child=>child.getBoundingClientRect().bottom>top+1);
      if(!article)return;
      const point=document.caretPositionFromPoint?.(bounds.left+parseFloat(getComputedStyle(scroll).paddingLeft)+2,top+2);
      let caret=point?{node:point.offsetNode,offset:point.offset}:null;
      if(!caret&&document.caretRangeFromPoint){const r=document.caretRangeFromPoint(bounds.left+20,top+2);if(r)caret={node:r.startContainer,offset:r.startOffset};}
      const nodes=textNodes(article);let offset=0,node=null,local=0;
      if(caret&&article.contains(caret.node)&&caret.node.nodeType===Node.TEXT_NODE){
        node=caret.node;local=Math.min(caret.offset,node.length);
        for(const value of nodes){if(value===node)break;offset+=value.length;}
        offset+=local;
      }else{
        // A padded message boundary: store its next text character, never a
        // distance from the end of the previous wrapping paragraph.
        node=nodes.find(value=>{const r=document.createRange();r.selectNodeContents(value);return r.getBoundingClientRect().bottom>top;})||nodes[0];
        if(node)for(const value of nodes){if(value===node)break;offset+=value.length;}
      }
      if(!node)return;
      const range=document.createRange();range.setStart(node,Math.min(local,node.length));range.setEnd(node,Math.min(local+1,node.length));
      const r=range.getBoundingClientRect();
      lastPosition={id:article.dataset.eventId,offset,top:r.top-top,bottom:false};
    }
    function restoreReading(){
      if(!opened||!presented||!lastPosition||!scroll.getClientRects().length)return;
      if(lastPosition.bottom){scroll.scrollTop=scroll.scrollHeight;return;}
      const article=[...eventsEl.children].find(child=>child.dataset.eventId===lastPosition.id);
      if(!article)return;
      let remaining=lastPosition.offset;
      for(const node of textNodes(article)){
        if(remaining>node.length){remaining-=node.length;continue;}
        const range=document.createRange();range.setStart(node,remaining);range.setEnd(node,Math.min(remaining+1,node.length));
        const rect=range.getBoundingClientRect();if(rect.height)scroll.scrollTop+=rect.top-scroll.getBoundingClientRect().top-lastPosition.top;
        break;
      }
    }
    function layoutChanged(){
      if(!opened||!presented)return;
      userScrolling=false;layoutPending=true;layoutStarted=performance.now();
      panel.dataset.conversationLayout='pending';
      clearTimeout(layoutTimer);cancelAnimationFrame(layoutFrame);
      layoutTimer=setTimeout(()=>{layoutTimer=0;layoutFrame=requestAnimationFrame(()=>{layoutFrame=requestAnimationFrame(()=>{
        layoutFrame=0;restoring=true;restoreReading();
        const r=screen.getBoundingClientRect();lastWidth=r.width;lastHeight=r.height;
        layoutFrame=requestAnimationFrame(()=>{
          layoutFrame=0;restoring=false;layoutPending=false;
          // A layout completion signal lets callers wait for the restored
          // character rather than assuming a fixed animation-frame duration.
          panel.dataset.conversationLayoutMs=String(performance.now()-layoutStarted);
          panel.dataset.conversationLayout='settled';
        });
      });});},32);
    }
    function relocate(target,{visible=true,suspend=true,focus=false}={}){
      const changed=screen!==target||presented!==visible||panel.parentElement!==target;
      if(changed){
        saveTables();tableMutating=true;layoutPending=true;
        screen.classList.remove('conversation-open','conversation-full','conversation-enabled','conversation-just-submitted');
        screen.style.removeProperty('--conversation-viewport-height');screen.style.removeProperty('--conversation-viewport-top');
        if(!visible&&presented&&suspend)stop(true);
        screen=target;presented=visible;
        if(panel.parentElement!==target)target.appendChild(panel);
      }
      panel.hidden=!opened||!presented;
      screen.classList.toggle('conversation-enabled',enabled);
      screen.classList.toggle('conversation-just-submitted',Boolean(flashTimer));
      screen.classList.toggle('conversation-open',opened&&presented);
      screen.classList.toggle('conversation-full',opened&&presented&&fullWidth);
      if(!presented||!opened)return;
      viewport();restoreTables();
      const rect=screen.getBoundingClientRect(),resized=rect.width!==lastWidth||rect.height!==lastHeight;
      if(changed||resized)layoutChanged();
      if(focus&&lastFocused?.isConnected&&document.activeElement===document.body){
        lastFocused.focus({preventScroll:true});layoutChanged();
      }
      if(followPending&&!busy){followPending=false;followSubmitted();}
      else if(changed&&!busy){if(!events.size)load();else plan();}
    }
    function trim(fromStart){
      let removed=false;
      while(events.size>MAX_EVENTS||retainedBytes>MAX_BYTES){
        const ids=[...events.keys()],id=fromStart?ids[0]:ids[ids.length-1];
        retainedBytes-=byteSize(events.get(id));events.delete(id);
        const child=fromStart?eventsEl.firstElementChild:eventsEl.lastElementChild;
        if(child)child.remove();removed=true;
      }
      if(removed&&!['fresh_tail','snapshot'].includes(mode)){
        const kept=[...events.values()];
        before=kept[0]?.cursor_before||before;
        if(!fromStart){after=kept[kept.length-1]?.cursor_after||after;paused=true;}
        hasOlder=true;
      }
      return removed;
    }
    function node(event){
      const article=document.createElement('article');article.className='conversation-event';
      article.dataset.eventId=event.id;article.dataset.role=event.role;article.dataset.kind=event.kind;
      if(event.kind==='mail'&&Array.isArray(event.mail)&&root.OrreryConversationMail)return root.OrreryConversationMail.render(event,article);
      const byline=document.createElement('div');byline.className='conversation-byline';
      const role=document.createElement('span');role.className='conversation-role';
      role.textContent=event.kind==='tool'?'Tool':event.kind==='tool_result'?'Tool result':event.role==='user'?'You':providerLabel;byline.appendChild(role);
      if(['tool','tool_result'].includes(event.kind)){
        const tool=document.createElement('span');tool.className='conversation-tool-name';tool.textContent=event.text;byline.appendChild(tool);
      }
      const time=document.createElement('time');time.className='conversation-time';
      const date=new Date(event.ts);
      if(Number.isFinite(date.getTime())){time.dateTime=event.ts;time.textContent=date.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});time.title=date.toLocaleString();}
      byline.appendChild(time);article.appendChild(byline);
      if(!['tool','tool_result'].includes(event.kind)){
        const text=document.createElement('div');text.className='conversation-text';
        if(event.role==='assistant'&&root.OrreryConversationMarkdown)root.OrreryConversationMarkdown.render(event.text,text);
        else if(root.OrreryConversationMarkdown)root.OrreryConversationMarkdown.renderText(event.text,text);
        else text.textContent=event.text;article.appendChild(text);
      }
      if(event.truncated){const note=document.createElement('div');note.className='conversation-truncated';note.textContent='Long message shortened in this reader.';article.appendChild(note);}
      const target=article.querySelector('.conversation-text')||byline;
      if(jumpToEvent){
        target.classList.add('conversation-jumpable');target.tabIndex=0;target.setAttribute('role','button');
        target.setAttribute('aria-label','Show this message in its terminal');target.title='Click to find this message in the terminal';
        let press=null;
        target.addEventListener('pointerdown',e=>{press={x:e.clientX,y:e.clientY,selected:!root.getSelection()?.isCollapsed};});
        target.addEventListener('click',e=>{
          clearTimeout(jumpTimer);
          if(e.target.closest('button,a')||e.detail>1||e.ctrlKey||e.metaKey||e.altKey||e.shiftKey||press?.selected||!root.getSelection()?.isCollapsed)return;
          if(press&&Math.hypot(e.clientX-press.x,e.clientY-press.y)>5)return;
          const token=generation;
          // Give double click and drag selection their native copy behaviour.
          jumpTimer=setTimeout(()=>{if(token===generation&&opened&&root.getSelection()?.isCollapsed)jump(event);},600);
        });
        target.addEventListener('keydown',e=>{if(e.target.closest('button,a')){clearTimeout(jumpTimer);return;}if(!['Enter',' '].includes(e.key)||e.ctrlKey||e.metaKey||e.altKey||e.shiftKey)return;e.preventDefault();e.stopPropagation();clearTimeout(jumpTimer);if(root.getSelection()?.isCollapsed)jump(event);});
      }
      if(Array.isArray(event.mail)&&root.OrreryConversationMail)root.OrreryConversationMail.render(event,article);
      return article;
    }
    function jump(event){
      const result=fingerprint(getContext()||{})!==contextKey?{state:'changed'}:
        jumpToEvent({agent,event,context:boundContext})||{state:'changed'};
      if(result.state==='unique'){
        preview?.close();
        if(screen.getBoundingClientRect().width<800||root.innerWidth<=1200)close({focus:false});
        else expand(false);
        message('Matching message shown in this terminal.');
      }else if(result.state==='limited')message('Terminal scrollback exceeds the search limit; cannot confirm a unique match. Keep reading history here.');
      else if(result.state==='multiple')message('Same text found in '+result.count+(result.limited?' or more':'')+' places in the terminal. Keep reading history here.');
      else if(result.state==='alternate')message('Earlier output of this screen is not kept in the terminal. Keep reading history here.');
      else if(result.state==='changed')message('Terminal changed. Search again.');
      else message('Not found in terminal scrollback. Keep reading history here.');
    }
    let holding=false,pendingAction=null;
    // A random id made in this page for this reader (pane); see orrery_backend.py
    // conversation_legacy_read: the server lets it take over its own held slot.
    const readerId=Array.from(root.crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
    // What the last answer said, for plan().
    const last={hold:false,slot:false,refused:false,rows:0,catchUp:false,failed:false};
    // A user's own load (Load earlier, Retry) is a user operation: other
    // panes' held polls give way, and this pane's held poll ends first.
    function userLoad(direction){
      if(busy&&!holding)return;
      const op=beginOp();
      if(busy){pendingAction={direction,op};controller?.abort();return;}
      load(direction,op);
    }
    /* The one place that decides when this reader asks next.
       - nothing while it is closed, hidden, paused or already asking;
       - while a user operation is in flight anywhere: no held poll, only the
         plain one after pollMs; the last operation's end plans again
         (replanAll), so holding resumes at once;
       - at once (a held poll) when the server can hold, did not refuse last
         time and this page's cap has room; after new rows, CONTENT_GAP_MS;
       - at once for a catch-up page from a slot;
       - otherwise, and after a failure, pollMs.
       Planning again never postpones a read already planned sooner, so
       frequent operations cannot starve a reader. */
    let timerDue=0;
    function plan(){
      if(!opened||!presented||!enabled||paused||busy||!agent||document.hidden){clearTimeout(timer);timer=0;return;}
      let delay=pollMs;
      if(opsActive()||last.failed)delay=pollMs;
      else if(last.catchUp&&last.slot)delay=0;
      else if(last.hold&&!last.refused&&waiting.size<MAX_WAITING)delay=last.rows>0?CONTENT_GAP_MS:0;
      const due=performance.now()+delay;
      if(timer&&timerDue<=due)return;
      clearTimeout(timer);timerDue=due;timer=setTimeout(()=>{timer=0;load('newer');},delay);
    }
    ops.planners.add(plan);
    // Older pages, newest first, merged into one page in reading order.
    // A later page that fails for a reason other than the binding (a record
    // over the byte limit, a dashboard or network failure) ends this load
    // with the pages already read; the next Load earlier continues from them.
    async function readOlder(name,options,token){
      const pages=[];let cursor=options.before,count=0;
      for(let n=0;n<OLDER_READS;n++){
        let page;
        try{page=await source.read(name,{...options,before:cursor,limit:Math.min(OLDER_LIMIT,OLDER_EVENTS-count)});}
        catch(error){
          if(!pages.length||token!==generation||error?.name==='AbortError'||BINDING_ERRORS.includes(error?.code))throw error;
          break;
        }
        pages.push(page);count+=page.events.length;
        if(token!==generation||page.has_older!==true||(page.mode||'cursor')!=='cursor'||
          typeof page.before!=='string'||page.before===cursor||count>=OLDER_EVENTS)break;
        cursor=page.before;
      }
      const oldest=pages[pages.length-1],seen=new Set();
      // Pages never overlap at the server's cursors; drop a repeated id anyway.
      const events=pages.reverse().flatMap(page=>page.events).filter(event=>!(event?.id&&seen.has(event.id))&&(seen.add(event?.id),true));
      return {...pages[pages.length-1],events,before:oldest.before,has_older:oldest.has_older,
        skipped_large_record:pages.some(page=>page.skipped_large_record===true)};
    }
    async function load(direction='initial',op=null){
      if(!opened||!presented||!enabled||busy||!agent||paused&&direction==='newer'){endOp(op);return;}
      const token=generation,name=agent,sequence=++readSequence;
      let pollAgain=true;
      controller=new AbortController();busy=true;retry.hidden=true;
      const options={signal:controller.signal},mine=controller;
      if(direction==='older')options.before=before;
      if(direction==='newer')options.after=after;
      const holder={yield:()=>mine.abort()};
      // A hidden tab never asks to be held: it keeps no connection open.
      if(direction==='newer'&&after!==null&&!document.hidden&&!opsActive()&&waiting.size<MAX_WAITING){options.wait=WAIT_SECONDS;options.reader=readerId;waiting.add(holder);}
      holding=Boolean(options.wait);
      // Load earlier stays usable while the poll only waits in the background.
      earlier.disabled=!holding;
      try{
        const page=direction==='older'?await readOlder(name,options,token):await source.read(name,options);
        holding=false;waiting.delete(holder);
        if(page.hold===true)last.hold=true;
        last.slot=page.slot===true;last.refused=Boolean(options.wait)&&!last.slot;
        last.catchUp=page.has_newer===true&&direction!=='older';last.rows=0;last.failed=false;
        if(token!==generation||!opened||!enabled)return;
        // The server saw no change since this cursor: keep every row as is.
        if(page.unchanged===true&&direction==='newer'&&page.after===after)return;
        const atBottom=nearBottom(),oldHeight=scroll.scrollHeight,oldTop=scroll.scrollTop,saved=anchor();
        const incoming=page.events.filter(event=>event&&typeof event.id==='string'&&typeof event.text==='string');
        for(const event of incoming)observedIds.add(event.id);
        mode=page.mode||'cursor';
        providerLabel=({codex:'Codex',claude:'Claude',dsh:'dsh',hermes:'Hermes'})[page.provider]||providerLabel;
        const fresh=['fresh_tail','snapshot'].includes(mode);
        const additions=incoming.filter(event=>!events.has(event.id));
        if(!fresh&&direction==='newer'&&!atBottom&&
          (events.size+additions.length>MAX_EVENTS||retainedBytes+additions.reduce((n,event)=>n+byteSize(event),0)>MAX_BYTES)){
          paused=true;message('Updates paused at reader limit. Latest resumes at the newest messages.');position();return;
        }
        saveTables();tableMutating=true;
        const fragment=document.createDocumentFragment();let added=0;
        if(fresh){
          const existing=new Map([...eventsEl.children].map(child=>[child.dataset.eventId,child]));
          const previous=events;
          if([...previous].some(([id,event])=>JSON.stringify(event)!==JSON.stringify(incoming.find(next=>next.id===id))))preview?.close();
          events=new Map();retainedBytes=0;
          for(const event of incoming.slice(-200)){
            if(events.has(event.id))continue;
            events.set(event.id,event);retainedBytes+=byteSize(event);
            fragment.appendChild(existing.has(event.id)&&JSON.stringify(previous.get(event.id))===JSON.stringify(event)?existing.get(event.id):draw(event));if(!previous.has(event.id))added++;
          }
          eventsEl.replaceChildren(fragment);
        }else{
          for(const event of additions){fragment.appendChild(draw(event));added++;}
          if(direction==='older'){
            events=new Map([...additions.map(event=>[event.id,event]),...events]);eventsEl.prepend(fragment);
          }else{
            additions.forEach(event=>events.set(event.id,event));eventsEl.appendChild(fragment);
          }
          retainedBytes+=additions.reduce((n,event)=>n+byteSize(event),0);
        }
        if(direction!=='newer'){before=page.before;hasOlder=page.has_older===true;}
        if(direction!=='older')after=page.after;
        const trimmed=trim(direction!=='older');earlier.hidden=!hasOlder;
        for(const key of tablePositions.keys())if(!events.has(JSON.parse(key)[0]))tablePositions.delete(key);
        restoreTables();
        reconcileSubmissions(incoming,direction,sequence);
        empty.hidden=events.size>0||submissions.length>0;empty.textContent='No conversation messages in this portion yet.';
        if(direction==='initial'||direction==='newer'&&atBottom)scroll.scrollTop=scroll.scrollHeight;
        else if(direction==='older')restoreAnchor(saved,Math.max(0,oldTop+scroll.scrollHeight-oldHeight));
        else{restoreAnchor(saved,oldTop);newCount+=added;}
        message(paused?'Reader window is bounded. Latest resumes at the newest messages.':
          mode==='snapshot'?page.notice||'Read-only · recent provider snapshot':
          fresh?(page.limited||trimmed?'Fresh · limited recent snapshot; earlier history and tools need telemetry support.':'Fresh · recent snapshot (up to 200 messages).'):
          trimmed?'Older loaded messages were released. Load earlier to read them again.':
          page.skipped_large_record?'A large record was skipped. Load earlier to continue.':page.notice||'Read-only · updates while open');
        position();if(direction==='initial'||direction==='newer'&&atBottom)remember(true);
        if(direction!=='older')last.rows=added;
        if(page.has_newer&&direction!=='older'){
          // A bounded page per request. Continue in the next poll without
          // sending overlapping reads during a fast provider burst.
          message('Read-only · catching up with new messages…');
        }
      }catch(error){
        waiting.delete(holder);holding=false;
        if(token!==generation||error.name==='AbortError')return;
        last.failed=true;
        pollAgain=!['history_changed','record_too_large','provider_unavailable','claude_next_phase','dashboard_upgrade_required','dsh_decoder_unavailable','history_format_unsupported'].includes(error.code);
        message(error.message);retry.hidden=false;
        if(BINDING_ERRORS.includes(error.code)){
          // Never retain content from a stale, unbound or different native session.
          clear({keepSubmissions:error.code==='history_pending'});retry.hidden=false;empty.hidden=false;
          empty.textContent=error.code==='history_changed'?'Session changed. Retry to load the current conversation.':error.message;
          position();
        }
      }finally{
        if(token===generation){
          busy=false;controller=null;earlier.disabled=false;
          if(followPending){followPending=false;followSubmitted();}
          else if(pendingAction){const next=pendingAction;pendingAction=null;load(next.direction,next.op);}
          else if(pollAgain)plan();
        }
        endOp(op);
      }
    }
    function context(){
      const current=getContext()||{};const name=String(current.name||''),key=fingerprint(current);
      if(!opened)return;
      if(name===agent&&key===contextKey)return;
      const sameBinding=key===contextKey;
      stop();agent=name;contextKey=key;clear({keepSubmissions:sameBinding});boundContext={...current};
      el('.conversation-subtitle').textContent=(agent||'No pane selected')+' · read-only';
      if(!agent){empty.textContent='Select an agent pane to read its conversation.';message('No agent selected');return;}
      providerLabel=({'claude-code':'Claude',claude:'Claude',dsh:'dsh',hermes:'Hermes'})[current.program]||'Codex';
      load();
    }
    function close({focus=true}={}){
      if(!opened)return;
      stop();opened=false;agent='';panel.hidden=true;screen.classList.remove('conversation-open','conversation-full');
      screen.style.removeProperty('--conversation-viewport-height');screen.style.removeProperty('--conversation-viewport-top');
      toggle.setAttribute('aria-expanded','false');clear({keepSubmissions:true});onState();const target=typeof focusControl==='function'?focusControl():focusControl||toggle;
      if(focus&&target&&!target.hidden&&target.getClientRects().length)target.focus();
    }
    function open(){
      if(!enabled)return;
      if(opened){onActivate();return;}
      onActivate();opened=true;panel.hidden=false;screen.classList.add('conversation-open');screen.classList.toggle('conversation-full',fullWidth);
      viewport();const rect=screen.getBoundingClientRect();lastWidth=rect.width;lastHeight=rect.height;
      toggle.setAttribute('aria-expanded','true');agent=null;context();scroll.focus();onState();
    }
    function preference(){
      try{enabled=localStorage.getItem(KEY)==='1';}catch(_){enabled=false;}
      setting.checked=enabled;toggle.hidden=!enabled;
      screen.classList.toggle('conversation-enabled',enabled);
      if(!enabled)close({focus:false});
    }
    listen(setting,'change',()=>{try{localStorage.setItem(KEY,setting.checked?'1':'0');}catch(_){}preference();});
    listen(document,'oc:prefs-changed',preference);
    listen(window,'storage',event=>{if(event.key===KEY)preference();});
    if(bindToggle)listen(toggle,'click',()=>opened?close():open());
    listen(el('.conversation-close'),'click',()=>close());
    listen(el('.conversation-expand'),'click',()=>{if(fullWidth)preview?.close();expand(!fullWidth);});
    listen(panel,'pointerdown',()=>onActivate());
    listen(panel,'focusin',event=>{lastFocused=event.target;onActivate();});
    listen(panel,'mousedown',event=>event.stopPropagation());
    listen(panel,'keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(preview?.selected){preview.close();scroll.focus();}else close();}});
    // Arrow/Page keys and wheels belong only to the browser scroll container;
    // there is no path from this module to xterm or tmux input.
    listen(earlier,'click',()=>userLoad('older'));
    listen(retry,'click',()=>userLoad(events.size?'newer':'initial'));
    listen(latest,'click',()=>{
      if(paused){stop();clear({keepSubmissions:true});load('initial');return;}
      scroll.scrollTop=scroll.scrollHeight;newCount=0;position();remember(true);
      if(!busy)plan();
    });
    // Submission remains owned by the existing composer/input guards. This
    // notification adds an ephemeral delivery receipt, never a provider event.
    // Only a subsequent exact user record replaces it (FIFO for repeated text).
    function followSubmitted(){
      if(paused){stop();clear({keepSubmissions:true});load('initial');}
      else{scroll.scrollTop=scroll.scrollHeight;newCount=0;position();remember(true);load('newer');}
    }
    listen(document,'oc:prompt-submitted',event=>{
      if(!opened||!enabled||event.detail?.name!==agent)return;
      const detail=event.detail;
      if(typeof detail.text==='string'&&typeof detail.id==='string'&&!submissions.some(item=>item.id===detail.id)){
        const text=normalizePrompt(detail.text);
        submissions.push({id:detail.id,name:agent,at:Number.isFinite(detail.submittedAt)?detail.submittedAt:Date.now(),
          text:text.slice(0,65536),length:text.length,matchable:text.length<=65536,preview:detail.text.slice(0,1000)+(detail.text.length>1000?'…':''),
          known:new Set(observedIds),uncertain:new Set(),nextRead:readSequence+1});
        renderSubmissions();empty.hidden=true;
        screen.classList.add('conversation-just-submitted');clearTimeout(flashTimer);
        flashTimer=setTimeout(()=>{flashTimer=0;screen.classList.remove('conversation-just-submitted');},1800);
      }
      if(!presented){followPending=true;return;}
      preview?.close();
      // Finish the in-flight page first; an older page may trim the newest
      // events and pause polling. Its finally must still honour this request.
      // A held poll began before this send: end it, so the record of the send
      // is read by a request that started after it.
      if(busy){followPending=true;if(holding)controller?.abort();return;}
      followSubmitted();
    });
    function userScroll(){clearTimeout(layoutTimer);cancelAnimationFrame(layoutFrame);layoutTimer=layoutFrame=0;layoutPending=restoring=false;panel.dataset.conversationLayout='settled';userScrolling=true;const r=screen.getBoundingClientRect();lastWidth=r.width;lastHeight=r.height;}
    listen(scroll,'wheel',userScroll,{passive:true});listen(scroll,'touchstart',userScroll,{passive:true});listen(scroll,'pointerdown',userScroll,{passive:true});
    listen(scroll,'keydown',event=>{if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(event.key))userScroll();});
    listen(scroll,'scroll',()=>{if(presented){position();if(userScrolling)remember();}},{passive:true});
    listen(window,'resize',layoutChanged);
    const layoutObserver=new ResizeObserver(layoutChanged);
    layoutObserver.observe(panel);layoutObserver.observe(scroll);layoutObserver.observe(eventsEl);
    listen(document,'oc:stage-agent',context);
    listen(document,'oc:focus-agent',context);
    listen(document,'oc:agents',context);
    // A hidden tab keeps no held poll: end one that is waiting, so its
    // browser connection and the server's slot are returned at once.
    listen(document,'visibilitychange',()=>{if(document.hidden){clearTimeout(timer);timer=0;if(holding)controller?.abort();}else if(opened){if(events.size)plan();else load('initial');}});
    preference();
    return Object.freeze({open,close,relocate,reconcile:context,get opened(){return opened;},get panel(){return panel;},refresh:()=>load(events.size?'newer':'initial'),
      dispose(){ops.planners.delete(plan);cancelAnimationFrame(tableFrame);layoutObserver.disconnect();clearTimeout(layoutTimer);cancelAnimationFrame(layoutFrame);close({focus:false});clearSubmissions();stop();listeners.forEach(remove=>remove());panel.remove();screen.classList.remove('conversation-enabled','conversation-full');}});
  }
  function mountWorkspace({getContext,getSlots,getOwner=name=>getContext(name)?.terminalPaneId,activate,...options}){
    const screen=document.querySelector('.screen'),toggle=document.getElementById('conversationToggle');
    // Keep one reader per live pane. A split cell is only a display destination.
    // Detached readers retain bounded DOM/cursors; inactive readers do not poll.
    const views=new Map();let sequence=0,syncing=false,lastCurrent='';
    const enabled=()=>{try{return localStorage.getItem(KEY)==='1';}catch(_){return false;}};
    const current=()=>views.get((getContext()||{}).name)?.view||views.get(lastCurrent)?.view;
    function paint(){
      const view=current();screen.classList.toggle('conversation-enabled',enabled());
      toggle.hidden=!enabled();toggle.setAttribute('aria-expanded',String(Boolean(view?.opened)));
      toggle.setAttribute('aria-controls',view?.panel.id||'conversationPanel');
    }
    function create(name,owner){
      const park=document.createElement('div'),control=document.createElement('button');
      control.type='button';control.className='cockpit-control split-history-toggle';
      control.innerHTML='<span class="pane-action-wide" aria-hidden="true">HISTORY</span><span class="pane-action-short" aria-hidden="true">HIST</span><span class="pane-action-icon" aria-hidden="true">◷</span>';
      control.title='Read history for '+name;control.setAttribute('aria-label','Read history for '+name);control.setAttribute('aria-expanded','false');
      const id='conversationPanel-'+(++sequence);control.setAttribute('aria-controls',id);park.appendChild(control);
      control.addEventListener('mousedown',event=>event.stopPropagation());control.addEventListener('pointerdown',event=>event.stopPropagation());
      const view=mount({...options,host:park,control,panelId:id,getContext:()=>getContext(name),
        focusControl:()=>control.getClientRects().length?control:toggle,
        onActivate:()=>{if((getContext()||{}).name!==name)activate(name);},onState:paint});
      view.relocate(park,{visible:false});
      const entry={name,owner,view,park,host:park,control,visible:false};views.set(name,entry);return entry;
    }
    function sync(){
      if(syncing)return;syncing=true;
      try{
        const active=enabled(),layout=active?getSlots():[];
        for(const [name,entry] of views){
          if(active&&getOwner(name)===entry.owner){entry.view.reconcile();continue;}
          entry.view.dispose();entry.control.remove();entry.host.classList.remove('conversation-cell');views.delete(name);
        }
        let selected=String((getContext()||{}).name||'');
        if(!getOwner(selected))selected=views.has(lastCurrent)?lastCurrent:
          [...views.values()].find(entry=>entry.view.opened)?.name||[...views.keys()][0]||'';
        if(active){
          for(const name of new Set([...layout.map(slot=>slot.name),selected].filter(Boolean))){
            const owner=getOwner(name);if(owner&&!views.has(name))create(name,owner);
          }
        }
        lastCurrent=selected;
        const targets=new Map(layout.map(slot=>[slot.name,slot]));
        if(active&&!layout.length&&views.has(selected))targets.set(selected,{host:screen});
        // Remove old host decorations before any reader enters the shared screen.
        // A visible-to-visible move must not abort its in-flight read/preview.
        for(const [name,entry] of views){
          const target=targets.get(name);
          if(target&&entry.host===target.host&&entry.view.panel.parentElement===target.host)continue;
          entry.host.classList.remove('conversation-cell');
          entry.view.relocate(entry.park,{visible:false,suspend:!target});
          if(entry.control.parentElement!==entry.park)entry.park.appendChild(entry.control);
          entry.host=entry.park;entry.visible=false;
        }
        screen.classList.toggle('conversation-enabled',active);
        for(const [name,target] of targets){
          const entry=views.get(name);if(!entry)continue;
          if(target.host!==screen){
            target.host.classList.add('conversation-cell');const controls=target.controlHost||target.host;
            if(entry.control.parentElement!==controls)controls.insertBefore(entry.control,controls.firstChild);
          }
          entry.view.relocate(target.host,{visible:true,focus:name===selected});entry.host=target.host;entry.visible=true;
        }
        paint();
      }finally{syncing=false;}
    }
    toggle.addEventListener('click',()=>{sync();const view=current();if(view)view.opened?view.close():view.open();});
    for(const event of ['oc:stage-agent','oc:focus-agent','oc:agents','oc:prefs-changed'])document.addEventListener(event,sync);
    document.getElementById('conversationEnabled').addEventListener('change',event=>{
      try{localStorage.setItem(KEY,event.target.checked?'1':'0');}catch(_){}sync();
    });
    window.addEventListener('storage',event=>{if(event.key===KEY)sync();});window.addEventListener('resize',sync);
    sync();
    return Object.freeze({open:()=>{sync();current()?.open();},close:()=>current()?.close(),refresh:()=>current()?.refresh()});
  }
  root.OrreryConversation=Object.freeze({mount,mountWorkspace,KEY,yieldHolds,trackFetch,userRequest});
})(window);
