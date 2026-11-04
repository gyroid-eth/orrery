/* Presentation only: source.read is replaceable for another provider/layout.
   This view renders inert text. Future file/preview navigation belongs in an
   explicit renderer/activation adapter, never arbitrary HTML or browser paths. */
(function(root){
  'use strict';
  const KEY='oc-term-conversation-enabled';
  const MAX_EVENTS=400,MAX_BYTES=2*1024*1024;
  function mount({getContext,source=new root.OrreryConversationSource.Source(),pollMs=4000,renderEvent=null}){
    const screen=document.querySelector('.screen'),toggle=document.getElementById('conversationToggle');
    const setting=document.getElementById('conversationEnabled');
    const panel=document.createElement('section');
    panel.className='conversation-panel';panel.id='conversationPanel';panel.hidden=true;
    panel.setAttribute('aria-label','Read-only conversation history');
    panel.innerHTML='<div class="conversation-head"><div class="conversation-heading">'+
      '<h2 class="conversation-title">Conversation</h2><div class="conversation-subtitle"></div></div>'+
      '<button class="conversation-action conversation-expand" type="button" aria-pressed="false">↔ Full width</button>'+
      '<button class="conversation-action conversation-close" type="button" aria-label="Close conversation history">× Close</button></div>'+
      '<div class="conversation-toolbar"><span class="conversation-status" role="status"></span>'+
      '<button class="conversation-action conversation-retry" type="button" hidden>Retry</button></div>'+
      '<div class="conversation-body"><div class="conversation-thread"><div class="conversation-scroll" tabindex="0" aria-label="Conversation messages">'+
      '<button class="conversation-action conversation-older" type="button" hidden>↑ Load earlier</button>'+
      '<div class="conversation-events"></div><div class="conversation-empty"></div></div>'+
      '<div class="conversation-bottom"><span class="conversation-status conversation-position"></span>'+
      '<button class="conversation-action conversation-latest" type="button">↓ Latest</button></div></div>'+
      '<aside class="conversation-preview" aria-label="Selected file preview" hidden></aside></div>';
    screen.appendChild(panel);
    const el=selector=>panel.querySelector(selector);
    const scroll=el('.conversation-scroll'),eventsEl=el('.conversation-events');
    const status=el('.conversation-toolbar .conversation-status'),empty=el('.conversation-empty');
    const earlier=el('.conversation-older'),retry=el('.conversation-retry'),latest=el('.conversation-latest');
    let fullWidth=false;
    function viewport(){
      if(!opened||!enabled)return;
      const view=root.visualViewport;
      screen.style.setProperty('--conversation-viewport-height',(view?view.height:root.innerHeight)+'px');
      screen.style.setProperty('--conversation-viewport-top',(view?view.offsetTop:0)+'px');
    }
    root.visualViewport?.addEventListener('resize',viewport);
    root.visualViewport?.addEventListener('scroll',viewport);
    function expand(value){
      fullWidth=value;screen.classList.toggle('conversation-full',value);
      el('.conversation-expand').setAttribute('aria-pressed',String(value));
      el('.conversation-expand').textContent=value?'↙ Side panel':'↔ Full width';
    }
    const preview=root.OrreryConversationPreview?.mount({host:el('.conversation-preview'),source,onActivate:()=>expand(true)});
    let enabled=false,opened=false,agent='',generation=0,controller=null,timer=0,busy=false;
    let before=null,after=null,hasOlder=false,mode='',newCount=0,events=new Map();
    let contextKey='',paused=false,retainedBytes=0;
    const byteSize=event=>new TextEncoder().encode(JSON.stringify(event)).byteLength;
    const fingerprint=current=>JSON.stringify(['name','program','provider','history_binding','transcript_path',
      'native_session_id','created','mail_instance_id','mail_agent_id'].map(key=>current[key]??null));
    function nearBottom(){return scroll.scrollHeight-scroll.clientHeight-scroll.scrollTop<45;}
    function position(){
      const atBottom=nearBottom();
      if(atBottom)newCount=0;
      el('.conversation-position').textContent=events.size+' loaded · '+(mode==='fresh_tail'?'recent window':'loaded portion');
      latest.textContent=paused?'↓ Latest · resume':newCount?'↓ '+newCount+' new':'↓ Latest';
    }
    function message(text){status.textContent=text;}
    function stop(){clearTimeout(timer);timer=0;if(controller)controller.abort();controller=null;generation++;busy=false;}
    function clear(){preview?.close();events.clear();eventsEl.replaceChildren();before=after=null;hasOlder=false;newCount=0;mode='';paused=false;retainedBytes=0;earlier.hidden=true;retry.hidden=true;empty.hidden=false;empty.textContent='Loading conversation…';position();}
    function draw(event){const article=renderEvent?renderEvent(event,node):node(event);return preview?preview.render(event,article):article;}
    function anchor(){
      const top=scroll.getBoundingClientRect().top;
      const first=[...eventsEl.children].find(child=>child.getBoundingClientRect().bottom>top);
      return first?{id:first.dataset.eventId,offset:first.getBoundingClientRect().top-top}:null;
    }
    function restoreAnchor(saved,fallback){
      const target=saved&&[...eventsEl.children].find(child=>child.dataset.eventId===saved.id);
      if(target)scroll.scrollTop+=target.getBoundingClientRect().top-scroll.getBoundingClientRect().top-saved.offset;
      else scroll.scrollTop=fallback;
    }
    function trim(fromStart){
      let removed=false;
      while(events.size>MAX_EVENTS||retainedBytes>MAX_BYTES){
        const ids=[...events.keys()],id=fromStart?ids[0]:ids[ids.length-1];
        retainedBytes-=byteSize(events.get(id));events.delete(id);
        const child=fromStart?eventsEl.firstElementChild:eventsEl.lastElementChild;
        if(child)child.remove();removed=true;
      }
      if(removed&&mode!=='fresh_tail'){
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
      const byline=document.createElement('div');byline.className='conversation-byline';
      const role=document.createElement('span');role.className='conversation-role';
      role.textContent=event.kind==='tool'?'Tool':event.role==='user'?'You':'Codex';byline.appendChild(role);
      if(event.kind==='tool'){
        const tool=document.createElement('span');tool.className='conversation-tool-name';tool.textContent=event.text;byline.appendChild(tool);
      }
      const time=document.createElement('time');time.className='conversation-time';
      const date=new Date(event.ts);
      if(Number.isFinite(date.getTime())){time.dateTime=event.ts;time.textContent=date.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});time.title=date.toLocaleString();}
      byline.appendChild(time);article.appendChild(byline);
      if(event.kind!=='tool'){
        const text=document.createElement('p');text.className='conversation-text';text.textContent=event.text;article.appendChild(text);
      }
      if(event.truncated){const note=document.createElement('div');note.className='conversation-truncated';note.textContent='Long message shortened in this reader.';article.appendChild(note);}
      return article;
    }
    function schedule(){
      clearTimeout(timer);
      if(opened&&enabled&&!paused&&!document.hidden)timer=setTimeout(()=>load('newer'),pollMs);
    }
    async function load(direction='initial'){
      if(!opened||!enabled||busy||!agent||paused&&direction==='newer')return;
      const token=generation,name=agent;
      let pollAgain=true;
      controller=new AbortController();busy=true;earlier.disabled=true;retry.hidden=true;
      const options={signal:controller.signal};
      if(direction==='older')options.before=before;
      if(direction==='newer')options.after=after;
      try{
        const page=await source.read(name,options);
        if(token!==generation||!opened||!enabled)return;
        const atBottom=nearBottom(),oldHeight=scroll.scrollHeight,oldTop=scroll.scrollTop,saved=anchor();
        const incoming=page.events.filter(event=>event&&typeof event.id==='string'&&typeof event.text==='string');
        mode=page.mode||'cursor';
        const fresh=mode==='fresh_tail';
        const additions=incoming.filter(event=>!events.has(event.id));
        if(!fresh&&direction==='newer'&&!atBottom&&
          (events.size+additions.length>MAX_EVENTS||retainedBytes+additions.reduce((n,event)=>n+byteSize(event),0)>MAX_BYTES)){
          paused=true;message('Updates paused at reader limit. Latest resumes at the newest messages.');position();return;
        }
        const fragment=document.createDocumentFragment();let added=0;
        if(fresh){
          const existing=new Map([...eventsEl.children].map(child=>[child.dataset.eventId,child]));
          const previous=events;
          events=new Map();retainedBytes=0;
          for(const event of incoming.slice(-200)){
            if(events.has(event.id))continue;
            events.set(event.id,event);retainedBytes+=byteSize(event);
            fragment.appendChild(existing.get(event.id)||draw(event));if(!previous.has(event.id))added++;
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
        empty.hidden=events.size>0;empty.textContent='No conversation messages in this portion yet.';
        if(direction==='initial'||direction==='newer'&&atBottom)scroll.scrollTop=scroll.scrollHeight;
        else if(direction==='older')restoreAnchor(saved,Math.max(0,oldTop+scroll.scrollHeight-oldHeight));
        else{restoreAnchor(saved,oldTop);newCount+=added;}
        message(paused?'Reader window is bounded. Latest resumes at the newest messages.':
          fresh?(page.limited||trimmed?'Fresh · limited recent snapshot; earlier history and tools need telemetry support.':'Fresh · recent snapshot (up to 200 messages).'):
          trimmed?'Older loaded messages were released. Load earlier to read them again.':
          page.skipped_large_record?'A large record was skipped. Load earlier to continue.':'Read-only · updates while open');
        position();
        if(page.has_newer&&direction!=='older'){
          // A bounded page per request. Continue in the next poll without
          // sending overlapping reads during a fast provider burst.
          message('Read-only · catching up with new messages…');
        }
      }catch(error){
        if(token!==generation||error.name==='AbortError')return;
        pollAgain=!['history_changed','record_too_large','provider_unavailable','claude_next_phase'].includes(error.code);
        message(error.message);retry.hidden=false;
        if(!events.size){empty.hidden=false;empty.textContent=error.code==='claude_next_phase'?
          'Claude Code support comes in the next phase. Codex history is available now.':'History is unavailable for this agent.';}
        if(['history_changed','history_unconfirmed','agent_unavailable','claude_next_phase','provider_unavailable'].includes(error.code)){
          // Never combine different provider sessions under one agent name.
          clear();retry.hidden=false;
          empty.hidden=false;empty.textContent='Session changed. Retry to load the current conversation.';position();
        }
      }finally{
        if(token===generation){busy=false;controller=null;earlier.disabled=false;if(pollAgain)schedule();}
      }
    }
    function context(){
      const current=getContext()||{};const name=String(current.name||''),key=fingerprint(current);
      if(!opened)return;
      if(name===agent&&key===contextKey)return;
      stop();agent=name;contextKey=key;clear();
      el('.conversation-subtitle').textContent=(agent||'No pane selected')+' · read-only';
      if(!agent){empty.textContent='Select an agent pane to read its conversation.';message('No agent selected');return;}
      if(/^claude/.test(current.program||'')){
        empty.textContent='Claude Code support comes in the next phase. Codex history is available now.';
        message('Claude Code · next phase');return;
      }
      load();
    }
    function close({focus=true}={}){
      if(!opened)return;
      stop();opened=false;agent='';panel.hidden=true;screen.classList.remove('conversation-open');
      screen.style.removeProperty('--conversation-viewport-height');screen.style.removeProperty('--conversation-viewport-top');
      toggle.setAttribute('aria-expanded','false');clear();if(focus&&!toggle.hidden)toggle.focus();
    }
    function open(){
      if(!enabled)return;
      opened=true;panel.hidden=false;screen.classList.add('conversation-open');
      viewport();
      toggle.setAttribute('aria-expanded','true');agent=null;context();scroll.focus();
    }
    function preference(){
      try{enabled=localStorage.getItem(KEY)==='1';}catch(_){enabled=false;}
      setting.checked=enabled;toggle.hidden=!enabled;
      screen.classList.toggle('conversation-enabled',enabled);
      if(!enabled)close({focus:false});
    }
    setting.addEventListener('change',()=>{try{localStorage.setItem(KEY,setting.checked?'1':'0');}catch(_){}preference();});
    document.addEventListener('oc:prefs-changed',preference);
    window.addEventListener('storage',event=>{if(event.key===KEY)preference();});
    toggle.addEventListener('click',()=>opened?close():open());
    el('.conversation-close').addEventListener('click',()=>close());
    el('.conversation-expand').addEventListener('click',()=>{if(fullWidth)preview?.close();expand(!fullWidth);});
    panel.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();if(preview?.selected){preview.close();scroll.focus();}else close();}});
    // Arrow/Page keys and wheels belong only to the browser scroll container;
    // there is no path from this module to xterm or tmux input.
    earlier.addEventListener('click',()=>load('older'));
    retry.addEventListener('click',()=>load(events.size?'newer':'initial'));
    latest.addEventListener('click',()=>{
      if(paused){stop();clear();load('initial');return;}
      scroll.scrollTop=scroll.scrollHeight;newCount=0;position();
    });
    scroll.addEventListener('scroll',position,{passive:true});
    document.addEventListener('oc:stage-agent',context);
    document.addEventListener('oc:focus-agent',context);
    document.addEventListener('oc:agents',context);
    document.addEventListener('visibilitychange',()=>{if(document.hidden)clearTimeout(timer);else if(opened)load(events.size?'newer':'initial');});
    preference();
    return Object.freeze({open,close,refresh:()=>load(events.size?'newer':'initial')});
  }
  root.OrreryConversation=Object.freeze({mount,KEY});
})(window);
