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
  // The user operations (README: Reader, "user operations"), by name. Same
  // origin only. Not History's own polls, not the terminal hover's path
  // probe, and not the dashboard frame's automatic error report (/api/jserr):
  // nobody asked for those. From the NETWORK frame: the dashboard's actions.
  const USER_POSTS=new Set(['/telemetry/open-url','/telemetry/reveal-path','/telemetry/open-ghostty',
    '/telemetry/spawn','/api/exit','/telemetry/conversation/reveal','/telemetry/conversation/path-image']);
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
  const readerIcon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 7h8M8 11h8M8 15h6"/></svg>';
  const expandIcon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6m0-6-6 6M10 20H4v-6m0 6 6-6"/></svg>';
  const latestIcon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v14m-6-6 6 6 6-6M5 21h14"/></svg>';
  const warningIcon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3 2 21h20L12 3Z"/><path d="M12 9v5m0 3v.1"/></svg>';
  const retryIcon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 10a8 8 0 1 0-1 7M20 4v6h-6"/></svg>';
  let closeActiveNotice=null;
  function mount({getContext,source=new root.OrreryConversationSource.Source(),pollMs=4000,renderEvent=null,host=null,control=null,expandControl=null,panelId='conversationPanel',bindToggle=true,onActivate=()=>{},onState=()=>{},focusControl=null,jumpToEvent=null,openExternalUrl=null,renderPeerAvatar=null,renderAvatar=null}){
    let screen=host||document.querySelector('.screen');
    const toggle=control||document.getElementById('conversationToggle');
    const listeners=[];
    function listen(target,type,handler,options){if(!target)return;target.addEventListener(type,handler,options);listeners.push(()=>target.removeEventListener(type,handler,options));}
    const setting=document.getElementById('conversationEnabled');
    const panel=document.createElement('section');
    panel.className='conversation-panel';panel.id=panelId;panel.hidden=true;
    panel.setAttribute('aria-label','Reader');
    panel.innerHTML='<div class="conversation-body"><div class="conversation-thread">'+
      '<div class="conversation-scroll" tabindex="0" aria-label="Conversation messages">'+
      '<button class="cockpit-control conversation-action conversation-older" type="button" aria-label="Load earlier" hidden>Load earlier</button>'+
      '<div class="conversation-events"></div><div class="conversation-pending" role="status" aria-live="polite"></div>'+
      '<div class="conversation-activity" hidden><span class="conversation-activity-mark" aria-hidden="true"><i></i><i></i><i></i></span><span class="conversation-activity-label" role="status" aria-live="polite"></span><span class="conversation-activity-time" aria-hidden="true"></span></div><div class="conversation-empty"></div></div>'+
      '<div class="conversation-bottom" hidden><button class="cockpit-control pane-icon conversation-latest" type="button" title="Latest" aria-label="Latest">'+latestIcon+'</button></div></div>'+
      '<aside class="conversation-preview" aria-label="Selected file preview" hidden></aside></div>';
    screen.appendChild(panel);
    const notices=document.createElement('span');notices.className='conversation-notices';notices.hidden=true;
    notices.innerHTML='<span class="conversation-toolbar" hidden><span class="conversation-status" role="status"></span>'+
      '<span class="conversation-status-label" aria-hidden="true"></span><span class="conversation-warning" aria-hidden="true">'+warningIcon+'</span>'+
      '<button class="cockpit-control conversation-action conversation-retry" type="button" title="Retry" aria-label="Retry" hidden><span>Retry</span>'+retryIcon+'</button>'+
      '<button class="cockpit-control conversation-notice-toggle" type="button" aria-haspopup="dialog" aria-expanded="false">'+warningIcon+'</button></span>'+
      '<button class="conversation-mode" type="button" hidden>i</button>';
    const noticeMenu=document.createElement('div');noticeMenu.className='conversation-notice-menu';noticeMenu.id=panelId+'-status';noticeMenu.hidden=true;
    noticeMenu.setAttribute('role','dialog');noticeMenu.setAttribute('aria-label','Reader status');noticeMenu.tabIndex=-1;
    noticeMenu.innerHTML='<div class="conversation-notice-copy"></div><button class="cockpit-control conversation-menu-retry" type="button">Retry</button>';
    document.body.appendChild(noticeMenu);
    let noticeControl=toggle,noticeTimer=0,noticeTemporary=false,menuAnchor=null;
    let noticeState={text:'',label:''},noticeOverlay=null;
    const expandButton=expandControl||document.createElement('button');
    expandButton.type='button';expandButton.className='cockpit-control pane-icon conversation-expand';expandButton.hidden=true;
    expandButton.innerHTML=expandIcon;expandButton.setAttribute('aria-controls',panelId);
    if(!expandControl)toggle.after(expandButton);
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
      if(link.dataset.localPath){
        event.preventDefault();const path=link.dataset.localPath;
        if(/\.(png|jpe?g|gif|webp)$/i.test(path))preview?.open({path,label:path.split('/').pop(),kind:'image'});
        else source.revealPath(path).catch(error=>message(error.message));
        return;
      }
      if(!/^https?:$/i.test(link.protocol))return;
      event.preventDefault();
      if(openExternalUrl)openExternalUrl(link.href);
      else root.open(link.href,'_blank','noopener,noreferrer');
    }
    listen(panel,'click',activateLink);listen(panel,'auxclick',activateLink);
    const toolbar=notices.querySelector('.conversation-toolbar'),status=notices.querySelector('.conversation-status'),statusLabel=notices.querySelector('.conversation-status-label'),modeInfo=notices.querySelector('.conversation-mode'),empty=el('.conversation-empty');
    const earlier=el('.conversation-older'),retry=notices.querySelector('.conversation-retry'),latest=el('.conversation-latest');
    const noticeToggle=notices.querySelector('.conversation-notice-toggle'),menuCopy=noticeMenu.querySelector('.conversation-notice-copy'),menuRetry=noticeMenu.querySelector('.conversation-menu-retry');
    for(const button of [noticeToggle,modeInfo]){button.setAttribute('aria-controls',noticeMenu.id);button.setAttribute('aria-expanded','false');button.setAttribute('aria-haspopup','dialog');}
    let fullWidth=false,tableMutating=false,tableFrame=0;
    const tablePositions=new Map();
    let toolGroups=[],toolSerial=0;
    const toolGroupFor=new Map();
    let submissions=[],submissionTimer=0,flashTimer=0,readSequence=0;
    const sending=new Map();
    const observedIds=new Set(),matchedSubmissions=new Set(),pendingEl=el('.conversation-pending');
    const normalizePrompt=text=>(root.OrreryConversationMarkdown?.submissionText(text)??text).replace(/\s+/gu,' ').trim();
    function keepReaderFocus(container){
      // A detached control leaves BODY focused, which terminal fitting may
      // interpret as permission to focus xterm and send the next reading key.
      if(opened&&presented&&container?.contains(document.activeElement))scroll.focus({preventScroll:true});
    }
    const activityEl=el('.conversation-activity'),activityLabel=el('.conversation-activity-label'),activityTime=el('.conversation-activity-time');
    function paintActivity(current=getContext()||{}){
      const state=opened&&presented&&current.running===true&&['work','wait','ask','question'].includes(current.act_state)?
        (current.act_state==='ask'?'question':current.act_state):'';
      const label=state==='work'?'Working':state==='wait'?'Waiting':state?'Waiting for you':'';
      const elapsed=state==='work'&&typeof current.work_disp==='string'?current.work_disp.trim():'';
      activityEl.classList.toggle('activity-paused',document.hidden||!presented||!opened);
      panel.classList.toggle('conversation-inactive',document.hidden||!presented||!opened);
      if(activityEl.hidden===!state&&activityEl.dataset.state===(state||'')&&activityTime.textContent===(elapsed?'· '+elapsed:''))return;
      const atBottom=nearBottom();
      activityEl.hidden=!state;activityEl.dataset.state=state;
      if(activityLabel.textContent!==label)activityLabel.textContent=label;
      activityTime.textContent=elapsed?'· '+elapsed:'';
      activityEl.title=label+(elapsed?' · '+elapsed:'');
      if(opened&&presented){
        if(atBottom)scroll.scrollTop=scroll.scrollHeight;
        position();if(atBottom)remember(true);
      }
    }
    function changeTail(change,follow=true){
      const atBottom=follow&&nearBottom(),top=scroll.scrollTop,saved=anchor();
      change();
      if(atBottom)scroll.scrollTop=scroll.scrollHeight;else restoreAnchor(saved,top);
      position();remember(true);
    }
    function paintSubmissionExpansion(){
      for(const row of pendingEl.children){
        const text=row.querySelector('.conversation-submission-text'),more=row.querySelector('.conversation-submission-more');
        const expanded=row.classList.contains('submission-expanded');
        if(!expanded)row._expandable=text.scrollHeight>text.clientHeight+1;
        if(!row._expandable&&document.activeElement===more)keepReaderFocus(more);
        more.hidden=!row._expandable;more.textContent=expanded?'Show less':'Show more';more.setAttribute('aria-expanded',String(expanded));
      }
    }
    function renderSubmissions({preserve=true}={}){
      clearTimeout(submissionTimer);submissionTimer=0;
      const paint=()=>{
        const existing=new Map([...pendingEl.children].map(row=>[row.dataset.receiptKey,row]));
        const items=[...submissions,...sending.values()].sort((a,b)=>a.at-b.at);let next=Infinity,previous=null;
        const receiptKey=item=>JSON.stringify([item.attemptId?'attempt':'sent',item.attemptId||item.id]);
        const retained=new Set(items.map(receiptKey));
        // Remove stale siblings before ordering rows that still own focus.
        for(const [key,row] of existing)if(!retained.has(key)){keepReaderFocus(row);row.remove();existing.delete(key);}
        for(const item of items){
          const key=receiptKey(item);
          let row=existing.get(key);existing.delete(key);
          if(!row){
            row=document.createElement('article');row.className='conversation-submission';row.dataset.receiptKey=key;
            const text=document.createElement('p');text.className='conversation-text conversation-submission-text';
            if(root.OrreryConversationMarkdown)root.OrreryConversationMarkdown.renderText(item.preview,text);else text.textContent=item.preview;
            text.addEventListener('focusin',event=>{
              if(row.classList.contains('submission-expanded'))return;
              changeTail(()=>{row.classList.add('submission-expanded');paintSubmissionExpansion();},false);
              event.target.scrollIntoView({block:'nearest'});remember(true);
            });
            const more=document.createElement('button');more.type='button';more.className='conversation-submission-more';more.hidden=true;
            more.addEventListener('click',()=>changeTail(()=>{row.classList.toggle('submission-expanded');paintSubmissionExpansion();},false));
            const label=document.createElement('div');label.className='conversation-byline';
            label.innerHTML='<span class="conversation-submission-mark" aria-hidden="true"></span><span class="conversation-submission-state"></span><span class="conversation-submission-recipient"></span>';
            const note=document.createElement('div');note.className='conversation-submission-note';
            row.append(text,more,label,note);
          }
          const elapsed=Date.now()-item.at,state=item.sending?'sending':item.unmatched?'unmatched':elapsed>=60000?'late':'awaiting';
          const status=state==='sending'?'Sending…':state==='unmatched'?'Record not matched':state==='late'?'Not recorded yet':'Awaiting record';
          row.dataset.state=state;row.dataset.submissionId=item.id;
          const label=row.querySelector('.conversation-byline');label.title=(item.sending?'Sending to ':'Sent → ')+item.name+' · '+status;
          const copy={mark:state==='sending'?'◌':state==='unmatched'?'ⓘ':'✓',state:item.sending?status:'Sent · '+status,recipient:' → '+item.name};
          for(const [part,value] of Object.entries(copy)){
            const span=label.querySelector('.conversation-submission-'+part);if(span.textContent!==value)span.textContent=value;
          }
          let dismiss=label.querySelector('.conversation-submission-dismiss');
          if(item.unmatched&&!dismiss){
            dismiss=document.createElement('button');dismiss.type='button';dismiss.className='cockpit-control conversation-submission-dismiss';dismiss.textContent='Dismiss';dismiss.setAttribute('aria-label','Dismiss unmatched send receipt');
            dismiss.addEventListener('click',()=>{keepReaderFocus(row);submissions=submissions.filter(entry=>entry.id!==item.id);renderSubmissions();});label.appendChild(dismiss);
          }else if(!item.unmatched&&dismiss){keepReaderFocus(dismiss);dismiss.remove();}
          const note=row.querySelector('.conversation-submission-note');note.hidden=!item.unmatched;
          const noteText=item.unmatched?'Check the conversation above.':'';if(note.textContent!==noteText)note.textContent=noteText;
          note.title=item.unmatched?'A user record arrived after this send, but it cannot be matched to this text.':'';
          const after=previous?previous.nextElementSibling:pendingEl.firstElementChild;
          if(row!==after){keepReaderFocus(row);pendingEl.insertBefore(row,after);}
          previous=row;
          if(!item.sending&&!item.unmatched&&elapsed<60000)next=Math.min(next,60000-elapsed);
        }
        paintSubmissionExpansion();
        if(Number.isFinite(next))submissionTimer=setTimeout(()=>renderSubmissions(),Math.max(1,next));
      };
      if(preserve)changeTail(paint);else paint();
    }
    function clearSubmissions(){
      submissions=[];sending.clear();observedIds.clear();matchedSubmissions.clear();clearTimeout(submissionTimer);clearTimeout(flashTimer);
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
      renderSubmissions({preserve:false});
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
      paintControls();onState();
    }
    function paintControls(){
      toggle.setAttribute('aria-pressed',String(opened));
      toggle.title=opened?'Close Reader':'Reader';toggle.setAttribute('aria-label',toggle.title);
      expandButton.hidden=!opened||!presented;
      expandButton.setAttribute('aria-pressed',String(fullWidth));
      expandButton.title=fullWidth?'Restore side panel':'Full width';expandButton.setAttribute('aria-label',expandButton.title);
      paintStatus();
      paintActivity();
    }
    const preview=root.OrreryConversationPreview?.mount({host:el('.conversation-preview'),source,onBeforeOpen:layoutChanged,onClose:layoutChanged,onActivate:()=>expand(true)});
    const stopPathLinks=root.OrreryConversationMarkdown?.observePaths?.(panel,source);
    let enabled=false,opened=false,agent='',generation=0,controller=null,timer=0,busy=false,sessionReloadAttempted=false;
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
      el('.conversation-bottom').hidden=!events.size||atBottom&&!paused;
      latest.title=paused?'Latest · resume':newCount?'Latest · '+newCount+' new messages':'Latest';
      latest.setAttribute('aria-label',latest.title);
      paintStatus();
    }
    function paintStatus(){
      const focused=document.activeElement;
      toolbar.hidden=!status.textContent&&retry.hidden;
      modeInfo.hidden=!opened||!modeInfo.title;
      notices.hidden=!presented||!opened&&!noticeTemporary||toolbar.hidden&&modeInfo.hidden;
      if(!presented){closeNotice();notices.remove();return;}
      if(noticeControl.parentElement&&(notices.parentElement!==noticeControl.parentElement||notices.nextElementSibling!==noticeControl))noticeControl.before(notices);
      const full=[...new Set([noticeOverlay?.text,noticeState.text,modeInfo.title].filter(Boolean))].join('\n\n');
      noticeToggle.title=full;noticeToggle.setAttribute('aria-label',full+(retry.hidden?'':' · Retry available'));
      menuCopy.textContent=full;
      if(focused===menuRetry&&retry.hidden&&opened)scroll.focus({preventScroll:true});
      menuRetry.hidden=retry.hidden;
      if(!noticeMenu.hidden&&(notices.hidden||!menuAnchor?.getClientRects().length))closeNotice({focus:true});
      if([modeInfo,noticeToggle].includes(focused)&&!focused.getClientRects().length&&opened){
        (noticeToggle.getClientRects().length?noticeToggle:scroll).focus({preventScroll:true});
      }
    }
    function closeNotice({focus=false}={}){
      if(noticeMenu.hidden)return;
      const owned=noticeMenu.contains(document.activeElement),anchor=menuAnchor;
      noticeMenu.hidden=true;menuAnchor=null;
      if(closeActiveNotice===closeNotice)closeActiveNotice=null;
      for(const button of [noticeToggle,modeInfo])button.setAttribute('aria-expanded','false');
      const target=[anchor,noticeToggle,modeInfo,scroll].find(e=>e?.getClientRects().length)||scroll;
      // A parked reader cannot focus yet. Retain a reader target rather than
      // its hidden menu control so relocate can restore it once visible.
      if(owned||noticeMenu.contains(lastFocused))lastFocused=target;
      if((focus||owned)&&opened&&presented)target.focus({preventScroll:true});
    }
    function openNotice(anchor){
      if(!noticeMenu.hidden){closeNotice({focus:true});return;}
      if(closeActiveNotice&&closeActiveNotice!==closeNotice)closeActiveNotice();
      closeActiveNotice=closeNotice;
      menuAnchor=anchor;noticeMenu.hidden=false;anchor.setAttribute('aria-expanded','true');
      const r=anchor.getBoundingClientRect(),box=noticeMenu.getBoundingClientRect();
      noticeMenu.style.left=Math.max(8,Math.min(r.right-box.width,root.innerWidth-box.width-8))+'px';
      noticeMenu.style.top=Math.max(8,Math.min(r.bottom+6,root.innerHeight-box.height-8))+'px';
      (menuRetry.hidden?noticeMenu:menuRetry).focus({preventScroll:true});
    }
    function paintMessage(){
      const value=noticeOverlay||noticeState;noticeTemporary=Boolean(noticeOverlay);
      status.textContent=value.text;status.title=value.text;toolbar.title=value.text;statusLabel.textContent=value.label;paintStatus();
    }
    function endTemporary(){clearTimeout(noticeTimer);noticeTimer=0;noticeOverlay=null;paintMessage();}
    function message(text,label=text,temporary=false){
      if(temporary){clearTimeout(noticeTimer);noticeOverlay={text,label};noticeTimer=setTimeout(endTemporary,5000);}
      else noticeState={text,label};
      paintMessage();
    }
    function modeMessage(text){if(!text&&document.activeElement===modeInfo&&opened)scroll.focus({preventScroll:true});modeInfo.title=text;modeInfo.setAttribute('aria-label',text);paintStatus();}
    function stop(keepFollow=false){clearTimeout(timer);clearTimeout(jumpTimer);timer=jumpTimer=0;sessionReloadAttempted=false;endTemporary();if(controller)controller.abort();controller=null;generation++;busy=false;if(pendingAction){endOp(pendingAction.op);pendingAction=null;}if(!keepFollow)followPending=false;}
    function clear({keepSubmissions=false}={}){closeNotice();noticeState={text:'',label:''};endTemporary();tablePositions.clear();toolGroups=[];toolGroupFor.clear();if(!keepSubmissions)clearSubmissions();lastPosition=null;clearTimeout(jumpTimer);jumpTimer=0;preview?.close();preview?.resetInline();events.clear();keepReaderFocus(eventsEl);eventsEl.replaceChildren();before=after=null;hasOlder=false;newCount=0;mode='';modeMessage('');paused=false;followPending=false;retainedBytes=0;earlier.hidden=true;retry.hidden=true;empty.hidden=false;empty.textContent='Loading conversation…';position();}
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
    // Keep message nodes in place so selections and previews survive polling.
    const rawRows=()=>[...eventsEl.children].filter(child=>child.dataset.eventId!==undefined);
    const visibleRows=()=>[...eventsEl.children,...pendingEl.children,activityEl].filter(child=>!child.hidden);
    const rowKey=child=>JSON.stringify(child.dataset.inlineFor?['images',child.dataset.inlineFor]:child.dataset.toolGroup?['tools',child.dataset.toolGroup]:child.dataset.receiptKey?['receipt',child.dataset.receiptKey]:child===activityEl?['activity']:['event',child.dataset.eventId]);
    function setGroupOpen(group,open){
      saveTables();const top=group.button.getBoundingClientRect().top;
      group.open=open;group.button.setAttribute('aria-expanded',String(open));
      for(const row of group.rows){if(!open)keepReaderFocus(row);row.hidden=!open;}
      restoreTables();scroll.scrollTop+=group.button.getBoundingClientRect().top-top;
      position();remember(true);
    }
    function regroupTools(focused=toolGroups.find(group=>group.button===document.activeElement)){
      const previous=toolGroups,used=new Set(),groups=[];let run=[];
      const finish=()=>{
        if(!run.length)return;
        const matches=[...new Set(run.map(row=>toolGroupFor.get(row.dataset.eventId)).filter(Boolean))];
        let group=matches.find(value=>value===focused&&!used.has(value))||matches.find(value=>!used.has(value));
        const open=matches.some(value=>value.open);
        if(!group){
          const button=document.createElement('button');button.type='button';button.className='conversation-tool-group';
          button.dataset.toolGroup=String(++toolSerial);
          button.innerHTML='<span class="conversation-tool-arrow" aria-hidden="true">▸</span><span class="conversation-tool-count"></span><span class="conversation-tool-names"></span><span class="conversation-tool-times"></span>';
          group={button,open:false,rows:[]};
          button.addEventListener('click',()=>{clearTimeout(jumpTimer);setGroupOpen(group,!group.open);});
        }
        used.add(group);group.rows=run;group.open=open;
        const calls=run.map(row=>events.get(row.dataset.eventId)).filter(event=>event.kind==='tool');
        const counts=new Map();for(const event of calls)counts.set(event.text,(counts.get(event.text)||0)+1);
        const names=[...counts].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).map(([name,count])=>(name||'Tool')+' ×'+count).join(', ');
        const count=calls.length||run.length,label=count+' '+(calls.length?'tool call':'tool result')+(count===1?'':'s');
        const dates=run.map(row=>new Date(events.get(row.dataset.eventId).ts)).filter(date=>Number.isFinite(date.getTime()));
        const time=date=>date.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
        const times=dates.length?time(dates[0])+(dates.length>1?'–'+time(dates[dates.length-1]):''):'';
        const full=label+(names?' · '+names:'')+(dates.length?' · '+dates[0].toLocaleString()+(dates.length>1?' – '+dates[dates.length-1].toLocaleString():''):'');
        const button=group.button;button.title=full;button.setAttribute('aria-label',full);button.setAttribute('aria-expanded',String(open));
        button.querySelector('.conversation-tool-count').textContent=label;
        button.querySelector('.conversation-tool-names').textContent=names?'· '+names:'';
        button.querySelector('.conversation-tool-times').textContent=times;
        if(button.nextElementSibling!==run[0])run[0].before(button);
        for(const row of run)row.hidden=!open;
        groups.push(group);run=[];
      };
      for(const row of rawRows()){
        const event=events.get(row.dataset.eventId);
        if(event&&['tool','tool_result'].includes(event.kind)&&!event.mail?.length)run.push(row);
        else{finish();row.hidden=false;}
      }
      finish();
      for(const group of previous)if(!used.has(group)){keepReaderFocus(group.button);group.button.remove();}
      toolGroups=groups;toolGroupFor.clear();
      for(const group of groups)for(const row of group.rows)toolGroupFor.set(row.dataset.eventId,group);
      // Keep native IDs and nodes as siblings for cursors and reading anchors,
      // while adjacent shell records share one visible heading and boundary.
      let shellStart=null;
      for(const row of rawRows()){
        row.classList.remove('conversation-shell-start','conversation-shell-continuation');
        const event=events.get(row.dataset.eventId),record=event?.role==='user'&&event.kind==='text'?root.OrreryConversationMarkdown?.commandRecord(event.text):null;
        if(!record?.shell){shellStart=null;continue;}
        if(record.command!==null)shellStart=row;
        else if(shellStart){shellStart.classList.add('conversation-shell-start');row.classList.add('conversation-shell-continuation');}
      }
      if(focused&&(document.activeElement===document.body||document.activeElement===scroll))(groups.includes(focused)?focused.button:scroll).focus({preventScroll:true});
      preview?.syncInline(rawRows(),events);
    }
    function anchor(){
      const top=scroll.getBoundingClientRect().top;
      const rows=visibleRows(),index=rows.findIndex(child=>child.getBoundingClientRect().bottom>top),first=rows[index],next=rows[index+1];
      return first?{id:rowKey(first),offset:first.getBoundingClientRect().top-top,
        next:next?{id:rowKey(next),offset:next.getBoundingClientRect().top-top}:null}:null;
    }
    function restoreAnchor(saved,fallback){
      let target=saved&&visibleRows().find(child=>rowKey(child)===saved.id),offset=saved?.offset;
      // Rewrapping can make the former tail offset longer than the whole
      // event. Keep its next visible boundary instead of skipping past it.
      if(target&&offset<0&&-offset>=target.getBoundingClientRect().height&&saved.next){
        const next=visibleRows().find(child=>rowKey(child)===saved.next.id);
        if(next){target=next;offset=saved.next.offset;}
      }
      if(target)scroll.scrollTop+=target.getBoundingClientRect().top-scroll.getBoundingClientRect().top-offset;
      else scroll.scrollTop=fallback;
    }
    function textNodes(article){
      const walker=document.createTreeWalker(article,NodeFilter.SHOW_TEXT),nodes=[];
      while(walker.nextNode())if(!walker.currentNode.parentElement?.closest('.conversation-code-head'))nodes.push(walker.currentNode);return nodes;
    }
    function remember(force=false){
      if(!opened||!presented||!panel.isConnected||!scroll.getClientRects().length)return;
      const rect=screen.getBoundingClientRect();
      if(!force&&(layoutPending||restoring||rect.width!==lastWidth||rect.height!==lastHeight))return;
      if(nearBottom()){lastPosition={bottom:true};return;}
      const bounds=scroll.getBoundingClientRect(),top=bounds.top;
      const article=visibleRows().find(child=>child.getBoundingClientRect().bottom>top+1);
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
      lastPosition={id:rowKey(article),offset,atTextEnd:local===node.length,top:r.top-top,bottom:false};
    }
    function restoreReading(){
      if(!opened||!presented||!lastPosition||!scroll.getClientRects().length)return;
      if(lastPosition.bottom){scroll.scrollTop=scroll.scrollHeight;return;}
      const article=visibleRows().find(child=>rowKey(child)===lastPosition.id);
      if(!article)return;
      let remaining=lastPosition.offset;
      for(const node of textNodes(article)){
        // Adjacent text nodes share a cumulative offset at their boundary.
        // Restore the same side: a body start must not become a label end.
        if(remaining>node.length||remaining===node.length&&!lastPosition.atTextEnd){remaining-=node.length;continue;}
        const range=document.createRange();range.setStart(node,remaining);range.setEnd(node,Math.min(remaining+1,node.length));
        const rect=range.getBoundingClientRect();if(rect.height)scroll.scrollTop+=rect.top-scroll.getBoundingClientRect().top-lastPosition.top;
        break;
      }
    }
    function layoutChanged(){
      if(!opened||!presented)return;
      root.OrreryConversationMail?.layout?.(panel);
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
    function relocate(target,{visible=true,suspend=true,focus=false,noticeAnchor=toggle}={}){
      noticeControl=noticeAnchor;
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
      preview?.setVisible(opened&&presented&&!document.hidden);
      paintControls();
      screen.classList.toggle('conversation-enabled',enabled);
      screen.classList.toggle('conversation-just-submitted',Boolean(flashTimer));
      screen.classList.toggle('conversation-open',opened&&presented);
      screen.classList.toggle('conversation-full',opened&&presented&&fullWidth);
      if(!presented||!opened)return;
      viewport();restoreTables();
      const rect=screen.getBoundingClientRect(),resized=rect.width!==lastWidth||rect.height!==lastHeight;
      if(changed||resized)layoutChanged();
      if(focus&&lastFocused&&(document.activeElement===document.body||noticeMenu.hidden&&noticeMenu.contains(document.activeElement))){
        lastFocused=[lastFocused,noticeToggle,modeInfo,scroll].find(e=>e?.isConnected&&e.getClientRects().length)||scroll;
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
        const child=rawRows().find(row=>row.dataset.eventId===id);
        if(child){keepReaderFocus(child);child.remove();}removed=true;
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
      if(event.kind==='system'){
        const toggle=document.createElement('button');toggle.type='button';toggle.className='conversation-system-toggle';toggle.setAttribute('aria-expanded','false');
        const arrow=document.createElement('span');arrow.className='conversation-tool-arrow';arrow.textContent='▸';arrow.setAttribute('aria-hidden','true');
        const label=document.createElement('span');label.textContent=event.text;toggle.append(arrow,label);
        const detail=document.createElement('div');detail.className='conversation-system-detail';detail.hidden=true;
        detail.id='conversation-system-'+(++toolSerial)+'-'+Math.random().toString(36).slice(2);toggle.setAttribute('aria-controls',detail.id);
        if(root.OrreryConversationMarkdown)root.OrreryConversationMarkdown.renderText(event.system_detail||event.text,detail);else detail.textContent=event.system_detail||event.text;
        toggle.addEventListener('click',()=>{if(!detail.hidden)keepReaderFocus(detail);detail.hidden=!detail.hidden;toggle.setAttribute('aria-expanded',String(!detail.hidden));});
        article.append(toggle,detail);return article;
      }
      if(event.kind==='mail'&&Array.isArray(event.mail)&&root.OrreryConversationMail)return root.OrreryConversationMail.render(event,article,{name:agent,renderPeerAvatar});
      const byline=document.createElement('div');byline.className='conversation-byline';
      const role=document.createElement('span');role.className='conversation-role';
      const shell=event.role==='user'&&root.OrreryConversationMarkdown?.commandRecord(event.text)?.shell;
      role.textContent=event.kind==='tool'?'Tool':event.kind==='tool_result'?'Tool result':shell?'Shell':event.role==='user'?'You':providerLabel;
      if(event.kind==='text'&&event.role==='assistant'&&root.OrreryConversationSpeaker){
        role.dataset.recordedModel=typeof event.model==='string'?event.model:'';
        root.OrreryConversationSpeaker.paint(role,{name:agent,model:role.dataset.recordedModel,harness:providerLabel,context:getContext()||{},renderAvatar});
      }
      byline.appendChild(role);
      if(['tool','tool_result'].includes(event.kind)){
        const tool=document.createElement('span');tool.className='conversation-tool-name';tool.textContent=event.text;byline.appendChild(tool);
      }
      const time=document.createElement('time');time.className='conversation-time';
      const date=new Date(event.ts);
      if(Number.isFinite(date.getTime())){time.dateTime=event.ts;time.textContent=date.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});time.title=date.toLocaleString();}
      byline.appendChild(time);article.appendChild(byline);
      if(!['tool','tool_result'].includes(event.kind)){
        const text=document.createElement('div');text.className='conversation-text';
        if(event.role==='assistant'&&root.OrreryConversationMarkdown){
          text.className+=' conversation-markdown';root.OrreryConversationMarkdown.renderDocument(event.text,text,{codeControls:true});
          // A single paragraph needs no block wrapper in a conversation row.
          if(text.childNodes.length===1&&text.firstChild.nodeName==='P')text.replaceChildren(...text.firstChild.childNodes);
        }
        else if(root.OrreryConversationMarkdown){if(!root.OrreryConversationMarkdown.renderCommand(event.text,text))root.OrreryConversationMarkdown.renderText(event.text,text);}
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
      if(Array.isArray(event.mail)&&root.OrreryConversationMail)root.OrreryConversationMail.render(event,article,{name:agent,renderPeerAvatar});
      return article;
    }
    function jump(event){
      const group=toolGroupFor.get(event.id);
      if(group&&!group.open){setGroupOpen(group,true);group.rows.find(row=>row.dataset.eventId===event.id)?.scrollIntoView({block:'nearest'});remember(true);}
      const result=fingerprint(getContext()||{})!==contextKey?{state:'changed'}:
        jumpToEvent({agent,event,context:boundContext})||{state:'changed'};
      if(result.state==='unique'){
        preview?.close();
        if(screen.getBoundingClientRect().width<800||root.innerWidth<=1200)close({focus:false});
        else expand(false);
        message('Matching message shown in this terminal.','Match shown',true);
      }else if(result.state==='limited')message('Terminal scrollback exceeds the search limit; cannot confirm a unique match. Keep reading history here.','Search limit',true);
      else if(result.state==='multiple')message('Same text found in '+result.count+(result.limited?' or more':'')+' places in the terminal. Keep reading history here.','Multiple matches',true);
      else if(result.state==='alternate')message('Earlier output of this screen is not kept in the terminal. Keep reading history here.','Output not retained',true);
      else if(result.state==='changed')message('Terminal changed. Search again.','Terminal changed',true);
      else message('Not found in terminal scrollback. Keep reading history here.','Not found',true);
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
    function plan(reloadDelay=null){
      if(!opened||!presented||!enabled||paused||busy||!agent||document.hidden){clearTimeout(timer);timer=0;return;}
      let delay=pollMs;
      if(opsActive()||last.failed)delay=pollMs;
      else if(last.catchUp&&last.slot)delay=0;
      else if(last.hold&&!last.refused&&waiting.size<MAX_WAITING)delay=last.rows>0?CONTENT_GAP_MS:0;
      if(reloadDelay!==null&&!opsActive())delay=reloadDelay;
      const due=performance.now()+delay;
      if(timer&&timerDue<=due)return;
      clearTimeout(timer);timerDue=due;timer=setTimeout(()=>{timer=0;load(after===null?'initial':'newer');},delay);
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
      let pollAgain=true,reloadDelay=null;
      if(document.activeElement===retry)scroll.focus({preventScroll:true});
      controller=new AbortController();busy=true;retry.hidden=true;paintStatus();
      const options={signal:controller.signal},mine=controller;
      if(direction==='older')options.before=before;
      if(direction==='newer')options.after=after;
      const holder={yield:()=>mine.abort()};
      // A hidden tab never asks to be held: it keeps no connection open.
      if(direction==='newer'&&after!==null&&!document.hidden&&!opsActive()&&waiting.size<MAX_WAITING){options.wait=WAIT_SECONDS;options.reader=readerId;waiting.add(holder);}
      holding=Boolean(options.wait);
      // Load earlier stays usable while the poll only waits in the background.
      earlier.disabled=!holding;paintStatus();
      if(direction!=='newer'||op){
        if(direction==='initial'&&!events.size)empty.hidden=true;
        message('');
      }
      try{
        const page=direction==='older'?await readOlder(name,options,token):await source.read(name,options);
        holding=false;waiting.delete(holder);
        if(page.hold===true)last.hold=true;
        last.slot=page.slot===true;last.refused=Boolean(options.wait)&&!last.slot;
        last.catchUp=page.has_newer===true&&direction!=='older';last.rows=0;last.failed=false;
        if(token!==generation||!opened||!enabled)return;
        sessionReloadAttempted=false;
        // The server saw no change since this cursor: keep every row as is.
        if(page.unchanged===true&&direction==='newer'&&page.after===after){message('');return;}
        const atBottom=nearBottom(),oldHeight=scroll.scrollHeight,oldTop=scroll.scrollTop,saved=anchor();
        const incoming=page.events.filter(event=>event&&typeof event.id==='string'&&typeof event.text==='string');
        for(const event of incoming)observedIds.add(event.id);
        mode=page.mode||'cursor';
        providerLabel=({codex:'Codex',claude:'Claude',dsh:'dsh',hermes:'Hermes'})[page.provider]||providerLabel;
        const fresh=['fresh_tail','snapshot'].includes(mode);
        const additions=incoming.filter(event=>!events.has(event.id));
        if(!fresh&&direction==='newer'&&!atBottom&&
          (events.size+additions.length>MAX_EVENTS||retainedBytes+additions.reduce((n,event)=>n+byteSize(event),0)>MAX_BYTES)){
          paused=true;message('Updates paused at reader limit. Scroll to the bottom or select Latest to resume.','Updates paused');position();return;
        }
        saveTables();tableMutating=true;
        const fragment=document.createDocumentFragment(),focusedGroup=toolGroups.find(group=>group.button===document.activeElement);let added=0;
        if(fresh){
          keepReaderFocus(eventsEl);
          const existing=new Map(rawRows().map(child=>[child.dataset.eventId,child]));
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
        regroupTools(focusedGroup);
        for(const key of tablePositions.keys())if(!events.has(JSON.parse(key)[0]))tablePositions.delete(key);
        restoreTables();
        reconcileSubmissions(incoming,direction,sequence);
        empty.hidden=events.size>0||submissions.length>0;empty.textContent='No conversation messages in this portion yet.';
        if(direction==='initial'||direction==='newer'&&atBottom)scroll.scrollTop=scroll.scrollHeight;
        else if(direction==='older')restoreAnchor(saved,Math.max(0,oldTop+scroll.scrollHeight-oldHeight));
        else{restoreAnchor(saved,oldTop);newCount+=added;}
        modeMessage(mode==='snapshot'?page.notice||'Recent provider snapshot.':
          fresh?(page.limited||trimmed?'Fresh · limited recent snapshot; earlier history and tools need telemetry support.':'Fresh · recent snapshot (up to 200 messages).'):
          page.notice||'');
        message(paused?'Reader window is bounded. Scroll to the bottom or select Latest to resume.':
          trimmed&&!fresh?'Older loaded messages were released. Load earlier to read them again.':
          page.skipped_large_record?'A large record was skipped. Load earlier to continue.':'',
          paused?'Updates paused':trimmed&&!fresh?'Older released':page.skipped_large_record?'Record skipped':'');
        position();if(direction==='initial'||direction==='newer'&&atBottom)remember(true);
        if(direction!=='older')last.rows=added;
      }catch(error){
        waiting.delete(holder);holding=false;
        if(token!==generation||error.name==='AbortError')return;
        last.failed=true;
        if(error.code==='history_changed'){
          // One short retry for a changed binding; repeated changes use the
          // normal poll interval instead of spinning on an unsettled session.
          clear();empty.textContent='New session';message('New session','New session',true);
          if(pendingAction){endOp(pendingAction.op);pendingAction=null;}
          if(!sessionReloadAttempted){sessionReloadAttempted=true;reloadDelay=250;}
          position();
        }else{
          pollAgain=!['record_too_large','provider_unavailable','claude_next_phase','dashboard_upgrade_required','dsh_decoder_unavailable','history_format_unsupported'].includes(error.code);
          retry.hidden=false;message(error.message,'Read failed');
          if(BINDING_ERRORS.includes(error.code)){
            // Never retain content from a stale, unbound or different native session.
            clear({keepSubmissions:error.code==='history_pending'});retry.hidden=false;empty.hidden=false;
            empty.textContent=error.message;
            message(error.message,'Read failed');
            position();
          }
        }
        paintStatus();
      }finally{
        if(token===generation){
          busy=false;controller=null;earlier.disabled=false;paintStatus();
          if(followPending){followPending=false;followSubmitted();}
          else if(pendingAction){const next=pendingAction;pendingAction=null;load(next.direction,next.op);}
          else if(pollAgain)plan(reloadDelay);
        }
        endOp(op);
      }
    }
    function context(){
      const current=getContext()||{};const name=String(current.name||''),key=fingerprint(current);
      if(!opened)return;
      root.OrreryConversationMail?.refreshPeers?.(panel,renderPeerAvatar);
      for(const heading of panel.querySelectorAll('.conversation-speaker'))root.OrreryConversationSpeaker?.paint(heading,
        {name:agent,model:heading.dataset.recordedModel,harness:heading.dataset.harness,context:current,renderAvatar});
      if(name===agent&&key===contextKey){paintActivity(current);return;}
      const sameBinding=key===contextKey;
      stop();agent=name;contextKey=key;clear({keepSubmissions:sameBinding});boundContext={...current};
      paintActivity(current);
      panel.setAttribute('aria-label',agent?'Reader for '+agent:'Reader');message('');
      if(!agent){empty.textContent='Select an agent pane to read its conversation.';message('No agent selected');return;}
      providerLabel=({'claude-code':'Claude',claude:'Claude',dsh:'dsh',hermes:'Hermes'})[current.program]||'Codex';
      load();
    }
    function close({focus=true}={}){
      if(!opened)return;
      stop();opened=false;agent='';panel.hidden=true;preview?.setVisible(false);screen.classList.remove('conversation-open','conversation-full');
      screen.style.removeProperty('--conversation-viewport-height');screen.style.removeProperty('--conversation-viewport-top');
      toggle.setAttribute('aria-expanded','false');paintControls();clear({keepSubmissions:true});onState();const target=typeof focusControl==='function'?focusControl():focusControl||toggle;
      if(focus&&target&&!target.hidden&&target.getClientRects().length)target.focus();
    }
    function open(){
      if(!enabled)return;
      if(opened){onActivate();return;}
      onActivate();opened=true;panel.hidden=false;preview?.setVisible(presented&&!document.hidden);screen.classList.add('conversation-open');screen.classList.toggle('conversation-full',fullWidth);
      viewport();const rect=screen.getBoundingClientRect();lastWidth=rect.width;lastHeight=rect.height;
      toggle.setAttribute('aria-expanded','true');paintControls();agent=null;context();scroll.focus();onState();
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
    listen(expandButton,'click',event=>{event.stopPropagation();onActivate();if(fullWidth)preview?.close();expand(!fullWidth);});
    for(const type of ['pointerdown','mousedown'])listen(expandButton,type,event=>event.stopPropagation());
    listen(expandButton,'keydown',event=>{event.stopPropagation();if(event.key==='Escape'){event.preventDefault();close();}});
    listen(expandButton,'focus',()=>onActivate());
    listen(panel,'pointerdown',()=>onActivate());
    listen(panel,'focusin',event=>{lastFocused=event.target;onActivate();});
    listen(notices,'focusin',event=>{lastFocused=event.target;onActivate();});
    listen(noticeMenu,'focusin',event=>{lastFocused=event.target;onActivate();});
    for(const type of ['pointerdown','mousedown'])listen(notices,type,event=>event.stopPropagation());
    for(const type of ['pointerdown','mousedown'])listen(noticeMenu,type,event=>event.stopPropagation());
    listen(notices,'keydown',event=>{event.stopPropagation();if(event.key==='Escape'){event.preventDefault();close();}});
    listen(noticeMenu,'keydown',event=>{event.stopPropagation();if(event.key==='Escape'){event.preventDefault();closeNotice({focus:true});}});
    listen(document,'pointerdown',event=>{if(!noticeMenu.hidden&&!noticeMenu.contains(event.target)&&!notices.contains(event.target))closeNotice();},{capture:true});
    listen(document,'scroll',event=>{if(!noticeMenu.hidden&&!noticeMenu.contains(event.target))closeNotice();},{capture:true,passive:true});
    for(const button of [noticeToggle,modeInfo])listen(button,'click',event=>{event.stopPropagation();openNotice(button);});
    listen(menuRetry,'click',()=>{scroll.focus({preventScroll:true});closeNotice();userLoad(events.size?'newer':'initial');});
    listen(panel,'mousedown',event=>event.stopPropagation());
    listen(panel,'keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(preview?.selected){preview.close();scroll.focus();}else close();}});
    // Arrow/Page keys and wheels belong only to the browser scroll container;
    // there is no path from this module to xterm or tmux input.
    listen(earlier,'click',()=>{scroll.focus({preventScroll:true});userLoad('older');});
    listen(retry,'click',()=>{scroll.focus({preventScroll:true});userLoad(events.size?'newer':'initial');});
    function resumePaused(){
      if(!paused)return false;
      stop();clear({keepSubmissions:true});load('initial');
      return true;
    }
    listen(latest,'click',()=>{
      if(!resumePaused()){
        scroll.scrollTop=scroll.scrollHeight;newCount=0;position();remember(true);
        if(!busy)plan();
      }
      scroll.focus({preventScroll:true});
    });
    // Submission remains owned by the existing composer/input guards. This
    // notification adds an ephemeral delivery receipt, never a provider event.
    // Only a subsequent exact user record replaces it (FIFO for repeated text).
    function followSubmitted(){
      if(!resumePaused()){scroll.scrollTop=scroll.scrollHeight;newCount=0;position();remember(true);load('newer');}
    }
    listen(document,'oc:prompt-sending',event=>{
      const detail=event.detail;
      if(!opened||!enabled||detail?.name!==agent||typeof detail.attemptId!=='string'||typeof detail.text!=='string')return;
      sending.set(detail.attemptId,{id:detail.attemptId,attemptId:detail.attemptId,name:agent,sending:true,at:Number.isFinite(detail.startedAt)?detail.startedAt:Date.now(),preview:detail.text.slice(0,1000)+(detail.text.length>1000?'…':'')});
      renderSubmissions();empty.hidden=true;
    });
    listen(document,'oc:prompt-send-cancelled',event=>{if(sending.delete(event.detail?.attemptId))renderSubmissions();});
    listen(document,'oc:prompt-submitted',event=>{
      const detail=event.detail,attempt=detail?.attemptId;
      const pending=attempt&&sending.get(attempt);if(pending)sending.delete(attempt);
      if(!opened||!enabled||detail?.name!==agent||attempt&&!pending){if(pending)renderSubmissions();return;}
      if(typeof detail.text==='string'&&typeof detail.id==='string'&&!submissions.some(item=>item.id===detail.id)){
        const text=normalizePrompt(detail.text);
        submissions.push({id:detail.id,attemptId:pending?attempt:null,name:agent,at:Number.isFinite(detail.submittedAt)?detail.submittedAt:Date.now(),
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
    let previousScrollTop=scroll.scrollTop,previousScrollHeight=scroll.scrollHeight;
    listen(scroll,'scroll',()=>{
      const top=scroll.scrollTop,height=scroll.scrollHeight;
      // Collapsing content can clamp the viewport to the end without the
      // reader moving downward. Keep that retained window paused.
      const movedDown=top>previousScrollTop&&height>=previousScrollHeight;
      previousScrollTop=top;previousScrollHeight=height;
      if(!presented)return;
      position();
      if(userScrolling){
        remember();
        if(opened&&enabled&&paused&&movedDown&&nearBottom())resumePaused();
      }
    },{passive:true});
    listen(window,'resize',()=>{closeNotice({focus:true});paintStatus();layoutChanged();});
    const layoutObserver=new ResizeObserver(layoutChanged);
    layoutObserver.observe(panel);layoutObserver.observe(scroll);layoutObserver.observe(eventsEl);
    const submissionObserver=new ResizeObserver(paintSubmissionExpansion);submissionObserver.observe(pendingEl);
    listen(document,'oc:stage-agent',context);
    listen(document,'oc:focus-agent',context);
    listen(document,'oc:agents',context);
    // A hidden tab keeps no held poll: end one that is waiting, so its
    // browser connection and the server's slot are returned at once.
    listen(document,'visibilitychange',()=>{preview?.setVisible(opened&&presented&&!document.hidden);paintActivity();if(document.hidden){clearTimeout(timer);timer=0;if(holding)controller?.abort();}else if(opened){if(events.size)plan();else load('initial');}});
    preference();paintControls();
    return Object.freeze({open,close,relocate,reconcile:context,get opened(){return opened;},get panel(){return panel;},refresh:()=>load(events.size?'newer':'initial'),
      dispose(){stopPathLinks?.();ops.planners.delete(plan);cancelAnimationFrame(tableFrame);layoutObserver.disconnect();submissionObserver.disconnect();clearTimeout(layoutTimer);cancelAnimationFrame(layoutFrame);close({focus:false});preview?.dispose();clearSubmissions();stop();listeners.forEach(remove=>remove());panel.remove();notices.remove();noticeMenu.remove();expandButton.remove();screen.classList.remove('conversation-enabled','conversation-full');}});
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
      toggle.setAttribute('aria-pressed',String(Boolean(view?.opened)));
      toggle.title=view?.opened?'Close Reader':'Reader';toggle.setAttribute('aria-label',toggle.title);
      toggle.setAttribute('aria-controls',view?.panel.id||'conversationPanel');
    }
    function create(name,owner){
      const park=document.createElement('div'),control=document.createElement('button'),expandControl=document.createElement('button');
      control.type='button';control.className='cockpit-control pane-icon split-history-toggle';
      control.innerHTML=readerIcon;
      control.title='Reader';control.setAttribute('aria-label','Reader');control.setAttribute('aria-expanded','false');
      const id='conversationPanel-'+(++sequence);control.setAttribute('aria-controls',id);park.append(control,expandControl);
      control.addEventListener('mousedown',event=>event.stopPropagation());control.addEventListener('pointerdown',event=>event.stopPropagation());
      const view=mount({...options,host:park,control,expandControl,panelId:id,getContext:()=>getContext(name),
        focusControl:()=>control.getClientRects().length?control:toggle,
        onActivate:()=>{if((getContext()||{}).name!==name)activate(name);},onState:paint});
      view.relocate(park,{visible:false});
      const entry={name,owner,view,park,host:park,control,expandControl,visible:false};views.set(name,entry);return entry;
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
          if(entry.expandControl.parentElement!==entry.park)entry.park.appendChild(entry.expandControl);
          entry.host=entry.park;entry.visible=false;
        }
        screen.classList.toggle('conversation-enabled',active);
        for(const [name,target] of targets){
          const entry=views.get(name);if(!entry)continue;
          if(target.host!==screen){
            target.host.classList.add('conversation-cell');const controls=target.controlHost||target.host;
            if(entry.control.parentElement!==controls)controls.insertBefore(entry.control,controls.firstChild);
          }
          if(target.host===screen||!screen.classList.contains('split-pane-headers'))toggle.after(entry.expandControl);
          else entry.control.after(entry.expandControl);
          entry.view.relocate(target.host,{visible:true,focus:name===selected,noticeAnchor:target.host===screen||!screen.classList.contains('split-pane-headers')?toggle:entry.control});entry.host=target.host;entry.visible=true;
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
